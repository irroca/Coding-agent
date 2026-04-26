"""Read file tool — reads a file with optional line range."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.security.path_guard import is_binary, resolve_and_validate
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class ReadParams(BaseModel):
    file_path: str = Field(description="Absolute or workspace-relative path to the file.")
    offset: int | None = Field(
        default=None,
        description="1-based line number to start reading from.",
        ge=1,
    )
    limit: int | None = Field(
        default=None,
        description="Number of lines to read. Reads entire file if omitted.",
        ge=1,
    )


class ReadTool(Tool):
    name: ClassVar[str] = "read"
    description: ClassVar[str] = (
        "Read a file from the filesystem. Returns the file content with line numbers. "
        "Use offset and limit for large files. Detects binary files."
    )
    Params: ClassVar[type[BaseModel]] = ReadParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, ReadParams)
        path = resolve_and_validate(params.file_path, ctx.workspace, must_exist=True)

        if is_binary(path):
            return ToolResult(
                call_id="",
                tool=self.name,
                ok=True,
                content=f"(binary file: {path}, {path.stat().st_size} bytes)",
            )

        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        total = len(lines)

        start = (params.offset or 1) - 1
        end = start + params.limit if params.limit else total
        selected = lines[start:end]

        numbered = "".join(
            f"{i + start + 1}\t{line}" for i, line in enumerate(selected)
        )
        if not numbered.endswith("\n"):
            numbered += "\n"

        header = f"File: {path} ({total} lines total)"
        if params.offset or params.limit:
            header += f", showing lines {start + 1}-{min(end, total)}"

        return ToolResult(
            call_id="",
            tool=self.name,
            ok=True,
            content=f"{header}\n{numbered}",
            metadata={"path": str(path), "total_lines": total},
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, ReadParams)
        return PermissionRequest(
            tool=self.name,
            action="file_read",
            summary=f"Read file: {params.file_path}",
            path=params.file_path,
        )
