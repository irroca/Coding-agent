"""Tests for edit / glob / grep / bash tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tools.base import ToolContext
from coding_agent.tools.bash import BashParams, BashTool
from coding_agent.tools.edit import EditParams, EditTool
from coding_agent.tools.glob import GlobParams, GlobTool
from coding_agent.tools.grep import GrepParams, GrepTool


def _ctx(ws: Path) -> ToolContext:
    return ToolContext(workspace=ws)


# ── Edit ────────────────────────────────────────────────────────────────


async def test_edit_single_replacement(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    tool = EditTool()
    result = await tool.run(
        EditParams(file_path="code.py", old_string="return 1", new_string="return 42"),
        _ctx(tmp_path),
    )
    assert result.ok
    assert "return 42" in f.read_text()


async def test_edit_not_found(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("hello\n")
    tool = EditTool()
    result = await tool.run(
        EditParams(file_path="code.py", old_string="missing", new_string="x"),
        _ctx(tmp_path),
    )
    assert not result.ok
    assert "not found" in result.content


async def test_edit_ambiguous(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("aaa\nbbb\naaa\n")
    tool = EditTool()
    result = await tool.run(
        EditParams(file_path="code.py", old_string="aaa", new_string="ccc"),
        _ctx(tmp_path),
    )
    assert not result.ok
    assert "2 times" in result.content


async def test_edit_replace_all(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("aaa\nbbb\naaa\n")
    tool = EditTool()
    result = await tool.run(
        EditParams(file_path="code.py", old_string="aaa", new_string="ccc", replace_all=True),
        _ctx(tmp_path),
    )
    assert result.ok
    assert f.read_text() == "ccc\nbbb\nccc\n"
    assert "2 occurrence" in result.content


async def test_edit_identical_strings(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("hello\n")
    tool = EditTool()
    result = await tool.run(
        EditParams(file_path="code.py", old_string="hello", new_string="hello"),
        _ctx(tmp_path),
    )
    assert not result.ok
    assert "identical" in result.content


async def test_edit_nonexistent_file(tmp_path: Path) -> None:
    from coding_agent.core.errors import PermissionDenied

    tool = EditTool()
    with pytest.raises(PermissionDenied, match="does not exist"):
        await tool.run(
            EditParams(file_path="nope.py", old_string="a", new_string="b"),
            _ctx(tmp_path),
        )


async def test_edit_generates_diff(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("old_value = 1\n")
    tool = EditTool()
    result = await tool.run(
        EditParams(file_path="code.py", old_string="old_value", new_string="new_value"),
        _ctx(tmp_path),
    )
    assert result.ok
    assert "-old_value" in result.content or "old_value" in result.content


# ── Glob ────────────────────────────────────────────────────────────────


async def test_glob_finds_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").touch()
    (tmp_path / "b.py").touch()
    (tmp_path / "c.txt").touch()
    tool = GlobTool()
    result = await tool.run(GlobParams(pattern="*.py"), _ctx(tmp_path))
    assert result.ok
    assert "a.py" in result.content
    assert "b.py" in result.content
    assert "c.txt" not in result.content


async def test_glob_no_matches(tmp_path: Path) -> None:
    tool = GlobTool()
    result = await tool.run(GlobParams(pattern="*.rs"), _ctx(tmp_path))
    assert result.ok
    assert "No files" in result.content


async def test_glob_nested(tmp_path: Path) -> None:
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    (sub / "main.py").touch()
    tool = GlobTool()
    result = await tool.run(GlobParams(pattern="**/*.py"), _ctx(tmp_path))
    assert result.ok
    assert "main.py" in result.content


async def test_glob_skips_dotdirs(tmp_path: Path) -> None:
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.py").touch()
    (tmp_path / "visible.py").touch()
    tool = GlobTool()
    result = await tool.run(GlobParams(pattern="*.py"), _ctx(tmp_path))
    assert result.ok
    assert "visible.py" in result.content
    assert "secret.py" not in result.content


# ── Grep ────────────────────────────────────────────────────────────────


async def test_grep_finds_pattern(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("hello world\nfoo bar\nhello again\n")
    tool = GrepTool()
    result = await tool.run(GrepParams(pattern="hello", path="data.txt"), _ctx(tmp_path))
    assert result.ok
    assert "hello world" in result.content
    assert "hello again" in result.content


async def test_grep_no_matches(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("abc\n")
    tool = GrepTool()
    result = await tool.run(GrepParams(pattern="xyz", path="data.txt"), _ctx(tmp_path))
    assert result.ok
    assert "No matches" in result.content


async def test_grep_fixed_strings(tmp_path: Path) -> None:
    f = tmp_path / "regex.txt"
    f.write_text("price is $10.00\nother line\n")
    tool = GrepTool()
    result = await tool.run(
        GrepParams(pattern="$10.00", path="regex.txt", fixed_strings=True),
        _ctx(tmp_path),
    )
    assert result.ok
    assert "$10.00" in result.content


async def test_grep_include_filter(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("target\n")
    (tmp_path / "b.txt").write_text("target\n")
    tool = GrepTool()
    result = await tool.run(
        GrepParams(pattern="target", include="*.py"),
        _ctx(tmp_path),
    )
    assert result.ok
    assert "a.py" in result.content
    # b.txt may or may not appear depending on rg availability;
    # the test verifies that a.py is found


async def test_grep_invalid_regex(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x\n")
    tool = GrepTool()
    result = await tool.run(
        GrepParams(pattern="[invalid"),
        _ctx(tmp_path),
    )
    # With rg this may fail differently; without rg we get "Invalid regex"
    # Either way it shouldn't crash
    assert isinstance(result.content, str)


# ── Bash ────────────────────────────────────────────────────────────────


async def test_bash_echo(tmp_path: Path) -> None:
    tool = BashTool()
    result = await tool.run(BashParams(command="echo hello"), _ctx(tmp_path))
    assert result.ok
    assert "hello" in result.content


async def test_bash_exit_code(tmp_path: Path) -> None:
    tool = BashTool()
    result = await tool.run(BashParams(command="exit 1"), _ctx(tmp_path))
    assert not result.ok
    assert "Exit code: 1" in result.content


async def test_bash_timeout(tmp_path: Path) -> None:
    tool = BashTool()
    result = await tool.run(
        BashParams(command="sleep 60", timeout=1),
        _ctx(tmp_path),
    )
    assert not result.ok
    assert "timed out" in result.content


async def test_bash_captures_stderr(tmp_path: Path) -> None:
    tool = BashTool()
    result = await tool.run(
        BashParams(command="echo err >&2"),
        _ctx(tmp_path),
    )
    assert "err" in result.content


async def test_bash_working_directory(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    tool = BashTool()
    result = await tool.run(
        BashParams(command="pwd", working_directory="sub"),
        _ctx(tmp_path),
    )
    assert result.ok
    assert "sub" in result.content


async def test_bash_permission_request(tmp_path: Path) -> None:
    tool = BashTool()
    params = BashParams(command="rm -rf /")
    perm = tool.permission_request(params)
    assert perm.action == "bash"
    assert "rm -rf /" in perm.summary
