"""
Tests de Change 59 (`notify-isolate-executor-lane`, D76/RN-170) — grupo 5 de
tasks.md.

Cubre el aislamiento de recursos entre el carril de ingesta y el carril de
notificación: executor dedicado (5.1, 5.2, 5.3), cota de entregas concurrentes
en las tres puertas de entrada (5.4, 5.5, 5.6), estabilidad de
`notification_id` (5.7), advertencia de backlog disparada por flanco (5.8), y
el invariante de dimensionamiento desde el lado de la aplicación (5.9).

Los ítems 5.10 y 5.11 no se duplican acá: 5.10 (cascada de canales y política
de reintentos sin cambios) lo cubre la suite existente y NO modificada de
`test_notifications.py` (`test_notify_event_retry_3x_then_dlq`,
`test_n8n_retry_ladder_finishes_before_real_fallback`, etc.); 5.11 (FIFO e
idempotencia, ítems 40/41 del protocolo) lo cubre `test_ingest_offload_
blocking_db.py` (`test_fifo_order_preserved_after_batch_drain`,
`test_no_duplicate_after_transient_db_error_and_pel_redelivery`), tampoco
modificado por esta change.

Los tests de aislamiento estructural (5.1, 5.2, 5.7, 5.9) usan SQLite
in-memory (mismo patrón que test_notifications.py). Los tests de concurrencia
real (5.4, 5.5, 5.6, 5.8) usan el engine de Postgres real de la suite —
`app.core.database.engine`, truncado y aislado por `_db_isolation`
(conftest.py) antes de cada test— porque ejercitan de a dos o más hilos del
executor de notificación tocando la base de datos AL MISMO TIEMPO: el módulo
`sqlite3` de la stdlib no es seguro para acceso concurrente genuino desde
varios hilos sobre la MISMA conexión, aun con `check_same_thread=False` y
`StaticPool` (eso desactiva sólo la verificación, no la garantía), y produce
fallos intermitentes que no tienen nada que ver con el código bajo prueba.

Se saltea si psycopg/libpq no está disponible porque `conftest.py` lo exige a
nivel de sesión.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

import app.modules.alerts.service as alerts_mod
from app.core import executors as executors_mod
from app.core.config import Settings, _DB_CONNECTIONS_RESERVED_NON_EXECUTOR
from app.core.database import engine as real_engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.alerts.models import Alert, AlertSeverity
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RuleSeverity


# ── Fixtures compartidas (mismo patrón que test_notifications.py) ────────────


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
def agent(session) -> Agent:
    a = Agent(agent_id="agent-001", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _make_event(session: Session, path: str = "/etc/passwd") -> Event:
    event = Event(
        event_id=f"evt-{id(session)}-{path}-{time.monotonic_ns()}",
        agent_id="agent-001",
        path=path,
        hash_detected="abc123",
        status=EventStatus.pending,
        severity=RuleSeverity.critical,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _make_alert(session: Session, event_id: int) -> Alert:
    alert = Alert(event_id=event_id, severity=AlertSeverity.critical)
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def _n8n_only_settings() -> MagicMock:
    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
    mock_settings.smtp_host = ""
    mock_settings.webhook_fallback_url = ""
    return mock_settings


def _reset_backlog_state() -> None:
    alerts_mod._notify_waiting_count = 0
    alerts_mod._notify_backlog_warned = False


# ── Fixtures/helpers para tests de concurrencia REAL (Postgres) ─────────────
#
# `_db_isolation` (conftest.py, autouse) trunca todas las tablas y resiembra
# el admin antes de cada test — estos helpers sólo agregan la fila `agents`
# que `events.agent_id` exige por FK.


@pytest.fixture()
def real_agent() -> Agent:
    with Session(real_engine) as db_session:
        a = Agent(agent_id="agent-concurrency", status=AgentStatus.online)
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        db_session.expunge(a)
    return a


def _make_real_event(path: str) -> Event:
    with Session(real_engine) as db_session:
        event = Event(
            event_id=f"evt-real-{path}-{time.monotonic_ns()}",
            agent_id="agent-concurrency",
            path=path,
            hash_detected="abc123",
            status=EventStatus.pending,
            severity=RuleSeverity.critical,
            detected_at=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
        )
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)
        db_session.expunge(event)
    return event


def _make_real_alert(event_id: int, **overrides: object) -> Alert:
    with Session(real_engine) as db_session:
        alert = Alert(event_id=event_id, severity=AlertSeverity.critical)
        for key, value in overrides.items():
            setattr(alert, key, value)
        db_session.add(alert)
        db_session.commit()
        db_session.refresh(alert)
        db_session.expunge(alert)
    return alert


# ── 5.1 — El trabajo de notificación corre en el executor de notificación ────


async def test_notify_work_runs_on_notify_executor_thread(mem_engine, session, agent) -> None:
    """
    Los seis call sites de `alerts/service.py` deben ejecutar en un hilo del
    executor de notificación (prefijo `test-fim-notify`, instalado por el
    fixture de conftest) y NUNCA en el executor de ingesta
    (`test-fim-db`) — la propiedad estructural que D-1 del design declara.
    """
    event = _make_event(session)

    seen_thread_names: list[str] = []

    orig_create_alert_row = alerts_mod._create_alert_row
    orig_prepare = alerts_mod._prepare_notification
    orig_mark_delivered = alerts_mod._mark_delivered

    def spy_create_alert_row(alert):
        seen_thread_names.append(threading.current_thread().name)
        return orig_create_alert_row(alert)

    def spy_prepare(alert_id):
        seen_thread_names.append(threading.current_thread().name)
        return orig_prepare(alert_id)

    def spy_mark_delivered(*args, **kwargs):
        seen_thread_names.append(threading.current_thread().name)
        return orig_mark_delivered(*args, **kwargs)

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "_create_alert_row", side_effect=spy_create_alert_row), \
            patch.object(alerts_mod, "_prepare_notification", side_effect=spy_prepare), \
            patch.object(alerts_mod, "_mark_delivered", side_effect=spy_mark_delivered), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=True), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"):
        await alerts_mod.notify_if_applicable(event)

    assert seen_thread_names, "ningún call site instrumentado corrió"
    for name in seen_thread_names:
        assert name.startswith("test-fim-notify"), (
            f"{name} no pertenece al executor de notificación — el aislamiento "
            "de pools se rompió"
        )
        assert not name.startswith("test-fim-db"), (
            f"{name} corrió en el executor de INGESTA — exactamente el "
            "acoplamiento que esta change existe para romper"
        )


# ── 5.2 — Ningún call site del camino de notificación pasa None ─────────────


def test_no_none_executor_in_notification_source() -> None:
    """
    Inspección de código, mismo criterio que
    `test_notification_id_is_built_once_per_notify_event`
    (test_notification_payload_contract.py): el modo de falla es SILENCIOSO
    —un `run_in_executor(None, ...)` nuevo funciona igual y el aislamiento
    desaparece sin señal— así que se fija con una búsqueda textual, no con
    comportamiento observable en un único test.
    """
    import inspect

    source = inspect.getsource(alerts_mod)
    code_lines = [
        line for line in source.splitlines() if not line.strip().startswith("#")
    ]
    offending = [line for line in code_lines if "run_in_executor(None" in line]
    assert not offending, (
        "un run_in_executor(None, ...) en alerts/service.py pide el executor "
        "de INGESTA — el camino de notificación debe referenciar su propio "
        f"executor de forma explícita (D76/RN-170, D-2 del design): {offending}"
    )
    # Los seis call sites deben referenciar el accesor del executor de
    # notificación.
    assert source.count("get_notify_executor()") == 6, (
        "se esperan exactamente seis call sites de run_in_executor "
        "referenciando el executor de notificación en el camino por evento"
    )


# ── 5.3 — Una ráfaga de notificaciones no retrasa la ingesta ─────────────────


async def test_notify_burst_does_not_delay_ingest_executor() -> None:
    """
    El test que corresponde directamente al problema que la change existe
    para resolver: con el executor de notificación saturado, una operación
    de base de datos del carril de ingesta obtiene un hilo del OTRO pool sin
    esperar a que el trabajo de notificación termine.
    """
    notify_executor = executors_mod.get_notify_executor()
    ingest_executor = executors_mod.get_ingest_executor()

    block = threading.Event()

    def blocking_notify_job() -> None:
        block.wait(timeout=5)

    # Saturar el executor de notificación bien por encima de su capacidad
    # (4 hilos en el fixture de test) para que quede un backlog real en su
    # cola FIFO.
    filler_futures = [notify_executor.submit(blocking_notify_job) for _ in range(20)]

    try:
        start = time.monotonic()
        result = await asyncio.get_running_loop().run_in_executor(
            ingest_executor, lambda: "ingest-ok"
        )
        elapsed = time.monotonic() - start
    finally:
        block.set()
        for f in filler_futures:
            f.result(timeout=5)

    assert result == "ingest-ok"
    assert elapsed < 1.0, (
        f"la operación de ingesta tardó {elapsed:.3f}s con el executor de "
        "notificación saturado — los pools dejaron de estar aislados"
    )


# ── 5.4 / 5.5 — La cota se respeta en las tres puertas, y el desborde espera ─


async def test_concurrency_cap_respected_via_consumer_door(real_agent) -> None:
    """Puerta 1: el consumer (fire-and-forget por evento)."""
    cap = 2
    n_notifications = 3 * cap
    pairs = []
    for i in range(n_notifications):
        event = _make_real_event(f"/etc/file{i}")
        alert = _make_real_alert(event.id)
        pairs.append((alert, event))

    concurrent_in_flight = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def fake_send_n8n(payload, url):
        nonlocal concurrent_in_flight, max_concurrent
        async with lock:
            concurrent_in_flight += 1
            max_concurrent = max(max_concurrent, concurrent_in_flight)
        await asyncio.sleep(0.03)
        async with lock:
            concurrent_in_flight -= 1
        return True

    with patch.object(alerts_mod, "_notify_delivery_semaphore", asyncio.Semaphore(cap)), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", side_effect=fake_send_n8n):
        await asyncio.gather(*(alerts_mod.notify_event(a, e) for a, e in pairs))

    assert max_concurrent <= cap, f"se vieron {max_concurrent} entregas en vuelo, cota={cap}"

    with Session(real_engine) as check_session:
        for alert, _event in pairs:
            refreshed = check_session.get(Alert, alert.id)
            assert refreshed is not None
            assert refreshed.delivered_at is not None, "el desborde no debe perder ninguna entrega"
            assert refreshed.failed_at is None, "el desborde no debe marcar fallo por la cota"


async def test_concurrency_cap_respected_via_startup_recovery_door(real_agent) -> None:
    """
    Puerta 2: `recover_pending_notifications`, cuyo `asyncio.gather` hoy
    dispara TODAS las pendientes de golpe — la cota debe acotarla igual,
    SIN que se toque su lógica de selección (D-4 del design).
    """
    cap = 2
    n_notifications = 3 * cap
    for i in range(n_notifications):
        event = _make_real_event(f"/etc/recovery{i}")
        _make_real_alert(event.id, notification_id=f"recovery-{i}")

    concurrent_in_flight = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def fake_send_n8n(payload, url):
        nonlocal concurrent_in_flight, max_concurrent
        async with lock:
            concurrent_in_flight += 1
            max_concurrent = max(max_concurrent, concurrent_in_flight)
        await asyncio.sleep(0.03)
        async with lock:
            concurrent_in_flight -= 1
        return True

    with patch.object(alerts_mod, "_notify_delivery_semaphore", asyncio.Semaphore(cap)), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", side_effect=fake_send_n8n):
        await alerts_mod.recover_pending_notifications()

    assert max_concurrent <= cap, f"se vieron {max_concurrent} entregas en vuelo, cota={cap}"

    with Session(real_engine) as check_session:
        delivered = check_session.exec(
            select(Alert).where(Alert.delivered_at.is_not(None))  # type: ignore[union-attr]
        ).all()
    assert len(delivered) == n_notifications, "todas las pendientes deben terminar entregándose"


async def test_concurrency_cap_respected_via_manual_retry_door(real_agent) -> None:
    """Puerta 3: el reintento manual desde la DLQ (`retry_alert`)."""
    cap = 2
    n_notifications = 3 * cap
    alert_ids = []
    for i in range(n_notifications):
        event = _make_real_event(f"/etc/retry{i}")
        alert = _make_real_alert(
            event.id, failed_at=datetime.now(timezone.utc), last_error="prior_failure"
        )
        alert_ids.append(alert.id)

    concurrent_in_flight = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def fake_send_n8n(payload, url):
        nonlocal concurrent_in_flight, max_concurrent
        async with lock:
            concurrent_in_flight += 1
            max_concurrent = max(max_concurrent, concurrent_in_flight)
        await asyncio.sleep(0.03)
        async with lock:
            concurrent_in_flight -= 1
        return True

    preexisting = set(alerts_mod._background_tasks)
    with patch.object(alerts_mod, "_notify_delivery_semaphore", asyncio.Semaphore(cap)), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", side_effect=fake_send_n8n):
        with Session(real_engine) as retry_session:
            for alert_id in alert_ids:
                await alerts_mod.retry_alert(alert_id, retry_session, 1)
            # `retry_alert` deja el Alert/Event de cada tarea de fondo atados
            # a ESTA Session (expire_on_commit=True los expira, no los
            # desliga): esperar las tareas ANTES de cerrar el `with`, o la
            # primera lectura de atributo dentro de `notify_event` dispara un
            # DetachedInstanceError que no tiene nada que ver con la cota.
            await asyncio.gather(*(alerts_mod._background_tasks - preexisting))

    assert max_concurrent <= cap, f"se vieron {max_concurrent} entregas en vuelo, cota={cap}"


# ── 5.6 — La creación de la fila Alert no espera a la cota de entregas ──────


async def test_alert_creation_does_not_wait_for_delivery_cap(real_agent) -> None:
    cap = 1
    blocker = asyncio.Event()

    async def blocking_send_n8n(payload, url):
        await blocker.wait()
        return True

    filler_event = _make_real_event("/etc/filler")
    filler_alert = _make_real_alert(filler_event.id)

    published: list[dict] = []

    with patch.object(alerts_mod, "_notify_delivery_semaphore", asyncio.Semaphore(cap)), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", side_effect=blocking_send_n8n), \
            patch.object(alerts_mod.alerts_broadcaster, "publish", side_effect=lambda p: published.append(p)):

        # Llenar la cota (1) con una entrega que queda bloqueada indefinidamente.
        filler_task = asyncio.create_task(alerts_mod.notify_event(filler_alert, filler_event))
        await asyncio.sleep(0.05)  # dejar que adquiera el único permiso disponible

        # Con la cota completa, un evento nuevo debe crear su fila y publicar
        # al broadcaster SSE SIN esperar un permiso de entrega.
        new_event = _make_real_event("/etc/passwd")
        notify_task = asyncio.create_task(alerts_mod.notify_if_applicable(new_event))
        await asyncio.sleep(0.05)

        assert len(published) == 1, "la fila Alert y su publicación SSE deben ocurrir sin esperar la cota"
        with Session(real_engine) as check_session:
            alerts_in_db = check_session.exec(
                select(Alert).where(Alert.event_id == new_event.id)  # type: ignore[union-attr]
            ).all()
        assert len(alerts_in_db) == 1

        assert not notify_task.done(), (
            "notify_if_applicable no debería completar todavía: su entrega "
            "sigue esperando el permiso de la cota, que está lleno"
        )

        blocker.set()
        await asyncio.gather(filler_task, notify_task)


# ── 5.7 — notification_id estable a lo largo de la escalera completa ───────


async def test_notification_id_stable_across_full_ladder_and_fallback(mem_engine, session, agent) -> None:
    """
    Fuerza los cuatro intentos de n8n (todos fallando) más la cascada de
    fallbacks (SMTP entrega) y verifica que TODOS los intentos —incluido el
    de SMTP— transportan el mismo `notification_id` que quedó persistido en
    la fila `Alert`.
    """
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    seen_notification_ids: list[str] = []

    async def failing_n8n(payload, url):
        seen_notification_ids.append(payload["notification_id"])
        return False

    async def succeeding_smtp(payload, cfg):
        seen_notification_ids.append(payload["notification_id"])
        return True

    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
    mock_settings.smtp_host = "smtp.local"
    mock_settings.webhook_fallback_url = ""

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", mock_settings), \
            patch.object(alerts_mod, "send_n8n", side_effect=failing_n8n), \
            patch.object(alerts_mod, "send_smtp", side_effect=succeeding_smtp), \
            patch("asyncio.sleep", new_callable=AsyncMock):
        await alerts_mod.notify_event(alert, event)

    session.refresh(alert)
    assert alert.delivered_at is not None
    assert alert.notification_id is not None
    assert len(seen_notification_ids) == 5, "4 intentos de n8n + 1 de SMTP"
    assert len(set(seen_notification_ids)) == 1, (
        "notification_id cambió entre intentos — se rompió D40/RN-134/D41/RN-135"
    )
    assert seen_notification_ids[0] == alert.notification_id


# ── 5.8 — La advertencia de backlog se dispara por flanco ───────────────────


async def test_backlog_warning_fires_once_per_edge_not_per_notification(real_agent) -> None:
    cap = 1
    threshold = 2
    n_notifications = 5  # bien por encima del umbral, para probar que NO escala con N

    pairs = []
    for i in range(n_notifications):
        event = _make_real_event(f"/etc/backlog{i}")
        alert = _make_real_alert(event.id)
        pairs.append((alert, event))

    blocker = asyncio.Event()

    async def blocking_send_n8n(payload, url):
        await blocker.wait()
        return True

    _reset_backlog_state()
    try:
        with patch.object(alerts_mod, "_notify_delivery_semaphore", asyncio.Semaphore(cap)), \
                patch.object(alerts_mod, "_notify_backlog_warning_threshold", threshold), \
                patch.object(alerts_mod, "settings", _n8n_only_settings()), \
                patch.object(alerts_mod, "send_n8n", side_effect=blocking_send_n8n), \
                patch.object(alerts_mod, "log") as mock_log:

            tasks = [asyncio.create_task(alerts_mod.notify_event(a, e)) for a, e in pairs]
            await asyncio.sleep(0.1)  # dejar que se acumule el backlog de espera

            high_calls = [c for c in mock_log.warning.call_args_list if c.args[0] == "notify.delivery_backlog_high"]
            assert len(high_calls) == 1, (
                f"se esperaba UNA advertencia de backlog alto, se vieron {len(high_calls)}"
            )

            blocker.set()
            await asyncio.gather(*tasks)

            cleared_calls = [
                c for c in mock_log.warning.call_args_list if c.args[0] == "notify.delivery_backlog_cleared"
            ]
            assert len(cleared_calls) == 1, (
                f"se esperaba UNA advertencia de backlog recuperado, se vieron {len(cleared_calls)}"
            )
    finally:
        _reset_backlog_state()


# ── 5.9 — Invariante de dimensionamiento desde el lado de la aplicación ────


def test_installed_executors_sum_within_pool_capacity() -> None:
    """
    Complementa 1.8: con la configuración por defecto de `Settings`
    (construida de forma independiente al fixture de test, que usa tamaños
    propios), la SUMA de los dos executors sigue siendo <=
    pool_size + max_overflow - reserva (D76/RN-170, D-5 del design).
    """
    default_settings = Settings(
        database_url="postgresql+psycopg://fim:test@localhost:5439/fim_test",
        valkey_url="valkey://localhost:6390",
        jwt_secret_current="x",
    )

    total = default_settings.db_executor_max_workers + default_settings.db_notify_executor_max_workers
    max_allowed = (
        default_settings.db_pool_size
        + default_settings.db_max_overflow
        - _DB_CONNECTIONS_RESERVED_NON_EXECUTOR
    )
    assert total <= max_allowed
    assert default_settings.db_notify_executor_max_workers < default_settings.db_executor_max_workers, (
        "el carril de notificación debe quedarse con la porción MENOR — ante "
        "cualquier duda de dimensionamiento, el carril que no puede "
        "degradarse (ingesta) se queda con la porción mayor (D-5 del design)"
    )
