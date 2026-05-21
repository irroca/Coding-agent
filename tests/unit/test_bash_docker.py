"""Tests for the bash tool's docker driver.

We don't require a real Docker daemon in CI — we just verify:

  * driver dispatch picks the docker path when configured
  * the docker command line we build has the right safety flags
  * the FileNotFoundError fallback returns a friendly error when docker is
    missing
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from coding_agent.core.config import AgentConfig, Config, PermissionsConfig, ProviderConfig
from coding_agent.tools.base import ToolContext
from coding_agent.tools.bash import BashParams, BashTool, _run_docker


def _ctx_with_driver(workspace: Path, driver: str) -> ToolContext:
    cfg = Config(
        provider="deepseek",
        workspace=workspace,
        providers={"deepseek": ProviderConfig(api_key="x", model="m")},
        permissions=PermissionsConfig(),
        agent=AgentConfig(bash_driver=driver),
    )
    return ToolContext(workspace=workspace, config=cfg)


async def test_subprocess_driver_runs_locally(tmp_path: Path) -> None:
    """Default driver still uses the host shell."""
    ctx = _ctx_with_driver(tmp_path, "subprocess")
    tool = BashTool()
    result = await tool.run(BashParams(command="echo hi"), ctx)
    assert result.ok
    assert "hi" in result.content


async def test_docker_driver_friendly_error_when_docker_missing(tmp_path: Path) -> None:
    """If `docker` is not on PATH the tool reports a clear actionable error
    rather than crashing."""
    ctx = _ctx_with_driver(tmp_path, "docker")
    tool = BashTool()

    async def _fake_exec(*args, **kwargs):
        raise FileNotFoundError("docker")

    with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
        result = await tool.run(BashParams(command="echo hi"), ctx)

    assert not result.ok
    assert "docker" in result.content.lower()
    assert "subprocess" in result.content.lower()


async def test_docker_driver_command_line_has_safety_flags(tmp_path: Path) -> None:
    """Inspect the argv we pass to subprocess: --network none, --rm,
    no-new-privileges, workspace mounted at /workspace."""
    captured = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b"OK\n", b""

    async def _fake_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProc()

    with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
        result = await _run_docker(
            "echo hi",
            cwd=str(tmp_path),
            workspace=str(tmp_path),
            timeout=10,
            image="ubuntu:24.04",
            output_limit=10000,
            tool_name="bash",
        )

    args = list(captured["args"])
    assert args[0] == "docker"
    assert "--rm" in args
    assert "--network" in args and "none" in args
    assert "--security-opt" in args and "no-new-privileges" in args
    assert any(f"{tmp_path}:/workspace" in a for a in args)
    assert result.ok


async def test_docker_driver_refuses_cwd_outside_workspace(tmp_path: Path) -> None:
    other = tmp_path.parent
    result = await _run_docker(
        "ls",
        cwd=str(other),
        workspace=str(tmp_path),
        timeout=10,
        image="x",
        output_limit=1000,
        tool_name="bash",
    )
    assert not result.ok
    assert "workspace" in result.content.lower()


def test_permissions_config_no_longer_has_network_field() -> None:
    """The `network` permission category was removed in B6 because no tool
    used it. Regression guard."""
    pc = PermissionsConfig()
    assert not hasattr(pc, "network")
