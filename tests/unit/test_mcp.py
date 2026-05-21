"""Unit tests for the MCP integration.

Server tests do schema-only validation (`--list` mode) and tool wrapper
correctness without spinning up a real stdio transport.

Client tests verify the spec parser and the dynamic Tool-class synthesis,
again without actually opening a stdio subprocess (covered by an end-to-end
test that imports our own server).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from coding_agent.mcp.client import _make_remote_tool_class, specs_from_config
from coding_agent.tools.base import _TOOL_REGISTRY


def test_specs_from_config_parses_minimal_entries() -> None:
    raw = [
        {"name": "fs", "command": "uvx", "args": ["mcp-server-filesystem", "/tmp"]},
        {"name": "noop", "command": "echo"},
    ]
    specs = specs_from_config(raw)
    assert len(specs) == 2
    assert specs[0].name == "fs"
    assert specs[0].args == ["mcp-server-filesystem", "/tmp"]
    assert specs[1].args == []


def test_specs_from_config_skips_invalid() -> None:
    raw = [{"command": "missing-name"}, {"name": "ok", "command": "yes"}]
    specs = specs_from_config(raw)
    assert len(specs) == 1
    assert specs[0].name == "ok"


def test_make_remote_tool_class_name_prefixed() -> None:
    cls = _make_remote_tool_class(
        host=None,  # type: ignore[arg-type]  not exercised in this test
        server_name="srv",
        remote_name="search",
        description="Search the web",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )
    assert cls.name == "mcp__srv__search"
    assert "search" in cls.description.lower()


def test_make_remote_tool_class_handles_empty_schema() -> None:
    """An MCP tool with no inputs must still produce a buildable class."""
    cls = _make_remote_tool_class(
        host=None,  # type: ignore[arg-type]
        server_name="srv",
        remote_name="ping",
        description="Health check",
        input_schema={"type": "object"},
    )
    # Pydantic refuses empty models; we plug in a placeholder field instead.
    params = cls.Params(_unused=None)
    assert params is not None


def test_make_remote_tool_class_does_not_pollute_registry() -> None:
    """Synthesizing a class must not silently register it; that's the host's job."""
    before = set(_TOOL_REGISTRY)
    _make_remote_tool_class(
        host=None,  # type: ignore[arg-type]
        server_name="srv",
        remote_name="foo",
        description="",
        input_schema={"type": "object"},
    )
    after = set(_TOOL_REGISTRY)
    assert after == before


def test_mcp_server_list_subcommand_emits_schema() -> None:
    """`coding_agent.mcp.server --list` should print a JSON schema for each
    built-in tool minus `task`."""
    proc = subprocess.run(
        [sys.executable, "-m", "coding_agent.mcp.server", "--list"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent.parent,
    )
    assert proc.returncode == 0, proc.stderr
    schema = json.loads(proc.stdout)
    # All real tools should be there; `task` must be excluded (no LLM in MCP).
    assert "read" in schema
    assert "write" in schema
    assert "bash" in schema
    assert "task" not in schema
    assert "parameters" in schema["read"]


@pytest.mark.requires_api
def test_mcp_roundtrip_via_stdio_against_own_server(tmp_path: Path) -> None:
    """End-to-end: spawn our server in a subprocess via stdio and call `ls`
    through MCP. Requires the `mcp` extra and a working asyncio loop, so we
    gate it behind `requires_api` since it touches subprocess + asyncio."""
    import asyncio

    (tmp_path / "hello.txt").write_text("hi\n")

    async def _run() -> str:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "coding_agent.mcp.server", "--workspace", str(tmp_path)],
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert "ls" in tool_names
            result = await session.call_tool("ls", {"path": "."})
            return "\n".join(
                getattr(b, "text", "") for b in result.content
            )

    output = asyncio.run(_run())
    assert "hello.txt" in output
