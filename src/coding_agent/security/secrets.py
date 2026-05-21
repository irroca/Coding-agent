"""Secret scanning + redaction.

Two responsibilities:

1. **Detection** — heuristics that match common API-key shapes (OpenAI
   ``sk-``, Anthropic ``sk-ant-``, GitHub ``ghp_``, generic 32+ char hex,
   AWS access keys, etc.). Used by the audit log and session saver to avoid
   persisting credentials.

2. **Redaction** — produce a safe string for storage / display. The function
   keeps the first 4 and last 2 characters so an operator can still recognise
   *which* key leaked without exposing it.

These patterns are intentionally narrow. False positives in a coding agent
context are catastrophic — a redacted code block stops being useful — so we
prefer to miss novel formats over destroying source code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

# Each pattern is anchored on something distinctive (prefix or character set).
_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    ("openai", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic", re.compile(r"\bsk-ant-(?:api\d{2}-)?[A-Za-z0-9_\-]{20,}\b")),
    ("github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    # Generic 40+ char hex blob (covers many tokens). Bounded to avoid hashing
    # ordinary commit SHAs (which are 40 chars exactly — we require 41+).
    ("generic_hex", re.compile(r"\b[a-fA-F0-9]{41,}\b")),
]


def find_secrets(text: str) -> list[tuple[str, str]]:
    """Return a list of (kind, value) matches for inspection."""
    out: list[tuple[str, str]] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            out.append((kind, m.group(0)))
    return out


def redact(text: str) -> str:
    """Replace every detected secret with ``<kind:abcd…xy>``.

    Keeps a 4+2 character window so leak detection is still possible without
    exposing the full credential.
    """
    if not text:
        return text
    out = text
    # Iterate patterns once; build a single replacement pass.
    for kind, pat in _PATTERNS:
        def _sub(m: re.Match[str], k: str = kind) -> str:
            v = m.group(0)
            if len(v) <= 10:
                return f"<{k}:redacted>"
            return f"<{k}:{v[:4]}…{v[-2:]}>"
        out = pat.sub(_sub, out)
    return out


def redact_iter(items: Iterable[str]) -> list[str]:
    return [redact(s) for s in items]
