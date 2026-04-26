"""Test the OpenAI-compatible provider with mocked SSE streams.

We use respx to intercept httpx requests and feed canned SSE chunks. The point
is to lock down the contract: regardless of how DeepSeek or any other vendor
chunks the stream, the canonical StreamEvent sequence we emit upstream is
stable.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from coding_agent.core.config import ProviderConfig
from coding_agent.core.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimitError,
)
from coding_agent.core.types import (
    Message,
    Role,
    StreamEventType,
    ToolCall,
    ToolResult,
    ToolSchema,
)
from coding_agent.providers.openai_compat import (
    OpenAICompatProvider,
    _ToolCallAccumulator,
    messages_to_openai,
    parse_sse_line,
    tools_to_openai,
)


def _config() -> ProviderConfig:
    return ProviderConfig(
        api_key="sk-test",
        base_url="https://api.test.example",
        model="test-model",
        context_window=64_000,
        max_output_tokens=4_096,
    )


def _sse(*chunks: dict | str) -> str:
    """Build an SSE body from JSON chunks (dicts) or literal strings."""
    parts: list[str] = []
    for c in chunks:
        if isinstance(c, dict):
            parts.append(f"data: {json.dumps(c)}\n\n")
        else:
            parts.append(c)
    return "".join(parts)


def test_parse_sse_line_handles_done_and_empty() -> None:
    assert parse_sse_line("data: [DONE]") is None
    assert parse_sse_line("data: ") is None
    assert parse_sse_line(": comment") is None
    assert parse_sse_line("data: {\"x\":1}") == {"x": 1}


def test_parse_sse_line_rejects_garbage() -> None:
    with pytest.raises(ProviderProtocolError):
        parse_sse_line("data: not json")


def test_messages_to_openai_basic() -> None:
    msgs = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content="thinking",
            tool_calls=[ToolCall(id="c1", name="ls", arguments={"path": "."})],
        ),
        Message(
            role=Role.TOOL,
            tool_results=[
                ToolResult(call_id="c1", tool="ls", ok=True, content="a\nb"),
            ],
        ),
    ]
    out = messages_to_openai(msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "hi"}
    assert out[2]["role"] == "assistant"
    assert out[2]["tool_calls"][0]["function"]["name"] == "ls"
    assert json.loads(out[2]["tool_calls"][0]["function"]["arguments"]) == {"path": "."}
    assert out[3]["role"] == "tool"
    assert out[3]["tool_call_id"] == "c1"


def test_tools_to_openai_shape() -> None:
    schema = ToolSchema(
        name="ls",
        description="list",
        parameters={"type": "object", "properties": {}},
    )
    [wire] = tools_to_openai([schema])
    assert wire["type"] == "function"
    assert wire["function"]["name"] == "ls"


def test_tool_call_accumulator_combines_split_arguments() -> None:
    acc = _ToolCallAccumulator()
    events_a = acc.feed(
        [{"index": 0, "id": "tc-1", "function": {"name": "ls", "arguments": "{\"pa"}}]
    )
    events_b = acc.feed([{"index": 0, "function": {"arguments": "th\":\".\"}"}}])
    end_events, calls = acc.finalize()

    types_in_order = [e.type for e in events_a + events_b + end_events]
    assert types_in_order == [
        StreamEventType.TOOL_USE_START,
        StreamEventType.TOOL_USE_DELTA,
        StreamEventType.TOOL_USE_DELTA,
        StreamEventType.TOOL_USE_END,
    ]
    assert calls[0].id == "tc-1"
    assert calls[0].name == "ls"
    assert calls[0].arguments == {"path": "."}


def test_tool_call_accumulator_rejects_malformed_json() -> None:
    acc = _ToolCallAccumulator()
    acc.feed(
        [
            {
                "index": 0,
                "id": "tc-1",
                "function": {"name": "ls", "arguments": "{not-json"},
            }
        ]
    )
    with pytest.raises(ProviderProtocolError):
        acc.finalize()


@respx.mock
async def test_stream_text_only() -> None:
    body = _sse(
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5}, "choices": []},
        "data: [DONE]\n\n",
    )
    respx.post("https://api.test.example/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    provider = OpenAICompatProvider(_config())
    events = [e async for e in provider.stream([Message(role=Role.USER, content="hi")], [])]
    await provider.aclose()

    types = [e.type for e in events]
    assert StreamEventType.TEXT_DELTA in types
    text = "".join(e.text or "" for e in events if e.type == StreamEventType.TEXT_DELTA)
    assert text == "Hello"
    usage_event = next(e for e in events if e.type == StreamEventType.USAGE)
    assert usage_event.usage.prompt_tokens == 10
    done = events[-1]
    assert done.type == StreamEventType.DONE
    assert done.finish_reason == "stop"


@respx.mock
async def test_stream_tool_call_split_across_chunks() -> None:
    body = _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "bash", "arguments": "{\"comm"},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": "and\":\"ls\"}"}}
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"usage": {"prompt_tokens": 5, "completion_tokens": 2}, "choices": []},
        "data: [DONE]\n\n",
    )
    respx.post("https://api.test.example/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    provider = OpenAICompatProvider(_config())
    events = [e async for e in provider.stream([Message(role=Role.USER, content="run ls")], [])]
    await provider.aclose()

    starts = [e for e in events if e.type == StreamEventType.TOOL_USE_START]
    deltas = [e for e in events if e.type == StreamEventType.TOOL_USE_DELTA]
    ends = [e for e in events if e.type == StreamEventType.TOOL_USE_END]
    assert len(starts) == 1
    assert starts[0].tool_call_id == "call_1"
    assert starts[0].tool_name == "bash"
    assert "".join(e.arguments_delta for e in deltas) == '{"command":"ls"}'
    assert len(ends) == 1
    done = events[-1]
    assert done.finish_reason == "tool_calls"


@respx.mock
async def test_stream_parallel_tool_calls() -> None:
    body = _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {"name": "ls", "arguments": "{}"},
                            },
                            {
                                "index": 1,
                                "id": "c2",
                                "function": {"name": "pwd", "arguments": "{}"},
                            },
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        "data: [DONE]\n\n",
    )
    respx.post("https://api.test.example/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    provider = OpenAICompatProvider(_config())
    events = [e async for e in provider.stream([Message(role=Role.USER, content="x")], [])]
    await provider.aclose()
    starts = [e for e in events if e.type == StreamEventType.TOOL_USE_START]
    ends = [e for e in events if e.type == StreamEventType.TOOL_USE_END]
    assert {e.tool_call_id for e in starts} == {"c1", "c2"}
    assert {e.tool_call_id for e in ends} == {"c1", "c2"}


@respx.mock
async def test_auth_error_mapped() -> None:
    respx.post("https://api.test.example/chat/completions").mock(
        return_value=httpx.Response(401, text='{"error":"invalid key"}')
    )
    provider = OpenAICompatProvider(_config())
    with pytest.raises(ProviderAuthError):
        async for _ in provider.stream([Message(role=Role.USER, content="x")], []):
            pass
    await provider.aclose()


@respx.mock
async def test_rate_limit_retries_then_raises() -> None:
    route = respx.post("https://api.test.example/chat/completions").mock(
        return_value=httpx.Response(429, text="rate limited")
    )
    provider = OpenAICompatProvider(_config())
    with pytest.raises(ProviderRateLimitError):
        async for _ in provider.stream([Message(role=Role.USER, content="x")], []):
            pass
    await provider.aclose()
    assert route.call_count >= 2


@respx.mock
async def test_server_error_no_retry() -> None:
    route = respx.post("https://api.test.example/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    provider = OpenAICompatProvider(_config())
    with pytest.raises(ProviderError):
        async for _ in provider.stream([Message(role=Role.USER, content="x")], []):
            pass
    await provider.aclose()
    assert route.call_count == 1


def test_count_tokens_via_provider() -> None:
    provider = OpenAICompatProvider(_config())
    n = provider.count_tokens([Message(role=Role.USER, content="hello")])
    assert n > 0


def test_capability_metadata() -> None:
    provider = OpenAICompatProvider(_config())
    assert provider.context_window == 64_000
    assert provider.max_output_tokens == 4_096
    assert provider.model == "test-model"
