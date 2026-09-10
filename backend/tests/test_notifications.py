"""
Tests del módulo notifications (C15 — backend-notifications).

Cubre:
  7.1  Tests unitarios de notifier y service:
       - severity determination (critical, high, low, no rules)
       - notify_if_applicable skip (low/medium/superseded)
       - retry loop 3x
       - cascada de canales
       - semántica de log_only (D23/RN-120): piso de logueo siempre exitoso,
         pero canal de ENTREGA solo cuando no hay ningún primario configurado

  7.2  Tests de endpoints DLQ:
       - GET /alerts/failed
       - POST /alerts/{id}/retry (200, 409, 404)
       - DELETE /alerts/{id} (204, 404)

  7.3  Tests de GET /health/components:
       - todos ok
       - valkey down
       - n8n degraded
       - detección de cambio de estado

Usa SQLite in-memory. Salta si psycopg no está disponible (Windows sin PostgreSQL).
"""

from __future__ import annotations

import asyncio
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

from sqlalchemy.pool import StaticPool

from app.modules.alerts.models import Alert, AlertChannel, AlertSeverity
from app.modules.alerts.notifier import send_log_only, send_n8n, send_smtp, send_webhook_fallback
from app.modules.alerts.service import (
    RETRY_DELAYS,
    _determine_severity,
    delete_alert,
    list_failed_alerts,
    notify_event,
    notify_if_applicable,
    retry_alert,
)
from app.modules.agents.models import Agent, AgentStatus
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import Rule, RuleAction, RuleSeverity


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_engine():
    # StaticPool ensures all connections (including TestClient threads) share the same
    # in-memory SQLite database — without it, each thread gets an empty database.
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


