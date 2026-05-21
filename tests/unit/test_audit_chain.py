"""Tests for the audit log hash chain.

The chain is what makes the audit log tamper-evident: any silent edit to
a historical line invalidates every line below it. ``verify_chain`` should
flag the first broken record, and secrets in summary/reason/command must
be redacted *before* being hashed (so a leaked key cannot be reconstructed
from the audit log).
"""

from __future__ import annotations

import json
from pathlib import Path

from coding_agent.security.audit import GENESIS_HASH, AuditLog
from coding_agent.security.rules import Decision
from coding_agent.tools.base import PermissionRequest


def _req(tool: str = "bash", command: str = "ls") -> PermissionRequest:
    return PermissionRequest(
        tool=tool, action="bash" if tool == "bash" else "file_write",
        summary=f"Run: {command}", command=command,
    )


def test_first_entry_chains_from_genesis(tmp_path: Path) -> None:
    log = AuditLog(path=tmp_path / "audit.log")
    log.record(_req(command="echo hi"), Decision.ALLOW, "ok")

    line = (tmp_path / "audit.log").read_text().strip()
    entry = json.loads(line)
    assert entry["prev_hash"] == GENESIS_HASH
    assert len(entry["hash"]) == 64  # sha256 hex


def test_subsequent_entry_chains_from_previous(tmp_path: Path) -> None:
    log = AuditLog(path=tmp_path / "audit.log")
    log.record(_req(command="echo a"), Decision.ALLOW, "a")
    log.record(_req(command="echo b"), Decision.ALLOW, "b")

    lines = (tmp_path / "audit.log").read_text().strip().splitlines()
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert second["prev_hash"] == first["hash"]


def test_verify_chain_returns_none_when_valid(tmp_path: Path) -> None:
    log = AuditLog(path=tmp_path / "audit.log")
    for i in range(5):
        log.record(_req(command=f"step {i}"), Decision.ALLOW, "ok")
    assert log.verify_chain() is None


def test_verify_chain_detects_tampered_field(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    log = AuditLog(path=path)
    for i in range(3):
        log.record(_req(command=f"cmd {i}"), Decision.ALLOW, "ok")

    # Silently edit the 2nd record's `reason`. The hash on line 2 will then
    # mismatch (because reason changed), so verify_chain returns 2.
    lines = path.read_text().splitlines()
    second = json.loads(lines[1])
    second["reason"] = "tampered"
    lines[1] = json.dumps(second, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")

    assert log.verify_chain() == 2


def test_verify_chain_detects_deleted_record(tmp_path: Path) -> None:
    """Removing line 2 breaks line 3's prev_hash linkage."""
    path = tmp_path / "audit.log"
    log = AuditLog(path=path)
    for i in range(3):
        log.record(_req(command=f"cmd {i}"), Decision.ALLOW, "ok")

    lines = path.read_text().splitlines()
    # Drop the middle entry — now line "2" (originally 3) expects line 1's
    # hash but carries line 2's old prev_hash, so the check fires.
    path.write_text(lines[0] + "\n" + lines[2] + "\n")

    assert log.verify_chain() == 2


def test_audit_redacts_secrets_in_summary_and_reason(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    log = AuditLog(path=path)

    secret = "sk-abcdEFGHij1234567890klMN"
    req = PermissionRequest(
        tool="bash", action="bash",
        summary=f"Run: curl -H 'Authorization: Bearer {secret}' https://x",
        command=f"curl -H 'Authorization: Bearer {secret}' https://x",
    )
    log.record(req, Decision.ASK, f"matched rule mentioning {secret}")

    raw = path.read_text()
    # The literal secret must be gone from disk.
    assert secret not in raw
    # The redaction marker must be present.
    assert "<openai:sk-a" in raw


def test_audit_chain_survives_redacted_secrets(tmp_path: Path) -> None:
    """Hashing happens *after* redaction, so chain verification still passes."""
    path = tmp_path / "audit.log"
    log = AuditLog(path=path)

    secret = "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ"
    log.record(
        PermissionRequest(
            tool="bash", action="bash",
            summary=f"Run: echo {secret}",
            command=f"echo {secret}",
        ),
        Decision.ALLOW,
        "ok",
    )
    log.record(
        PermissionRequest(tool="read", action="file_read", summary="Read x"),
        Decision.ALLOW, "default",
    )
    assert log.verify_chain() is None


def test_last_hash_resumes_after_reopen(tmp_path: Path) -> None:
    """A second AuditLog instance must continue the chain, not restart it."""
    path = tmp_path / "audit.log"
    AuditLog(path=path).record(_req(command="first"), Decision.ALLOW, "ok")
    AuditLog(path=path).record(_req(command="second"), Decision.ALLOW, "ok")

    lines = path.read_text().splitlines()
    assert json.loads(lines[1])["prev_hash"] == json.loads(lines[0])["hash"]
    assert AuditLog(path=path).verify_chain() is None
