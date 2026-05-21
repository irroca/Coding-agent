"""Rich-powered rendering for the agent TUI.

Renders agent events in real-time:
  - Assistant text: streamed as Markdown (via Live)
  - Tool calls: per-tool icon + status, two-pane args/result on completion
  - Usage: token + cache-rate strip
  - Errors: red highlighted blocks

The visual language tracks the browser UI: zinc surfaces, brand colors
(blue / violet / emerald / amber / rose), rounded borders, soft dim rules.
"""

from __future__ import annotations

from rich.box import ROUNDED
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.theme import Theme

from coding_agent.agent.loop import AgentEvent, EventKind

# ── Brand palette (mirrors frontend/tailwind.config.ts) ──
# blue   #2563eb   violet #7c3aed   emerald #10b981
# amber  #f59e0b   rose   #f43f5e   zinc-400 #a1a1aa
THEME = Theme(
    {
        # Brand
        "brand": "#2563eb",
        "brand.alt": "#7c3aed",
        "accent": "bold #2563eb",
        "muted": "#a1a1aa",
        "subtle": "dim #a1a1aa",
        # Tool states
        "tool.name": "bold #2563eb",
        "tool.run": "bold #f59e0b",
        "tool.ok": "bold #10b981",
        "tool.fail": "bold #f43f5e",
        # Misc
        "cost": "dim #a1a1aa",
        "error": "bold #f43f5e",
        "ok": "bold #10b981",
        "warn": "bold #f59e0b",
        "kbd": "reverse bold",
        # Markdown overrides — Rich picks these up
        "markdown.code": "bold #7c3aed",
        "markdown.link": "underline #2563eb",
        "markdown.h1": "bold #2563eb",
        "markdown.h2": "bold #2563eb",
    }
)


# Map of tool name → (icon, color style name from THEME).
# Falls back to ⚙ / brand for anything not listed.
_TOOL_META: dict[str, tuple[str, str]] = {
    "read": ("📖", "brand"),
    "write": ("✎", "brand.alt"),
    "edit": ("✎", "brand.alt"),
    "ls": ("▤", "muted"),
    "glob": ("✦", "muted"),
    "grep": ("⌕", "muted"),
    "bash": ("▶", "warn"),
    "todo_write": ("✓", "ok"),
    "task": ("⚑", "brand.alt"),
}


def _tool_icon(name: str) -> tuple[str, str]:
    if name in _TOOL_META:
        return _TOOL_META[name]
    # MCP-supplied remote tools come through with mcp__<server>__<tool> names.
    if name.startswith("mcp__"):
        return ("◇", "brand.alt")
    return ("⚙", "brand")


