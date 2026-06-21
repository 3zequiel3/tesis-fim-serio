"""
Servicio de notificaciones de alertas para FIM Platform (C15 — backend-notifications).

Responsabilidades:
  - _determine_severity: lookup fnmatch en rules para obtener severidad máxima (D-C15-01)
  - notify_if_applicable: punto de entrada desde el consumer — crea Alert y dispara notificación
  - notify_event: retry loop 3x con cascada de canales (D-C15-03, D-C15-04)
  - list_failed_alerts, retry_alert, delete_alert: gestión de la DLQ
"""

from __future__ import annotations

import asyncio
import fnmatch
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.stream import alerts_broadcaster
from app.modules.alerts.notifier import (
    send_log_only,
    send_n8n,
    send_smtp,
    send_webhook_fallback,
)
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import Rule, RuleSeverity

log = structlog.get_logger()

# Delays entre reintentos en segundos (D-C15-03)
RETRY_DELAYS: list[int] = [5, 30, 120]

# Orden de severidades para comparación
_SEVERITY_RANK: dict[str, int] = {
    RuleSeverity.low: 0,
    RuleSeverity.medium: 1,
    RuleSeverity.high: 2,
    RuleSeverity.critical: 3,
}


# ── Determinación de severidad ────────────────────────────────────────────────

def _determine_severity(event: Event, session: Session) -> RuleSeverity:
    """
    Busca todas las reglas cuyo patrón (glob) matchee event.path con fnmatch.
    Retorna la severidad más alta de los matches.
    Si no hay matches → RuleSeverity.low (D-C15-01).
    """
    rules = session.exec(select(Rule)).all()
    max_rank = -1
    max_severity = RuleSeverity.low

    for rule in rules:
        if fnmatch.fnmatch(event.path, rule.pattern):
            rank = _SEVERITY_RANK.get(rule.severity, 0)
            if rank > max_rank:
                max_rank = rank
                max_severity = rule.severity

    return max_severity


# ── Punto de entrada post-ingesta ─────────────────────────────────────────────

async def notify_if_applicable(event: Event) -> None:
    """
    Fire-and-forget desde el consumer (D-C15-02).
    Crea Alert en DB solo si la severidad es critical o high y el evento no es superseded.
    """
    # RN-22: no notificar superseded
    if event.status == EventStatus.superseded:
        log.debug("notify.skipped_superseded", event_id=event.event_id)
        return

    with Session(engine) as session:
        severity = _determine_severity(event, session)

    # RN-52: solo critical y high notifican
    if severity not in (RuleSeverity.critical, RuleSeverity.high):
        log.debug("notify.skipped_low_severity", event_id=event.event_id, severity=severity)
        return

    # Crear fila Alert
    alert_severity = AlertSeverity(severity.value)
    alert = Alert(event_id=event.id, severity=alert_severity)
    with Session(engine) as session:
        session.add(alert)
        session.commit()
        session.refresh(alert)

    log.info("notify.alert_created", alert_id=alert.id, event_id=event.event_id, severity=severity)

    # Publicar al broadcaster SSE (D-SSE-1): los clientes conectados reciben la alerta de inmediato
    alerts_broadcaster.publish({
        "id": alert.id,
        "event_id": alert.event_id,
        "severity": alert.severity.value,
        "channel": None,
        "delivered_at": None,
        "failed_at": None,
        "last_error": None,
        "retry_count": 0,
        "created_at": alert.created_at.isoformat(),
    })

    await notify_event(alert, event)


# ── Envío con retry y cascada ─────────────────────────────────────────────────

def _build_payload(alert: Alert, event: Event) -> dict[str, Any]:
    """Construye el payload estándar de notificación."""
    return {
        "alert_id": alert.id,
        "event_id": event.event_id,
        "path": event.path,
        "severity": alert.severity.value,
        "agent_id": event.agent_id,
        "detected_at": event.detected_at.isoformat(),
        "alert_created_at": alert.created_at.isoformat(),
    }


