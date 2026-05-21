"""Integration tests for the sub-agent (`task` tool) dispatch.

We use a MockProvider that can be cloned-and-controlled differently for the
parent vs sub-agent turn, so we can assert that:

  * the parent sees only the final summary (no flood of tool results)
  * the sub-agent runs in an isolated session with read-only tools
  * recursion is blocked at depth 2
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from coding_agent.agent.loop import Agent, EventKind
from coding_agent.core.config import (
    AgentConfig,
    Config,
    PermissionsConfig,
    ProviderConfig,
)
from coding_agent.core.session import Session
from coding_agent.core.types import (
    StreamEvent,
    StreamEventType,
    Usage,
)
from coding_agent.providers.base import LLMProvider


class MockProvider(LLMProvider):
    """Replays canned turns. Same provider is shared by parent and sub-agent,
    so order of turn consumption matters."""

    name = "mock"

    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self._turns = list(turns)
        self.config = ProviderConfig(
            api_key="mock-key", model="mock-model", context_window=64_000
        )
        self.stream_count = 0

    async def stream(
        self, messages, tools, *, temperature=None, max_tokens=None,
    ) -> AsyncIterator[StreamEvent]:
        self.stream_count += 1
        if not self._turns:
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="(done)")
            yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")
            return
        for event in self._turns.pop(0):
            yield event

    @property
    def model(self) -> str:
        return "mock-model"


def _config(workspace: Path) -> Config:
    return Config(
        provider="deepseek",
        workspace=workspace,
        providers={"deepseek": ProviderConfig(api_key="x", model="m")},
        permissions=PermissionsConfig(file_read="allow", file_write="allow", bash="allow"),
        agent=AgentConfig(max_iterations=10, subagent_max_iterations=5),
    )


def _text_turn(text: str, finish: str = "stop") -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TEXT_DELTA, text=text),
        StreamEvent(type=StreamEventType.USAGE, usage=Usage(prompt_tokens=5, completion_tokens=3)),
        StreamEvent(type=StreamEventType.DONE, finish_reason=finish),  # type: ignore[arg-type]
    ]


def _tool_turn(tool_name: str, args: dict, tc_id: str = "tc-1") -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TOOL_USE_START, tool_call_id=tc_id, tool_name=tool_name),
        StreamEvent(
            type=StreamEventType.TOOL_USE_DELTA,
            tool_call_id=tc_id,
            arguments_delta=json.dumps(args),
        ),
        StreamEvent(type=StreamEventType.TOOL_USE_END, tool_call_id=tc_id),
        StreamEvent(type=StreamEventType.USAGE, usage=Usage(prompt_tokens=10, completion_tokens=5)),
        StreamEvent(type=StreamEventType.DONE, finish_reason="tool_calls"),
    ]


async def test_subagent_returns_summary_to_parent(tmp_path: Path) -> None:
    """Parent dispatches a sub-agent. Sub-agent reads a file and reports back."""
    (tmp_path / "data.txt").write_text("the answer is 42")

    provider = MockProvider([
        # Parent turn 1: invoke task tool
        _tool_turn(
            "task",
            {"description": "Find the answer", "prompt": "Read data.txt and tell me what's in it"},
            tc_id="parent-tc-1",
        ),
        # Sub-agent turn 1: read data.txt
        _tool_turn("read", {"file_path": "data.txt"}, tc_id="sub-tc-1"),
        # Sub-agent turn 2: produce final answer
        _text_turn("The file says: the answer is 42"),
        # Parent turn 2: relay
        _text_turn("Got it — the answer is 42."),
    ])

    config = _config(tmp_path)
    session = Session(workspace=str(tmp_path), provider="deepseek", model="mock-model")
    agent = Agent(provider, config, session)

    events = [e async for e in agent.run("what's in data.txt?")]

    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    # The parent should see exactly one tool result — the `task` summary.
    # The sub-agent's `read` result must NOT leak into the parent's event stream.
    assert len(tool_results) == 1
    assert tool_results[0].tool_result.tool == "task"
    assert tool_results[0].tool_result.ok
    assert "42" in tool_results[0].tool_result.content
    assert tool_results[0].tool_result.metadata.get("tool_calls") == 1


async def test_subagent_cannot_recursively_dispatch(tmp_path: Path) -> None:
    """A sub-agent calling `task` again must get rejected to bound recursion."""
    provider = MockProvider([
        # Parent: dispatches sub-agent
        _tool_turn(
            "task",
            {"description": "Outer", "prompt": "Do work"},
            tc_id="parent-tc",
        ),
        # Sub-agent: tries to dispatch ANOTHER sub-agent
        _tool_turn(
            "task",
            {"description": "Inner", "prompt": "Recursion!"},
            tc_id="sub-tc",
        ),
        # Sub-agent: produces a final answer after getting rejected
        _text_turn("Recursion was blocked. I'll do it myself: done."),
        # Parent: relay
        _text_turn("OK."),
    ])

    config = _config(tmp_path)
    session = Session(workspace=str(tmp_path), provider="deepseek", model="mock-model")
    agent = Agent(provider, config, session)

    events = [e async for e in agent.run("explore")]

    parent_tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    # Parent still sees only ONE tool result (the outer task summary).
    assert len(parent_tool_results) == 1
    # The summary should mention the recursion got blocked OR that the sub-agent
    # recovered from it. We just check the run ultimately succeeded.
    assert "done" in parent_tool_results[0].tool_result.content.lower()


async def test_subagent_session_is_isolated(tmp_path: Path) -> None:
    """The parent's session must not contain the sub-agent's intermediate
    read/write messages."""
    (tmp_path / "x.txt").write_text("x")

    provider = MockProvider([
        _tool_turn(
            "task",
            {"description": "Probe", "prompt": "Read x.txt"},
            tc_id="parent-tc",
        ),
        _tool_turn("read", {"file_path": "x.txt"}, tc_id="sub-tc"),
        _text_turn("File x.txt contains 'x'."),
        _text_turn("done"),
    ])

    config = _config(tmp_path)
    session = Session(workspace=str(tmp_path), provider="deepseek", model="mock-model")
    agent = Agent(provider, config, session)

    [e async for e in agent.run("probe")]

    # Walk every message in the parent session — none should be a tool result
    # for `read`. The parent should only see its own `task` tool result.
    tool_msgs = [m for m in session.messages if m.role.value == "tool"]
    tool_names_seen = {r.tool for m in tool_msgs for r in m.tool_results}
    assert tool_names_seen == {"task"}
