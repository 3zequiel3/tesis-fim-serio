"""
Tests de regresión para C32 — backend-sse-security-fixes.

Cubre los tres fixes implementados:
  FIX-01: sesión DB liberada tras replay SSE + cola acotada maxsize=100 (D24)
  FIX-02: consumers rechazan mensajes de agentes con status=revoked (D26/RN-122)
  FIX-03: PublishedCommand insertado para todos los tipos de comando (D10)

Usa SQLite in-memory. Salta si psycopg/libpq no está disponible.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus, RejectedEventAudit
from app.modules.rules.models import PublishedCommand, RulesetVersion


# ── Fixtures comunes ──────────────────────────────────────────────────────────


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
def secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent_online(mem_engine, secret) -> Agent:
    """Agente activo con shared_secret."""
    a = Agent(
        agent_id="agent-online",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
    )
    with Session(mem_engine) as s:
        s.add(a)
        s.commit()
        s.refresh(a)
    return a


@pytest.fixture()
def agent_revoked(mem_engine, secret) -> Agent:
    """Agente con status=revoked."""
    a = Agent(
        agent_id="agent-revoked",
        status=AgentStatus.revoked,
        shared_secret_hex=secret.hex(),
    )
    with Session(mem_engine) as s:
        s.add(a)
        s.commit()
        s.refresh(a)
    return a


@pytest.fixture()
def event(mem_engine, agent_online) -> Event:
    """Evento pending para agent_online."""
    ev = Event(
        event_id="evt-c32-001",
        agent_id="agent-online",
        path="/etc/c32test",
        hash_detected="deadbeef",
        status=EventStatus.pending,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    with Session(mem_engine) as s:
        s.add(ev)
        s.commit()
        s.refresh(ev)
    return ev


def _make_valid_payload(agent_id: str, shared_secret: bytes) -> dict:
    from app.core.streams import SCHEMA_VERSION, sign_payload
    import uuid
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "abc123",
        "process_pid": 1234,
        "process_uid": 0,
        "process_exe": "/usr/bin/test",
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    return payload


def _make_hb_payload(agent_id: str, shared_secret: bytes) -> dict:
    from app.core.streams import sign_payload
    payload = {
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_size": 0,
        "queue_pressure": 0.1,
        "ruleset_version": 0,
        "shutdown": False,
        "schema_version": 1,
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    return {"data": json.dumps(payload)}


def _run_consumer(mem_engine, payload: dict, mock_client=None) -> MagicMock:
    """Ejecuta _handle_message del event consumer con el engine de test."""
    if mock_client is None:
        mock_client = AsyncMock()
        mock_client.xack = AsyncMock()
        mock_client.xadd = AsyncMock()

    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod
    msg_data = {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", msg_data))
    return mock_client


# ── FIX-01: sesión DB liberada tras replay ────────────────────────────────────


@pytest.mark.asyncio
async def test_session_closed_after_replay_before_sse_loop():
    """
    FIX-01: la sesión de DB se cierra explícitamente después del replay
    y ANTES de que el generador SSE emita el primer evento en tiempo real.

    Verifica que session.close() fue invocado antes de que el broadcaster
    publique y el generador produzca su primer yield de datos.
    """
    from app.modules.alerts.router import _alert_sse_generator
    from app.modules.alerts.stream import alerts_broadcaster

    mock_session = MagicMock()
    mock_session.exec.return_value.all.return_value = []

    mock_request = MagicMock()
    mock_request.headers = {"last-event-id": "0"}  # activa replay
    mock_request.is_disconnected = AsyncMock(return_value=False)

    gen = _alert_sse_generator(mock_request, mock_session)

    close_called_before_first_event = False

    alert_dict = {
        "id": 42, "severity": "critical", "event_id": 1, "channel": None,
        "delivered_at": None, "failed_at": None, "last_error": None,
        "retry_count": 0, "created_at": "2026-01-01T00:00:00",
    }

    async def push_and_collect():
        await asyncio.sleep(0.05)
        alerts_broadcaster.publish(alert_dict)

    async def read_gen():
        nonlocal close_called_before_first_event
        async for ev in gen:
            if "data" in ev:
                # El broadcaster emitió un evento: en este punto close() debe haber sido llamado
                close_called_before_first_event = mock_session.close.called
                await gen.aclose()
                break

    await asyncio.gather(push_and_collect(), read_gen())

    assert close_called_before_first_event, (
        "session.close() debe ser invocado antes del primer evento SSE en tiempo real (FIX-01)"
    )


@pytest.mark.asyncio
async def test_session_closed_when_no_replay():
    """
    FIX-01: session.close() también se invoca cuando no hay Last-Event-ID
    (replay omitido) — el finally garantiza el cierre en todos los casos.
    """
    from app.modules.alerts.router import _alert_sse_generator
    from app.modules.alerts.stream import alerts_broadcaster

    mock_session = MagicMock()

    mock_request = MagicMock()
    mock_request.headers = {}  # sin Last-Event-ID
    mock_request.is_disconnected = AsyncMock(return_value=False)

    gen = _alert_sse_generator(mock_request, mock_session)

    alert_dict = {
        "id": 99, "severity": "high", "event_id": 1, "channel": None,
        "delivered_at": None, "failed_at": None, "last_error": None,
        "retry_count": 0, "created_at": "2026-01-01T00:00:00",
    }

    async def push():
        await asyncio.sleep(0.05)
        alerts_broadcaster.publish(alert_dict)

    async def read_gen():
        async for ev in gen:
            if "data" in ev:
                await gen.aclose()
                break

    await asyncio.gather(push(), read_gen())

    mock_session.close.assert_called()


# ── FIX-01: cola SSE acotada con drop-newest ──────────────────────────────────


def test_broadcaster_queue_bounded_at_100():
    """
    FIX-01 (D24): la cola por suscriptor tiene maxsize=100.
    El 101° evento se descarta (drop-newest) y la cola permanece en 100.
    """
    from app.modules.alerts.stream import AlertsBroadcaster

    bc = AlertsBroadcaster()
    q = bc.subscribe()

    for i in range(100):
        bc.publish({"id": i, "severity": "critical"})

    assert q.qsize() == 100, "La cola debería estar llena en 100 (maxsize=100)"

    # El 101° evento se descarta
    bc.publish({"id": 100, "severity": "critical"})

    assert q.qsize() == 100, "La cola no debe superar maxsize=100 (drop-newest)"


def test_broadcaster_queue_full_logs_warning():
    """
    FIX-01 (D24): cuando la cola está llena, se registra un log WARNING
    con el event_id del evento descartado.
    """
    import app.modules.alerts.stream as stream_mod
    from app.modules.alerts.stream import AlertsBroadcaster

    bc = AlertsBroadcaster()
    q = bc.subscribe()

    for i in range(100):
        bc.publish({"id": i})

    with patch.object(stream_mod, "log") as mock_log:
        bc.publish({"id": 100, "severity": "high"})
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args
        assert call_args[0][0] == "alerts_broadcaster.queue_full.drop_newest"

    assert q.qsize() == 100


# ── FIX-02: event consumer rechaza agentes revocados ─────────────────────────


def test_event_consumer_discards_message_from_revoked_agent(mem_engine, agent_revoked, secret):
    """
    FIX-02 / RN-122: mensaje de agente revocado es descartado (XACK sin procesar).
    No se inserta ningún Event ni RejectedEventAudit.
    """
    payload = _make_valid_payload("agent-revoked", secret)
    mock_client = _run_consumer(mem_engine, payload)

    # Mensaje descartado con XACK
    mock_client.xack.assert_called_once()

    with Session(mem_engine) as s:
        events = s.exec(select(Event)).all()
        rejections = s.exec(select(RejectedEventAudit)).all()

    assert len(events) == 0, "No debe insertar Event para agente revocado"
    assert len(rejections) == 0, "No debe insertar RejectedEventAudit para agente revocado"


def test_event_consumer_processes_online_agent_normally(mem_engine, agent_online, secret):
    """
    FIX-02: agente con status=online sigue siendo procesado normalmente.
    No se descarta el mensaje.
    """
    payload = _make_valid_payload("agent-online", secret)

    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod
    import app.modules.alerts.service as alerts_mod

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()
    msg_data = {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}

    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "notify_if_applicable", new=AsyncMock()):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", msg_data))

    with Session(mem_engine) as s:
        events = s.exec(select(Event)).all()

    assert len(events) == 1, "Agente online debe generar un Event"
    mock_client.xack.assert_called_once()


# ── FIX-02: heartbeat consumer rechaza agentes revocados ──────────────────────


def test_heartbeat_consumer_discards_heartbeat_from_revoked_agent(mem_engine, agent_revoked, secret):
    """
    FIX-02 / RN-122: heartbeat de agente revocado es descartado.
    El campo last_heartbeat NO se actualiza.

    Nota: SQLite guarda datetimes como naive — se convierte a UTC-naive para comparar.
    """
    # Usamos naive datetime para compatibilidad con SQLite
    known_time_naive = datetime.now() - timedelta(hours=1)
    with Session(mem_engine) as s:
        a = s.get(Agent, "agent-revoked")
        a.last_heartbeat = known_time_naive
        s.add(a)
        s.commit()

    hb = _make_hb_payload("agent-revoked", secret)

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(hb)

    with Session(mem_engine) as s:
        a = s.get(Agent, "agent-revoked")

    assert a.status == AgentStatus.revoked, "Status debe seguir siendo revoked"
    # last_heartbeat no debe ser más reciente que 5 segundos antes de "now"
    # (si el handler actualizara last_heartbeat estaría ~1 hora más reciente que known_time_naive)
    if a.last_heartbeat is not None:
        lhb = a.last_heartbeat
        # Normalizar a naive para comparar
        if hasattr(lhb, 'tzinfo') and lhb.tzinfo is not None:
            lhb = lhb.replace(tzinfo=None)
        delta = (lhb - known_time_naive).total_seconds()
        assert delta < 5, (
            f"last_heartbeat fue actualizado (delta={delta:.1f}s) — no debería serlo para agente revocado"
        )


def test_heartbeat_consumer_does_not_change_revoked_status(mem_engine, agent_revoked, secret):
    """
    FIX-02: el heartbeat de un agente revocado no cambia su status a online.
    """
    hb = _make_hb_payload("agent-revoked", secret)

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(hb)

    with Session(mem_engine) as s:
        a = s.get(Agent, "agent-revoked")

    assert a.status == AgentStatus.revoked


# ── FIX-03: PublishedCommand para todos los tipos de comando ──────────────────
#
# D37/RN-131 renombró publish_restore_file/publish_quarantine_file/
# publish_baseline_update a enqueue_* e invirtió su contrato: ya NO hacen
# `XADD` ni `session.commit()` propio (antes, C36/FIX-03, sí) — insertan la
# fila `PublishedCommand` `pending` en la sesión y el caller decide cuándo
# comitea (misma transacción que su mutación); el `XADD` lo hace el
# despachador genérico `publish_pending_commands` después.


def test_enqueue_restore_file_inserts_published_command(session, event, agent_online):
    """FIX-03 / D10, actualizado por D37/RN-131: enqueue_restore_file inserta un PublishedCommand pending."""
    from app.modules.actions.streams import enqueue_restore_file

    enqueue_restore_file(session, event)
    session.commit()

    cmds = session.exec(select(PublishedCommand).where(
        PublishedCommand.command_type == "restore_file"
    )).all()
    assert len(cmds) == 1
    assert cmds[0].target_agent_id == "agent-online"
    assert cmds[0].status == "pending"  # D37/RN-131: nace pending, sin XADD propio


def test_enqueue_quarantine_file_inserts_published_command(session, event, agent_online):
    """FIX-03 / D10, actualizado por D37/RN-131: enqueue_quarantine_file inserta un PublishedCommand pending."""
    from app.modules.actions.streams import enqueue_quarantine_file

    enqueue_quarantine_file(session, event)
    session.commit()

    cmds = session.exec(select(PublishedCommand).where(
        PublishedCommand.command_type == "quarantine_file"
    )).all()
    assert len(cmds) == 1
    assert cmds[0].target_agent_id == "agent-online"
    assert cmds[0].status == "pending"


def test_enqueue_baseline_update_inserts_published_command_with_ruleset_version(session, event, agent_online):
    """FIX-03 / D10, actualizado por D37/RN-131: enqueue_baseline_update inserta un PublishedCommand con ruleset_version."""
    from app.modules.actions.streams import enqueue_baseline_update

    # Asegurar que existe una fila de RulesetVersion (requerida por el caller en producción)
    rv = RulesetVersion(version=7)
    session.add(rv)
    session.flush()

    enqueue_baseline_update(session, event, ruleset_version=7)
    session.commit()

    cmds = session.exec(select(PublishedCommand).where(
        PublishedCommand.command_type == "baseline_update"
    )).all()
    assert len(cmds) == 1
    assert cmds[0].target_agent_id == "agent-online"
    assert cmds[0].ruleset_version == 7
    assert cmds[0].status == "pending"


def test_published_command_inserted_for_rule_sync(mem_engine, agent_online, secret):
    """
    FIX-03 / D10: publish_rule_sync inserta un PublishedCommand por agente.
    (Ya existía en el servicio — test de no-regresión explícito.)
    """
    from app.modules.rules.service import publish_rule_sync

    mock_valkey = MagicMock()

    with Session(mem_engine) as s:
        count = publish_rule_sync(s, mock_valkey, new_version=3)
        # commit ya fue hecho dentro de publish_rule_sync

    assert count == 1

    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(
            PublishedCommand.command_type == "rule_sync"
        )).all()

    assert len(cmds) == 1
    assert cmds[0].ruleset_version == 3
    assert cmds[0].target_agent_id == "agent-online"
    mock_valkey.xadd.assert_called_once()


def test_enqueue_restore_file_survives_xadd_failure(session, event, agent_online):
    """
    D37/RN-131 invierte FIX-03/C36: antes, si el XADD fallaba, la fila
    PublishedCommand debía revertirse junto con la transacción (no había
    outbox — la única garantía era "todo o nada" contra Valkey). Ahora
    `enqueue_restore_file` NO hace XADD — solo inserta la fila `pending` en
    la sesión — así que un XADD que falle después (en
    `publish_pending_commands`, corrido por el despachador) NO puede
    arrastrarla: la fila sigue viva y `pending`, lista para que el
    despachador reintente. Esta es la garantía que reemplaza a la anterior.
    """
    from app.modules.actions.streams import enqueue_restore_file
    from app.modules.rules.service import publish_pending_commands
    from valkey.exceptions import ValkeyError

    enqueue_restore_file(session, event)
    session.commit()

    mock_valkey = MagicMock()
    mock_valkey.xadd.side_effect = ValkeyError("Valkey unavailable")

    published = publish_pending_commands(session, mock_valkey)
    assert published == 0

    cmds = session.exec(select(PublishedCommand)).all()
    assert len(cmds) == 1, "la fila NO se pierde cuando el XADD falla — queda pending para el próximo intento"
    assert cmds[0].status == "pending"
