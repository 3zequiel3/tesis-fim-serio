"""
Tests for the sanitize_secrets log processor (RN-89).

The production sanitizer in app.core.logging is already correct (case-insensitive,
recursive). These tests call sanitize_secrets() directly instead of using
structlog.testing.capture_logs(), which replaces the configured processor chain
and therefore would never run the sanitizer.

Pattern: build an event_dict, call sanitize_secrets(None, "info", event_dict),
assert on the returned dict.
"""

import os

# Env vars needed before Settings() is instantiated at import time.
# The root conftest already sets these, but this module may be imported
# before conftest runs in some collection orders, so we guard with setdefault.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")

from app.core.logging import redact_query_credentials, sanitize_secrets


def test_password_redacted_direct_kwarg():
    """Password at top-level must be [REDACTED]."""
    event_dict = {"event": "login_attempt", "username": "alice", "password": "hunter2"}
    result = sanitize_secrets(None, "info", event_dict)
    assert result["username"] == "alice"
    assert result["password"] == "[REDACTED]"
    assert "hunter2" not in str(result)


def test_access_token_redacted_direct_kwarg():
    """access_token at top-level must be [REDACTED]."""
    event_dict = {"event": "login", "access_token": "eyJhbGciOiJIUzI1NiJ9"}
    result = sanitize_secrets(None, "info", event_dict)
    assert result["access_token"] == "[REDACTED]"
    assert "eyJhbGciOiJIUzI1NiJ9" not in str(result)


def test_multiple_secrets_redacted():
    """Both password and access_token are redacted; username is preserved."""
    event_dict = {
        "event": "login",
        "username": "alice",
        "password": "hunter2",
        "access_token": "eyJ...",
    }
    result = sanitize_secrets(None, "info", event_dict)
    assert result["username"] == "alice"
    assert result["password"] == "[REDACTED]"
    assert result["access_token"] == "[REDACTED]"


def test_nested_dict_access_token_redacted():
    """Token in a nested dict is recursively [REDACTED]."""
    event_dict = {
        "event": "auth",
        "payload": {"user": "alice", "access_token": "eyJ..."},
    }
    result = sanitize_secrets(None, "info", event_dict)
    assert result["payload"]["user"] == "alice"
    assert result["payload"]["access_token"] == "[REDACTED]"


def test_case_insensitive_match():
    """Key matching is case-insensitive: 'Password' (capital P) is redacted."""
    event_dict = {"event": "x", "Password": "hunter2"}
    result = sanitize_secrets(None, "info", event_dict)
    assert result["Password"] == "[REDACTED]"


def test_canonical_keys_all_redacted():
    """All canonical sensitive keys from RN-89 are redacted."""
    canonical_keys = [
        "password",
        "access_token",
        "refresh_token",
        "bootstrap_secret",
        "master_secret",
        "shared_secret",
        "signature",
    ]
    event_dict = {"event": "test", **{k: f"value_of_{k}" for k in canonical_keys}}
    result = sanitize_secrets(None, "info", event_dict)
    for k in canonical_keys:
        assert result[k] == "[REDACTED]", f"Key '{k}' was not redacted"


def test_hex_dump_keys_redacted():
    """US-09: hex_dump_before/hex_dump_after are redacted like diff_text."""
    event_dict = {
        "event": "test",
        "hex_dump_before": "00000000  89 50 4e 47",
        "hex_dump_after": "00000000  ff ee dd cc",
    }
    result = sanitize_secrets(None, "info", event_dict)
    assert result["hex_dump_before"] == "[REDACTED]"
    assert result["hex_dump_after"] == "[REDACTED]"


def test_non_sensitive_keys_preserved():
    """Non-sensitive keys retain their original values."""
    event_dict = {
        "event": "event",
        "user_id": "123",
        "action": "login",
        "status": "ok",
    }
    result = sanitize_secrets(None, "info", event_dict)
    assert result["user_id"] == "123"
    assert result["action"] == "login"
    assert result["status"] == "ok"


def test_diff_text_redacted_direct_kwarg():
    """diff_text at top-level must be [REDACTED] — it carries file content
    that can include secrets (RN-89 defense-in-depth, privacy hardening)."""
    event_dict = {
        "event": "event_detail",
        "diff_text": "--- a/etc/shadow\n+++ b/etc/shadow\n@@ -1 +1 @@\n-root:x\n+root:hacked\n",
    }
    result = sanitize_secrets(None, "info", event_dict)
    assert result["diff_text"] == "[REDACTED]"
    assert "root:hacked" not in str(result)


