"""Permission confirmation UI.

Presents a simple terminal prompt for write/bash actions:
  [y] Allow    [n] Deny    [a] Allow for this session
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


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

    con.print()
    con.print(
        Panel(
            Text(summary),
            title=f"⚠ {tool_name} requires approval",
            border_style="yellow",
        )
    )

    if diff_preview:
        con.print(
            Panel(
                Syntax(diff_preview, "diff", theme="monokai"),
                title="Preview",
                border_style="dim",
            )
        )

    con.print()
    con.print("  [bold green]y[/] - Allow   [bold red]n[/] - Deny   [bold cyan]a[/] - Allow all for this session")

    while True:
        try:
            response = input("  (y/n/a) > ").strip().lower()
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
        con.print("  Please enter [bold green]y[/], [bold red]n[/], or [bold cyan]a[/].")
