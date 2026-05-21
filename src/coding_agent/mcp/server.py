"""Expose Coding Agent's built-in tools as an MCP server.

Run via the ``coding-agent-mcp`` console script or
``python -m coding_agent.mcp.server``. Communicates over stdio by default,
which is what every existing MCP client (Claude Code, Cursor, Inspector) speaks.

The server walks ``_TOOL_REGISTRY`` and turns each ``Tool`` subclass into an MCP
tool using the **low-level** ``mcp.server.Server`` API so we can pass our own
JSON Schema verbatim instead of having FastMCP try to infer one from a
``**kwargs`` signature.

Every call goes through the same permission engine + audit log path as when
the in-process Agent invokes the tool, so there is no "back door" around
policy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from coding_agent.core.config import PermissionsConfig, load_config
from coding_agent.core.logging import configure_logging, get_logger
from coding_agent.security.audit import AuditLog
from coding_agent.security.permissions import PermissionEngine
from coding_agent.security.rules import Decision, RuleSet
from coding_agent.tools.base import ToolContext, all_tools

log = get_logger("mcp.server")


def _exposable_tools() -> dict[str, Any]:
    """Tools we expose over MCP. ``task`` is excluded because spawning a
    sub-agent from an MCP server has no in-context LLM to drive it."""
    return {n: c for n, c in all_tools().items() if n != "task"}


def _list_tools_payload() -> list[Any]:
    """Build the list_tools response. Imports the mcp types lazily."""
    import mcp.types as t

    out: list[t.Tool] = []
    for name, cls in _exposable_tools().items():
        schema = cls.Params.model_json_schema()
        schema.pop("title", None)
        out.append(
            t.Tool(
                name=name,
                description=cls.description,
                inputSchema=schema,
            )
        )
    return out


async def _serve(workspace: Path, permissions: PermissionsConfig) -> None:
    """Run the stdio MCP server until the client disconnects."""
    import mcp.server.stdio
    import mcp.types as t
    from mcp.server.lowlevel import NotificationOptions, Server
    from mcp.server.models import InitializationOptions

    server: Server = Server("coding-agent")
    ctx = ToolContext(workspace=workspace.resolve(), session_id="mcp-server")
    permission_engine = PermissionEngine(permissions, RuleSet())
    audit = AuditLog()
    tools = _exposable_tools()

    @server.list_tools()
    async def _list() -> list[t.Tool]:
        return _list_tools_payload()

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, Any]) -> list[t.TextContent]:
        tool_cls = tools.get(name)
        if tool_cls is None:
            return [t.TextContent(type="text", text=f"Unknown tool: {name}")]

        tool = tool_cls()
        try:
            params = tool.validate_params(arguments or {})
        except Exception as e:
            return [t.TextContent(type="text", text=f"Invalid arguments: {e}")]

        perm = tool.permission_request(params)
        decision = permission_engine.check(perm)
        audit.record(perm, decision.decision, decision.reason, session_id=ctx.session_id)
        if decision.decision == Decision.DENY:
            return [
                t.TextContent(
                    type="text",
                    text=f"Permission denied by policy: {decision.reason}",
                )
            ]

        try:
            result = await tool.run(params, ctx)
        except Exception as e:
            log.error("mcp_tool_error", tool=name, error=str(e), exc_info=True)
            return [t.TextContent(type="text", text=f"Tool error: {type(e).__name__}: {e}")]

        return [t.TextContent(type="text", text=result.content)]

    log.info("mcp_server_starting", workspace=str(workspace))
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(
            read,
            write,
            InitializationOptions(
                server_name="coding-agent",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Coding Agent's MCP server (stdio)")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace root the exposed tools operate inside.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the tool schemas as JSON and exit (debug aid).",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.workspace)
    configure_logging(cfg.log_level)

    if args.list:
        out = {
            name: {
                "description": cls.description,
                "parameters": cls.Params.model_json_schema(),
            }
            for name, cls in _exposable_tools().items()
        }
        json.dump(out, sys.stdout, indent=2)
        return

    asyncio.run(_serve(args.workspace, cfg.permissions))


if __name__ == "__main__":
    main()
