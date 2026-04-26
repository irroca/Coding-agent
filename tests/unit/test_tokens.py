from __future__ import annotations

from coding_agent.core.tokens import count_message, count_messages, count_text
from coding_agent.core.types import (
    Message,
    Role,
    StreamEvent,
    StreamEventType,
    ToolCall,
    ToolResult,
    Usage,
)


def test_count_text_handles_empty() -> None:
    assert count_text("") == 0
    assert count_text("hello world") > 0


def test_count_message_includes_overhead() -> None:
    msg = Message(role=Role.USER, content="hello")
    assert count_message(msg) >= 4


def test_count_messages_priming_tokens() -> None:
    msgs = [Message(role=Role.USER, content="hi")]
    n = count_messages(msgs)
    assert n == count_message(msgs[0]) + 2


def test_assistant_with_tool_calls_counts_args() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="bash", arguments={"command": "ls -la"})],
    )
    assert count_message(msg) > 4


def test_tool_result_message_counts_content() -> None:
    msg = Message(
        role=Role.TOOL,
        tool_results=[ToolResult(call_id="x", tool="bash", ok=True, content="files\nhere")],
    )
    assert count_message(msg) > 4


def test_usage_total() -> None:
    u = Usage(prompt_tokens=10, completion_tokens=5, cached_prompt_tokens=2)
    assert u.total_tokens == 15


def test_stream_event_round_trip() -> None:
    e = StreamEvent(type=StreamEventType.TEXT_DELTA, text="hi")
    j = e.model_dump_json()
    e2 = StreamEvent.model_validate_json(j)
    assert e2.text == "hi"
    assert e2.type is StreamEventType.TEXT_DELTA
