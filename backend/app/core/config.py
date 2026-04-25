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

    # Variables que usan Changes posteriores; default vacío en M1.
    jwt_secret_current: str = ""
    jwt_secret_previous: str = ""
    admin_username: str = ""
    admin_password: SecretStr = SecretStr("")
    ca_cert_path: str = ""
    ca_key_path: str = ""

    # Comportamiento del backend.
    environment: str = "dev"
    log_level: str = "INFO"


# Instancia singleton — falla en import-time si DATABASE_URL o VALKEY_URL faltan.
settings = Settings()
