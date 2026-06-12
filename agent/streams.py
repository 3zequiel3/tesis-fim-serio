"""
Espejo del contrato de firma de mensajes Valkey Streams en el agente (D7, RN-79).

canonical_json y sign_payload son idénticos al helper del backend para garantizar
que las firmas HMAC producidas aquí sean verificables por el backend.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION: int = 1


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


def load_shared_secret(secrets_dir: str | Path) -> bytes:
    """Lee los 32 bytes raw del shared_secret desde secrets_dir/shared_secret."""
    return (Path(secrets_dir) / "shared_secret").read_bytes()
