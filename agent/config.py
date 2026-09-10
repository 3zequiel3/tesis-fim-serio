from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, PrivateAttr, field_validator

# D36/RN-130 (D-10): código de salida único para todo fallo de CONFIGURACIÓN
# del arranque (EX_CONFIG, sysexits.h). fim-agent.service declara
# `RestartPreventExitStatus=78` para que un despliegue mal configurado quede
# en `failed` con un mensaje legible una sola vez, en vez de repetir el mismo
# error cada RestartSec en un loop de Restart=on-failure indefinido.
EX_CONFIG = 78


class StorageConfig(BaseModel):
    baseline_dir: str
    queue_dir: str
    journal_dir: str
    secrets_dir: str = "/var/lib/fim-agent/secrets"
    certs_dir: str = "/var/lib/fim-agent/certs"
    # D37/RN-131 (D-8 del design): directorio local de descarte, hermano de la
    # cola. Destino terminal de un evento que agota el techo de reintentos o
    # recibe un event_nack terminal (invalid_schema, clock_skew).
    discard_dir: str = "/var/lib/fim-agent/discarded"
    quarantine_retention_days: int = 30

    @field_validator("baseline_dir", "queue_dir", "journal_dir", "discard_dir", mode="before")
    @classmethod
    def _not_empty(cls, v: object) -> object:
        if not str(v).strip():
            raise ValueError("storage path must not be empty")
        return v

    @field_validator("quarantine_retention_days", mode="before")
    @classmethod
    def _valid_quarantine_retention(cls, v: object) -> object:
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 365:
            raise ValueError("quarantine_retention_days must be between 1 and 365")
        return v


class PublisherConfig(BaseModel):
    command_flush_timeout_s: float = 2.0
    # D37/RN-131: parámetros operativos del contrato de durabilidad del
    # transporte (design D-4/D-6/D-7/D-8, valores por defecto del appendix).
    # Techo de reintentos por evento sin respuesta de ningún tipo (~20 h de
    # backend inalcanzable a 60 s por intento antes de descartar).
    max_publish_attempts: int = 20
    # Techo del retry_after que el agente acepta de un event_nack retenible:
    # un backend con un bug o comprometido no puede silenciar al agente por
    # más de este valor con un retry_after enorme (D-5, D-6).
    max_retry_after_s: float = 60.0
    # Cota por cantidad de archivos del directorio de descarte, con
    # drop-oldest propio (D-8), mismo criterio que la cola de RN-40.
    max_discard_files: int = 1000

    @field_validator("max_publish_attempts", "max_discard_files", mode="before")
    @classmethod
    def _positive_int(cls, v: object) -> object:
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ValueError("must be a positive integer")
        return v

    @field_validator("max_retry_after_s", mode="before")
    @classmethod
    def _positive_float(cls, v: object) -> object:
        try:
            numeric = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError("must be a positive number") from None
        if numeric <= 0:
            raise ValueError("must be a positive number")
        return v


class AgentConfig(BaseModel):
    agent_id: str
    backend_url: str
    # Credential issuance is isolated from the ordinary HTTP API.
    mtls_backend_url: str = ""
    valkey_url: str
    ca_cert_path: str
    watch_paths: list[str]
    storage: StorageConfig
    publisher: PublisherConfig = PublisherConfig()
    cert_renewal_check_interval_h: float = 24.0
    allow_plaintext_valkey: bool = False

    _config_path: Path | None = PrivateAttr(default=None)

    @field_validator("agent_id", mode="before")
    @classmethod
    def _agent_id_not_empty(cls, v: object) -> object:
        if not str(v).strip():
            raise ValueError("agent_id must not be empty")
        return v

    @field_validator("watch_paths", mode="before")
    @classmethod
    def _watch_paths_not_empty(cls, v: object) -> object:
        if not v:
            raise ValueError("watch_paths must not be empty")
        return v


def load_config(path: str | Path = "/etc/fim-agent/config.yaml") -> AgentConfig:
    path = Path(path)
    if not path.exists():
        print(f"Config file not found: {path}", file=sys.stderr)
        sys.exit(EX_CONFIG)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        cfg = AgentConfig.model_validate(data)
        cfg._config_path = Path(path)
        return cfg
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Config validation error: {exc}", file=sys.stderr)
        sys.exit(EX_CONFIG)
