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

    # Rate limiting de ingesta de eventos (RN-88, D7) — ventana deslizante por
    # agent_id del consumer del stream `events`. Parametrizado para las corridas
    # de laboratorio del Cap. 5 (P1 del plan de medición): con el límite fijo en
    # 100/60s la batería de concurrencia se estrangula a sí misma. Los defaults
    # reproducen exactamente el comportamiento hardcodeado previo.
    # La ventana es float (no int como la de login) porque además de acotar el
    # presupuesto deriva el `retry_after` del `event_nack` de rate_limited
    # (D37/RN-131), que se expresa en segundos fraccionarios.
    rate_limit_ingest_events: int = 100             # eventos máximos por ventana y agent_id
    rate_limit_ingest_window_seconds: float = 60.0  # ventana de ingesta en segundos

    # command_ack (D30/RN-124, C36) — umbral del barrido de timeout de comandos sin confirmar.
    # Default alineado con _DEAD_THRESHOLD_S del heartbeat_consumer (300s).
    command_ack_timeout_seconds: int = 300

    # Notificaciones — todas opcionales; si faltan, el canal correspondiente se salta.
    n8n_webhook_url: str = ""

    # Endpoint de salud de n8n (D43/RN-137). DELIBERADAMENTE independiente de
    # n8n_webhook_url y NO derivado de él: derivarlo (parsear el host y sustituir
    # el path por /healthz) adivinaría la topología — el webhook puede estar
    # detrás de un proxy, un path prefix o un host distinto — y devolvería el
    # health check al problema que esta decisión corrige: pegarle a algo que no
    # es un endpoint de salud. Un GET contra un webhook productivo puede DISPARAR
    # el workflow, convirtiendo un check de 10 s en un emisor de notificaciones.
    # Vacío ⇒ el componente n8n se reporta `degraded` (no se puede afirmar que
    # está sano sin con qué comprobarlo).
    n8n_health_url: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    # Modo de cifrado del canal SMTP (D43/RN-137). Antes `send_smtp` forzaba
    # start_tls=True sin condición, así que un relay en 465 (SMTPS implícito) o
    # uno interno sin STARTTLS fallaba siempre. Los defaults reproducen
    # exactamente el comportamiento previo: migración de cero pasos.
    #   smtp_ssl=True                        → TLS implícito (SMTPS, típico 465)
    #   smtp_starttls=True y smtp_ssl=False  → STARTTLS (típico 587) — default
    #   ambos False                          → sin cifrar (solo relay interno)
    # Ambos en True es configuración inválida y se registra como error.
    smtp_starttls: bool = True
    smtp_ssl: bool = False

    webhook_fallback_url: str = ""

    def get_allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


# Instancia singleton — falla en import-time si DATABASE_URL o VALKEY_URL faltan.
settings = Settings()
