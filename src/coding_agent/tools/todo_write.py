"""TodoWrite tool — structured task tracking for the agent.

The agent uses this tool to plan multi-step tasks, track progress,
and show the user what it's working on. The todo list is stored
in the ToolContext and rendered by the TUI.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class TodoItem(BaseModel):
    content: str = Field(description="What needs to be done (imperative form, e.g. 'Run tests').")
    status: str = Field(
        default="pending",
        description="One of: pending, in_progress, completed.",
    )


class TodoWriteParams(BaseModel):
    todos: list[TodoItem] = Field(description="The complete updated todo list.")


class TodoWriteTool(Tool):
    name: ClassVar[str] = "todo_write"
    description: ClassVar[str] = (
        "Create or update a structured task list to plan and track progress on "
        "multi-step tasks. Each todo has a content string and a status "
        "(pending / in_progress / completed). Send the full list each time — "
        "it replaces the previous one."
    )
    Params: ClassVar[type[BaseModel]] = TodoWriteParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, TodoWriteParams)

        valid_statuses = {"pending", "in_progress", "completed"}
        for item in params.todos:
            if item.status not in valid_statuses:
                return ToolResult(
                    call_id="", tool=self.name, ok=False,
                    content=f"Invalid status '{item.status}'. Must be one of: {valid_statuses}",
                )

        todo_data: list[dict[str, Any]] = [
            {"content": t.content, "status": t.status}
            for t in params.todos
        ]

        ctx.metadata["todos"] = todo_data

        lines: list[str] = []
        for t in params.todos:
            icon = {"pending": "○", "in_progress": "◉", "completed": "✓"}.get(t.status, "?")
            lines.append(f"  {icon} [{t.status}] {t.content}")

        summary = "\n".join(lines) if lines else "(empty todo list)"
        return ToolResult(
            call_id="", tool=self.name, ok=True,
            content=f"Todo list updated ({len(params.todos)} items):\n{summary}",
            metadata={"todos": todo_data},
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        return PermissionRequest(
            tool=self.name,
            action="file_read",
            summary="Update task list",
        )
