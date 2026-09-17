"""Tests del heartbeat consumer (Change 08, task 9.5).

Cubre: online/draining por heartbeat, offline por barrido a 30 s.

Los tests se saltan si psycopg/libpq no está disponible.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus


@pytest.fixture()
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def shared_secret() -> bytes:
    import os
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, shared_secret) -> Agent:
    a = Agent(agent_id="hb-agent", status=AgentStatus.offline, shared_secret_hex=shared_secret.hex())
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def _make_hb(
    agent_id: str,
    secret: bytes,
    shutdown: bool = False,
    queue_pressure: float = 0.1,
    discarded_events: object = None,
    queue_size: object = 0,
    out_of_scope_drops: object = None,
) -> dict:
    from app.core.streams import sign_payload
    payload = {
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_pressure": queue_pressure,
        "ruleset_version": 0,
        "shutdown": shutdown,
        "schema_version": 1,
    }
    if queue_size is not None:
        payload["queue_size"] = queue_size
    if discarded_events is not None:
        payload["discarded_events"] = discarded_events
    if out_of_scope_drops is not None:
        payload["out_of_scope_drops"] = out_of_scope_drops
    payload["signature"] = sign_payload(secret, payload)
    return {"data": json.dumps(payload)}


# ── Heartbeat marca online ────────────────────────────────────────────────────

def test_heartbeat_marks_online(mem_engine, agent, shared_secret) -> None:
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, shutdown=False, queue_pressure=0.4))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.online
    assert a.queue_pressure == pytest.approx(0.4)
    assert a.last_heartbeat is not None


# ── Heartbeat con shutdown=true → draining ────────────────────────────────────

def test_heartbeat_shutdown_marks_draining(mem_engine, agent, shared_secret) -> None:
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, shutdown=True))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.draining


# ── Barrido a 30 s marca offline ──────────────────────────────────────────────

def test_sweep_marks_offline_after_30s(mem_engine, agent) -> None:
    # Poner el agente online con last_heartbeat en el pasado
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.online
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=35)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._sweep_offline()

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.offline


def test_sweep_marks_draining_agent_offline_after_30s(mem_engine, agent) -> None:
    """
    US-30 (anexo §7, nivel 1 #8): un agente que se apagó de forma graceful queda
    en `draining`; si deja de latir 30 s, el barrido debe llevarlo a `offline`.
    El barrido sólo se ejercitaba desde `online`, así que esta rama del
    `status.in_([online, draining])` no estaba cubierta.
    """
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.draining
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=35)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._sweep_offline()

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.offline


def test_sweep_keeps_draining_agent_if_heartbeat_is_recent(mem_engine, agent) -> None:
    """Un agente drenando que sigue latiendo NO se marca offline (US-30)."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.draining
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=10)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._sweep_offline()

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.draining


def test_sweep_does_not_mark_offline_if_recent(mem_engine, agent) -> None:
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.online
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=10)  # reciente
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._sweep_offline()

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.online


# ── 14.13 discarded_events (D37/RN-131) ───────────────────────────────────────


def test_discarded_events_persisted(mem_engine, agent, shared_secret) -> None:
    """Heartbeat con discarded_events=3 → se persiste en Agent.discarded_events."""
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, discarded_events=3))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.discarded_events == 3


def test_discarded_events_absent_does_not_reset(mem_engine, agent, shared_secret) -> None:
    """Un heartbeat sin la clave NO pisa el valor guardado (tolerancia hacia adelante)."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, discarded_events=3))
        # Segundo heartbeat, agente sin actualizar a D37: sin la clave.
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.discarded_events == 3


def test_discarded_events_non_numeric_ignored(mem_engine, agent, shared_secret) -> None:
    """Un valor no numérico se ignora sin romper el resto del heartbeat."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, discarded_events="not-a-number"))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    # El heartbeat se procesó igual (status/last_heartbeat avanzaron) pese al valor inválido.
    assert a.status == AgentStatus.online
    assert a.last_heartbeat is not None
    assert a.discarded_events is None


def test_discarded_events_never_reported_reads_as_null(mem_engine, agent) -> None:
    """Un agente que nunca envió discarded_events expone None, no 0."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.discarded_events is None


# ── out_of_scope_drops (D69/RN-163) ────────────────────────────────────────────


def test_out_of_scope_drops_persisted(mem_engine, agent, shared_secret) -> None:
    """Heartbeat con out_of_scope_drops numérico → se persiste en Agent.out_of_scope_drops
    y viaja hacia los dos endpoints vía AgentResponse (5.1)."""
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, out_of_scope_drops=2748492))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.out_of_scope_drops == 2748492

    from app.modules.agents.service import _agent_to_response
    response = _agent_to_response(a)
    assert response.out_of_scope_drops == 2748492


def test_out_of_scope_drops_absent_does_not_reset(mem_engine, agent, shared_secret) -> None:
    """Un heartbeat sin la clave NO pisa el valor guardado (5.2)."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, out_of_scope_drops=42))
        # Segundo heartbeat, sin la clave.
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.out_of_scope_drops == 42


def test_out_of_scope_drops_non_numeric_ignored_processes_rest(mem_engine, agent, shared_secret) -> None:
    """Un valor no numérico se ignora, se registra el log de inválido y el resto
    del heartbeat se procesa igual: el agente queda online con last_heartbeat
    actualizado (5.3)."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine) as _, patch.object(hc, "log") as mock_log:
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, out_of_scope_drops="not-a-number"))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.online
    assert a.last_heartbeat is not None
    assert a.out_of_scope_drops is None
    mock_log.warning.assert_any_call("heartbeat_consumer.invalid_out_of_scope_drops", agent_id="hb-agent")


def test_out_of_scope_drops_boolean_rejected(mem_engine, agent, shared_secret) -> None:
    """Un booleano se rechaza por la misma rama que el no numérico —
    isinstance(True, int) es True en Python (5.4)."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine), patch.object(hc, "log") as mock_log:
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, out_of_scope_drops=True))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.out_of_scope_drops is None
    mock_log.warning.assert_any_call("heartbeat_consumer.invalid_out_of_scope_drops", agent_id="hb-agent")


