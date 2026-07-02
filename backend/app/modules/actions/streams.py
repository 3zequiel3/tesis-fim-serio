"""
Publicación de comandos HMAC-signed al stream Valkey `commands` (C13).

publish_baseline_update  — al aprobar un evento.
publish_restore_file     — al rechazar con action=restore.
publish_quarantine_file  — al rechazar con action=quarantine.

Todos firman con el shared_secret del agente destino (mismo patrón que C12).
El ruleset_version para baseline_update ya fue incrementado por el caller
(service._approve_single llama a _increment_ruleset_version primero).

FIX-03 (D10): Cada función inserta un registro PublishedCommand ANTES del XADD
para garantizar trazabilidad de auditoría. Si el XADD falla, el INSERT se
revierte junto con la transacción del caller.

C36 (D30/RN-124): cada función ahora persiste `command_id` (antes se generaba
y se descartaba) y `event_id` en la fila PublishedCommand, para que el
consumer de `command_ack` (agents/command_ack_consumer.py) pueda correlacionar
la confirmación de ejecución. Se agrega además `session.commit()` inmediato
tras el XADD exitoso: estas funciones se invocan DESPUÉS de que el caller ya
hizo `db.commit()` (post-commit del evento), así que sin este commit propio
la fila quedaba agregada a la sesión pero nunca llegaba a Postgres (bug
descubierto durante el apply de C36 — el rollback-on-XADD-failure existente
se preserva, ver test_published_command_inserted_before_xadd_atomicity).
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
from app.modules.events.models import Event
from app.modules.rules.models import PublishedCommand

log = structlog.get_logger()


def _record_published_command(
    session: Session,
    agent_id: str,
    command_type: str,
    command_id: str,
    event_id: int | None = None,
    ruleset_version: int = 0,
) -> None:
    """
    Inserta un registro PublishedCommand en la sesión (sin commit — el caller
    debe comitear después del XADD exitoso, ver C36).
    FIX-03 / D10: garantiza trazabilidad de auditoría para todos los tipos de comando.
    La inserción ocurre antes del XADD — si el XADD falla, el INSERT se revierte.
    C36 / D30: persiste `command_id` y `event_id` para correlacionar el
    `command_ack` de ejecución; `ack_status="pending"` marca el comando como
    confirmable (distinto de `status`, que es el estado de outbox).
    """
    cmd = PublishedCommand(
        command_type=command_type,
        target_agent_id=agent_id,
        event_id=event_id,
        command_id=command_id,
        ack_status="pending",
        ruleset_version=ruleset_version,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    session.add(cmd)


def _get_agent_secret(session: Session, agent_id: str) -> bytes:
    """
    Obtiene el shared_secret_hex del agente desde la DB (persistido en C06).
    Lanza ValueError si el agente no existe o no tiene secret.
    """
    from sqlmodel import select

    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if agent is None:
        raise ValueError(f"Agent not found: {agent_id}")
    if not agent.shared_secret_hex:
        raise ValueError(f"Agent {agent_id} has no shared_secret_hex")
    return bytes.fromhex(agent.shared_secret_hex)


def publish_baseline_update(
    session: Session,
    valkey_client: Any,
    event: Event,
    ruleset_version: int,
) -> None:
    """
    Publica comando `baseline_update` al stream `commands` firmado con HMAC-SHA256.

    Payload:
      type, command_id, event_id, target_agent_id, path, hash,
      baseline_status, ruleset_version, issued_at, signature.

    D2: usa event.hash_detected directamente, nunca consulta al agente.
    D5: lleva ruleset_version++ (incrementado por el caller).
    """
    try:
        secret = _get_agent_secret(session, event.agent_id)
    except ValueError as exc:
        log.error("streams.actions.publish_baseline_update.no_secret", agent_id=event.agent_id, error=str(exc))
        return

    # hash vacío == archivo ausente (D-C13-04, mismo criterio que service.py)
    hash_value: str | None = event.hash_detected if event.hash_detected else None
    baseline_status = "absent" if hash_value is None else "present"

    command_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "type": "baseline_update",
        "command_id": command_id,
        "event_id": event.id,
        "target_agent_id": event.agent_id,
        "path": event.path,
        "hash": hash_value,
        "baseline_status": baseline_status,
        "ruleset_version": ruleset_version,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    # FIX-03: registrar ANTES del XADD para atomicidad (D10)
    _record_published_command(
        session, event.agent_id, "baseline_update", command_id,
        event_id=event.id, ruleset_version=ruleset_version,
    )
    valkey_client.xadd(STREAM_COMMANDS, {"data": data})
    # C36: commit propio — esta función corre post-commit del caller (ver docstring del módulo)
    session.commit()

    log.info(
        "streams.actions.baseline_update_published",
        event_id=event.id,
        agent_id=event.agent_id,
        ruleset_version=ruleset_version,
        command_id=command_id,
    )


def publish_restore_file(
    session: Session,
    valkey_client: Any,
    event: Event,
) -> None:
    """
    Publica comando `restore_file` al stream `commands` firmado con HMAC-SHA256.

    Payload: type, command_id, event_id, target_agent_id, path, issued_at, signature.
    No incluye hash ni ruleset_version (según spec).
    """
    try:
        secret = _get_agent_secret(session, event.agent_id)
    except ValueError as exc:
        log.error("streams.actions.publish_restore_file.no_secret", agent_id=event.agent_id, error=str(exc))
        return

    command_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "type": "restore_file",
        "command_id": command_id,
        "event_id": event.id,
        "target_agent_id": event.agent_id,
        "path": event.path,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    # FIX-03: registrar ANTES del XADD para atomicidad (D10)
    _record_published_command(session, event.agent_id, "restore_file", command_id, event_id=event.id)
    valkey_client.xadd(STREAM_COMMANDS, {"data": data})
    # C36: commit propio — esta función corre post-commit del caller (ver docstring del módulo)
    session.commit()

    log.info(
        "streams.actions.restore_file_published",
        event_id=event.id,
        agent_id=event.agent_id,
        command_id=command_id,
    )


def publish_quarantine_file(
    session: Session,
    valkey_client: Any,
    event: Event,
) -> None:
    """
    Publica comando `quarantine_file` al stream `commands` firmado con HMAC-SHA256.

    Payload: type, command_id, event_id, target_agent_id, path, issued_at, signature.
    No incluye hash ni ruleset_version (según spec).
    """
    try:
        secret = _get_agent_secret(session, event.agent_id)
    except ValueError as exc:
        log.error("streams.actions.publish_quarantine_file.no_secret", agent_id=event.agent_id, error=str(exc))
        return

    command_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "type": "quarantine_file",
        "command_id": command_id,
        "event_id": event.id,
        "target_agent_id": event.agent_id,
        "path": event.path,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    # FIX-03: registrar ANTES del XADD para atomicidad (D10)
    _record_published_command(session, event.agent_id, "quarantine_file", command_id, event_id=event.id)
    valkey_client.xadd(STREAM_COMMANDS, {"data": data})
    # C36: commit propio — esta función corre post-commit del caller (ver docstring del módulo)
    session.commit()

    log.info(
        "streams.actions.quarantine_file_published",
        event_id=event.id,
        agent_id=event.agent_id,
        command_id=command_id,
    )
