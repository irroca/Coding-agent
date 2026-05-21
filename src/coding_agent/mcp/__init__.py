"""MCP (Model Context Protocol) integration.

Two halves:

- ``client`` — connects to external MCP servers and registers their tools into
  the local tool registry, so the agent can call them transparently.
- ``server`` — exposes our built-in tools as an MCP server so other clients
  (Claude Code, Cursor, custom apps) can drive Coding Agent's tools.

The ``mcp`` Python SDK is an optional dependency. Install with
``pip install coding-agent[mcp]``.
"""

from __future__ import annotations
