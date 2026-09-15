"""
Ticket SSE de un solo uso para GET /alerts/stream (D64/RN-158).

Un JWT de acceso no debe viajar en la URL de una conexión SSE: queda en el
historial del navegador y en los logs de acceso durante toda su vigencia.
`POST /alerts/stream-ticket` emite en su lugar un ticket opaco
(`secrets.token_urlsafe(32)`, 256 bits de entropía) con TTL de 30 segundos,
guardado en Valkey y ligado al `user_id` del admin autenticado.
`GET /alerts/stream?ticket=` lo consume de forma atómica con `GETDEL`, de modo
que un mismo ticket habilita como máximo una conexión — dos consumos
concurrentes del mismo ticket resuelven a exactamente un `user_id`.

La clave en Valkey se deriva del SHA-256 del ticket
(`fim:sse_ticket:<sha256_hex>`) para que el valor en claro del ticket no quede
expuesto en el keyspace ante un `KEYS`/`SCAN`/`MONITOR`.

Vive como módulo propio (sin FastAPI) para poder testearlo sin HTTP.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

SSE_TICKET_PREFIX = "fim:sse_ticket:"
SSE_TICKET_TTL_SECONDS = 30


def _ticket_key(ticket: str) -> str:
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    return f"{SSE_TICKET_PREFIX}{digest}"


async def issue_ticket(user_id: int, valkey: Any) -> str:
    """Genera un ticket opaco de un solo uso y lo guarda en Valkey (D64/RN-158).

    La clave expira sola a los SSE_TICKET_TTL_SECONDS segundos (EX); NX evita
    pisar una clave existente en la práctica imposible colisión de SHA-256.
    """
    ticket = secrets.token_urlsafe(32)
    await valkey.set(_ticket_key(ticket), user_id, ex=SSE_TICKET_TTL_SECONDS, nx=True)
    return ticket


async def consume_ticket(ticket: str, valkey: Any) -> int | None:
    """Consume el ticket de forma atómica (GETDEL).

    Retorna el user_id asociado, o None si el ticket es inexistente, ya fue
    consumido o venció — los tres casos son indistinguibles para el caller
    (todos se traducen en 401 en la dependencia del stream).
    """
    raw = await valkey.getdel(_ticket_key(ticket))
    if raw is None:
        return None
    return int(raw)
