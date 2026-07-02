"""
Lógica de negocio del dominio de eventos (Change 11).

Expone: validate_transition, ingest_event, compact_chain, retention_task.
Reutilizable por el consumer Valkey y el HTTP handler de approve/reject (C13).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from app.core.database import engine
from app.modules.audit.models import AuditLog
from app.modules.events.models import Event, EventStatus

log = structlog.get_logger()

TERMINAL_STATUSES: frozenset[EventStatus] = frozenset(
    {
        EventStatus.approved,
        EventStatus.rejected,
        EventStatus.auto_restored,
        EventStatus.quarantined,
        EventStatus.alert_only,
        EventStatus.superseded,
    }
)

# RN-72: solo pending tiene out-edges; todos los demás son terminales.
VALID_TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.pending: {EventStatus.approved, EventStatus.rejected, EventStatus.superseded},
    EventStatus.approved: set(),
    EventStatus.rejected: set(),
    EventStatus.auto_restored: set(),
    EventStatus.quarantined: set(),
    EventStatus.alert_only: set(),
    EventStatus.superseded: set(),
}

_MAX_CHAIN = 10
_RETENTION_DAYS = 30


class InvalidTransitionError(Exception):
    def __init__(self, from_status: EventStatus, to_status: EventStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status} → {to_status}")


def validate_transition(from_status: EventStatus, to_status: EventStatus) -> None:
    """Lanza InvalidTransitionError si la transición no está en VALID_TRANSITIONS."""
    if to_status not in VALID_TRANSITIONS.get(from_status, set()):
        raise InvalidTransitionError(from_status, to_status)


def get_pending_event_for_path(session: Session, path: str) -> Event | None:
    """Retorna el evento pending más reciente para un path, o None."""
    return session.exec(
        select(Event)
        .where(Event.path == path, Event.status == EventStatus.pending)
        .order_by(Event.created_at.desc())
    ).first()


def mark_superseded(session: Session, event_id: int, version: int) -> bool:
    """
    UPDATE optimista: marca el evento como superseded solo si version coincide y status=pending.
    Retorna True si afectó 1 fila, False si hubo carrera (0 filas).
    """
    stmt = (
        sa_update(Event)
        .where(
            Event.id == event_id,
            Event.version == version,
            Event.status == EventStatus.pending,
        )
        .values(status=EventStatus.superseded, version=version + 1)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    return result.rowcount == 1


def compact_chain(session: Session, path: str) -> None:
    """
    Si hay >_MAX_CHAIN eventos superseded para el path, elimina los más antiguos
    excluyendo los referenciados en audit_log. Se llama en la misma transacción
    que ingest_event (RN-98).
    """
    superseded = session.exec(
        select(Event)
        .where(Event.path == path, Event.status == EventStatus.superseded)
        .order_by(Event.created_at.asc())
    ).all()

    if len(superseded) <= _MAX_CHAIN:
        return

    protected_ids: set[int] = {
        r
        for r in session.exec(
            select(AuditLog.target_id).where(
                AuditLog.target_type == "event",
                AuditLog.target_id.isnot(None),
            )
        ).all()
        if r is not None
    }

    excess = len(superseded) - _MAX_CHAIN
    deleted = 0
    for evt in superseded:
        if deleted >= excess:
            break
        if evt.id not in protected_ids:
            session.delete(evt)
            deleted += 1


def ingest_event(
    event_data: dict[str, Any],
    received_at: datetime,
    detected_at: datetime,
) -> Event | None:
    """
    Ingesta un evento válido:
    1. Busca pending para el mismo path.
    2. Si existe → mark_superseded (optimistic); si carrera → retorna None.
    3. Crea el nuevo evento con parent_event_id si hubo superseded.
    4. Llama compact_chain en la misma transacción.
    """
    path = event_data.get("path", "")
    status_str = event_data.get("status", "pending")
    try:
        status = EventStatus(status_str)
    except ValueError:
        status = EventStatus.pending

    with Session(engine) as session:
        pending = get_pending_event_for_path(session, path)
        parent_event_id: int | None = None

        if pending is not None and pending.id is not None:
            validate_transition(pending.status, EventStatus.superseded)
            success = mark_superseded(session, pending.id, pending.version)
            if not success:
                log.warning("service.superseded_race", path=path, pending_id=pending.id)
                # FIX-03 (D25, RN-121): re-consultar si el pending fue aprobado/rechazado
                # concurrentemente (en ese caso no hay pending activo → insertar independiente)
                still_pending = get_pending_event_for_path(session, path)
                if still_pending is not None:
                    # Todavía hay un pending activo → skip legítimo
                    log.warning("service.superseded_race.still_pending", path=path)
                    return None
                # No hay pending → continuar inserción como evento independiente
                log.info("service.superseded_race.insert_independent", path=path)
                # parent_event_id ya es None; el flujo continúa normalmente
            else:
                parent_event_id = pending.id

        event = Event(
            event_id=event_data.get("event_id", ""),
            agent_id=event_data.get("agent_id", ""),
            path=path,
            hash_detected=event_data.get("hash_detected") or "",
            status=status,
            parent_event_id=parent_event_id,
            process_pid=event_data.get("process_pid"),
            process_uid=event_data.get("process_uid"),
            process_exe=event_data.get("process_exe"),
            detected_at=detected_at,
            received_at=received_at,
            # D33/RN-127 (C39): .get() tolerante — un agente viejo sin estas keys
            # ingiere igual, con defaults false/None.
            is_symlink=event_data.get("is_symlink", False),
            symlink_target=event_data.get("symlink_target"),
        )
        session.add(event)
        session.flush()

        if parent_event_id is not None:
            compact_chain(session, path)

        session.commit()
        session.refresh(event)
        return event


async def retention_task() -> None:
    """
    Tarea asyncio periódica: elimina eventos terminales con más de 30 días
    que no están referenciados en audit_log (RN-98).
    """
    while True:
        await asyncio.sleep(3600)
        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        with Session(engine) as session:
            protected_ids: set[int] = {
                r
                for r in session.exec(
                    select(AuditLog.target_id).where(
                        AuditLog.target_type == "event",
                        AuditLog.target_id.isnot(None),
                    )
                ).all()
                if r is not None
            }

            q = select(Event).where(
                Event.status.in_(list(TERMINAL_STATUSES)),
                Event.created_at < cutoff,
            )
            if protected_ids:
                q = q.where(Event.id.notin_(protected_ids))

            to_delete = session.exec(q).all()
            for evt in to_delete:
                session.delete(evt)
            if to_delete:
                session.commit()
                log.info("service.retention_run", deleted=len(to_delete))
