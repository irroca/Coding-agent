"""Advanced integration tests — multi-tool chains, permission denied, bash execution."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from coding_agent.agent.loop import Agent, AgentEvent, EventKind
from coding_agent.core.config import AgentConfig, Config, PermissionsConfig, ProviderConfig
from coding_agent.core.session import Session
from coding_agent.core.types import (
    StreamEvent,
    StreamEventType,
    Usage,
)
from coding_agent.providers.base import LLMProvider


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self._turns = list(turns)
        self.config = ProviderConfig(
            api_key="mock-key", model="mock-model", context_window=64_000
        )

    async def stream(self, messages, tools, *, temperature=None, max_tokens=None) -> AsyncIterator[StreamEvent]:
        if not self._turns:
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="(done)")
            yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")
            return
        for event in self._turns.pop(0):
            yield event

    @property
    def model(self) -> str:
        return "mock-model"


def _config(workspace: Path, **kwargs) -> Config:
    return Config(
        provider="deepseek",
        workspace=workspace,
        providers={"deepseek": ProviderConfig(api_key="x", model="m")},
        agent=AgentConfig(max_iterations=10),
        **kwargs,
    )


def _text_turn(text: str) -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TEXT_DELTA, text=text),
        StreamEvent(type=StreamEventType.USAGE, usage=Usage(prompt_tokens=10, completion_tokens=5)),
        StreamEvent(type=StreamEventType.DONE, finish_reason="stop"),
    ]


def _tool_turn(tool_name: str, args: dict, tc_id: str = "tc-1") -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TOOL_USE_START, tool_call_id=tc_id, tool_name=tool_name),
        StreamEvent(type=StreamEventType.TOOL_USE_DELTA, tool_call_id=tc_id, arguments_delta=json.dumps(args)),
        StreamEvent(type=StreamEventType.TOOL_USE_END, tool_call_id=tc_id),
        StreamEvent(type=StreamEventType.USAGE, usage=Usage(prompt_tokens=15, completion_tokens=8)),
        StreamEvent(type=StreamEventType.DONE, finish_reason="tool_calls"),
    ]


async def _collect(agent: Agent, text: str) -> list[AgentEvent]:
    return [e async for e in agent.run(text)]


# ── Multi-tool chain: read → edit → read ──────────────────────────────


async def test_read_edit_read_chain(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n")
    provider = MockProvider([
        _tool_turn("read", {"file_path": "app.py"}),
        _tool_turn("edit", {
            "file_path": "app.py",
            "old_string": "x = 1",
            "new_string": "x = 42",
        }),
        _text_turn("Changed x to 42."),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    agent = Agent(provider, _config(tmp_path), session)
    events = await _collect(agent, "change x to 42")

    assert (tmp_path / "app.py").read_text().strip() == "x = 42"
    texts = [e.text for e in events if e.kind == EventKind.TEXT_DELTA]
    assert "42" in "".join(texts)


# ── Bash tool execution ───────────────────────────────────────────────


async def test_bash_tool_execution(tmp_path: Path) -> None:
    provider = MockProvider([
        _tool_turn("bash", {"command": "echo hello_from_bash"}),
        _text_turn("Done."),
    ])
    config = _config(tmp_path, permissions=PermissionsConfig(bash="allow"))
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    agent = Agent(provider, config, session)
    events = await _collect(agent, "run echo")

    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert any("hello_from_bash" in (r.tool_result.content or "") for r in tool_results)


# ── Glob + grep workflow ──────────────────────────────────────────────


async def test_glob_and_grep_workflow(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def calculate(): pass\n")
    (tmp_path / "src" / "util.py").write_text("def helper(): pass\n")

    provider = MockProvider([
        _tool_turn("glob", {"pattern": "*.py", "path": "src"}),
        _tool_turn("grep", {"pattern": "calculate", "path": "src"}),
        _text_turn("Found calculate in main.py."),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    agent = Agent(provider, _config(tmp_path), session)
    events = await _collect(agent, "find calculate")

    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert len(tool_results) == 2
    assert all(r.tool_result.ok for r in tool_results)


# ── Provider error propagation ─────────────────────────────────────────


async def test_provider_error_event(tmp_path: Path) -> None:
    error_turn = [
        StreamEvent(type=StreamEventType.ERROR, error="Rate limit exceeded"),
    ]
    provider = MockProvider([error_turn])
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    agent = Agent(provider, _config(tmp_path), session)
    events = await _collect(agent, "hi")

    errors = [e for e in events if e.kind == EventKind.ERROR]
    assert len(errors) == 1
    assert "Rate limit" in (errors[0].error or "")


# ── Todo write tool ───────────────────────────────────────────────────


async def test_todo_write_in_agent_loop(tmp_path: Path) -> None:
    provider = MockProvider([
        _tool_turn("todo_write", {"todos": [
            {"content": "Fix bug", "status": "in_progress"},
            {"content": "Write tests", "status": "pending"},
        ]}),
        _text_turn("Tasks set."),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    agent = Agent(provider, _config(tmp_path), session)
    events = await _collect(agent, "plan work")

    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert tool_results[0].tool_result.ok
    assert "2 items" in tool_results[0].tool_result.content


# ── Cancel signal ─────────────────────────────────────────────────────


async def test_multiple_text_deltas(tmp_path: Path) -> None:
    """Multiple text delta events should be emitted individually."""
    multi_text = [
        StreamEvent(type=StreamEventType.TEXT_DELTA, text="Hello "),
        StreamEvent(type=StreamEventType.TEXT_DELTA, text="world!"),
        StreamEvent(type=StreamEventType.USAGE, usage=Usage(prompt_tokens=10, completion_tokens=5)),
        StreamEvent(type=StreamEventType.DONE, finish_reason="stop"),
    ]
    provider = MockProvider([multi_text])
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    agent = Agent(provider, _config(tmp_path), session)
    events = await _collect(agent, "hi")
    texts = [e.text for e in events if e.kind == EventKind.TEXT_DELTA]
    assert texts == ["Hello ", "world!"]


# ── Ls tool ───────────────────────────────────────────────────────────


async def test_ls_tool(tmp_path: Path) -> None:
    (tmp_path / "file1.txt").write_text("a")
    (tmp_path / "file2.txt").write_text("b")
    provider = MockProvider([
        _tool_turn("ls", {"path": "."}),
        _text_turn("Listed."),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    agent = Agent(provider, _config(tmp_path), session)
    events = await _collect(agent, "list files")

    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert tool_results[0].tool_result.ok
    assert "file1.txt" in tool_results[0].tool_result.content
