"""Tool implementations and the tool registry.

Importing this package auto-registers all built-in tools. The agent loop
only needs ``from coding_agent.tools.base import all_tools, all_schemas``.
"""

from coding_agent.tools import (  # noqa: F401 — trigger registration
    bash,
    edit,
    glob,
    grep,
    ls,
    read,
    task,
    todo_write,
    write,
)
