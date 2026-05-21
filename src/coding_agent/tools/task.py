"""Task tool — dispatch a sub-agent for independent exploration.

A sub-agent reuses the main `Agent` class with three crucial restrictions:

1. **Read-only tool surface** — it can only call `read`, `ls`, `glob`, `grep`.
   This makes it safe to dispatch on untrusted prompts and keeps the killer
   use-case (scoped exploration) front-and-centre.
2. **No recursion** — a sub-agent cannot itself call `task`. Enforced by
   `ToolContext.is_subagent`.
3. **Capped iteration budget** — `AgentConfig.subagent_max_iterations` (default
   15) is independent of the parent's `max_iterations`.

The sub-agent runs in an **isolated session**: its messages do not pollute the
parent's context. Only the final assistant text is returned to the parent as
the tool result. Tool-call traffic, intermediate text, and reasoning content
stay inside the sub-agent and are dropped.

Token-wise this is a real win: the parent only sees a summary, not the dozens
of `read` results the sub-agent needed to produce it.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.logging import get_logger
from coding_agent.core.session import Session
from coding_agent.core.types import ToolResult
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext

log = get_logger("tools.task")

SUBAGENT_TOOLS: frozenset[str] = frozenset({"read", "ls", "glob", "grep"})


class TaskParams(BaseModel):
    description: str = Field(
        description="Short description of the task (3-5 words).",
    )
    prompt: str = Field(
        description=(
            "Detailed instructions for the sub-agent. Include all context "
            "needed — the sub-agent does not see your conversation history. "
            "Sub-agents can only call read-only tools (read / ls / glob / grep)."
        ),
    )


class TaskTool(Tool):
    name: ClassVar[str] = "task"
    description: ClassVar[str] = (
        "Dispatch an independent sub-agent for read-only exploration. "
        "Use this when you need to investigate a large area of the codebase "
        "without polluting the main conversation with hundreds of file reads. "
        "The sub-agent has access to read / ls / glob / grep only and returns "
        "a single summary string. It cannot make changes."
    )
    Params: ClassVar[type[BaseModel]] = TaskParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, TaskParams)

        if ctx.is_subagent:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=(
                    "Recursive sub-agent dispatch is disabled. "
                    "Handle this work directly within the current sub-agent."
                ),
            )

        if ctx.provider is None or ctx.config is None:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=(
                    "Sub-agent dispatch requires provider/config in ToolContext. "
                    "This is an internal wiring bug."
                ),
            )

        # Import here to avoid circular import (Agent imports ToolContext).
        from coding_agent.agent.loop import Agent, EventKind

        sub_session = Session(
            workspace=str(ctx.workspace),
            provider=ctx.config.provider,
            model=ctx.provider.model,
            metadata={"parent_session_id": ctx.session_id, "task": params.description},
        )

        sub_config = ctx.config.model_copy(deep=False)
        sub_config.agent = ctx.config.agent.model_copy(deep=False)
        sub_config.agent.max_iterations = ctx.config.agent.subagent_max_iterations

        sub_agent = Agent(
            ctx.provider,
            sub_config,
            sub_session,
            allowed_tools=set(SUBAGENT_TOOLS),
            is_subagent=True,
        )

        text_parts: list[str] = []
        tool_call_count = 0
        had_error = False
        last_error: str | None = None

        try:
            async for event in sub_agent.run(params.prompt):
                if event.kind == EventKind.TEXT_DELTA and event.text:
                    text_parts.append(event.text)
                elif event.kind == EventKind.TOOL_START:
                    tool_call_count += 1
                elif event.kind == EventKind.ERROR:
                    had_error = True
                    last_error = event.error
        except Exception as e:  # defensive: should not happen, but isolate fully
            log.warning("subagent_crash", error=str(e))
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"Sub-agent crashed: {type(e).__name__}: {e}",
            )

        summary = "".join(text_parts).strip()
        if not summary and had_error:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"Sub-agent failed without producing output: {last_error}",
                metadata={"tool_calls": tool_call_count},
            )
        if not summary:
            summary = (
                "(Sub-agent finished without producing a final answer. "
                "Try giving it a more specific prompt.)"
            )

        log.info(
            "subagent_done",
            description=params.description,
            tool_calls=tool_call_count,
            output_chars=len(summary),
        )

        return ToolResult(
            call_id="", tool=self.name, ok=not had_error,
            content=summary,
            metadata={
                "tool_calls": tool_call_count,
                "subagent_session_id": sub_session.id,
            },
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, TaskParams)
        return PermissionRequest(
            tool=self.name,
            action="file_read",
            summary=f"Dispatch read-only sub-agent: {params.description}",
        )
