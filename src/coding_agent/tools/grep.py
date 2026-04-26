"""Grep tool — search file contents using ripgrep or fallback."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.security.path_guard import resolve_and_validate
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class GrepParams(BaseModel):
    pattern: str = Field(description="Search pattern (regex by default, literal with fixed_strings=true).")
    path: str = Field(
        default=".",
        description="Directory or file to search (relative to workspace).",
    )
    include: str | None = Field(
        default=None,
        description="Glob pattern to filter files (e.g. '*.py').",
    )
    fixed_strings: bool = Field(
        default=False,
        description="Treat pattern as a literal string instead of regex.",
    )


class GrepTool(Tool):
    name: ClassVar[str] = "grep"
    description: ClassVar[str] = (
        "Search file contents for a pattern. Uses ripgrep (rg) when available, "
        "otherwise falls back to a built-in search. Returns matching lines with "
        "file paths and line numbers."
    )
    Params: ClassVar[type[BaseModel]] = GrepParams

    MAX_RESULTS: ClassVar[int] = 200

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, GrepParams)
        target = resolve_and_validate(params.path, ctx.workspace, must_exist=True)

        if shutil.which("rg"):
            return await self._rg_search(params, target, ctx)
        return self._fallback_search(params, target, ctx)

    async def _rg_search(
        self, params: GrepParams, target, ctx: ToolContext
    ) -> ToolResult:
        cmd = [
            "rg", "--no-heading", "--line-number", "--color=never",
            "--max-count=50", "--max-filesize=1M",
        ]
        if params.fixed_strings:
            cmd.append("--fixed-strings")
        if params.include:
            cmd.extend(["--glob", params.include])
        cmd.extend([params.pattern, str(target)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ctx.workspace),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode(errors="replace")

        if proc.returncode == 1:
            return ToolResult(
                call_id="", tool=self.name, ok=True,
                content=f"No matches for '{params.pattern}'.",
            )
        if proc.returncode not in (0, 1):
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"rg error (exit {proc.returncode}): {stderr.decode(errors='replace')}",
            )

        lines = output.splitlines()
        truncated = ""
        if len(lines) > self.MAX_RESULTS:
            lines = lines[: self.MAX_RESULTS]
            truncated = f"\n(truncated at {self.MAX_RESULTS} lines)"

        return ToolResult(
            call_id="", tool=self.name, ok=True,
            content="\n".join(lines) + truncated,
            metadata={"match_count": len(lines)},
        )

    def _fallback_search(
        self, params: GrepParams, target, ctx: ToolContext
    ) -> ToolResult:
        ws = ctx.workspace.resolve()
        if params.fixed_strings:
            check = lambda line: params.pattern in line  # noqa: E731
        else:
            try:
                regex = re.compile(params.pattern)
            except re.error as e:
                return ToolResult(
                    call_id="", tool=self.name, ok=False,
                    content=f"Invalid regex: {e}",
                )
            check = lambda line: regex.search(line) is not None  # noqa: E731

        results: list[str] = []
        files = [target] if target.is_file() else []

        if target.is_dir():
            for root, dirs, fnames in os.walk(target):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fname in fnames:
                    if params.include and not __import__("fnmatch").fnmatch(fname, params.include):
                        continue
                    files.append(os.path.join(root, fname))

        for fpath in files:
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if check(line):
                            rel = os.path.relpath(fpath, ws)
                            results.append(f"{rel}:{lineno}:{line.rstrip()}")
                            if len(results) >= self.MAX_RESULTS:
                                break
            except OSError:
                continue
            if len(results) >= self.MAX_RESULTS:
                break

        if not results:
            return ToolResult(
                call_id="", tool=self.name, ok=True,
                content=f"No matches for '{params.pattern}'.",
            )

        truncated = ""
        if len(results) >= self.MAX_RESULTS:
            truncated = f"\n(truncated at {self.MAX_RESULTS} lines)"

        return ToolResult(
            call_id="", tool=self.name, ok=True,
            content="\n".join(results) + truncated,
            metadata={"match_count": len(results)},
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, GrepParams)
        return PermissionRequest(
            tool=self.name,
            action="file_read",
            summary=f"Search contents: {params.pattern}",
        )
