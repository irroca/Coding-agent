"""SessionRunner — owns one Agent + Session per browser tab.

The runner is a thin coordinator. It does NOT do any rendering, networking,
or persistence beyond what already exists in ``Session.save()``. It:

1. Holds a single ``Agent`` instance plus the underlying ``Session``.
2. Accepts user submits via :meth:`submit`, draining them serially.
3. Pumps every ``AgentEvent`` into an outbound ``asyncio.Queue`` that the
   WebSocket handler forwards to the browser.
4. Resolves permission prompts by sending ``ConfirmRequest`` to the browser
   and awaiting the matching ``ConfirmResponse`` via a future map.

Switching session or workspace tears down the agent and rebuilds it cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from coding_agent.agent.loop import Agent, AgentEvent, EventKind
from coding_agent.core.config import Config
from coding_agent.core.logging import get_logger
from coding_agent.core.session import Session
from coding_agent.providers.base import LLMProvider
from coding_agent.providers.registry import build_provider
from coding_agent.web.protocol import (
    ConfirmRequest,
    ErrorEvent,
    SessionMessageSnapshot,
    SessionState,
    TextDeltaEvent,
    ToolResultEvent,
    ToolStartEvent,
    TurnEndEvent,
    UsageEvent,
)

log = get_logger("web.runner")


_CONFIRM_TIMEOUT_SECONDS = 300.0
"""How long to wait for the browser to respond to a permission prompt
before defaulting to deny. 5 minutes matches typical "step away from
the desk" tolerance."""


