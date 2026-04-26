"""Audit logger — append-only JSONL log for all permission-checked actions."""

from __future__ import annotations

import json
import time
from pathlib import Path

from platformdirs import user_data_dir

from coding_agent.core.logging import get_logger
from coding_agent.security.rules import Decision
from coding_agent.tools.base import PermissionRequest

log = get_logger("security.audit")


def _audit_path() -> Path:
    return Path(user_data_dir("coding_agent")) / "audit.log"


class AuditLog:
    """Writes one JSON line per permission-checked action."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _audit_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        req: PermissionRequest,
        decision: Decision,
        reason: str,
        *,
        session_id: str = "",
    ) -> None:
        entry = {
            "ts": time.time(),
            "session": session_id,
            "tool": req.tool,
            "action": req.action,
            "summary": req.summary,
            "decision": str(decision),
            "reason": reason,
        }
        if req.path:
            entry["path"] = req.path
        if req.command:
            entry["command"] = req.command

        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            log.warning("audit_write_failed", error=str(e))
