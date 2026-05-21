"""Audit logger — append-only JSONL log for all permission-checked actions.

Each entry carries a ``prev_hash`` and ``hash`` field. The ``hash`` is
SHA-256 over the JSON-serialised entry (excluding the ``hash`` field itself)
concatenated with the previous entry's ``hash``. This forms a tamper-evident
chain: any silent edit to a line will break ``hash == sha256(content + prev_hash)``
on every subsequent line, and ``AuditLog.verify_chain()`` returns the index
of the first break.

Secrets passing through the ``summary`` / ``reason`` / ``command`` fields
are redacted via ``security.secrets.redact`` *before* hashing, so a leaked
``sk-…`` in a previous session can never be reconstructed from the audit log.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from platformdirs import user_data_dir

from coding_agent.core.logging import get_logger
from coding_agent.security.rules import Decision
from coding_agent.security.secrets import redact
from coding_agent.tools.base import PermissionRequest

log = get_logger("security.audit")

GENESIS_HASH = "0" * 64  # sha256 of nothing, used as prev for the first record


def _audit_path() -> Path:
    return Path(user_data_dir("coding_agent")) / "audit.log"


def _hash_entry(entry: dict, prev_hash: str) -> str:
    """Stable hash of the entry content plus the previous hash."""
    payload = json.dumps(
        {k: v for k, v in entry.items() if k != "hash"},
        sort_keys=True, separators=(",", ":"),
    )
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(payload.encode("utf-8"))
    return h.hexdigest()


class AuditLog:
    """Writes one JSON line per permission-checked action.

    Each line carries a hash chain so silent edits to historical records can
    be detected via ``verify_chain``. Secrets are redacted before hashing.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _audit_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        """Read the tail to find the most recent ``hash`` to chain from.

        On a fresh file we return ``GENESIS_HASH``.
        """
        if not self._path.exists():
            return GENESIS_HASH
        # File can be large in long-lived deployments — read only the last
        # 4 KB and parse the last valid JSON line.
        try:
            with self._path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return GENESIS_HASH

        for line in reversed(tail.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and "hash" in data:
                return str(data["hash"])
        return GENESIS_HASH

    def record(
        self,
        req: PermissionRequest,
        decision: Decision,
        reason: str,
        *,
        session_id: str = "",
    ) -> None:
        entry: dict = {
            "ts": time.time(),
            "session": session_id,
            "tool": req.tool,
            "action": req.action,
            "summary": redact(req.summary or ""),
            "decision": str(decision),
            "reason": redact(reason or ""),
        }
        if req.path:
            entry["path"] = req.path
        if req.command:
            entry["command"] = redact(req.command)

        prev = self._last_hash()
        entry["prev_hash"] = prev
        entry["hash"] = _hash_entry(entry, prev)

        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
        except OSError as e:
            log.warning("audit_write_failed", error=str(e))

    def verify_chain(self) -> int | None:
        """Verify the hash chain top-to-bottom.

        Returns ``None`` if every record is consistent; otherwise returns the
        1-based line number of the first bad entry. Lines that don't parse as
        JSON or lack the ``hash`` field are skipped (legacy entries).
        """
        if not self._path.exists():
            return None
        prev = GENESIS_HASH
        with self._path.open(encoding="utf-8") as f:
            for i, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or "hash" not in entry:
                    continue
                expected_prev = entry.get("prev_hash", GENESIS_HASH)
                if expected_prev != prev:
                    return i
                if _hash_entry(entry, prev) != entry["hash"]:
                    return i
                prev = entry["hash"]
        return None
