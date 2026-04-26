"""Tests for context budget monitoring and compaction."""

from __future__ import annotations

from collections.abc import AsyncIterator

from coding_agent.agent.compaction import (
    _fallback_summarize,
    _format_messages_for_summary,
    build_summary_message,
    compact_messages,
    split_for_compaction,
)
from coding_agent.agent.context import ContextBudget
from coding_agent.core.types import (
    Message,
    Role,
    StreamEvent,
    StreamEventType,
    ToolCall,
    ToolResult,
    Usage,
)


def _msg(role: Role, content: str = "x" * 100) -> Message:
    return Message(role=role, content=content)


# ── ContextBudget ───────────────────────────────────────────────────────


def test_budget_no_compact_when_under_threshold() -> None:
    budget = ContextBudget(context_window=100_000, compact_threshold=0.85)
    msgs = [_msg(Role.SYSTEM, "sys"), _msg(Role.USER, "hi")]
    assert not budget.should_compact(msgs)


def test_budget_compact_when_over_threshold() -> None:
    budget = ContextBudget(context_window=50, compact_threshold=0.5)
    # Each unique word is ~1 token; 50 words > 25 token threshold
    msgs = [_msg(Role.USER, " ".join(f"word{i}" for i in range(100)))]
    assert budget.should_compact(msgs)


def test_budget_utilization() -> None:
    budget = ContextBudget(context_window=100_000)
    msgs = [_msg(Role.USER, "hello")]
    util = budget.utilization(msgs)
    assert 0.0 < util < 0.01


def test_budget_utilization_zero_window() -> None:
    budget = ContextBudget(context_window=0)
    assert budget.utilization([]) == 0.0


# ── split_for_compaction ────────────────────────────────────────────────


def test_split_empty() -> None:
    s, m, t = split_for_compaction([])
    assert s == m == t == []


def test_split_short_no_middle() -> None:
    msgs = [_msg(Role.SYSTEM, "sys"), _msg(Role.USER, "hi"), _msg(Role.ASSISTANT, "yo")]
    s, m, t = split_for_compaction(msgs, keep_recent=6)
    assert len(s) == 1
    assert m == []
    assert len(t) == 2


def test_split_long_has_middle() -> None:
    msgs = [_msg(Role.SYSTEM, "sys")]
    for i in range(10):
        msgs.append(_msg(Role.USER, f"q{i}"))
        msgs.append(_msg(Role.ASSISTANT, f"a{i}"))
    s, m, t = split_for_compaction(msgs, keep_recent=4)
    assert len(s) == 1
    assert len(t) == 4
    assert len(m) == 16  # 20 non-system - 4 recent


def test_split_no_system() -> None:
    msgs = [_msg(Role.USER, "hi"), _msg(Role.ASSISTANT, "yo")]
    s, m, t = split_for_compaction(msgs, keep_recent=6)
    assert s == []
    assert m == []
    assert len(t) == 2


# ── format / summary helpers ───────────────────────────────────────────


def test_format_messages() -> None:
    msgs = [
        Message(role=Role.USER, content="hello"),
        Message(role=Role.ASSISTANT, content="hi", tool_calls=[
            ToolCall(name="read", arguments={"file_path": "x.py"}),
        ]),
        Message(role=Role.TOOL, tool_results=[
            ToolResult(call_id="1", tool="read", ok=True, content="file content"),
        ]),
    ]
    text = _format_messages_for_summary(msgs)
    assert "hello" in text
    assert "read" in text
    assert "file content" in text


def test_build_summary_message() -> None:
    msg = build_summary_message("This is a summary.")
    assert msg.role == Role.USER
    assert "summary" in msg.content.lower()
    assert "This is a summary." in msg.content


def test_fallback_summarize() -> None:
    msgs = [
        Message(role=Role.USER, content="fix the bug"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[
            ToolCall(name="read", arguments={}),
        ]),
        Message(role=Role.ASSISTANT, content="Done!"),
    ]
    text = _fallback_summarize(msgs)
    assert "fix the bug" in text
    assert "read" in text
    assert "Done!" in text


# ── compact_messages ────────────────────────────────────────────────────


class FakeProvider:
    """Yields a canned summary text."""

    context_window = 128_000

    def __init__(self, summary: str = "Summary of prior conversation.") -> None:
        self._summary = summary

    async def stream(self, messages, tools, **kwargs) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=self._summary)
        yield StreamEvent(
            type=StreamEventType.USAGE,
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )
        yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")


class FailingProvider:
    context_window = 128_000

    async def stream(self, messages, tools, **kwargs) -> AsyncIterator[StreamEvent]:
        raise RuntimeError("LLM unavailable")
        yield  # make it an async generator  # type: ignore[misc]


async def test_compact_with_llm() -> None:
    msgs = [_msg(Role.SYSTEM, "sys")]
    for i in range(10):
        msgs.append(_msg(Role.USER, f"q{i}"))
        msgs.append(_msg(Role.ASSISTANT, f"a{i}"))

    provider = FakeProvider("This is the LLM summary.")
    result = await compact_messages(msgs, provider, keep_recent=4)

    assert len(result) < len(msgs)
    assert result[0].role == Role.SYSTEM
    assert "summary" in result[1].content.lower()
    assert result[-1].content == "a9"


async def test_compact_fallback_on_provider_error() -> None:
    msgs = [_msg(Role.SYSTEM, "sys")]
    for i in range(10):
        msgs.append(_msg(Role.USER, f"q{i}"))
        msgs.append(_msg(Role.ASSISTANT, f"a{i}"))

    provider = FailingProvider()
    result = await compact_messages(msgs, provider, keep_recent=4)

    assert len(result) < len(msgs)
    assert "summary" in result[1].content.lower()


async def test_compact_nothing_to_compact() -> None:
    msgs = [_msg(Role.SYSTEM, "sys"), _msg(Role.USER, "hi")]
    provider = FakeProvider()
    result = await compact_messages(msgs, provider, keep_recent=6)
    assert result == msgs
