"""
Router de alertas para FIM Platform (C15 + C16).

Endpoints:
  GET  /alerts                — listado paginado completo con filtros (C16)
  GET  /alerts/stream         — stream SSE de alertas nuevas (C16)
  GET  /alerts/failed         — DLQ (C15)
  POST /alerts/{id}/retry     — reintento desde DLQ (C15)
  DELETE /alerts/{id}         — descartar de DLQ (C15)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator

import anyio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from jose import JWTError
from pydantic import BaseModel
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_session
from app.core.deps import require_admin
from app.core.rate_limit import check_api_rate_limit
from app.core.security import BLACKLIST_PREFIX, decode_token
from app.core.valkey import get_valkey_client
from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.service import delete_alert, list_alerts, list_failed_alerts, retry_alert
from app.modules.alerts.stream import alerts_broadcaster
from app.modules.auth.models import User

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Schemas de respuesta ──────────────────────────────────────────────────────

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

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int


class AlertPaginatedResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    page: int
    size: int


# ── Auth via query param para SSE (EventSource no soporta headers) ────────────

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
)


async def _require_admin_from_token(
    token: str = Query(...),
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
) -> User:
    """Dependency SSE: valida JWT de query param ?token= y exige rol admin."""
    try:
        payload = decode_token(token)
    except JWTError:
        raise _credentials_exc

    jti: str | None = payload.get("jti")
    if jti and valkey_client.exists(f"{BLACKLIST_PREFIX}{jti}"):
        raise _credentials_exc

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise _credentials_exc

    if payload.get("scope") == "password_change_only":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="password_change_required")

    await check_api_rate_limit(int(user_id))

    user = session.exec(select(User).where(User.id == int(user_id))).first()
    if user is None or not user.is_active:
        raise _credentials_exc

    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")

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
    # 1. Replay via Last-Event-ID (D-SSE-3)
    # FIX-01: la sesión se usa SÓLO para el replay y se cierra explícitamente
    # antes de entrar al bucle SSE, para no retener una conexión del pool
    # durante el lifetime de la conexión SSE (que puede ser horas).
    last_id_str = request.headers.get("last-event-id")
    try:
        if last_id_str is not None:
            try:
                last_id = int(last_id_str)
            except ValueError:
                last_id = 0

            missed_stmt = select(Alert).where(Alert.id > last_id).order_by(Alert.id.asc())  # type: ignore[arg-type]
            missed = list(session.exec(missed_stmt).all())
            for alert in missed:
                yield {"id": str(alert.id), "data": json.dumps(_alert_to_dict(alert))}
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
                yield {"id": str(alert_dict["id"]), "data": json.dumps(alert_dict)}
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
    return AlertPaginatedResponse(
        items=[AlertResponse.model_validate(a) for a in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/stream")
async def stream_alerts(
    request: Request,
    session: Session = Depends(get_session),
    _admin: User = Depends(_require_admin_from_token),
) -> EventSourceResponse:
    """Stream SSE de alertas nuevas. Auth via query param ?token=<jwt>."""
    return EventSourceResponse(_alert_sse_generator(request, session))


@router.get("/failed", response_model=AlertListResponse)
async def get_failed_alerts(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> AlertListResponse:
    """Lista alertas con failed_at NOT NULL y delivered_at IS NULL, ordenadas por failed_at DESC."""
    alerts = list_failed_alerts(session)
    return AlertListResponse(
        items=[AlertResponse.model_validate(a) for a in alerts],
        total=len(alerts),
    )


@router.post("/{alert_id}/retry", response_model=AlertResponse)
async def retry_failed_alert(
    alert_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> AlertResponse:
    """Resetea la alerta fallida y re-intenta el envío."""
    try:
        alert = await retry_alert(alert_id, session)
    except ValueError as exc:
        reason = str(exc)
        if reason in ("not_found", "event_not_found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert_not_found")
        if reason == "already_delivered":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="alert_already_delivered")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)
    return AlertResponse.model_validate(alert)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_alert(
    alert_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Elimina la alerta de la DLQ."""
    try:
        delete_alert(alert_id, session)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert_not_found")
