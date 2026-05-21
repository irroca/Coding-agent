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


@slash("cost", "Show session token usage, cache hit rate, and estimated cost")
def cmd_cost(console: Console, session: Session, **_) -> None:
    u = session.usage
    console.print(f"  Prompt tokens:     {u.prompt_tokens:,}")
    console.print(f"  Completion tokens: {u.completion_tokens:,}")
    console.print(f"  Cached tokens:     {u.cached_prompt_tokens:,}")
    if u.cache_creation_tokens:
        console.print(f"  Cache writes:      {u.cache_creation_tokens:,}")
    console.print(f"  Total tokens:      {u.total_tokens:,}")
    if u.prompt_tokens:
        console.print(
            f"  Cache hit rate:    {u.cache_hit_rate * 100:.1f}% "
            f"[dim]({u.cached_prompt_tokens:,}/{u.prompt_tokens:,})[/dim]"
        )


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


@slash("diff", "Show the cumulative diff of file changes made this session")
def cmd_diff(console: Console, session: Session, **_) -> None:
    """Reconstruct unified diffs from every write/edit tool result on record."""
    from collections import OrderedDict

    # path → (first_pre_image, latest_post_image). We collapse repeated writes
    # to the same file so the displayed diff is "before any change → now".
    file_snapshots: OrderedDict[str, tuple[str, str]] = OrderedDict()

    for msg in session.messages:
        if msg.role.value != "tool":
            continue
        for r in msg.tool_results:
            if r.tool not in ("write", "edit") or not r.ok:
                continue
            path = r.metadata.get("path")
            prev = r.metadata.get("previous_content")
            new = r.metadata.get("new_content")
            if not path or prev is None or new is None:
                continue
            if path in file_snapshots:
                first_prev, _ = file_snapshots[path]
                file_snapshots[path] = (first_prev, new)
            else:
                file_snapshots[path] = (prev, new)

    if not file_snapshots:
        console.print("  [dim]No file changes recorded in this session yet.[/dim]")
        return

    import difflib
    from pathlib import Path

    for path, (prev, new) in file_snapshots.items():
        name = Path(path).name
        diff_text = "".join(
            difflib.unified_diff(
                prev.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
        if not diff_text:
            continue
        console.print(f"\n[bold]{path}[/bold]")
        for line in diff_text.splitlines():
            style = ""
            if line.startswith("+++") or line.startswith("---"):
                style = "bold"
            elif line.startswith("+"):
                style = "green"
            elif line.startswith("-"):
                style = "red"
            elif line.startswith("@@"):
                style = "cyan"
            console.print(line, style=style, highlight=False)


@slash("undo", "Revert the last write/edit performed by the agent")
def cmd_undo(console: Console, session: Session, **_) -> None:
    """Pop the most recent successful write/edit and restore its pre-image.

    Only file_write actions are undoable; bash side-effects are not."""
    from pathlib import Path

    for msg in reversed(session.messages):
        if msg.role.value != "tool":
            continue
        for r in reversed(msg.tool_results):
            if r.tool not in ("write", "edit") or not r.ok:
                continue
            if r.metadata.get("undone"):
                continue
            path_str = r.metadata.get("path")
            prev = r.metadata.get("previous_content")
            if not path_str or prev is None:
                continue
            target = Path(path_str)
            try:
                if prev == "" and r.metadata.get("created"):
                    # File didn't exist before — delete it.
                    target.unlink(missing_ok=True)
                    action = "deleted"
                else:
                    target.write_text(prev, encoding="utf-8")
                    action = "restored"
            except OSError as e:
                console.print(f"  [red]Cannot undo {target}: {e}[/red]")
                return
            r.metadata["undone"] = True
            console.print(f"  [yellow]Undone[/yellow]: {action} {target}")
            session.save()
            return

    console.print("  [dim]No undoable write/edit in this session.[/dim]")
