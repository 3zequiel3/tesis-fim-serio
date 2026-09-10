"""
Servicio de notificaciones de alertas para FIM Platform (C15 — backend-notifications).

Responsabilidades:
  - _determine_severity: lookup fnmatch en rules para obtener severidad máxima (D-C15-01)
  - notify_if_applicable: punto de entrada desde el consumer — crea Alert y dispara notificación
  - notify_event: retry durable de n8n seguido por fallbacks (D-C15-03, D-C15-04)
  - list_failed_alerts, retry_alert, delete_alert: gestión de la DLQ
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.alerts.contract import (
    NOTIFICATION_TYPE_ALERT,
    SCHEMA_VERSION,
    action_taken_for,
)
from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.stream import alerts_broadcaster
from app.modules.alerts.notifier import (
    send_log_only,
    send_n8n,
    send_smtp,
    send_webhook_fallback,
)
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RuleSeverity
from app.modules.rules.service import determine_severity_for_path

log = structlog.get_logger()

_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# Delays entre reintentos en segundos (D-C15-03)
RETRY_DELAYS: list[int] = [5, 30, 120]


def _as_utc(value: datetime) -> datetime:
    """Normalize database timestamps; SQLite drops timezone information."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ── Determinación de severidad ────────────────────────────────────────────────

def _determine_severity(event: Event, session: Session) -> RuleSeverity:
    """
    Severidad máxima entre las reglas cuyo patrón (glob) matchea event.path;
    sin matches → RuleSeverity.low (D-C15-01).

    Delega en el helper compartido de rules/service.py — la misma lógica que
    persiste Event.severity al ingerir (D34/RN-128).

    D51/RN-145 (hallazgo de la task 9.4, no anticipado por el design): un
    evento sin ruta (p. ej. detection_gap, D50/RN-144) recibe `high` fijo,
    SIN consultar el ruleset — determine_severity_for_path(None, ...) tanto
    rompería con TypeError en fnmatch.fnmatch como, si hubiera devuelto algo,
    caería en `low` sin matches, contradiciendo la severidad `high` que
    events/service.py ya persiste para el mismo evento (D-7 del design). La
    excepción se dispara por AUSENCIA DE RUTA, mismo criterio que en la
    ingesta — no específico de detection_gap.
    """
    if event.path is None:
        return RuleSeverity.high
    return determine_severity_for_path(event.path, session)


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

    # Reutilizar el snapshot de severidad de la ingesta. Reevaluar las reglas
    # agrega una consulta y puede contradecir la política que clasificó el evento.
    severity = RuleSeverity(event.severity)

    # RN-52: solo critical y high notifican
    if severity not in (RuleSeverity.critical, RuleSeverity.high):
        log.debug("notify.skipped_low_severity", event_id=event.event_id, severity=severity)
        return

    # Crear fila Alert
    alert_severity = AlertSeverity(severity.value)
    alert = Alert(
        event_id=event.id,
        severity=alert_severity,
        notification_id=str(uuid.uuid4()),
    )
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
        # C38 (FIX-02): estado derivado — una alerta recién creada aún no fue
        # entregada ni falló (ver _derive_alert_status en alerts/router.py).
        "status": "pending",
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
    """
    Construye el payload canónico de notificación (D40/RN-134).

    Sobre PLANO: `schema_version`, `notification_id` y `type` son hermanos de
    los campos de datos, nunca padres. La forma anidada rompería el receptor de
    la Batería 4 (lee los campos al tope del objeto) y los tres workflows de n8n
    (leen `$json.body.<campo>`). Ver contract.py para el fundamento completo.

    Todos los campos de RN-53 salen de columnas que `Event` YA persiste: no
    requiere captura nueva en el agente ni migración de esquema.
    """
    return {
        # Sobre
        "schema_version": SCHEMA_VERSION,
        "notification_id": alert.notification_id or str(uuid.uuid4()),
        "type": NOTIFICATION_TYPE_ALERT,
        # Datos
        "alert_id": alert.id,
        "event_id": event.event_id,
        "path": event.path,
        "severity": alert.severity.value,
        "status": event.status.value,
        "action_taken": action_taken_for(event.status),
        "action_failed": event.action_failed,
        "is_symlink": event.is_symlink,
        "agent_id": event.agent_id,
        "process_pid": event.process_pid,
        "process_uid": event.process_uid,
        "process_exe": event.process_exe,
        "detected_at": event.detected_at.isoformat(),
        "received_at": event.received_at.isoformat(),
        "alert_created_at": alert.created_at.isoformat(),
    }


