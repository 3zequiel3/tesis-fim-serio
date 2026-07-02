"""
Configuración tipada del backend FIM.

Usa pydantic-settings para leer variables de entorno (y opcionalmente .env).
La instancia `settings` se crea al import-time: si falta una variable
obligatoria pydantic lanza ValidationError antes de que uvicorn acepte
conexiones (fail-fast por diseño — D-CHANGE-04).

`extra="ignore"` tolera variables del compose que pertenecen a OTROS servicios
(ej. DB_PASSWORD para `db`, variables de n8n, etc.) sin causar fallo al arranque.
"""

from pydantic import PostgresDsn
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # Obligatorias — sin default; ValidationError al startup si faltan.
    database_url: PostgresDsn
    valkey_url: str

    # Auth — obligatorias desde Change 04.
    jwt_secret_current: str
    jwt_secret_previous: str = ""
    admin_username: str = ""
    admin_password: SecretStr = SecretStr("")
    admin_email: str = "admin@fim.local"

    # CORS — lista de origins permitidos, separada por comas.
    cors_allowed_origins: str = ""

    # PKI (Change 06).
    ca_cert_path: str = ""
    ca_key_path: str = ""
    backend_cert_path: str = ""
    backend_key_path: str = ""

    # Comportamiento del backend.
    environment: str = "dev"
    log_level: str = "INFO"

    # Rate limiting (C20) — defaults idénticos a las constantes anteriores de rate_limit.py.
    rate_limit_login_attempts: int = 5          # intentos máximos por ventana (LOGIN_MAX_ATTEMPTS)
    rate_limit_login_window_seconds: int = 900  # ventana login en segundos
    rate_limit_api_per_minute: int = 100        # req/min por user_id autenticado

    # command_ack (D30/RN-124, C36) — umbral del barrido de timeout de comandos sin confirmar.
    # Default alineado con _DEAD_THRESHOLD_S del heartbeat_consumer (300s).
    command_ack_timeout_seconds: int = 300

    # Notificaciones — todas opcionales; si faltan, el canal correspondiente se salta.
    n8n_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    webhook_fallback_url: str = ""

    def get_allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


# Instancia singleton — falla en import-time si DATABASE_URL o VALKEY_URL faltan.
settings = Settings()
