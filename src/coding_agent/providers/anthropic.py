"""Anthropic Messages API adapter.

Anthropic's wire format differs from OpenAI's: messages have content blocks
(``text`` / ``tool_use`` / ``tool_result``) and the SSE protocol is event-typed
(``message_start`` / ``content_block_start`` / ``content_block_delta`` / ...).
We translate that into the same canonical ``StreamEvent`` stream so the agent
loop is unaware of the difference.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

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
    ToolSchema,
    Usage,
)
from coding_agent.providers.base import LLMProvider
from coding_agent.providers.openai_compat import parse_sse_line

log = get_logger("providers.anthropic")


def _split_system(messages: list[Message]) -> tuple[str | None, list[Message]]:
    """Anthropic takes ``system`` as a top-level string, not a chat message."""
    sys_chunks: list[str] = []
    rest: list[Message] = []
    for m in messages:
        if m.role == Role.SYSTEM:
            sys_chunks.append(m.content)
        else:
            rest.append(m)
    system = "\n\n".join(s for s in sys_chunks if s) or None
    return system, rest


def _messages_to_anthropic(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == Role.USER:
            out.append({"role": "user", "content": m.content})
        elif m.role == Role.ASSISTANT:
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif m.role == Role.TOOL:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content,
                            "is_error": not r.ok,
                        }
                        for r in m.tool_results
                    ],
                }
            )
    return out


def _tools_to_anthropic(
    tools: list[ToolSchema], *, cache_last: bool = False,
) -> list[dict[str, Any]]:
    """Convert canonical ToolSchemas to Anthropic's tool format.

    When ``cache_last`` is True the last tool gets a ``cache_control`` marker,
    which tells the server to cache everything up to and including the tools
    block. Anthropic caches inputs in declaration order, so a marker on the
    final tool covers ``system`` + all tools in one breakpoint.
    """
    out: list[dict[str, Any]] = []
    for i, t in enumerate(tools):
        entry: dict[str, Any] = {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        if cache_last and i == len(tools) - 1:
            entry["cache_control"] = {"type": "ephemeral"}
        out.append(entry)
    return out


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_base_url = "https://api.anthropic.com"
    default_model = "claude-sonnet-4-6"
    api_version = "2023-06-01"

    def __init__(self, config) -> None:  # type: ignore[no-untyped-def]
        super().__init__(config)
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url or self.default_base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": self.api_version,
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        system, rest = _split_system(messages)
        cache_enabled = self.config.supports_prompt_cache

        body: dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_anthropic(rest),
            "stream": True,
            "max_tokens": max_tokens or self.max_output_tokens,
        }
        if system:
            if cache_enabled:
                # Wrap the system prompt as a single text block with an
                # ephemeral cache marker. The marker covers the system block
                # and any preceding content (none here), giving us a stable
                # prefix that survives across turns.
                body["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                body["system"] = system
        if tools:
            body["tools"] = _tools_to_anthropic(tools, cache_last=cache_enabled)
        if temperature is not None:
            body["temperature"] = temperature

        retrying = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (ProviderRateLimitError, httpx.ConnectError, httpx.ReadTimeout)
            ),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                async with self._client.stream(
                    "POST", "/v1/messages", json=body
                ) as resp:
                    if resp.status_code == 401:
                        raise ProviderAuthError("Anthropic rejected the API key (401).")
                    if resp.status_code == 429:
                        raise ProviderRateLimitError("Anthropic rate-limited (429).")
                    if resp.status_code >= 400:
                        text = (await resp.aread()).decode("utf-8", "replace")
                        raise ProviderError(
                            f"Anthropic HTTP {resp.status_code}: {text[:500]}"
                        )
                    async for ev in self._consume_sse(resp):
                        yield ev
                return

    async def _consume_sse(self, resp: httpx.Response) -> AsyncIterator[StreamEvent]:
        # Anthropic emits event-typed SSE: an `event: <type>` line followed by
        # a `data: <json>` line. The event type lives outside the JSON, so we
        # remember it across the line pair.
        block_types: dict[int, str] = {}
        block_meta: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage = Usage()

        pending_event: str | None = None
        async for raw in resp.aiter_lines():
            if not raw:
                continue
            if raw.startswith("event:"):
                pending_event = raw[6:].strip()
                continue
            if not raw.startswith("data:"):
                continue
            chunk = parse_sse_line(raw)
            if chunk is None:
                pending_event = None
                continue
            etype = chunk.get("type") or pending_event
            pending_event = None

            if etype == "content_block_start":
                idx = chunk["index"]
                block = chunk.get("content_block") or {}
                btype = block.get("type")
                block_types[idx] = btype
                block_meta[idx] = {"args": ""}
                if btype == "tool_use":
                    block_meta[idx]["id"] = block["id"]
                    block_meta[idx]["name"] = block["name"]
                    yield StreamEvent(
                        type=StreamEventType.TOOL_USE_START,
                        tool_call_id=block["id"],
                        tool_name=block["name"],
                    )

            elif etype == "content_block_delta":
                idx = chunk["index"]
                delta = chunk.get("delta") or {}
                btype = block_types.get(idx)
                if btype == "text" and delta.get("type") == "text_delta":
                    yield StreamEvent(
                        type=StreamEventType.TEXT_DELTA, text=delta.get("text", "")
                    )
                elif btype == "tool_use" and delta.get("type") == "input_json_delta":
                    chunk_text = delta.get("partial_json", "")
                    block_meta[idx]["args"] += chunk_text
                    yield StreamEvent(
                        type=StreamEventType.TOOL_USE_DELTA,
                        tool_call_id=block_meta[idx]["id"],
                        arguments_delta=chunk_text,
                    )

            elif etype == "content_block_stop":
                idx = chunk["index"]
                if block_types.get(idx) == "tool_use":
                    meta = block_meta[idx]
                    yield StreamEvent(
                        type=StreamEventType.TOOL_USE_END,
                        tool_call_id=meta["id"],
                    )
                    if meta["args"]:
                        try:
                            json.loads(meta["args"])
                        except json.JSONDecodeError as e:
                            raise ProviderProtocolError(
                                f"Tool {meta['name']} returned malformed JSON: {e}"
                            ) from e

            elif etype == "message_delta":
                delta = chunk.get("delta") or {}
                if delta.get("stop_reason"):
                    finish_reason = delta["stop_reason"]
                u = chunk.get("usage")
                if u:
                    usage = _merge_anthropic_usage(usage, u)

            elif etype == "message_start":
                msg = chunk.get("message") or {}
                u = msg.get("usage") or {}
                usage = _merge_anthropic_usage(Usage(), u)

            elif etype == "message_stop":
                pass

        yield StreamEvent(type=StreamEventType.USAGE, usage=usage)
        yield StreamEvent(
            type=StreamEventType.DONE,
            finish_reason=_normalize_anthropic_finish(finish_reason),
        )


def _merge_anthropic_usage(prev: Usage, u: dict[str, Any]) -> Usage:
    """Normalize Anthropic usage payloads into our canonical Usage.

    Anthropic reports ``input_tokens``, ``cache_read_input_tokens``, and
    ``cache_creation_input_tokens`` as three disjoint counters. To stay
    consistent with OpenAI semantics (``prompt_tokens`` = full prompt size
    including cache reads), we sum them into ``prompt_tokens`` and keep the
    cache breakdown in dedicated fields.
    """
    cache_read = u.get("cache_read_input_tokens", prev.cached_prompt_tokens)
    cache_creation = u.get(
        "cache_creation_input_tokens", prev.cache_creation_tokens
    )
    input_tokens = u.get(
        "input_tokens",
        max(prev.prompt_tokens - prev.cached_prompt_tokens - prev.cache_creation_tokens, 0),
    )
    return Usage(
        prompt_tokens=input_tokens + cache_read + cache_creation,
        completion_tokens=u.get("output_tokens", prev.completion_tokens),
        cached_prompt_tokens=cache_read,
        cache_creation_tokens=cache_creation,
    )


def _normalize_anthropic_finish(reason: str | None):  # type: ignore[no-untyped-def]
    if reason in ("end_turn", "stop_sequence"):
        return "stop"
    if reason == "tool_use":
        return "tool_calls"
    if reason == "max_tokens":
        return "length"
    return None
