"""
Consumer del stream 'agent_heartbeat' y tarea de barrido de agentes offline.

Por heartbeat recibido:
  - Actualiza Agent.last_heartbeat, Agent.queue_pressure, status = online.
  - Si shutdown=true → status = draining (RN-93).

Barrido periódico (~10 s): marca offline a agentes con last_heartbeat > 30 s (RN-92).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlmodel import Session, select

from app.core.database import engine
from app.core.streams import STREAM_HEARTBEAT
from app.modules.agents.models import Agent, AgentStatus

log = structlog.get_logger()

_BLOCK_MS = 2000
_SWEEP_INTERVAL_S = 10.0
_OFFLINE_THRESHOLD_S = 30.0


async def run_heartbeat_consumer(client: Any, stop_event: asyncio.Event) -> None:
    """Tareas concurrentes: lector del stream y barrido de offline."""
    await asyncio.gather(
        _reader_loop(client, stop_event),
        _sweep_loop(stop_event),
    )


async def _reader_loop(client: Any, stop_event: asyncio.Event) -> None:
    last_id = "$"
    log.info("heartbeat_consumer.started")
    while not stop_event.is_set():
        try:
            results = await client.xread(
                {STREAM_HEARTBEAT: last_id}, block=_BLOCK_MS, count=50
            )
            if results:
                for _stream, messages in results:
                    for msg_id, msg_data in messages:
                        _handle_heartbeat(msg_data)
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

    with Session(engine) as session:
        agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
        if agent is None:
            log.warning("heartbeat_consumer.unknown_agent", agent_id=agent_id)
            return
        agent.last_heartbeat = datetime.now(timezone.utc)
        if isinstance(queue_pressure, (int, float)):
            agent.queue_pressure = float(queue_pressure)
        agent.status = AgentStatus.draining if shutdown else AgentStatus.online
        session.add(agent)
        session.commit()
    log.debug("heartbeat_consumer.updated", agent_id=agent_id, shutdown=shutdown)


async def _sweep_loop(stop_event: asyncio.Event) -> None:
    """Marca offline a agentes sin heartbeat en los últimos 30 s (RN-92)."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_SWEEP_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        _sweep_offline()


def _sweep_offline() -> None:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=_OFFLINE_THRESHOLD_S)
    with Session(engine) as session:
        candidates = session.exec(
            select(Agent).where(
                Agent.status.in_([AgentStatus.online, AgentStatus.draining]),  # type: ignore[attr-defined]
                Agent.last_heartbeat < threshold,
            )
        ).all()
        for agent in candidates:
            agent.status = AgentStatus.offline
            session.add(agent)
        if candidates:
            session.commit()
            log.info("heartbeat_consumer.sweep_offline", count=len(candidates))
