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

from rich.box import ROUNDED
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from coding_agent import __version__
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


def _wordmark() -> Text:
    """ASCII wordmark coloured with a blue→violet gradient."""
    letters = "CODING  AGENT"
    # Two-stop gradient: brand blue (#2563eb) → brand violet (#7c3aed).
    starts = (0x25, 0x63, 0xEB)
    ends = (0x7C, 0x3A, 0xED)
    n = max(len(letters) - 1, 1)
    text = Text()
    for i, ch in enumerate(letters):
        if ch == " ":
            text.append(" ")
            continue
        r = int(starts[0] + (ends[0] - starts[0]) * i / n)
        g = int(starts[1] + (ends[1] - starts[1]) * i / n)
        b = int(starts[2] + (ends[2] - starts[2]) * i / n)
        text.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
    return text


def _banner(
    console: Console,
    config: Config,
    provider: LLMProvider,
    session: Session,
) -> None:
    """Render a modern startup screen — gradient wordmark, info grid, tip strip."""
    info = Table.grid(padding=(0, 2))
    info.add_column(style="muted", no_wrap=True)
    info.add_column(style="bold")
    info.add_row("provider", f"[brand]{config.provider}[/] [muted]·[/] {provider.model}")
    info.add_row("workspace", str(config.workspace))
    info.add_row("session", session.id)

    body = Group(
        Text(),
        _wordmark(),
        Text(f"v{__version__}  ·  production-grade terminal coding agent", style="muted"),
        Text(),
        info,
    )

    console.print()
    console.print(
        Panel(
            body,
            box=ROUNDED,
            border_style="brand",
            padding=(0, 2),
            expand=False,
        )
    )

    tips = Text()
    tips.append(" ⌨  ", style="brand")
    tips.append("/help", style="kbd")
    tips.append(" commands  ", style="muted")
    tips.append("Enter", style="kbd")
    tips.append(" send  ", style="muted")
    tips.append("Esc Enter", style="kbd")
    tips.append(" newline  ", style="muted")
    tips.append("Ctrl+C", style="kbd")
    tips.append(" cancel  ", style="muted")
    tips.append("Ctrl+D", style="kbd")
    tips.append(" exit", style="muted")
    console.print(tips)
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

    # Discover third-party plugins (tools / providers / slash commands).
    # Must run *before* we build the provider so plugin-provided providers
    # can be selected via --provider.
    from coding_agent.plugins import load_plugins

    plugin_summary = load_plugins()
    if any(plugin_summary.values()):
        log.info("plugins_loaded", **plugin_summary)

    console = Console(theme=THEME)

    try:
        provider = build_provider(config, override=provider_override)
    except Exception as e:
        console.print(f"  [error]✗ Failed to initialize provider:[/] {e}")
        console.print("  [muted]Check your API key configuration (.env or environment).[/]")
        return

    if resume:
        try:
            session = Session.load(resume)
            console.print(f"  [muted]↻ Resumed session[/] [accent]{session.id}[/]")
        except Exception as e:
            console.print(f"  [error]✗ Cannot resume session[/] '{resume}': {e}")
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

    # ── Optional: connect external MCP servers and inject their tools ──
    mcp_host = None
    if config.mcp_servers:
        try:
            from coding_agent.mcp.client import McpClientHost, specs_from_config

            mcp_host = McpClientHost(specs_from_config(config.mcp_servers))
            await mcp_host.start()
        except ImportError:
            console.print(
                "  [warn]⚠[/] mcp_servers configured but the [accent]mcp[/] extra is "
                "not installed. Run [bold]pip install coding-agent[mcp][/]."
            )
            mcp_host = None
        except Exception as e:
            console.print(f"  [warn]⚠ Failed to start MCP host:[/] {e}")
            mcp_host = None

    _banner(console, config, provider, session)

    while True:
        try:
            user_input = await asyncio.to_thread(prompt_session.prompt)
        except EOFError:
            console.print("\n  [muted]✦ Goodbye.[/]")
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
                console.print("  [muted]✦ Goodbye.[/]")
                break
            continue

        renderer.start()
        try:
            async for event in agent.run(user_input):
                renderer.feed(event)
        except KeyboardInterrupt:
            agent.cancel()
            console.print("\n  [warn]⏹ Interrupted.[/]")
        except Exception as e:
            log.error("repl_error", error=str(e), exc_info=True)
            console.print(f"\n  [error]✗ Error:[/] {e}")
        finally:
            renderer.stop()

        console.print()

    if hasattr(provider, "aclose"):
        await provider.aclose()
    if mcp_host is not None:
        await mcp_host.aclose()