def _make_event(
    session: Session,
    agent_id: str = "agent-001",
    path: str | None = "/etc/passwd",
    status: EventStatus = EventStatus.pending,
    severity: RuleSeverity = RuleSeverity.low,
) -> Event:
    event = Event(
        event_id=f"evt-{id(session)}-{path[:5] if path else 'nopath'}",
        agent_id=agent_id,
        path=path,
        hash_detected="abc123",
        status=status,
        severity=severity,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _make_rule(
    session: Session,
    pattern: str = "/etc/*",
    severity: RuleSeverity = RuleSeverity.critical,
) -> Rule:
    rule = Rule(
        pattern=pattern,
        severity=severity,
        action=RuleAction.alert_only,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


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


# ── 7.1 Tests unitarios de notifier ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_log_only_always_succeeds():
    """send_log_only siempre retorna True sin importar el payload."""
    result = await send_log_only({"severity": "critical", "event_id": "evt-1"})
    assert result is True


@pytest.mark.asyncio
async def test_send_n8n_skipped_when_no_url():
    """send_n8n retorna False si url está vacía."""
    result = await send_n8n({"data": "x"}, url="")
    assert result is False


@pytest.mark.asyncio
async def test_send_n8n_success():
    """send_n8n retorna True en respuesta 2xx."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await send_n8n({"data": "x"}, url="http://n8n.local/webhook/test")
    assert result is True


@pytest.mark.asyncio
async def test_send_n8n_failure():
    """send_n8n retorna False si httpx levanta excepción."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await send_n8n({"data": "x"}, url="http://n8n.local/webhook/test")
    assert result is False


@pytest.mark.asyncio
async def test_send_smtp_skipped_when_no_host():
    """send_smtp retorna False si smtp_host está vacío."""
    cfg = MagicMock()
    cfg.smtp_host = ""
    result = await send_smtp({"data": "x"}, cfg)
    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_fallback_skipped_when_no_url():
    """send_webhook_fallback retorna False si url está vacía."""
    result = await send_webhook_fallback({"data": "x"}, url="")
    assert result is False


# ── 7.1 Tests unitarios de service — severity determination ──────────────────


def test_determine_severity_critical(session, agent):
    """Regla critical matchea /etc/passwd → retorna critical."""
    _make_rule(session, pattern="/etc/*", severity=RuleSeverity.critical)
    event = _make_event(session, path="/etc/passwd")
    sev = _determine_severity(event, session)
    assert sev == RuleSeverity.critical


def test_determine_severity_high_over_low(session, agent):
    """Dos reglas: low y high; retorna high."""
    _make_rule(session, pattern="/etc/*", severity=RuleSeverity.low)
    _make_rule(session, pattern="/etc/p*", severity=RuleSeverity.high)
    event = _make_event(session, path="/etc/passwd")
    sev = _determine_severity(event, session)
    assert sev == RuleSeverity.high


def test_determine_severity_no_match(session, agent):
    """Sin reglas matching → retorna low."""
    _make_rule(session, pattern="/var/log/*", severity=RuleSeverity.critical)
    event = _make_event(session, path="/etc/passwd")
    sev = _determine_severity(event, session)
    assert sev == RuleSeverity.low


def test_determine_severity_no_rules(session, agent):
    """Sin reglas en DB → retorna low."""
    event = _make_event(session, path="/etc/passwd")
    sev = _determine_severity(event, session)
    assert sev == RuleSeverity.low


def test_determine_severity_high_fixed_for_path_none(session, agent):
    """D51/RN-145 (hallazgo task 9.4): evento sin ruta recibe high fijo, SIN
    consultar el ruleset — ni siquiera una regla critical que matchea todo
    puede subir ni bajar esta severidad, y determine_severity_for_path no se
    invoca (evita el TypeError de fnmatch.fnmatch(None, ...) y mantiene
    consistencia con la severidad que events/service.py ya persiste)."""
    _make_rule(session, pattern="*", severity=RuleSeverity.critical)
    event = _make_event(session, path=None, status=EventStatus.alert_only)
    with patch(
        "app.modules.alerts.service.determine_severity_for_path"
    ) as mock_determine:
        sev = _determine_severity(event, session)
    assert sev == RuleSeverity.high
    mock_determine.assert_not_called()


# ── 7.1 Tests de notify skip ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_skip_superseded(session, agent):
    """Evento superseded → no crea Alert."""
    event = _make_event(
        session,
        path="/etc/passwd",
        status=EventStatus.superseded,
        severity=RuleSeverity.critical,
    )

    with patch("app.modules.alerts.service.engine") as mock_engine:
        mock_engine.__enter__ = MagicMock()
        # Parchar Session para devolver nuestra session de test
        with patch("app.modules.alerts.service.Session") as mock_session_class:
            mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
            mock_session_class.return_value.__exit__ = MagicMock(return_value=False)
            await notify_if_applicable(event)

    # No debe haber creado alertas
    alerts = session.exec(select(Alert)).all()
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_notify_skip_low_severity(session, agent):
    """Evento con severity=low → no crea Alert."""
    event = _make_event(session, path="/etc/passwd", severity=RuleSeverity.low)

    with patch("app.modules.alerts.service.Session") as mock_session_class:
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)
        await notify_if_applicable(event)

    alerts = session.exec(select(Alert)).all()
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_notify_skip_medium_severity(session, agent):
    """Evento con severity=medium → no crea Alert."""
    event = _make_event(session, path="/etc/passwd", severity=RuleSeverity.medium)

    with patch("app.modules.alerts.service.Session") as mock_session_class:
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)
        await notify_if_applicable(event)

    alerts = session.exec(select(Alert)).all()
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_notify_critical_event_creates_alert_and_publishes_sse(session, agent):
    """US-20: the positive notifier path persists an alert and emits its SSE payload."""
    event = _make_event(session, path="/etc/passwd", severity=RuleSeverity.critical)

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.alerts_broadcaster.publish") as publish, \
         patch("app.modules.alerts.service.notify_event", new_callable=AsyncMock) as deliver:
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        await notify_if_applicable(event)

    alerts = session.exec(select(Alert)).all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.event_id == event.id
    assert alert.severity == AlertSeverity.critical
    publish.assert_called_once_with(
        {
            "id": alert.id,
            "event_id": event.id,
            "severity": "critical",
            "status": "pending",
            "channel": None,
            "delivered_at": None,
            "failed_at": None,
            "last_error": None,
            "retry_count": 0,
            "created_at": alert.created_at.isoformat(),
        }
    )
    deliver.assert_awaited_once_with(alert, event)


