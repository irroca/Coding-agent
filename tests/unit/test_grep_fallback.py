"""Tests for grep tool's built-in fallback search (no rg)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from coding_agent.tools.base import ToolContext
from coding_agent.tools.grep import GrepParams, GrepTool


def _ctx(ws: Path) -> ToolContext:
    return ToolContext(workspace=ws)


def _no_rg():
    """Patch shutil.which to pretend rg is not installed."""
    return patch("coding_agent.tools.grep.shutil.which", return_value=None)


async def test_fallback_finds_pattern(tmp_path: Path) -> None:
    (tmp_path / "code.py").write_text("def hello():\n    pass\ndef world():\n    pass\n")
    tool = GrepTool()
    params = GrepParams(pattern="hello", path=".")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "hello" in result.content
    assert "code.py" in result.content


async def test_fallback_no_matches(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("nothing here\n")
    tool = GrepTool()
    params = GrepParams(pattern="zzzzz", path=".")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "No matches" in result.content


async def test_fallback_fixed_strings(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("a.b.c\nfoo\n")
    tool = GrepTool()
    params = GrepParams(pattern="a.b.c", path=".", fixed_strings=True)
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "a.b.c" in result.content


async def test_fallback_invalid_regex(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("data\n")
    tool = GrepTool()
    params = GrepParams(pattern="[invalid", path=".")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert not result.ok
    assert "Invalid regex" in result.content


async def test_fallback_include_filter(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("target\n")
    (tmp_path / "b.txt").write_text("target\n")
    tool = GrepTool()
    params = GrepParams(pattern="target", path=".", include="*.py")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "a.py" in result.content
    assert "b.txt" not in result.content


async def test_fallback_skips_hidden_dirs(tmp_path: Path) -> None:
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.txt").write_text("target\n")
    (tmp_path / "visible.txt").write_text("target\n")
    tool = GrepTool()
    params = GrepParams(pattern="target", path=".")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "visible.txt" in result.content
    assert "secret.txt" not in result.content


async def test_fallback_single_file_search(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("line1\nfind_me\nline3\n")
    tool = GrepTool()
    params = GrepParams(pattern="find_me", path="one.txt")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "find_me" in result.content
    assert result.metadata.get("match_count") == 1


async def test_fallback_truncates_at_max(tmp_path: Path) -> None:
    content = "\n".join(f"match_{i}" for i in range(300))
    (tmp_path / "big.txt").write_text(content)
    tool = GrepTool()
    params = GrepParams(pattern="match_", path=".")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "truncated" in result.content


async def test_fallback_handles_binary_file(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02target\xff\xfe")
    (tmp_path / "ok.txt").write_text("target\n")
    tool = GrepTool()
    params = GrepParams(pattern="target", path=".")
    with _no_rg():
        result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "ok.txt" in result.content
