#!/usr/bin/env python3
"""Secret-scan staged files for accidental API keys.

Wired in as a pre-commit hook (see .pre-commit-config.yaml). Exits non-zero if
any tracked file contains a recognised API key pattern, so the commit aborts.

Skips binary files, the ``.env.example`` template, and anything under
``docs/eval-reports/`` (those are deliberate redacted artefacts).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running before the package is installed (e.g. CI bootstrap).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from coding_agent.security.secrets import find_secrets

SKIP_NAMES = {".env.example", "uv.lock", "README.md", "CHANGELOG.md"}
SKIP_DIRS = {
    "docs/eval-reports",
    "docs/decisions",
    "tests/unit/test_secrets.py",
    "tests/unit/test_audit_chain.py",
}


def _should_skip(path: Path) -> bool:
    name = path.name
    if name in SKIP_NAMES:
        return True
    s = str(path).replace("\\", "/")
    return any(d in s for d in SKIP_DIRS)


def _is_text(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            chunk = f.read(2048)
        return b"\x00" not in chunk
    except OSError:
        return False


def main(argv: list[str]) -> int:
    found_any = False
    for arg in argv:
        p = Path(arg)
        if not p.is_file() or _should_skip(p) or not _is_text(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        secrets = find_secrets(text)
        if not secrets:
            continue
        found_any = True
        for kind, value in secrets:
            shown = value[:8] + "…" if len(value) > 12 else value
            print(f"{p}: detected {kind} secret: {shown}", file=sys.stderr)

    if found_any:
        print(
            "\nCommit aborted. If this is a false positive, exempt the file "
            "in scripts/secret_scan.py or scrub the secret first.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