class SessionRunner:
    """One per browser tab. Decoupled from the WS transport."""

    def __init__(self, tab_id: str, config: Config) -> None:
        self.tab_id = tab_id
        self.config = config
        self.outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self._submit_queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending_confirms: dict[str, asyncio.Future[tuple[bool, bool]]] = {}
        self._auto_approve: set[str] = set()
        self._worker_task: asyncio.Task[None] | None = None
        self._provider: LLMProvider | None = None
        self._agent: Agent | None = None
        self._session: Session | None = None
        self._workspace: Path = config.workspace
        self._lock = asyncio.Lock()
        """Guards :meth:`attach_session` so we never tear down mid-turn."""

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._worker_loop(), name=f"runner-{self.tab_id}"
            )

    async def close(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._worker_task
            self._worker_task = None
        if self._agent is not None:
            self._agent.cancel()
        if self._provider is not None and hasattr(self._provider, "aclose"):
            with contextlib.suppress(Exception):
                await self._provider.aclose()  # type: ignore[func-returns-value]
        for fut in self._pending_confirms.values():
            if not fut.done():
                fut.set_result((False, False))

    # ── public surface used by the WS handler ───────────────────────

    async def attach_session(
        self,
        session_id: str | None,
        workspace: str | None = None,
    ) -> None:
        """(Re)attach the runner to a session and optionally change workspace.

        Always emits a fresh :class:`SessionState` afterwards so the client
        rerenders.
        """
        async with self._lock:
            if workspace is not None:
                ws = Path(workspace).expanduser().resolve()
                if not ws.is_dir():
                    raise ValueError(f"Workspace is not a directory: {ws}")
                self._workspace = ws

            if self._provider is None:
                self._provider = build_provider(self.config)

            if session_id is None:
                self._session = Session(
                    workspace=str(self._workspace),
                    provider=self.config.provider,
                    model=self._provider.model,
                )
            else:
                self._session = Session.load(session_id)

            # New session ⇒ new auto-approve set (mirrors REPL behaviour:
            # the user re-grants per session).
            self._auto_approve = set()

            agent_config = self.config.model_copy(update={"workspace": self._workspace})
            self._agent = Agent(
                self._provider,
                agent_config,
                self._session,
                confirm=self._confirm,
            )

        await self._emit_session_state()

    async def submit(self, text: str) -> None:
        if self._agent is None or self._session is None:
            raise RuntimeError("No session attached. Send attach_session first.")
        await self._submit_queue.put(text)

    def cancel(self) -> None:
        if self._agent is not None:
            self._agent.cancel()

    async def deliver_confirm_response(
        self, request_id: str, approved: bool, always: bool
    ) -> None:
        fut = self._pending_confirms.get(request_id)
        if fut is None or fut.done():
            log.warning("confirm_response_stale", request_id=request_id)
            return
        fut.set_result((approved, always))

    @property
    def session(self) -> Session | None:
        return self._session

    # ── worker ──────────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        while True:
            text = await self._submit_queue.get()
            if self._agent is None:
                await self._push(
                    ErrorEvent(error="Agent not initialized; attach a session first.")
                )
                continue
            try:
                async for event in self._agent.run(text):
                    await self._push(_to_wire(event))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("runner_turn_error", error=str(e), exc_info=True)
                await self._push(ErrorEvent(error=f"{type(e).__name__}: {e}"))
            finally:
                await self._emit_session_state()

    # ── permission confirm bridge ───────────────────────────────────

    async def _confirm(
        self, tool_name: str, summary: str, diff_preview: str | None
    ) -> bool:
        if tool_name in self._auto_approve:
            return True

        request_id = uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[tuple[bool, bool]] = loop.create_future()
        self._pending_confirms[request_id] = fut
        await self._push(
            ConfirmRequest(
                request_id=request_id,
                tool_name=tool_name,
                summary=summary,
                diff_preview=diff_preview,
            )
        )
        try:
            approved, always = await asyncio.wait_for(
                fut, timeout=_CONFIRM_TIMEOUT_SECONDS
            )
        except TimeoutError:
            log.warning("confirm_timeout", tool=tool_name, request_id=request_id)
            return False
        finally:
            self._pending_confirms.pop(request_id, None)

        if approved and always:
            self._auto_approve.add(tool_name)
        return approved

    # ── helpers ─────────────────────────────────────────────────────

    async def _push(self, message: Any) -> None:
        """Serialise a pydantic message and enqueue for the WS sender."""
        payload = message.model_dump(mode="json")
        try:
            self.outbound.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop oldest to keep up with a slow client; never block the
            # event stream because the browser is laggy.
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = self.outbound.get_nowait()
            self.outbound.put_nowait(payload)

    async def _emit_session_state(self) -> None:
        if self._session is None:
            return
        msgs = [
            SessionMessageSnapshot(
                role=m.role,
                content=m.content,
                reasoning_content=m.reasoning_content,
                tool_calls=list(m.tool_calls),
                tool_results=list(m.tool_results),
                created_at=m.created_at,
            )
            for m in self._session.messages
        ]
        await self._push(
            SessionState(
                session_id=self._session.id,
                workspace=self._session.workspace,
                provider=self._session.provider,
                model=self._session.model,
                messages=msgs,
                usage=self._session.usage,
                created_at=self._session.created_at,
                auto_approved=sorted(self._auto_approve),
            )
        )


_TOOL_CONTENT_LIMIT = 30_000
"""Mirror of ``AgentConfig.tool_output_max_chars`` — protect WS frame size.

We don't reach into config for this because we want the same hard ceiling
regardless of what the user sets there; very large tool outputs hurt the
browser more than the LLM."""


def _to_wire(event: AgentEvent) -> Any:
    """Translate an internal AgentEvent into a wire-format pydantic model."""
    if event.kind == EventKind.TEXT_DELTA:
        return TextDeltaEvent(text=event.text)
    if event.kind == EventKind.TOOL_START:
        assert event.tool_call is not None
        return ToolStartEvent(tool_call=event.tool_call)
    if event.kind == EventKind.TOOL_RESULT:
        assert event.tool_result is not None
        tr = event.tool_result
        if len(tr.content) > _TOOL_CONTENT_LIMIT:
            head = tr.content[: _TOOL_CONTENT_LIMIT // 2]
            tail = tr.content[-_TOOL_CONTENT_LIMIT // 2 :]
            trimmed = tr.model_copy(
                update={
                    "content": (
                        f"{head}\n…[truncated {len(tr.content) - _TOOL_CONTENT_LIMIT} chars]…\n{tail}"
                    )
                }
            )
            return ToolResultEvent(tool_result=trimmed)
        return ToolResultEvent(tool_result=tr)
    if event.kind == EventKind.USAGE:
        assert event.usage is not None
        return UsageEvent(usage=event.usage)
    if event.kind == EventKind.TURN_END:
        return TurnEndEvent(finish_reason=event.finish_reason)
    if event.kind == EventKind.ERROR:
        return ErrorEvent(error=event.error or "Unknown error")
    raise RuntimeError(f"Unknown event kind: {event.kind}")


def first_user_message(session: Session) -> str:
    for m in session.messages:
        if m.role.value == "user" and m.content:
            text = m.content.strip().splitlines()[0] if m.content.strip() else ""
            return text[:80] + ("…" if len(text) > 80 else "")
    return ""


def session_summary_payload(session_id: str, created_at: datetime) -> dict[str, Any]:
    """Cheap summary for the sidebar list — only loads if a title is wanted."""
    try:
        s = Session.load(session_id)
        return {
            "id": session_id,
            "created_at": created_at.isoformat(),
            "title": first_user_message(s) or "(empty)",
            "message_count": len(s.messages),
        }
    except Exception:
        return {
            "id": session_id,
            "created_at": created_at.isoformat(),
            "title": "(unreadable)",
            "message_count": 0,
        }
