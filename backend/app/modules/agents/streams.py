"""
Publicación de comandos HMAC-signed al stream Valkey `commands` para gestión de agentes (C14).

publish_update_config   — al actualizar watch_paths de un agente.
publish_rescan_baseline — al forzar re-scan de baseline de un agente.

Firma con shared_secret del agente destino (mismo patrón que modules/actions/streams.py de C13).
update_config incrementa el counter ruleset_version (mismo counter que C12/C13).

C36 (D30/RN-124): ambas funciones ahora registran una fila PublishedCommand
(antes no creaban ninguna) con el mismo `command_id` del payload y
`ack_status="pending"`, para que el consumer de `command_ack`
(agents/command_ack_consumer.py) pueda correlacionar la confirmación de
ejecución. Se comitea inmediatamente tras el XADD exitoso, porque estas
funciones se invocan post-commit del caller (ver agents/service.py).
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
from app.modules.rules.models import PublishedCommand

log = structlog.get_logger()


def _get_agent_secret(agent: Agent) -> bytes:
    """
    Obtiene el shared_secret del agente (ya cargado desde DB).
    Lanza ValueError si el agente no tiene secret.
    """
    if not agent.shared_secret_hex:
        raise ValueError(f"Agent {agent.agent_id} has no shared_secret_hex")
    return bytes.fromhex(agent.shared_secret_hex)


def _record_published_command(
    session: Session,
    agent_id: str,
    command_type: str,
    command_id: str,
    ruleset_version: int = 0,
) -> None:
    """
    Inserta un registro PublishedCommand confirmable (ack_status="pending").
    Mismo patrón que actions/streams.py::_record_published_command (C36).
    """
    cmd = PublishedCommand(
        command_type=command_type,
        target_agent_id=agent_id,
        command_id=command_id,
        ack_status="pending",
        ruleset_version=ruleset_version,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    session.add(cmd)


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

    command_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "type": "update_config",
        "command_id": command_id,
        "target_agent_id": agent.agent_id,
        "watch_paths": new_paths,
        "ruleset_version": ruleset_version,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    _record_published_command(session, agent.agent_id, "update_config", command_id, ruleset_version)
    valkey_client.xadd(STREAM_COMMANDS, {"data": data})
    # C36: commit propio — esta función corre post-commit del caller (ver docstring del módulo)
    session.commit()

    log.info(
        "streams.agents.update_config_published",
        agent_id=agent.agent_id,
        watch_paths=new_paths,
        ruleset_version=ruleset_version,
        command_id=command_id,
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

    command_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "type": "rescan_baseline",
        "command_id": command_id,
        "target_agent_id": agent.agent_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    _record_published_command(session, agent.agent_id, "rescan_baseline", command_id)
    valkey_client.xadd(STREAM_COMMANDS, {"data": data})
    # C36: commit propio — esta función corre post-commit del caller (ver docstring del módulo)
    session.commit()

    log.info(
        "streams.agents.rescan_baseline_published",
        agent_id=agent.agent_id,
        command_id=command_id,
    )
