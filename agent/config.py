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

    @field_validator("baseline_dir", "queue_dir", "journal_dir", mode="before")
    @classmethod
    def _not_empty(cls, v: object) -> object:
        if not str(v).strip():
            raise ValueError("storage path must not be empty")
        return v


class PublisherConfig(BaseModel):
    command_flush_timeout_s: float = 2.0


class AgentConfig(BaseModel):
    agent_id: str
    backend_url: str
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
