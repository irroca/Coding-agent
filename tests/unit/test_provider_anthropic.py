"""Anthropic adapter tests with mocked event-typed SSE streams."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from coding_agent.core.config import ProviderConfig
from coding_agent.core.types import (
    Message,
    Role,
    StreamEventType,
    ToolCall,
    ToolResult,
    ToolSchema,
    Usage,
)
from coding_agent.providers.anthropic import (
    AnthropicProvider,
    _merge_anthropic_usage,
    _messages_to_anthropic,
    _split_system,
    _tools_to_anthropic,
)


def _config() -> ProviderConfig:
    return ProviderConfig(
        api_key="sk-anthropic-test",
        base_url="https://anthropic.test.example",
        model="claude-test",
    )


def _sse(*events: tuple[str, dict]) -> str:
    """Build an event-typed SSE body."""
    return "".join(f"event: {t}\ndata: {json.dumps(d)}\n\n" for t, d in events)


def test_split_system_extracts_system_content() -> None:
    msgs = [
        Message(role=Role.SYSTEM, content="be helpful"),
        Message(role=Role.SYSTEM, content="be concise"),
        Message(role=Role.USER, content="hi"),
    ]
    sys, rest = _split_system(msgs)
    assert sys == "be helpful\n\nbe concise"
    assert [m.role for m in rest] == [Role.USER]


def test_messages_to_anthropic_tool_use_block() -> None:
    msgs = [
        Message(
            role=Role.ASSISTANT,
            content="ok",
            tool_calls=[ToolCall(id="t1", name="bash", arguments={"command": "ls"})],
        ),
        Message(
            role=Role.TOOL,
            tool_results=[ToolResult(call_id="t1", tool="bash", ok=True, content="x")],
        ),
    ]
    wire = _messages_to_anthropic(msgs)
    assert wire[0]["role"] == "assistant"
    blocks = wire[0]["content"]
    assert blocks[0] == {"type": "text", "text": "ok"}
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["input"] == {"command": "ls"}
    assert wire[1]["role"] == "user"
    assert wire[1]["content"][0]["type"] == "tool_result"
    assert wire[1]["content"][0]["is_error"] is False


@respx.mock
async def test_anthropic_stream_text_and_tool() -> None:
    body = _sse(
        ("message_start", {"message": {"usage": {"input_tokens": 12, "output_tokens": 0}}}),
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        (
            "content_block_delta",
            {"index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
        ),
        ("content_block_stop", {"index": 0}),
        (
            "content_block_start",
            {
                "index": 1,
                "content_block": {"type": "tool_use", "id": "tu_1", "name": "bash"},
            },
        ),
        (
            "content_block_delta",
            {
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": "{\"command\":"},
            },
        ),
        (
            "content_block_delta",
            {
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": "\"ls\"}"},
            },
        ),
        ("content_block_stop", {"index": 1}),
        (
            "message_delta",
            {
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 8, "input_tokens": 12},
            },
        ),
        ("message_stop", {}),
    )
    respx.post("https://anthropic.test.example/v1/messages").mock(
        return_value=httpx.Response(200, text=body)
    )
    provider = AnthropicProvider(_config())
    events = [
        e async for e in provider.stream([Message(role=Role.USER, content="run ls")], [])
    ]
    await provider.aclose()

    text = "".join(e.text or "" for e in events if e.type == StreamEventType.TEXT_DELTA)
    assert text == "Hello"
    starts = [e for e in events if e.type == StreamEventType.TOOL_USE_START]
    assert starts[0].tool_name == "bash"
    deltas = [e for e in events if e.type == StreamEventType.TOOL_USE_DELTA]
    assert "".join(e.arguments_delta for e in deltas) == '{"command":"ls"}'
    done = events[-1]
    assert done.type == StreamEventType.DONE
    assert done.finish_reason == "tool_calls"


# ── Prompt cache integration ──────────────────────────────────────────


def test_tools_to_anthropic_marks_last_tool_when_caching() -> None:
    schemas = [
        ToolSchema(name="a", description="A", parameters={"type": "object"}),
        ToolSchema(name="b", description="B", parameters={"type": "object"}),
    ]
    no_cache = _tools_to_anthropic(schemas, cache_last=False)
    assert all("cache_control" not in t for t in no_cache)

    with_cache = _tools_to_anthropic(schemas, cache_last=True)
    assert "cache_control" not in with_cache[0]
    assert with_cache[-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_anthropic_request_includes_cache_control_when_enabled() -> None:
    """When supports_prompt_cache=True, system gets a text block with
    cache_control and the last tool also gets a cache_control marker."""
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=(
                'event: message_start\ndata: {"message":{"usage":{"input_tokens":1,"output_tokens":0}}}\n\n'
                'event: message_stop\ndata: {}\n\n'
            ),
        )

    with respx.mock:
        respx.post("https://anthropic.test.example/v1/messages").mock(side_effect=_capture)

        cfg = ProviderConfig(
            api_key="sk-x",
            base_url="https://anthropic.test.example",
            model="claude-test",
            supports_prompt_cache=True,
        )
        provider = AnthropicProvider(cfg)
        tools = [ToolSchema(name="ls", description="list", parameters={"type": "object"})]
        [
            e async for e in provider.stream(
                [Message(role=Role.SYSTEM, content="x"), Message(role=Role.USER, content="hi")],
                tools,
            )
        ]
        await provider.aclose()

    body = captured["body"]
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_anthropic_request_no_cache_when_disabled() -> None:
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=(
                'event: message_start\ndata: {"message":{"usage":{"input_tokens":1,"output_tokens":0}}}\n\n'
                'event: message_stop\ndata: {}\n\n'
            ),
        )

    with respx.mock:
        respx.post("https://anthropic.test.example/v1/messages").mock(side_effect=_capture)

        cfg = ProviderConfig(
            api_key="sk-x",
            base_url="https://anthropic.test.example",
            model="claude-test",
            supports_prompt_cache=False,
        )
        provider = AnthropicProvider(cfg)
        [
            e async for e in provider.stream(
                [Message(role=Role.SYSTEM, content="x"), Message(role=Role.USER, content="hi")],
                [],
            )
        ]
        await provider.aclose()

    body = captured["body"]
    # When cache is off, system is a plain string and no cache_control anywhere.
    assert body["system"] == "x"


def test_merge_anthropic_usage_normalizes_cache_fields() -> None:
    """Anthropic reports input/cache_read/cache_creation as disjoint counters.
    We sum them into prompt_tokens to keep semantics aligned with OpenAI."""
    usage = _merge_anthropic_usage(
        Usage(),
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 800,
            "cache_creation_input_tokens": 200,
        },
    )
    assert usage.prompt_tokens == 1100
    assert usage.cached_prompt_tokens == 800
    assert usage.cache_creation_tokens == 200
    assert usage.completion_tokens == 50
    assert usage.cache_hit_rate == pytest.approx(800 / 1100)


def test_usage_cache_hit_rate_zero_when_no_prompt() -> None:
    assert Usage().cache_hit_rate == 0.0