async def notify_event(alert: Alert, event: Event) -> None:
    """
    Retry durable con orden n8n inicial + 3 reintentos, seguido una sola vez por
    SMTP → webhook_fallback → log_only. Actualiza ``alerts`` antes de cada
    espera para que un reinicio pueda continuar desde el próximo intento.

    INVARIANTE (D40/RN-134): `_build_payload` se invoca UNA sola vez, fuera del
    bucle. Eso es lo que hace que `notification_id` sea estable a lo largo de
    toda la escalera de reintentos — que es la única razón por la que sirve como
    clave de deduplicación (D41/RN-135). Moverlo adentro del bucle generaría un
    id por intento y volvería indistinguible un reintento de una notificación
    nueva, que es exactamente la ambigüedad que el campo existe para resolver.

    La estabilidad cubre también recuperación y reintento manual: el id vive en
    la fila Alert, no en la tarea asyncio. La entrega es al-menos-una-vez ante
    una caída después de que un receptor acepta pero antes del commit local;
    receptores que necesiten efecto único deben deduplicar notification_id.
    """
    if alert.id is None:
        raise ValueError("alert_not_persisted")

    # Mint and commit the identity before any external effect. Legacy rows from
    # before migration 014 receive one on first retry/recovery.
    with Session(engine) as session:
        db_alert = session.get(Alert, alert.id)
        if db_alert is None:
            raise ValueError("alert_not_found")
        if db_alert.delivered_at is not None:
            return
        if not db_alert.notification_id:
            db_alert.notification_id = str(uuid.uuid4())
            session.add(db_alert)
            session.commit()
            session.refresh(db_alert)
        db_event = session.get(Event, db_alert.event_id)
        if db_event is None:
            raise ValueError("event_not_found")
        payload = _build_payload(db_alert, db_event)
        starting_attempt = min(max(db_alert.attempt_count, 0), len(RETRY_DELAYS) + 1)
        persisted_next_retry = db_alert.next_retry_at

    attempts = len(RETRY_DELAYS) + 1  # 4 intentos totales (1 inicial + 3 reintentos)

    if settings.n8n_webhook_url:
        for attempt in range(starting_attempt, attempts):
            if attempt > 0:
                if attempt == starting_attempt and persisted_next_retry is not None:
                    delay = max(
                        0.0,
                        (_as_utc(persisted_next_retry) - datetime.now(timezone.utc)).total_seconds(),
                    )
                else:
                    delay = float(RETRY_DELAYS[attempt - 1])
                log.info("notify.retry_wait", alert_id=alert.id, attempt=attempt, delay_s=delay)
                await asyncio.sleep(delay)

            if await send_n8n(payload, settings.n8n_webhook_url):
                _mark_delivered(alert.id, AlertChannel.n8n, attempt, attempt + 1)
                log.info("notify.delivered", alert_id=alert.id, channel=AlertChannel.n8n, attempt=attempt)
                return

            next_retry_at = (
                datetime.now(timezone.utc) + timedelta(seconds=RETRY_DELAYS[attempt])
                if attempt < len(RETRY_DELAYS)
                else None
            )
            with Session(engine) as session:
                db_alert = session.get(Alert, alert.id)
                if db_alert:
                    db_alert.attempt_count = attempt + 1
                    db_alert.retry_count = attempt
                    db_alert.next_retry_at = next_retry_at
                    db_alert.failed_at = None
                    db_alert.last_error = f"n8n failed on attempt {attempt + 1} of {attempts}"
                    session.add(db_alert)
                    session.commit()

    success, channel = await _try_fallbacks(payload)
    if success:
        _mark_delivered(
            alert.id,
            channel,
            max(attempts - 1, 0) if settings.n8n_webhook_url else 0,
            attempts if settings.n8n_webhook_url else 0,
        )
        log.info("notify.delivered", alert_id=alert.id, channel=channel)
        return

    with Session(engine) as session:
        db_alert = session.get(Alert, alert.id)
        if db_alert:
            db_alert.failed_at = datetime.now(timezone.utc)
            db_alert.next_retry_at = None
            db_alert.last_error = "All configured notification channels failed"
            session.add(db_alert)
            session.commit()
    log.error("notify.all_attempts_failed", alert_id=alert.id)