# ── 7.1 Tests de retry loop y cascada ────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_event_delivers_on_first_attempt(session, agent):
    """n8n responde en primer intento → delivered_at poblado, retry_count=0."""
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", new_callable=AsyncMock, return_value=True), \
         patch("app.modules.alerts.service.settings") as mock_settings:

        mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
        mock_settings.smtp_host = ""
        mock_settings.webhook_fallback_url = ""

        # Usar la session de test para las actualizaciones
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        await notify_event(alert, event)

    session.refresh(alert)
    assert alert.delivered_at is not None
    assert alert.channel == AlertChannel.n8n
    assert alert.retry_count == 0


@pytest.mark.asyncio
async def test_notify_event_retry_3x_then_dlq(session, agent):
    """
    n8n configurado y fallando, sin otros primarios → D23/RN-120: log_only es el
    piso de logueo, NO un canal de entrega. Se agotan los 4 intentos y la alerta
    cae en la DLQ con retry_count == len(RETRY_DELAYS).
    """
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", new_callable=AsyncMock, return_value=False), \
         patch("app.modules.alerts.service.send_log_only", new_callable=AsyncMock, return_value=True), \
         patch("app.modules.alerts.service.settings") as mock_settings, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:  # no esperar en tests

        mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
        mock_settings.smtp_host = ""
        mock_settings.webhook_fallback_url = ""

        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        await notify_event(alert, event)

    session.refresh(alert)
    assert alert.delivered_at is None, "un primario configurado que falla NO se marca entregado"
    assert alert.failed_at is not None
    assert alert.retry_count == len(RETRY_DELAYS)
    assert alert.last_error is not None
    # Los 3 reintentos esperaron los delays de RETRY_DELAYS, en orden.
    assert [c.args[0] for c in mock_sleep.await_args_list] == RETRY_DELAYS


@pytest.mark.asyncio
async def test_log_only_no_entrega_si_hay_primarios_configurados(session, agent):
    """
    D23/RN-120: con los tres canales primarios configurados y fallando, log_only
    se ejecuta como piso (RN-54) pero la alerta va a la DLQ — no queda entregada.
    (El caso "sin primarios configurados → log_only entrega" lo cubre
    test_fix01_no_primaries_log_only_delivers en test_c31_backend_event_correctness.)
    """
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    log_only_calls: list[dict] = []

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", new_callable=AsyncMock, return_value=False), \
         patch("app.modules.alerts.service.send_smtp", new_callable=AsyncMock, return_value=False), \
         patch("app.modules.alerts.service.send_webhook_fallback", new_callable=AsyncMock, return_value=False), \
         patch("app.modules.alerts.service.send_log_only", new_callable=AsyncMock,
               side_effect=lambda p: log_only_calls.append(p) or True), \
         patch("app.modules.alerts.service.settings") as mock_settings, \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_settings.n8n_webhook_url = "http://n8n.local"
        mock_settings.smtp_host = "smtp.local"
        mock_settings.webhook_fallback_url = "http://fallback.local"

        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        await notify_event(alert, event)

    session.refresh(alert)
    assert alert.delivered_at is None
    assert alert.channel != AlertChannel.log_only
    assert alert.failed_at is not None
    # Las alternativas se ejecutan una sola vez DESPUÉS de agotar n8n.
    assert len(log_only_calls) == 1


@pytest.mark.asyncio
async def test_n8n_retry_ladder_finishes_before_real_fallback(session, agent):
    """n8n gets all four attempts before SMTP is attempted once."""
    event = _make_event(session)
    alert = _make_alert(session, event.id)
    calls: list[str] = []

    async def n8n_fails(*_args, **_kwargs):
        calls.append("n8n")
        return False

    async def smtp_succeeds(*_args, **_kwargs):
        calls.append("smtp")
        return True

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", side_effect=n8n_fails), \
         patch("app.modules.alerts.service.send_smtp", side_effect=smtp_succeeds), \
         patch("app.modules.alerts.service.send_webhook_fallback", new_callable=AsyncMock) as webhook, \
         patch("app.modules.alerts.service.send_log_only", new_callable=AsyncMock) as log_only, \
         patch("app.modules.alerts.service.settings") as mock_settings, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_settings.n8n_webhook_url = "http://n8n.local/webhook/fim-alert"
        mock_settings.smtp_host = "smtp.test"
        mock_settings.webhook_fallback_url = "http://fallback.test"
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        await notify_event(alert, event)

    session.refresh(alert)
    assert calls == ["n8n", "n8n", "n8n", "n8n", "smtp"]
    webhook.assert_not_awaited()
    log_only.assert_not_awaited()
    assert alert.channel == AlertChannel.smtp_fallback
    assert alert.delivered_at is not None
    assert alert.attempt_count == 4


