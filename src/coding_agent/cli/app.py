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
) -> None:
    """List recent saved sessions."""
    from coding_agent.core.session import Session

    rows = Session.list_recent(limit=limit)
    if not rows:
        typer.echo("(no saved sessions)")
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
