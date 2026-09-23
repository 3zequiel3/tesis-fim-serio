"""
Tests de Change 60 (`notify-accepted-at-and-test-port-isolation`, D77/RN-171) —
grupo 5 de tasks.md.

Cubre el instante de aceptación del canal (`channel_accepted_at`): captura en
el éxito de n8n (5.1), captura en cada canal de la cascada de fallbacks (5.2),
ausencia cuando la cascada completa falla (5.3), captura en el intento que
efectivamente aceptó dentro de la escalera de reintentos (5.4), invariante de
`_build_payload` invocado una sola vez (5.5), recuperación de arranque y
reintento manual (5.6), ausencia de transacciones adicionales (5.7), ausencia
de la marca en el payload canónico y en la respuesta de la API (5.8), estado
derivado sin cambios (5.9).

5.10 (no regresión de la cota de entregas concurrentes, su desborde FIFO y la
advertencia por flanco, D76/RN-170) NO se duplica acá: esta change no toca
ninguna de las tres puertas de entrada, el semáforo, `RETRY_DELAYS` ni el
`async with _delivery_slot()`, y la suite existente y NO modificada
`test_notify_isolate_executor_lane.py` sigue ejercitando exactamente ese
comportamiento contra el mismo `notify_event` — extendido, no reescrito.

Mismo patrón de fixtures que `test_notify_isolate_executor_lane.py`: SQLite
in-memory para los tests estructurales (no ejercitan concurrencia real), el
engine de Postgres real de la suite para arranque/recuperación cuando hace
falta una fila persistida entre dos `Session` independientes.

Se saltea si psycopg/libpq no está disponible porque `conftest.py` lo exige a
nivel de sesión.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

import app.modules.alerts.service as alerts_mod
from app.core.database import engine as real_engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.alerts.contract import FORBIDDEN_FIELDS
from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.router import AlertResponse
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RuleSeverity


# ── Fixtures compartidas (mismo patrón que test_notify_isolate_executor_lane.py) ──


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
        event_id=f"evt-{id(session)}-{path}",
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


def _make_alert(session: Session, event_id: int, **overrides: object) -> Alert:
    alert = Alert(event_id=event_id, severity=AlertSeverity.critical)
    for key, value in overrides.items():
        setattr(alert, key, value)
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


def _no_primary_settings() -> MagicMock:
    """Sin n8n ni SMTP ni webhook_fallback configurados: log_only es el canal
    intencional (RN-54), no un fallback tras un fallo."""
    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = ""
    mock_settings.smtp_host = ""
    mock_settings.webhook_fallback_url = ""
    return mock_settings


# ── Real engine helpers para arranque / reintento manual (5.6) ──────────────


@pytest.fixture()
def real_agent() -> Agent:
    with Session(real_engine) as db_session:
        a = Agent(agent_id="agent-accepted-at", status=AgentStatus.online)
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        db_session.expunge(a)
    return a


def _make_real_event(path: str) -> Event:
    with Session(real_engine) as db_session:
        event = Event(
            event_id=f"evt-real-accepted-{path}",
            agent_id="agent-accepted-at",
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


# ── 5.1 — Entrega exitosa por n8n en el primer intento ──────────────────────


async def test_n8n_success_sets_channel_accepted_at_before_delivered_at(
    mem_engine, session, agent
) -> None:
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=True), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"):
        await alerts_mod.notify_event(alert, event)

    session.refresh(alert)
    assert alert.channel_accepted_at is not None, (
        "D77/RN-171: el canal aceptó y la marca debe quedar registrada"
    )
    assert alert.delivered_at is not None
    assert alert.channel_accepted_at <= alert.delivered_at, (
        "la marca de aceptación debe preceder o igualar a la de entregado — "
        "se captura antes, en la corrutina, y se persiste en el mismo commit"
    )
    assert alert.channel == AlertChannel.n8n


# ── 5.2 — Entrega exitosa por cada canal de la cascada ───────────────────────


async def test_smtp_fallback_success_sets_channel_accepted_at(mem_engine, session, agent) -> None:
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
    mock_settings.smtp_host = "smtp.local"
    mock_settings.webhook_fallback_url = ""

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", mock_settings), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=False), \
            patch.object(alerts_mod, "send_smtp", new_callable=AsyncMock, return_value=True), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"), \
            patch("asyncio.sleep", new_callable=AsyncMock):
        await alerts_mod.notify_event(alert, event)

    session.refresh(alert)
    assert alert.channel == AlertChannel.smtp_fallback
    assert alert.channel_accepted_at is not None
    assert alert.delivered_at is not None
    assert alert.channel_accepted_at <= alert.delivered_at


async def test_webhook_fallback_success_sets_channel_accepted_at(mem_engine, session, agent) -> None:
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
    mock_settings.smtp_host = ""
    mock_settings.webhook_fallback_url = "http://fallback.local/hook"

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", mock_settings), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=False), \
            patch.object(alerts_mod, "send_webhook_fallback", new_callable=AsyncMock, return_value=True), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"), \
            patch("asyncio.sleep", new_callable=AsyncMock):
        await alerts_mod.notify_event(alert, event)

    session.refresh(alert)
    assert alert.channel == AlertChannel.webhook_fallback
    assert alert.channel_accepted_at is not None
    assert alert.delivered_at is not None
    assert alert.channel_accepted_at <= alert.delivered_at


async def test_log_only_floor_sets_channel_accepted_at(mem_engine, session, agent) -> None:
    """Sin ningún canal primario configurado, log_only es el canal
    intencional (RN-54) y también escribe la marca — D-1 del design: para
    log_only, "aceptación" es la escritura del log, que es lo que ese canal
    significa."""
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", _no_primary_settings()), \
            patch.object(alerts_mod, "send_log_only", new_callable=AsyncMock, return_value=None), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"):
        await alerts_mod.notify_event(alert, event)

    session.refresh(alert)
    assert alert.channel == AlertChannel.log_only
    assert alert.channel_accepted_at is not None
    assert alert.delivered_at is not None
    assert alert.channel_accepted_at <= alert.delivered_at


# ── 5.3 — La cascada completa falla: no se registra aceptación ──────────────


async def test_full_cascade_failure_leaves_channel_accepted_at_null(
    mem_engine, session, agent
) -> None:
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
    mock_settings.smtp_host = "smtp.local"
    mock_settings.webhook_fallback_url = "http://fallback.local/hook"

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", mock_settings), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=False), \
            patch.object(alerts_mod, "send_smtp", new_callable=AsyncMock, return_value=False), \
            patch.object(alerts_mod, "send_webhook_fallback", new_callable=AsyncMock, return_value=False), \
            patch.object(alerts_mod, "send_log_only", new_callable=AsyncMock, return_value=None), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"), \
            patch("asyncio.sleep", new_callable=AsyncMock):
        await alerts_mod.notify_event(alert, event)

    session.refresh(alert)
    assert alert.channel_accepted_at is None, (
        "toda la cascada falló — la marca de aceptación MUST permanecer NULL"
    )
    assert alert.delivered_at is None
    assert alert.failed_at is not None, "la fila debe caer en la DLQ"


# ── 5.4 — Entrega exitosa en el tercer intento de la escalera ───────────────


async def test_accepted_at_marks_the_attempt_that_actually_succeeded(
    mem_engine, session, agent
) -> None:
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    call_count = 0

    async def n8n_succeeds_on_third_attempt(payload, url):
        nonlocal call_count
        call_count += 1
        return call_count == 3

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", side_effect=n8n_succeeds_on_third_attempt), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"), \
            patch("asyncio.sleep", new_callable=AsyncMock):
        await alerts_mod.notify_event(alert, event)

    session.refresh(alert)
    assert call_count == 3, "la entrega debía tardar exactamente 3 intentos en aceptar"
    assert alert.channel_accepted_at is not None
    assert alert.delivered_at is not None
    assert alert.notification_id is not None


# ── 5.5 — _build_payload se invoca exactamente una vez ──────────────────────


def test_build_payload_still_called_exactly_once_per_module() -> None:
    """
    Extiende `test_notification_id_is_built_once_per_notify_event`
    (test_notification_payload_contract.py, D40/RN-134, D41/RN-135) a esta
    change: agregar un parámetro a `_mark_delivered` y capturar el instante en
    los dos puntos de éxito de `notify_event` NO debe introducir un segundo
    call site de `_build_payload` en todo el módulo.
    """
    source = inspect.getsource(alerts_mod)
    call_sites = [
        line for line in source.splitlines()
        if "_build_payload(" in line and not line.strip().startswith("def ")
    ]
    assert len(call_sites) == 1, (
        "un segundo call site de _build_payload rompería la estabilidad de "
        f"notification_id a lo largo de la escalera de reintentos: {call_sites}"
    )


# ── 5.6 — Recuperación de arranque y reintento manual también escriben la marca ──


async def test_startup_recovery_writes_channel_accepted_at(real_agent) -> None:
    event = _make_real_event("/etc/recovery-accepted-at")
    alert = _make_real_alert(event.id, notification_id="recovery-accepted-at-1")

    with patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=True):
        await alerts_mod.recover_pending_notifications()

    with Session(real_engine) as check_session:
        refreshed = check_session.get(Alert, alert.id)
        assert refreshed is not None
        assert refreshed.channel_accepted_at is not None
        assert refreshed.delivered_at is not None


async def test_manual_retry_from_dlq_writes_channel_accepted_at(real_agent) -> None:
    event = _make_real_event("/etc/manual-retry-accepted-at")
    alert = _make_real_alert(
        event.id, failed_at=datetime.now(timezone.utc), last_error="prior_failure"
    )

    preexisting = set(alerts_mod._background_tasks)
    with patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=True):
        with Session(real_engine) as retry_session:
            await alerts_mod.retry_alert(alert.id, retry_session, 1)
            await asyncio.gather(*(alerts_mod._background_tasks - preexisting))

    with Session(real_engine) as check_session:
        refreshed = check_session.get(Alert, alert.id)
        assert refreshed is not None
        assert refreshed.channel_accepted_at is not None
        assert refreshed.delivered_at is not None


# ── 5.7 — Registrar la marca no agrega transacciones ─────────────────────────


async def test_marking_acceptance_adds_no_extra_commits_or_executor_dispatch(
    mem_engine, session, agent
) -> None:
    """
    Cuenta los despachos a `run_in_executor` para `_mark_delivered` y los
    `commit` dentro de él: deben seguir siendo UNO de cada uno por entrega
    exitosa, igual que antes de esta change (D-1 del design, alternativa C
    descartada explícitamente por agregar una transacción).
    """
    event = _make_event(session)
    # notification_id ya seteado a propósito: si faltara, _prepare_notification
    # lo mintearía y haría un commit propio, contaminando el conteo de abajo —
    # este test aísla específicamente el commit de _mark_delivered.
    alert = _make_alert(session, event.id, notification_id="preset-notification-id")

    mark_delivered_calls = 0
    commit_calls = 0

    orig_mark_delivered = alerts_mod._mark_delivered

    def spy_mark_delivered(*args, **kwargs):
        nonlocal mark_delivered_calls
        mark_delivered_calls += 1
        return orig_mark_delivered(*args, **kwargs)

    orig_session_commit = Session.commit

    def spy_commit(self, *args, **kwargs):
        nonlocal commit_calls
        commit_calls += 1
        return orig_session_commit(self, *args, **kwargs)

    with patch.object(alerts_mod, "engine", mem_engine), \
            patch.object(alerts_mod, "settings", _n8n_only_settings()), \
            patch.object(alerts_mod, "send_n8n", new_callable=AsyncMock, return_value=True), \
            patch.object(alerts_mod, "_mark_delivered", side_effect=spy_mark_delivered), \
            patch.object(Session, "commit", spy_commit), \
            patch.object(alerts_mod.alerts_broadcaster, "publish"):
        await alerts_mod.notify_event(alert, event)

    assert mark_delivered_calls == 1, "_mark_delivered debe invocarse una sola vez por entrega"
    # _prepare_notification (1 commit potencial si mintea notification_id ya
    # existente -> 0) + _mark_delivered (1 commit). El alert ya tiene
    # notification_id de _make_alert vía Alert(...), así que _prepare_notification
    # no mintea uno nuevo y no hace commit propio.
    assert commit_calls == 1, (
        f"se esperaba exactamente 1 commit en el camino de entrega exitosa, "
        f"se vieron {commit_calls} — escribir channel_accepted_at no debe "
        "agregar una transacción"
    )


# ── 5.8 — La marca no viaja en el payload ni en la respuesta de la API ──────


def test_channel_accepted_at_absent_from_canonical_payload() -> None:
    from app.modules.alerts.service import _build_payload

    now = datetime.now(timezone.utc)
    alert = Alert(
        id=1,
        event_id=7,
        severity=AlertSeverity.critical,
        created_at=now,
        channel_accepted_at=now,
    )
    event = Event(
        id=7,
        event_id="e-payload-1",
        agent_id="agent-01",
        path="/etc/passwd",
        status=EventStatus.auto_restored,
        is_symlink=False,
        action_failed=False,
        process_pid=1,
        process_uid=0,
        process_exe="/usr/bin/curl",
        detected_at=now,
        received_at=now,
    )
    payload = _build_payload(alert, event)

    assert "channel_accepted_at" not in payload, (
        "D40/RN-134: la marca es instrumentación de medición, no viaja en el "
        "payload canónico de notificación"
    )
    for forbidden in FORBIDDEN_FIELDS:
        assert forbidden not in payload


def test_channel_accepted_at_absent_from_api_response_model() -> None:
    assert "channel_accepted_at" not in AlertResponse.model_fields, (
        "D-4 del design: la marca es instrumentación, no superficie de "
        "producto — el modelo de respuesta de la API no debe incorporarla"
    )


# ── 5.9 — El estado derivado no cambia por la existencia de la columna ──────


def test_derived_status_ignores_channel_accepted_at() -> None:
    """
    Una fila con channel_accepted_at no nulo y delivered_at nulo -que en
    régimen no debería existir, pero que este test construye a propósito- NO
    debe reportarse como `delivered`: el estado derivado sigue viniendo SOLO
    de delivered_at y failed_at (D-4 del design).
    """
    from app.modules.alerts.router import _derive_alert_status

    alert = Alert(
        id=1,
        event_id=1,
        severity=AlertSeverity.critical,
        channel_accepted_at=datetime.now(timezone.utc),
        delivered_at=None,
        failed_at=None,
    )
    assert _derive_alert_status(alert) == "pending", (
        "channel_accepted_at no debe participar de la derivación del estado"
    )
