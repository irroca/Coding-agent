"""Session state and persistence.

A Session owns the canonical message history for one Agent run, the cumulative
usage stats, and a stable ID. Snapshots are written as JSON to
``<data_dir>/sessions/<id>.json`` after every turn so the user can ``--resume``
even if the process crashes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from platformdirs import user_data_dir
from pydantic import BaseModel, Field

from coding_agent.core.types import Message, Role, ToolCall, ToolResult, Usage


def _sessions_dir() -> Path:
    p = Path(user_data_dir("coding_agent")) / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _new_session_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{uuid4().hex[:8]}"


class Session(BaseModel):
    id: str = Field(default_factory=_new_session_id)
    workspace: str
    provider: str
    model: str
    messages: list[Message] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_system(self, content: str) -> None:
        self.messages.append(Message(role=Role.SYSTEM, content=content))

    def add_user(self, content: str) -> None:
        self.messages.append(Message(role=Role.USER, content=content))

    def add_assistant(
        self,
        content: str,
        tool_calls: list[ToolCall] | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        self.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=tool_calls or [],
                reasoning_content=reasoning_content,
            )
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        if not results:
            return
        self.messages.append(Message(role=Role.TOOL, tool_results=results))

    def accumulate_usage(self, u: Usage) -> None:
        self.usage = Usage(
            prompt_tokens=self.usage.prompt_tokens + u.prompt_tokens,
            completion_tokens=self.usage.completion_tokens + u.completion_tokens,
            cached_prompt_tokens=self.usage.cached_prompt_tokens + u.cached_prompt_tokens,
        )

    def snapshot_path(self) -> Path:
        return _sessions_dir() / f"{self.id}.json"

    def save(self, *, redact_secrets: bool = True) -> Path:
        """Persist the session to disk.

        When ``redact_secrets`` is true (the default) every message content
        and tool-result payload is scanned and any detected API keys are
        replaced with ``<kind:abcd…xy>`` placeholders **in the serialised
        copy only** — the in-memory ``Session`` is unchanged so the live
        conversation continues with full fidelity. This guarantees that a
        leaked key never lands on disk in ``sessions/*.json``.
        """
        path = self.snapshot_path()
        if redact_secrets:
            from coding_agent.security.secrets import redact

            payload = self.model_dump(mode="json")
            for msg in payload.get("messages", []):
                if isinstance(msg.get("content"), str):
                    msg["content"] = redact(msg["content"])
                if isinstance(msg.get("reasoning_content"), str):
                    msg["reasoning_content"] = redact(msg["reasoning_content"])
                for r in msg.get("tool_results") or []:
                    if isinstance(r.get("content"), str):
                        r["content"] = redact(r["content"])
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        else:
            path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, session_id: str) -> Session:
        path = _sessions_dir() / f"{session_id}.json"
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @classmethod
    def list_recent(cls, limit: int = 20) -> list[tuple[str, datetime]]:
        files = sorted(_sessions_dir().glob("*.json"), reverse=True)[:limit]
        out: list[tuple[str, datetime]] = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append((data["id"], datetime.fromisoformat(data["created_at"])))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return out
