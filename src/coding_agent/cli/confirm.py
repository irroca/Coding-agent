"""Permission confirmation UI.

Presents a modern terminal prompt for write/bash actions. Mirrors the
browser permission modal: shield icon, diff with stats, keyboard caps.

  [y] Allow    [n] Deny    [a] Allow for this session
"""

from __future__ import annotations

from rich.box import ROUNDED
from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


def _diff_stats(diff: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


async def confirm_action(
    tool_name: str,
    summary: str,
    diff_preview: str | None,
    *,
    console: Console | None = None,
    auto_approve_session: set[str] | None = None,
) -> bool:
    """Ask user to approve a tool action.

    Returns True if approved. The *auto_approve_session* set tracks tools
    the user has permanently approved for this session.
    """
    if auto_approve_session and tool_name in auto_approve_session:
        return True

    con = console or Console()

    # ── Header: shield icon + title ──
    header = Table.grid(padding=(0, 1))
    header.add_column(no_wrap=True)
    header.add_column()
    title = Text()
    title.append("Allow ", style="bold")
    title.append(tool_name, style="tool.name")
    title.append(" ?", style="bold")
    subtitle = Text(
        "Review the action before approving. Approving once won't auto-allow next time.",
        style="muted",
    )
    header.add_row(Text("🛡", style="warn"), Group(title, subtitle))

    summary_block = Panel(
        Text(summary, no_wrap=False),
        box=ROUNDED,
        border_style="subtle",
        padding=(0, 1),
    )

    children: list[Text | Panel | Table] = [header, Text(), summary_block]

    if diff_preview:
        added, removed = _diff_stats(diff_preview)
        diff_title = Text()
        diff_title.append("diff preview  ", style="muted")
        diff_title.append(f"+{added}", style="ok")
        diff_title.append("  ", style="muted")
        diff_title.append(f"−{removed}", style="error")  # noqa: RUF001 — minus-glyph for diff
        children.append(Text())
        children.append(
            Panel(
                Syntax(diff_preview, "diff", theme="ansi_dark", background_color="default"),
                title=diff_title,
                title_align="left",
                box=ROUNDED,
                border_style="subtle",
                padding=(0, 1),
            )
        )

    con.print()
    con.print(
        Panel(
            Group(*children),
            box=ROUNDED,
            border_style="warn",
            padding=(1, 2),
            title="[warn]⚠ Permission required[/]",
            title_align="left",
        )
    )

    hint = Text()
    hint.append("  ")
    hint.append(" y ", style="kbd")
    hint.append(" allow   ", style="muted")
    hint.append(" n ", style="kbd")
    hint.append(" deny   ", style="muted")
    hint.append(" a ", style="kbd")
    hint.append(" allow for this session", style="muted")
    con.print(hint)

    while True:
        try:
            response = input("  ❯ ").strip().lower()  # noqa: RUF001 — caret prompt
        except (EOFError, KeyboardInterrupt):
            return False

        if response in ("y", "yes", "allow", ""):
            return True
        if response in ("n", "no", "deny"):
            return False
        if response in ("a", "always"):
            if auto_approve_session is not None:
                auto_approve_session.add(tool_name)
            return True
        con.print(
            "  [muted]Please enter[/] [kbd] y [/] [muted],[/] [kbd] n [/] [muted], or[/] [kbd] a [/][muted].[/]"
        )
