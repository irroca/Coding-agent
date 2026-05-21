"""REST routes for the browser UI.

Stateless GETs that don't need WebSocket push: session list/load/delete,
workspace listing, tool inventory, config snapshot (without API keys).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platformdirs import user_config_dir
from pydantic import BaseModel

from coding_agent.core.config import Config
from coding_agent.core.session import Session
from coding_agent.tools.base import all_tools
from coding_agent.web.runner import session_summary_payload

if TYPE_CHECKING:
    from fastapi import FastAPI


def _state_path() -> Path:
    p = Path(user_config_dir("coding_agent"))
    p.mkdir(parents=True, exist_ok=True)
    return p / "web-state.json"


def _load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {"recent_workspaces": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"recent_workspaces": []}


def _save_state(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_workspace(path: Path) -> None:
    """Bump the given workspace to the top of the recent list."""
    state = _load_state()
    recent: list[dict[str, Any]] = state.get("recent_workspaces", [])
    norm = str(path.expanduser().resolve())
    recent = [r for r in recent if r.get("path") != norm]
    recent.insert(0, {"path": norm, "last_used": datetime.now().isoformat()})
    state["recent_workspaces"] = recent[:20]
    _save_state(state)


class WorkspaceItem(BaseModel):
    path: str
    last_used: str | None = None


class WorkspaceListResponse(BaseModel):
    current: str
    recent: list[WorkspaceItem]


def register(app: FastAPI, config: Config) -> None:
    """Mount all REST routes on the given app."""
    from fastapi import HTTPException

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        provider_cfg = config.providers.get(config.provider)
        return {
            "provider": config.provider,
            "model": provider_cfg.model if provider_cfg else None,
            "workspace": str(config.workspace),
            "supports_prompt_cache": bool(
                provider_cfg and provider_cfg.supports_prompt_cache
            ),
            "version": _version(),
        }

    @app.get("/api/sessions")
    def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for sid, ts in Session.list_recent(limit=limit):
            out.append(session_summary_payload(sid, ts))
        return out

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            s = Session.load(session_id)
        except FileNotFoundError:
            raise HTTPException(404, f"Session not found: {session_id}") from None
        return s.model_dump(mode="json")

    @app.delete("/api/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str) -> None:
        from coding_agent.core.session import _sessions_dir

        path = _sessions_dir() / f"{session_id}.json"
        if not path.exists():
            raise HTTPException(404, f"Session not found: {session_id}")
        path.unlink()

    @app.get("/api/workspaces", response_model=WorkspaceListResponse)
    def list_workspaces() -> WorkspaceListResponse:
        state = _load_state()
        recent_raw = state.get("recent_workspaces", [])
        return WorkspaceListResponse(
            current=str(config.workspace),
            recent=[
                WorkspaceItem(path=r["path"], last_used=r.get("last_used"))
                for r in recent_raw
                if Path(r["path"]).exists()
            ],
        )

    @app.get("/api/tools")
    def list_tools() -> list[dict[str, Any]]:
        out = []
        for tool_cls in all_tools().values():
            try:
                schema = tool_cls.schema()
            except Exception:
                schema = None
            out.append(
                {
                    "name": tool_cls.name,
                    "description": tool_cls.description,
                    "parameters": schema.parameters if schema else {},
                }
            )
        return sorted(out, key=lambda d: d["name"])


def _version() -> str:
    try:
        from coding_agent import __version__

        return __version__
    except Exception:
        return "unknown"
