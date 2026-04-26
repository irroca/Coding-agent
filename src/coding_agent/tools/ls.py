"""List directory tool — shows files with .gitignore awareness."""

from __future__ import annotations

import subprocess
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.security.path_guard import resolve_and_validate
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class LsParams(BaseModel):
    path: str = Field(
        default=".",
        description="Directory to list (absolute or workspace-relative). Defaults to workspace root.",
    )
    depth: int = Field(
        default=1,
        description="How many levels deep to recurse. 1 = immediate children only.",
        ge=1,
        le=5,
    )
    show_hidden: bool = Field(
        default=False,
        description="Include hidden files (dotfiles).",
    )


class LsTool(Tool):
    name: ClassVar[str] = "ls"
    description: ClassVar[str] = (
        "List files and directories. Respects .gitignore when inside a git repo. "
        "Use depth > 1 for recursive listing. Hidden files excluded by default."
    )
    Params: ClassVar[type[BaseModel]] = LsParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, LsParams)
        target = resolve_and_validate(params.path, ctx.workspace, must_exist=True)

        if not target.is_dir():
            return ToolResult(
                call_id="",
                tool=self.name,
                ok=False,
                content=f"Not a directory: {target}",
            )

        entries = _list_with_git(target, params.depth, params.show_hidden)

        if not entries:
            return ToolResult(
                call_id="",
                tool=self.name,
                ok=True,
                content=f"{target}/ (empty directory)",
            )

        formatted = "\n".join(entries)
        return ToolResult(
            call_id="",
            tool=self.name,
            ok=True,
            content=f"{target}/\n{formatted}",
            metadata={"path": str(target), "count": len(entries)},
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, LsParams)
        return PermissionRequest(
            tool=self.name,
            action="file_read",
            summary=f"List directory: {params.path}",
            path=params.path,
        )


def _list_with_git(root, depth: int, show_hidden: bool) -> list[str]:
    """Try `git ls-files` first for .gitignore awareness; fall back to os walk."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _filter_git_output(result.stdout, depth, show_hidden)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return _walk_fallback(root, depth, show_hidden)


def _filter_git_output(stdout: str, depth: int, show_hidden: bool) -> list[str]:
    entries: set[str] = set()
    for line in stdout.strip().splitlines():
        parts = line.split("/")
        if not show_hidden and any(p.startswith(".") for p in parts):
            continue
        if len(parts) <= depth:
            entries.add(line)
        else:
            entries.add("/".join(parts[:depth]) + "/")
    return sorted(entries)


def _walk_fallback(root, depth: int, show_hidden: bool) -> list[str]:
    from pathlib import Path

    root = Path(root)
    entries: list[str] = []

    def _recurse(current: Path, current_depth: int) -> None:
        if current_depth > depth:
            return
        try:
            children = sorted(current.iterdir())
        except PermissionError:
            return
        for child in children:
            if not show_hidden and child.name.startswith("."):
                continue
            rel = child.relative_to(root)
            if child.is_dir():
                entries.append(f"{rel}/")
                _recurse(child, current_depth + 1)
            else:
                entries.append(str(rel))

    _recurse(root, 1)
    return entries
