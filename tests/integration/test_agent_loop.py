"""Integration tests for the Agent loop using a mock provider.

These tests verify the full cycle:
  user message → LLM stream → tool calls → tool execution → next turn → final answer.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from coding_agent.agent.loop import Agent, AgentEvent, EventKind
from coding_agent.core.config import AgentConfig, Config, ProviderConfig
from coding_agent.core.session import Session
from coding_agent.core.types import (
    StreamEvent,
    StreamEventType,
    Usage,
)
from coding_agent.providers.base import LLMProvider


class MockProvider(LLMProvider):
    """Controllable mock that yields canned responses.

    Each call to ``stream()`` pops the next response from ``turns``.
    A "turn" is a list of StreamEvents the provider should emit.
    """

    name = "mock"

    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self._turns = list(turns)
        self.config = ProviderConfig(
            api_key="mock-key", model="mock-model", context_window=64_000
        )

    async def stream(  # type: ignore[override]
        self, messages, tools, *, temperature=None, max_tokens=None
    ) -> AsyncIterator[StreamEvent]:
        if not self._turns:
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="(no more turns)")
            yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")
            return
        turn = self._turns.pop(0)
        for event in turn:
            yield event

    @property
    def model(self) -> str:
        return "mock-model"


def _config(workspace: Path) -> Config:
    return Config(
        provider="deepseek",
        workspace=workspace,
        providers={"deepseek": ProviderConfig(api_key="x", model="m")},
        agent=AgentConfig(max_iterations=10),
    )


def _text_turn(text: str) -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TEXT_DELTA, text=text),
        StreamEvent(
            type=StreamEventType.USAGE,
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        ),
        StreamEvent(type=StreamEventType.DONE, finish_reason="stop"),
    ]


def _tool_turn(tool_name: str, args: dict, text: str = "") -> list[StreamEvent]:
    events: list[StreamEvent] = []
    if text:
        events.append(StreamEvent(type=StreamEventType.TEXT_DELTA, text=text))
    events.extend([
        StreamEvent(
            type=StreamEventType.TOOL_USE_START,
            tool_call_id="tc-1",
            tool_name=tool_name,
        ),
        StreamEvent(
            type=StreamEventType.TOOL_USE_DELTA,
            tool_call_id="tc-1",
            arguments_delta=json.dumps(args),
        ),
        StreamEvent(type=StreamEventType.TOOL_USE_END, tool_call_id="tc-1"),
        StreamEvent(
            type=StreamEventType.USAGE,
            usage=Usage(prompt_tokens=15, completion_tokens=8),
        ),
        StreamEvent(type=StreamEventType.DONE, finish_reason="tool_calls"),
    ])
    return events


async def _collect(agent: Agent, user_input: str) -> list[AgentEvent]:
    return [e async for e in agent.run(user_input)]


# ── Tests ────────────────────────────────────────────────────────────────


async def test_simple_text_response(tmp_path: Path) -> None:
    provider = MockProvider([_text_turn("Hello, world!")])
    session = Session(workspace=str(tmp_path), provider="mock", model="mock-model")
    agent = Agent(provider, _config(tmp_path), session)

    events = await _collect(agent, "hi")
    texts = [e.text for e in events if e.kind == EventKind.TEXT_DELTA]
    assert "".join(texts) == "Hello, world!"
    assert any(e.kind == EventKind.TURN_END for e in events)
    assert session.usage.total_tokens > 0


async def test_tool_call_and_followup(tmp_path: Path) -> None:
    """Model calls `write` to create a file, then responds with text."""
    provider = MockProvider([
        _tool_turn("write", {"file_path": "test.txt", "content": "hello"}),
        _text_turn("File created!"),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="mock-model")
    agent = Agent(provider, _config(tmp_path), session)

    events = await _collect(agent, "create test.txt")

    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].tool_result.ok
    assert (tmp_path / "test.txt").read_text() == "hello"

    texts = [e.text for e in events if e.kind == EventKind.TEXT_DELTA]
    assert "File created!" in "".join(texts)


async def test_tool_call_read_file(tmp_path: Path) -> None:
    (tmp_path / "data.py").write_text("print('hi')\n")
    provider = MockProvider([
        _tool_turn("read", {"file_path": "data.py"}),
        _text_turn("The file prints hi."),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="mock-model")
    agent = Agent(provider, _config(tmp_path), session)

    events = await _collect(agent, "read data.py")
    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert tool_results[0].tool_result.ok
    assert "print('hi')" in tool_results[0].tool_result.content


async def test_unknown_tool_returns_error(tmp_path: Path) -> None:
    provider = MockProvider([
        _tool_turn("nonexistent_tool", {"x": 1}),
        _text_turn("OK."),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="mock-model")
    agent = Agent(provider, _config(tmp_path), session)

    events = await _collect(agent, "do something")
    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert not tool_results[0].tool_result.ok
    assert "Unknown tool" in tool_results[0].tool_result.content


async def test_max_iterations_stops(tmp_path: Path) -> None:
    """If the model keeps calling tools forever, the loop stops at max_iterations."""
    infinite_turns = [_tool_turn("ls", {"path": "."}) for _ in range(20)]
    provider = MockProvider(infinite_turns)
    config = _config(tmp_path)
    config.agent.max_iterations = 3
    session = Session(workspace=str(tmp_path), provider="mock", model="mock-model")
    agent = Agent(provider, config, session)

    events = await _collect(agent, "loop forever")
    errors = [e for e in events if e.kind == EventKind.ERROR]
    assert any("max iterations" in (e.error or "").lower() for e in errors)


async def test_session_persisted_after_run(tmp_path: Path) -> None:
    provider = MockProvider([_text_turn("saved")])
    session = Session(workspace=str(tmp_path), provider="mock", model="mock-model")
    agent = Agent(provider, _config(tmp_path), session)

    await _collect(agent, "persist me")
    assert session.snapshot_path().is_file()

    loaded = Session.load(session.id)
    assert len(loaded.messages) >= 3  # system + user + assistant


async def test_confirm_callback_deny(tmp_path: Path) -> None:
    """When the confirm callback denies, the tool result shows denial."""
    async def _deny(name, summary, diff):
        return False

    provider = MockProvider([
        _tool_turn("write", {"file_path": "x.txt", "content": "y"}),
        _text_turn("OK."),
    ])
    session = Session(workspace=str(tmp_path), provider="mock", model="mock-model")
    agent = Agent(provider, _config(tmp_path), session, confirm=_deny)

    events = await _collect(agent, "write file")
    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert not tool_results[0].tool_result.ok
    assert "denied" in tool_results[0].tool_result.content.lower()
    assert not (tmp_path / "x.txt").exists()