@pytest.mark.asyncio
async def test_persisted_retry_recovers_after_interrupted_task(session, agent):
    """A new task resumes the persisted next attempt with the same identity."""
    import app.modules.alerts.service as alerts_service

    event = _make_event(session)
    alert = _make_alert(session, event.id)
    alert_id = alert.id

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", new_callable=AsyncMock, return_value=False), \
         patch("app.modules.alerts.service.settings") as mock_settings, \
         patch("asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError):
        mock_settings.n8n_webhook_url = "http://n8n.local/webhook/fim-alert"
        mock_settings.smtp_host = ""
        mock_settings.webhook_fallback_url = ""
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(asyncio.CancelledError):
            await notify_event(alert, event)

    session.refresh(alert)
    persisted_id = alert.notification_id
    assert persisted_id
    assert alert.attempt_count == 1
    assert alert.next_retry_at is not None
    assert alert.delivered_at is None
    assert alert.failed_at is None

    captured_payloads: list[dict] = []

    async def recovered_delivery(payload, *_args, **_kwargs):
        captured_payloads.append(payload)
        return True

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", side_effect=recovered_delivery), \
         patch("app.modules.alerts.service.settings") as mock_settings, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_settings.n8n_webhook_url = "http://n8n.local/webhook/fim-alert"
        mock_settings.smtp_host = ""
        mock_settings.webhook_fallback_url = ""
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        await alerts_service.recover_pending_notifications()

    persisted = session.get(Alert, alert_id)
    assert persisted is not None
    assert persisted.delivered_at is not None
    assert persisted.attempt_count == 2
    assert persisted.next_retry_at is None
    assert captured_payloads[0]["notification_id"] == persisted_id


@pytest.mark.asyncio
async def test_terminal_dlq_entry_is_not_retried_on_restart(session, agent):
    """Startup recovery resumes interrupted work, not terminal DLQ rows."""
    import app.modules.alerts.service as alerts_service

    event = _make_event(session)
    alert = _make_alert(session, event.id, failed=True)
    alert.notification_id = "terminal-dlq-id"
    alert.attempt_count = len(RETRY_DELAYS) + 1
    session.add(alert)
    session.commit()

    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", new_callable=AsyncMock) as send:
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)
        await alerts_service.recover_pending_notifications()

    send.assert_not_awaited()


# ── 7.2 Tests de endpoints ────────────────────────────────────────────────────


def _make_test_app(test_session: Session, mock_valkey=None):
    """Crea una app FastAPI con overrides para test."""
    from app.main import app
    from app.core.database import get_session
    from app.core.valkey import get_valkey_client
    from app.core.deps import require_admin
    from app.modules.auth.models import User

    def override_session():
        yield test_session

    def override_admin():
        return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)

    def override_valkey():
        if mock_valkey:
            return mock_valkey
        return MagicMock()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_valkey_client] = override_valkey
    return app


def test_get_failed_alerts_returns_only_failed(session, agent):
    """GET /alerts/failed retorna solo alertas fallidas."""
    event = _make_event(session)
    _make_alert(session, event.id, delivered=True)   # entregada — NO debe aparecer
    failed = _make_alert(session, event.id, failed=True)  # fallida — SÍ debe aparecer

    app = _make_test_app(session)
    with TestClient(app) as client:
        response = client.get("/alerts/failed")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == failed.id

    app.dependency_overrides.clear()


