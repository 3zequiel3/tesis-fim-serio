"""
Tests de C16 — backend-sse-alerts.

Cubre:
  6.1  AlertsBroadcaster: publish → subscribers reciben; unsubscribe
  6.2  list_alerts(): filtros status, severity, paginación
  6.3  GET /alerts: sin filtros, filtro status/severity, paginación, sin auth → 401
  6.4  GET /alerts/stream: token inválido → 401; token válido → text/event-stream
  6.5  Replay via Last-Event-ID

Usa SQLite in-memory. Salta si psycopg no está disponible (Windows sin PostgreSQL).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.service import list_alerts
from app.modules.alerts.stream import AlertsBroadcaster
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(mem_engine):
    with Session(mem_engine) as s:
        yield s


def _make_event(session: Session, agent_id: str = "agent-001") -> Event:
    event = Event(
        event_id=f"evt-{id(session)}-{agent_id[:4]}",
        agent_id=agent_id,
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


def _make_alert(
    session: Session,
    event_id: int,
    severity: AlertSeverity = AlertSeverity.critical,
    failed: bool = False,
    delivered: bool = False,
) -> Alert:
    alert = Alert(event_id=event_id, severity=severity)
    if failed:
        alert.failed_at = datetime.now(timezone.utc)
        alert.last_error = "test_error"
        alert.retry_count = 3
    if delivered:
        alert.delivered_at = datetime.now(timezone.utc)
        alert.channel = AlertChannel.n8n
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def _make_test_app(test_session: Session, mock_valkey=None):
    """App con overrides para tests de HTTP (sin auth real, sin DB real)."""
    from app.main import app
    from app.core.database import get_session
    from app.core.valkey import get_valkey_client
    from app.core.deps import require_admin

    def override_session():
        yield test_session

    def override_admin():
        return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)

    def override_valkey():
        return mock_valkey if mock_valkey else MagicMock()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_valkey_client] = override_valkey
    return app


def _make_test_app_for_sse(test_session: Session):
    """App con overrides para tests SSE (override del dep SSE, no require_admin)."""
    from app.main import app
    from app.core.database import get_session
    from app.core.valkey import get_valkey_client
    from app.modules.alerts.router import _require_admin_from_token

    def override_session():
        yield test_session

    def override_sse_admin():
        return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)

    def override_valkey():
        return MagicMock()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[_require_admin_from_token] = override_sse_admin
    app.dependency_overrides[get_valkey_client] = override_valkey
    return app


# ── 6.1 AlertsBroadcaster ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcaster_publish_delivers_to_all_subscribers():
    """publish() entrega el dict a todas las queues suscritas."""
    bc = AlertsBroadcaster()
    q1 = bc.subscribe()
    q2 = bc.subscribe()

    payload = {"id": 1, "severity": "critical"}
    bc.publish(payload)

    item1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    item2 = await asyncio.wait_for(q2.get(), timeout=1.0)

    assert item1 == payload
    assert item2 == payload


@pytest.mark.asyncio
async def test_broadcaster_unsubscribe_removes_queue():
    """unsubscribe() elimina la queue; publish posterior no le llega."""
    bc = AlertsBroadcaster()
    q = bc.subscribe()
    bc.unsubscribe(q)

    bc.publish({"id": 2, "severity": "high"})

    # La queue fue removida: no debería recibir nada
    assert q.empty()


@pytest.mark.asyncio
async def test_broadcaster_unsubscribe_idempotent():
    """unsubscribe() de una queue ya removida no lanza excepción."""
    bc = AlertsBroadcaster()
    q = bc.subscribe()
    bc.unsubscribe(q)
    bc.unsubscribe(q)  # segunda llamada — no debe levantar


# ── 6.2 list_alerts() ────────────────────────────────────────────────────────


def test_list_alerts_no_filters(session):
    """Sin filtros retorna todas las alertas."""
    event = _make_event(session)
    _make_alert(session, event.id, delivered=True)
    _make_alert(session, event.id, failed=True)
    _make_alert(session, event.id)  # pending

    items, total = list_alerts(session)
    assert total == 3
    assert len(items) == 3


def test_list_alerts_filter_status_pending(session):
    """status=pending retorna solo alertas sin delivered_at ni failed_at."""
    event = _make_event(session)
    pending = _make_alert(session, event.id)
    _make_alert(session, event.id, delivered=True)
    _make_alert(session, event.id, failed=True)

    items, total = list_alerts(session, status="pending")
    assert total == 1
    assert items[0].id == pending.id


def test_list_alerts_filter_status_delivered(session):
    """status=delivered retorna solo alertas con delivered_at NOT NULL."""
    event = _make_event(session)
    delivered = _make_alert(session, event.id, delivered=True)
    _make_alert(session, event.id)
    _make_alert(session, event.id, failed=True)

    items, total = list_alerts(session, status="delivered")
    assert total == 1
    assert items[0].id == delivered.id


def test_list_alerts_filter_status_failed(session):
    """status=failed retorna solo alertas con failed_at NOT NULL."""
    event = _make_event(session)
    failed = _make_alert(session, event.id, failed=True)
    _make_alert(session, event.id, delivered=True)
    _make_alert(session, event.id)

    items, total = list_alerts(session, status="failed")
    assert total == 1
    assert items[0].id == failed.id


def test_list_alerts_filter_severity_critical(session):
    """severity=critical retorna solo alertas critical."""
    event = _make_event(session)
    crit = _make_alert(session, event.id, severity=AlertSeverity.critical)
    _make_alert(session, event.id, severity=AlertSeverity.high)

    items, total = list_alerts(session, severity=AlertSeverity.critical)
    assert total == 1
    assert items[0].id == crit.id


def test_list_alerts_pagination(session):
    """Paginación retorna página y size correctos."""
    event = _make_event(session)
    alerts = [_make_alert(session, event.id) for _ in range(3)]

    items, total = list_alerts(session, page=2, size=1)
    assert total == 3
    assert len(items) == 1


def test_list_alerts_empty(session):
    """Sin alertas retorna lista vacía y total=0."""
    items, total = list_alerts(session)
    assert total == 0
    assert items == []


# ── 6.3 GET /alerts endpoint ──────────────────────────────────────────────────


def test_get_alerts_no_auth_returns_401(session):
    """GET /alerts sin token → 401."""
    from app.main import app
    from app.core.database import get_session
    from app.core.valkey import get_valkey_client

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_valkey_client] = lambda: MagicMock()

    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_get_alerts_returns_all(session):
    """GET /alerts sin filtros retorna todo el historial."""
    event = _make_event(session)
    _make_alert(session, event.id, delivered=True)
    _make_alert(session, event.id, failed=True)
    _make_alert(session, event.id)

    app = _make_test_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3
        assert data["page"] == 1
        assert data["size"] == 50
    finally:
        app.dependency_overrides.clear()


def test_get_alerts_filter_status_failed(session):
    """GET /alerts?status=failed retorna solo alertas fallidas."""
    event = _make_event(session)
    _make_alert(session, event.id, delivered=True)
    failed = _make_alert(session, event.id, failed=True)

    app = _make_test_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts?status=failed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == failed.id
    finally:
        app.dependency_overrides.clear()


def test_get_alerts_filter_severity_high(session):
    """GET /alerts?severity=high retorna solo alertas high."""
    event = _make_event(session)
    high = _make_alert(session, event.id, severity=AlertSeverity.high)
    _make_alert(session, event.id, severity=AlertSeverity.critical)

    app = _make_test_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts?severity=high")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == high.id
    finally:
        app.dependency_overrides.clear()


def test_get_alerts_pagination(session):
    """GET /alerts?page=2&size=1 retorna página correcta."""
    event = _make_event(session)
    for _ in range(3):
        _make_alert(session, event.id)

    app = _make_test_app(session)
    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts?page=2&size=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["page"] == 2
        assert data["size"] == 1
        assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.clear()


# ── 6.4 GET /alerts/stream — auth ─────────────────────────────────────────────


def test_stream_alerts_invalid_token_returns_401(session):
    """GET /alerts/stream?token=bad → 401 (JWTError en decode_token)."""
    from app.main import app
    from app.core.database import get_session
    from app.core.valkey import get_valkey_client

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_valkey_client] = lambda: MagicMock()

    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts/stream?token=badtoken")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_stream_alerts_no_token_returns_422(session):
    """GET /alerts/stream sin query param token → 422 (token es requerido)."""
    from app.main import app
    from app.core.database import get_session
    from app.core.valkey import get_valkey_client

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_valkey_client] = lambda: MagicMock()

    try:
        with TestClient(app) as tc:
            resp = tc.get("/alerts/stream")
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


async def test_stream_alerts_valid_token_content_type(session):
    """stream_alerts endpoint retorna EventSourceResponse con media_type text/event-stream.

    httpx.ASGITransport buffers the entire response body before returning — it
    blocks forever on SSE streams. Instead we call the route handler directly
    and verify the response type without iterating the generator (EventSourceResponse
    stores the generator lazily and sets media_type unconditionally in __init__).
    """
    from unittest.mock import MagicMock
    from app.modules.alerts.router import stream_alerts
    from app.modules.auth.models import User

    mock_request = MagicMock()
    mock_request.headers = {}  # no Last-Event-ID

    response = await stream_alerts(
        request=mock_request,
        session=session,
        _admin=User(id=1, username="admin", password_hash="x", role="admin", is_active=True),
    )

    # EventSourceResponse unconditionally sets media_type="text/event-stream" and
    # status_code=200 — the generator body is NOT iterated until the response is sent.
    assert "text/event-stream" in (response.media_type or "")
    assert response.status_code == 200


# ── 6.5 Replay via Last-Event-ID ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sse_replay_yields_missed_alerts(session):
    """Reconexión con Last-Event-ID emite alertas con id > last_id."""
    from app.modules.alerts.router import _alert_sse_generator

    event = _make_event(session)
    a1 = _make_alert(session, event.id)
    a2 = _make_alert(session, event.id)
    a3 = _make_alert(session, event.id)
    first_id = a1.id

    mock_request = MagicMock()
    mock_request.headers = {"last-event-id": str(first_id - 1)}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    received = []
    gen = _alert_sse_generator(mock_request, session)
    async for ev in gen:
        if "data" in ev:
            received.append(json.loads(ev["data"]))
        if len(received) >= 3:
            await gen.aclose()
            break

    assert len(received) == 3
    received_ids = [e["id"] for e in received]
    assert a1.id in received_ids
    assert a2.id in received_ids
    assert a3.id in received_ids


@pytest.mark.asyncio
async def test_sse_no_last_event_id_no_replay(session):
    """Sin Last-Event-ID no se emiten eventos de replay."""
    from app.modules.alerts.router import _alert_sse_generator

    event = _make_event(session)
    _make_alert(session, event.id)
    _make_alert(session, event.id)

    mock_request = MagicMock()
    mock_request.headers = {}  # sin Last-Event-ID
    mock_request.is_disconnected = AsyncMock(return_value=False)

    # El generador no debe emitir replay: subscribe e inmediatamente entra al loop
    gen = _alert_sse_generator(mock_request, session)

    # Publicar un evento al broadcaster para que el generador avance un paso
    from app.modules.alerts.stream import alerts_broadcaster

    replay_events = []

    # Avanzar el generador: como no hay Last-Event-ID, el generador no yield en replay
    # Llama a subscribe() y entra al loop; publicamos un item para avanzar un yield
    alert_dict = {"id": 99, "severity": "high", "event_id": 1, "channel": None,
                  "delivered_at": None, "failed_at": None, "last_error": None,
                  "retry_count": 0, "created_at": "2026-01-01T00:00:00"}

    async def _push_and_collect():
        # esperar un poco para que el generador entre al loop y subscribe
        await asyncio.sleep(0.05)
        alerts_broadcaster.publish(alert_dict)

    async def _read_gen():
        async for ev in gen:
            if "data" in ev:
                replay_events.append(json.loads(ev["data"]))
            await gen.aclose()
            break

    await asyncio.gather(_push_and_collect(), _read_gen())

    # Solo debe haber 1 evento (el publicado en tiempo real), no 2 del replay
    assert len(replay_events) == 1
    assert replay_events[0]["id"] == 99


# ── C35 / FIX-02: contrato `event: alert` (frontend `addEventListener('alert', ...)`) ──


@pytest.mark.asyncio
async def test_sse_replay_frames_carry_event_alert(session):
    """
    Regresión C35/FIX-02: antes del fix, los yields de replay no llevaban la clave
    `event`, por lo que el navegador asignaba el tipo default `message` y el listener
    `es.addEventListener('alert', ...)` del frontend (useAlertsSSE.ts) nunca disparaba.
    """
    from app.modules.alerts.router import _alert_sse_generator

    event = _make_event(session)
    _make_alert(session, event.id)
    first_id = _make_alert(session, event.id).id  # noqa: F841 — usado solo para setear last-event-id

    mock_request = MagicMock()
    mock_request.headers = {"last-event-id": "0"}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    received = []
    gen = _alert_sse_generator(mock_request, session)
    async for ev in gen:
        if "data" in ev:
            received.append(ev)
        if len(received) >= 2:
            await gen.aclose()
            break

    assert len(received) == 2
    for ev in received:
        assert ev.get("event") == "alert"


@pytest.mark.asyncio
async def test_sse_realtime_frame_carries_event_alert(session):
    """El yield en tiempo real (fuera del replay) también debe llevar `event: alert`."""
    from app.modules.alerts.router import _alert_sse_generator
    from app.modules.alerts.stream import alerts_broadcaster

    mock_request = MagicMock()
    mock_request.headers = {}  # sin Last-Event-ID → sin replay
    mock_request.is_disconnected = AsyncMock(return_value=False)

    gen = _alert_sse_generator(mock_request, session)
    alert_dict = {"id": 101, "severity": "high", "event_id": 1, "channel": None,
                  "delivered_at": None, "failed_at": None, "last_error": None,
                  "retry_count": 0, "created_at": "2026-01-01T00:00:00"}

    received = []

    async def _push_and_collect():
        await asyncio.sleep(0.05)
        alerts_broadcaster.publish(alert_dict)

    async def _read_gen():
        async for ev in gen:
            if "data" in ev:
                received.append(ev)
            await gen.aclose()
            break

    await asyncio.gather(_push_and_collect(), _read_gen())

    assert len(received) == 1
    assert received[0].get("event") == "alert"


@pytest.mark.asyncio
async def test_sse_keepalive_frame_has_no_event_type(session):
    """El keepalive es un comentario SSE puro — NO debe llevar `event: alert` (dispararía el listener sin datos)."""
    from app.modules.alerts import router as alerts_router

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    with patch.object(alerts_router, "_KEEPALIVE_INTERVAL", 0.01):
        gen = alerts_router._alert_sse_generator(mock_request, session)
        first = await gen.__anext__()
        await gen.aclose()

    assert first == {"comment": "keepalive"}
    assert "event" not in first


@pytest.mark.asyncio
async def test_sse_replay_last_event_id_current_no_extra(session):
    """Last-Event-ID apuntando a la última alerta → no se emite replay extra."""
    from app.modules.alerts.router import _alert_sse_generator

    event = _make_event(session)
    a1 = _make_alert(session, event.id)
    last_id = a1.id

    mock_request = MagicMock()
    mock_request.headers = {"last-event-id": str(last_id)}  # ya al día
    mock_request.is_disconnected = AsyncMock(return_value=False)

    gen = _alert_sse_generator(mock_request, session)

    from app.modules.alerts.stream import alerts_broadcaster

    replay_events = []

    async def _push_and_collect():
        await asyncio.sleep(0.05)
        alerts_broadcaster.publish({"id": 100, "severity": "low", "event_id": 1, "channel": None,
                                    "delivered_at": None, "failed_at": None, "last_error": None,
                                    "retry_count": 0, "created_at": "2026-01-01T00:00:00"})

    async def _read_gen():
        async for ev in gen:
            if "data" in ev:
                replay_events.append(json.loads(ev["data"]))
            await gen.aclose()
            break

    await asyncio.gather(_push_and_collect(), _read_gen())

    # Solo el evento real-time (id=100), no replay de a1
    assert len(replay_events) == 1
    assert replay_events[0]["id"] == 100
