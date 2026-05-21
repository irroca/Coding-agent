# Browser UI

The agent ships with an optional browser UI for users who prefer a
ChatGPT/Claude-style interface to the terminal REPL. Both modes share
the same underlying `Agent` — the web layer is a thin transport.

> See [ADR-0011](decisions/0011-web-ui.md) for the design rationale.

## Install

```bash
# Add the web extra (also pulls FastAPI / uvicorn / websockets)
uv sync --extra web                 # repo dev install
# or
pip install 'coding-agent[web]'     # installed wheel
```

The bundled React SPA is committed under `src/coding_agent/web/static/`
and shipped inside the wheel — **users do not need Node.js**.

## Start

```bash
uv run coding-agent web                          # opens http://127.0.0.1:8765
uv run coding-agent web --port 9000 --no-open-browser
uv run coding-agent web --workspace /path/to/project
```

`Ctrl+C` shuts the server down.

### WSL note

WSL2 (Win10 19044+ / Win11) forwards `localhost` to Windows automatically,
so running `coding-agent web` inside Ubuntu and opening
`http://localhost:8765` in Windows Chrome works with no extra
configuration. If your WSL doesn't forward `localhost`, bind to
`0.0.0.0` and access via `$(hostname -I)`:

```bash
coding-agent web --host 0.0.0.0
# Then in Windows:  http://<wsl-ip>:8765
```

## Features

- **Multi-session sidebar** — grouped by date; click to resume, hover
  for delete; "+ New chat" to start fresh.
- **Workspace switcher** — top-bar dropdown lists recent workspaces;
  type any absolute path in the input box and press Enter to switch.
  Each new workspace starts a fresh session.
- **Streaming assistant** — text streams character-by-character; tool
  calls appear as collapsible cards that turn green/red as they
  complete.
- **Permission modal** — same approve/deny semantics as the TUI's
  `[y/n/a]` prompt. Diff preview for `write` / `edit`. The "Always
  allow for this session" checkbox plugs into the per-session
  `auto_approve` set used by the agent loop.
- **Live usage strip** — top-right shows `<provider:model>`,
  `prompt tokens in · completion tokens out`, and prompt cache hit
  rate when non-zero.
- **Reconnect** — drop the connection (laptop sleep, server restart)
  and the WebSocket auto-reconnects every 1.5s; messages aren't lost
  because the runner re-emits a fresh `session_state` on connect.

## Keyboard

| Key | Action |
| --- | --- |
| `⌘/Ctrl + Enter` | Send |
| `Esc` while running | Cancel current turn |
| `Enter` in workspace path input | Switch workspace |

## Architecture

```
┌────────────── Browser (React SPA) ──────────────┐
│  Sidebar │ TopBar │ ChatView │ Composer │ Modal │
│           ▲   wires through zustand store        │
│           │       │                              │
│   useWebSocket() ─┴── ws → JSON ServerMessage ──┐│
└───────────────────────────────────────────────────│
                                                   │
┌──────────── Backend (FastAPI / uvicorn) ─────────│┐
│  /api/sessions  /api/workspaces  /api/config     ││ REST
│  /ws/{tab_id}                                    ││ WebSocket
│      ▼                                           ││
│  SessionRunner ── confirm callback ─────┐        ││
│      ▼                                  │        ││
│  Agent.run() → AsyncIterator[AgentEvent]│        ││
│      ▼                                  │        ││
│  Session ⇄ disk                         ▼        ││
│                       ConfirmRequest msg ──── ws ┘│
└──────────────────────────────────────────────────┘
```

### Per-tab runner

Each browser tab opens its own WebSocket. The server mints one
`SessionRunner` per tab — that runner owns:

- a single `Agent` instance,
- the underlying `Session` (loaded fresh or resumed),
- an inbound queue of user submissions (drained serially),
- an outbound queue of pydantic-typed messages,
- a `pending_confirms` futures map for permission round-trips,
- the per-session `auto_approve` set ("Always allow this session").

Switching session in the sidebar re-attaches the runner to a different
`Session` object and rebuilds the `Agent`; the WebSocket stays open.

### Wire protocol

Source of truth: [`src/coding_agent/web/protocol.py`](../src/coding_agent/web/protocol.py).
TypeScript mirror: [`frontend/src/types.ts`](../frontend/src/types.ts) — kept
in sync manually (small surface; could be generated with
`datamodel-code-generator` later).

| Direction | Message types |
|-----------|---------------|
| Server → Client | `text_delta`, `tool_start`, `tool_result`, `usage`, `turn_end`, `error`, `confirm_request`, `session_state`, `session_list`, `workspace_list`, `ack`, `server_error` |
| Client → Server | `submit`, `cancel`, `confirm_response`, `attach_session`, `delete_session`, `list_sessions`, `list_workspaces` |

All messages are JSON with a `type` discriminator. Schemas use pydantic
`Field(discriminator="type")` unions on the server side.

### Permission round-trip

```
LLM picks tool ──► Agent loop ──► ToolContext + PermissionEngine
                                            │
                                            ▼  decision = ASK
                                  runner._confirm(name, summary, diff)
                                            │
            ┌── ConfirmRequest{request_id, …} ──► (browser modal)
            │
            │                                      user clicks Allow
            ▼                                              │
  asyncio.Future ◄── ConfirmResponse{request_id, approved, always} ◄┘
            │
            ▼  resolves True/False
        Tool runs (or doesn't)
```

If the user closes the tab mid-prompt, the future times out after 5
minutes and defaults to **deny**.

## Frontend dev workflow

Only needed when editing the frontend. End users never see this.

```bash
cd frontend
npm install        # one-time
npm run dev        # Vite dev server on :5173 with proxy to backend
# Open http://localhost:5173

# Production rebuild (artifact lands in ../src/coding_agent/web/static/)
npm run build

# Type-check only (no emit)
npm run typecheck
```

`vite.config.ts` proxies `/api/*` and `/ws/*` to `127.0.0.1:8765` so
`npm run dev` (frontend) + `coding-agent web` (backend) coexist during
development.

## Testing

The web layer is fully covered by the suite — no real LLM needed:

```bash
uv run pytest tests/unit/test_web_protocol.py     # protocol round-trip
uv run pytest tests/unit/test_web_runner.py       # runner + confirm flow
uv run pytest tests/unit/test_web_routes.py       # REST endpoints
uv run pytest tests/integration/test_web_e2e.py   # WebSocket end-to-end
```

44 web tests; together they pass in <2s.

## Limitations (v1)

- No auth; **don't expose the port** beyond localhost.
- One workspace per tab. Open multiple tabs for multiple workspaces.
- Persistent settings UI is not implemented — config remains YAML.
- The sub-agent (`task` tool) is available to the LLM but doesn't
  surface a separate UI panel; its summary is shown inline as a tool
  result.
