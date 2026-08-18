"""
Encolado de comandos HMAC-signed al outbox `published_commands` para gestión
de agentes (C14, D37/RN-131).

enqueue_update_config   — al actualizar watch_paths de un agente.
enqueue_rescan_baseline — al forzar re-scan de baseline de un agente.

Firma con shared_secret del agente destino (mismo patrón que modules/actions/streams.py de C13).
update_config incrementa el counter ruleset_version (mismo counter que C12/C13).

D37/RN-131 (outbox transaccional): estas dos funciones ya NO hacen `XADD` ni
`session.commit()` propio. Firman y serializan el payload igual que
siempre, e insertan la fila `PublishedCommand` con `status="pending"` y
`published_at=None` — el caller (`agents/service.py`) debe llamarlas ANTES
de su propio `db.commit()`, dentro de la MISMA transacción que la mutación
del agente. La publicación efectiva (el `XADD`) la hace el despachador
genérico `rules.service.publish_pending_commands`. D37/RN-131 enumera
literalmente `baseline_update`, `restore_file` y `quarantine_file`;
`update_config` y `rescan_baseline` comparten el hueco idéntico
(publicador síncrono post-commit, sin outbox) y se incluyen por aplicación
del mismo principio — ver la desviación explícita en el proposal de
`stream-ack-durability`.

C36 (D30/RN-124): ambas funciones registran una fila PublishedCommand con el
mismo `command_id` del payload y `ack_status="pending"`, para que el
consumer de `command_ack` (agents/command_ack_consumer.py) pueda
correlacionar la confirmación de ejecución.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlmodel import Session

from app.core.streams import SCHEMA_VERSION, sign_payload
from app.modules.agents.models import Agent
from app.modules.rules.models import PublishedCommand

log = structlog.get_logger()


def _get_agent_secret(agent: Agent) -> bytes:
    """
    Obtiene el shared_secret del agente (ya cargado desde DB).
    Lanza ValueError si el agente no tiene secret. D37/RN-131: el caller NO
    debe capturar esta excepción — MUST propagarse para revertir la
    transacción (ver docstring del módulo).
    """
    if not agent.shared_secret_hex:
        raise ValueError(f"Agent {agent.agent_id} has no shared_secret_hex")
    return bytes.fromhex(agent.shared_secret_hex)


def _record_published_command(
    session: Session,
    agent_id: str,
    command_type: str,
    command_id: str,
    payload: str,
    ruleset_version: int = 0,
) -> None:
    """
    Inserta un registro PublishedCommand `pending` (outbox, D37/RN-131) —
    sin `XADD` ni commit propio. Mismo patrón que
    actions/streams.py::_record_published_command.
    """
    cmd = PublishedCommand(
        command_type=command_type,
        target_agent_id=agent_id,
        command_id=command_id,
        ack_status="pending",
        ruleset_version=ruleset_version,
        payload=payload,
        status="pending",
        published_at=None,
    )
    session.add(cmd)


def enqueue_update_config(
    session: Session,
    agent: Agent,
    new_paths: list[str],
    ruleset_version: int,
) -> None:
    """
    Encola el comando `update_config` en el outbox, firmado con HMAC-SHA256.

    Payload:
      type, command_id, target_agent_id, watch_paths, ruleset_version,
      issued_at, schema_version, signature.

    D-C14-05: el ruleset_version ya fue incrementado por el caller (update_agent_config).
    MUST llamarse ANTES de `db.commit()` (D37/RN-131) — ver docstring del módulo.
    """
    secret = _get_agent_secret(agent)

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
    _record_published_command(session, agent.agent_id, "update_config", command_id, data, ruleset_version)

    log.info(
        "streams.agents.update_config_enqueued",
        agent_id=agent.agent_id,
        watch_paths=new_paths,
        ruleset_version=ruleset_version,
        command_id=command_id,
    )


def enqueue_rescan_baseline(
    session: Session,
    agent: Agent,
) -> None:
    """
    Encola el comando `rescan_baseline` en el outbox, firmado con HMAC-SHA256.

    Payload:
      type, command_id, target_agent_id, issued_at, schema_version, signature.

    MUST llamarse ANTES de `db.commit()` (D37/RN-131) — ver docstring del módulo.
    """
    secret = _get_agent_secret(agent)

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
    _record_published_command(session, agent.agent_id, "rescan_baseline", command_id, data)

    log.info(
        "streams.agents.rescan_baseline_enqueued",
        agent_id=agent.agent_id,
        command_id=command_id,
    )
