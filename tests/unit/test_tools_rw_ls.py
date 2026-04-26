"""Tests for read / write / ls tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.core.errors import PermissionDenied
from coding_agent.tools.base import ToolContext
from coding_agent.tools.ls import LsParams, LsTool
from coding_agent.tools.read import ReadParams, ReadTool
from coding_agent.tools.write import WriteParams, WriteTool


def _ctx(ws: Path) -> ToolContext:
    return ToolContext(workspace=ws)


# ── Read ─────────────────────────────────────────────────────────────────


async def test_read_full_file(tmp_path: Path) -> None:
    f = tmp_path / "hello.py"
    f.write_text("line1\nline2\nline3\n")
    tool = ReadTool()
    result = await tool.run(ReadParams(file_path="hello.py"), _ctx(tmp_path))
    assert result.ok
    assert "line1" in result.content
    assert "3 lines total" in result.content


async def test_read_with_offset_and_limit(tmp_path: Path) -> None:
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"L{i}" for i in range(1, 101)))
    tool = ReadTool()
    result = await tool.run(
        ReadParams(file_path="big.txt", offset=10, limit=5), _ctx(tmp_path)
    )
    assert result.ok
    assert "L10" in result.content
    assert "L14" in result.content
    assert "showing lines 10-14" in result.content


async def test_read_binary_file(tmp_path: Path) -> None:
    f = tmp_path / "img.bin"
    f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    tool = ReadTool()
    result = await tool.run(ReadParams(file_path="img.bin"), _ctx(tmp_path))
    assert result.ok
    assert "binary" in result.content


async def test_read_outside_workspace(tmp_path: Path) -> None:
    tool = ReadTool()
    with pytest.raises(PermissionDenied):
        await tool.run(ReadParams(file_path="/etc/passwd"), _ctx(tmp_path))


async def test_read_nonexistent(tmp_path: Path) -> None:
    tool = ReadTool()
    with pytest.raises(PermissionDenied, match="does not exist"):
        await tool.run(ReadParams(file_path="nope.txt"), _ctx(tmp_path))


# ── Write ────────────────────────────────────────────────────────────────


async def test_write_creates_file(tmp_path: Path) -> None:
    tool = WriteTool()
    result = await tool.run(
        WriteParams(file_path="new.txt", content="hello"), _ctx(tmp_path)
    )
    assert result.ok
    assert (tmp_path / "new.txt").read_text() == "hello"
    assert "Created" in result.content


async def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    tool = WriteTool()
    result = await tool.run(
        WriteParams(file_path="a/b/c.txt", content="deep"), _ctx(tmp_path)
    )
    assert result.ok
    assert (tmp_path / "a" / "b" / "c.txt").read_text() == "deep"


async def test_write_overwrites_with_diff(tmp_path: Path) -> None:
    f = tmp_path / "existing.txt"
    f.write_text("old content")
    tool = WriteTool()
    result = await tool.run(
        WriteParams(file_path="existing.txt", content="new content"), _ctx(tmp_path)
    )
    assert result.ok
    assert f.read_text() == "new content"
    assert "---" in result.content  # unified diff marker


async def test_write_outside_workspace(tmp_path: Path) -> None:
    tool = WriteTool()
    with pytest.raises(PermissionDenied):
        await tool.run(
            WriteParams(file_path="/tmp/evil.txt", content="x"), _ctx(tmp_path)
        )


async def test_write_diff_preview(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("aaa\n")
    tool = WriteTool()
    diff = tool.generate_diff(
        WriteParams(file_path="f.txt", content="bbb\n"), _ctx(tmp_path)
    )
    assert diff is not None
    assert "-aaa" in diff
    assert "+bbb" in diff


# ── Ls ───────────────────────────────────────────────────────────────────


async def test_ls_basic(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("")
    tool = LsTool()
    result = await tool.run(LsParams(path="."), _ctx(tmp_path))
    assert result.ok
    assert "a.py" in result.content
    assert "b.py" in result.content


async def test_ls_hides_dotfiles_by_default(tmp_path: Path) -> None:
    (tmp_path / ".hidden").write_text("")
    (tmp_path / "visible.txt").write_text("")
    tool = LsTool()
    result = await tool.run(LsParams(path="."), _ctx(tmp_path))
    assert "visible.txt" in result.content
    assert ".hidden" not in result.content


async def test_ls_shows_dotfiles_when_asked(tmp_path: Path) -> None:
    (tmp_path / ".hidden").write_text("")
    tool = LsTool()
    result = await tool.run(LsParams(path=".", show_hidden=True), _ctx(tmp_path))
    assert ".hidden" in result.content


async def test_ls_not_a_directory(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x")
    tool = LsTool()
    result = await tool.run(LsParams(path="file.txt"), _ctx(tmp_path))
    assert not result.ok
    assert "Not a directory" in result.content


async def test_ls_outside_workspace(tmp_path: Path) -> None:
    tool = LsTool()
    with pytest.raises(PermissionDenied):
        await tool.run(LsParams(path="/etc"), _ctx(tmp_path))
