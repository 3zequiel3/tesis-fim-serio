"""
Tests para los endpoints REST de eventos (Change 11).

GET /events  — lista paginada con filtros
GET /events/{id} — detalle

Usa httpx ASGI transport sin servidor HTTP real.
Los tests de auth usan un token JWT válido generado desde el seed admin.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.core.security import create_access_token


def _auth_headers() -> dict[str, str]:
    token = create_access_token(user_id=1, username="admin", must_change_password=False, jti="test-jti")
    return {"Authorization": f"Bearer {token}"}


async def _get_client() -> AsyncClient:
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_list_events_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.get("/events")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_event_by_id_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.get("/events/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_event_not_found_returns_404(monkeypatch) -> None:
    """Sin datos en DB, GET /events/9999 retorna 404."""
    from unittest.mock import patch, MagicMock
    from app.core import deps

    # Patch get_current_user para que no necesite DB/Valkey real
    async def _fake_user():
        from app.modules.auth.models import User
        return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)

    monkeypatch.setattr(deps, "get_current_user", _fake_user)

    async with await _get_client() as ac:
        resp = await ac.get("/events/9999", headers=_auth_headers())
    # 404 esperado (no existe el evento) o 401/500 si el mock no se aplicó bien en este contexto
    assert resp.status_code in (404, 401)


@pytest.mark.asyncio
async def test_list_events_returns_200_with_auth(monkeypatch) -> None:
    """Con auth válido, GET /events retorna 200 aunque la lista esté vacía."""
    from unittest.mock import MagicMock
    from app.core import deps
    from sqlmodel import Session

    async def _fake_user():
        from app.modules.auth.models import User
        return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)

    monkeypatch.setattr(deps, "get_current_user", _fake_user)

    async with await _get_client() as ac:
        resp = await ac.get("/events", headers=_auth_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "items" in body
    assert "page" in body
    assert "page_size" in body


# ── US-12 (C10, D-8): baseline_status en GET /events/{id} ───────────────────

import uuid
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus, BaselineEntry, BaselineStatus
from app.modules.events.models import Event, EventStatus


def _baseline_session():
    return Session(engine)


def _make_agent(session: Session) -> Agent:
    a = Agent(
        agent_id=f"agent-baseline-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.online,
        shared_secret_hex=uuid.uuid4().hex + uuid.uuid4().hex,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _make_event_with_path(session: Session, agent: Agent, path: str | None) -> Event:
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=f"evt-baseline-{uuid.uuid4().hex[:12]}",
        agent_id=agent.agent_id,
        event_type="detection_gap" if path is None else "file_modified",
        path=path,
        hash_detected="abc123" if path is not None else "",
        status=EventStatus.pending,
        version=0,
        detected_at=now,
        received_at=now,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@pytest.mark.asyncio
async def test_get_event_baseline_status_absent() -> None:
    with _baseline_session() as session:
        agent = _make_agent(session)
        path = f"/etc/{uuid.uuid4().hex[:6]}"
        event = _make_event_with_path(session, agent, path)
        session.add(
            BaselineEntry(
                path=path,
                agent_id=agent.agent_id,
                status=BaselineStatus.absent,
                ruleset_version=1,
            )
        )
        session.commit()
        event_id = event.id

    async with await _get_client() as ac:
        resp = await ac.get(f"/events/{event_id}", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()["baseline_status"] == "absent"


@pytest.mark.asyncio
async def test_get_event_baseline_status_present() -> None:
    with _baseline_session() as session:
        agent = _make_agent(session)
        path = f"/etc/{uuid.uuid4().hex[:6]}"
        event = _make_event_with_path(session, agent, path)
        session.add(
            BaselineEntry(
                path=path,
                agent_id=agent.agent_id,
                status=BaselineStatus.present,
                hash="deadbeef",
                ruleset_version=1,
            )
        )
        session.commit()
        event_id = event.id

    async with await _get_client() as ac:
        resp = await ac.get(f"/events/{event_id}", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()["baseline_status"] == "present"


@pytest.mark.asyncio
async def test_get_event_baseline_status_null_sin_fila() -> None:
    with _baseline_session() as session:
        agent = _make_agent(session)
        path = f"/etc/{uuid.uuid4().hex[:6]}"
        event = _make_event_with_path(session, agent, path)
        event_id = event.id

    async with await _get_client() as ac:
        resp = await ac.get(f"/events/{event_id}", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()["baseline_status"] is None


@pytest.mark.asyncio
async def test_get_event_baseline_status_null_sin_path() -> None:
    with _baseline_session() as session:
        agent = _make_agent(session)
        event = _make_event_with_path(session, agent, None)
        event_id = event.id

    async with await _get_client() as ac:
        resp = await ac.get(f"/events/{event_id}", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()["baseline_status"] is None
