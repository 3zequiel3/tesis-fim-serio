"""
Endpoints REST del dominio de eventos (Change 11).

GET /events  — lista paginada con filtros
GET /events/{event_id} — detalle de un evento
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.deps import require_full_access
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import PublishedCommand, RuleSeverity

router = APIRouter(prefix="/events", tags=["events"])


class EventOut(BaseModel):
    id: int
    event_id: str
    agent_id: str
    # D51/RN-145: vocabulario canónico que el agente ya emite (RN-71), sin
    # validación contra enum — mismo criterio que action/action_error.
    event_type: str
    # D51/RN-145: nulo para eventos que no hablan de ningún archivo concreto,
    # como detection_gap (D50/RN-144). path_prefix no matchea un NULL, así
    # que un evento sin ruta queda fuera de una búsqueda por prefijo.
    path: str | None
    hash_detected: str
    status: EventStatus
    # D34/RN-128 (C38): severidad persistida al ingerir (snapshot, D-C15-01).
    severity: RuleSeverity = RuleSeverity.low
    parent_event_id: int | None
    version: int
    process_pid: int | None
    process_uid: int | None
    process_exe: str | None
    detected_at: datetime
    received_at: datetime
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: int | None
    # C36 (D30/RN-124): estado de ejecución del comando asociado, indicador
    # secundario — NO forma parte de la máquina de estados del evento (RN-72).
    ack_status: str | None = None
    # D33/RN-127 (C39): metadato de symlink-as-object, columnas directas de Event.
    is_symlink: bool = False
    symlink_target: str | None = None
    # D35/RN-129 (C40): true cuando la acción automática (auto_restore/quarantine)
    # falló en el agente. Ortogonal al status — ver Event.action_failed.
    action_failed: bool = False
    # D36/RN-130 (C41): causa del fallo de la acción automática, puramente
    # explicativa — ver Event.action_error. Aditivo, sin filtro nuevo.
    action_error: str | None = None

    model_config = {"from_attributes": True}


class EventDetailOut(EventOut):
    """Detalle con evidencia textual acotada; el listado no expone el diff."""

    hash_expected: str | None = None
    diff_text: str | None = None


class PaginatedEventsOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[EventOut]


@router.get("", response_model=PaginatedEventsOut)
async def list_events(
    status_filter: Annotated[list[EventStatus], Query(alias="status")] = [],
    # D34/RN-128 (C38): filtro repetible por severidad, mismo patrón que status.
    severity_filter: Annotated[list[RuleSeverity], Query(alias="severity")] = [],
    path_prefix: str | None = Query(default=None),
    # D39/RN-133: date_from/date_to se interpretan como INSTANTES, no como hora
    # de pared del servidor. Un valor con desfase (`+00:00`, `-03:00`, `Z`) se
    # respeta tal cual; uno sin desfase se interpreta como UTC explícitamente
    # (_as_utc_instant), nunca en la zona local del proceso — ver D-4 del design
    # de timestamps-timezone-aware: la conversión de hora local ya ocurrió en
    # el frontend antes de construir la petición HTTP.
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    include_superseded: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    _user: User = Depends(require_full_access),
) -> PaginatedEventsOut:
    q = select(Event)

    if not include_superseded:
        q = q.where(Event.status != EventStatus.superseded)

    if status_filter:
        q = q.where(Event.status.in_(status_filter))

    if severity_filter:
        q = q.where(Event.severity.in_(severity_filter))

    if path_prefix:
        q = q.where(Event.path.startswith(path_prefix))

    if date_from:
        q = q.where(Event.created_at >= _as_utc_instant(date_from))

    if date_to:
        q = q.where(Event.created_at <= _as_utc_instant(date_to))

    # FIX-04: paginación SQL real con COUNT subquery + LIMIT/OFFSET (sin full table scan)
    count_q = select(func.count()).select_from(q.subquery())
    total = session.exec(count_q).one()

    items_q = q.order_by(Event.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(session.exec(items_q).all())

    ack_map = _get_ack_status_map(session, [e.id for e in items if e.id is not None])
    return PaginatedEventsOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_event_out(e, ack_map) for e in items],
    )


@router.get("/{event_id}", response_model=EventDetailOut)
async def get_event(
    event_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_full_access),
) -> EventDetailOut:
    event = session.exec(select(Event).where(Event.id == event_id)).first()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    ack_map = _get_ack_status_map(session, [event.id] if event.id is not None else [])
    return _to_event_detail_out(event, ack_map)


# ── Helpers — filtros de fecha (D39/RN-133) ──────────────────────────────────


def _as_utc_instant(value: datetime) -> datetime:
    """
    Interpreta un datetime de filtro como instante UTC.

    Un valor que ya trae zona (aware) se preserva tal cual. Uno sin zona
    (naive) se interpreta como UTC de forma explícita, NUNCA en la zona local
    del proceso del servidor — así el endpoint mantiene un significado
    definido para links existentes sin depender de la configuración de la
    sesión de PostgreSQL (D39/RN-133).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ── Helpers — indicador secundario de ejecución (C36, D30/RN-124) ───────────────


def _get_ack_status_map(session: Session, event_ids: list[int]) -> dict[int, str]:
    """
    Retorna {event_id: ack_status} usando el PublishedCommand más reciente
    (mayor id) asociado a cada evento, con ack_status no nulo. No altera
    Event ni su máquina de estados (RN-72) — es un lookup de solo lectura.
    """
    if not event_ids:
        return {}
    rows = session.exec(
        select(PublishedCommand)
        .where(PublishedCommand.event_id.in_(event_ids))  # type: ignore[union-attr]
        .order_by(PublishedCommand.id.desc())
    ).all()
    result: dict[int, str] = {}
    for row in rows:
        if row.event_id is not None and row.event_id not in result and row.ack_status is not None:
            result[row.event_id] = row.ack_status
    return result


def _to_event_out(event: Event, ack_map: dict[int, str]) -> EventOut:
    out = EventOut.model_validate(event)
    out.ack_status = ack_map.get(event.id) if event.id is not None else None
    return out


def _to_event_detail_out(event: Event, ack_map: dict[int, str]) -> EventDetailOut:
    out = EventDetailOut.model_validate(event)
    out.ack_status = ack_map.get(event.id) if event.id is not None else None
    return out
