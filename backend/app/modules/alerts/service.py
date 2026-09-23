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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.core.executors import get_notify_executor
from app.modules.alerts.contract import (
    NOTIFICATION_TYPE_ALERT,
    SCHEMA_VERSION,
    action_taken_for,
)
from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.audit.models import AuditLog
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


# ── Cota de entregas concurrentes (D76/RN-170, D-4 y D-6 del design de
# `notify-isolate-executor-lane`) ───────────────────────────────────────────
#
# Acota las CORRUTINAS de entrega en vuelo dentro de `notify_event` — un
# recurso distinto de los hilos de `db_notify_executor_max_workers`, y a
# propósito no se igualan (ver el comentario de `Settings`). Vive a nivel de
# módulo, no dentro de una función, porque tiene que ser el MISMO semáforo
# para las tres puertas de entrada de `notify_event`: el consumer de eventos,
# `recover_pending_notifications` (arranque) y el reintento manual desde la
# DLQ. Ninguna de las tres lo referencia directamente — todas pasan por
# `notify_event`, que es donde vive el `async with _delivery_slot()` de abajo.
#
# El valor se lee de `settings` UNA sola vez, al importar el módulo — igual
# que `RETRY_DELAYS` es una constante de módulo y no una lectura dinámica de
# `settings` en cada llamada. Un test que reemplaza `service.settings` por un
# `MagicMock` parcial (patrón ya establecido en esta suite) no debe romper el
# cupo de entregas: no es un parámetro por request, es dimensionamiento de
# arranque.
_notify_delivery_semaphore = asyncio.Semaphore(settings.notify_max_concurrent_deliveries)
_notify_backlog_warning_threshold = settings.notify_backlog_warning_threshold

# Contador de entregas EN ESPERA del permiso (no de las que ya lo tienen).
# Junto con `_notify_backlog_warned` implementa el disparo por FLANCO de la
# advertencia de backlog: una línea de log al cruzar el umbral hacia arriba,
# una al volver hacia abajo, nunca una por notificación.
_notify_waiting_count = 0
_notify_backlog_warned = False


@asynccontextmanager
async def _delivery_slot():
    """
    Async context manager del cupo de entregas concurrentes.

    Comportamiento de desborde: al llenarse el cupo, la corrutina ESPERA su
    turno en orden de llegada (FIFO, propiedad de `asyncio.Semaphore`). No se
    descarta, no se rechaza y no se difiere — degradar cualquiera de esas
    formas violaría la semántica al-menos-una-vez que `notify_event` declara,
    y "diferir" no tiene adónde: `recover_pending_notifications` corre una
    sola vez, en el arranque, no hay barrido periódico que recoja una entrega
    diferida (D-4 del design). El costo residual —la cola de espera no tiene
    cota— se acota aritméticamente contra el rate limit de ingesta y se hace
    observable acá, con la advertencia disparada por flanco.
    """
    global _notify_waiting_count, _notify_backlog_warned
    _notify_waiting_count += 1
    if (
        not _notify_backlog_warned
        and _notify_waiting_count >= _notify_backlog_warning_threshold
    ):
        _notify_backlog_warned = True
        log.warning(
            "notify.delivery_backlog_high",
            waiting=_notify_waiting_count,
            threshold=_notify_backlog_warning_threshold,
        )
    try:
        await _notify_delivery_semaphore.acquire()
    finally:
        _notify_waiting_count -= 1
        if (
            _notify_backlog_warned
            and _notify_waiting_count < _notify_backlog_warning_threshold
        ):
            _notify_backlog_warned = False
            log.warning(
                "notify.delivery_backlog_cleared",
                waiting=_notify_waiting_count,
                threshold=_notify_backlog_warning_threshold,
            )
    try:
        yield
    finally:
        _notify_delivery_semaphore.release()


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

