from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


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


class AgentConfig(BaseModel):
    agent_id: str
    backend_url: str
    valkey_url: str
    ca_cert_path: str
    watch_paths: list[str]
    storage: StorageConfig

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
        sys.exit(1)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return AgentConfig.model_validate(data)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Config validation error: {exc}", file=sys.stderr)
        sys.exit(1)
