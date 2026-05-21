"""Write file tool — writes content to a file with diff preview."""

from __future__ import annotations

import difflib
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.security.path_guard import resolve_and_validate
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class WriteParams(BaseModel):
    file_path: str = Field(description="Absolute or workspace-relative path to write to.")
    content: str = Field(description="The full content to write to the file.")


class WriteTool(Tool):
    name: ClassVar[str] = "write"
    description: ClassVar[str] = (
        "Write content to a file. Creates parent directories if needed. "
        "If the file exists, it will be overwritten. Prefer the edit tool "
        "for modifying existing files — it only sends the diff."
    )
    Params: ClassVar[type[BaseModel]] = WriteParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, WriteParams)
        path = resolve_and_validate(params.file_path, ctx.workspace)

        path.parent.mkdir(parents=True, exist_ok=True)

        old_content = ""
        if path.is_file():
            old_content = path.read_text(encoding="utf-8", errors="replace")

        path.write_text(params.content, encoding="utf-8")

        diff = "".join(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                params.content.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
        )

        if not diff:
            summary = f"Wrote {path} (no changes from existing content)"
        elif old_content:
            summary = f"Updated {path}\n{diff}"
        else:
            summary = f"Created {path} ({len(params.content)} chars)"

        return ToolResult(
            call_id="",
            tool=self.name,
            ok=True,
            content=summary,
            metadata={
                "path": str(path),
                "created": not bool(old_content),
                "previous_content": old_content,
                "new_content": params.content,
                "diff": diff,
            },
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, WriteParams)
        return PermissionRequest(
            tool=self.name,
            action="file_write",
            summary=f"Write file: {params.file_path}",
            path=params.file_path,
        )

    def generate_diff(self, params: WriteParams, ctx: ToolContext) -> str | None:
        """Pre-execution diff for the permission confirmation UI."""
        path = resolve_and_validate(params.file_path, ctx.workspace)
        if not path.is_file():
            return None
        old = path.read_text(encoding="utf-8", errors="replace")
        return "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                params.content.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
        )
