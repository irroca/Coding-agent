"""End-to-end compaction test: an agent run that crosses the compaction
threshold mid-conversation must keep working without losing the system prompt
or recent context."""

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
    Role,
    StreamEvent,
    StreamEventType,
    Usage,
)
from coding_agent.providers.base import LLMProvider


class CompactionProvider(LLMProvider):
    """First N turns report huge prompt_tokens to force compaction; later
    turns report normal usage. Also serves as the summarizer when compaction
    runs."""

    name = "compact-mock"

    def __init__(self, turns: list[list[StreamEvent]], summary_text: str) -> None:
        self._turns = list(turns)
        self._summary_text = summary_text
        self.config = ProviderConfig(api_key="x", model="m", context_window=1000)
        self.summarize_called = 0

    @property
    def model(self) -> str:
        return "m"

    async def stream(
        self, messages, tools, *, temperature=None, max_tokens=None,
    ) -> AsyncIterator[StreamEvent]:
        # If the prompt looks like our compaction prompt (single user message
        # containing the literal "Summarize the following conversation"),
        # respond with summary text only.
        if (
            len(messages) == 1
            and messages[0].role == Role.USER
            and "Summarize the following conversation" in messages[0].content
        ):
            self.summarize_called += 1
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=self._summary_text)
            yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")
            return

        if not self._turns:
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="(no more)")
            yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")
            return
        for ev in self._turns.pop(0):
            yield ev


def _config(workspace: Path) -> Config:
    return Config(
        provider="deepseek",
        workspace=workspace,
        providers={"deepseek": ProviderConfig(api_key="x", model="m", context_window=1000)},
        permissions=PermissionsConfig(
            file_read="allow", file_write="allow", bash="allow",
        ),
        agent=AgentConfig(
            max_iterations=10,
            compact_threshold=0.2,  # ~200 tokens triggers compaction
            keep_recent_turns=2,
            streaming_tool_dispatch=False,
        ),
    )


def _text_turn(text: str, prompt_tokens: int = 5) -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TEXT_DELTA, text=text),
        StreamEvent(
            type=StreamEventType.USAGE,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=3),
        ),
        StreamEvent(type=StreamEventType.DONE, finish_reason="stop"),
    ]


def _tool_turn(name: str, args: dict, tc_id: str = "tc-1") -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TOOL_USE_START, tool_call_id=tc_id, tool_name=name),
        StreamEvent(
            type=StreamEventType.TOOL_USE_DELTA,
            tool_call_id=tc_id,
            arguments_delta=json.dumps(args),
        ),
        StreamEvent(type=StreamEventType.TOOL_USE_END, tool_call_id=tc_id),
        StreamEvent(type=StreamEventType.USAGE, usage=Usage(prompt_tokens=10, completion_tokens=5)),
        StreamEvent(type=StreamEventType.DONE, finish_reason="tool_calls"),
    ]


async def test_compaction_keeps_system_prompt_and_recent_messages(
    tmp_path: Path,
) -> None:
    """After compaction the system prompt must still be at index 0 and the
    most recent N turns must still be present verbatim."""
    (tmp_path / "data.txt").write_text("payload")
    provider = CompactionProvider(
        turns=[
            _tool_turn("read", {"file_path": "data.txt"}),
            _text_turn("First answer", prompt_tokens=300),  # forces compaction next
            _text_turn("Second answer"),
        ],
        summary_text="Conversation so far: user asked to read data.txt.",
    )
    config = _config(tmp_path)
    session = Session(workspace=str(tmp_path), provider="deepseek", model="m")
    agent = Agent(provider, config, session)

    # First user message: drives initial read + answer
    [e async for e in agent.run("read data.txt")]
    # Second user message: prompt_tokens=300 from previous turn means budget
    # triggers compaction before this turn's stream call
    events_2 = [e async for e in agent.run("follow up")]

    # Sanity: agent didn't error out
    errors = [e for e in events_2 if e.kind == EventKind.ERROR]
    assert not errors, errors

    # System message must still be first
    assert session.messages[0].role == Role.SYSTEM
    assert "Coding Agent" in session.messages[0].content

    # Compaction must have run at least once
    assert provider.summarize_called >= 1

    # Look for the summary marker
    summary_msgs = [
        m for m in session.messages
        if m.role == Role.USER and "Prior conversation summary" in m.content
    ]
    assert len(summary_msgs) >= 1, "compaction did not insert a summary message"

    # The follow-up answer must be the last assistant message
    last_assistant = next(
        m for m in reversed(session.messages) if m.role == Role.ASSISTANT
    )
    assert "Second answer" in last_assistant.content
