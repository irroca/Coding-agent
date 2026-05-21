"""CLI entry point. Full REPL is implemented in cli/repl.py (M3+)."""

from __future__ import annotations

from typing import Annotated

import typer

from coding_agent import __version__
from coding_agent.core.config import load_config
from coding_agent.core.logging import configure_logging, get_logger

app = typer.Typer(
    name="coding-agent",
    help="A production-grade terminal coding agent (Claude Code-style).",
    no_args_is_help=False,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"coding-agent {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True),
    ] = False,
    log_level: Annotated[
        str | None,
        typer.Option("--log-level", help="Override log level (DEBUG/INFO/WARNING/ERROR)."),
    ] = None,
) -> None:
    config = load_config()
    configure_logging(log_level or config.log_level)
    if ctx.invoked_subcommand is None:
        ctx.invoke(chat)


@app.command()
def chat(
    resume: Annotated[
        str | None,
        typer.Option("--resume", "-r", help="Resume a previous session by ID."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Override the active LLM provider."),
    ] = None,
) -> None:
    """Start an interactive chat session (default command)."""
    log = get_logger("cli")
    log.info("starting_chat", resume=resume, provider=provider)
    try:
        from coding_agent.cli.repl import run_repl
    except ImportError:
        typer.echo("REPL not yet implemented (M3 milestone). Showing config instead:\n")
        cfg = load_config()
        typer.echo(f"Provider: {cfg.provider}")
        typer.echo(f"Workspace: {cfg.workspace}")
        return
    run_repl(resume=resume, provider_override=provider)


@app.command()
def sessions(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    grep: Annotated[
        str | None,
        typer.Option("--grep", "-g", help="Only show sessions whose messages contain this substring."),
    ] = None,
) -> None:
    """List recent saved sessions, optionally filtered by content."""
    from coding_agent.core.session import Session

    rows = Session.list_recent(limit=limit if grep is None else 500)
    if grep:
        matches: list[tuple[str, object]] = []
        for sid, ts in rows:
            try:
                session = Session.load(sid)
            except Exception:
                continue
            haystack = "\n".join(
                m.content for m in session.messages
                if m.content and m.role.value in ("user", "assistant")
            )
            if grep.lower() in haystack.lower():
                matches.append((sid, ts))
            if len(matches) >= limit:
                break
        rows = matches

    if not rows:
        typer.echo("(no matching sessions)" if grep else "(no saved sessions)")
        return
    for sid, ts in rows:
        typer.echo(f"{sid}\t{ts.isoformat()}")


@app.command()
def config_show() -> None:
    """Print the resolved configuration (with API keys redacted)."""
    cfg = load_config()
    data = cfg.model_dump()
    for prov in data.get("providers", {}).values():
        if prov.get("api_key"):
            prov["api_key"] = prov["api_key"][:4] + "***"
    import json

    typer.echo(json.dumps(data, indent=2, default=str))


@app.command()
def web(
    host: Annotated[
        str, typer.Option("--host", help="Bind address. Default 127.0.0.1 (localhost only).")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p")] = 8765,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="Workspace path (defaults to cwd from config)."),
    ] = None,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open-browser/--no-open-browser",
            help="Open the system browser at startup.",
        ),
    ] = True,
) -> None:
    """Run the agent in a browser UI (localhost only by default)."""
    try:
        from coding_agent.web.server import run as run_web
    except ImportError as e:
        typer.echo(
            "Web UI dependencies missing. Install with: "
            "pip install coding-agent[web]\n"
            f"Original error: {e}",
            err=True,
        )
        raise typer.Exit(1) from None
    from pathlib import Path

    run_web(
        host=host,
        port=port,
        workspace=Path(workspace) if workspace else None,
        open_browser=open_browser,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
