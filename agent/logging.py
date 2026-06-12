from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

import structlog

_SENSITIVE_RE = re.compile(
    r"(password|token|secret|key|credential)", re.IGNORECASE
)


def sanitize_logs(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    for k in list(event_dict.keys()):
        if _SENSITIVE_RE.search(k):
            event_dict[k] = "[REDACTED]"
    return event_dict


def configure_logging(level: str = "info", fmt: str = "json") -> None:
    level = os.environ.get("LOG_LEVEL", level).upper()
    fmt = os.environ.get("LOG_FORMAT", fmt)

    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if fmt == "console"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            sanitize_logs,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level, logging.INFO),
    )
