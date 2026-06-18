"""
Endpoints REST del dominio de eventos (Change 11).

GET /events  — lista paginada con filtros
GET /events/{event_id} — detalle de un evento
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.deps import get_current_user
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus

router = APIRouter(prefix="/events", tags=["events"])


class EventOut(BaseModel):
    id: int
    event_id: str
    agent_id: str
    path: str
    hash_detected: str
    status: EventStatus
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

    model_config = {"from_attributes": True}


class PaginatedEventsOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[EventOut]


@router.get("", response_model=PaginatedEventsOut)
async def list_events(
    status_filter: Annotated[list[EventStatus], Query(alias="status")] = [],
    path_prefix: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    include_superseded: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> PaginatedEventsOut:
    q = select(Event)

    if not include_superseded:
        q = q.where(Event.status != EventStatus.superseded)

    if status_filter:
        q = q.where(Event.status.in_(status_filter))

    if path_prefix:
        q = q.where(Event.path.startswith(path_prefix))

    if date_from:
        q = q.where(Event.created_at >= date_from)

    if date_to:
        q = q.where(Event.created_at <= date_to)

    all_events = session.exec(q).all()
    total = len(all_events)

    offset = (page - 1) * page_size
    items = all_events[offset : offset + page_size]

    return PaginatedEventsOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[EventOut.model_validate(e) for e in items],
    )


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> EventOut:
    event = session.exec(select(Event).where(Event.id == event_id)).first()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return EventOut.model_validate(event)