def test_sanitize_secrets_processor_direct():
    """Direct processor call: verifies signature (logger, method_name, event_dict)."""
    event_dict = {
        "event": "test",
        "password": "secret123",
        "username": "alice",
    }
    result = sanitize_secrets(None, "info", event_dict)
    assert result["password"] == "[REDACTED]"
    assert result["username"] == "alice"
    assert result["event"] == "test"


# ── redact_query_credentials (D64/RN-158) ─────────────────────────────────────


def test_redact_query_credentials_uvicorn_access_line():
    """Línea de uvicorn.access con ?ticket=...&last_event_id=9: ticket redactado,
    last_event_id intacto, el valor del ticket no aparece en ninguna parte."""
    event_dict = {
        "event": '"GET /alerts/stream?ticket=abc123&last_event_id=9 HTTP/1.1" 200',
    }
    result = redact_query_credentials(None, "info", event_dict)
    assert "ticket=[REDACTED]&last_event_id=9" in result["event"]
    assert "abc123" not in result["event"]


def test_redact_query_credentials_token_residual():
    event_dict = {"event": "/alerts/stream?token=eyJhbGciOi.payload.sig"}
    result = redact_query_credentials(None, "info", event_dict)
    assert "token=[REDACTED]" in result["event"]
    assert "eyJhbGciOi" not in result["event"]


def test_redact_query_credentials_nested_string_case_insensitive():
    event_dict = {"event": "sse.request", "ctx": {"url": "/alerts/stream?Ticket=abc123"}}
    result = redact_query_credentials(None, "info", event_dict)
    assert result["ctx"]["url"] == "/alerts/stream?Ticket=[REDACTED]"


def test_redact_query_credentials_non_credential_query_untouched():
    event_dict = {"event": "x", "url": "/events?page=2&size=50"}
    result = redact_query_credentials(None, "info", event_dict)
    assert result["url"] == "/events?page=2&size=50"


def test_redact_query_credentials_access_token_param():
    event_dict = {"event": "/alerts/stream?access_token=secretvalue123"}
    result = redact_query_credentials(None, "info", event_dict)
    assert "access_token=[REDACTED]" in result["event"]
    assert "secretvalue123" not in result["event"]


# ── 5.7: end-to-end via el pipeline real de configure_logging() ──────────────
#
# TestClient (httpx + ASGITransport) nunca pasa por el servidor uvicorn real,
# así que no dispara el middleware de access log de uvicorn — ese camino
# completo (nginx + uvicorn reales) se verifica en 7.4 contra el stack
# levantado. Esta prueba verifica en cambio que el pipeline REAL configurado
# por configure_logging() (dictConfig + structlog.configure(), no la función
# processor llamada a mano como en los tests de arriba) redacta una línea
# `uvicorn.access` con el formato real que produciría el servidor, emitida a
# través del logger stdlib `uvicorn.access` — mismo logger que dictConfig
# conecta al ProcessorFormatter con el foreign_pre_chain real.


def test_e2e_stream_ticket_never_appears_in_stdout(capfd):
    """
    Hace GET /alerts/stream?ticket=<valor> (401, ticket inexistente) contra la
    app configurada con configure_logging(), y emite además la línea de
    access log que produciría uvicorn para esa request real a través del
    logger stdlib `uvicorn.access` — el mismo que configure_logging() conecta
    al ProcessorFormatter con sanitize_secrets + redact_query_credentials.
    Ninguna línea de stdout/stderr debe contener el valor del ticket.

    Sin overrides de sesión: usa la Postgres real de test (autouse
    _db_isolation de conftest), igual que cualquier otro request no-SSE de la
    suite — el ticket inexistente corta en la dependencia antes de tocar la
    tabla alerts.
    """
    import logging as stdlib_logging

    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock, MagicMock

    from app.core.logging import configure_logging
    from app.core.valkey import get_async_valkey_client, get_valkey_client
    from app.main import app

    configure_logging()

    ticket_value = "super-secret-e2e-ticket-should-not-leak"

    mock_async_valkey = AsyncMock()
    mock_async_valkey.getdel.return_value = None  # ticket inexistente ⇒ 401

    app.dependency_overrides[get_valkey_client] = lambda: MagicMock()
    app.dependency_overrides[get_async_valkey_client] = lambda: mock_async_valkey

    try:
        with TestClient(app) as tc:
            resp = tc.get(f"/alerts/stream?ticket={ticket_value}")
        assert resp.status_code == 401

        stdlib_logging.getLogger("uvicorn.access").info(
            '%s - "GET /alerts/stream?ticket=%s HTTP/1.1" 401',
            "127.0.0.1:12345",
            ticket_value,
        )
    finally:
        app.dependency_overrides.clear()

    captured = capfd.readouterr()
    assert ticket_value not in captured.out
    assert ticket_value not in captured.err
    assert "ticket=[REDACTED]" in captured.out
