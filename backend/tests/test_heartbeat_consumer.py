"""Tests del heartbeat consumer (Change 08, task 9.5).

Cubre: online/draining por heartbeat, offline por barrido a 30 s.

Los tests se saltan si psycopg/libpq no está disponible.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.modules.agents.models import Agent, AgentStatus


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def agent(mem_engine) -> Agent:
    a = Agent(agent_id="hb-agent", status=AgentStatus.offline)
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def _make_hb(agent_id: str, shutdown: bool = False, queue_pressure: float = 0.1) -> dict:
    return {
        "data": json.dumps({
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "queue_size": 0,
            "queue_pressure": queue_pressure,
            "ruleset_version": 0,
            "shutdown": shutdown,
            "schema_version": 1,
        })
    }


# ── Heartbeat marca online ────────────────────────────────────────────────────

def test_heartbeat_marks_online(mem_engine, agent) -> None:
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shutdown=False, queue_pressure=0.4))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.online
    assert a.queue_pressure == pytest.approx(0.4)
    assert a.last_heartbeat is not None


# ── Heartbeat con shutdown=true → draining ────────────────────────────────────

def test_heartbeat_shutdown_marks_draining(mem_engine, agent) -> None:
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shutdown=True))

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
