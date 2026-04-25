"""
Tests del processor sanitize_secrets.

Usa structlog.testing.capture_logs() para capturar logs en memoria
(sin output JSON real) — el processor se invoca igualmente pero el
renderer JSON no llega a correr, por eso los valores capturados son
los dictionaries pre-render.

Nota: capture_logs() reconfigura structlog temporalmente para capturar
en lista; después del `with` se restaura la config original.
"""

import os

import structlog

# Variables de entorno mínimas para importar Settings
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")

from app.core.logging import configure_logging
from app.core.logging import log
from app.core.logging import sanitize_secrets

# Configurar logging una sola vez para el módulo de tests.
configure_logging()


def test_password_redacted_direct_kwarg():
    """Password en kwargs de nivel 1 debe ser [REDACTED]."""
    with structlog.testing.capture_logs() as logs:
        log.info("login_attempt", username="alice", password="hunter2")

    assert len(logs) == 1
    entry = logs[0]
    assert entry["username"] == "alice"
    assert entry["password"] == "[REDACTED]"
    assert "hunter2" not in str(entry)


def test_access_token_redacted_direct_kwarg():
    """access_token en kwargs de nivel 1 debe ser [REDACTED]."""
    with structlog.testing.capture_logs() as logs:
        log.info("login", access_token="eyJhbGciOiJIUzI1NiJ9")

    entry = logs[0]
    assert entry["access_token"] == "[REDACTED]"
    assert "eyJhbGciOiJIUzI1NiJ9" not in str(entry)


def test_multiple_secrets_redacted():
    """password y access_token juntos — ambos redactados, username no."""
    with structlog.testing.capture_logs() as logs:
        log.info(
            "login",
            username="alice",
            password="hunter2",
            access_token="eyJ...",
        )

    entry = logs[0]
    assert entry["username"] == "alice"
    assert entry["password"] == "[REDACTED]"
    assert entry["access_token"] == "[REDACTED]"


def test_nested_dict_access_token_redacted():
    """Token en dict anidado debe ser [REDACTED]."""
    with structlog.testing.capture_logs() as logs:
        log.info("auth", payload={"user": "alice", "access_token": "eyJ..."})

    entry = logs[0]
    assert entry["payload"]["user"] == "alice"
    assert entry["payload"]["access_token"] == "[REDACTED]"


def test_case_insensitive_match():
    """Match de key es case-insensitive (Password con P mayúscula)."""
    with structlog.testing.capture_logs() as logs:
        log.info("x", Password="hunter2")

    entry = logs[0]
    assert entry["Password"] == "[REDACTED]"


def test_canonical_keys_all_redacted():
    """Todas las keys canónicas de RN-89 deben ser redactadas."""
    canonical_keys = [
        "password",
        "access_token",
        "refresh_token",
        "bootstrap_secret",
        "master_secret",
        "shared_secret",
        "signature",
    ]
    with structlog.testing.capture_logs() as logs:
        log.info("test", **{k: f"value_of_{k}" for k in canonical_keys})

    entry = logs[0]
    for k in canonical_keys:
        assert entry[k] == "[REDACTED]", f"Key '{k}' no fue redactada"


def test_non_sensitive_keys_preserved():
    """Keys no sensibles deben preservar sus valores."""
    with structlog.testing.capture_logs() as logs:
        log.info("event", user_id="123", action="login", status="ok")

    entry = logs[0]
    assert entry["user_id"] == "123"
    assert entry["action"] == "login"
    assert entry["status"] == "ok"


def test_sanitize_secrets_processor_direct():
    """Verificar el processor directamente sin pasar por structlog."""
    event_dict = {
        "event": "test",
        "password": "secret123",
        "username": "alice",
    }
    result = sanitize_secrets(None, "info", event_dict)
    assert result["password"] == "[REDACTED]"
    assert result["username"] == "alice"
    assert result["event"] == "test"
