"""
Router de alertas para FIM Platform (C15 + C16).

Endpoints:
  GET  /alerts                — listado paginado completo con filtros (C16)
  POST /alerts/stream-ticket  — emite ticket SSE de un solo uso (D64/RN-158)
  GET  /alerts/stream         — stream SSE de alertas nuevas, autenticado
                                 por ticket (contrato C16, D64/RN-158)
  GET  /alerts/failed         — DLQ (C15)
  POST /alerts/{id}/retry     — reintento desde DLQ (C15)
  DELETE /alerts/{id}         — descartar de DLQ (C15)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator, Literal

import anyio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_session
from app.core.deps import require_admin
from app.core.rate_limit import check_api_rate_limit
from app.core.valkey import get_async_valkey_client
from app.modules.alerts.contract import action_taken_for
from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.service import (
    count_failed_alerts,
    delete_alert,
    list_alerts,
    list_failed_alerts,
    retry_alert,
)
from app.modules.alerts.stream import alerts_broadcaster
from app.modules.alerts.stream_ticket import (
    SSE_TICKET_TTL_SECONDS,
    consume_ticket,
    issue_ticket,
)
from app.modules.auth.models import User
from app.modules.events.models import Event

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Schemas de respuesta ──────────────────────────────────────────────────────

AlertDerivedStatus = Literal["pending", "delivered", "failed"]


class AlertResponse(BaseModel):
    id: int
    event_id: int
    severity: AlertSeverity
    channel: AlertChannel | None
    delivered_at: datetime | None
    failed_at: datetime | None
    last_error: str | None
    retry_count: int
    created_at: datetime
    # C38 (FIX-02): estado derivado de delivered_at/failed_at — misma semántica
    # que el filtro filter_status de list_alerts. Antes solo se computaba
    # server-side para filtrar y la columna "Estado" del frontend quedaba vacía.
    status: AlertDerivedStatus
    # US-19: path y acción tomada del evento asociado — la alerta en sí no los
    # persiste (RN-107/D6), así que se derivan con un join a `events` en el
    # router, sin migración de esquema. `None` cuando el evento no tiene acción
    # tomada todavía (p. ej. `pending`) o no se encontró (dato huérfano).
    path: str | None
    action_taken: str | None


def _derive_alert_status(alert: Alert) -> AlertDerivedStatus:
    """delivered_at ⊃ delivered; failed_at (sin delivered) ⊃ failed; resto pending."""
    if alert.delivered_at is not None:
        return "delivered"
    if alert.failed_at is not None:
        return "failed"
    return "pending"


def _to_alert_response(alert: Alert, event: Event | None) -> AlertResponse:
    return AlertResponse(
        id=alert.id,  # type: ignore[arg-type]
        event_id=alert.event_id,
        severity=alert.severity,
        channel=alert.channel,
        delivered_at=alert.delivered_at,
        failed_at=alert.failed_at,
        last_error=alert.last_error,
        retry_count=alert.retry_count,
        created_at=alert.created_at,
        status=_derive_alert_status(alert),
        path=event.path if event else None,
        action_taken=action_taken_for(event.status) if event else None,
    )


def _events_by_id(session: Session, alerts: list[Alert]) -> dict[int, Event]:
    """Batch-fetch the events referenced by a page of alerts (US-19, D6/RN-107 join)."""
    event_ids = {a.event_id for a in alerts}
    if not event_ids:
        return {}
    events = session.exec(select(Event).where(Event.id.in_(event_ids))).all()  # type: ignore[attr-defined]
    return {e.id: e for e in events}


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int


class AlertPaginatedResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    page: int
    size: int


# ── Auth via ticket de un solo uso para SSE (D64/RN-158) ──────────────────────
#
# EventSource no admite headers custom, así que el contrato C16 no puede
# autenticar con Authorization: Bearer. Antes de este change el JWT de acceso
# viajaba completo en ?token=, quedando expuesto en logs de acceso y en el
# historial del navegador durante toda su vigencia. Ahora GET /alerts/stream
# exige un ticket opaco de un solo uso (?ticket=), emitido por
# POST /alerts/stream-ticket y consumido atómicamente (GETDEL) — ver
# app.modules.alerts.stream_ticket.

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
)


class StreamTicketResponse(BaseModel):
    ticket: str
    expires_in: int


async def _require_admin_from_ticket(
    ticket: str | None = Query(default=None),
    session: Session = Depends(get_session),
    async_valkey_client=Depends(get_async_valkey_client),
) -> User:
    """
    Dependencia SSE del stream (D64/RN-158): consume el ticket de un solo uso
    con GETDEL y exige rol admin. Un ticket ausente, inexistente, vencido o ya
    consumido responde 401 explícito (antes, sin `ticket`, FastAPI respondía
    422 por validación del `token` requerido — divergencia frente a la spec,
    corregida acá). `?token=<jwt>` sin `?ticket=` ya no autentica: el parámetro
    `token` desapareció de la firma, así que cae en "ticket ausente" ⇒ 401.
    """
    if ticket is None:
        raise _credentials_exc

    user_id = await consume_ticket(ticket, async_valkey_client)
    if user_id is None:
        raise _credentials_exc

    user = session.exec(select(User).where(User.id == user_id)).first()
    if user is None or not user.is_active:
        raise _credentials_exc

    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")

    await check_api_rate_limit(user_id)

    return user


# ── Generador SSE ─────────────────────────────────────────────────────────────

# Keepalive interval in seconds. Module-level so tests can patch it via
# unittest.mock.patch.object if needed without touching the generator body.
_KEEPALIVE_INTERVAL: float = 15.0


def _alert_to_dict(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "event_id": alert.event_id,
        "severity": alert.severity.value,
        "status": _derive_alert_status(alert),
        "channel": alert.channel.value if alert.channel else None,
        "delivered_at": alert.delivered_at.isoformat() if alert.delivered_at else None,
        "failed_at": alert.failed_at.isoformat() if alert.failed_at else None,
        "last_error": alert.last_error,
        "retry_count": alert.retry_count,
        "created_at": alert.created_at.isoformat(),
    }


async def _alert_sse_generator(
    request: Request,
    session: Session,
) -> AsyncGenerator[dict[str, Any], None]:
    # 1. Replay via Last-Event-ID (D-SSE-3), o su equivalente en la URL
    # last_event_id (D64/RN-158, D-EV-6): EventSource no permite fijar el
    # header Last-Event-ID en la URL inicial de una conexión abierta a mano
    # (solo lo reenvía en su propia reconexión nativa, que este change
    # desactiva — ver useAlertsSSE.ts), así que el frontend lo pasa como query
    # param en su lugar. El header prevalece si ambos están presentes.
    # FIX-01: la sesión se usa SÓLO para el replay y se cierra explícitamente
    # antes de entrar al bucle SSE, para no retener una conexión del pool
    # durante el lifetime de la conexión SSE (que puede ser horas).
    last_id_str = request.headers.get("last-event-id")
    if last_id_str is None:
        last_id_str = request.query_params.get("last_event_id")
    try:
        if last_id_str is not None:
            try:
                last_id = int(last_id_str)
            except ValueError:
                last_id = 0

            missed_stmt = select(Alert).where(Alert.id > last_id).order_by(Alert.id.asc())  # type: ignore[arg-type]
            missed = list(session.exec(missed_stmt).all())
            for alert in missed:
                yield {
                    "event": "alert",
                    "id": str(alert.id),
                    "data": json.dumps(_alert_to_dict(alert)),
                }
    finally:
        # FIX-01: liberar sesión DB antes del bucle en tiempo real
        session.close()

    # 2. Streaming en tiempo real desde el broadcaster (D-SSE-1)
    #
    # anyio.move_on_after is used instead of asyncio.wait_for for the keepalive
    # timeout because asyncio.wait_for creates an internal asyncio Task that
    # breaks anyio cancel-scope ownership — causing RuntimeError when the ASGI
    # response is cancelled on client disconnect.
    queue: asyncio.Queue[dict[str, Any]] = alerts_broadcaster.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break
            alert_dict: dict[str, Any] | None = None
            with anyio.move_on_after(_KEEPALIVE_INTERVAL) as cancel_scope:
                alert_dict = await queue.get()
            if cancel_scope.cancelled_caught:
                # Keepalive cada 15s para prevenir corte de proxies (D-SSE-4)
                yield {"comment": "keepalive"}
            else:
                assert alert_dict is not None
                yield {
                    "event": "alert",
                    "id": str(alert_dict["id"]),
                    "data": json.dumps(alert_dict),
                }
    finally:
        alerts_broadcaster.unsubscribe(queue)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=AlertPaginatedResponse)
async def list_all_alerts(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 50,
    filter_status: str | None = Query(default=None, alias="status"),
    severity: AlertSeverity | None = Query(default=None),
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> AlertPaginatedResponse:
    """Listado paginado de todas las alertas con filtros opcionales por estado y severidad."""
    items, total = list_alerts(session, status=filter_status, severity=severity, page=page, size=size)
    event_map = _events_by_id(session, items)
    return AlertPaginatedResponse(
        items=[_to_alert_response(a, event_map.get(a.event_id)) for a in items],
        total=total,
        page=page,
        size=size,
    )


@router.post("/stream-ticket", response_model=StreamTicketResponse)
async def create_stream_ticket(
    _admin: User = Depends(require_admin),
    async_valkey_client=Depends(get_async_valkey_client),
) -> StreamTicketResponse:
    """
    Emite un ticket opaco de un solo uso para GET /alerts/stream (D64/RN-158).

    Reutiliza `require_admin` (JWT en Authorization, scope completo, activo,
    admin, rate limit). El valor del ticket no se loguea.
    """
    ticket = await issue_ticket(_admin.id, async_valkey_client)  # type: ignore[arg-type]
    return StreamTicketResponse(ticket=ticket, expires_in=SSE_TICKET_TTL_SECONDS)


@router.get("/stream")
async def stream_alerts(
    request: Request,
    session: Session = Depends(get_session),
    _admin: User = Depends(_require_admin_from_ticket),
) -> EventSourceResponse:
    """
    Stream SSE de alertas nuevas (contrato C16). Auth via ticket de un solo
    uso `?ticket=<ticket>` emitido por POST /alerts/stream-ticket (D64/RN-158)
    — ya no acepta un JWT en `?token=`. La continuidad tras un corte usa el
    header `Last-Event-ID` o, como equivalente en la URL, `?last_event_id=`
    (D-EV-6).
    """
    return EventSourceResponse(_alert_sse_generator(request, session))


@router.get("/failed", response_model=AlertListResponse)
async def get_failed_alerts(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> AlertListResponse:
    """Lista alertas con failed_at NOT NULL y delivered_at IS NULL, ordenadas por failed_at DESC."""
    alerts = list_failed_alerts(session)
    event_map = _events_by_id(session, alerts)
    return AlertListResponse(
        items=[_to_alert_response(a, event_map.get(a.event_id)) for a in alerts],
        total=len(alerts),
    )


class FailedAlertsCountResponse(BaseModel):
    count: int


# Declarada antes de las rutas con /{alert_id} para que ese parámetro de path
# no la capture (D-3).
@router.get("/failed/count", response_model=FailedAlertsCountResponse)
async def get_failed_alerts_count(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> FailedAlertsCountResponse:
    """
    Conteo de alertas en fallo terminal para el banner (US-29, US-05, D-3):
    delivered_at IS NULL AND failed_at IS NOT NULL, sin umbral de retry_count.
    """
    return FailedAlertsCountResponse(count=count_failed_alerts(session))


@router.post("/{alert_id}/retry", response_model=AlertResponse)
async def retry_failed_alert(
    alert_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> AlertResponse:
    """Resetea la alerta fallida y re-intenta el envío."""
    try:
        alert = await retry_alert(alert_id, session, _admin.id)  # type: ignore[arg-type]
    except ValueError as exc:
        reason = str(exc)
        if reason in ("not_found", "event_not_found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert_not_found")
        if reason == "already_delivered":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="alert_already_delivered")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)
    event = session.get(Event, alert.event_id)
    return _to_alert_response(alert, event)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_alert(
    alert_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Elimina la alerta de la DLQ."""
    try:
        delete_alert(alert_id, session, _admin.id)  # type: ignore[arg-type]
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert_not_found")
