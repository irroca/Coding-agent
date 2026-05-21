"""Slash command registry and handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from rich.box import ROUNDED, SIMPLE_HEAD
from rich.console import Console
from rich.table import Table

from coding_agent.core.session import Session

SlashHandler = Callable[..., Awaitable[bool] | bool | None]


COMMANDS: dict[str, tuple[str, SlashHandler]] = {}

# ── Inline color palette (kept in sync with cli/render.py) ──
# Using hex literals means slash commands render correctly even when the
# Console wasn't constructed with our Theme (e.g. in unit tests).
_BRAND = "#2563eb"
_BRAND_ALT = "#7c3aed"
_MUTED = "#a1a1aa"
_OK = "#10b981"
_WARN = "#f59e0b"
_ERROR = "#f43f5e"


def slash(name: str, description: str):
    def decorator(fn: SlashHandler) -> SlashHandler:
        COMMANDS[name] = (description, fn)
        return fn
    return decorator


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    """Two-column key/value table — used by all info-style slash commands."""
    t = Table.grid(padding=(0, 2))
    t.add_column(style=_MUTED, justify="right", no_wrap=True)
    t.add_column(style="bold")
    for k, v in rows:
        t.add_row(k, v)
    return t


@slash("help", "Show available slash commands")
def cmd_help(console: Console, **_) -> None:
    table = Table(
        title=f"[bold {_BRAND}]◆ Slash commands[/]",
        title_justify="left",
        box=ROUNDED,
        border_style=_BRAND,
        header_style="bold",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Command", style=f"bold {_BRAND}", no_wrap=True)
    table.add_column("Description", style=_MUTED)
    for name, (desc, _) in sorted(COMMANDS.items()):
        table.add_row(f"/{name}", desc)
    console.print(table)


@slash("clear", "Clear the screen")
def cmd_clear(console: Console, **_) -> None:
    console.clear()


@slash("cost", "Show session token usage, cache hit rate, and estimated cost")
def cmd_cost(console: Console, session: Session, **_) -> None:
    u = session.usage
    rows = [
        ("prompt", f"{u.prompt_tokens:,}"),
        ("completion", f"{u.completion_tokens:,}"),
        ("cached", f"{u.cached_prompt_tokens:,}"),
    ]
    if u.cache_creation_tokens:
        rows.append(("cache writes", f"{u.cache_creation_tokens:,}"))
    rows.append(("total", f"[bold {_BRAND}]{u.total_tokens:,}[/]"))
    if u.prompt_tokens:
        rate = u.cache_hit_rate * 100
        rows.append(
            (
                "cache hit rate",
                f"[bold {_OK}]{rate:.1f}%[/] [{_MUTED}]({u.cached_prompt_tokens:,} / {u.prompt_tokens:,})[/]",
            )
        )
    console.print(_kv_table(rows))


@slash("model", "Show current model info")
def cmd_model(console: Console, provider_name: str = "", model_name: str = "", **_) -> None:
    console.print(_kv_table([("provider", provider_name), ("model", model_name)]))


@slash("exit", "Exit the agent")
def cmd_exit(**_) -> bool:
    return True  # signal to REPL to break


@slash("compact", "Show context utilization (compaction runs automatically)")
def cmd_compact(console: Console, session: Session, **_) -> None:
    from coding_agent.core.tokens import count_messages

    total = count_messages(session.messages)
    msg_count = len(session.messages)
    console.print(
        _kv_table(
            [
                ("messages", str(msg_count)),
                ("est. tokens", f"{total:,}"),
            ]
        )
    )
    console.print(
        f"  [{_MUTED}]Compaction runs automatically when the context budget is exceeded.[/]"
    )


def dispatch_slash(command_line: str, **kwargs) -> bool | None:
    """Parse and execute a slash command. Returns True if should exit."""
    parts = command_line.strip().split(maxsplit=1)
    name = parts[0].lstrip("/")
    handler_entry = COMMANDS.get(name)
    if handler_entry is None:
        console = kwargs.get("console")
        if console:
            console.print(
                f"  [bold {_ERROR}]✗[/] Unknown command [bold {_BRAND}]/{name}[/]. "
                f"Type [bold {_BRAND}]/help[/] for available commands."
            )
        return None
    _, handler = handler_entry
    result = handler(**kwargs)
    return result


@slash("history", "Show conversation message count by role")
def cmd_history(console: Console, session: Session, **_) -> None:
    from collections import Counter

    counts = Counter(m.role.value for m in session.messages)
    rows = [("total", str(len(session.messages)))]
    for role in ("system", "user", "assistant", "tool"):
        if counts[role]:
            rows.append((role, str(counts[role])))
    console.print(_kv_table(rows))


@slash("sessions", "List recent sessions")
def cmd_sessions(console: Console, **_) -> None:
    recent = Session.list_recent(10)
    if not recent:
        console.print(f"  [{_MUTED}]No saved sessions.[/]")
        return
    table = Table(
        title=f"[bold {_BRAND}]◆ Recent sessions[/]",
        title_justify="left",
        box=SIMPLE_HEAD,
        border_style=_BRAND,
        header_style="bold",
        padding=(0, 1),
    )
    table.add_column("Session ID", style=f"bold {_BRAND}", no_wrap=True)
    table.add_column("Created", style=_MUTED)
    for sid, created in recent:
        table.add_row(sid, created.strftime("%Y-%m-%d %H:%M"))
    console.print(table)


@slash("permissions", "Show current permission settings")
def cmd_permissions(console: Console, **_) -> None:
    from coding_agent.core.config import load_config

    try:
        config = load_config()
    except Exception:
        console.print(f"  [{_MUTED}]Could not load config.[/]")
        return
    p = config.permissions

    def colorize(decision: str) -> str:
        d = str(decision).lower()
        if "allow" in d:
            return f"[bold {_OK}]{decision}[/]"
        if "deny" in d:
            return f"[bold {_ERROR}]{decision}[/]"
        return f"[bold {_WARN}]{decision}[/]"

    rows = [
        ("file_read", colorize(p.file_read)),
        ("file_write", colorize(p.file_write)),
        ("bash", colorize(p.bash)),
    ]
    if p.rules_file:
        rows.append(("rules_file", str(p.rules_file)))
    console.print(_kv_table(rows))


@slash("tools", "List all registered tools")
def cmd_tools(console: Console, **_) -> None:
    from coding_agent.tools.base import all_tools

    table = Table(
        title=f"[bold {_BRAND}]◆ Registered tools[/]",
        title_justify="left",
        box=SIMPLE_HEAD,
        border_style=_BRAND,
        header_style="bold",
        padding=(0, 1),
    )
    table.add_column("Tool", style=f"bold {_BRAND}", no_wrap=True)
    table.add_column("Description", style=_MUTED)
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
        console.print(f"  [{_MUTED}]No file changes recorded in this session yet.[/]")
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
        console.print(f"\n[bold]{path}[/]")
        for line in diff_text.splitlines():
            style = ""
            if line.startswith("+++") or line.startswith("---"):
                style = "bold"
            elif line.startswith("+"):
                style = _OK
            elif line.startswith("-"):
                style = _ERROR
            elif line.startswith("@@"):
                style = _BRAND
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
                console.print(f"  [bold {_ERROR}]✗ Cannot undo {target}:[/] {e}")
                return
            r.metadata["undone"] = True
            console.print(f"  [bold {_WARN}]↶ Undone[/]: {action} [bold {_BRAND}]{target}[/]")
            session.save()
            return

    console.print(f"  [{_MUTED}]No undoable write/edit in this session.[/]")
