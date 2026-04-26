"""Tests for audit log."""

from __future__ import annotations

import json
from pathlib import Path

from coding_agent.security.audit import AuditLog
from coding_agent.security.rules import Decision
from coding_agent.tools.base import PermissionRequest


def test_audit_writes_jsonl(tmp_path: Path) -> None:
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    req = PermissionRequest(
        tool="bash", action="bash",
        summary="Run: echo hello",
        command="echo hello",
    )
    audit.record(req, Decision.ALLOW, "Config default", session_id="s-123")

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "bash"
    assert entry["decision"] == "allow"
    assert entry["session"] == "s-123"
    assert entry["command"] == "echo hello"


def test_audit_multiple_entries(tmp_path: Path) -> None:
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    for i in range(3):
        req = PermissionRequest(
            tool="write", action="file_write",
            summary=f"Write file {i}",
            path=f"file{i}.py",
        )
        audit.record(req, Decision.ASK, "test")

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 3


def test_audit_includes_path(tmp_path: Path) -> None:
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    req = PermissionRequest(
        tool="write", action="file_write",
        summary="Write", path="src/main.py",
    )
    audit.record(req, Decision.ALLOW, "rule")

    entry = json.loads(log_file.read_text().strip())
    assert entry["path"] == "src/main.py"


def test_audit_no_path_or_command(tmp_path: Path) -> None:
    log_file = tmp_path / "audit.log"
    audit = AuditLog(path=log_file)

    req = PermissionRequest(tool="read", action="file_read", summary="Read")
    audit.record(req, Decision.ALLOW, "default")

    entry = json.loads(log_file.read_text().strip())
    assert "path" not in entry
    assert "command" not in entry
