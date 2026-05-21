"""End-to-end test: McpClientHost connects to our own MCP server and the
synthesized remote tool runs through the normal Agent dispatch path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from coding_agent.mcp.client import McpClientHost, McpServerSpec
from coding_agent.tools.base import _TOOL_REGISTRY, ToolContext


@pytest.mark.requires_api  # spawns subprocess + asyncio; gate from quick runs
async def test_mcp_client_registers_remote_tools_and_calls_them(tmp_path: Path) -> None:
    """Spawn our own MCP server as a child process, then drive it through
    McpClientHost. The remote `ls` tool should appear in _TOOL_REGISTRY with
    the canonical `mcp__local__ls` name and return real ls output when
    invoked."""
    (tmp_path / "marker.txt").write_text("hi")

    host = McpClientHost([
        McpServerSpec(
            name="local",
            command=sys.executable,
            args=["-m", "coding_agent.mcp.server", "--workspace", str(tmp_path)],
        )
    ])
    try:
        await host.start()

        # The synthetic tool should be registered.
        cls = _TOOL_REGISTRY.get("mcp__local__ls")
        assert cls is not None, "Remote tool was not registered into _TOOL_REGISTRY"

        # Invoke via the normal Tool.run path.
        params = cls.Params()
        ctx = ToolContext(workspace=tmp_path)
        result = await cls().run(params, ctx)
        assert result.ok
        assert "marker.txt" in result.content
    finally:
        await host.aclose()

    # After aclose the tool should be gone from the registry.
    assert "mcp__local__ls" not in _TOOL_REGISTRY