def _create_alert_row(alert: Alert) -> Alert:
    """
    Sync helper invocado via `run_in_executor` (D75/RN-169, D-1 del design de
    `ingest-offload-blocking-db`): add + commit + refresh de la fila `Alert`
    en un hilo del executor, no sobre el event loop.

    `session.expunge(alert)` antes de cerrar el `with` desliga la instancia
    con sus atributos ya materializados por el `refresh` — mismo criterio que
    `events/service.py` ya aplica sobre `Event` (D-5.3 del design): el objeto
    que cruza del hilo del executor al loop es un detached con todo cargado,
    así que leer `id`, `event_id`, `severity`, `notification_id`,
    `created_at` desde el loop no dispara ningún I/O ni toca ninguna Session.
    """
    with Session(engine) as session:
        session.add(alert)
        session.commit()
        session.refresh(alert)
        session.expunge(alert)
    return alert


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

    # Crear fila Alert. La Session sale del event loop (D75/RN-169, D-7 del
    # design de `ingest-offload-blocking-db`): la notificación ya era
    # fire-and-forget y por eso no bloqueaba a `_handle_message` de forma
    # directa, pero su Session SÍ frenaba el event loop, y frenar el loop es
    # frenar el bucle de despacho secuencial del consumer — de ahí sale
    # exactamente el solapamiento que esta change busca.
    alert_severity = AlertSeverity(severity.value)
    alert = Alert(
        event_id=event.id,
        severity=alert_severity,
        notification_id=str(uuid.uuid4()),
    )
    loop = asyncio.get_running_loop()
    # Executor de notificación, referenciado EXPLÍCITAMENTE (D76/RN-170, D-2
    # del design de `notify-isolate-executor-lane`): `set_default_executor`
    # más `run_in_executor(None, ...)` es exactamente el mecanismo que
    # compartía los pools, así que pasar `None` acá pediría el executor de
    # ingesta sin importar este comentario. La creación de la fila `Alert`
    # queda FUERA del semáforo de entregas (D-4 del design): es el registro
    # durable del que dependen la DLQ, el broadcaster SSE y la recuperación,
    # y sigue ocurriendo antes de entrar a `notify_event`.
    alert = await loop.run_in_executor(get_notify_executor(), _create_alert_row, alert)

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


@dataclass(frozen=True)
class _PreparedNotification:
    payload: dict[str, Any]
    starting_attempt: int
    persisted_next_retry: datetime | None


def _prepare_notification(alert_id: int) -> _PreparedNotification | None:
    """
    Sync helper invocado via `run_in_executor` (D75/RN-169, D-7 del design):
    mintea `notification_id` si falta, resuelve el evento asociado y arma el
    payload canónico (D40/RN-134) dentro de un hilo del executor. Devuelve
    `None` si la alerta ya fue entregada — misma idempotencia de `notify_event`
    que antes del cambio. Levanta `ValueError` si la alerta o el evento
    asociado no existen, con el mismo texto que la versión previa sobre el
    event loop, para que el caller no cambie su manejo de errores.
    """
    with Session(engine) as session:
        db_alert = session.get(Alert, alert_id)
        if db_alert is None:
            raise ValueError("alert_not_found")
        if db_alert.delivered_at is not None:
            return None
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
    return _PreparedNotification(payload, starting_attempt, persisted_next_retry)


def _record_retry_attempt(
    alert_id: int, attempt: int, attempts: int, next_retry_at: datetime | None,
) -> None:
    """
    Sync helper invocado via `run_in_executor` (D75/RN-169, D-7 del design):
    persiste el estado de un intento de n8n fallido antes de la próxima
    espera, para que un reinicio pueda continuar desde el próximo intento.
    """
    with Session(engine) as session:
        db_alert = session.get(Alert, alert_id)
        if db_alert:
            db_alert.attempt_count = attempt + 1
            db_alert.retry_count = attempt
            db_alert.next_retry_at = next_retry_at
            db_alert.failed_at = None
            db_alert.last_error = f"n8n failed on attempt {attempt + 1} of {attempts}"
            session.add(db_alert)
            session.commit()


