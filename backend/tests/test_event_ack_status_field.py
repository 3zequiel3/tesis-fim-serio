"""
Tests de regresión para C36 — indicador secundario ack_status en GET /events.

Cubre:
  - Evento con comando confirmado expone ack_status en la respuesta.
  - Evento sin comando confirmable no expone ack_status (None, no un valor
    inventado) — RN-72 intacto, el status del evento no cambia.
  - Se usa el PublishedCommand más reciente cuando hay más de uno asociado.

Usa la DB real de test (Postgres, vía conftest) con Session directa —
mismo patrón que test_command_ack_consumer.py pero contra el engine real
para validar el query .in_()/order_by contra Postgres (no solo SQLite).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from sqlmodel import Session

from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus
from app.modules.events.router import _get_ack_status_map, _to_event_out
from app.modules.rules.models import PublishedCommand


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    # agent_id único por test — la DB de test es compartida entre tests (Postgres real,
    # no rollback-able porque los helpers de este módulo comitean explícitamente).
    a = Agent(agent_id=f"agent-evt-ack-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _make_event(session: Session, agent_id: str, event_id: str) -> Event:
    ev = Event(
        event_id=f"{event_id}-{uuid.uuid4().hex[:8]}",
        agent_id=agent_id,
        path="/etc/evt-ack-test",
        hash_detected="feedface",
        status=EventStatus.approved,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def test_event_with_confirmed_command_exposes_ack_status(session, agent):
    event = _make_event(session, agent.agent_id, "evt-ack-field-001")
    cmd = PublishedCommand(
        command_type="baseline_update",
        target_agent_id=agent.agent_id,
        event_id=event.id,
        command_id=f"cmd-evt-ack-field-001-{uuid.uuid4().hex[:8]}",
        ack_status="acked",
        ruleset_version=1,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    session.add(cmd)
    session.commit()

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.ack_status == "acked"
    assert out.status == EventStatus.approved, "el status del evento no cambia (RN-72)"


def test_event_without_confirmable_command_has_no_ack_status(session, agent):
    event = _make_event(session, agent.agent_id, "evt-ack-field-002")

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.ack_status is None


def test_event_uses_most_recent_published_command(session, agent):
    event = _make_event(session, agent.agent_id, "evt-ack-field-003")
    older = PublishedCommand(
        command_type="restore_file",
        target_agent_id=agent.agent_id,
        event_id=event.id,
        command_id=f"cmd-evt-ack-field-003-a-{uuid.uuid4().hex[:8]}",
        ack_status="failed",
        ruleset_version=0,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    session.add(older)
    session.commit()
    newer = PublishedCommand(
        command_type="restore_file",
        target_agent_id=agent.agent_id,
        event_id=event.id,
        command_id=f"cmd-evt-ack-field-003-b-{uuid.uuid4().hex[:8]}",
        ack_status="acked",
        ruleset_version=0,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    session.add(newer)
    session.commit()

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.ack_status == "acked", "debe reflejar el PublishedCommand más reciente (mayor id)"
