"""prompt_toolkit-based input with multi-line support and history."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


def _history_path() -> Path:
    p = Path(user_data_dir("coding_agent"))
    p.mkdir(parents=True, exist_ok=True)
    return p / "input_history"


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
        history=FileHistory(str(_history_path())),
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=kb,
        multiline=False,
        enable_history_search=True,
    )