def _mark_delivered(
    alert_id: int,
    channel: AlertChannel | None,
    retry_count: int,
    attempt_count: int,
) -> None:
    """Persist success only after a channel has confirmed acceptance."""
    with Session(engine) as session:
        db_alert = session.get(Alert, alert_id)
        if db_alert:
            db_alert.delivered_at = datetime.now(timezone.utc)
            db_alert.channel = channel
            db_alert.retry_count = retry_count
            db_alert.attempt_count = attempt_count
            db_alert.next_retry_at = None
            db_alert.failed_at = None
            db_alert.last_error = None
            session.add(db_alert)
            session.commit()


async def _try_fallbacks(payload: dict[str, Any]) -> tuple[bool, AlertChannel | None]:
    """
    Intenta las alternativas una vez, después de agotar n8n.

    Tres casos de retorno (D23, RN-120):
    - Canal primario tiene éxito → (True, canal).
    - Canales primarios configurados pero todos fallan → log_only como piso (RN-54)
      → (False, None) para que el retry loop active la DLQ.
    - Sin canales primarios configurados → log_only es el canal intencional
      → (True, AlertChannel.log_only).
    """
    any_delivery_channel_configured = bool(
        settings.n8n_webhook_url or settings.smtp_host or settings.webhook_fallback_url
    )

    # 1. SMTP
    if settings.smtp_host:
        if await send_smtp(payload, settings):
            return True, AlertChannel.smtp_fallback

    # 2. webhook_fallback
    if settings.webhook_fallback_url:
        if await send_webhook_fallback(payload, settings.webhook_fallback_url):
            return True, AlertChannel.webhook_fallback

    # 3. log_only — siempre como piso (RN-54)
    await send_log_only(payload)
    if any_delivery_channel_configured:
        return False, None
    return True, AlertChannel.log_only


async def recover_pending_notifications() -> None:
    """Resume every persisted undelivered alert after backend startup."""
    pending_ids: list[int] = []
    with Session(engine) as session:
        alerts = list(
            session.exec(
                select(Alert)
                .where(Alert.delivered_at.is_(None))  # type: ignore[union-attr]
                .where(Alert.failed_at.is_(None))  # type: ignore[union-attr]
                .where(Alert.notification_id.is_not(None))  # type: ignore[union-attr]
                .order_by(Alert.id.asc())  # type: ignore[union-attr]
            ).all()
        )
        for alert in alerts:
            event = session.get(Event, alert.event_id)
            if event is None:
                alert.failed_at = datetime.now(timezone.utc)
                alert.next_retry_at = None
                alert.last_error = "Associated event not found during notification recovery"
                session.add(alert)
                continue
            if alert.id is not None:
                pending_ids.append(alert.id)
        session.commit()

    # Reload after the commit above: SQLAlchemy expires ORM instances at commit,
    # and passing those objects outside the session would make restart recovery
    # fail with DetachedInstanceError before the first network attempt.
    pending: list[tuple[Alert, Event]] = []
    with Session(engine) as session:
        for alert_id in pending_ids:
            alert = session.get(Alert, alert_id)
            if alert is None:
                continue
            event = session.get(Event, alert.event_id)
            if event is None:
                continue
            session.expunge(alert)
            session.expunge(event)
            pending.append((alert, event))

    if pending:
        log.info("notify.recovery_started", count=len(pending))
        results = await asyncio.gather(
            *(notify_event(alert, event) for alert, event in pending),
            return_exceptions=True,
        )
        for (alert, _event), result in zip(pending, results, strict=True):
            if isinstance(result, Exception):
                log.error(
                    "notify.recovery_failed",
                    alert_id=alert.id,
                    error=str(result),
                )


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
    alert.attempt_count = 0
    alert.next_retry_at = None
    if not alert.notification_id:
        alert.notification_id = str(uuid.uuid4())
    session.add(alert)
    session.commit()
    session.refresh(alert)

    # Obtener el evento asociado
    event = session.get(Event, alert.event_id)
    if event is None:
        raise ValueError("event_not_found")

    # Re-intentar en background con referencia fuerte para evitar GC prematuro
    _fire_and_forget(notify_event(alert, event))
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
