"""Tool orchestrator — dispatches tool calls with permission checks.

The orchestrator sits between the agent loop and individual tools. For each
tool call the model requests, it:

  1. Resolves the tool class from the registry
  2. Validates parameters
  3. Checks the permission engine (rules → command guard → config defaults)
  4. If "ask" → calls the confirm callback; if "deny" → rejects immediately
  5. Executes the tool (parallel when the model requests multiple calls)
  6. Logs the action to the audit log
  7. Returns ToolResults to be fed back to the model
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from coding_agent.core.errors import (
    PermissionDenied,
    ToolError,
    UserAborted,
)
from coding_agent.core.logging import get_logger
from coding_agent.core.types import ToolCall, ToolResult
from coding_agent.security.audit import AuditLog
from coding_agent.security.permissions import PermissionEngine
from coding_agent.security.rules import Decision
from coding_agent.tools.base import (
    ToolContext,
    all_tools,
    get_tool,
)

log = get_logger("orchestrator")

ConfirmCallback = Callable[[str, str, str | None], Awaitable[bool]]
"""async callback(tool_name, summary, diff_preview) → user approved?"""


async def execute_tool_calls(
    calls: list[ToolCall],
    ctx: ToolContext,
    *,
    confirm: ConfirmCallback | None = None,
    parallel: bool = True,
    permission_engine: PermissionEngine | None = None,
    audit_log: AuditLog | None = None,
) -> list[ToolResult]:
    """Execute a batch of tool calls.

    If *parallel* is True and there are multiple calls, independent ones run
    concurrently via ``asyncio.gather``. Each call is wrapped so that failures
    are isolated — a broken tool does not crash the batch.
    """
    if not calls:
        return []

    async def _run_one(call: ToolCall) -> ToolResult:
        return await execute_single_call(
            call, ctx,
            confirm=confirm,
            permission_engine=permission_engine,
            audit_log=audit_log,
        )

    if parallel and len(calls) > 1:
        results = await asyncio.gather(*[_run_one(c) for c in calls])
        return list(results)

    return [await _run_one(c) for c in calls]


async def execute_single_call(
    call: ToolCall,
    ctx: ToolContext,
    *,
    confirm: ConfirmCallback | None = None,
    permission_engine: PermissionEngine | None = None,
    audit_log: AuditLog | None = None,
) -> ToolResult:
    """Public single-call entry point used by streaming dispatch in the loop."""
    return await _execute_single(
        call, ctx,
        confirm=confirm,
        permission_engine=permission_engine,
        audit_log=audit_log,
    )


async def _execute_single(
    call: ToolCall,
    ctx: ToolContext,
    *,
    confirm: ConfirmCallback | None = None,
    permission_engine: PermissionEngine | None = None,
    audit_log: AuditLog | None = None,
) -> ToolResult:
    """Execute one tool call with error isolation."""
    tool_cls = get_tool(call.name)
    if tool_cls is None:
        return ToolResult(
            call_id=call.id,
            tool=call.name,
            ok=False,
            content=f"Unknown tool: '{call.name}'. Available: {sorted(all_tools())}",
        )

    tool = tool_cls()

    try:
        params = tool.validate_params(call.arguments)
    except ToolError as e:
        return ToolResult(call_id=call.id, tool=call.name, ok=False, content=str(e))

    perm = tool.permission_request(params)

    # --- Permission check ---
    if permission_engine is not None:
        decision = permission_engine.check(perm)

        if audit_log is not None:
            audit_log.record(
                perm, decision.decision, decision.reason,
                session_id=ctx.session_id,
            )

        if decision.decision == Decision.DENY:
            return ToolResult(
                call_id=call.id,
                tool=call.name,
                ok=False,
                content=f"Permission denied: {decision.reason}",
            )

        if decision.decision == Decision.ASK and confirm is not None:
            diff_preview = None
            if hasattr(tool, "generate_diff"):
                import contextlib

                with contextlib.suppress(Exception):
                    diff_preview = tool.generate_diff(params, ctx)

            try:
                approved = await confirm(call.name, perm.summary, diff_preview)
            except UserAborted:
                return ToolResult(
                    call_id=call.id, tool=call.name, ok=False,
                    content="User denied this action.",
                )
            if not approved:
                return ToolResult(
                    call_id=call.id, tool=call.name, ok=False,
                    content="User denied this action.",
                )
    else:
        # Fallback: no engine → ask for all writes/bash
        if perm.action in ("file_write", "bash") and confirm is not None:
            diff_preview = None
            if hasattr(tool, "generate_diff"):
                import contextlib

                with contextlib.suppress(Exception):
                    diff_preview = tool.generate_diff(params, ctx)

            try:
                approved = await confirm(call.name, perm.summary, diff_preview)
            except UserAborted:
                return ToolResult(
                    call_id=call.id, tool=call.name, ok=False,
                    content="User denied this action.",
                )
            if not approved:
                return ToolResult(
                    call_id=call.id, tool=call.name, ok=False,
                    content="User denied this action.",
                )

    try:
        result = await tool.run(params, ctx)
        result.call_id = call.id
        return result
    except PermissionDenied as e:
        return ToolResult(
            call_id=call.id,
            tool=call.name,
            ok=False,
            content=f"Permission denied: {e.reason}",
        )
    except ToolError as e:
        return ToolResult(call_id=call.id, tool=call.name, ok=False, content=str(e))
    except Exception as e:
        log.error("tool_execution_error", tool=call.name, error=str(e), exc_info=True)
        return ToolResult(
            call_id=call.id,
            tool=call.name,
            ok=False,
            content=f"Internal error running '{call.name}': {type(e).__name__}: {e}",
        )
