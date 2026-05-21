"""Browser UI for the agent.

Optional package — requires the `web` extra: ``pip install coding-agent[web]``.

The web layer is a thin transport over the existing agent core:

* ``runner.SessionRunner`` owns one ``Agent`` + ``Session`` per browser tab.
* ``server.create_app`` builds the FastAPI app, mounts the WebSocket route,
  serves the bundled React SPA from ``static/``.
* ``protocol.*`` is the single source of truth for every WS message shape;
  both Python and TypeScript types derive from it.

No agent / provider / tool / TUI code changes. The browser is just another
consumer of ``Agent.run() -> AsyncIterator[AgentEvent]``.
"""

from __future__ import annotations
