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
    """Reimport app.core.config with a controlled environment.

    D78/RN-172, Caso B (task 4.5): el `delenv` de abajo sanea `os.environ`, y
    eso es correcto y necesario, pero por sí solo NO alcanza — `env_file`
    (`app/core/config.py:40`) es una ruta relativa que pydantic-settings
    resuelve contra el directorio de trabajo del proceso, y un `.env` real en
    ese directorio se lee igual, `delenv` o no. La defensa contra ESO vive en
    `backend/tests/conftest.py` (neutraliza la fuente dotenv una sola vez,
    para toda la suite). Este `delenv` se CONSERVA a propósito aunque quede
    redundante contra el mecanismo del conftest: es la defensa explícita de
    este test contra una variable exportada por el proceso invocante, y
    quitarla lo dejaría dependiendo de un mecanismo que vive en otro archivo.
    """
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


def test_dotenv_file_in_cwd_does_not_leak_into_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    D78/RN-172, Caso B (task 6.5) — la prueba central de esta obligación.

    Un `.env` REAL, en el directorio de trabajo, con las mismas claves que
    produjeron la fuga original (`N8N_WEBHOOK_URL`, `N8N_HEALTH_URL`). La
    defensa acá NO es el `delenv` de `_fresh_settings` de arriba —eso sólo
    limpia `os.environ` y no evita que pydantic-settings lea el archivo—: es
    el monkeypatch de `DotEnvSettingsSource._read_env_files` que
    `backend/tests/conftest.py` aplica una sola vez, para toda la suite,
    antes del primer import de `app.core.config`. Si esta aserción falla, el
    monkeypatch centralizado dejó de aplicarse.
    """
    (tmp_path / ".env").write_text(
        "N8N_WEBHOOK_URL=http://n8n:5678/webhook/fim-alert\n"
        "N8N_HEALTH_URL=http://n8n:5678/healthz\n"
    )
    monkeypatch.chdir(tmp_path)

    settings = _fresh_settings(monkeypatch)

    assert settings.n8n_webhook_url == "", (
        "un .env real en el CWD no debe filtrarse a Settings() — la suite "
        "debe producir el mismo resultado que si se la invocara desde un "
        "directorio sin ese archivo"
    )
    assert settings.n8n_health_url == ""


def test_env_var_exported_by_invoking_process_does_not_leak_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    D78/RN-172, Caso B (task 6.6). Simula que el proceso que invoca pytest ya
    tenía `N8N_WEBHOOK_URL` exportada -sentándola ANTES del saneamiento, no
    después- para probar que la defensa es real y no pasa "por vacío" porque
    el entorno de CI nunca tuvo la variable puesta. El `delenv` de
    `_fresh_settings` corre después de este `setenv` y la borra antes de
    reconstruir `Settings()`.
    """
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://exported-by-invoking-shell/webhook")

    settings = _fresh_settings(monkeypatch)

    assert settings.n8n_webhook_url == "", (
        "una variable exportada por el proceso invocante no debe sobrevivir "
        "al saneamiento del entorno de prueba"
    )


def test_guard_config_still_declares_env_file() -> None:
    """
    Task 6.7 — guarda sobre producción: falla si alguien "arregla" la suite
    cambiando la configuración de la aplicación (`env_file=".env"`,
    `config.py:40`) en lugar del arnés. `env_file=".env"` es correcto y
    necesario para el despliegue (D-6 del design); el defecto nunca fue que
    la aplicación lea su `.env`, sino que la SUITE lo heredara.
    """
    from app.core.config import Settings

    assert Settings.model_config.get("env_file") == ".env"


def teardown_module() -> None:
    """Restore the module-level singleton for the rest of the suite."""
    import app.core.config

    importlib.reload(app.core.config)
