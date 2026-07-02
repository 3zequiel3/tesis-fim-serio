"""
Consumer del stream 'event_ack' (concepto command_ack) para el backend FIM Platform.

D30/RN-124 (C36): el agente publica confirmaciones de ejecución de comandos
(baseline_update, restore_file, quarantine_file, update_config,
rescan_baseline) en el stream Valkey `event_ack` (agent/commands.py::
_publish_ack). Nadie las consumía. Este módulo agrega ese consumer dedicado.

Nomenclatura: "command_ack" designa la confirmación de EJECUCIÓN que el
agente publica acá — distinta del ack de INGESTA homónimo de RN-40/RN-54 que
el backend publica en el stream `commands` (events/consumer.py::
_publish_event_ack). El nombre del stream Valkey (`event_ack`) no cambia.

Consumer group dedicado y durable (`fim-command-ack`, patrón events/
consumer.py — NO `xread last_id="$"` del heartbeat): un command_ack perdido
en un reinicio del backend dejaría el comando en `pending` hasta un falso
`timeout`. El consumer group entrega desde el último XACK.

Por cada command_ack:
  1. Validación estructural: command_id presente, PublishedCommand conocido.
  2. Autorización cross-agent + verificación de firma HMAC-SHA256 (decisión del
     usuario, 2026-07-02). El secret verificador se resuelve desde
     `cmd.target_agent_id` (autoridad en DB), NUNCA desde `payload.agent_id`
     (controlado por el emisor): así un agente con su propio secret no puede
     confirmar el comando de otro agente (fix confused deputy). Un `agent_id`
     de payload distinto del dueño del comando se rechaza explícitamente.
     Rechaza además acks con firma inválida o sin shared_secret resoluble.
  3. Actualiza ack_status/acked_at/error (idempotente si ya es terminal). El
     status/error se toman del payload; command_type/event_id se leen de la
     fila (D-1bis), NUNCA del payload (evita baseline poisoning).
  4. Reconcilia baseline_entries (D1/RN-104) y ruleset_version_applied
     (D5/RN-106) en la MISMA transacción.

Barrido periódico de timeout: filas `ack_status=pending` vencidas pasan a
`timeout` (patrón heartbeat_consumer._sweep_offline). Las filas con
ack_status IS NULL (p. ej. rule_sync, que el agente no confirma) quedan
excluidas.

El I/O de DB corre vía run_in_executor (D21) para no bloquear el event loop.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.core.streams import STREAM_EVENT_ACK, verify_payload
from app.modules.agents.models import Agent
from app.modules.events.models import Event
from app.modules.agents.models import BaselineStatus
from app.modules.rules.models import PublishedCommand

log = structlog.get_logger()

CONSUMER_GROUP_COMMAND_ACK = "fim-command-ack"
CONSUMER_NAME_COMMAND_ACK = "backend-01"

_BLOCK_MS = 2000
_BATCH_SIZE = 50
_SWEEP_INTERVAL_S = 10.0

_TERMINAL_ACK_STATUSES = ("acked", "failed")
_RECONCILE_ROOT_VERSION_TYPES = ("update_config", "baseline_update")

# Errores de CONEXIÓN/disponibilidad de DB: transitorios → NO XACK (reintento en PEL).
# Los errores de DATOS (IntegrityError, DataError, ProgrammingError, payload
# malformado, etc.) NO están acá a propósito: se ackean y descartan, porque tratarlos
# como transitorios reintroduciría el poison-loop infinito de C35.
_TRANSIENT_DB_ERRORS = (OperationalError, DisconnectionError, InterfaceError)


# ── Entry point ────────────────────────────────────────────────────────────────


async def run_command_ack_consumer(client: Any, stop_event: asyncio.Event) -> None:
    """Tareas concurrentes: lector del stream (consumer group) y barrido de timeout."""
    await asyncio.gather(
        _reader_loop(client, stop_event),
        _sweep_loop(stop_event),
    )


# ── Lector del stream (consumer group durable) ─────────────────────────────────


async def _reader_loop(client: Any, stop_event: asyncio.Event) -> None:
    while True:
        try:
            await _ensure_group(client)
            # Releer pendientes al arrancar (mismo criterio que events/consumer.py)
            try:
                await _process_batch(client, "0")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("command_ack_consumer.startup_pending_error", error=str(exc))
            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("command_ack_consumer.startup_error", error=str(exc))
            await asyncio.sleep(1)
    log.info("command_ack_consumer.started", group=CONSUMER_GROUP_COMMAND_ACK)

    while not stop_event.is_set():
        try:
            await _process_batch(client, ">")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("command_ack_consumer.loop_error", error=str(exc))
            await asyncio.sleep(1)


async def _ensure_group(client: Any) -> None:
    try:
        await client.xgroup_create(STREAM_EVENT_ACK, CONSUMER_GROUP_COMMAND_ACK, id="0", mkstream=True)
        log.info("command_ack_consumer.group_created", group=CONSUMER_GROUP_COMMAND_ACK)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            pass  # group ya existe
        else:
            raise


async def _process_batch(client: Any, start_id: str) -> None:
    results = await client.xreadgroup(
        CONSUMER_GROUP_COMMAND_ACK,
        CONSUMER_NAME_COMMAND_ACK,
        {STREAM_EVENT_ACK: start_id},
        count=_BATCH_SIZE,
        block=(_BLOCK_MS if start_id == ">" else None),
    )
    if not results:
        return
    loop = asyncio.get_running_loop()
    for _stream, messages in results:
        for msg_id, msg_data in messages:
            try:
                await loop.run_in_executor(None, _handle_command_ack, msg_data)
            except _TRANSIENT_DB_ERRORS as exc:
                # Error transitorio de DB (conexión/disponibilidad): NO XACK → el
                # mensaje queda en el PEL para reintento. Un ack legítimo no se pierde
                # por un Postgres momentáneamente caído (evita timeout falso).
                log.error("command_ack_consumer.transient_db_error", msg_id=msg_id, error=str(exc))
                continue
            except Exception as exc:
                # Error permanente (dato inválido, payload malformado, IntegrityError,
                # etc.): se loguea y se hace XACK abajo — descartar. NUNCA dejar sin
                # XACK un error de datos: eso fue el poison-loop infinito de C35. Ante
                # la duda, fail-safe hacia descartar (XACK), no hacia reintentar.
                log.error("command_ack_consumer.handle_error", msg_id=msg_id, error=str(exc))
            # MUST XACK todo mensaje procesado, descartado o rechazado por dato (spec backend-command-ack).
            await client.xack(STREAM_EVENT_ACK, CONSUMER_GROUP_COMMAND_ACK, msg_id)


# ── Handler síncrono (corre en threadpool, D21) ─────────────────────────────────


def _handle_command_ack(msg_data: dict[str, Any]) -> None:
    raw = msg_data.get("data", "{}")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("command_ack_consumer.unparseable_message")
        return

    command_id = payload.get("command_id")
    if not command_id:
        log.warning("command_ack_consumer.missing_command_id")
        return

    # Del payload SOLO se toman status/error — lo que el agente legítimamente
    # reporta. command_type y event_id se leen de la fila (cmd), NUNCA del payload:
    # el payload lo controla el emisor y no es fuente de autoridad (evita baseline
    # poisoning — un atacante no puede declarar command_type="baseline_update" +
    # event_id arbitrario sobre un comando que no lo es).
    status_in = payload.get("status")  # "ok" | "error"
    error_msg = payload.get("error")

    with Session(engine) as session:
        cmd = session.exec(
            select(PublishedCommand).where(PublishedCommand.command_id == command_id)
        ).first()
        if cmd is None:
            log.info("command_ack_consumer.unknown_command_id", command_id=command_id)
            return

        # command_type/event_id de confianza: los de la fila persistida (D-1bis).
        command_type = cmd.command_type
        event_id = cmd.event_id

        # ── Autorización cross-agent (fix confused deputy) ───────────────────────
        # El stream `commands` es broadcast: un agente A con SU secret válido NO debe
        # poder confirmar el comando de otro agente V. El secret verificador se
        # resuelve desde cmd.target_agent_id (autoridad en DB), NUNCA desde
        # payload.agent_id (controlado por el emisor). Además, si el payload declara
        # un agent_id distinto del dueño del comando, se rechaza explícitamente.
        payload_agent_id = payload.get("agent_id")
        if payload_agent_id is not None and payload_agent_id != cmd.target_agent_id:
            log.warning(
                "command_ack_consumer.cross_agent_rejected",
                command_id=command_id,
                payload_agent_id=payload_agent_id,
                target_agent_id=cmd.target_agent_id,
            )
            return

        secret = _get_shared_secret(session, cmd.target_agent_id) if cmd.target_agent_id else None
        if secret is None:
            log.warning(
                "command_ack_consumer.no_shared_secret",
                command_id=command_id,
                agent_id=cmd.target_agent_id,
            )
            return
        if not verify_payload(secret, payload):
            log.warning(
                "command_ack_consumer.invalid_signature",
                command_id=command_id,
                agent_id=cmd.target_agent_id,
            )
            return

        # Idempotencia: fila ya terminal no reaplica efectos secundarios.
        if cmd.ack_status in _TERMINAL_ACK_STATUSES:
            log.debug("command_ack_consumer.already_terminal", command_id=command_id, ack_status=cmd.ack_status)
            return

        now = datetime.now(timezone.utc)
        if status_in == "ok":
            cmd.ack_status = "acked"
            cmd.acked_at = now
            cmd.error = None
        else:
            cmd.ack_status = "failed"
            cmd.acked_at = now
            cmd.error = error_msg
        session.add(cmd)

        # D1/RN-104: reconciliar baseline_entries en ack ok de baseline_update.
        if status_in == "ok" and command_type == "baseline_update" and event_id is not None:
            _reconcile_baseline_entry(session, event_id, cmd.ruleset_version)

        # D5/RN-106: avanzar ruleset_version_applied de forma monotónica.
        if status_in == "ok" and command_type in _RECONCILE_ROOT_VERSION_TYPES:
            _advance_ruleset_version_applied(session, cmd.target_agent_id, cmd.ruleset_version)

        session.commit()

    log.info(
        "command_ack_consumer.processed",
        command_id=command_id,
        command_type=command_type,
        status=status_in,
    )


def _get_shared_secret(session: Session, agent_id: str) -> bytes | None:
    """Mismo patrón que events/consumer.py::_get_shared_secret."""
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if agent is None or not agent.shared_secret_hex:
        return None
    try:
        return bytes.fromhex(agent.shared_secret_hex)
    except ValueError:
        return None


def _reconcile_baseline_entry(session: Session, event_id: Any, ruleset_version: int) -> None:
    """D1/RN-104: refleja en baseline_entries el hash aprobado que el agente confirmó."""
    from app.modules.actions.service import upsert_baseline_entry

    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        log.warning("command_ack_consumer.reconcile_baseline.invalid_event_id", event_id=event_id)
        return

    event = session.exec(select(Event).where(Event.id == eid)).first()
    if event is None:
        log.warning("command_ack_consumer.reconcile_baseline.event_not_found", event_id=eid)
        return

    hash_value: str | None = event.hash_detected if event.hash_detected else None
    baseline_status = BaselineStatus.absent if hash_value is None else BaselineStatus.present
    upsert_baseline_entry(session, event.path, event.agent_id, hash_value, baseline_status, ruleset_version)


def _advance_ruleset_version_applied(session: Session, target_agent_id: str | None, ruleset_version: int) -> None:
    """D5/RN-106: avance monotónico — nunca retrocede, nunca se aplica sin confirmación."""
    if not target_agent_id:
        return
    agent = session.exec(select(Agent).where(Agent.agent_id == target_agent_id)).first()
    if agent is None:
        return
    if ruleset_version > agent.ruleset_version_applied:
        agent.ruleset_version_applied = ruleset_version
        session.add(agent)


# ── Barrido de timeout ───────────────────────────────────────────────────────────


async def _sweep_loop(stop_event: asyncio.Event) -> None:
    """Marca timeout los comandos ack_status=pending vencidos (patrón heartbeat_consumer)."""
    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_SWEEP_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            await loop.run_in_executor(None, _sweep_timeouts)
        except Exception as exc:
            log.error("command_ack_consumer.sweep_error", error=str(exc))


def _sweep_timeouts() -> None:
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(seconds=settings.command_ack_timeout_seconds)

    with Session(engine) as session:
        candidates = session.exec(
            select(PublishedCommand).where(
                PublishedCommand.ack_status == "pending",
                PublishedCommand.published_at < threshold,
            )
        ).all()
        for cmd in candidates:
            cmd.ack_status = "timeout"
            session.add(cmd)
        if candidates:
            session.commit()
            log.info("command_ack_consumer.sweep_timeout", count=len(candidates))