def _record_all_attempts_failed(alert_id: int) -> None:
    """
    Sync helper invocado via `run_in_executor` (D75/RN-169, D-7 del design):
    marca el fallo terminal de la cascada de canales (n8n + fallbacks).
    """
    with Session(engine) as session:
        db_alert = session.get(Alert, alert_id)
        if db_alert:
            db_alert.failed_at = datetime.now(timezone.utc)
            db_alert.next_retry_at = None
            db_alert.last_error = "All configured notification channels failed"
            session.add(db_alert)
            session.commit()


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

    CONCURRENCIA ACOTADA (D76/RN-170, D-4 del design de
    `notify-isolate-executor-lane`): el cuerpo completo de esta función corre
    bajo un cupo de entregas concurrentes (`_delivery_slot`), compartido por
    sus TRES puertas de entrada — el consumer de eventos, la recuperación del
    arranque y el reintento manual desde la DLQ — porque las tres llegan acá.
    El permiso se adquiere UNA sola vez, ANTES de `_prepare_notification`, y se
    sostiene hasta que la entrega termina por cualquier salida (entregada,
    fallo terminal, o el `return` de idempotencia cuando `_prepare_notification`
    devuelve `None`): adquirirlo después dejaría la preparación del payload
    —una `Session` con `commit` y `refresh`— fuera de la cota, y readquirirlo
    por vuelta del bucle movería `_build_payload` adentro del bucle, con un
    `notification_id` por intento (D-7 del design). Al llenarse el cupo, la
    entrega ESPERA su turno en orden de llegada — no se descarta, no se
    rechaza y no se difiere a un barrido posterior, que hoy no existe.
    """
    if alert.id is None:
        raise ValueError("alert_not_persisted")

    async with _delivery_slot():
        # Mint and commit the identity before any external effect. Legacy rows
        # from before migration 014 receive one on first retry/recovery.
        # Sale del event loop (D75/RN-169, D-7 del design) y corre en el
        # executor de notificación, referenciado EXPLÍCITAMENTE (D76/RN-170,
        # D-2 del design): pasar `None` acá pediría el executor de ingesta.
        loop = asyncio.get_running_loop()
        prepared = await loop.run_in_executor(get_notify_executor(), _prepare_notification, alert.id)
        if prepared is None:
            return
        payload = prepared.payload
        starting_attempt = prepared.starting_attempt
        persisted_next_retry = prepared.persisted_next_retry

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
                    # D77/RN-171, D-1 del design: se captura ACÁ, en el punto
                    # de éxito de la corrutina -antes de despachar nada al
                    # executor-, porque es el primer instante del proceso en
                    # que se sabe, con `alert.id` a la vista, que un canal
                    # aceptó. Todo lo que sigue -el despacho al executor, la
                    # espera en la cola FIFO del pool, la `Session`, el
                    # `commit`- es exactamente lo que el protocolo de medición
                    # excluye (tesis/plan_medicion_cap5.md:202-204).
                    #
                    # Error residual declarado (D-1): entre el
                    # `raise_for_status()` de notifier.py:47 y esta captura
                    # median una línea de log, el cierre del `AsyncClient` de
                    # httpx y el retorno de la corrutina -del orden de
                    # microsegundos a un milisegundo, contra una magnitud
                    # objetivo en segundos-. La alternativa exacta (que
                    # `send_n8n` devuelva el instante) está evaluada y
                    # descartada por desproporción; se declara, no se oculta.
                    channel_accepted_at = datetime.now(timezone.utc)
                    await loop.run_in_executor(
                        get_notify_executor(),
                        _mark_delivered,
                        alert.id,
                        AlertChannel.n8n,
                        attempt,
                        attempt + 1,
                        channel_accepted_at,
                    )
                    log.info("notify.delivered", alert_id=alert.id, channel=AlertChannel.n8n, attempt=attempt)
                    return

                next_retry_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=RETRY_DELAYS[attempt])
                    if attempt < len(RETRY_DELAYS)
                    else None
                )
                # Sale del event loop (D75/RN-169, D-7 del design): corre por
                # evento, dentro de la cadena de reintentos de n8n, en el
                # executor de notificación (D76/RN-170).
                await loop.run_in_executor(
                    get_notify_executor(), _record_retry_attempt, alert.id, attempt, attempts, next_retry_at
                )

        success, channel = await _try_fallbacks(payload)
        if success:
            # D77/RN-171, D-1 del design: mismo criterio que el punto de
            # éxito de n8n de arriba. El canal que aceptó es el que devolvió
            # `_try_fallbacks` -incluido `log_only`, para el cual "aceptación"
            # es la escritura del log (`notifier.py:520`), que es lo que ese
            # canal significa-.
            channel_accepted_at = datetime.now(timezone.utc)
            await loop.run_in_executor(
                get_notify_executor(),
                _mark_delivered,
                alert.id,
                channel,
                max(attempts - 1, 0) if settings.n8n_webhook_url else 0,
                attempts if settings.n8n_webhook_url else 0,
                channel_accepted_at,
            )
            log.info("notify.delivered", alert_id=alert.id, channel=channel)
            return

        # Sale del event loop (D75/RN-169, D-7 del design): fallo terminal de
        # la cascada de canales, corre por evento, en el executor de
        # notificación (D76/RN-170).
        await loop.run_in_executor(get_notify_executor(), _record_all_attempts_failed, alert.id)
        log.error("notify.all_attempts_failed", alert_id=alert.id)


def _mark_delivered(
    alert_id: int,
    channel: AlertChannel | None,
    retry_count: int,
    attempt_count: int,
    channel_accepted_at: datetime,
) -> None:
    """
    Persist success only after a channel has confirmed acceptance.

    Invocado via `run_in_executor` desde `notify_event` (D75/RN-169, D-7 del
    design de `ingest-offload-blocking-db`) — sigue siendo una función sync.
    Único cambio de firma de toda esta change (D77/RN-171, task 2.1): recibe
    el instante de aceptación del canal ya capturado por la corrutina, ANTES
    de este despacho al executor, y lo persiste en `channel_accepted_at`
    dentro del mismo `commit` que ya escribe `delivered_at`. No se abre una
    `Session` adicional ni un `commit` adicional para esto.

    `delivered_at` NO se toca: sigue siendo el `datetime.now(timezone.utc)`
    evaluado acá, dentro del hilo del executor. Esta función agrega una marca;
    no redefine la existente (D-4 del design) — hay mediciones ya emitidas que
    dependen de que `delivered_at` signifique exactamente esto.
    """
    with Session(engine) as session:
        db_alert = session.get(Alert, alert_id)
        if db_alert:
            db_alert.delivered_at = datetime.now(timezone.utc)
            db_alert.channel_accepted_at = channel_accepted_at
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


def count_failed_alerts(session: Session) -> int:
    """
    Cuenta alertas en fallo terminal (D6/RN-102): failed_at NOT NULL y
    delivered_at IS NULL — misma condición que list_failed_alerts, SIN umbral
    adicional de retry_count (D-3, US-29/US-05).
    """
    stmt = (
        select(func.count())
        .select_from(Alert)
        .where(Alert.failed_at.is_not(None))  # type: ignore[union-attr]
        .where(Alert.delivered_at.is_(None))  # type: ignore[union-attr]
    )
    return session.exec(stmt).one()  # type: ignore[return-value]


async def retry_alert(alert_id: int, session: Session, actor_id: int) -> Alert:
    """
    Resetea failed_at/last_error/retry_count y re-intenta la notificación.
    Raises ValueError si no existe o ya fue entregada (el router convierte a 404/409).

    Registra `audit_log` (action="alert_retry", D-5/RN-94) en la MISMA
    transacción que el reset — un 404/409 lanza antes del commit y no deja fila.
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
    session.add(
        AuditLog(
            user_id=actor_id,
            action="alert_retry",
            target_type="alert",
            target_id=alert_id,
            detail=f"event_id={alert.event_id}",
        )
    )
    session.commit()
    session.refresh(alert)

    # Obtener el evento asociado
    event = session.get(Event, alert.event_id)
    if event is None:
        raise ValueError("event_not_found")

    # Re-intentar en background con referencia fuerte para evitar GC prematuro
    _fire_and_forget(notify_event(alert, event))
    return alert


def delete_alert(alert_id: int, session: Session, actor_id: int) -> None:
    """
    Elimina la fila de alerts.
    Raises ValueError si no existe.

    Registra `audit_log` (action="alert_discard", D-5/RN-94) en la MISMA
    transacción que la eliminación — un 404 lanza antes del commit y no deja fila.
    """
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise ValueError("not_found")
    session.add(
        AuditLog(
            user_id=actor_id,
            action="alert_discard",
            target_type="alert",
            target_id=alert_id,
            detail=f"event_id={alert.event_id}",
        )
    )
    session.delete(alert)
    session.commit()
