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

from app.core.logging import sanitize_secrets


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