def test_get_failed_alerts_empty(session, agent):
    """GET /alerts/failed retorna lista vacía si no hay fallos."""
    app = _make_test_app(session)
    with TestClient(app) as client:
        response = client.get("/alerts/failed")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_retry_alert_already_delivered(session, agent):
    """retry_alert lanza ValueError('already_delivered') si ya fue entregada."""
    event = _make_event(session)
    alert = _make_alert(session, event.id, delivered=True)

    with pytest.raises(ValueError, match="already_delivered"):
        await retry_alert(alert.id, session)


@pytest.mark.asyncio
async def test_retry_alert_not_found(session):
    """retry_alert lanza ValueError('not_found') si id no existe."""
    with pytest.raises(ValueError, match="not_found"):
        await retry_alert(99999, session)


@pytest.mark.asyncio
async def test_retry_alert_resets_dlq_state_and_reschedules(session, agent):
    """
    US-29 (anexo §7, nivel 1 #7) — camino feliz del reintento: la fila sale de
    la DLQ (failed_at, last_error y retry_count reseteados) y la notificación
    se vuelve a disparar con la misma alerta y el mismo evento.
    """
    import app.modules.alerts.service as alerts_service

    event = _make_event(session)
    alert = _make_alert(session, event.id, failed=True)
    alert.notification_id = "stable-manual-retry-id"
    session.add(alert)
    session.commit()
    session.refresh(alert)
    assert alert.failed_at is not None and alert.retry_count == 3  # precondición: está en la DLQ

    preexisting = set(alerts_service._background_tasks)
    with patch.object(
        alerts_service, "notify_event", new_callable=AsyncMock
    ) as mock_notify:
        returned = await retry_alert(alert.id, session)
        # La notificación es fire-and-forget: cederle el loop para que corra.
        # Sólo las tareas que creó esta llamada, no las que pudo dejar otro test.
        await asyncio.gather(*(alerts_service._background_tasks - preexisting))

    # Estado reseteado y persistido.
    session.expire_all()
    persisted = session.get(Alert, alert.id)
    assert persisted.failed_at is None
    assert persisted.last_error is None
    assert persisted.retry_count == 0
    assert persisted.attempt_count == 0
    assert persisted.next_retry_at is None
    assert persisted.notification_id == "stable-manual-retry-id"
    assert persisted.delivered_at is None
    assert returned.id == alert.id

    # La cascada se volvió a disparar sobre la misma alerta y el mismo evento.
    assert mock_notify.await_count == 1
    called_alert, called_event = mock_notify.await_args.args
    assert called_alert.id == alert.id
    assert called_event.id == event.id


@pytest.mark.asyncio
async def test_retry_alert_delivers_and_leaves_the_dlq(session, agent):
    """
    US-29: el reintento efectivo entrega por n8n y la alerta deja de figurar
    en `list_failed_alerts` — el ciclo completo, no sólo el reseteo de campos.
    """
    import app.modules.alerts.service as alerts_service

    event = _make_event(session)
    alert = _make_alert(session, event.id, failed=True)
    assert [a.id for a in list_failed_alerts(session)] == [alert.id]

    preexisting = set(alerts_service._background_tasks)
    with patch("app.modules.alerts.service.Session") as mock_session_class, \
         patch("app.modules.alerts.service.send_n8n", new_callable=AsyncMock, return_value=True), \
         patch("app.modules.alerts.service.settings") as mock_settings:

        mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
        mock_settings.smtp_host = ""
        mock_settings.webhook_fallback_url = ""
        mock_session_class.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        await retry_alert(alert.id, session)
        await asyncio.gather(*(alerts_service._background_tasks - preexisting))

    session.expire_all()
    persisted = session.get(Alert, alert.id)
    assert persisted.delivered_at is not None
    assert persisted.channel == AlertChannel.n8n
    assert persisted.failed_at is None
    assert persisted.last_error is None
    assert list_failed_alerts(session) == []


def test_post_retry_alert_409_if_delivered(session, agent):
    """POST /alerts/{id}/retry → 409 si ya entregada."""
    event = _make_event(session)
    alert = _make_alert(session, event.id, delivered=True)

    app = _make_test_app(session)
    with TestClient(app) as client:
        response = client.post(f"/alerts/{alert.id}/retry")

    assert response.status_code == 409
    app.dependency_overrides.clear()


