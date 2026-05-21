"""FastAPI app + WebSocket handler + uvicorn entry.

Architecture:

* One FastAPI app, one ``Config``, shared by every connection.
* Per-WS ``SessionRunner`` (see :mod:`coding_agent.web.runner`).
* Static SPA served from ``static/`` — built by ``frontend/`` and shipped
  inside the wheel via the ``force-include`` rule in ``pyproject.toml``.

Bind defaults to 127.0.0.1. There is no auth; do not expose the port.
"""

# NOTE: deliberately no ``from __future__ import annotations`` — FastAPI's
# routing introspection requires real classes for WebSocket parameter
# detection, and PEP-563 string annotations break that.

import asyncio
import importlib.resources
import json
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from coding_agent.core.config import Config, load_config, reset_config_cache
from coding_agent.core.logging import configure_logging, get_logger
from coding_agent.web.protocol import (
    Ack,
    AttachSession,
    Cancel,
    ConfirmResponse,
    DeleteSession,
    ListSessions,
    ListWorkspaces,
    ServerError,
    SessionList,
    SessionSummary,
    Submit,
    WorkspaceInfo,
    WorkspaceList,
    parse_client_message,
)
from coding_agent.web.routes import (
    _load_state,
    record_workspace,
)
from coding_agent.web.routes import (
    register as register_routes,
)
from coding_agent.web.runner import SessionRunner, session_summary_payload

log = get_logger("web.server")


def _static_dir() -> Path:
    """Locate the bundled SPA inside the installed package."""
    return Path(str(importlib.resources.files("coding_agent.web") / "static"))


def create_app(config: Config) -> FastAPI:
    """Build the FastAPI application bound to one ``Config``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from coding_agent.plugins import load_plugins

        summary = load_plugins()
        if any(summary.values()):
            log.info("plugins_loaded", **summary)
        record_workspace(config.workspace)
        yield

    app = FastAPI(title="Coding Agent", lifespan=lifespan, openapi_url=None)
    app.state.config = config

    register_routes(app, config)

    @app.websocket("/ws/{tab_id}")
    async def ws_endpoint(websocket: WebSocket, tab_id: str) -> None:
        await _serve_ws(websocket, tab_id, config)

    static = _static_dir()
    if static.exists():
        assets_dir = static / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="assets",
            )

        @app.get("/")
        async def index() -> Any:
            idx = static / "index.html"
            if idx.exists():
                return FileResponse(str(idx))
            return PlainTextResponse(
                "Frontend not built. Run `cd frontend && pnpm install && pnpm build`.",
                status_code=503,
            )

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> Any:
            if full_path.startswith(("api/", "ws/", "assets/")):
                return PlainTextResponse("Not found", status_code=404)
            idx = static / "index.html"
            if idx.exists():
                return FileResponse(str(idx))
            return PlainTextResponse("Not found", status_code=404)

    return app


async def _serve_ws(websocket: WebSocket, tab_id: str, config: Config) -> None:
    await websocket.accept()
    runner = SessionRunner(tab_id=tab_id, config=config)
    await runner.start()
    try:
        await runner.attach_session(session_id=None, workspace=None)
    except Exception as e:
        log.error("ws_initial_attach_failed", error=str(e))
        await websocket.send_text(
            ServerError(message=f"Boot failed: {e}", recoverable=False).model_dump_json()
        )
        await websocket.close()
        return

    sender = asyncio.create_task(_sender_loop(websocket, runner))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = parse_client_message(json.loads(raw))
            except Exception as e:
                await runner.outbound.put(
                    ServerError(message=f"Bad message: {e}").model_dump(mode="json")
                )
                continue
            await _handle_client_message(msg, runner)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("ws_loop_error", error=str(e), exc_info=True)
    finally:
        sender.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await sender
        await runner.close()


async def _sender_loop(websocket: WebSocket, runner: SessionRunner) -> None:
    """Forward everything the runner enqueues to the WebSocket."""
    while True:
        msg = await runner.outbound.get()
        try:
            await websocket.send_text(json.dumps(msg, default=str))
        except Exception:
            return


async def _handle_client_message(msg: Any, runner: SessionRunner) -> None:
    if isinstance(msg, Submit):
        try:
            await runner.submit(msg.text)
            await runner.outbound.put(Ack(of="submit").model_dump(mode="json"))
        except Exception as e:
            await runner.outbound.put(
                ServerError(message=str(e)).model_dump(mode="json")
            )
    elif isinstance(msg, Cancel):
        runner.cancel()
        await runner.outbound.put(Ack(of="cancel").model_dump(mode="json"))
    elif isinstance(msg, ConfirmResponse):
        await runner.deliver_confirm_response(msg.request_id, msg.approved, msg.always)
    elif isinstance(msg, AttachSession):
        try:
            await runner.attach_session(msg.session_id, msg.workspace)
            if msg.workspace:
                record_workspace(Path(msg.workspace).expanduser().resolve())
        except Exception as e:
            await runner.outbound.put(
                ServerError(message=f"attach_session failed: {e}").model_dump(mode="json")
            )
    elif isinstance(msg, DeleteSession):
        from coding_agent.core.session import _sessions_dir

        path = _sessions_dir() / f"{msg.session_id}.json"
        if path.exists():
            path.unlink()
        await runner.outbound.put(
            Ack(of="delete_session", detail={"id": msg.session_id}).model_dump(mode="json")
        )
        await _emit_session_list(runner)
    elif isinstance(msg, ListSessions):
        await _emit_session_list(runner)
    elif isinstance(msg, ListWorkspaces):
        state = _load_state()
        recent_raw = state.get("recent_workspaces", [])
        recent: list[WorkspaceInfo] = []
        for r in recent_raw:
            p = Path(r["path"])
            if not p.exists():
                continue
            last_used: datetime | None = None
            if r.get("last_used"):
                with suppress(Exception):
                    last_used = datetime.fromisoformat(r["last_used"])
            recent.append(WorkspaceInfo(path=str(p), last_used=last_used))
        await runner.outbound.put(
            WorkspaceList(
                current=str(runner.config.workspace), recent=recent
            ).model_dump(mode="json")
        )


async def _emit_session_list(runner: SessionRunner) -> None:
    from coding_agent.core.session import Session

    summaries = []
    for sid, ts in Session.list_recent(limit=50):
        d = session_summary_payload(sid, ts)
        summaries.append(SessionSummary(**d))
    await runner.outbound.put(SessionList(sessions=summaries).model_dump(mode="json"))


def run(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace: Path | None = None,
    open_browser: bool = True,
) -> None:
    """Entry point used by the ``coding-agent web`` CLI subcommand."""
    import uvicorn

    reset_config_cache()
    config = load_config()
    configure_logging(config.log_level)

    if workspace is not None:
        ws = workspace.expanduser().resolve()
        if not ws.is_dir():
            raise SystemExit(f"Workspace is not a directory: {ws}")
        config = config.model_copy(update={"workspace": ws})

    url = f"http://{host}:{port}"
    log.info("web_starting", url=url, workspace=str(config.workspace))
    print(f"\n  Coding Agent web UI starting on {url}")
    print(f"  Workspace: {config.workspace}")
    if host not in {"127.0.0.1", "localhost"}:
        print("  ⚠ Warning: binding to non-loopback; there is no authentication.")
    print()

    app = create_app(config)

    if open_browser:
        with suppress(Exception):
            webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="warning")
