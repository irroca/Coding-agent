"""Rich-powered rendering for the agent TUI.

Renders agent events in real-time:
  - Assistant text: streamed as Markdown (via Live)
  - Tool calls: name + result panels
  - Usage: token count footer
  - Errors: red highlighted blocks

All output for one agent turn is collected and printed as a single bordered
block at the end, giving a clear visual separation between user and agent.
During streaming, Live only shows the current text being generated.
"""

from __future__ import annotations

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from coding_agent.agent.loop import AgentEvent, EventKind

THEME = Theme(
    {
        "tool.name": "bold cyan",
        "tool.ok": "green",
        "tool.fail": "bold red",
        "cost": "dim",
        "error": "bold red",
    }
)


class Renderer:
    """Renders agent events with a unified outer panel per turn."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(theme=THEME)
        self._text_buf: list[str] = []
        self._items: list[Panel | Text] = []
        self._live: Live | None = None
        self._usage_text: str | None = None

    def start(self) -> None:
        self._text_buf = []
        self._items = []
        self._usage_text = None

    def pause(self) -> None:
        """Pause Live for blocking UI (permission prompt)."""
        self._stop_live()
        self._commit_text()
        self._print_block()

    def resume(self) -> None:
        """Resume after pause — reset items since we already printed."""
        self._items = []
        self._usage_text = None

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
            self._items.append(Text(f"  ⚙ {tc.name}", style="tool.name"))

        elif event.kind == EventKind.TOOL_RESULT and event.tool_result:
            tr = event.tool_result
            style = "tool.ok" if tr.ok else "tool.fail"
            status = "✓" if tr.ok else "✗"
            content = tr.content
            if len(content) > 500:
                content = content[:500] + "\n... (truncated)"
            result_panel = Panel(
                Text(content),
                title=f"{status} {tr.tool}",
                border_style=style,
                expand=False,
            )
            if self._items and isinstance(self._items[-1], Text):
                last_text = self._items[-1].plain
                if last_text.strip().startswith("⚙"):
                    self._items[-1] = result_panel
                else:
                    self._items.append(result_panel)
            else:
                self._items.append(result_panel)

        elif event.kind == EventKind.USAGE and event.usage:
            u = event.usage
            cost_text = (
                f"Tokens: {u.prompt_tokens} prompt + {u.completion_tokens} completion"
            )
            if u.cached_prompt_tokens:
                cost_text += f" ({u.cached_prompt_tokens} cached)"
            self._usage_text = cost_text

        elif event.kind == EventKind.ERROR:
            self._stop_live()
            self._commit_text()
            self._items.append(Text(f"  Error: {event.error}", style="error"))

        elif event.kind == EventKind.TURN_END:
            self._stop_live()
            self._commit_text()

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
                Panel(Markdown(md_text), border_style="dim", expand=True)
            )
            self._text_buf = []

    def _print_block(self) -> None:
        """Print all accumulated items wrapped in a single outer panel."""
        if not self._items and not self._usage_text:
            return

        renderables = list(self._items)

        if renderables:
            subtitle = self._usage_text or None
            self.console.print(
                Panel(
                    Group(*renderables),
                    title="[bold cyan]Agent[/]",
                    subtitle=f"[dim]{subtitle}[/]" if subtitle else None,
                    border_style="cyan",
                    expand=True,
                    padding=(0, 1),
                )
            )
        elif self._usage_text:
            self.console.print(Text(f"  {self._usage_text}", style="cost"))

        self._items = []
        self._usage_text = None
