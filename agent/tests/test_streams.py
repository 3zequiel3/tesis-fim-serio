"""Tests del contrato de firma HMAC de streams (Change 08, task 9.3).

Verifica agent/streams.py y, por simetría, backend/app/core/streams.py
(ambas implementaciones deben producir firmas intercambiables).
"""

from __future__ import annotations

import os

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2] / "backend"))

from agent.streams import SCHEMA_VERSION, canonical_json, sign_payload, verify_payload as agent_verify_payload

# También importamos el espejo del backend para verificar la simetría
from app.core.streams import (
    canonical_json as backend_canonical_json,
    check_schema_version,
    sign_payload as backend_sign_payload,
    verify_payload as backend_verify_payload,
)


# ── canonical_json determinístico ─────────────────────────────────────────────

def test_canonical_json_deterministic() -> None:
    """Mismo payload en distinto orden de inserción → mismo string."""
    p1 = {"b": 2, "a": 1, "c": 3}
    p2 = {"c": 3, "a": 1, "b": 2}
    assert canonical_json(p1) == canonical_json(p2)


def test_canonical_json_excludes_signature() -> None:
    p = {"event_id": "x", "signature": "should_be_excluded", "data": "y"}
    result = canonical_json(p)
    assert "signature" not in result
    assert "event_id" in result


def test_canonical_json_compact_separators() -> None:
    p = {"a": 1}
    result = canonical_json(p)
    assert " " not in result  # sin espacios después de : o ,


# ── verify_payload rechaza firma alterada ─────────────────────────────────────

def test_verify_payload_valid_signature() -> None:
    secret = os.urandom(32)
    payload = {"event_id": "e1", "path": "/etc/passwd"}
    payload["signature"] = backend_sign_payload(secret, payload)
    assert backend_verify_payload(secret, payload) is True


def test_verify_payload_rejects_altered_payload() -> None:
    secret = os.urandom(32)
    payload = {"event_id": "e1", "path": "/etc/passwd"}
    payload["signature"] = backend_sign_payload(secret, payload)
    payload["path"] = "/etc/shadow"  # alterar un byte
    assert backend_verify_payload(secret, payload) is False


def test_verify_payload_rejects_wrong_secret() -> None:
    secret1 = os.urandom(32)
    secret2 = os.urandom(32)
    payload = {"event_id": "e1"}
    payload["signature"] = backend_sign_payload(secret1, payload)
    assert backend_verify_payload(secret2, payload) is False


# ── simetría agente ↔ backend ──────────────────────────────────────────────────

def test_agent_signature_verifiable_by_backend() -> None:
    """Firma producida por agent/streams.py debe ser válida en backend/streams.py."""
    secret = os.urandom(32)
    payload = {"event_id": "e2", "agent_id": "agent-1", "schema_version": 1}
    payload["signature"] = sign_payload(secret, payload)
    assert backend_verify_payload(secret, payload) is True


def test_canonical_json_identical_in_both_impls() -> None:
    p = {"z": 3, "a": 1, "m": 2, "signature": "ignored"}
    assert canonical_json(p) == backend_canonical_json(p)


# ── schema_version: tres resultados (D37/RN-131, enmienda de RN-91) ───────────
#
# check_schema_version dejó de devolver un booleano: distingue un payload
# ilegible (schema_version ausente o no parseable, "invalid" — terminal) de
# un agente adelantado respecto del backend ("unsupported" — retenible, el
# evento sobrevive con backpressure). Ver D37 amendment y
# backend/app/core/streams.py.

def test_check_schema_version_supported() -> None:
    assert check_schema_version({"schema_version": SCHEMA_VERSION}) == "ok"


def test_check_schema_version_older_accepted() -> None:
    assert check_schema_version({"schema_version": 0}) == "ok"


def test_check_schema_version_future_unsupported_retainable() -> None:
    assert check_schema_version({"schema_version": SCHEMA_VERSION + 1}) == "unsupported"


def test_check_schema_version_missing_invalid_terminal() -> None:
    assert check_schema_version({}) == "invalid"


def test_check_schema_version_invalid_type_terminal() -> None:
    assert check_schema_version({"schema_version": "not-a-number"}) == "invalid"
