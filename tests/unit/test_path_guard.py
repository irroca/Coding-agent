"""Tests for path_guard — traversal prevention, symlink escape, etc."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.core.errors import PermissionDenied
from coding_agent.security.path_guard import is_binary, resolve_and_validate


def test_relative_path_resolves_under_workspace(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text("print('hi')")
    result = resolve_and_validate("hello.py", tmp_path, must_exist=True)
    assert result == tmp_path / "hello.py"


def test_absolute_path_inside_workspace(tmp_path: Path) -> None:
    f = tmp_path / "sub" / "a.txt"
    f.parent.mkdir()
    f.write_text("x")
    result = resolve_and_validate(str(f), tmp_path, must_exist=True)
    assert result == f


def test_traversal_blocked(tmp_path: Path) -> None:
    with pytest.raises(PermissionDenied, match="outside"):
        resolve_and_validate("../../etc/passwd", tmp_path)


def test_absolute_outside_blocked(tmp_path: Path) -> None:
    with pytest.raises(PermissionDenied, match="outside"):
        resolve_and_validate("/etc/passwd", tmp_path)


def test_null_byte_blocked(tmp_path: Path) -> None:
    with pytest.raises(PermissionDenied, match="null bytes"):
        resolve_and_validate("file\x00.txt", tmp_path)


def test_empty_path_blocked(tmp_path: Path) -> None:
    with pytest.raises(PermissionDenied, match="Empty"):
        resolve_and_validate("", tmp_path)


def test_symlink_escape_blocked(tmp_path: Path) -> None:
    link = tmp_path / "escape"
    link.symlink_to("/etc")
    with pytest.raises(PermissionDenied, match="outside"):
        resolve_and_validate("escape/passwd", tmp_path, must_exist=False)


def test_must_exist_nonexistent(tmp_path: Path) -> None:
    with pytest.raises(PermissionDenied, match="does not exist"):
        resolve_and_validate("nope.txt", tmp_path, must_exist=True)


def test_allow_outside_flag(tmp_path: Path) -> None:
    result = resolve_and_validate("/etc/hostname", tmp_path, allow_outside=True)
    assert result == Path("/etc/hostname")


def test_is_binary_text(tmp_path: Path) -> None:
    f = tmp_path / "text.txt"
    f.write_text("hello world")
    assert is_binary(f) is False


def test_is_binary_binary(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00\x01\x02\xff")
    assert is_binary(f) is True