class Renderer:
    """Renders agent events with a unified outer panel per turn."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(theme=THEME)
        self._text_buf: list[str] = []
        self._items: list[Panel | Text | Rule | Group] = []
        self._live: Live | None = None
        self._usage_text: str | None = None
        # Track running tool calls so we can fold the result into the same row.
        self._pending_tool: tuple[str, str] | None = None  # (name, icon)

    def start(self) -> None:
        self._text_buf = []
        self._items = []
        self._usage_text = None
        self._pending_tool = None

    def pause(self) -> None:
        """Pause Live for blocking UI (permission prompt)."""
        self._stop_live()
        self._commit_text()
        self._print_block()

    def resume(self) -> None:
        """Resume after pause — reset items since we already printed."""
        self._items = []
        self._usage_text = None
        self._pending_tool = None

    def stop(self) -> None:
        self._stop_live()
        self._commit_text()
        self._print_block()

    def feed(self, event: AgentEvent) -> None:
        if event.kind == EventKind.TEXT_DELTA:
            if not self._text_buf and not self._live:
                self._start_live()
            self._text_buf.append(event.text)
            self._refresh_live()

        elif event.kind == EventKind.TOOL_START and event.tool_call:
            self._stop_live()
            self._commit_text()
            tc = event.tool_call
            icon, color = _tool_icon(tc.name)
            self._pending_tool = (tc.name, icon)
            header = Text()
            header.append(f"  {icon} ", style=color)
            header.append(tc.name, style="tool.name")
            header.append("  ", style="dim")
            header.append("running…", style="tool.run")
            self._items.append(header)

        elif event.kind == EventKind.TOOL_RESULT and event.tool_result:
            tr = event.tool_result
            icon, color = _tool_icon(tr.tool)
            status_style = "tool.ok" if tr.ok else "tool.fail"
            status_glyph = "✓" if tr.ok else "✗"
            status_word = "ok" if tr.ok else "failed"

            content = tr.content
            if len(content) > 600:
                content = content[:600] + "\n…[truncated]"

            header_line = Text()
            header_line.append(f"  {icon} ", style=color)
            header_line.append(tr.tool, style="tool.name")
            header_line.append("  ", style="dim")
            header_line.append(f"{status_glyph} {status_word}", style=status_style)

            body = Panel(
                Text(content, no_wrap=False),
                box=ROUNDED,
                border_style="tool.ok" if tr.ok else "tool.fail",
                padding=(0, 1),
                expand=True,
            )

            block = Group(header_line, body)

            # Replace the most recent "running…" header for this tool if present.
            replaced = False
            if (
                self._pending_tool
                and self._pending_tool[0] == tr.tool
                and self._items
                and isinstance(self._items[-1], Text)
                and "running…" in self._items[-1].plain
            ):
                self._items[-1] = block
                replaced = True
            if not replaced:
                self._items.append(block)
            self._pending_tool = None

        elif event.kind == EventKind.USAGE and event.usage:
            u = event.usage
            parts = [
                f"↑ {u.prompt_tokens:,}",
                f"↓ {u.completion_tokens:,}",
            ]
            if u.prompt_tokens:
                rate = u.cache_hit_rate * 100
                parts.append(f"cache {rate:.0f}%")
            self._usage_text = "  ·  ".join(parts)

        elif event.kind == EventKind.ERROR:
            self._stop_live()
            self._commit_text()
            self._items.append(
                Panel(
                    Text(str(event.error or "unknown error"), style="error"),
                    box=ROUNDED,
                    border_style="error",
                    title="✗ error",
                    title_align="left",
                    padding=(0, 1),
                )
            )

        elif event.kind == EventKind.TURN_END:
            self._stop_live()
            self._commit_text()

    # ── Live / streaming helpers ──

    def _start_live(self) -> None:
        if self._live:
            return
        self._live = Live(
            "",
            console=self.console,
            refresh_per_second=15,
            vertical_overflow="visible",
        )
        self._live.start()

    def _stop_live(self) -> None:
        if self._live:
            self._live.update("")
            self._live.stop()
            self._live = None

    def _refresh_live(self) -> None:
        if not self._live or not self._text_buf:
            return
        self._live.update(Markdown("".join(self._text_buf)))

    def _commit_text(self) -> None:
        """Move streaming text buffer into items list as Markdown."""
        if self._text_buf:
            md_text = "".join(self._text_buf)
            self._items.append(
                Panel(
                    Markdown(md_text),
                    box=ROUNDED,
                    border_style="subtle",
                    padding=(0, 1),
                    expand=True,
                )
            )
            self._text_buf = []

    def _print_block(self) -> None:
        """Print all accumulated items wrapped in a single outer panel."""
        if not self._items and not self._usage_text:
            return

        renderables = list(self._items)

        if renderables:
            subtitle = (
                Text(self._usage_text, style="cost") if self._usage_text else None
            )
            title = Text()
            title.append("◆ ", style="brand")
            title.append("Agent", style="accent")
            self.console.print(
                Panel(
                    Group(*renderables),
                    title=title,
                    title_align="left",
                    subtitle=subtitle,
                    subtitle_align="right",
                    box=ROUNDED,
                    border_style="brand",
                    expand=True,
                    padding=(0, 1),
                )
            )
        elif self._usage_text:
            self.console.print(Text(f"  {self._usage_text}", style="cost"))

        self._items = []
        self._usage_text = None
        self._pending_tool = None
