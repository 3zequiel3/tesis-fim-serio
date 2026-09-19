"""
Configuración tipada del backend FIM.

Usa pydantic-settings para leer variables de entorno (y opcionalmente .env).
La instancia `settings` se crea al import-time: si falta una variable
obligatoria pydantic lanza ValidationError antes de que uvicorn acepte
conexiones (fail-fast por diseño — D-CHANGE-04).

`extra="ignore"` tolera variables del compose que pertenecen a OTROS servicios
(ej. DB_PASSWORD para `db`, variables de n8n, etc.) sin causar fallo al arranque.
"""

from typing import Literal

from pydantic import Field
from pydantic import PostgresDsn
from pydantic import SecretStr
from pydantic import model_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

# Conexiones reservadas para consumidores que NO pasan por el executor de DB
# (D75/RN-169, D-4 del design de `ingest-offload-blocking-db`): 6 para las
# dependencias HTTP de FastAPI (`get_session`, cada request en vuelo retiene
# su conexión durante toda la request porque son endpoints async con Session
# sync — D21) + 2 para el consumer de heartbeat (`_handle_heartbeat` y
# `_sweep_offline`, que pueden coincidir) + 2 para las corrutinas del
# lifespan que abren `Session` directamente sobre el loop (`retention_task` y
# la lectura de `outbox_publisher_task`, D-8 del design). Es una CONSTANTE y
# no un cuarto parámetro configurable a propósito: D75 pide que el pool y el
# executor sean configurables, no la reserva — un knob acá permitiría
# desactivar el invariante ajustándolo.
_DB_CONNECTIONS_RESERVED_NON_EXECUTOR = 10


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

    # Hosts públicos del servidor (D53/RN-147, change 52). Lista separada por
    # comas de IPs y/o nombres DNS por los que los agentes remotos alcanzan
    # este backend. Extiende el SAN del certificado de servidor del backend
    # (8443/8444) y el de Valkey (6380) más allá de los nombres internos del
    # compose. Vacío ⇒ sólo los nombres internos ({backend, fim-backend,
    # localhost} / {valkey, localhost}), que es el comportamiento previo.
    fim_public_hosts: str = ""

    # Modo TLS de la consola web (D55/RN-149, change 52). Determina si
    # `_set_refresh_cookie` agrega `Secure` y qué certificado sirve nginx.
    # `off` ⇒ HTTP en claro (credenciales y tokens viajan sin cifrar);
    # `self_signed` ⇒ HTTPS con el certificado autofirmado ECDSA P-256 que
    # emite `certs-init`, sin la CA propia (D62/RN-156); `provided` ⇒ HTTPS
    # con un certificado provisto por el
    # operador (p. ej. Let's Encrypt). Un valor fuera de este dominio aborta
    # el arranque con ValidationError.
    console_tls_mode: Literal["off", "self_signed", "provided"] = "off"

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

    # Retención de rejected_events_audit (D65/RN-159, D4). rejected_events_audit
    # guarda payloads rechazados truncados y crecía sin límite; esta variable
    # fija cuántos días se conservan antes de que rejected_events_retention_task()
    # los elimine en lotes (backend/app/modules/events/service.py). ge=1 aborta
    # el arranque con ValidationError ante un valor inválido (0 o negativo) —
    # fail-fast, mismo criterio que el resto de Settings.
    # audit_log NO tiene un setting equivalente: su retención es ilimitada y no
    # se purga (W18/RN-94, ratificada) — no confundir ambas tablas.
    rejected_events_retention_days: int = Field(default=90, ge=1)

    # Dimensionamiento conjunto del pool de conexiones y del executor de
    # hilos (D75/RN-169, que amplía D21). Hoy `core/database.py` construye el
    # engine sólo con `pool_pre_ping=True` y `echo=False`, así que rigen los
    # defaults de SQLAlchemy: `pool_size=5` + `max_overflow=10` = 15
    # conexiones (verificado en ejecución: `QueuePool size=5 overflow_max=10`)
    # contra un executor por defecto de asyncio de `min(32, cpu_count + 4)` =
    # 16 hilos en el anfitrión de medición (12 CPUs). Mandar el trabajo
    # bloqueante del carril de ingesta al executor sin tocar el pool cambia
    # un cuello de botella por agotamiento de conexiones, que además falla en
    # vez de degradar. Los tres campos pasan a ser explícitos y configurables,
    # con el reparto de D-4 del design: capacidad total 20 = 6 (dependencias
    # HTTP de FastAPI) + 2 (consumer de heartbeat) + 2 (corrutinas del
    # lifespan con Session sobre el loop) + 10 (executor).
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_executor_max_workers: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def _validate_db_executor_within_pool(self) -> "Settings":
        """
        Fail-fast: el executor no puede tener más hilos que conexiones
        disponibles para él (D75/RN-169). Mismo criterio que
        `rejected_events_retention_days` — una configuración capaz de agotar
        el pool tiene que matar el arranque, no descubrirse bajo carga como
        un `TimeoutError` intermitente.
        """
        max_allowed = (
            self.db_pool_size + self.db_max_overflow - _DB_CONNECTIONS_RESERVED_NON_EXECUTOR
        )
        if self.db_executor_max_workers > max_allowed:
            raise ValueError(
                "db_executor_max_workers "
                f"({self.db_executor_max_workers}) excede la capacidad disponible del pool: "
                f"db_pool_size ({self.db_pool_size}) + db_max_overflow ({self.db_max_overflow}) "
                f"- reserva no-executor ({_DB_CONNECTIONS_RESERVED_NON_EXECUTOR}) = {max_allowed}. "
                "Bajá db_executor_max_workers o subí db_pool_size/db_max_overflow (D75/RN-169)."
            )
        return self

    def get_allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


# Instancia singleton — falla en import-time si DATABASE_URL o VALKEY_URL faltan.
settings = Settings()
