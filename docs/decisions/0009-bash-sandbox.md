# ADR 0009 — Bash sandbox driver

Date: 2026-05-21
Status: Accepted (B6)

## Context

`BashTool` historically ran every command via `asyncio.create_subprocess_shell`
in the host's process namespace. The permission engine and command guard
catch the obviously dangerous cases (`rm -rf /`, fork bombs, network calls),
but a determined or LLM-confused prompt-injection can still:

- Touch files outside the workspace via creative path manipulation.
- Exhaust CPU / memory.
- Reach internal network services.

Production deployments — CI runners, hosted Agent SaaS, classroom
environments — want hard isolation.

We also noticed `PermissionsConfig.network` was declared but no tool ever
used it; the bash command guard simply flagged `curl`/`wget` as dangerous.
Dead concept → delete.

## Decision

- Add `AgentConfig.bash_driver: Literal["subprocess", "docker"] = "subprocess"`.
- Add `AgentConfig.bash_docker_image: str = "python:3.12-slim"`.
- `subprocess` driver is the existing path, unchanged.
- `docker` driver shells out to `docker run` with:
  - `--rm` (no leftover containers)
  - `--network none` (no network exfiltration)
  - `--cpus 2 --memory 1g` (resource caps)
  - `--security-opt no-new-privileges`
  - Workspace mounted at `/workspace`, `--workdir /workspace`
  - Refuses to run if `working_directory` resolves outside the workspace.
- If `docker` binary is missing or returns a friendly error, fall back to
  a clear message — we never silently downgrade to `subprocess`.
- **Delete `PermissionsConfig.network`** and the
  `_provider_env_key("network")` path in the engine. Backwards-incompatible
  for users who wrote YAML referencing it; we log a warning if seen.

## Consequences

- Hosting Coding Agent for untrusted users becomes practical: set
  `bash_driver = "docker"` in the project config and the worst the LLM can
  do is mangle files inside the workspace.
- Performance cost: docker startup ~0.5-1s per command. Acceptable for the
  isolation it buys; users who don't need it leave `subprocess` on.
- One config concept removed; the action vocabulary is now exactly
  `file_read | file_write | bash`.

## Alternatives considered

- **Firejail / bubblewrap** — Linux-only, complex setup. Docker is
  cross-platform and the default tool every dev already has.
- **Run the entire agent in docker** — heavier-handed; users want native
  TUI access for development.
