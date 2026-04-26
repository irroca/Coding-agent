"""Bash tool — execute shell commands with timeout and output capture."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class BashParams(BaseModel):
    command: str = Field(description="The shell command to execute.")
    timeout: int = Field(
        default=120,
        description="Timeout in seconds (max 600).",
        ge=1,
        le=600,
    )
    working_directory: str | None = Field(
        default=None,
        description="Working directory for the command (defaults to workspace root).",
    )


class BashTool(Tool):
    name: ClassVar[str] = "bash"
    description: ClassVar[str] = (
        "Execute a shell command and return its output. Commands run in bash "
        "with a configurable timeout. The working directory defaults to the "
        "workspace root."
    )
    Params: ClassVar[type[BaseModel]] = BashParams

    OUTPUT_LIMIT: ClassVar[int] = 30_000

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, BashParams)

        cwd = str(ctx.workspace)
        if params.working_directory:
            from coding_agent.security.path_guard import resolve_and_validate
            cwd_path = resolve_and_validate(
                params.working_directory, ctx.workspace, must_exist=True,
            )
            if not cwd_path.is_dir():
                return ToolResult(
                    call_id="", tool=self.name, ok=False,
                    content=f"Not a directory: {cwd_path}",
                )
            cwd = str(cwd_path)

        try:
            proc = await asyncio.create_subprocess_shell(
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=None,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=params.timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"Command timed out after {params.timeout}s.",
            )
        except OSError as e:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"Failed to execute command: {e}",
            )

        output = stdout.decode(errors="replace")

        truncated = False
        if len(output) > self.OUTPUT_LIMIT:
            half = self.OUTPUT_LIMIT // 2
            output = (
                output[:half]
                + f"\n\n... ({len(stdout) - self.OUTPUT_LIMIT} bytes truncated) ...\n\n"
                + output[-half:]
            )
            truncated = True

        exit_code = proc.returncode
        header = f"Exit code: {exit_code}\n"
        if truncated:
            header += "(output truncated)\n"

        return ToolResult(
            call_id="", tool=self.name,
            ok=exit_code == 0,
            content=header + output,
            metadata={"exit_code": exit_code, "truncated": truncated},
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, BashParams)
        return PermissionRequest(
            tool=self.name,
            action="bash",
            summary=f"Run: {params.command}",
            command=params.command,
        )
