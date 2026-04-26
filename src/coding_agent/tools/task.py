"""Task tool — dispatch a sub-agent for independent work.

The sub-agent runs with its own conversation context but shares the same
workspace and tools. Results are returned as a summary to the parent agent.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class TaskParams(BaseModel):
    description: str = Field(
        description="Short description of the task (3-5 words).",
    )
    prompt: str = Field(
        description="Detailed instructions for the sub-agent. Include all context needed.",
    )


class TaskTool(Tool):
    name: ClassVar[str] = "task"
    description: ClassVar[str] = (
        "Dispatch an independent sub-agent to handle a self-contained task. "
        "The sub-agent has access to all the same tools and workspace but runs "
        "in its own conversation context. Use this to parallelize independent "
        "work or to protect the main context from excessive output. "
        "The sub-agent's result is returned as a summary."
    )
    Params: ClassVar[type[BaseModel]] = TaskParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, TaskParams)

        return ToolResult(
            call_id="", tool=self.name, ok=False,
            content=(
                "Sub-agent dispatch is not yet available. "
                "Please perform this task directly instead of delegating it.\n"
                f"Task: {params.description}\n"
                f"Instructions: {params.prompt[:200]}"
            ),
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, TaskParams)
        return PermissionRequest(
            tool=self.name,
            action="ask",
            summary=f"Dispatch sub-agent: {params.description}",
        )
