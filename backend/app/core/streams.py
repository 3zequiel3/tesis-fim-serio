"""
Contrato compartido de mensajes Valkey Streams (D7, RN-79, RN-91).

sign_payload / verify_payload y canonical_json son reutilizados por todos
los changes posteriores que emitan comandos (Changes 10, 11).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

SCHEMA_VERSION: int = 1

STREAM_EVENTS = "events"
STREAM_HEARTBEAT = "agent_heartbeat"
STREAM_COMMANDS = "commands"
STREAM_EVENT_ACK = "event_ack"  # command_ack — confirmación de ejecución del agente (D30/RN-124, C36)
CONSUMER_GROUP = "fim-backend"
CONSUMER_NAME = "backend-01"


def canonical_json(payload: dict[str, Any]) -> str:
    """JSON determinístico sin el campo 'signature', sort_keys, separadores compactos."""
    p = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(p, sort_keys=True, separators=(",", ":"))


def sign_payload(secret: bytes, payload: dict[str, Any]) -> str:
    """Retorna hexdigest HMAC-SHA256 del canonical_json del payload."""
    msg = canonical_json(payload).encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify_payload(secret: bytes, payload: dict[str, Any]) -> bool:
    """True si la firma en payload['signature'] es válida."""
    sig = str(payload.get("signature", ""))
    expected = sign_payload(secret, payload)
    return hmac.compare_digest(expected, sig)


def check_schema_version(payload: dict[str, Any]) -> str:
    """
    Clasifica `schema_version` del payload en tres resultados (D37/RN-131,
    enmienda de RN-91 — antes devolvía un booleano):

      "ok"          — parseable y <= SCHEMA_VERSION soportado.
      "unsupported" — parseable pero MAYOR al soportado: el agente va
                       adelantado respecto del backend. El payload es válido,
                       el receptor todavía no sabe leerlo — condición
                       transitoria, nack RETENIBLE (el evento se conserva).
      "invalid"     — no parseable (clave ausente, tipo inválido, valor no
                       entero) — payload ilegible, defecto PERMANENTE, nack
                       terminal.

    Se distinguen porque tienen desenlaces opuestos para el agente: uno
    reintenta con backpressure, el otro descarta y deja de reintentar.
    """
    try:
        v = int(payload["schema_version"])
    except (KeyError, ValueError, TypeError):
        return "invalid"
    return "ok" if v <= SCHEMA_VERSION else "unsupported"
