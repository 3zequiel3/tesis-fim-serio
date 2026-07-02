"""
Tests de regresión para C38 — severidad persistida en Event (D34/RN-128).

Cubre:
  - ingest_event persiste severity calculada con la lógica compartida de
    D-C15-01 (rules/service.py::determine_severity_for_path).
  - Sin reglas que matcheen → low (default D-C15-01).
  - Con múltiples reglas matcheando → gana la más grave.
  - EventOut expone severity.
  - GET /events acepta severity como filtro repetible.
  - La migración 006 es idempotente (aplicarla dos veces no falla).

Sigue el mismo patrón que test_event_symlink_metadata.py (SQLite in-memory
para ingest_event; Postgres real para serialización, API y migración).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

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

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import engine
from app.core.security import create_access_token
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus
from app.modules.events.router import _get_ack_status_map, _to_event_out
from app.modules.events.service import ingest_event
from app.modules.rules.models import Rule, RuleAction, RuleSeverity
from app.modules.rules.service import determine_severity_for_path


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload(path: str) -> dict:
    return {
        "event_id": f"uuid-sev-{uuid.uuid4().hex[:8]}",
        "agent_id": "agent-test",
        "path": path,
        "hash_detected": "deadbeef",
    }


# ── determine_severity_for_path + ingest_event (SQLite in-memory) ─────────────

@pytest.fixture()
def mem_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _add_rule(eng, pattern: str, severity: RuleSeverity) -> None:
    with Session(eng) as s:
        s.add(Rule(pattern=pattern, severity=severity, action=RuleAction.alert_only))
        s.commit()


def test_ingest_event_persists_severity_from_matching_rule(mem_engine) -> None:
    _add_rule(mem_engine, "/etc/*", RuleSeverity.critical)
    now = _now()
    import app.modules.events.service as svc
    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(_payload("/etc/passwd"), now, now)

    assert event is not None
    assert event.severity == RuleSeverity.critical


def test_ingest_event_without_matching_rules_defaults_low(mem_engine) -> None:
    _add_rule(mem_engine, "/var/log/*", RuleSeverity.high)
    now = _now()
    import app.modules.events.service as svc
    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(_payload("/etc/passwd"), now, now)

    assert event is not None
    assert event.severity == RuleSeverity.low


def test_determine_severity_picks_max_of_matches(mem_engine) -> None:
    _add_rule(mem_engine, "/etc/*", RuleSeverity.medium)
    _add_rule(mem_engine, "/etc/pass*", RuleSeverity.high)
    _add_rule(mem_engine, "/tmp/*", RuleSeverity.critical)
    with Session(mem_engine) as s:
        assert determine_severity_for_path("/etc/passwd", s) == RuleSeverity.high
        assert determine_severity_for_path("/etc/hosts", s) == RuleSeverity.medium
        assert determine_severity_for_path("/opt/x", s) == RuleSeverity.low


# ── EventOut + filtro /events?severity (Postgres real) ────────────────────────

@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(agent_id=f"agent-evt-sev-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _make_event(session: Session, agent: Agent, severity: RuleSeverity, status: EventStatus = EventStatus.pending) -> Event:
    event = Event(
        event_id=f"evt-sev-{uuid.uuid4().hex[:8]}",
        agent_id=agent.agent_id,
        path=f"/etc/{uuid.uuid4().hex[:6]}",
        hash_detected="deadbeef",
        status=status,
        severity=severity,
        detected_at=_now(),
        received_at=_now(),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def test_event_out_serializes_severity(session: Session, agent: Agent) -> None:
    event = _make_event(session, agent, RuleSeverity.high)
    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)
    assert out.severity == RuleSeverity.high


def _auth_headers() -> dict[str, str]:
    token = create_access_token(user_id=1, username="admin", must_change_password=False, jti="test-jti-sev")
    return {"Authorization": f"Bearer {token}"}


async def _get_client() -> AsyncClient:
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_list_events_filters_by_severity(session: Session, agent: Agent) -> None:
    _make_event(session, agent, RuleSeverity.critical)
    _make_event(session, agent, RuleSeverity.high)
    _make_event(session, agent, RuleSeverity.low)
    _make_event(session, agent, RuleSeverity.low)

    async with await _get_client() as ac:
        resp = await ac.get(
            "/events?status=pending&severity=critical&severity=high&page_size=1",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert all(item["severity"] in ("critical", "high") for item in body["items"])


@pytest.mark.asyncio
async def test_list_events_without_severity_filter_returns_all(session: Session, agent: Agent) -> None:
    _make_event(session, agent, RuleSeverity.critical)
    _make_event(session, agent, RuleSeverity.low)

    async with await _get_client() as ac:
        resp = await ac.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {item["severity"] for item in body["items"]} == {"critical", "low"}


# ── Migración 006 — idempotencia ──────────────────────────────────────────────

def test_migration_006_is_idempotent() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1] / "db" / "migrations" / "006_add_event_severity.sql"
    )
    sql = migration_path.read_text()

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        # Segunda ejecución: no debe lanzar (ADD COLUMN IF NOT EXISTS).
        conn.execute(text(sql))
        conn.commit()


def test_events_table_has_severity_column_after_migration() -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'events' AND column_name = 'severity'"
            )
        ).all()
    assert {r[0] for r in rows} == {"severity"}
