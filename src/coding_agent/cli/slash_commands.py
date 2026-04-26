"""Slash command registry and handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from rich.console import Console
from rich.table import Table

from coding_agent.core.session import Session

SlashHandler = Callable[..., Awaitable[bool] | bool | None]


COMMANDS: dict[str, tuple[str, SlashHandler]] = {}


def slash(name: str, description: str):
    def decorator(fn: SlashHandler) -> SlashHandler:
        COMMANDS[name] = (description, fn)
        return fn
    return decorator


@slash("help", "Show available slash commands")
def cmd_help(console: Console, **_) -> None:
    table = Table(title="Slash Commands", show_header=True)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    for name, (desc, _) in sorted(COMMANDS.items()):
        table.add_row(f"/{name}", desc)
    console.print(table)


@slash("clear", "Clear the screen")
def cmd_clear(console: Console, **_) -> None:
    console.clear()


@slash("cost", "Show session token usage and estimated cost")
def cmd_cost(console: Console, session: Session, **_) -> None:
    u = session.usage
    console.print(f"  Prompt tokens:     {u.prompt_tokens:,}")
    console.print(f"  Completion tokens: {u.completion_tokens:,}")
    console.print(f"  Cached tokens:     {u.cached_prompt_tokens:,}")
    console.print(f"  Total tokens:      {u.total_tokens:,}")


@slash("model", "Show current model info")
def cmd_model(console: Console, provider_name: str = "", model_name: str = "", **_) -> None:
    console.print(f"  Provider: {provider_name}")
    console.print(f"  Model:    {model_name}")


@slash("exit", "Exit the agent")
def cmd_exit(**_) -> bool:
    return True  # signal to REPL to break


@slash("compact", "Show context utilization (compaction runs automatically)")
def cmd_compact(console: Console, session: Session, **_) -> None:
    from coding_agent.core.tokens import count_messages

    total = count_messages(session.messages)
    msg_count = len(session.messages)
    console.print(f"  Messages:    {msg_count}")
    console.print(f"  Est. tokens: {total:,}")
    console.print("  [dim]Compaction runs automatically when context budget is exceeded.[/dim]")


def dispatch_slash(command_line: str, **kwargs) -> bool | None:
    """Parse and execute a slash command. Returns True if should exit."""
    parts = command_line.strip().split(maxsplit=1)
    name = parts[0].lstrip("/")
    handler_entry = COMMANDS.get(name)
    if handler_entry is None:
        console = kwargs.get("console")
        if console:
            console.print(f"  Unknown command: /{name}. Type /help for available commands.", style="dim")
        return None
    _, handler = handler_entry
    result = handler(**kwargs)
    return result


@slash("history", "Show conversation message count by role")
def cmd_history(console: Console, session: Session, **_) -> None:
    from collections import Counter

    counts = Counter(m.role.value for m in session.messages)
    console.print(f"  Total messages: {len(session.messages)}")
    for role in ("system", "user", "assistant", "tool"):
        if counts[role]:
            console.print(f"    {role}: {counts[role]}")


@slash("sessions", "List recent sessions")
def cmd_sessions(console: Console, **_) -> None:
    recent = Session.list_recent(10)
    if not recent:
        console.print("  No saved sessions.", style="dim")
        return
    table = Table(title="Recent Sessions", show_header=True)
    table.add_column("Session ID", style="cyan")
    table.add_column("Created")
    for sid, created in recent:
        table.add_row(sid, created.strftime("%Y-%m-%d %H:%M"))
    console.print(table)


@slash("permissions", "Show current permission settings")
def cmd_permissions(console: Console, **_) -> None:
    from coding_agent.core.config import load_config

    try:
        config = load_config()
    except Exception:
        console.print("  [dim]Could not load config.[/dim]")
        return
    p = config.permissions
    console.print(f"  file_read:  {p.file_read}")
    console.print(f"  file_write: {p.file_write}")
    console.print(f"  bash:       {p.bash}")
    console.print(f"  network:    {p.network}")
    if p.rules_file:
        console.print(f"  rules_file: {p.rules_file}")


@slash("tools", "List all registered tools")
def cmd_tools(console: Console, **_) -> None:
    from coding_agent.tools.base import all_tools

    table = Table(title="Registered Tools", show_header=True)
    table.add_column("Tool", style="bold cyan")
    table.add_column("Description")
    for name, cls in sorted(all_tools().items()):
        table.add_row(name, cls.description[:80])
    console.print(table)
