"""
Tests de Change 54 (backend-privacy-hardening) — ticket SSE de un solo uso
(D64/RN-158) y continuidad D-EV-6 vía last_event_id en la URL.

Cubre:
  5.1  POST /alerts/stream-ticket: emisión, auth, tickets distintos
  5.2  GET /alerts/stream: ticket válido/reutilizado/vencido/inexistente/
       ausente, ?token= sin ticket, usuario desactivado
  5.3  Atomicidad de consume_ticket contra Valkey real
  5.4  Replay via last_event_id (query param, precedencia del header)

Usa SQLite in-memory para la sesión de DB (mismo patrón que test_sse_alerts.py)
y Valkey real (TEST_VALKEY_URL) para el ticket, porque su semántica depende de
SET NX EX y GETDEL atómicos que un mock no puede reproducir con fidelidad.
Salta si psycopg/libpq no está disponible (patrón C08+ del resto de la suite).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.security import create_access_token
from app.core.valkey import build_async_valkey_client
from app.modules.alerts.models import Alert, AlertSeverity
from app.modules.alerts.stream_ticket import (
    SSE_TICKET_TTL_SECONDS,
    _ticket_key,
    consume_ticket,
    issue_ticket,
)
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus


# ── Fixtures ──────────────────────────────────────────────────────────────────


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
def session(mem_engine):
    with Session(mem_engine) as s:
        yield s


@pytest.fixture()
async def real_async_valkey():
    """Reemplaza el singleton async por un cliente real de Valkey (TEST_VALKEY_URL).

    issue_ticket/consume_ticket dependen de SET NX EX y GETDEL atómicos, que un
    Mock no reproduce con fidelidad. get_current_user (blacklist) y
    check_api_rate_limit importan el singleton directamente (no via DI), así
    que patchear el singleton alcanza también a esos paths sin overrides
    adicionales — mismo criterio que la fixture `real_valkey` (sync) de conftest.
    """
    import app.core.valkey as _valkey_mod

    client = build_async_valkey_client(os.environ["VALKEY_URL"])
    original = _valkey_mod._async_client
    _valkey_mod._async_client = client
    try:
        yield client
    finally:
        _valkey_mod._async_client = original
        await client.aclose()


def _make_user(
    session: Session,
    *,
    username: str = "sse-admin",
    role: str = "admin",
    is_active: bool = True,
) -> User:
    user = User(
        username=username,
        email=f"{username}@fim.local",
        password_hash="x",
        role=role,
        is_active=is_active,
        must_change_password=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _token_for(user: User, *, must_change_password: bool = False) -> str:
    return create_access_token(
        user_id=user.id,  # type: ignore[arg-type]
        username=user.username,
        must_change_password=must_change_password,
        jti=str(uuid.uuid4()),
    )


def _make_app(test_session: Session):
    from app.main import app
    from app.core.database import get_session

    app.dependency_overrides[get_session] = lambda: test_session
    return app


def _make_event(session: Session) -> Event:
    event = Event(
        event_id=f"evt-{uuid.uuid4()}",
        agent_id="agent-001",
        path="/etc/passwd",
        hash_detected="abc123",
        status=EventStatus.pending,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _make_alert(session: Session, event_id: int, severity: AlertSeverity = AlertSeverity.critical) -> Alert:
    alert = Alert(event_id=event_id, severity=severity)
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


# ── 5.1 POST /alerts/stream-ticket ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_ticket_admin_creates_valid_key(session, real_async_valkey):
    """Admin autenticado obtiene 200 con expires_in=30 y una clave hasheada con TTL <= 30."""
    admin = _make_user(session)
    token = _token_for(admin)
    app = _make_app(session)

    try:
        with TestClient(app) as tc:
            resp = tc.post("/alerts/stream-ticket", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket"]
        assert data["expires_in"] == SSE_TICKET_TTL_SECONDS

        key = _ticket_key(data["ticket"])
        value = await real_async_valkey.get(key)
        ttl = await real_async_valkey.ttl(key)
        assert value == str(admin.id)
        assert 0 < ttl <= SSE_TICKET_TTL_SECONDS
    finally:
        app.dependency_overrides.clear()


def test_issue_ticket_without_jwt_returns_401_and_no_key(session, real_async_valkey):
    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.post("/alerts/stream-ticket")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_issue_ticket_non_admin_returns_403(session, real_async_valkey):
    viewer = _make_user(session, username="viewer", role="viewer")
    token = _token_for(viewer)
    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.post("/alerts/stream-ticket", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_issue_ticket_password_change_only_scope_returns_403(session, real_async_valkey):
    admin = _make_user(session)
    token = _token_for(admin, must_change_password=True)
    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.post("/alerts/stream-ticket", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "password_change_required"
    finally:
        app.dependency_overrides.clear()


def test_issue_ticket_successive_tickets_are_distinct(session, real_async_valkey):
    admin = _make_user(session)
    token = _token_for(admin)
    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            r1 = tc.post("/alerts/stream-ticket", headers={"Authorization": f"Bearer {token}"})
            r2 = tc.post("/alerts/stream-ticket", headers={"Authorization": f"Bearer {token}"})
        assert r1.json()["ticket"] != r2.json()["ticket"]
    finally:
        app.dependency_overrides.clear()


# ── 5.2 GET /alerts/stream — auth por ticket ──────────────────────────────────


@pytest.mark.asyncio
async def test_stream_valid_ticket_returns_200_and_consumes_key(session, real_async_valkey):
    """
    Ejercita la dependencia y el endpoint directamente, sin abrir una conexión
    HTTP real: httpx.ASGITransport (usado tanto por TestClient como por
    AsyncClient) buffera el body completo antes de devolver el control, y
    EventSourceResponse nunca termina de emitir — ver el mismo criterio en
    test_sse_alerts.py::test_stream_alerts_valid_token_content_type.
    """
    from app.modules.alerts.router import _require_admin_from_ticket, stream_alerts

    admin = _make_user(session)
    ticket = await issue_ticket(admin.id, real_async_valkey)  # type: ignore[arg-type]

    resolved = await _require_admin_from_ticket(
        ticket=ticket, session=session, async_valkey_client=real_async_valkey
    )
    assert resolved.id == admin.id

    mock_request = MagicMock()
    mock_request.headers = {}
    response = await stream_alerts(request=mock_request, session=session, _admin=resolved)
    assert "text/event-stream" in (response.media_type or "")
    assert response.status_code == 200

    assert await real_async_valkey.get(_ticket_key(ticket)) is None


@pytest.mark.asyncio
async def test_stream_reused_ticket_returns_401(session, real_async_valkey):
    from fastapi import HTTPException

    from app.modules.alerts.router import _require_admin_from_ticket

    admin = _make_user(session)
    ticket = await issue_ticket(admin.id, real_async_valkey)  # type: ignore[arg-type]

    await _require_admin_from_ticket(
        ticket=ticket, session=session, async_valkey_client=real_async_valkey
    )

    with pytest.raises(HTTPException) as exc_info:
        await _require_admin_from_ticket(
            ticket=ticket, session=session, async_valkey_client=real_async_valkey
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_stream_expired_ticket_returns_401(session, real_async_valkey):
    admin = _make_user(session)
    ticket = await issue_ticket(admin.id, real_async_valkey)  # type: ignore[arg-type]
    # Forzar el vencimiento sin esperar los 30s reales.
    await real_async_valkey.pexpire(_ticket_key(ticket), 1)
    await asyncio.sleep(0.05)

    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get(f"/alerts/stream?ticket={ticket}")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_stream_nonexistent_ticket_returns_401(session, real_async_valkey):
    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts/stream?ticket=this-ticket-was-never-issued")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_stream_missing_ticket_returns_401_not_422(session, real_async_valkey):
    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts/stream")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_stream_jwt_in_query_without_ticket_returns_401(session, real_async_valkey):
    """?token=<jwt admin válido> sin ?ticket= no autentica (D64/RN-158)."""
    admin = _make_user(session)
    token = _token_for(admin)
    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get(f"/alerts/stream?token={token}")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_ticket_of_deactivated_user_returns_401(session, real_async_valkey):
    admin = _make_user(session)
    ticket = await issue_ticket(admin.id, real_async_valkey)  # type: ignore[arg-type]
    admin.is_active = False
    session.add(admin)
    session.commit()

    app = _make_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get(f"/alerts/stream?ticket={ticket}")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── 5.3 Atomicidad de consume_ticket ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_ticket_concurrent_resolves_exactly_once(real_async_valkey):
    """Dos consume_ticket() concurrentes sobre el mismo ticket: exactamente uno gana."""
    user_id = 42
    ticket = await issue_ticket(user_id, real_async_valkey)

    results = await asyncio.gather(
        consume_ticket(ticket, real_async_valkey),
        consume_ticket(ticket, real_async_valkey),
    )

    winners = [r for r in results if r is not None]
    assert winners == [user_id]
    assert results.count(None) == 1


# ── 5.4 Replay via last_event_id (query param, precedencia del header) ───────


@pytest.mark.asyncio
async def test_replay_via_last_event_id_query_param(session):
    """?last_event_id=9 con alertas 10,11,12 -> se reemiten en orden (D-EV-6)."""
    from app.modules.alerts.router import _alert_sse_generator

    event = _make_event(session)
    a1 = _make_alert(session, event.id)
    a2 = _make_alert(session, event.id)
    a3 = _make_alert(session, event.id)
    first_id = a1.id

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.query_params = {"last_event_id": str(first_id - 1)}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    received = []
    gen = _alert_sse_generator(mock_request, session)
    async for ev in gen:
        if "data" in ev:
            received.append(json.loads(ev["data"]))
        if len(received) >= 3:
            await gen.aclose()
            break

    assert [e["id"] for e in received] == [a1.id, a2.id, a3.id]


@pytest.mark.asyncio
async def test_replay_header_takes_precedence_over_query_param(session):
    """Last-Event-ID (header) prevalece sobre ?last_event_id= (query)."""
    from app.modules.alerts.router import _alert_sse_generator

    event = _make_event(session)
    a1 = _make_alert(session, event.id)
    a2 = _make_alert(session, event.id)
    a3 = _make_alert(session, event.id)

    mock_request = MagicMock()
    # Header dice "ya vi hasta a2" (solo falta a3); query dice "ya vi hasta a1"
    # (faltarían a2 y a3). El header debe ganar: solo se reemite a3.
    mock_request.headers = {"last-event-id": str(a2.id)}
    mock_request.query_params = {"last_event_id": str(a1.id - 1)}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    received = []
    gen = _alert_sse_generator(mock_request, session)
    async for ev in gen:
        if "data" in ev:
            received.append(json.loads(ev["data"]))
        if len(received) >= 1:
            await gen.aclose()
            break

    assert [e["id"] for e in received] == [a3.id]


@pytest.mark.asyncio
async def test_no_header_and_no_query_param_no_replay(session):
    """Sin header ni query param no hay replay histórico."""
    from app.modules.alerts.router import _alert_sse_generator
    from app.modules.alerts.stream import alerts_broadcaster

    event = _make_event(session)
    _make_alert(session, event.id)
    _make_alert(session, event.id)

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.query_params = {}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    gen = _alert_sse_generator(mock_request, session)
    replay_events = []
    alert_dict = {
        "id": 999, "severity": "high", "event_id": 1, "channel": None,
        "delivered_at": None, "failed_at": None, "last_error": None,
        "retry_count": 0, "created_at": "2026-01-01T00:00:00",
    }

    async def _push_and_collect():
        await asyncio.sleep(0.05)
        alerts_broadcaster.publish(alert_dict)

    async def _read_gen():
        async for ev in gen:
            if "data" in ev:
                replay_events.append(json.loads(ev["data"]))
            await gen.aclose()
            break

    await asyncio.gather(_push_and_collect(), _read_gen())

    assert len(replay_events) == 1
    assert replay_events[0]["id"] == 999
