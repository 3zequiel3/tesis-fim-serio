"""
Lógica de negocio para aprobación y rechazo de eventos FIM (C13, D37/RN-131).

Expone: _approve_single, _reject_single, approve_bulk, reject_bulk.

Orden de operaciones en approve (D37/RN-131 — reemplaza el orden post-commit
de FIX-02, ver "Inversión de FIX-02" abajo):
  1. Verificar confirm_absent si hash is None (antes del UPDATE).
  2. UPDATE optimista sobre events (status, version, resolved_at, resolved_by).
  3. flush + refresh.
  4. increment_ruleset_version.
  5. Upsert en baseline_entries.
  6. Escribir audit_log.
  7. Encolar baseline_update en el outbox (`enqueue_baseline_update`) — MISMA
     transacción que la mutación del evento.
  8. commit.
  9. refresh.
  10. Intento inmediato best-effort de `publish_pending_commands` (no agrega
      la latencia del poller al camino feliz; si Valkey está caído, el
      comando queda `pending` y el background task lo reintenta).

Orden de operaciones en reject (D37/RN-131):
  1. UPDATE optimista sobre events.
  2. flush + refresh.
  3. Consultar baseline_entry.
  4. Escribir audit_log.
  5. Encolar restore_file o quarantine_file en el outbox, salvo no-op de
     baseline `absent` (RN-74) — MISMA transacción que la mutación.
  6. commit.
  7. refresh.
  8. Intento inmediato best-effort de `publish_pending_commands`.

Inversión de FIX-02: antes, el comando se publicaba (XADD síncrono) recién
DESPUÉS del `commit`, para que el agente no recibiera un comando de una
transacción que después se revertía. Con el outbox esa protección la da la
**atomicidad**: la fila `PublishedCommand` vive o muere con la transacción
del evento. Si se revierte, no queda nada que publicar; si comitea, el
comando está garantizado en el outbox y el despachador (`rules.service.
publish_pending_commands`, ya genérico y ya corrido por `outbox_publisher_task`
en el lifespan) lo entrega con reintento — más fuerte que la garantía previa,
que dependía de un `XADD` síncrono sin outbox. Ver D-10 del design de
`stream-ack-durability`.

`_get_agent_secret` (actions/streams.py) ya NO atrapa su propio `ValueError`:
la excepción SHALL propagarse y revertir la transacción completa — un
agente sin `shared_secret_hex` deja de poder terminar un evento sin emitir
comando (el bug que motivó esta change).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from app.modules.agents.models import Agent, BaselineEntry, BaselineStatus
from app.modules.audit.models import AuditLog
from app.modules.events.models import Event, EventStatus
from app.modules.rules.service import increment_ruleset_version as _increment_ruleset_version
from app.modules.actions.schemas import RejectAction

log = structlog.get_logger()


# ── Excepciones de dominio ────────────────────────────────────────────────────


class ConflictError(Exception):
    """El UPDATE optimista no afectó ninguna fila (versión incorrecta o evento no-pending)."""
    def __init__(self, event_id: int) -> None:
        self.event_id = event_id
        super().__init__(f"conflict on event {event_id}")


class AbsentConfirmationRequired(Exception):
    """El evento tiene hash=None y confirm_absent no fue True."""
    def __init__(self, event_id: int) -> None:
        self.event_id = event_id
        super().__init__(f"absent_confirmation_required for event {event_id}")


# ── Helpers internos ──────────────────────────────────────────────────────────
#
# El incremento de RulesetVersion (M6) está unificado en
# `rules.service.increment_ruleset_version` (UPDATE ... RETURNING atómico) y
# se reutiliza acá bajo el alias `_increment_ruleset_version` para no tocar
# los call-sites de approve/reject. No debe reimplementarse localmente.


def _get_event(session: Session, event_id: int) -> Event | None:
    return session.exec(select(Event).where(Event.id == event_id)).first()


def _get_agent(session: Session, agent_id: str) -> Agent | None:
    return session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()


def _get_baseline_entry(session: Session, path: str, agent_id: str) -> BaselineEntry | None:
    return session.exec(
        select(BaselineEntry).where(
            BaselineEntry.path == path,
            BaselineEntry.agent_id == agent_id,
        )
    ).first()


def upsert_baseline_entry(
    session: Session,
    path: str,
    agent_id: str,
    hash_value: str | None,
    baseline_status: BaselineStatus,
    ruleset_version: int,
) -> None:
    """
    Upsert de BaselineEntry por (path, agent_id). Pública (C36): reutilizada
    por `command_ack_consumer.py` para cerrar D1/RN-104 (el ack exitoso de
    un `baseline_update` refleja el hash aprobado en `baseline_entries`).
    """
    entry = _get_baseline_entry(session, path, agent_id)
    if entry is None:
        entry = BaselineEntry(
            path=path,
            agent_id=agent_id,
            hash=hash_value,
            status=baseline_status,
            last_updated=datetime.now(timezone.utc),
            ruleset_version=ruleset_version,
        )
        session.add(entry)
    else:
        entry.hash = hash_value
        entry.status = baseline_status
        entry.last_updated = datetime.now(timezone.utc)
        entry.ruleset_version = ruleset_version
        session.add(entry)


def _write_audit(
    session: Session,
    user_id: int,
    action: str,
    event_id: int,
    details: dict[str, Any] | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        target_type="event",
        target_id=event_id,
        detail=json.dumps(details) if details else None,
    )
    session.add(entry)


# ── Approve single ────────────────────────────────────────────────────────────


def _approve_single(
    db: Session,
    valkey_client: Any,
    event_id: int,
    version: int,
    confirm_absent: bool,
    user_id: int,
) -> Event:
    """
    Aprueba un evento pending con optimistic locking.

    Raises:
        AbsentConfirmationRequired: si hash is None y confirm_absent is False.
        ConflictError: si el UPDATE no afecta ninguna fila.
        ValueError: si el agente destino no tiene shared_secret_hex — la
            transacción NO se comitea (D37/RN-131, ver docstring del módulo).
    """
    from app.modules.actions.streams import enqueue_baseline_update
    from app.modules.rules.service import publish_pending_commands

    # 1. Leer el evento para detectar hash None ANTES del UPDATE (no modifica estado)
    # En el modelo Event, hash_detected es str; cadena vacía "" indica archivo ausente (D-C13-04).
    event = _get_event(db, event_id)
    if event is None:
        raise ConflictError(event_id)

    # Verificar ausencia antes del UPDATE (D-C13-04)
    # hash vacío o None = archivo eliminado/ausente
    hash_value: str | None = event.hash_detected if event.hash_detected else None
    if hash_value is None and not confirm_absent:
        raise AbsentConfirmationRequired(event_id)

    # 2. UPDATE optimista
    now = datetime.now(timezone.utc)
    stmt = (
        sa_update(Event)
        .where(
            Event.id == event_id,
            Event.version == version,
            Event.status == EventStatus.pending,
        )
        .values(
            status=EventStatus.approved,
            version=version + 1,
            resolved_at=now,
            resolved_by=user_id,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise ConflictError(event_id)

    # 3. Refrescar event para obtener datos actualizados
    db.flush()
    db.refresh(event)

    # 4. Incrementar ruleset_version
    new_version = _increment_ruleset_version(db)

    # 5. Upsert baseline_entries
    baseline_status = BaselineStatus.absent if hash_value is None else BaselineStatus.present
    upsert_baseline_entry(db, event.path, event.agent_id, hash_value, baseline_status, new_version)

    # 6. Audit log
    _write_audit(db, user_id, "approve", event_id, {"version": version})

    # 7. Encolar baseline_update en el outbox — MISMA transacción que la
    #    mutación del evento (D37/RN-131). Si el agente no tiene
    #    shared_secret, ValueError se propaga acá y revierte todo lo de
    #    arriba (nada se comitea).
    enqueue_baseline_update(db, event, new_version)

    # 8. Commit
    db.commit()

    # 9. Refresh post-commit
    db.refresh(event)

    # 10. Intento inmediato best-effort de publicación del outbox (D37/RN-131):
    #     no agrega la latencia del poller al camino feliz. Si Valkey está
    #     caído, el comando queda `pending` y el background task lo reintenta.
    publish_pending_commands(db, valkey_client)

    log.info("service.actions.approve", event_id=event_id, user_id=user_id)
    return event


# ── Reject single ─────────────────────────────────────────────────────────────


def _reject_single(
    db: Session,
    valkey_client: Any,
    event_id: int,
    version: int,
    action: RejectAction,
    user_id: int,
) -> tuple[Event, bool]:
    """
    Rechaza un evento pending con optimistic locking.

    Returns:
        tuple (Event, baseline_absent) — M8: baseline_absent es True cuando
        el no-op de baseline "absent" ocurrió (RN-74). No altera el
        comportamiento del no-op, solo lo hace observable para el caller.

    Raises:
        ConflictError: si el UPDATE no afecta ninguna fila.
        ValueError: si el agente destino no tiene shared_secret_hex — la
            transacción NO se comitea (D37/RN-131, ver docstring del módulo).
    """
    from app.modules.actions.streams import enqueue_quarantine_file, enqueue_restore_file
    from app.modules.rules.service import publish_pending_commands

    event = _get_event(db, event_id)
    if event is None:
        raise ConflictError(event_id)

    # 1. UPDATE optimista
    now = datetime.now(timezone.utc)
    stmt = (
        sa_update(Event)
        .where(
            Event.id == event_id,
            Event.version == version,
            Event.status == EventStatus.pending,
        )
        .values(
            status=EventStatus.rejected,
            version=version + 1,
            resolved_at=now,
            resolved_by=user_id,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise ConflictError(event_id)

    # 2. flush + refresh
    db.flush()
    db.refresh(event)

    # 3. Consultar baseline_entry (dentro de la transacción, antes del commit)
    baseline_entry = _get_baseline_entry(db, event.path, event.agent_id)
    baseline_absent = baseline_entry is not None and baseline_entry.status == BaselineStatus.absent

    # 4. Audit log
    _write_audit(db, user_id, "reject", event_id, {"version": version, "action": action.value})

    # 5. Encolar restore_file/quarantine_file en el outbox — MISMA transacción
    #    que la mutación del evento (D37/RN-131), salvo el no-op de baseline
    #    absent (RN-74), que no encola ningún comando.
    if baseline_absent:
        log.warning(
            "service.actions.reject.baseline_absent_noop",
            event_id=event_id,
            path=event.path,
        )
    else:
        if action == RejectAction.restore:
            enqueue_restore_file(db, event)
        else:
            enqueue_quarantine_file(db, event)

    # 6. Commit
    db.commit()

    # 7. Refresh post-commit
    db.refresh(event)

    # 8. Intento inmediato best-effort de publicación del outbox (D37/RN-131).
    publish_pending_commands(db, valkey_client)

    log.info("service.actions.reject", event_id=event_id, user_id=user_id, action=action.value)
    return event, baseline_absent


# ── Bulk operations ───────────────────────────────────────────────────────────


def approve_bulk(
    db: Session,
    valkey_client: Any,
    items: list[dict[str, Any]],
    user_id: int,
) -> dict[str, Any]:
    """
    Aprueba múltiples eventos de forma independiente.
    Error en un ítem no aborta el resto.
    Retorna {"succeeded": [...], "failed": [...]}.
    """
    succeeded: list[int] = []
    failed: list[dict[str, Any]] = []

    for item in items:
        event_id = item["event_id"]
        try:
            _approve_single(
                db,
                valkey_client,
                event_id=event_id,
                version=item["version"],
                confirm_absent=item.get("confirm_absent", False),
                user_id=user_id,
            )
            succeeded.append(event_id)
        except AbsentConfirmationRequired:
            db.rollback()
            failed.append({"event_id": event_id, "reason": "absent_confirmation_required"})
        except ConflictError:
            db.rollback()
            failed.append({"event_id": event_id, "reason": "conflict"})
        except Exception as exc:
            db.rollback()
            log.error("service.actions.approve_bulk.unexpected", event_id=event_id, error=str(exc))
            failed.append({"event_id": event_id, "reason": "internal_error"})

    return {"succeeded": succeeded, "failed": failed}


def reject_bulk(
    db: Session,
    valkey_client: Any,
    items: list[dict[str, Any]],
    user_id: int,
) -> dict[str, Any]:
    """
    Rechaza múltiples eventos de forma independiente.
    Error en un ítem no aborta el resto.
    Retorna {"succeeded": [...], "failed": [...], "baseline_absent": {event_id: bool}}.
    M8: baseline_absent mapea cada evento exitoso a si hubo no-op por baseline absent.
    """
    succeeded: list[int] = []
    failed: list[dict[str, Any]] = []
    baseline_absent_by_event: dict[int, bool] = {}

    for item in items:
        event_id = item["event_id"]
        try:
            action = RejectAction(item["action"])
            _, baseline_absent = _reject_single(
                db,
                valkey_client,
                event_id=event_id,
                version=item["version"],
                action=action,
                user_id=user_id,
            )
            succeeded.append(event_id)
            baseline_absent_by_event[event_id] = baseline_absent
        except ConflictError:
            db.rollback()
            failed.append({"event_id": event_id, "reason": "conflict"})
        except Exception as exc:
            db.rollback()
            log.error("service.actions.reject_bulk.unexpected", event_id=event_id, error=str(exc))
            failed.append({"event_id": event_id, "reason": "internal_error"})

    return {"succeeded": succeeded, "failed": failed, "baseline_absent": baseline_absent_by_event}
