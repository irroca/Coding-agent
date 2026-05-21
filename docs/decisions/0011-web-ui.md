# ADR 0011 — Browser UI

Date: 2026-05-22
Status: Accepted

## Context

The agent has been terminal-only since day one. Two real problems with that:

1. **Windows users**. Native Windows terminals are mediocre; running in WSL
   means giving up Windows-native tooling. A browser UI is the only
   delivery channel that's first-class on every OS.
2. **Demo / discoverability**. A web UI is much more legible at a glance
   than a TUI, especially for non-CLI users (course graders, casual
   evaluators).

Three viable approaches were considered:

1. **Browser UI over WebSocket** (chosen). Python backend exposes
   `Agent.run()` over a WS, React SPA consumes it. WSL2 forwards
   `localhost` to Windows automatically, so the same command works
   everywhere.
2. **Tauri / Electron desktop app**. Rejected — depends on system webview;
   doesn't work cleanly inside WSL (no graphics stack). Forces a
   per-OS download.
3. **TUI-in-browser via ttyd / xterm.js**. Rejected — no real UX win over
   the existing TUI, and we'd lose the structured-data UI affordances
   (collapsible tool cards, side-by-side diffs, etc.).

## Decision

- New optional package `coding_agent.web` (extra: `pip install coding-agent[web]`).
  Deps: `fastapi`, `uvicorn[standard]`, `websockets`.
- A new Typer subcommand `coding-agent web` boots a FastAPI app via
  uvicorn on `127.0.0.1:8765`, no auth.
- **One WebSocket per browser tab**, served at `/ws/{tab_id}`. Each WS
  owns one `SessionRunner` (= one `Agent` + one `Session`).
- **Wire protocol** (`web/protocol.py`) is pydantic-defined and
  discriminated by a `type` field. Server-to-client messages mirror
  `AgentEvent` plus a few control envelopes (`confirm_request`,
  `session_state`, `session_list`, `workspace_list`, `ack`,
  `server_error`). Client-to-server: `submit`, `cancel`,
  `confirm_response`, `attach_session`, `delete_session`,
  `list_sessions`, `list_workspaces`.
- **Permission confirmation** flows over the same WS: the server sends a
  `confirm_request` with a 12-char request id, the runner suspends on
  an `asyncio.Future`, the browser replies with `confirm_response`,
  the future resolves. 5-minute timeout defaults to deny. The
  "Always allow" checkbox feeds into the same per-session
  `auto_approve` set the TUI uses.
- **No new agent/provider/tool code paths.** The runner consumes the
  identical `Agent.run() -> AsyncIterator[AgentEvent]` and implements
  the same `ConfirmCallback` signature already used by `cli/repl.py`.
- **Frontend** is a Vite + React 18 + TypeScript + Tailwind + Radix
  SPA. Build output goes to `src/coding_agent/web/static/`, which is
  **committed and shipped inside the wheel** (via the hatchling
  `force-include` rule). Users `pip install`-ing the package do not
  need Node.
- **State**: one zustand store; one WS hook with auto-reconnect.
- **Markdown** rendered with `react-markdown` + `rehype-highlight`;
  diffs in the confirm modal are colored line-by-line (no extra dep).

## Consequences

- Single deployable command: `coding-agent web` works on macOS, Linux,
  Windows, and WSL (via Windows browser pointing at `localhost`).
- The web layer is **strictly additive**. Pulling it out wouldn't change
  any other file. The TUI is unaffected.
- The bundled SPA adds ~570 KB (uncompressed) to the wheel. Acceptable.
- We pay the cost of keeping `frontend/src/types.ts` in sync with
  `web/protocol.py` until we wire `datamodel-code-generator` (future
  work). The protocol is small enough that manual sync is fine for v1.

## Out of scope (deliberately)

- **Auth, multi-user, remote access.** localhost-only, single user.
- **File browser inside the UI.** Workspace picker is a recent list +
  path input.
- **Settings UI.** Config remains YAML; the web reads but doesn't write.
- **MCP server management UI.** MCP servers stay in YAML.
- **Mobile responsive.** Desktop-first.

## Critical files

- `src/coding_agent/web/protocol.py` — wire-format pydantic types
- `src/coding_agent/web/runner.py` — `SessionRunner` (1 per tab)
- `src/coding_agent/web/server.py` — FastAPI app + WS handler + uvicorn entry
- `src/coding_agent/web/routes.py` — REST endpoints
- `src/coding_agent/cli/app.py` — `web` Typer subcommand
- `frontend/` — Vite + React project; build output committed under
  `src/coding_agent/web/static/`

## Tests

- `tests/unit/test_web_protocol.py` — 22 tests, every message round-trips
- `tests/unit/test_web_runner.py` — 11 tests, runner driven by MockProvider:
  text turn, tool flow, confirm round-trip, always-allow, deny
- `tests/unit/test_web_routes.py` — 6 tests, FastAPI TestClient against
  every REST route
- `tests/integration/test_web_e2e.py` — 5 tests, full WebSocket via
  `TestClient.websocket_connect`: submit / confirm / attach to existing
  session / bad message handling / list_sessions

44 web tests in total, suite still under 12s end-to-end.
