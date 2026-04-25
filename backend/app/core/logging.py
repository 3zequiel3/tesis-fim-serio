"""
Pipeline de logging estructurado para FIM Platform.

Una sola llamada a `configure_logging()` al arrancar la app configura structlog
para emitir JSON por stdout, con sanitización de secrets y trace_id por request.
No llamar más de una vez (idempotente en la práctica, pero innecesario).

Decisión D-CHANGE-01: la sanitización vive como structlog processor, NO como
ASGI middleware. Razón: cubre también logs emitidos fuera del ciclo HTTP
(lifespan, consumers Valkey en Change 08+, tareas de background).
"""

from __future__ import annotations

import logging
import logging.config
from typing import Any

import structlog
from structlog.stdlib import add_log_level
from structlog.contextvars import merge_contextvars
from structlog.processors import TimeStamper
from structlog.processors import JSONRenderer

from app.core.config import settings

# ─────────────────────────────────────────────────────────────────────────────
# Lista canónica de keys a redactar (D-CHANGE-01)
# ─────────────────────────────────────────────────────────────────────────────
# Mínimo obligatorio RN-89 / arquitectura_stack.md §1813:
_CANONICAL_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "access_token",
        "refresh_token",
        "bootstrap_secret",
        "master_secret",
        "shared_secret",
        "signature",
    }
)

# Extensión defensiva (D-CHANGE-01 §extensión):
_EXTENDED_KEYS: frozenset[str] = frozenset(
    {
        "current_password",
        "new_password",
        "token",
        "secret",
        "bootstrap_secret_hash",
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "csrf_token",
        "jwt",
        "private_key",
    }
)

SENSITIVE_KEYS: frozenset[str] = _CANONICAL_KEYS | _EXTENDED_KEYS
_REDACTED = "[REDACTED]"
_MAX_DEPTH = 5
_warned_depth = False  # emitir warning solo una vez por proceso


def _redact_value(value: Any, depth: int) -> Any:
    """Recorre recursivamente dicts y listas redactando valores sensibles."""
    global _warned_depth
    if depth > _MAX_DEPTH:
        if not _warned_depth:
            # No podemos usar log aquí (ciclo), escribimos directo a stderr.
            import sys

            print(
                "[structlog sanitizer] max recursion depth reached; "
                "remaining nested data NOT sanitized",
                file=sys.stderr,
            )
            _warned_depth = True
        return value

    if isinstance(value, dict):
        return {
            k: _REDACTED if k.lower() in SENSITIVE_KEYS else _redact_value(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, depth + 1) for item in value]
    return value


def sanitize_secrets(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Structlog processor que redacta valores de keys sensibles.

    - Match case-insensitive sobre keys de primer nivel del event_dict.
    - Recursión sobre dicts y listas anidados (profundidad máxima 5).
    - Preserva la key; reemplaza el valor por "[REDACTED]".
    """
    return {
        k: _REDACTED if k.lower() in SENSITIVE_KEYS else _redact_value(v, 1)
        for k, v in event_dict.items()
    }


def configure_logging() -> None:
    """
    Configura structlog + logging stdlib para emitir JSON por stdout.

    Debe llamarse UNA SOLA VEZ al arrancar, antes de instanciar FastAPI
    (para que los logs del lifespan ya salgan formateados — D-CHANGE-07).

    Pipeline de processors en orden:
      1. merge_contextvars  — inyecta trace_id y demás vars del context
      2. add_log_level      — agrega key "level"
      3. TimeStamper        — agrega "timestamp" ISO 8601 UTC
      4. sanitize_secrets   — redacta secrets (D-CHANGE-01)
      5. JSONRenderer       — serializa a JSON

    El wrapper_class filtra por nivel de log configurado en settings.log_level.
    """
    log_level_int = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Configurar el logging stdlib para que uvicorn/sqlalchemy/httpx
    # emitan sus logs a través de structlog.
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structlog": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        JSONRenderer(),
                    ],
                    "foreign_pre_chain": [
                        structlog.stdlib.add_log_level,
                        structlog.stdlib.add_logger_name,
                        TimeStamper(fmt="iso", utc=True),
                        sanitize_secrets,
                    ],
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "structlog",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {
                "handlers": ["default"],
                "level": settings.log_level.upper(),
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "propagate": False},
                "uvicorn.access": {"handlers": ["default"], "propagate": False},
                "sqlalchemy.engine": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
        }
    )

    structlog.configure(
        processors=[
            merge_contextvars,
            add_log_level,
            TimeStamper(fmt="iso", utc=True),
            sanitize_secrets,
            JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# Singleton de conveniencia; los módulos pueden hacer structlog.get_logger(__name__)
log = structlog.get_logger()
