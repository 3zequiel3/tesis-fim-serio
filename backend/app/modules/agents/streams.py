"""
Publicación de comandos HMAC-signed al stream Valkey `commands` para gestión de agentes (C14).

publish_update_config   — al actualizar watch_paths de un agente.
publish_rescan_baseline — al forzar re-scan de baseline de un agente.

Firma con shared_secret del agente destino (mismo patrón que modules/actions/streams.py de C13).
update_config incrementa el counter ruleset_version (mismo counter que C12/C13).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlmodel import Session

from app.core.streams import SCHEMA_VERSION, STREAM_COMMANDS, sign_payload
from app.modules.agents.models import Agent

log = structlog.get_logger()


def _get_agent_secret(agent: Agent) -> bytes:
    """
    Obtiene el shared_secret del agente (ya cargado desde DB).
    Lanza ValueError si el agente no tiene secret.
    """
    if not agent.shared_secret_hex:
        raise ValueError(f"Agent {agent.agent_id} has no shared_secret_hex")
    return bytes.fromhex(agent.shared_secret_hex)


def publish_update_config(
    session: Session,
    valkey_client: Any,
    agent: Agent,
    new_paths: list[str],
    ruleset_version: int,
) -> None:
    """
    Publica comando `update_config` al stream `commands` firmado con HMAC-SHA256.

    Payload:
      type, command_id, target_agent_id, watch_paths, ruleset_version,
      issued_at, schema_version, signature.

    D-C14-05: el ruleset_version ya fue incrementado por el caller (update_agent_config).
    """
    try:
        secret = _get_agent_secret(agent)
    except ValueError as exc:
        log.error(
            "streams.agents.publish_update_config.no_secret",
            agent_id=agent.agent_id,
            error=str(exc),
        )
        return

    payload: dict[str, Any] = {
        "type": "update_config",
        "command_id": str(uuid.uuid4()),
        "target_agent_id": agent.agent_id,
        "watch_paths": new_paths,
        "ruleset_version": ruleset_version,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    valkey_client.xadd(STREAM_COMMANDS, {"data": data})

    log.info(
        "streams.agents.update_config_published",
        agent_id=agent.agent_id,
        watch_paths=new_paths,
        ruleset_version=ruleset_version,
    )


def publish_rescan_baseline(
    session: Session,
    valkey_client: Any,
    agent: Agent,
) -> None:
    """
    Publica comando `rescan_baseline` al stream `commands` firmado con HMAC-SHA256.

    Payload:
      type, command_id, target_agent_id, issued_at, schema_version, signature.
    """
    try:
        secret = _get_agent_secret(agent)
    except ValueError as exc:
        log.error(
            "streams.agents.publish_rescan_baseline.no_secret",
            agent_id=agent.agent_id,
            error=str(exc),
        )
        return

    payload: dict[str, Any] = {
        "type": "rescan_baseline",
        "command_id": str(uuid.uuid4()),
        "target_agent_id": agent.agent_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    valkey_client.xadd(STREAM_COMMANDS, {"data": data})

    log.info(
        "streams.agents.rescan_baseline_published",
        agent_id=agent.agent_id,
    )
