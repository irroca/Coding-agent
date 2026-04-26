"""Tests for the tool orchestrator — permission checks, error isolation, parallel exec."""

from __future__ import annotations

from pathlib import Path

from coding_agent.agent.orchestrator import execute_tool_calls
from coding_agent.core.config import PermissionsConfig
from coding_agent.core.types import ToolCall
from coding_agent.security.audit import AuditLog
from coding_agent.security.permissions import PermissionEngine
from coding_agent.security.rules import RuleSet
from coding_agent.tools.base import ToolContext


def _ctx(ws: Path) -> ToolContext:
    return ToolContext(workspace=ws)


def _call(name: str, args: dict | None = None, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args or {})


def _engine(defaults: dict | None = None) -> PermissionEngine:
    cfg = PermissionsConfig(**(defaults or {}))
    return PermissionEngine(cfg, RuleSet())


# ── Unknown tool ───────────────────────────────────────────────────────


async def test_unknown_tool_returns_error(tmp_path: Path) -> None:
    results = await execute_tool_calls(
        [_call("does_not_exist")], _ctx(tmp_path),
    )
    assert len(results) == 1
    assert not results[0].ok
    assert "Unknown tool" in results[0].content


# ── Empty call list ────────────────────────────────────────────────────


async def test_empty_calls_returns_empty(tmp_path: Path) -> None:
    results = await execute_tool_calls([], _ctx(tmp_path))
    assert results == []


# ── Validation error ───────────────────────────────────────────────────


async def test_invalid_params_returns_error(tmp_path: Path) -> None:
    results = await execute_tool_calls(
        [_call("read", {"nonexistent_param": 42})], _ctx(tmp_path),
    )
    assert len(results) == 1
    assert not results[0].ok
    assert "Invalid arguments" in results[0].content


# ── Successful tool execution ──────────────────────────────────────────


async def test_read_tool_success(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("world")
    results = await execute_tool_calls(
        [_call("read", {"file_path": "hello.txt"})], _ctx(tmp_path),
    )
    assert len(results) == 1
    assert results[0].ok
    assert "world" in results[0].content


# ── Permission engine: DENY ────────────────────────────────────────────


async def test_permission_deny_blocks_tool(tmp_path: Path) -> None:
    engine = _engine({"file_write": "deny"})
    results = await execute_tool_calls(
        [_call("write", {"file_path": "x.txt", "content": "y"})],
        _ctx(tmp_path),
        permission_engine=engine,
    )
    assert len(results) == 1
    assert not results[0].ok
    assert "denied" in results[0].content.lower()


# ── Permission engine: ASK + confirm callback ─────────────────────────


async def test_permission_ask_approved(tmp_path: Path) -> None:
    engine = _engine({"file_write": "ask"})

    async def _approve(name, summary, diff):
        return True

    (tmp_path / "f.txt").write_text("old")
    results = await execute_tool_calls(
        [_call("write", {"file_path": "f.txt", "content": "new"})],
        _ctx(tmp_path),
        confirm=_approve,
        permission_engine=engine,
    )
    assert results[0].ok


async def test_permission_ask_denied(tmp_path: Path) -> None:
    engine = _engine({"file_write": "ask"})

    async def _deny(name, summary, diff):
        return False

    results = await execute_tool_calls(
        [_call("write", {"file_path": "f.txt", "content": "new"})],
        _ctx(tmp_path),
        confirm=_deny,
        permission_engine=engine,
    )
    assert not results[0].ok
    assert "denied" in results[0].content.lower()


# ── Permission engine: ALLOW skips confirm ─────────────────────────────


async def test_permission_allow_skips_confirm(tmp_path: Path) -> None:
    engine = _engine({"file_read": "allow"})
    (tmp_path / "x.txt").write_text("data")

    confirm_called = False

    async def _should_not_be_called(name, summary, diff):
        nonlocal confirm_called
        confirm_called = True
        return True

    results = await execute_tool_calls(
        [_call("read", {"file_path": "x.txt"})],
        _ctx(tmp_path),
        confirm=_should_not_be_called,
        permission_engine=engine,
    )
    assert results[0].ok
    assert not confirm_called


# ── Audit log integration ──────────────────────────────────────────────


async def test_audit_log_records_decisions(tmp_path: Path) -> None:
    engine = _engine({"file_read": "allow"})
    audit = AuditLog(path=tmp_path / "audit.log")
    (tmp_path / "a.txt").write_text("hi")

    await execute_tool_calls(
        [_call("read", {"file_path": "a.txt"})],
        _ctx(tmp_path),
        permission_engine=engine,
        audit_log=audit,
    )
    log_file = tmp_path / "audit.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "read" in content


# ── Parallel execution ─────────────────────────────────────────────────


async def test_parallel_execution(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")

    results = await execute_tool_calls(
        [
            _call("read", {"file_path": "a.txt"}, call_id="c1"),
            _call("read", {"file_path": "b.txt"}, call_id="c2"),
        ],
        _ctx(tmp_path),
        parallel=True,
    )
    assert len(results) == 2
    assert all(r.ok for r in results)


async def test_sequential_execution(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("seq")

    results = await execute_tool_calls(
        [_call("read", {"file_path": "a.txt"})],
        _ctx(tmp_path),
        parallel=False,
    )
    assert len(results) == 1
    assert results[0].ok


# ── Fallback confirm without engine ────────────────────────────────────


async def test_no_engine_fallback_asks_for_writes(tmp_path: Path) -> None:
    asked = False

    async def _track(name, summary, diff):
        nonlocal asked
        asked = True
        return True

    results = await execute_tool_calls(
        [_call("write", {"file_path": "x.txt", "content": "y"})],
        _ctx(tmp_path),
        confirm=_track,
    )
    assert asked
    assert results[0].ok


async def test_no_engine_fallback_deny_writes(tmp_path: Path) -> None:
    async def _deny(name, summary, diff):
        return False

    results = await execute_tool_calls(
        [_call("write", {"file_path": "x.txt", "content": "y"})],
        _ctx(tmp_path),
        confirm=_deny,
    )
    assert not results[0].ok


# ── Tool runtime exception isolation ──────────────────────────────────


async def test_tool_runtime_error_isolated(tmp_path: Path) -> None:
    results = await execute_tool_calls(
        [_call("read", {"file_path": "nonexistent_file_xyz.txt"})],
        _ctx(tmp_path),
    )
    assert len(results) == 1
    assert not results[0].ok


# ── Confirm callback with diff preview ─────────────────────────────────


async def test_confirm_receives_diff_preview(tmp_path: Path) -> None:
    engine = _engine({"file_write": "ask"})
    (tmp_path / "e.txt").write_text("old content")
    received_diff = None

    async def _capture(name, summary, diff):
        nonlocal received_diff
        received_diff = diff
        return True

    results = await execute_tool_calls(
        [_call("edit", {
            "file_path": "e.txt",
            "old_string": "old content",
            "new_string": "new content",
        })],
        _ctx(tmp_path),
        confirm=_capture,
        permission_engine=engine,
    )
    assert results[0].ok
    assert received_diff is not None
    assert "old content" in received_diff
