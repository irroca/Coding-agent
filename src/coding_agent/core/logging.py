"""Structured logging setup using structlog.

The agent emits JSON logs by default to a rotating file under
``~/.coding_agent/logs/agent.log`` and human-readable logs to stderr at the
configured level. Tools, providers, and the loop should use ``get_logger()``
rather than the standard ``logging`` module so context (session_id, tool, etc.)
propagates automatically.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog
from platformdirs import user_data_dir

_INITIALIZED = False


def _log_dir() -> Path:
    p = Path(user_data_dir("coding_agent")) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def configure_logging(level: str = "INFO") -> None:
    """Idempotent logging setup. Safe to call multiple times."""
    global _INITIALIZED
    if _INITIALIZED:
        logging.getLogger().setLevel(level)
        return

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        foreign_pre_chain=shared_processors,
    )
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(console_formatter)
    stderr.setLevel(level)
    root.addHandler(stderr)

    file_handler = logging.handlers.RotatingFileHandler(
        _log_dir() / "agent.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    _INITIALIZED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _INITIALIZED:
        configure_logging()
    return structlog.get_logger(name)