async def notify_event(alert: Alert, event: Event) -> None:
    """
    Retry loop con RETRY_DELAYS y cascada n8n → SMTP → webhook_fallback → log_only.
    Actualiza la fila alerts tras cada intento.
    """
    payload = _build_payload(alert, event)
    attempts = len(RETRY_DELAYS) + 1  # 4 intentos totales (1 inicial + 3 reintentos)

    for attempt in range(attempts):
        if attempt > 0:
            delay = RETRY_DELAYS[attempt - 1]
            log.info("notify.retry_wait", alert_id=alert.id, attempt=attempt, delay_s=delay)
            await asyncio.sleep(delay)

        success, channel = await _try_cascade(payload)

        if success:
            with Session(engine) as session:
                db_alert = session.get(Alert, alert.id)
                if db_alert:
                    db_alert.delivered_at = datetime.now(timezone.utc)
                    db_alert.channel = channel
                    db_alert.retry_count = attempt
                    db_alert.failed_at = None
                    db_alert.last_error = None
                    session.add(db_alert)
                    session.commit()
            log.info("notify.delivered", alert_id=alert.id, channel=channel, attempt=attempt)
            return
        else:
            # Actualizar estado fallido en DB tras cada intento
            with Session(engine) as session:
                db_alert = session.get(Alert, alert.id)
                if db_alert:
                    db_alert.failed_at = datetime.now(timezone.utc)
                    db_alert.last_error = f"All channels failed on attempt {attempt}"
                    db_alert.retry_count = attempt
                    session.add(db_alert)
                    session.commit()

    log.error("notify.all_attempts_failed", alert_id=alert.id, retry_count=attempts - 1)


async def _try_cascade(payload: dict[str, Any]) -> tuple[bool, AlertChannel | None]:
    """
    Intenta los canales en orden: n8n → SMTP → webhook_fallback → log_only.
    Retorna (True, canal) si alguno tiene éxito; (False, None) si todos fallan.
    Nota: log_only siempre es exitoso (RN-54), así que nunca se retorna False.
    """
    # 1. n8n
    if settings.n8n_webhook_url:
        if await send_n8n(payload, settings.n8n_webhook_url):
            return True, AlertChannel.n8n

    # 2. SMTP
    if settings.smtp_host:
        if await send_smtp(payload, settings):
            return True, AlertChannel.smtp_fallback

    # 3. webhook_fallback
    if settings.webhook_fallback_url:
        if await send_webhook_fallback(payload, settings.webhook_fallback_url):
            return True, AlertChannel.webhook_fallback

    # 4. log_only — siempre exitoso (RN-54)
    await send_log_only(payload)
    return True, AlertChannel.log_only


# ── Listado completo de alertas ───────────────────────────────────────────────

def list_alerts(
    session: Session,
    status: str | None = None,
    severity: AlertSeverity | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Alert], int]:
    """
    Retorna (items, total) con paginación y filtros opcionales.
    status: 'pending' | 'delivered' | 'failed'
    """
    def _apply_filters(stmt):
        if status == "pending":
            stmt = stmt.where(Alert.delivered_at.is_(None)).where(Alert.failed_at.is_(None))  # type: ignore[union-attr]
        elif status == "delivered":
            stmt = stmt.where(Alert.delivered_at.is_not(None))  # type: ignore[union-attr]
        elif status == "failed":
            stmt = stmt.where(Alert.failed_at.is_not(None))  # type: ignore[union-attr]
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity)
        return stmt

    count_stmt = _apply_filters(select(func.count()).select_from(Alert))
    total: int = session.exec(count_stmt).one()  # type: ignore[assignment]

    items_stmt = _apply_filters(select(Alert)).order_by(Alert.created_at.desc()).offset((page - 1) * size).limit(size)
    items = list(session.exec(items_stmt).all())

    return items, total


# ── Gestión de la DLQ ─────────────────────────────────────────────────────────

def list_failed_alerts(session: Session) -> list[Alert]:
    """Retorna alertas con failed_at NOT NULL y delivered_at IS NULL, ordenadas por failed_at DESC."""
    stmt = (
        select(Alert)
        .where(Alert.failed_at.is_not(None))  # type: ignore[union-attr]
        .where(Alert.delivered_at.is_(None))  # type: ignore[union-attr]
        .order_by(Alert.failed_at.desc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


async def retry_alert(alert_id: int, session: Session) -> Alert:
    """
    Resetea failed_at/last_error/retry_count y re-intenta la notificación.
    Raises ValueError si no existe o ya fue entregada (el router convierte a 404/409).
    """
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise ValueError("not_found")
    if alert.delivered_at is not None:
        raise ValueError("already_delivered")

    # Resetear estado
    alert.failed_at = None
    alert.last_error = None
    alert.retry_count = 0
    session.add(alert)
    session.commit()
    session.refresh(alert)

    # Obtener el evento asociado
    event = session.get(Event, alert.event_id)
    if event is None:
        raise ValueError("event_not_found")

    # Re-intentar en background
    asyncio.create_task(notify_event(alert, event))
    return alert


def delete_alert(alert_id: int, session: Session) -> None:
    """
    Elimina la fila de alerts.
    Raises ValueError si no existe.
    """
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise ValueError("not_found")
    session.delete(alert)
    session.commit()
