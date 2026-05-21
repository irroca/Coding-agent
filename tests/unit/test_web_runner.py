"""Runner tests — drive a SessionRunner with a MockProvider and assert that
events flow correctly through the outbound queue, including the
permission-confirm round trip."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coding_agent.agent.loop import AgentEvent, EventKind
from coding_agent.core.config import (
    AgentConfig,
    Config,
    PermissionsConfig,
    ProviderConfig,
)
from coding_agent.core.types import ToolResult, Usage
from coding_agent.web.runner import SessionRunner, _to_wire
from tests.integration.test_agent_loop import MockProvider, _text_turn, _tool_turn


@pytest.fixture(autouse=True)
def _patch_build_provider(monkeypatch):
    """SessionRunner builds its own provider via build_provider; override
    the registry to return our MockProvider regardless of config."""
    from coding_agent.providers import registry

    def _fake_build(config, override=None):
        # The test sets ``config.providers`` to a marker; each test fixture
        # below replaces this with a fresh MockProvider via the request param.
        prov = getattr(_fake_build, "_provider", None)
        if prov is None:
            raise RuntimeError("Test forgot to install a MockProvider")
        return prov

    monkeypatch.setattr(registry, "build_provider", _fake_build)
    # SessionRunner imports build_provider at module load time
    from coding_agent.web import runner as runner_module

    monkeypatch.setattr(runner_module, "build_provider", _fake_build)
    return _fake_build


def _config(workspace: Path) -> Config:
    return Config(
        provider="deepseek",
        workspace=workspace,
        providers={"deepseek": ProviderConfig(api_key="x", model="m")},
        permissions=PermissionsConfig(
            file_read="allow", file_write="allow", bash="allow",
        ),
        agent=AgentConfig(max_iterations=5),
    )


async def _drain_until(queue: asyncio.Queue, predicate, timeout=2.0):
    """Pull from queue until predicate matches a message; return all collected."""
    collected = []
    async def _go():
        while True:
            msg = await queue.get()
            collected.append(msg)
            if predicate(msg):
                return
    await asyncio.wait_for(_go(), timeout=timeout)
    return collected


async def test_runner_emits_text_then_turn_end(tmp_path, _patch_build_provider):
    provider = MockProvider(turns=[_text_turn("Hello world")])
    _patch_build_provider._provider = provider

    runner = SessionRunner("tab-1", _config(tmp_path))
    await runner.start()
    await runner.attach_session(session_id=None, workspace=None)
    await runner.submit("hi")

    # First emission is the session_state from the initial attach.
    initial = await asyncio.wait_for(runner.outbound.get(), timeout=2.0)
    assert initial["type"] == "session_state"

    msgs = await _drain_until(runner.outbound, lambda m: m["type"] == "turn_end")
    kinds = [m["type"] for m in msgs]
    assert "text_delta" in kinds
    assert "usage" in kinds
    assert "turn_end" in kinds

    await runner.close()


async def test_runner_tool_flow_with_allow(tmp_path, _patch_build_provider):
    (tmp_path / "x.txt").write_text("hello")
    provider = MockProvider(
        turns=[
            _tool_turn("read", {"file_path": "x.txt"}),
            _text_turn("done"),
        ]
    )
    _patch_build_provider._provider = provider

    runner = SessionRunner("tab-2", _config(tmp_path))
    await runner.start()
    await runner.attach_session(session_id=None, workspace=None)
    await runner.submit("read x")

    # Drain everything for two turns
    seen_types: list[str] = []
    deadline = asyncio.get_event_loop().time() + 3.0
    turn_ends = 0
    while turn_ends < 2 and asyncio.get_event_loop().time() < deadline:
        try:
            msg = await asyncio.wait_for(runner.outbound.get(), timeout=1.0)
        except TimeoutError:
            break
        seen_types.append(msg["type"])
        if msg["type"] == "turn_end":
            turn_ends += 1

    assert "tool_start" in seen_types
    assert "tool_result" in seen_types
    await runner.close()


async def test_runner_confirm_round_trip(tmp_path, _patch_build_provider):
    """ask permission → runner emits confirm_request → we respond → tool runs."""
    cfg = _config(tmp_path)
    cfg = cfg.model_copy(
        update={
            "permissions": PermissionsConfig(
                file_read="allow", file_write="ask", bash="allow",
            )
        }
    )
    provider = MockProvider(
        turns=[
            _tool_turn("write", {"file_path": "out.txt", "content": "yo"}),
            _text_turn("ok"),
        ]
    )
    _patch_build_provider._provider = provider

    runner = SessionRunner("tab-3", cfg)
    await runner.start()
    await runner.attach_session(session_id=None, workspace=None)
    await runner.submit("write a file")

    # Drain until we see a confirm_request
    confirm_msg = None
    while confirm_msg is None:
        msg = await asyncio.wait_for(runner.outbound.get(), timeout=3.0)
        if msg["type"] == "confirm_request":
            confirm_msg = msg

    assert confirm_msg["tool_name"] == "write"
    request_id = confirm_msg["request_id"]

    await runner.deliver_confirm_response(request_id, approved=True, always=False)

    # Eventually we should see tool_result with ok=True
    saw_ok_result = False
    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline and not saw_ok_result:
        try:
            msg = await asyncio.wait_for(runner.outbound.get(), timeout=1.0)
        except TimeoutError:
            break
        if msg["type"] == "tool_result":
            saw_ok_result = msg["tool_result"]["ok"]
            break

    assert saw_ok_result, "Tool did not execute after confirm approval"
    assert (tmp_path / "out.txt").read_text() == "yo"
    await runner.close()


async def test_runner_confirm_always_auto_approves(tmp_path, _patch_build_provider):
    cfg = _config(tmp_path).model_copy(
        update={
            "permissions": PermissionsConfig(
                file_read="allow", file_write="ask", bash="allow",
            )
        }
    )
    provider = MockProvider(
        turns=[
            _tool_turn("write", {"file_path": "a.txt", "content": "1"}),
            _tool_turn("write", {"file_path": "b.txt", "content": "2"}),
            _text_turn("done"),
        ]
    )
    _patch_build_provider._provider = provider

    runner = SessionRunner("tab-4", cfg)
    await runner.start()
    await runner.attach_session(session_id=None, workspace=None)
    await runner.submit("turn 1")

    # First write: confirm with always=True
    rid = None
    while rid is None:
        msg = await asyncio.wait_for(runner.outbound.get(), timeout=3.0)
        if msg["type"] == "confirm_request":
            rid = msg["request_id"]
    await runner.deliver_confirm_response(rid, approved=True, always=True)

    # Second submit must NOT produce a confirm_request
    await runner.submit("turn 2")
    saw_second_confirm = False
    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            msg = await asyncio.wait_for(runner.outbound.get(), timeout=0.5)
        except TimeoutError:
            break
        if msg["type"] == "confirm_request":
            saw_second_confirm = True
            break

    assert not saw_second_confirm, "always-allow should suppress second prompt"
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()
    await runner.close()


async def test_runner_deny_blocks_tool(tmp_path, _patch_build_provider):
    cfg = _config(tmp_path).model_copy(
        update={
            "permissions": PermissionsConfig(
                file_read="allow", file_write="ask", bash="allow",
            )
        }
    )
    provider = MockProvider(
        turns=[
            _tool_turn("write", {"file_path": "no.txt", "content": "x"}),
            _text_turn("ack"),
        ]
    )
    _patch_build_provider._provider = provider

    runner = SessionRunner("tab-5", cfg)
    await runner.start()
    await runner.attach_session(session_id=None, workspace=None)
    await runner.submit("try write")

    rid = None
    while rid is None:
        msg = await asyncio.wait_for(runner.outbound.get(), timeout=3.0)
        if msg["type"] == "confirm_request":
            rid = msg["request_id"]
    await runner.deliver_confirm_response(rid, approved=False, always=False)

    # Drain rest; file must not exist
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            await asyncio.wait_for(runner.outbound.get(), timeout=0.3)
        except TimeoutError:
            break

    assert not (tmp_path / "no.txt").exists()
    await runner.close()


# ─── _to_wire pure-function tests ─────────────────────────────────


def test_to_wire_text_delta() -> None:
    w = _to_wire(AgentEvent(kind=EventKind.TEXT_DELTA, text="hi"))
    assert w.type == "text_delta"


def test_to_wire_truncates_huge_tool_output() -> None:
    big = "x" * 100_000
    tr = ToolResult(call_id="c", tool="bash", ok=True, content=big)
    w = _to_wire(AgentEvent(kind=EventKind.TOOL_RESULT, tool_result=tr))
    assert "truncated" in w.tool_result.content
    assert len(w.tool_result.content) < 35_000


def test_to_wire_preserves_short_tool_output() -> None:
    tr = ToolResult(call_id="c", tool="bash", ok=True, content="short")
    w = _to_wire(AgentEvent(kind=EventKind.TOOL_RESULT, tool_result=tr))
    assert w.tool_result.content == "short"


def test_to_wire_usage() -> None:
    w = _to_wire(AgentEvent(kind=EventKind.USAGE, usage=Usage(prompt_tokens=1)))
    assert w.type == "usage"
    assert w.usage.prompt_tokens == 1


def test_to_wire_turn_end_passes_reason() -> None:
    w = _to_wire(AgentEvent(kind=EventKind.TURN_END, finish_reason="stop"))
    assert w.finish_reason == "stop"


def test_to_wire_error() -> None:
    w = _to_wire(AgentEvent(kind=EventKind.ERROR, error="boom"))
    assert w.error == "boom"
