"""Path guard — validates that file operations stay within the workspace.

Defends against:
  * Path traversal (``../../../etc/passwd``)
  * Symlink escape (a symlink under workspace pointing outside)
  * Absolute paths outside workspace
  * Null bytes and other injection tricks
"""

from __future__ import annotations

from pathlib import Path

from coding_agent.core.errors import PermissionDenied


def resolve_and_validate(
    raw_path: str,
    workspace: Path,
    *,
    must_exist: bool = False,
    allow_outside: bool = False,
) -> Path:
    """Resolve *raw_path* to an absolute ``Path`` inside *workspace*.

    Raises ``PermissionDenied`` if the resolved path escapes the workspace.
    """
    if "\x00" in raw_path:
        raise PermissionDenied("Path contains null bytes", tool="path_guard")

    if not raw_path:
        raise PermissionDenied("Empty path", tool="path_guard")

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate

    try:
        resolved = candidate.resolve(strict=False)
    except OSError as e:
        raise PermissionDenied(f"Cannot resolve path: {e}", tool="path_guard") from e

    if not allow_outside:
        ws_resolved = workspace.resolve()
        try:
            resolved.relative_to(ws_resolved)
        except ValueError as e:
            raise PermissionDenied(
                f"Path '{raw_path}' resolves to '{resolved}' which is outside "
                f"the workspace '{ws_resolved}'",
                tool="path_guard",
            ) from e

    if must_exist and not resolved.exists():
        raise PermissionDenied(
            f"Path does not exist: {resolved}", tool="path_guard"
        )

    return resolved


def is_binary(path: Path, sample_size: int = 8192) -> bool:
    """Heuristic: file is binary if a sample contains null bytes."""
    try:
        with path.open("rb") as f:
            chunk = f.read(sample_size)
    except OSError:
        return False
    return b"\x00" in chunk
