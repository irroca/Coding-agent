"""Tests for the new B8 UX commands: /diff and /undo.

We invoke the slash handlers directly with a synthetic Session and capture
their output via rich.Console(record=True). The /undo handler also mutates
the filesystem, which we verify against tmp_path.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from coding_agent.cli.slash_commands import COMMANDS
from coding_agent.core.session import Session
from coding_agent.core.types import Message, Role, ToolResult


def _session_with_writes(workspace: Path) -> Session:
    """Hand-build a session with a couple of write tool results in it,
    matching the metadata shape produced by the real `write` tool."""
    session = Session(workspace=str(workspace), provider="mock", model="m")
    session.add_user("create foo")
    session.add_assistant("ok")
    session.messages.append(
        Message(
            role=Role.TOOL,
            tool_results=[
                ToolResult(
                    call_id="c1", tool="write", ok=True,
                    content="Created foo.py",
                    metadata={
                        "path": str(workspace / "foo.py"),
                        "created": True,
                        "previous_content": "",
                        "new_content": "print('a')\n",
                        "diff": "--- a/foo.py\n+++ b/foo.py\n@@ -0,0 +1 @@\n+print('a')\n",
                    },
                ),
            ],
        )
    )
    session.add_user("update foo")
    session.add_assistant("ok")
    session.messages.append(
        Message(
            role=Role.TOOL,
            tool_results=[
                ToolResult(
                    call_id="c2", tool="edit", ok=True,
                    content="Replaced 1 occurrence(s)",
                    metadata={
                        "path": str(workspace / "foo.py"),
                        "replacements": 1,
                        "previous_content": "print('a')\n",
                        "new_content": "print('b')\n",
                        "diff": "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-print('a')\n+print('b')\n",
                    },
                ),
            ],
        )
    )
    return session


def test_diff_command_shows_collapsed_change(tmp_path: Path) -> None:
    """When the same file is written twice, /diff shows ONE diff comparing
    the original pre-image against the latest post-image."""
    (tmp_path / "foo.py").write_text("print('b')\n")
    session = _session_with_writes(tmp_path)

    console = Console(record=True, width=120)
    _, handler = COMMANDS["diff"]
    handler(console=console, session=session)
    text = console.export_text()

    assert "foo.py" in text
    assert "+print('b')" in text
    # The intermediate state ("print('a')") must NOT appear — it's been collapsed
    assert "+print('a')" not in text


def test_diff_command_empty_session(tmp_path: Path) -> None:
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    console = Console(record=True, width=120)
    _, handler = COMMANDS["diff"]
    handler(console=console, session=session)
    text = console.export_text()
    assert "No file changes" in text


def test_undo_reverts_last_edit_and_marks_undone(tmp_path: Path) -> None:
    target = tmp_path / "foo.py"
    target.write_text("print('b')\n")
    session = _session_with_writes(tmp_path)

    console = Console(record=True, width=120)
    _, handler = COMMANDS["undo"]
    handler(console=console, session=session)
    text = console.export_text()
    assert "Undone" in text or "restored" in text

    # File restored to the previous content
    assert target.read_text() == "print('a')\n"

    # The latest tool result is flagged so a second /undo skips it
    last = session.messages[-1].tool_results[-1]
    assert last.metadata.get("undone") is True


def test_undo_deletes_file_if_originally_created(tmp_path: Path) -> None:
    target = tmp_path / "foo.py"
    target.write_text("print('a')\n")

    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    session.add_user("create foo")
    session.add_assistant("ok")
    session.messages.append(
        Message(
            role=Role.TOOL,
            tool_results=[
                ToolResult(
                    call_id="c1", tool="write", ok=True,
                    content="Created",
                    metadata={
                        "path": str(target),
                        "created": True,
                        "previous_content": "",
                        "new_content": "print('a')\n",
                        "diff": "",
                    },
                ),
            ],
        )
    )

    console = Console(record=True, width=120)
    _, handler = COMMANDS["undo"]
    handler(console=console, session=session)
    assert not target.exists()


def test_undo_with_no_writes_says_nothing_to_do(tmp_path: Path) -> None:
    session = Session(workspace=str(tmp_path), provider="mock", model="m")
    console = Console(record=True, width=120)
    _, handler = COMMANDS["undo"]
    handler(console=console, session=session)
    text = console.export_text()
    assert "No undoable" in text


def test_sessions_grep_filters_by_message_content(tmp_path: Path, monkeypatch) -> None:
    """`coding-agent sessions --grep` walks saved sessions and only returns
    ones whose user/assistant messages match. Persist two sessions, search."""
    from coding_agent.core import session as session_mod

    monkeypatch.setattr(session_mod, "_sessions_dir", lambda: tmp_path)

    s1 = Session(workspace=str(tmp_path), provider="mock", model="m")
    s1.add_user("please refactor the parser")
    s1.add_assistant("done")
    s1.save()

    s2 = Session(workspace=str(tmp_path), provider="mock", model="m")
    s2.add_user("just say hello")
    s2.add_assistant("hello")
    s2.save()

    # Listing matches by grep substring (case-insensitive)
    from typer.testing import CliRunner

    from coding_agent.cli.app import app

    runner = CliRunner()
    result = runner.invoke(app, ["sessions", "--grep", "parser"])
    assert result.exit_code == 0
    assert s1.id in result.stdout
    assert s2.id not in result.stdout
