"""Interactive REPL — the main user-facing loop.

Wires together:
  - prompt_toolkit input
  - Agent loop
  - Rich renderer
  - Slash commands
  - Permission confirmation
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.text import Text

from coding_agent.agent.loop import Agent
from coding_agent.cli.confirm import confirm_action
from coding_agent.cli.prompt import create_prompt_session
from coding_agent.cli.render import THEME, Renderer
from coding_agent.cli.slash_commands import dispatch_slash
from coding_agent.core.config import Config, load_config, reset_config_cache
from coding_agent.core.logging import get_logger
from coding_agent.core.session import Session
from coding_agent.providers.base import LLMProvider
from coding_agent.providers.registry import build_provider

log = get_logger("repl")


def _banner(console: Console, config: Config, provider: LLMProvider) -> None:
    console.print()
    console.print(
        Text("  Coding Agent", style="bold cyan"),
        Text(" v0.1.0", style="dim"),
        Text(f"  [{config.provider}:{provider.model}]", style="dim"),
    )
    console.print(
        Text(f"  Workspace: {config.workspace}", style="dim"),
    )
    console.print(
        Text("  Type /help for commands. Ctrl+C to cancel. Ctrl+D to exit.", style="dim"),
    )
    console.print()


def run_repl(
    *,
    resume: str | None = None,
    provider_override: str | None = None,
) -> None:
    """Entry point called from CLI. Boots the async event loop."""
    asyncio.run(_async_repl(resume=resume, provider_override=provider_override))


async def _async_repl(
    *,
    resume: str | None = None,
    provider_override: str | None = None,
) -> None:
    reset_config_cache()
    config = load_config()
    console = Console(theme=THEME)

    try:
        provider = build_provider(config, override=provider_override)
    except Exception as e:
        console.print(f"  [bold red]Failed to initialize provider:[/] {e}")
        console.print("  Check your API key configuration (.env or environment).")
        return

    if resume:
        try:
            session = Session.load(resume)
            console.print(f"  [dim]Resumed session: {session.id}[/dim]")
        except Exception as e:
            console.print(f"  [bold red]Cannot resume session '{resume}':[/] {e}")
            return
    else:
        session = Session(
            workspace=str(config.workspace),
            provider=config.provider,
            model=provider.model,
        )

    auto_approve: set[str] = set()

    async def _confirm(tool_name: str, summary: str, diff: str | None) -> bool:
        renderer.pause()
        result = await confirm_action(
            tool_name, summary, diff,
            console=console,
            auto_approve_session=auto_approve,
        )
        renderer.resume()
        return result

    renderer = Renderer(console=console)
    agent = Agent(provider, config, session, confirm=_confirm)
    prompt_session = create_prompt_session()

    _banner(console, config, provider)

    while True:
        try:
            user_input = await asyncio.to_thread(
                prompt_session.prompt,
                "  > ",
            )
        except EOFError:
            console.print("\n  [dim]Goodbye.[/dim]")
            break
        except KeyboardInterrupt:
            console.print()
            continue

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            should_exit = dispatch_slash(
                user_input,
                console=console,
                session=session,
                provider_name=config.provider,
                model_name=provider.model,
            )
            if should_exit is True:
                console.print("  [dim]Goodbye.[/dim]")
                break
            continue

        renderer.start()
        try:
            async for event in agent.run(user_input):
                renderer.feed(event)
        except KeyboardInterrupt:
            agent.cancel()
            console.print("\n  [dim]Interrupted.[/dim]")
        except Exception as e:
            log.error("repl_error", error=str(e), exc_info=True)
            console.print(f"\n  [bold red]Error:[/] {e}")
        finally:
            renderer.stop()

        console.print()

    if hasattr(provider, "aclose"):
        await provider.aclose()
