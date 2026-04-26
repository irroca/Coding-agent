"""Glob tool — find files by name pattern."""

from __future__ import annotations

import fnmatch
import os
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class GlobParams(BaseModel):
    pattern: str = Field(description="Glob pattern to match (e.g. '**/*.py', 'src/**/*.ts').")
    path: str = Field(
        default=".",
        description="Directory to search from (relative to workspace). Defaults to workspace root.",
    )


class GlobTool(Tool):
    name: ClassVar[str] = "glob"
    description: ClassVar[str] = (
        "Find files matching a glob pattern. Returns paths relative to the workspace. "
        "Respects .gitignore when inside a git repository."
    )
    Params: ClassVar[type[BaseModel]] = GlobParams

    MAX_RESULTS: ClassVar[int] = 500

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, GlobParams)

        from coding_agent.security.path_guard import resolve_and_validate

        base = resolve_and_validate(params.path, ctx.workspace, must_exist=True)

        if not base.is_dir():
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"Not a directory: {base}",
            )

        matches: list[str] = []
        ws = ctx.workspace.resolve()

        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                full = os.path.join(root, name)
                try:
                    rel = os.path.relpath(full, ws)
                except ValueError:
                    continue
                if fnmatch.fnmatch(rel, params.pattern) or fnmatch.fnmatch(name, params.pattern):
                    matches.append(rel)
                    if len(matches) >= self.MAX_RESULTS:
                        break
            if len(matches) >= self.MAX_RESULTS:
                break

        matches.sort()

        if not matches:
            return ToolResult(
                call_id="", tool=self.name, ok=True,
                content=f"No files match pattern '{params.pattern}'.",
            )

        truncated = ""
        if len(matches) >= self.MAX_RESULTS:
            truncated = f"\n(truncated at {self.MAX_RESULTS} results)"

        return ToolResult(
            call_id="", tool=self.name, ok=True,
            content="\n".join(matches) + truncated,
            metadata={"count": len(matches)},
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, GlobParams)
        return PermissionRequest(
            tool=self.name,
            action="file_read",
            summary=f"Search files: {params.pattern}",
        )
