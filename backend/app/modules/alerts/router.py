"""
Router de gestión de alertas / DLQ para FIM Platform (C15 — backend-notifications).

Endpoints:
  GET  /alerts/failed        — lista alertas fallidas (DLQ); requiere JWT admin
  POST /alerts/{id}/retry    — reintenta una alerta fallida; requiere JWT admin
  DELETE /alerts/{id}        — descarta una alerta de la DLQ; requiere JWT admin
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import require_admin
from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.service import delete_alert, list_failed_alerts, retry_alert
from app.modules.auth.models import User

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Schemas de respuesta ──────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: int
    event_id: int
    severity: AlertSeverity
    channel: AlertChannel | None
    failed_at: datetime | None
    last_error: str | None
    retry_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int


# ── Endpoints ──────────────────────────────────────────────────────────────────

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
        if reason == "not_found" or reason == "event_not_found":
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