def test_post_retry_alert_404_if_not_found(session):
    """POST /alerts/{id}/retry → 404 si no existe."""
    app = _make_test_app(session)
    with TestClient(app) as client:
        response = client.post("/alerts/99999/retry")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_delete_alert_204(session, agent):
    """DELETE /alerts/{id} → 204 si ok."""
    event = _make_event(session)
    alert = _make_alert(session, event.id)

    app = _make_test_app(session)
    with TestClient(app) as client:
        response = client.delete(f"/alerts/{alert.id}")

    assert response.status_code == 204
    app.dependency_overrides.clear()


def test_delete_alert_404_if_not_found(session):
    """DELETE /alerts/{id} → 404 si no existe."""
    app = _make_test_app(session)
    with TestClient(app) as client:
        response = client.delete("/alerts/99999")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_delete_alert_service(session, agent):
    """delete_alert elimina correctamente la fila."""
    event = _make_event(session)
    alert = _make_alert(session, event.id)
    alert_id = alert.id

    delete_alert(alert_id, session)
    assert session.get(Alert, alert_id) is None


# ── 7.3 Tests de GET /health/components ─────────────────────────────────────


@pytest.mark.asyncio
async def test_health_all_ok(session):
    """Todos los componentes up → todos 'ok' (excepto agents que depende de DB)."""
    mock_valkey = AsyncMock()
    mock_valkey.ping = AsyncMock(return_value=True)

    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local"
    mock_settings.smtp_host = ""

    # Parchar _check_n8n para que retorne ok sin llamada HTTP real
    with patch("app.core.health._check_n8n", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._check_postgres", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._last_state", {}):

        from app.core import health as health_module
        health_module._last_state = {}

        result = await health_module.check_components(session, mock_valkey, mock_settings)

    assert result["postgres"] == "ok"
    assert result["valkey"] == "ok"
    assert result["n8n"] == "ok"
    assert "checked_at" in result


