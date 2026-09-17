from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

import structlog

# Privacy hardening M4: diff_text added explicitly — it carries file content
# that may include secrets and does not match any of the existing terms
# (password/token/secret/key/credential). "payload" is deliberately NOT
# added here: no agent log call passes the full payload dict as a kwarg
# today (grep-verified), and doing so would make this regex swallow
# unrelated non-sensitive keys.
# US-09: hex_dump (matches hex_dump_before/hex_dump_after) added for the same
# reason as diff_text — it is a bounded sample of file content, not a secret
# by name, but still content that must never reach structured logs (W6).
_SENSITIVE_RE = re.compile(
    r"(password|token|secret|key|credential|diff_text|hex_dump)", re.IGNORECASE
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

    # D73/RN-167: `wrapper_class=structlog.stdlib.BoundLogger` combined with
    # `logger_factory=structlog.PrintLoggerFactory` never filtered by level —
    # the level only reached `logging.basicConfig` below, which does not
    # intercept structlog's own output path. Every level got printed
    # regardless of `--log-level`/`LOG_LEVEL`, which is why D69/RN-163
    # (lowering `detector.out_of_scope_drop` to `debug`) did not stop the
    # journal flood (82 "debug" lines measured in the 15s after the
    # 2026-09-17 deploy). `make_filtering_bound_logger` is the same mechanism
    # the backend already uses (`backend/app/core/logging.py`). An unknown or
    # malformed level name MUST NOT crash startup, so it falls back to INFO.
    log_level_int = getattr(logging, level, logging.INFO)
    if not isinstance(log_level_int, int):
        log_level_int = logging.INFO

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            sanitize_logs,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level_int,
    )
