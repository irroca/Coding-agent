"""MCP client — connect to external MCP servers and expose their tools.

Spawned at REPL startup. For each configured server we open a stdio connection,
``initialize`` the session, and ``list_tools`` to discover the surface. Each
remote tool is then wrapped in a synthetic `Tool` subclass and registered into
``_TOOL_REGISTRY`` with the canonical name ``mcp__<server>__<tool>``.

Lifecycle: ``McpClientHost.aclose()`` tears down sessions and unregisters the
synthetic tools so a re-spawn doesn't leak.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, create_model

from coding_agent.core.logging import get_logger
from coding_agent.core.types import ToolResult
from coding_agent.tools.base import (
    _TOOL_REGISTRY,
    PermissionRequest,
    Tool,
    ToolContext,
)

log = get_logger("mcp.client")


@dataclass
class McpServerSpec:
    """Connection parameters for one external MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


class _RemoteTool(Tool, register=False):
    """Base class for dynamically synthesized MCP-backed tools.

    Subclasses are produced by `_make_remote_tool_class` at runtime. Each
    instance owns no state — the live MCP session is held by `McpClientHost`
    via the ``mcp_host`` class attribute. We pass ``register=False`` so that
    creating subclasses doesn't auto-add them to ``_TOOL_REGISTRY``; the host
    registers them deliberately after discovery.
    """

    mcp_host: ClassVar[Any]
    mcp_server_name: ClassVar[str]
    mcp_remote_name: ClassVar[str]

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        host = self.mcp_host
        try:
            result = await host.call_remote_tool(
                self.mcp_server_name,
                self.mcp_remote_name,
                params.model_dump(),
            )
        except Exception as e:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"MCP call failed: {type(e).__name__}: {e}",
            )
        return result

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        # External tools are treated as `bash`-equivalent risk by default —
        # we don't know what they do. Users who trust a particular MCP server
        # can add an allow rule for `mcp__<server>__*`.
        return PermissionRequest(
            tool=self.name,
            action="bash",
            summary=f"Call MCP tool {self.name}",
        )


def _make_remote_tool_class(
    host: McpClientHost,
    server_name: str,
    remote_name: str,
    description: str,
    input_schema: dict[str, Any],
) -> type[_RemoteTool]:
    """Synthesize a Tool subclass for one remote MCP tool.

    The pydantic Params model is built from the input_schema; for now we treat
    every field as `Any` and rely on the remote server's own validation. A
    future refinement could translate the JSON Schema into typed fields, but
    JSON Schema → pydantic is non-trivial and not worth the code right now.
    """
    full_name = f"mcp__{server_name}__{remote_name}"

    # Build a permissive pydantic model from the schema's top-level properties.
    properties = (input_schema or {}).get("properties", {})
    fields: dict[str, Any] = {prop: (Any, None) for prop in properties}
    if not fields:
        # Pydantic refuses to create an empty model; give it a single optional
        # passthrough field.
        fields["_unused"] = (Any, None)

    params_cls = create_model(
        f"{remote_name}_Params",
        __config__=ConfigDict(extra="allow"),
        **fields,
    )

    cls = type(
        f"RemoteTool_{server_name}_{remote_name}",
        (_RemoteTool,),
        {
            "name": full_name,
            "description": description or f"Remote MCP tool {remote_name}",
            "Params": params_cls,
            "mcp_host": host,
            "mcp_server_name": server_name,
            "mcp_remote_name": remote_name,
        },
    )
    return cls


class McpClientHost:
    """Owns lifetime of connections to one or more external MCP servers."""

    def __init__(self, specs: list[McpServerSpec]) -> None:
        self.specs = specs
        self._sessions: dict[str, Any] = {}
        self._exit_stack: AsyncExitStack | None = None
        self._registered_names: list[str] = []

    async def start(self) -> None:
        """Open stdio sessions to every configured server and register tools."""
        if not self.specs:
            return

        # Imported lazily so the `mcp` package stays an optional dependency.
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        await stack.__aenter__()
        self._exit_stack = stack

        for spec in self.specs:
            try:
                params = StdioServerParameters(
                    command=spec.command,
                    args=spec.args,
                    env=spec.env or None,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools_response = await session.list_tools()
            except Exception as e:
                log.warning(
                    "mcp_server_init_failed",
                    server=spec.name,
                    error=str(e),
                )
                continue

            self._sessions[spec.name] = session

            for remote_tool in tools_response.tools:
                try:
                    schema = remote_tool.inputSchema or {"type": "object"}
                except AttributeError:
                    schema = {"type": "object"}

                cls = _make_remote_tool_class(
                    self,
                    server_name=spec.name,
                    remote_name=remote_tool.name,
                    description=remote_tool.description or "",
                    input_schema=schema,
                )
                _TOOL_REGISTRY[cls.name] = cls
                self._registered_names.append(cls.name)
                log.info("mcp_tool_registered", name=cls.name)

    async def call_remote_tool(
        self,
        server_name: str,
        remote_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Forward a tool call to the right MCP session."""
        session = self._sessions.get(server_name)
        if session is None:
            return ToolResult(
                call_id="", tool=f"mcp__{server_name}__{remote_name}", ok=False,
                content=f"MCP server '{server_name}' is not connected.",
            )

        # Drop the placeholder _unused field if the user (LLM) didn't fill it.
        arguments = {k: v for k, v in arguments.items() if v is not None}

        result = await session.call_tool(remote_name, arguments=arguments)

        text_parts: list[str] = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)
            else:
                text_parts.append(json.dumps(_block_to_jsonable(block), default=str))
        joined = "\n".join(text_parts).strip() or "(no content returned)"

        return ToolResult(
            call_id="", tool=f"mcp__{server_name}__{remote_name}",
            ok=not result.isError,
            content=joined,
            metadata={"is_error": bool(result.isError)},
        )

    async def aclose(self) -> None:
        """Tear down all sessions and unregister synthesized tools."""
        for name in self._registered_names:
            _TOOL_REGISTRY.pop(name, None)
        self._registered_names.clear()

        stack = self._exit_stack
        if stack is None:
            return
        self._exit_stack = None
        try:
            await stack.__aexit__(None, None, None)
        except Exception as e:
            log.warning("mcp_host_close_error", error=str(e))


def _block_to_jsonable(block: Any) -> Any:
    """Best-effort conversion of an MCP content block to JSON."""
    if hasattr(block, "model_dump"):
        return block.model_dump()
    if hasattr(block, "__dict__"):
        return {k: v for k, v in vars(block).items() if not k.startswith("_")}
    return repr(block)


def specs_from_config(raw: list[dict[str, Any]] | None) -> list[McpServerSpec]:
    """Parse the `mcp_servers` config list into McpServerSpec values."""
    out: list[McpServerSpec] = []
    for entry in raw or []:
        try:
            out.append(
                McpServerSpec(
                    name=entry["name"],
                    command=entry["command"],
                    args=list(entry.get("args", [])),
                    env=dict(entry.get("env", {})),
                )
            )
        except KeyError as e:
            log.warning("mcp_spec_missing_key", entry=entry, missing=str(e))
    return out
