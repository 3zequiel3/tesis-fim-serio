"""
Tests de regresión para C31 — backend-event-correctness.

Cubre los 9 fixes:
  FIX-01 (8.1, 8.2)  — _try_cascade: DLQ activa cuando canales fallan / log_only intencional
  FIX-02 (8.3, 8.4)  — publish Valkey post-commit en approve y reject
  FIX-03 (8.5, 8.6)  — re-consulta de pending cuando mark_superseded falla
  FIX-04 (8.7)       — paginación SQL real en list_events (no full table scan)
  FIX-05 (8.8)       — compact_chain retiene eventos más recientes, borra los más antiguos
  FIX-06 (8.9)       — dedup antes de rate limit: re-entregas no consumen presupuesto
  FIX-07 (8.10)      — event_id vacío rechazado con invalid_schema
  FIX-08 (8.11,8.12) — detected_at no parseable → clock_skew; naive datetime aceptado
  FIX-09 (8.13)      — datetime.utcnow() erradicado de módulos de producción

Usa SQLite in-memory (StaticPool) para tests unitarios.
Test 8.7 requiere Postgres real (authenticated_client del conftest).
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus, BaselineEntry, BaselineStatus
from app.modules.alerts.models import Alert, AlertChannel
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus, RejectedEventAudit, RejectionReason
from app.modules.rules.models import RulesetVersion
from app.modules.actions.schemas import RejectAction
from app.modules.actions.service import (
    _approve_single,
    _reject_single,
)
from app.modules.events.service import (
    compact_chain,
    get_pending_event_for_path,
    ingest_event,
)


# ── Fixtures comunes ──────────────────────────────────────────────────────────


@pytest.fixture()
def mem_engine():
    """SQLite in-memory con StaticPool (todas las conexiones comparten la misma DB)."""
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
def admin_user(session) -> User:
    user = User(
        id=1,
        username="admin",
        email="admin@fim.local",
        password_hash="hashed",
        role="admin",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def agent_with_secret(session) -> tuple[Agent, bytes]:
    secret = os.urandom(32)
    agent = Agent(
        agent_id="agent-c31",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, secret


def _make_pending_event(
    session: Session,
    agent_id: str = "agent-c31",
    path: str = "/etc/passwd",
    hash_detected: str = "abc123def456",
    version: int = 0,
    created_at: datetime | None = None,
) -> Event:
    now = created_at or datetime.now(timezone.utc)
    event = Event(
        event_id=f"eid-{uuid.uuid4()}",
        agent_id=agent_id,
        path=path,
        hash_detected=hash_detected,
        status=EventStatus.pending,
        version=version,
        detected_at=now,
        received_at=now,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _make_superseded_event(
    session: Session,
    path: str = "/etc/passwd",
    agent_id: str = "agent-c31",
    created_at: datetime | None = None,
) -> Event:
    now = created_at or datetime.now(timezone.utc)
    event = Event(
        event_id=f"eid-sup-{uuid.uuid4()}",
        agent_id=agent_id,
        path=path,
        hash_detected="abc",
        status=EventStatus.superseded,
        detected_at=now,
        received_at=now,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-01 — _try_cascade semántica correcta
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fix01_primary_fails_dlq_activated(session):
    """8.1 — Canal primario configurado (n8n) pero siempre falla → notify_event
    agota todos los reintentos, failed_at poblado, delivered_at IS NULL,
    log_only fue llamado en cada intento (RN-54)."""
    from app.modules.alerts.service import notify_event, RETRY_DELAYS
    from app.modules.alerts.models import Alert, AlertSeverity

    event = _make_pending_event(session)
    alert = Alert(event_id=event.id, severity=AlertSeverity.critical)
    session.add(alert)
    session.commit()
    session.refresh(alert)

    log_only_calls = []

    with patch("app.modules.alerts.service.send_n8n", new_callable=AsyncMock, return_value=False), \
         patch("app.modules.alerts.service.send_log_only", new_callable=AsyncMock,
               side_effect=lambda p: log_only_calls.append(p) or True), \
         patch("app.modules.alerts.service.settings") as mock_settings, \
         patch("app.modules.alerts.service.Session") as mock_session_cls, \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
        mock_settings.smtp_host = ""
        mock_settings.webhook_fallback_url = ""

        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        await notify_event(alert, event)

    session.refresh(alert)
    # DLQ activada: failed_at poblado, delivered_at nulo
    assert alert.failed_at is not None, "failed_at debe estar poblado cuando todos los canales fallan"
    assert alert.delivered_at is None, "delivered_at debe ser None"
    # log_only llamado en cada uno de los 4 intentos (1 inicial + 3 reintentos)
    assert len(log_only_calls) == len(RETRY_DELAYS) + 1, (
        f"log_only debe llamarse {len(RETRY_DELAYS) + 1} veces (piso RN-54), "
        f"fue llamado {len(log_only_calls)}"
    )


@pytest.mark.asyncio
async def test_fix01_no_primaries_log_only_delivers(session):
    """8.2 — Sin canales primarios configurados → log_only es canal intencional,
    alerta queda como delivered con channel=log_only."""
    from app.modules.alerts.service import notify_event
    from app.modules.alerts.models import Alert, AlertSeverity

    event = _make_pending_event(session)
    alert = Alert(event_id=event.id, severity=AlertSeverity.high)
    session.add(alert)
    session.commit()
    session.refresh(alert)

    with patch("app.modules.alerts.service.send_log_only", new_callable=AsyncMock, return_value=True), \
         patch("app.modules.alerts.service.settings") as mock_settings, \
         patch("app.modules.alerts.service.Session") as mock_session_cls:

        mock_settings.n8n_webhook_url = ""
        mock_settings.smtp_host = ""
        mock_settings.webhook_fallback_url = ""

        mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        await notify_event(alert, event)

    session.refresh(alert)
    assert alert.delivered_at is not None, "debe estar delivered"
    assert alert.channel == AlertChannel.log_only, "canal debe ser log_only"
    assert alert.failed_at is None, "failed_at debe ser None"


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-02 — Valkey publish post-commit
#
# D37/RN-131 invierte la NORMA de FIX-02 ("publicar solo post-commit"): el
# comando ahora se ENCOLA (enqueue_baseline_update/enqueue_restore_file)
# DENTRO de la misma transacción que la mutación del evento, antes del
# commit — la garantía de durabilidad la da la atomicidad de esa fila
# `PublishedCommand pending`, no el orden del XADD. Estos dos tests siguen
# vivos porque el intento inmediato best-effort de `publish_pending_commands`
# sigue corriendo DESPUÉS de `db.commit()` (para no agregar la latencia del
# poller al camino feliz) — así que el XADD observado acá sigue ocurriendo
# después del commit, mismo efecto observable, mecanismo distinto: si el
# XADD fallara, el evento seguiría approved/rejected igual (ver
# test_stream_ack_durability_outbox.py, que sí ejercita esa rama).
# ═══════════════════════════════════════════════════════════════════════════════


def test_fix02_approve_publish_is_post_commit(mem_engine, admin_user, agent_with_secret):
    """8.3 — _approve_single: el XADD del outbox (best-effort, `publish_pending_commands`)
    ocurre DESPUÉS de db.commit(). Cuando xadd es llamado, el evento ya tiene status=approved en la DB."""
    agent, _ = agent_with_secret
    with Session(mem_engine) as s:
        event = _make_pending_event(s, agent_id=agent.agent_id)
        event_id_pk = event.id

    published_statuses: list[EventStatus] = []

    def capture_on_xadd(*args, **kwargs):
        # Abrir una sesión nueva para verificar estado en DB post-commit
        with Session(mem_engine) as s:
            db_ev = s.get(Event, event_id_pk)
            if db_ev:
                published_statuses.append(db_ev.status)

    mock_valkey = MagicMock()
    mock_valkey.xadd = MagicMock(side_effect=capture_on_xadd)

    with Session(mem_engine) as session:
        _approve_single(
            db=session,
            valkey_client=mock_valkey,
            event_id=event_id_pk,
            version=0,
            confirm_absent=False,
            user_id=admin_user.id,
        )

    assert mock_valkey.xadd.call_count == 1, "xadd debe haberse llamado exactamente una vez"
    assert len(published_statuses) == 1
    assert published_statuses[0] == EventStatus.approved, (
        "el evento debe estar approved en DB cuando xadd es llamado (post-commit)"
    )


def test_fix02_reject_publish_is_post_commit(mem_engine, admin_user, agent_with_secret):
    """8.4 — _reject_single: el XADD del outbox (best-effort, `publish_pending_commands`)
    ocurre DESPUÉS de db.commit(). Cuando xadd es llamado, el evento ya tiene status=rejected en la DB."""
    agent, _ = agent_with_secret
    with Session(mem_engine) as s:
        event = _make_pending_event(s, agent_id=agent.agent_id)
        event_id_pk = event.id

    published_statuses: list[EventStatus] = []

    def capture_on_xadd(*args, **kwargs):
        with Session(mem_engine) as s:
            db_ev = s.get(Event, event_id_pk)
            if db_ev:
                published_statuses.append(db_ev.status)

    mock_valkey = MagicMock()
    mock_valkey.xadd = MagicMock(side_effect=capture_on_xadd)

    with Session(mem_engine) as session:
        _reject_single(
            db=session,
            valkey_client=mock_valkey,
            event_id=event_id_pk,
            version=0,
            action=RejectAction.restore,
            user_id=admin_user.id,
        )

    assert mock_valkey.xadd.call_count == 1
    assert len(published_statuses) == 1
    assert published_statuses[0] == EventStatus.rejected, (
        "el evento debe estar rejected en DB cuando xadd es llamado (post-commit)"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-03 — Re-consulta de pending cuando mark_superseded falla
# ═══════════════════════════════════════════════════════════════════════════════


def test_fix03_race_no_pending_inserts_independent(mem_engine):
    """8.5 — mark_superseded retorna False Y no hay pending activo
    (fue aprobado/rechazado concurrentemente) → se inserta un nuevo evento independiente
    con parent_event_id=None."""
    import app.modules.events.service as svc

    now = datetime.now(timezone.utc)
    event_data = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "agent-c31",
        "path": "/etc/shadow",
        "hash_detected": "newdeadbeef",
        "status": "pending",
    }

    call_count = [0]
    original_get_pending = svc.get_pending_event_for_path

    def fake_get_pending(session, path):
        call_count[0] += 1
        if call_count[0] == 1:
            # Primera llamada: hay un pending (para que entre al bloque mark_superseded)
            fake = MagicMock()
            fake.id = 999
            fake.version = 0
            fake.status = EventStatus.pending
            return fake
        # Segunda llamada (re-consulta post-race): no hay pending
        return None

    with patch.object(svc, "engine", mem_engine), \
         patch.object(svc, "get_pending_event_for_path", side_effect=fake_get_pending), \
         patch.object(svc, "mark_superseded", return_value=False):

        result = ingest_event(event_data, received_at=now, detected_at=now)

    assert result is not None, "debe insertar un evento independiente, no retornar None"
    assert result.event_id == event_data["event_id"]
    assert result.parent_event_id is None, "event insertado de forma independiente (sin parent)"


def test_fix03_race_still_pending_returns_none(mem_engine):
    """8.6 — mark_superseded retorna False Y todavía hay un pending activo
    (carrera legítima) → ingest_event retorna None."""
    import app.modules.events.service as svc

    now = datetime.now(timezone.utc)
    event_data = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "agent-c31",
        "path": "/etc/shadow",
        "hash_detected": "newdeadbeef",
        "status": "pending",
    }

    call_count = [0]

    def fake_get_pending(session, path):
        call_count[0] += 1
        # Ambas llamadas devuelven un pending activo
        fake = MagicMock()
        fake.id = 999
        fake.version = 0
        fake.status = EventStatus.pending
        return fake

    with patch.object(svc, "engine", mem_engine), \
         patch.object(svc, "get_pending_event_for_path", side_effect=fake_get_pending), \
         patch.object(svc, "mark_superseded", return_value=False):

        result = ingest_event(event_data, received_at=now, detected_at=now)

    assert result is None, "debe retornar None cuando todavía hay un pending activo (skip legítimo)"


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-04 — Paginación SQL real en list_events
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fix04_pagination_sql(authenticated_client):
    """8.7 — Insertar 120 eventos, pedir page=2&page_size=50:
    total=120, len(items)=50, page=2 (paginación real sin full table scan)."""
    from app.core.database import engine as real_engine

    ac, token = authenticated_client

    # Insertar 120 eventos pendientes directamente en Postgres.
    # `events.agent_id` tiene FK a `agents.agent_id`: el agente debe existir antes.
    with Session(real_engine) as s:
        if s.get(Agent, "agent-fix04") is None:
            s.add(Agent(
                agent_id="agent-fix04",
                status=AgentStatus.online,
                shared_secret_hex=os.urandom(32).hex(),
            ))
            s.commit()
        for i in range(120):
            ev = Event(
                event_id=f"fix04-evt-{i:04d}",
                agent_id="agent-fix04",
                path=f"/etc/test/file-{i:04d}.txt",
                hash_detected=f"hash{i:08x}",
                status=EventStatus.pending,
                detected_at=datetime.now(timezone.utc),
                received_at=datetime.now(timezone.utc),
            )
            s.add(ev)
        s.commit()

    resp = await ac.get(
        "/events",
        params={"page": 2, "page_size": 50, "include_superseded": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == 120, f"total debe ser 120, got {body['total']}"
    assert len(body["items"]) == 50, f"debe retornar 50 items, got {len(body['items'])}"
    assert body["page"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-05 — compact_chain retiene los más recientes
# ═══════════════════════════════════════════════════════════════════════════════


def test_fix05_compact_chain_retains_newest(mem_engine):
    """8.8 — 11 eventos superseded para el mismo path; compact_chain debe eliminar
    el MÁS ANTIGUO y retener los 10 más recientes."""
    path = "/etc/compact-test"
    base_time = datetime.now(timezone.utc)

    with Session(mem_engine) as session:
        events = []
        for i in range(11):
            ev = Event(
                event_id=f"eid-comp-{i}",
                agent_id="agent-c31",
                path=path,
                hash_detected=f"hash{i}",
                status=EventStatus.superseded,
                detected_at=base_time + timedelta(minutes=i),
                received_at=base_time + timedelta(minutes=i),
            )
            # SQLite no siempre respeta created_at auto; forzamos con update
            session.add(ev)
        session.commit()

        # Forzar created_at distintos para que el orden sea determinístico
        all_evts = session.exec(
            select(Event).where(Event.path == path).order_by(Event.id)
        ).all()
        for idx, ev in enumerate(all_evts):
            # Usamos detected_at como proxy (created_at tiene default NOW en Postgres)
            # En SQLite podemos sobreescribir vía SQL
            from sqlalchemy import text
            # La tabla es `events` (Event.__tablename__), no el `event` que
            # SQLModel derivaría por default. El nombre viejo hacía que este
            # UPDATE fallara con "no such table".
            session.execute(
                text("UPDATE events SET created_at = :ts WHERE id = :id"),
                {"ts": (base_time + timedelta(minutes=idx)).isoformat(), "id": ev.id},
            )
        session.commit()

        # El más antiguo es all_evts[0]
        oldest_id = all_evts[0].id
        newest_ids = {ev.id for ev in all_evts[1:]}  # 10 más recientes

        compact_chain(session, path)
        session.commit()

        remaining = session.exec(
            select(Event).where(Event.path == path, Event.status == EventStatus.superseded)
        ).all()

    remaining_ids = {ev.id for ev in remaining}
    assert len(remaining_ids) == 10, f"deben quedar exactamente 10 eventos, hay {len(remaining_ids)}"
    assert oldest_id not in remaining_ids, "el más antiguo debe haber sido eliminado"
    assert newest_ids.issubset(remaining_ids), "los 10 más recientes deben haberse retenido"


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-06 — Dedup antes de rate limit
# ═══════════════════════════════════════════════════════════════════════════════


def test_fix06_redelivery_does_not_consume_rate_budget(mem_engine):
    """8.9 — Re-entrega detectada en dedup NO llama a _rate_limiter.check().
    Tras la re-entrega, el slot 100 (límite) aún está disponible."""
    import app.modules.events.consumer as consumer_mod
    from app.modules.events.consumer import reset_rate_limiter, _rate_limiter

    # Setup: agente registrado
    secret = os.urandom(32)
    with Session(mem_engine) as s:
        a = Agent(
            agent_id="agent-ratelimit",
            status=AgentStatus.online,
            shared_secret_hex=secret.hex(),
        )
        s.add(a)
        s.commit()

    # Llenar el bucket hasta 99 (queda un slot disponible: el #100)
    reset_rate_limiter()
    for _ in range(99):
        _rate_limiter.check("agent-ratelimit")

    # Insertar un evento existente para simular re-entrega
    from app.core.streams import SCHEMA_VERSION, sign_payload
    existing_event_id = str(uuid.uuid4())
    with Session(mem_engine) as s:
        ev = Event(
            event_id=existing_event_id,
            agent_id="agent-ratelimit",
            path="/etc/redelivery",
            hash_detected="abc",
            status=EventStatus.pending,
            detected_at=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
        )
        s.add(ev)
        s.commit()

    # Construir re-entrega (event_id ya existe)
    payload = {
        "event_id": existing_event_id,
        "agent_id": "agent-ratelimit",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/redelivery",
        "hash_detected": "abc",
    }
    payload["signature"] = sign_payload(secret, payload)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    import app.modules.events.service as service_mod
    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(
            mock_client, "1-0", {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
        ))

    # La re-entrega debe XACK sin llamar rate limiter → slot #100 aún disponible
    mock_client.xack.assert_called_once()
    assert _rate_limiter.check("agent-ratelimit") is True, (
        "el slot #100 debe estar disponible: la re-entrega no debe haber consumido rate budget"
    )

    # Ahora el bucket tiene 100 → el próximo evento nuevo debe ser rate-limited
    assert _rate_limiter.check("agent-ratelimit") is False, (
        "el bucket está lleno (101): debe retornar False"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-07 — Validación explícita de event_id no-vacío
# ═══════════════════════════════════════════════════════════════════════════════


def test_fix07_empty_event_id_rejected_as_invalid_schema(mem_engine):
    """8.10 — Mensaje con event_id="" debe ser rechazado con reason=invalid_schema."""
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod
    from app.core.streams import SCHEMA_VERSION, sign_payload

    secret = os.urandom(32)
    with Session(mem_engine) as s:
        a = Agent(
            agent_id="agent-fix07",
            status=AgentStatus.online,
            shared_secret_hex=secret.hex(),
        )
        s.add(a)
        s.commit()

    # Payload válido en todo excepto event_id=""
    payload = {
        "event_id": "",
        "agent_id": "agent-fix07",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "abc123",
    }
    payload["signature"] = sign_payload(secret, payload)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(
            mock_client, "1-0", {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
        ))

    with Session(mem_engine) as s:
        rejections = s.exec(select(RejectedEventAudit)).all()

    assert len(rejections) == 1, "debe haber exactamente 1 rechazo auditado"
    assert rejections[0].reason == RejectionReason.invalid_schema, (
        f"reason debe ser invalid_schema, got {rejections[0].reason}"
    )
    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()  # no se publica event_ack


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-08 — Normalización UTC-aware de detected_at
# ═══════════════════════════════════════════════════════════════════════════════


def test_fix08_unparseable_detected_at_rejected_as_clock_skew(mem_engine):
    """8.11 — detected_at='not-a-date' → rechazado con reason=clock_skew."""
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod
    from app.core.streams import SCHEMA_VERSION, sign_payload

    secret = os.urandom(32)
    with Session(mem_engine) as s:
        a = Agent(
            agent_id="agent-fix08a",
            status=AgentStatus.online,
            shared_secret_hex=secret.hex(),
        )
        s.add(a)
        s.commit()

    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "agent-fix08a",
        "detected_at": "not-a-date",
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "abc123",
    }
    payload["signature"] = sign_payload(secret, payload)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(
            mock_client, "1-0", {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
        ))

    with Session(mem_engine) as s:
        rejections = s.exec(select(RejectedEventAudit)).all()

    assert len(rejections) == 1
    assert rejections[0].reason == RejectionReason.clock_skew, (
        f"detected_at no parseable debe rechazar con clock_skew, got {rejections[0].reason}"
    )


def test_fix08_naive_datetime_within_range_accepted(mem_engine):
    """8.12 — detected_at como naive ISO8601 (sin Z ni offset) dentro del rango
    de 5 minutos → el evento se acepta (sin TypeError por awareness mismatch)."""
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod
    from app.core.streams import SCHEMA_VERSION, sign_payload

    secret = os.urandom(32)
    with Session(mem_engine) as s:
        a = Agent(
            agent_id="agent-fix08b",
            status=AgentStatus.online,
            shared_secret_hex=secret.hex(),
        )
        s.add(a)
        s.commit()

    # naive datetime (sin tzinfo) dentro del rango de 5 min
    naive_dt = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "agent-fix08b",
        "detected_at": naive_dt,  # naive — sin Z ni offset
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/hosts",
        "hash_detected": "cafebabe1234",
    }
    payload["signature"] = sign_payload(secret, payload)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(
            mock_client, "1-0", {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
        ))

    # No debe haber rechazos — el evento es válido
    with Session(mem_engine) as s:
        rejections = s.exec(select(RejectedEventAudit)).all()
        events = s.exec(select(Event)).all()

    assert len(rejections) == 0, (
        f"no debe haber rechazos para naive datetime dentro del rango; "
        f"rejections: {[(r.reason, r.event_id) for r in rejections]}"
    )
    assert len(events) == 1, "el evento debe haberse insertado exitosamente"
    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_called_once()  # event_ack publicado


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-09 — datetime.utcnow() erradicado de módulos de producción
#
# D39/RN-133 (timestamps-timezone-aware): el predicado original buscaba la
# cadena literal "datetime.utcnow()" — CON paréntesis, es decir, la *llamada*.
# Los 9 usos reales de producción no eran llamadas: eran *referencias*
# pasadas como fábrica (`default_factory=datetime.utcnow`, sin paréntesis
# porque no se invoca ahí, SQLModel la invoca por fila), y pasaban por debajo
# del grep sin tocarlo. El test tenía el nombre del defecto, existía para
# atraparlo, y pasaba en verde con el defecto presente en 9 lugares — separado
# por dos caracteres. El predicado ahora es una regex con \b que detecta
# `datetime.utcnow` en CUALQUIER forma: llamada (`datetime.utcnow()`) o
# referencia bare (`datetime.utcnow`), y se prueba contra su propio caso
# negativo (test siguiente) para que un guard roto no vuelva a pasar en verde
# sin que nadie lo haya visto fallar nunca.
# ═══════════════════════════════════════════════════════════════════════════════

_UTCNOW_PATTERN = re.compile(r"datetime\.utcnow\b")


def _find_utcnow_offenders(content: str) -> bool:
    """True si `content` contiene `datetime.utcnow` en cualquier forma
    (llamada o referencia bare) — el predicado compartido entre el guard
    real (test_fix09_no_utcnow_in_production_modules) y su prueba negativa
    (test_fix09_guard_detects_bare_reference_form)."""
    return bool(_UTCNOW_PATTERN.search(content))


def test_fix09_no_utcnow_in_production_modules():
    """8.13 — Verificar que datetime.utcnow no aparece en ningún módulo
    de producción bajo backend/app/, ni como llamada ni como referencia
    bare (`default_factory=datetime.utcnow`)."""
    backend_app_root = os.path.join(
        os.path.dirname(__file__),  # backend/tests/
        "..",                        # backend/
        "app",
    )
    py_files = glob.glob(os.path.join(backend_app_root, "**", "*.py"), recursive=True)
    assert py_files, "no se encontraron archivos .py en backend/app/"

    offenders: list[str] = []
    for fpath in py_files:
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
        if _find_utcnow_offenders(content):
            offenders.append(os.path.relpath(fpath))

    assert offenders == [], (
        f"datetime.utcnow encontrado en módulos de producción: {offenders}\n"
        "Reemplazar con datetime.now(timezone.utc), sea llamada o "
        "default_factory=datetime.utcnow"
    )


def test_fix09_guard_detects_bare_reference_form():
    """Caso negativo del guard (D39/RN-133): un fragmento con la forma
    bare `default_factory=datetime.utcnow` — la que dejó pasar el defecto
    original, SIN paréntesis — debe ser rechazado. Un guard que nunca se vio
    fallar contra su propio caso negativo no es evidencia de nada; esta es
    la prueba de que el agujero de dos caracteres está cerrado."""
    offending_fragment = "    created_at: datetime = Field(default_factory=datetime.utcnow)\n"
    assert _find_utcnow_offenders(offending_fragment), (
        "el guard debe rechazar la forma bare default_factory=datetime.utcnow"
    )

    # Y sigue detectando la forma con paréntesis que ya cubría.
    call_fragment = "    now = datetime.utcnow()\n"
    assert _find_utcnow_offenders(call_fragment), (
        "el guard debe seguir rechazando la forma con paréntesis datetime.utcnow()"
    )

    # Control: código correcto no dispara el guard.
    correct_fragment = "    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))\n"
    assert not _find_utcnow_offenders(correct_fragment), (
        "el guard no debe rechazar datetime.now(timezone.utc)"
    )