@pytest.mark.asyncio
async def test_health_valkey_down(session):
    """Valkey no responde → resultado 'down' para valkey.

    _check_valkey calls valkey_client.ping() synchronously inside
    run_in_executor, so the mock must be a regular MagicMock (not AsyncMock)
    for the side_effect to trigger when ping() is called without await.
    """
    mock_valkey = MagicMock()
    mock_valkey.ping = MagicMock(side_effect=Exception("connection refused"))

    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = ""
    mock_settings.smtp_host = ""

    with patch("app.core.health._check_postgres", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._check_n8n", new_callable=AsyncMock, return_value="degraded"):

        from app.core import health as health_module
        health_module._last_state = {}

        result = await health_module.check_components(session, mock_valkey, mock_settings)

    assert result["valkey"] == "down"


@pytest.mark.asyncio
async def test_health_n8n_degraded_when_not_configured(session):
    """
    N8N_HEALTH_URL no configurado → n8n: 'degraded' (D43/RN-137).

    Antes de C46 la variable que gobernaba este check era N8N_WEBHOOK_URL. La
    intención del test no cambió —sin configuración no se puede afirmar que n8n
    esté sano—, cambió cuál es la variable que la aporta.
    """
    mock_valkey = AsyncMock()
    mock_valkey.ping = AsyncMock(return_value=True)

    mock_settings = MagicMock()
    mock_settings.n8n_health_url = ""     # no configurado
    mock_settings.n8n_webhook_url = ""

    with patch("app.core.health._check_postgres", new_callable=AsyncMock, return_value="ok"):
        from app.core import health as health_module
        health_module._last_state = {}

        result = await health_module.check_components(session, mock_valkey, mock_settings)

    assert result["n8n"] == "degraded"


@pytest.mark.asyncio
async def test_health_check_reads_health_url_not_webhook_url(session):
    """
    D43/RN-137: `check_components` pasa n8n_health_url al check, nunca el webhook.

    Con el enrutador `fim-alert` operativo (change 47), consultar la URL del
    webhook dispararía el workflow. Este test fija qué variable llega al check,
    complementando a test_health_n8n_check.py, que fija qué URL se consulta.
    """
    mock_valkey = AsyncMock()
    mock_valkey.ping = AsyncMock(return_value=True)

    mock_settings = MagicMock()
    mock_settings.n8n_health_url = "http://n8n.local/healthz"
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook/fim-alert"

    from app.core import health as health_module
    health_module._last_state = {}

    with patch("app.core.health._check_postgres", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._check_n8n", new_callable=AsyncMock, return_value="ok") as spy:
        await health_module.check_components(session, mock_valkey, mock_settings)

    spy.assert_awaited_once_with("http://n8n.local/healthz")


@pytest.mark.asyncio
async def test_health_change_payload_carries_the_discriminator(session):
    """
    4.6 / D40/RN-134: el webhook de cambio de salud lleva el sobre plano.

    Alertas de evento y cambios de salud comparten una única URL de webhook, así
    que sin `type` el receptor no puede distinguir las dos formas. `event` se
    conserva por compatibilidad con consumidores previos.
    """
    mock_valkey = AsyncMock()
    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook/fim-alert"
    mock_settings.n8n_health_url = "http://n8n.local/healthz"

    from app.core import health as health_module
    health_module._last_state = {
        "postgres": "ok", "valkey": "ok", "n8n": "ok", "agents": "degraded",
    }

    sent: list[dict] = []

    async def fake_send_n8n(payload, url, timeout=None):
        sent.append(payload)
        return True

    with patch("app.core.health._check_postgres", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._check_valkey", new_callable=AsyncMock, return_value="down"), \
         patch("app.core.health._check_n8n", new_callable=AsyncMock, return_value="ok"), \
         patch("app.modules.alerts.notifier.send_n8n", side_effect=fake_send_n8n):
        await health_module.check_components(session, mock_valkey, mock_settings)
        await asyncio.sleep(0)  # dejar correr la task fire-and-forget

    assert sent, "un cambio ok→down debe emitir el webhook de salud"
    payload = sent[0]
    assert payload["type"] == "health_change"
    assert payload["schema_version"] == 1
    assert "notification_id" in payload
    assert payload["event"] == "health_change"  # compatibilidad
    assert payload["component"] == "valkey"
    assert payload["old_status"] == "ok"
    assert payload["new_status"] == "down"


@pytest.mark.asyncio
async def test_health_state_change_triggers_webhook(session):
    """Cambio de estado ok→down dispara asyncio.create_task con send_n8n."""
    mock_valkey = AsyncMock()
    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"
    mock_settings.smtp_host = ""

    from app.core import health as health_module

    # Establecer estado previo: valkey=ok
    health_module._last_state = {
        "postgres": "ok",
        "valkey": "ok",
        "n8n": "ok",
        "agents": "degraded",
    }

    tasks_created: list = []

    def fake_create_task(coro):
        tasks_created.append(coro)
        # Cerrar la coroutine para evitar ResourceWarning
        coro.close()
        return MagicMock()

    with patch("app.core.health._check_postgres", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._check_valkey", new_callable=AsyncMock, return_value="down"), \
         patch("app.core.health._check_n8n", new_callable=AsyncMock, return_value="ok"), \
         patch("asyncio.create_task", side_effect=fake_create_task):

        await health_module.check_components(session, mock_valkey, mock_settings)

    # Debe haberse disparado un create_task por el cambio valkey ok→down
    assert len(tasks_created) >= 1


@pytest.mark.asyncio
async def test_health_no_webhook_on_first_call(session):
    """Primera llamada (sin estado previo) → no dispara webhook."""
    mock_valkey = AsyncMock()
    mock_settings = MagicMock()
    mock_settings.n8n_webhook_url = "http://n8n.local/webhook"

    from app.core import health as health_module
    health_module._last_state = {}  # sin estado previo

    tasks_created: list = []

    def fake_create_task(coro):
        tasks_created.append(coro)
        coro.close()
        return MagicMock()

    with patch("app.core.health._check_postgres", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._check_valkey", new_callable=AsyncMock, return_value="ok"), \
         patch("app.core.health._check_n8n", new_callable=AsyncMock, return_value="ok"), \
         patch("asyncio.create_task", side_effect=fake_create_task):

        await health_module.check_components(session, mock_valkey, mock_settings)

    # Sin estado previo → no debe dispararse ningún webhook
    assert len(tasks_created) == 0
