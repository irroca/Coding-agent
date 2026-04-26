"""OpenAI Chat Completions-compatible provider.

DeepSeek, Qwen (DashScope OpenAI mode), Moonshot Kimi and OpenAI itself all
expose the same wire format. The thin per-vendor adapters subclass this and
inject `default_base_url` / `default_model` / behavioural quirks (cache flag,
unsupported parameters, etc.).

Streaming protocol notes (the messy reality):
  * `tool_calls` deltas arrive **indexed by position**, NOT by id. The vendor
    only sends the `id` and `function.name` on the very first chunk for that
    index; subsequent chunks carry only `function.arguments` fragments. We
    keep an `index → (id, name, args_buffer)` map and synthesize the
    canonical START / DELTA / END events.
  * DeepSeek may send several "empty" deltas at the head of a turn before any
    content / tool_calls show up; we ignore those rather than emitting empty
    TEXT_DELTAs.
  * `finish_reason` arrives on the last chunk; usage may arrive separately
    (DeepSeek's `stream_options={"include_usage": True}` puts it on a final
    chunk with empty choices).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from coding_agent.core.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimitError,
)
from coding_agent.core.logging import get_logger
from coding_agent.core.types import (
    Message,
    Role,
    StreamEvent,
    StreamEventType,
    ToolCall,
    ToolSchema,
    Usage,
)
from coding_agent.providers.base import LLMProvider

log = get_logger("providers.openai_compat")


def messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate canonical messages to the OpenAI Chat Completions wire format.

    A canonical `tool` message can carry multiple `ToolResult`s; the wire format
    requires one message per result, hence the flatten step.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == Role.SYSTEM:
            out.append({"role": "system", "content": msg.content})
        elif msg.role == Role.USER:
            out.append({"role": "user", "content": msg.content})
        elif msg.role == Role.ASSISTANT:
            wire: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if msg.reasoning_content:
                wire["reasoning_content"] = msg.reasoning_content
            if msg.tool_calls:
                wire["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            out.append(wire)
        elif msg.role == Role.TOOL:
            for r in msg.tool_results:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": r.call_id,
                        "content": r.content,
                    }
                )
    return out


def tools_to_openai(tools: list[ToolSchema]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class _ToolCallAccumulator:
    """Aggregates streaming `tool_calls` deltas indexed by position."""

    __slots__ = ("by_index", "order")

    def __init__(self) -> None:
        self.by_index: dict[int, dict[str, Any]] = {}
        self.order: list[int] = []

    def feed(self, deltas: list[dict[str, Any]]) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for delta in deltas:
            idx = delta.get("index")
            if idx is None:
                continue
            entry = self.by_index.get(idx)
            if entry is None:
                entry = {"id": None, "name": None, "args": "", "started": False}
                self.by_index[idx] = entry
                self.order.append(idx)

            if delta.get("id") and entry["id"] is None:
                entry["id"] = delta["id"]

            fn = delta.get("function") or {}
            if fn.get("name") and entry["name"] is None:
                entry["name"] = fn["name"]

            if entry["id"] and entry["name"] and not entry["started"]:
                entry["started"] = True
                events.append(
                    StreamEvent(
                        type=StreamEventType.TOOL_USE_START,
                        tool_call_id=entry["id"],
                        tool_name=entry["name"],
                    )
                )

            arg_chunk = fn.get("arguments")
            if arg_chunk:
                entry["args"] += arg_chunk
                if entry["started"]:
                    events.append(
                        StreamEvent(
                            type=StreamEventType.TOOL_USE_DELTA,
                            tool_call_id=entry["id"],
                            arguments_delta=arg_chunk,
                        )
                    )
        return events

    def finalize(self) -> tuple[list[StreamEvent], list[ToolCall]]:
        """Emit TOOL_USE_END events and return the parsed ToolCalls."""
        events: list[StreamEvent] = []
        calls: list[ToolCall] = []
        for idx in self.order:
            entry = self.by_index[idx]
            if not entry["started"]:
                continue
            events.append(
                StreamEvent(
                    type=StreamEventType.TOOL_USE_END,
                    tool_call_id=entry["id"],
                )
            )
            try:
                args = json.loads(entry["args"]) if entry["args"] else {}
            except json.JSONDecodeError as e:
                raise ProviderProtocolError(
                    f"Tool call {entry['id']} ({entry['name']}) returned malformed JSON "
                    f"arguments: {e}. Raw: {entry['args']!r}"
                ) from e
            calls.append(ToolCall(id=entry["id"], name=entry["name"], arguments=args))
        return events, calls


def parse_sse_line(line: str) -> dict[str, Any] | None:
    """Parse one SSE `data: …` line. Returns None for empty / `[DONE]` markers."""
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        raise ProviderProtocolError(f"Malformed SSE payload: {payload!r}") from e


class OpenAICompatProvider(LLMProvider):
    """Shared implementation for OpenAI Chat Completions-compatible APIs."""

    name = "openai-compat"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"
    supports_stream_usage: ClassVar[bool] = True
    """Whether the vendor honors `stream_options={'include_usage': True}`."""

    extra_headers: ClassVar[dict[str, str]] = {}

    def __init__(self, config) -> None:  # type: ignore[no-untyped-def]
        super().__init__(config)
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url or self.default_base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                **self.extra_headers,
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _build_body(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        *,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages_to_openai(messages),
            "stream": True,
        }
        if tools:
            body["tools"] = tools_to_openai(tools)
            body["tool_choice"] = "auto"
        if temperature is not None:
            body["temperature"] = temperature
        body["max_tokens"] = max_tokens or self.max_output_tokens
        if self.supports_stream_usage:
            body["stream_options"] = {"include_usage": True}
        return body

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        body = self._build_body(
            messages, tools, temperature=temperature, max_tokens=max_tokens
        )
        log.debug(
            "provider_stream_request",
            provider=self.name,
            model=self.model,
            n_messages=len(messages),
            n_tools=len(tools),
        )

        retrying = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (ProviderRateLimitError, httpx.ConnectError, httpx.ReadTimeout)
            ),
            reraise=True,
        )

        # tenacity wraps the attempt; we must drive the streaming response from
        # the same coroutine that opened it, so we open and stream inline.
        async for attempt in retrying:
            with attempt:
                async with self._client.stream(
                    "POST", "/chat/completions", json=body
                ) as response:
                    if response.status_code == 401:
                        raise ProviderAuthError(
                            f"{self.name} rejected the API key (HTTP 401)."
                        )
                    if response.status_code == 429:
                        raise ProviderRateLimitError(
                            f"{self.name} rate-limited the request (HTTP 429)."
                        )
                    if response.status_code >= 400:
                        body_text = (await response.aread()).decode("utf-8", "replace")
                        raise ProviderError(
                            f"{self.name} HTTP {response.status_code}: {body_text[:500]}"
                        )

                    async for ev in self._consume_sse(response):
                        yield ev
                return

    async def _consume_sse(
        self, response: httpx.Response
    ) -> AsyncIterator[StreamEvent]:
        accumulator = _ToolCallAccumulator()
        finish_reason: str | None = None
        usage_seen = False

        async for raw_line in response.aiter_lines():
            if not raw_line:
                continue
            chunk = parse_sse_line(raw_line)
            if chunk is None:
                continue

            choices = chunk.get("choices") or []
            for choice in choices:
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield StreamEvent(type=StreamEventType.REASONING_DELTA, text=reasoning)
                text = delta.get("content")
                if text:
                    yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=text)

                if delta.get("tool_calls"):
                    for ev in accumulator.feed(delta["tool_calls"]):
                        yield ev

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

            usage = chunk.get("usage")
            if usage:
                usage_seen = True
                yield StreamEvent(
                    type=StreamEventType.USAGE,
                    usage=Usage(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        cached_prompt_tokens=(
                            usage.get("prompt_tokens_details", {}).get(
                                "cached_tokens", 0
                            )
                            if isinstance(usage.get("prompt_tokens_details"), dict)
                            else usage.get("prompt_cache_hit_tokens", 0)
                        ),
                    ),
                )

        end_events, _calls = accumulator.finalize()
        for ev in end_events:
            yield ev

        if not usage_seen:
            yield StreamEvent(type=StreamEventType.USAGE, usage=Usage())

        yield StreamEvent(
            type=StreamEventType.DONE,
            finish_reason=_normalize_finish_reason(finish_reason),
        )


def _normalize_finish_reason(reason: str | None):  # type: ignore[no-untyped-def]
    if reason in ("stop", "tool_calls", "length"):
        return reason
    if reason in ("end_turn", "complete"):
        return "stop"
    if reason in ("function_call",):
        return "tool_calls"
    return None
