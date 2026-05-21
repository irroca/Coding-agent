"""Bash tool — execute shell commands with timeout and output capture.

Two execution drivers:

- ``subprocess`` (default): runs the command directly in the host shell.
- ``docker``: runs the command inside a throwaway container with the workspace
  mounted read-write and **no network**. Requires the optional ``docker``
  extra and a reachable Docker daemon.

The driver is chosen by ``Config.agent.bash_driver``; the per-call ``Params``
shape doesn't change so models that learned the v1 schema keep working.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.logging import get_logger
from coding_agent.core.types import ToolResult
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext

log = get_logger("tools.bash")


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

        driver = "subprocess"
        image = "ubuntu:24.04"
        if ctx.config is not None:
            driver = ctx.config.agent.bash_driver
            image = ctx.config.agent.bash_docker_image

        if driver == "docker":
            return await _run_docker(
                params.command,
                cwd=cwd,
                workspace=str(ctx.workspace),
                timeout=params.timeout,
                image=image,
                output_limit=self.OUTPUT_LIMIT,
                tool_name=self.name,
            )
        return await _run_subprocess(
            params.command,
            cwd=cwd,
            timeout=params.timeout,
            output_limit=self.OUTPUT_LIMIT,
            tool_name=self.name,
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, BashParams)
        return PermissionRequest(
            tool=self.name,
            action="bash",
            summary=f"Run: {params.command}",
            command=params.command,
        )


async def _run_subprocess(
    command: str,
    *,
    cwd: str,
    timeout: int,
    output_limit: int,
    tool_name: str,
) -> ToolResult:
    """Direct shell execution on the host. The default for development."""
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=None,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()
        return ToolResult(
            call_id="", tool=tool_name, ok=False,
            content=f"Command timed out after {timeout}s.",
        )
    except OSError as e:
        return ToolResult(
            call_id="", tool=tool_name, ok=False,
            content=f"Failed to execute command: {e}",
        )

    return _make_result(stdout, proc.returncode, output_limit, tool_name)


async def _run_docker(
    command: str,
    *,
    cwd: str,
    workspace: str,
    timeout: int,
    image: str,
    output_limit: int,
    tool_name: str,
) -> ToolResult:
    """Run the command inside a throwaway container.

    The container:
      - has the workspace mounted at ``/workspace`` (rw)
      - has its ``--workdir`` set to ``/workspace`` plus the relative cwd
      - has ``--network none`` (no internet)
      - is auto-removed (``--rm``) and capped by ``--cpus 2 --memory 1g``
      - uses ``--security-opt no-new-privileges``

    We shell out to the ``docker`` CLI rather than the ``docker`` Python SDK
    so that pipe handling and timeout cancellation stay simple. The ``docker``
    extra is still needed for the SDK-based tests; the runtime itself only
    needs the binary on PATH.
    """
    try:
        rel_cwd = os.path.relpath(cwd, workspace)
    except ValueError:
        rel_cwd = "."
    if rel_cwd.startswith(".."):
        # Caller pointed at a directory outside the workspace; refuse rather
        # than silently dropping out of the sandbox.
        return ToolResult(
            call_id="", tool=tool_name, ok=False,
            content=(
                "working_directory escapes the workspace and would not be "
                "mounted inside the container."
            ),
        )
    container_workdir = "/workspace" if rel_cwd == "." else f"/workspace/{rel_cwd}"

    args = [
        "docker", "run", "--rm", "-i",
        "--network", "none",
        "--cpus", "2", "--memory", "1g",
        "--security-opt", "no-new-privileges",
        "--workdir", container_workdir,
        "-v", f"{workspace}:/workspace",
        image,
        "bash", "-lc", command,
    ]

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError:
        return ToolResult(
            call_id="", tool=tool_name, ok=False,
            content=(
                "Docker driver requested but `docker` is not on PATH. "
                "Install Docker, or set agent.bash_driver=subprocess."
            ),
        )
    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()
        return ToolResult(
            call_id="", tool=tool_name, ok=False,
            content=f"Command timed out after {timeout}s (docker driver).",
        )

    log.info(
        "docker_exec",
        cmd=shlex.join(args[:10]) + " ...",
        exit=proc.returncode,
    )
    return _make_result(stdout, proc.returncode, output_limit, tool_name)


def _make_result(
    stdout: bytes,
    exit_code: int | None,
    output_limit: int,
    tool_name: str,
) -> ToolResult:
    output = stdout.decode(errors="replace")
    truncated = False
    if len(output) > output_limit:
        half = output_limit // 2
        output = (
            output[:half]
            + f"\n\n... ({len(stdout) - output_limit} bytes truncated) ...\n\n"
            + output[-half:]
        )
        truncated = True

    header = f"Exit code: {exit_code}\n"
    if truncated:
        header += "(output truncated)\n"

    return ToolResult(
        call_id="", tool=tool_name,
        ok=exit_code == 0,
        content=header + output,
        metadata={"exit_code": exit_code, "truncated": truncated},
    )