def test_out_of_scope_drops_never_reported_reads_as_null(mem_engine, agent) -> None:
    """Un agente que nunca envió out_of_scope_drops expone None, no 0, en los
    dos endpoints (5.5)."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.out_of_scope_drops is None

    from app.modules.agents.service import _agent_to_response
    response = _agent_to_response(a)
    assert response.out_of_scope_drops is None


# ── US-21: queue_size persistido ──────────────────────────────────────────────


def test_queue_size_persisted(mem_engine, agent, shared_secret) -> None:
    """Heartbeat con queue_size=7 → se persiste en Agent.queue_size."""
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, queue_size=7))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.queue_size == 7


def test_queue_size_absent_does_not_reset(mem_engine, agent, shared_secret) -> None:
    """Un heartbeat sin la clave queue_size NO pisa el valor guardado."""
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, queue_size=7))
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, queue_size=None))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.queue_size == 7


def test_queue_size_non_numeric_ignored(mem_engine, agent, shared_secret) -> None:
    """Un valor no numérico se ignora sin romper el resto del heartbeat."""
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, queue_size="not-a-number"))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.online
    assert a.queue_size is None


def test_queue_size_never_reported_reads_as_null(mem_engine, agent) -> None:
    """Un agente que nunca envió heartbeat expone queue_size None, no 0."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.queue_size is None


# ── US-21: webhook n8n al pasar a `dead` ──────────────────────────────────────


def test_sweep_offline_returns_newly_dead_agent_ids(mem_engine, agent) -> None:
    """_sweep_offline retorna los agent_id que recién pasaron a dead (para
    que el caller async dispare el webhook n8n — ver _sweep_loop)."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.offline
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=301)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        newly_dead = hc._sweep_offline()

    assert newly_dead == ["hb-agent"]
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.dead


def test_sweep_offline_does_not_report_agent_already_dead(mem_engine, agent) -> None:
    """Un agente ya `dead` no se reporta de nuevo en barridos subsiguientes."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.dead
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=301)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        newly_dead = hc._sweep_offline()

    assert newly_dead == []


def test_notify_agent_dead_skips_without_webhook_url(mem_engine) -> None:
    """Sin n8n_webhook_url configurado, no se intenta ningún envío (mismo
    criterio que el resto de los webhooks n8n del backend)."""
    import app.modules.agents.heartbeat_consumer as hc
    from app.core.config import settings

    with patch.object(settings, "n8n_webhook_url", ""):
        with patch("app.modules.alerts.notifier.send_n8n") as mock_send:
            hc._notify_agent_dead("hb-agent")
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_notify_agent_dead_sends_n8n_payload(mem_engine) -> None:
    """Con n8n_webhook_url configurado, se dispara send_n8n con type=agent_dead."""
    import app.modules.agents.heartbeat_consumer as hc
    from app.core.config import settings
    from unittest.mock import AsyncMock

    with patch.object(settings, "n8n_webhook_url", "http://n8n.local/webhook"):
        with patch("app.modules.alerts.notifier.send_n8n", new=AsyncMock(return_value=True)) as mock_send:
            hc._notify_agent_dead("hb-agent")
            # asyncio.create_task necesita al menos un ciclo del loop para correr.
            await asyncio.sleep(0)

    mock_send.assert_called_once()
    call_args = mock_send.call_args
    payload = call_args[0][0]
    assert payload["type"] == "agent_dead"
    assert payload["agent_id"] == "hb-agent"
    assert call_args[0][1] == "http://n8n.local/webhook"


# ── D68/RN-162: agentes que nunca latieron ────────────────────────────────────


def test_sweep_marks_dead_agent_with_null_heartbeat_past_registered_at_threshold(
    mem_engine, agent
) -> None:
    """Un agente que nunca latió (last_heartbeat IS NULL) pasa a `dead` cuando
    su registered_at supera el umbral de 5 min (D68/RN-162). Sin esta rama,
    `last_heartbeat < dead_threshold` evalúa NULL y la fila nunca matchea."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.offline
        a.last_heartbeat = None
        a.registered_at = datetime.now(timezone.utc) - timedelta(seconds=301)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        newly_dead = hc._sweep_offline()

    assert newly_dead == ["hb-agent"]
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.dead


def test_sweep_keeps_offline_agent_with_null_heartbeat_within_grace_window(
    mem_engine, agent
) -> None:
    """El mismo agente, con registered_at reciente, permanece `offline`
    (ventana de gracia de D68/RN-162: register-agent.sh precede a install.sh,
    en otro host y otro momento — no se marca `dead` a un agente todavía no
    instalado)."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.offline
        a.last_heartbeat = None
        a.registered_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        newly_dead = hc._sweep_offline()

    assert newly_dead == []
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.offline


def test_sweep_does_not_touch_revoked_agent_with_null_heartbeat(mem_engine, agent) -> None:
    """Un agente `revoked` sin heartbeat nunca participa de ninguna pasada del
    barrido, sin importar cuán viejo sea su registered_at (D68/RN-162)."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.revoked
        a.last_heartbeat = None
        a.registered_at = datetime.now(timezone.utc) - timedelta(seconds=301)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        newly_dead = hc._sweep_offline()

    assert newly_dead == []
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.revoked
