"""Verify that streaming tool dispatch starts tools before the LLM stream ends.

The optimization in `Agent.run` is: when the model emits text + tool calls in
the same turn, kick off the tool at `TOOL_USE_END` instead of waiting for
`DONE`. This test inserts a slow-arriving final event to make the difference
observable.
"""

from __future__ import annotations

import asyncio
import json
import time
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
from coding_agent.core.types import StreamEvent, StreamEventType, Usage
from coding_agent.providers.base import LLMProvider


class SlowProvider(LLMProvider):
    """Yields a tool call, then sleeps before sending DONE.

    With streaming dispatch the tool starts during the sleep; without it the
    tool only starts after the sleep elapses."""

    name = "slow-mock"

    def __init__(self, sleep_seconds: float, turns: list[list[StreamEvent]]) -> None:
        self.sleep_seconds = sleep_seconds
        self._turns = list(turns)
        self.config = ProviderConfig(api_key="x", model="m", context_window=64_000)

    @property
    def model(self) -> str:
        return "m"

    async def stream(
        self, messages, tools, *, temperature=None, max_tokens=None,
    ) -> AsyncIterator[StreamEvent]:
        if not self._turns:
            yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="(no more)")
            yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")
            return
        turn = self._turns.pop(0)
        for ev in turn:
            if ev.type == StreamEventType.DONE:
                await asyncio.sleep(self.sleep_seconds)
            yield ev


def _config(workspace: Path, streaming: bool) -> Config:
    return Config(
        provider="deepseek",
        workspace=workspace,
        providers={"deepseek": ProviderConfig(api_key="x", model="m")},
        permissions=PermissionsConfig(
            file_read="allow", file_write="allow", bash="allow",
        ),
        agent=AgentConfig(max_iterations=5, streaming_tool_dispatch=streaming),
    )


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


def _text_turn(text: str) -> list[StreamEvent]:
    return [
        StreamEvent(type=StreamEventType.TEXT_DELTA, text=text),
        StreamEvent(type=StreamEventType.USAGE, usage=Usage(prompt_tokens=5, completion_tokens=3)),
        StreamEvent(type=StreamEventType.DONE, finish_reason="stop"),
    ]


async def test_streaming_dispatch_runs_concurrently_with_stream(
    tmp_path: Path,
) -> None:
    """With streaming_tool_dispatch=True the read tool finishes before DONE,
    so the total wall-clock should be close to max(sleep, tool_time)
    rather than sleep + tool_time."""
    (tmp_path / "x.txt").write_text("x" * 10)

    sleep_s = 0.3
    provider = SlowProvider(
        sleep_seconds=sleep_s,
        turns=[_tool_turn("read", {"file_path": "x.txt"}), _text_turn("done")],
    )
    config = _config(tmp_path, streaming=True)
    session = Session(workspace=str(tmp_path), provider="deepseek", model="m")
    agent = Agent(provider, config, session)

    t0 = time.monotonic()
    events = [e async for e in agent.run("read x")]
    elapsed = time.monotonic() - t0

    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].tool_result.ok
    # Two turns: one with sleep, one without. Whole run should be close to
    # 1x sleep_s, not 2x. Allow generous slack for CI noise.
    assert elapsed < sleep_s * 2.5, f"streaming dispatch did not parallelize (elapsed={elapsed:.2f}s)"


async def test_non_streaming_dispatch_still_works(tmp_path: Path) -> None:
    """With streaming_tool_dispatch=False the old "wait for DONE then run"
    path must still be functional."""
    (tmp_path / "x.txt").write_text("hello")

    provider = SlowProvider(
        sleep_seconds=0.01,
        turns=[_tool_turn("read", {"file_path": "x.txt"}), _text_turn("done")],
    )
    config = _config(tmp_path, streaming=False)
    session = Session(workspace=str(tmp_path), provider="deepseek", model="m")
    agent = Agent(provider, config, session)

    events = [e async for e in agent.run("read x")]
    tool_results = [e for e in events if e.kind == EventKind.TOOL_RESULT]
    assert tool_results[0].tool_result.ok
    assert "hello" in tool_results[0].tool_result.content
