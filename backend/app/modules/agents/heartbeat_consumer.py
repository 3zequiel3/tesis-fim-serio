"""
Consumer del stream 'agent_heartbeat' y tarea de barrido de agentes offline.

Por heartbeat recibido:
  - Verifica HMAC-SHA256 del payload (D22 / RN-119).
  - Actualiza Agent.last_heartbeat, Agent.queue_pressure, status = online.
  - Si shutdown=true → status = draining (RN-93).

Barrido periódico (~10 s): marca offline a agentes con last_heartbeat > 30 s (RN-92).

Las funciones síncronas de DB (_handle_heartbeat, _sweep_offline) se ejecutan
vía run_in_executor para no bloquear el event loop (D21).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlmodel import Session, select

from app.core.database import engine
from app.core.streams import STREAM_HEARTBEAT, verify_payload
from app.modules.agents.models import Agent, AgentStatus

log = structlog.get_logger()

_BLOCK_MS = 2000
_SWEEP_INTERVAL_S = 10.0
_OFFLINE_THRESHOLD_S = 30.0
_DEAD_THRESHOLD_S = 300.0  # 5 minutos sin heartbeat → dead (D-C14-04)


async def run_heartbeat_consumer(client: Any, stop_event: asyncio.Event) -> None:
    """Tareas concurrentes: lector del stream y barrido de offline."""
    await asyncio.gather(
        _reader_loop(client, stop_event),
        _sweep_loop(stop_event),
    )


async def _reader_loop(client: Any, stop_event: asyncio.Event) -> None:
    last_id = "$"
    log.info("heartbeat_consumer.started")
    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        try:
            results = await client.xread(
                {STREAM_HEARTBEAT: last_id}, block=_BLOCK_MS, count=50
            )
            if results:
                for _stream, messages in results:
                    for msg_id, msg_data in messages:
                        await loop.run_in_executor(None, _handle_heartbeat, msg_data)
                        last_id = msg_id
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("heartbeat_consumer.read_error", error=str(exc))
            await asyncio.sleep(1)


def _handle_heartbeat(msg_data: dict[str, Any]) -> None:
    raw = msg_data.get("data", "{}")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return
    agent_id = payload.get("agent_id", "")
    if not agent_id:
        return
    queue_pressure = payload.get("queue_pressure")
    shutdown = bool(payload.get("shutdown", False))
    # D36/RN-130 (C41): clave nueva, opcional. Sin schema ni allowlist en este
    # consumer (ver docstring del módulo) — leer una clave más no toca la
    # verificación de firma, que firma el dict completo (streams.py).
    watch_path_status = payload.get("watch_path_status")

    with Session(engine) as session:
        agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
        if agent is None:
            log.warning("heartbeat_consumer.unknown_agent", agent_id=agent_id)
            return

        # FIX-02 / RN-122: agente revocado — descartar heartbeat sin actualizar estado
        if agent.status == AgentStatus.revoked:
            log.info("heartbeat_consumer.agent_revoked.discard", agent_id=agent_id)
            return

        # HMAC verification (D22 / RN-119)
        if not agent.shared_secret_hex:
            log.error("heartbeat_consumer.missing_secret", agent_id=agent_id)
            return
        try:
            secret = bytes.fromhex(agent.shared_secret_hex)
        except ValueError:
            log.error("heartbeat_consumer.invalid_secret_hex", agent_id=agent_id)
            return
        if not verify_payload(secret, payload):
            log.warning("heartbeat_consumer.invalid_signature", agent_id=agent_id)
            return

        agent.last_heartbeat = datetime.now(timezone.utc)
        if isinstance(queue_pressure, (int, float)):
            agent.queue_pressure = float(queue_pressure)
        # dead → online cuando llega un heartbeat (D-C14-04: el agente puede volver a la vida)
        agent.status = AgentStatus.draining if shutdown else AgentStatus.online

        # D36/RN-130 (C41): tolerancia hacia adelante en las dos direcciones.
        # Clave ausente (agente viejo) → no tocar la columna, no borrar el
        # último estado conocido. Valor que no es un mapa de strings → ignorar
        # con warning y procesar el heartbeat igual (nunca offline por esto).
        if watch_path_status is not None:
            if isinstance(watch_path_status, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in watch_path_status.items()
            ):
                agent.watch_path_status = watch_path_status
            else:
                log.warning(
                    "heartbeat_consumer.invalid_watch_path_status",
                    agent_id=agent_id,
                )

        session.add(agent)
        session.commit()
    log.debug("heartbeat_consumer.updated", agent_id=agent_id, shutdown=shutdown)


async def _sweep_loop(stop_event: asyncio.Event) -> None:
    """Marca offline a agentes sin heartbeat en los últimos 30 s (RN-92)."""
    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_SWEEP_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            await loop.run_in_executor(None, _sweep_offline)
        except Exception as exc:
            log.error("heartbeat_consumer.sweep_error", error=str(exc))


def _sweep_offline() -> None:
    now = datetime.now(timezone.utc)
    offline_threshold = now - timedelta(seconds=_OFFLINE_THRESHOLD_S)
    dead_threshold = now - timedelta(seconds=_DEAD_THRESHOLD_S)

    with Session(engine) as session:
        # Primera pasada: online/draining sin heartbeat en 30s → offline
        candidates = session.exec(
            select(Agent).where(
                Agent.status.in_([AgentStatus.online, AgentStatus.draining]),  # type: ignore[attr-defined]
                Agent.last_heartbeat < offline_threshold,
            )
        ).all()
        for agent in candidates:
            agent.status = AgentStatus.offline
            session.add(agent)
        if candidates:
            log.info("heartbeat_consumer.sweep_offline", count=len(candidates))

        # Segunda pasada: offline sin heartbeat en 5min → dead (D-C14-04)
        dead_candidates = session.exec(
            select(Agent).where(
                Agent.status == AgentStatus.offline,  # type: ignore[attr-defined]
                Agent.last_heartbeat < dead_threshold,
            )
        ).all()
        for agent in dead_candidates:
            agent.status = AgentStatus.dead
            session.add(agent)
        if dead_candidates:
            log.info("heartbeat_consumer.sweep_dead", count=len(dead_candidates))

        if candidates or dead_candidates:
            session.commit()
