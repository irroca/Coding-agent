"""prompt_toolkit-based input with multi-line support and history."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style


def _history_path() -> Path:
    p = Path(user_data_dir("coding_agent"))
    p.mkdir(parents=True, exist_ok=True)
    return p / "input_history"


# Match the Rich brand palette so the caret matches the agent panel border.
_PROMPT_STYLE = Style.from_dict(
    {
        "caret": "#2563eb bold",
        "caret.shadow": "#7c3aed",
        "muted": "#a1a1aa",
        "bottom-toolbar": "fg:#a1a1aa bg:#18181b",
        "bottom-toolbar.kbd": "fg:#fafafa bg:#27272a bold",
        "bottom-toolbar.brand": "fg:#2563eb bold",
    }
)


def _prompt_fragments() -> FormattedText:
    return FormattedText(
        [
            ("", "  "),
            ("class:caret", "❯"),  # noqa: RUF001 — intentional caret glyph
            ("class:caret.shadow", "❯ "),  # noqa: RUF001 — intentional caret glyph
        ]
    )


def _bottom_toolbar() -> FormattedText:
    return FormattedText(
        [
            ("class:bottom-toolbar", " "),
            ("class:bottom-toolbar.brand", "coding-agent"),
            ("class:bottom-toolbar", "  · type "),
            ("class:bottom-toolbar.kbd", " /help "),
            ("class:bottom-toolbar", " for commands  ·  "),
            ("class:bottom-toolbar.kbd", " Esc Enter "),
            ("class:bottom-toolbar", " newline  ·  "),
            ("class:bottom-toolbar.kbd", " Ctrl+D "),
            ("class:bottom-toolbar", " exit "),
        ]
    )


def create_prompt_session() -> PromptSession:
    kb = KeyBindings()

    @kb.add(Keys.Enter)
    def _submit(event):
        buf = event.current_buffer
        if buf.text.strip():
            buf.validate_and_handle()

    @kb.add(Keys.Escape, Keys.Enter)
    def _newline(event):
        event.current_buffer.insert_text("\n")

    return PromptSession(
        message=_prompt_fragments,
        bottom_toolbar=_bottom_toolbar,
        style=_PROMPT_STYLE,
        history=FileHistory(str(_history_path())),
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=kb,
        multiline=False,
        enable_history_search=True,
    )
