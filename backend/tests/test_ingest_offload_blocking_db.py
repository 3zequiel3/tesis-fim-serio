"""
Tests de Change 58 (`ingest-offload-blocking-db`, D75/RN-169).

Cubre el grupo 7 de tasks.md — FIFO, no-duplicación y despacho secuencial NO
degradados tras mover el carril feliz de ingesta y la cadena de notificación
por evento al executor — más el grupo 5.4 (`_RateLimiter` thread-safe) y una
verificación de aplicación del invariante de dimensionamiento de `Settings`
(grupo 1.6 / 7.8).

Usa SQLite in-memory (mismo patrón que test_consumer.py / test_c22_consumer.py
/ test_notifications.py). Se saltea si psycopg/libpq no está disponible.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus
from app.modules.alerts.models import Alert, AlertSeverity
from app.modules.events.models import Event, RejectedEventAudit, RejectionReason
from app.modules.rules.models import RuleSeverity


# ── Fixtures compartidas (mismo patrón que los tests de consumer existentes) ──

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
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, shared_secret: bytes) -> Agent:
    a = Agent(
        agent_id="agent-test",
        status=AgentStatus.offline,
        shared_secret_hex=shared_secret.hex(),
    )
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def _make_msg_data(payload: dict) -> dict:
    return {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}


def _make_payload(
    agent_id: str,
    shared_secret: bytes,
    path: str = "/etc/passwd",
    detected_at: datetime | None = None,
) -> dict:
    from app.core.streams import SCHEMA_VERSION, sign_payload

    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "detected_at": (detected_at or datetime.now(timezone.utc)).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": path,
        "hash_detected": "abc123",
        "process_pid": 1234,
        "process_uid": 0,
        "process_exe": "/usr/bin/test",
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    return payload


# ── 7.1 — El despacho del lote sigue siendo secuencial ────────────────────────

async def test_batch_dispatch_is_strictly_sequential() -> None:
    """
    Red de contención de D-2 del design: si alguien "aprovecha y paraleliza el
    lote", este test falla. Con un `_handle_message` instrumentado que duerme
    entre su entrada y su salida, nunca debe haber más de una invocación en
    vuelo en simultáneo.
    """
    import app.modules.events.consumer as consumer_mod

    concurrent_in_flight = 0
    max_concurrent = 0
    call_log: list[tuple[str, str]] = []

    async def fake_handle_message(client, msg_id, msg_data) -> None:
        nonlocal concurrent_in_flight, max_concurrent
        concurrent_in_flight += 1
        max_concurrent = max(max_concurrent, concurrent_in_flight)
        call_log.append(("start", msg_id))
        await asyncio.sleep(0.01)
        call_log.append(("end", msg_id))
        concurrent_in_flight -= 1

    messages = [(f"{i}-0", {"data": "{}"}) for i in range(5)]
    mock_client = AsyncMock()
    mock_client.xreadgroup = AsyncMock(return_value=[("events", messages)])

    with patch.object(consumer_mod, "_handle_message", fake_handle_message):
        await consumer_mod._process_batch(mock_client, ">")

    assert max_concurrent == 1, "más de un _handle_message en vuelo — el despacho dejó de ser secuencial"
    # El orden de entrada/salida respeta estrictamente start(n), end(n), start(n+1), end(n+1), ...
    for i in range(0, len(call_log), 2):
        assert call_log[i] == ("start", f"{i // 2}-0")
        assert call_log[i + 1] == ("end", f"{i // 2}-0")


# ── 7.2 — Orden FIFO preservado tras un drenaje (ítem 40) ─────────────────────

async def test_fifo_order_preserved_after_batch_drain(mem_engine, agent, shared_secret) -> None:
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    n = 10
    base_time = datetime.now(timezone.utc)
    payloads = [
        _make_payload(
            "agent-test", shared_secret, path=f"/etc/file{i}",
            detected_at=base_time + timedelta(seconds=i),
        )
        for i in range(n)
    ]
    messages = [(f"{i}-0", _make_msg_data(p)) for i, p in enumerate(payloads)]

    mock_client = AsyncMock()
    mock_client.xreadgroup = AsyncMock(return_value=[("events", messages)])
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine):
        await consumer_mod._process_batch(mock_client, ">")

    with Session(mem_engine) as session:
        # El orden de INSERCIÓN (id ascendente) debe reproducir el orden de
        # generación — y ese orden, ordenado por detected_at, es monótono.
        events = session.exec(select(Event).order_by(Event.id.asc())).all()  # type: ignore[union-attr]

    assert len(events) == n
    assert [e.path for e in events] == [f"/etc/file{i}" for i in range(n)]
    detected_ats = [e.detected_at for e in events]
    assert detected_ats == sorted(detected_ats), "el orden por detected_at dejó de ser monótono"


# ── 7.3 — Cero duplicados, incluida la reentrega del PEL (ítem 41) ────────────

async def test_no_duplicate_after_transient_db_error_and_pel_redelivery(
    mem_engine, agent, shared_secret,
) -> None:
    """
    Reentrega del mismo event_id tras un error transitorio de DB en el primer
    intento (el mensaje queda en la PEL, sin XACK) — la segunda entrega debe
    resolver con éxito sin duplicar la fila en `events`.
    """
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    payload = _make_payload("agent-test", shared_secret)

    mock_client1 = AsyncMock()
    mock_client1.xack = AsyncMock()
    mock_client1.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine), \
            patch.object(consumer_mod, "_ingest", side_effect=SQLAlchemyError("connection refused")):
        await consumer_mod._handle_message(mock_client1, "1-0", _make_msg_data(payload))

    mock_client1.xack.assert_not_called()  # queda en la PEL, sin duplicar ni perder el mensaje

    mock_client2 = AsyncMock()
    mock_client2.xack = AsyncMock()
    mock_client2.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine):
        await consumer_mod._handle_message(mock_client2, "1-0", _make_msg_data(payload))

    mock_client2.xack.assert_called_once()
    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
        dup_check = session.exec(
            select(Event.event_id, Event.id)  # type: ignore[arg-type]
        ).all()
    assert len(events) == 1
    assert events[0].event_id == payload["event_id"]
    event_ids = [row[0] for row in dup_check]
    assert len(event_ids) == len(set(event_ids)), "event_id duplicado tras la reentrega"


# ── 7.4 — El objeto persistido cruza el límite del executor sin disparar I/O ──

def test_ingest_result_survives_executor_boundary_without_io(mem_engine, agent, shared_secret) -> None:
    """
    `_ingest` corre de punta a punta en un hilo separado (reproduce el cruce
    real del executor). El `Event` que devuelve debe tener sus atributos ya
    materializados (session.expunge antes del commit, events/service.py) —
    si ese expunge desapareciera, leer un atributo expirado en un objeto
    detached levantaría DetachedInstanceError acá mismo.
    """
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    payload = _make_payload("agent-test", shared_secret)
    received_at = datetime.now(timezone.utc)
    detected_at = datetime.now(timezone.utc)

    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine):
        with ThreadPoolExecutor(max_workers=1) as executor:
            outcome = executor.submit(
                consumer_mod._ingest, payload, received_at, detected_at, "agent-test",
            ).result()

    event = outcome.event
    assert event is not None
    # Ninguna de estas lecturas debe disparar una consulta ni levantar
    # DetachedInstanceError — la Session que las persistió ya está cerrada.
    assert event.id is not None
    assert event.status is not None
    assert event.severity is not None
    assert event.path == payload["path"]


# ── 7.5 — _get_agent_auth e _ingest corren fuera del event loop ───────────────

async def test_get_agent_auth_and_ingest_run_off_the_event_loop(mem_engine, agent, shared_secret) -> None:
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    main_thread_id = threading.get_ident()
    payload = _make_payload("agent-test", shared_secret)
    seen_thread_ids: dict[str, int] = {}

    orig_get_agent_auth = consumer_mod._get_agent_auth
    orig_ingest = consumer_mod._ingest

    def spy_get_agent_auth(agent_id):
        seen_thread_ids["_get_agent_auth"] = threading.get_ident()
        return orig_get_agent_auth(agent_id)

    def spy_ingest(*args, **kwargs):
        seen_thread_ids["_ingest"] = threading.get_ident()
        return orig_ingest(*args, **kwargs)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine), \
            patch.object(consumer_mod, "_get_agent_auth", side_effect=spy_get_agent_auth), \
            patch.object(consumer_mod, "_ingest", side_effect=spy_ingest):
        await consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload))

    assert "_get_agent_auth" in seen_thread_ids and seen_thread_ids["_get_agent_auth"] != main_thread_id
    assert "_ingest" in seen_thread_ids and seen_thread_ids["_ingest"] != main_thread_id


# ── 7.6 — Semántica de errores del carril feliz sin cambios ───────────────────
#
# Cubierto por los tests EXISTENTES y NO modificados de test_c22_consumer.py:
# test_invalid_transition_xack_audits_and_terminal_nack y
# test_sqlalchemy_error_no_xack_stays_in_pel. Se listan acá como referencia
# de cobertura, no se duplican.


# ── 7.7 — Alta de Alert y marca de entrega fuera del event loop ───────────────

async def test_alert_creation_and_delivery_run_off_the_event_loop() -> None:
    """
    `_create_alert_row` (creación de la fila Alert) y `_mark_delivered`
    (marca de entrega) deben ejecutarse en un hilo distinto del loop, y el
    payload publicado al broadcaster SSE debe conservar exactamente su forma
    previa (D75/RN-169, D-7 del design).
    """
    import app.modules.alerts.service as alerts_mod
    from app.modules.events.models import EventStatus

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        event = Event(
            event_id="evt-off-loop",
            agent_id="agent-test",
            path="/etc/passwd",
            hash_detected="abc123",
            status=EventStatus.pending,
            severity=RuleSeverity.critical,
            detected_at=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        session.expunge(event)

    main_thread_id = threading.get_ident()
    seen_thread_ids: dict[str, int] = {}

    orig_create_alert_row = alerts_mod._create_alert_row
    orig_mark_delivered = alerts_mod._mark_delivered

    def spy_create_alert_row(alert):
        seen_thread_ids["_create_alert_row"] = threading.get_ident()
        return orig_create_alert_row(alert)

    def spy_mark_delivered(*args, **kwargs):
        seen_thread_ids["_mark_delivered"] = threading.get_ident()
        return orig_mark_delivered(*args, **kwargs)

    published: list[dict] = []
    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
    mock_settings.smtp_host = ""
    mock_settings.webhook_fallback_url = ""

    with patch.object(alerts_mod, "engine", engine), \
            patch.object(alerts_mod, "settings", mock_settings), \
            patch.object(alerts_mod, "_create_alert_row", side_effect=spy_create_alert_row), \
            patch.object(alerts_mod, "_mark_delivered", side_effect=spy_mark_delivered), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=True), \
            patch.object(alerts_mod.alerts_broadcaster, "publish", side_effect=lambda p: published.append(p)):
        await alerts_mod.notify_if_applicable(event)

    assert seen_thread_ids.get("_create_alert_row") not in (None, main_thread_id)
    assert seen_thread_ids.get("_mark_delivered") not in (None, main_thread_id)

    assert len(published) == 1
    payload = published[0]
    # Forma exacta previa al cambio (alerts/service.py:124-137) — esta tarea
    # mueve DÓNDE corre el trabajo, no QUÉ hace.
    assert set(payload.keys()) == {
        "id", "event_id", "severity", "status", "channel",
        "delivered_at", "failed_at", "last_error", "retry_count", "created_at",
    }
    assert payload["event_id"] == event.id
    assert payload["severity"] == "critical"
    assert payload["status"] == "pending"

    with Session(engine) as session:
        alerts = session.exec(select(Alert)).all()
    assert len(alerts) == 1
    assert alerts[0].delivered_at is not None
    assert alerts[0].severity == AlertSeverity.critical


# ── 7.8 — Invariante de dimensionamiento aplicado ─────────────────────────────

def test_executor_max_workers_within_pool_capacity_minus_reserve() -> None:
    """
    Complementa 1.6 desde el lado de la aplicación: con la configuración por
    defecto, el número de hilos del executor instalado es <= pool_size +
    max_overflow - la reserva documentada.
    """
    from app.core.config import Settings, _DB_CONNECTIONS_RESERVED_NON_EXECUTOR

    settings = Settings()
    assert settings.db_executor_max_workers <= (
        settings.db_pool_size + settings.db_max_overflow - _DB_CONNECTIONS_RESERVED_NON_EXECUTOR
    )


# ── 1.6 — Validación fail-fast de Settings ────────────────────────────────────

def test_settings_defaults_satisfy_invariant() -> None:
    from app.core.config import Settings

    settings = Settings()
    assert settings.db_pool_size == 10
    assert settings.db_max_overflow == 10
    assert settings.db_executor_max_workers == 10


def test_settings_executor_workers_exceeding_pool_capacity_aborts() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(db_executor_max_workers=11)  # 11 > 10+10-10=10


def test_settings_pool_size_zero_aborts() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(db_pool_size=0)


def test_settings_max_overflow_negative_aborts() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(db_max_overflow=-1)


def test_settings_executor_workers_zero_aborts() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(db_executor_max_workers=0)


# ── 5.4 — _RateLimiter thread-safe: admisiones exactas bajo concurrencia ──────

def test_rate_limiter_thread_safe_exact_admission_count() -> None:
    """
    `check()` invocado concurrentemente desde varios hilos sobre el mismo
    agent_id no debe admitir más eventos que el límite configurado, ni uno
    menos por una condición de carrera perdida (D75/RN-169, D-6 del design).
    """
    import app.modules.events.consumer as consumer_mod

    limiter = consumer_mod._RateLimiter(limit=100, window_s=60.0)
    admitted = 0
    admitted_lock = threading.Lock()

    def worker() -> None:
        nonlocal admitted
        if limiter.check("agent-concurrent"):
            with admitted_lock:
                admitted += 1

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker) for _ in range(500)]
        for f in futures:
            f.result()

    assert admitted == 100


def test_rate_limiter_seconds_until_available_thread_safe() -> None:
    """`seconds_until_available` no debe lanzar ni corromper el estado cuando
    se invoca concurrentemente con `check()` desde otros hilos (simula el
    cruce loop/executor descrito en D-6 del design)."""
    import app.modules.events.consumer as consumer_mod

    limiter = consumer_mod._RateLimiter(limit=10, window_s=60.0)
    errors: list[Exception] = []

    def checker() -> None:
        try:
            for _ in range(50):
                limiter.check("agent-mixed")
        except Exception as exc:  # pragma: no cover - solo si el lock falla
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(50):
                limiter.seconds_until_available("agent-mixed")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(checker) for _ in range(5)] + [
            executor.submit(reader) for _ in range(5)
        ]
        for f in futures:
            f.result()

    assert not errors
