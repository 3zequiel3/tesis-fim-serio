"""
Encolado de comandos HMAC-signed al outbox `published_commands` (C13, D37/RN-131).

enqueue_baseline_update  — al aprobar un evento.
enqueue_restore_file     — al rechazar con action=restore.
enqueue_quarantine_file  — al rechazar con action=quarantine.

Todos firman con el shared_secret del agente destino (mismo patrón que C12).
El ruleset_version para baseline_update ya fue incrementado por el caller
(service._approve_single llama a _increment_ruleset_version primero).

D37/RN-131 (outbox transaccional, reemplaza FIX-03/C36 síncrono): estas tres
funciones ya NO hacen `XADD` ni `session.commit()` propio. Firman y serializan
el payload igual que siempre, e insertan la fila `PublishedCommand` con
`status="pending"` y `published_at=None` — el caller (`actions/service.py`)
debe llamarlas ANTES de su propio `db.commit()`, dentro de la MISMA
transacción que la mutación del evento. La publicación efectiva (el `XADD`)
la hace el despachador genérico `rules.service.publish_pending_commands`,
que ya corre post-commit best-effort y también como background task
periódico (ver `main.py` lifespan) — no se inventa un segundo mecanismo.

Esto invierte la norma previa "publicar solo post-commit" (FIX-02): la
protección que FIX-02 buscaba —que el agente no reciba un comando de una
transacción que después se revierte— ahora la da la atomicidad de la fila
del outbox en la misma transacción del evento, de forma más fuerte: si la
transacción se revierte, la fila del comando se revierte con ella; si
comitea, el comando está garantizado en el outbox y el despachador lo
entrega con reintento. Ver D-10 del design de `stream-ack-durability`.

Si `_get_agent_secret` no puede resolver el secreto del agente, la excepción
SHALL propagarse sin capturarse acá — revierte la transacción del caller en
vez de dejar un evento terminal con ningún comando emitido (el bug que
motivó esta change).

C36 (D30/RN-124): cada función persiste `command_id` y `event_id` en la fila
PublishedCommand, para que el consumer de `command_ack`
(agents/command_ack_consumer.py) pueda correlacionar la confirmación de
ejecución. `ack_status="pending"` marca el comando como confirmable —
distinto de `status`, que es el estado de outbox (D-1 del design de C36).
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
from app.modules.events.models import Event
from app.modules.rules.models import PublishedCommand

log = structlog.get_logger()


def _record_published_command(
    session: Session,
    agent_id: str,
    command_type: str,
    command_id: str,
    payload: str,
    event_id: int | None = None,
    ruleset_version: int = 0,
) -> None:
    """
    Inserta un registro PublishedCommand `pending` en la sesión (D37/RN-131:
    outbox — sin `XADD` ni commit propio, el caller decide cuándo comitea y
    el despachador genérico publica después). `payload` es el JSON ya
    firmado y serializado, listo para que `publish_pending_commands` lo
    `XADD`-ee tal cual.

    `command_id` y `event_id` se conservan para correlacionar el
    `command_ack` de ejecución (C36/D30); `ack_status="pending"` marca el
    comando como confirmable.
    """
    cmd = PublishedCommand(
        command_type=command_type,
        target_agent_id=agent_id,
        event_id=event_id,
        command_id=command_id,
        ack_status="pending",
        ruleset_version=ruleset_version,
        payload=payload,
        status="pending",
        published_at=None,
    )
    session.add(cmd)


def _get_agent_secret(session: Session, agent_id: str) -> bytes:
    """
    Obtiene el shared_secret_hex del agente desde la DB (persistido en C06).
    Lanza ValueError si el agente no existe o no tiene secret. D37/RN-131:
    el caller NO debe capturar esta excepción — MUST propagarse para
    revertir la transacción (ver docstring del módulo).
    """
    from sqlmodel import select

    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if agent is None:
        raise ValueError(f"Agent not found: {agent_id}")
    if not agent.shared_secret_hex:
        raise ValueError(f"Agent {agent_id} has no shared_secret_hex")
    return bytes.fromhex(agent.shared_secret_hex)


def enqueue_baseline_update(
    session: Session,
    event: Event,
    ruleset_version: int,
) -> None:
    """
    Encola el comando `baseline_update` en el outbox, firmado con HMAC-SHA256.

    Payload:
      type, command_id, event_id, source_event_id, target_agent_id, path, hash,
      baseline_status, ruleset_version, issued_at, signature.

    D2: usa event.hash_detected directamente, nunca consulta al agente.
    D5: lleva ruleset_version++ (incrementado por el caller).

    MUST llamarse ANTES de `db.commit()`, dentro de la transacción que muta
    el evento (D37/RN-131) — ver docstring del módulo.
    """
    secret = _get_agent_secret(session, event.agent_id)

    # hash vacío == archivo ausente (D-C13-04, mismo criterio que service.py)
    hash_value: str | None = event.hash_detected if event.hash_detected else None
    baseline_status = "absent" if hash_value is None else "present"

    command_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "type": "baseline_update",
        "command_id": command_id,
        "event_id": event.id,
        "source_event_id": event.event_id,
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
    _record_published_command(
        session, event.agent_id, "baseline_update", command_id, data,
        event_id=event.id, ruleset_version=ruleset_version,
    )

    log.info(
        "streams.actions.baseline_update_enqueued",
        event_id=event.id,
        agent_id=event.agent_id,
        ruleset_version=ruleset_version,
        command_id=command_id,
    )


def enqueue_restore_file(
    session: Session,
    event: Event,
) -> None:
    """
    Encola el comando `restore_file` en el outbox, firmado con HMAC-SHA256.

    Payload: type, command_id, event_id, target_agent_id, path, issued_at, signature.
    No incluye hash ni ruleset_version (según spec).

    MUST llamarse ANTES de `db.commit()` (D37/RN-131) — ver docstring del módulo.
    """
    secret = _get_agent_secret(session, event.agent_id)

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
    _record_published_command(session, event.agent_id, "restore_file", command_id, data, event_id=event.id)

    log.info(
        "streams.actions.restore_file_enqueued",
        event_id=event.id,
        agent_id=event.agent_id,
        command_id=command_id,
    )


def enqueue_quarantine_file(
    session: Session,
    event: Event,
) -> None:
    """
    Encola el comando `quarantine_file` en el outbox, firmado con HMAC-SHA256.

    Payload: type, command_id, event_id, target_agent_id, path, issued_at, signature.
    No incluye hash ni ruleset_version (según spec).

    MUST llamarse ANTES de `db.commit()` (D37/RN-131) — ver docstring del módulo.
    """
    secret = _get_agent_secret(session, event.agent_id)

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
    _record_published_command(session, event.agent_id, "quarantine_file", command_id, data, event_id=event.id)

    log.info(
        "streams.actions.quarantine_file_enqueued",
        event_id=event.id,
        agent_id=event.agent_id,
        command_id=command_id,
    )
