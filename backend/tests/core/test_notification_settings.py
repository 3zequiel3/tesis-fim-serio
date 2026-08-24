"""
C46 — notification settings defaults (D43/RN-137).

Two properties are load-bearing here and neither is obvious from reading the
model:

1. `n8n_health_url` MUST NOT fall back to `n8n_webhook_url`. The whole point of
   D43/RN-137 is that the health check stops touching the webhook, because a GET
   against a live webhook can fire the workflow. A convenience fallback would
   silently reintroduce exactly that.

2. The SMTP TLS defaults MUST reproduce the previous hardcoded `start_tls=True`,
   so that existing deployments migrate in zero steps.
"""

from __future__ import annotations

import importlib

import pytest


def _fresh_settings(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Reimport app.core.config with a controlled environment."""
    for key in (
        "N8N_WEBHOOK_URL",
        "N8N_HEALTH_URL",
        "SMTP_HOST",
        "SMTP_STARTTLS",
        "SMTP_SSL",
        "WEBHOOK_FALLBACK_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import app.core.config as config

    return importlib.reload(config).Settings()


def test_notification_settings_default_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _fresh_settings(monkeypatch)

    assert settings.n8n_webhook_url == ""
    assert settings.n8n_health_url == ""
    assert settings.smtp_host == ""
    assert settings.webhook_fallback_url == ""


def test_health_url_is_not_derived_from_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """D43/RN-137: the health URL is configured, never inferred."""
    settings = _fresh_settings(
        monkeypatch, N8N_WEBHOOK_URL="http://n8n:5678/webhook/fim-alert"
    )

    assert settings.n8n_webhook_url == "http://n8n:5678/webhook/fim-alert"
    assert settings.n8n_health_url == "", (
        "n8n_health_url must stay empty when unset — deriving it from the webhook "
        "would point the health check back at the webhook, which is the bug "
        "D43/RN-137 exists to remove"
    )


def test_smtp_tls_defaults_preserve_previous_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before C46, send_smtp hardcoded start_tls=True. Defaults must match."""
    settings = _fresh_settings(monkeypatch)

    assert settings.smtp_starttls is True
    assert settings.smtp_ssl is False


def test_smtp_tls_flags_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _fresh_settings(monkeypatch, SMTP_STARTTLS="false", SMTP_SSL="true")

    assert settings.smtp_starttls is False
    assert settings.smtp_ssl is True


def teardown_module() -> None:
    """Restore the module-level singleton for the rest of the suite."""
    import app.core.config

    importlib.reload(app.core.config)
