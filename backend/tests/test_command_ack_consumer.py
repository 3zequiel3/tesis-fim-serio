"""
Tests de regresión para C36 — backend-command-ack-consumer (slice 2: consumer
dedicado, verificación HMAC del ack, reconciliación y barrido de timeout).

Cubre:
  - Ack ok de baseline_update: fila acked, baseline_entries upserteado,
    ruleset_version_applied avanzado (D1/RN-104, D5/RN-106).
  - Ack error: fila failed con error, sin reconciliación.
  - Ack sin command_id / command_id desconocido: descartados sin tocar DB.
  - Ack con firma HMAC inválida: rechazado (decisión del usuario, C36).
  - Ack repetido: idempotente, no re-aplica efectos.
  - Barrido de timeout: pending vencido -> timeout; NULL y terminales intactos.

Usa SQLite in-memory. Salta si psycopg/libpq no está disponible.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.streams import sign_payload
from app.modules.agents.models import Agent, AgentStatus, BaselineEntry
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import PublishedCommand


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
def secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent_online(mem_engine, secret) -> Agent:
    a = Agent(
        agent_id="agent-ack-001",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
        ruleset_version_applied=5,
    )
    with Session(mem_engine) as s:
        s.add(a)
        s.commit()
        s.refresh(a)
    return a


@pytest.fixture()
def approved_event(mem_engine, agent_online) -> Event:
    """Evento approved cuyo baseline_update se confirma en los tests."""
    ev = Event(
        event_id="evt-ack-001",
        agent_id=agent_online.agent_id,
        path="/etc/ack-test",
        hash_detected="cafebabe",
        status=EventStatus.approved,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    with Session(mem_engine) as s:
        s.add(ev)
        s.commit()
        s.refresh(ev)
    return ev


def _make_pending_command(
    mem_engine,
    *,
    command_id: str,
    command_type: str,
    target_agent_id: str,
    event_id: int | None = None,
    ruleset_version: int = 7,
) -> PublishedCommand:
    cmd = PublishedCommand(
        command_type=command_type,
        target_agent_id=target_agent_id,
        event_id=event_id,
        command_id=command_id,
        ack_status="pending",
        ruleset_version=ruleset_version,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    with Session(mem_engine) as s:
        s.add(cmd)
        s.commit()
        s.refresh(cmd)
    return cmd


def _make_ack_payload(
    command_id: str,
    command_type: str,
    event_id,
    agent_id: str,
    secret: bytes,
    ok: bool = True,
    error: str | None = None,
) -> dict:
    payload: dict = {
        "command_id": command_id,
        "command_type": command_type,
        "event_id": event_id,
        "agent_id": agent_id,
        "status": "ok" if ok else "error",
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload["signature"] = sign_payload(secret, payload)
    return payload


def _handle(mem_engine, payload: dict) -> None:
    import app.modules.agents.command_ack_consumer as mod

    msg_data = {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
    with patch.object(mod, "engine", mem_engine):
        mod._handle_command_ack(msg_data)


# ── Ack ok de baseline_update: acked + reconciliación D1/D5 ──────────────────


def test_ack_ok_baseline_update_marks_acked(mem_engine, agent_online, approved_event, secret):
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-ack-001",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=7,
    )
    payload = _make_ack_payload(cmd.command_id, "baseline_update", approved_event.id, agent_online.agent_id, secret)

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        row = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-ack-001")).first()
        assert row.ack_status == "acked"
        assert row.acked_at is not None
        assert row.error is None


def test_ack_ok_baseline_update_reconciles_baseline_entries(mem_engine, agent_online, approved_event, secret):
    """D1/RN-104: ack ok de baseline_update refleja el hash aprobado en baseline_entries."""
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-ack-002",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=7,
    )
    payload = _make_ack_payload(cmd.command_id, "baseline_update", approved_event.id, agent_online.agent_id, secret)

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        entry = s.exec(
            select(BaselineEntry).where(
                BaselineEntry.path == approved_event.path,
                BaselineEntry.agent_id == agent_online.agent_id,
            )
        ).first()
        assert entry is not None
        assert entry.hash == approved_event.hash_detected
        assert entry.ruleset_version == 7


def test_ack_ok_baseline_update_advances_ruleset_version_applied(mem_engine, agent_online, approved_event, secret):
    """D5/RN-106: ruleset_version_applied avanza SOLO al confirmar (agent_online arranca en 5)."""
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-ack-003",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=9,
    )
    payload = _make_ack_payload(cmd.command_id, "baseline_update", approved_event.id, agent_online.agent_id, secret)

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 9


def test_ack_ok_monotonic_does_not_regress(mem_engine, agent_online, approved_event, secret):
    """Un ack con ruleset_version menor al ya aplicado no retrocede el valor."""
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-ack-004",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=1,  # agent_online.ruleset_version_applied == 5
    )
    payload = _make_ack_payload(cmd.command_id, "baseline_update", approved_event.id, agent_online.agent_id, secret)

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5


# ── Ack error ─────────────────────────────────────────────────────────────────


def test_ack_error_marks_failed_no_reconciliation(mem_engine, agent_online, approved_event, secret):
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-ack-005",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=9,
    )
    payload = _make_ack_payload(
        cmd.command_id, "baseline_update", approved_event.id, agent_online.agent_id, secret,
        ok=False, error="write_failed",
    )

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        row = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-ack-005")).first()
        assert row.ack_status == "failed"
        assert row.error == "write_failed"

        entry = s.exec(
            select(BaselineEntry).where(BaselineEntry.path == approved_event.path)
        ).first()
        assert entry is None, "baseline_entries no debe tocarse en un ack error"

        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5, "ruleset_version_applied no debe avanzar en un ack error"


# ── Validación estructural y de firma ─────────────────────────────────────────


def test_ack_missing_command_id_discarded(mem_engine, agent_online, secret):
    import app.modules.agents.command_ack_consumer as mod

    payload = {
        "command_type": "baseline_update",
        "event_id": 1,
        "agent_id": agent_online.agent_id,
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload["signature"] = sign_payload(secret, payload)

    msg_data = {"data": json.dumps(payload)}
    with patch.object(mod, "engine", mem_engine):
        mod._handle_command_ack(msg_data)  # no debe lanzar

    with Session(mem_engine) as s:
        assert s.exec(select(PublishedCommand)).all() == []


def test_ack_unknown_command_id_discarded(mem_engine, agent_online, secret):
    payload = _make_ack_payload("cmd-does-not-exist", "baseline_update", 1, agent_online.agent_id, secret)

    _handle(mem_engine, payload)  # no debe lanzar, no debe crear filas

    with Session(mem_engine) as s:
        assert s.exec(select(PublishedCommand)).all() == []


def test_ack_invalid_signature_rejected(mem_engine, agent_online, approved_event, secret):
    """Decisión del usuario (C36): ack con firma inválida se rechaza, no actualiza la fila."""
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-ack-badsig",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=9,
    )
    payload = _make_ack_payload(cmd.command_id, "baseline_update", approved_event.id, agent_online.agent_id, secret)
    payload["signature"] = "0" * 64  # firma inválida

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        row = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-ack-badsig")).first()
        assert row.ack_status == "pending", "la fila no debe actualizarse con firma inválida"
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5


# ── Idempotencia ──────────────────────────────────────────────────────────────


def test_ack_repeated_is_idempotent(mem_engine, agent_online, approved_event, secret):
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-ack-idem",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=9,
    )
    payload = _make_ack_payload(cmd.command_id, "baseline_update", approved_event.id, agent_online.agent_id, secret)

    _handle(mem_engine, payload)
    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        agent.ruleset_version_applied = 2  # simular un downgrade manual imposible en la práctica
        s.add(agent)
        s.commit()

    # Segundo ack idéntico: la fila ya es terminal (acked) -> no debe reaplicar efectos
    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 2, "un ack repetido no debe re-aplicar efectos secundarios"


# ── Barrido de timeout ────────────────────────────────────────────────────────


def test_sweep_marks_expired_pending_as_timeout(mem_engine, agent_online):
    import app.modules.agents.command_ack_consumer as mod

    old = datetime.now(timezone.utc) - timedelta(seconds=9999)
    with Session(mem_engine) as s:
        s.add(PublishedCommand(
            command_type="restore_file", target_agent_id=agent_online.agent_id,
            command_id="cmd-timeout-1", ack_status="pending", ruleset_version=0,
            status="published", published_at=old,
        ))
        s.commit()

    with patch.object(mod, "engine", mem_engine):
        mod._sweep_timeouts()

    with Session(mem_engine) as s:
        cmd = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-timeout-1")).first()
        assert cmd.ack_status == "timeout"


def test_sweep_excludes_null_ack_status_and_terminal_rows(mem_engine, agent_online):
    import app.modules.agents.command_ack_consumer as mod

    old = datetime.now(timezone.utc) - timedelta(seconds=9999)
    with Session(mem_engine) as s:
        s.add(PublishedCommand(
            command_type="rule_sync", target_agent_id=agent_online.agent_id,
            command_id=None, ack_status=None, ruleset_version=1,
            status="published", published_at=old,
        ))
        s.add(PublishedCommand(
            command_type="restore_file", target_agent_id=agent_online.agent_id,
            command_id="cmd-already-acked", ack_status="acked", ruleset_version=0,
            status="published", published_at=old, acked_at=old,
        ))
        s.commit()

    with patch.object(mod, "engine", mem_engine):
        mod._sweep_timeouts()

    with Session(mem_engine) as s:
        rule_sync_cmd = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "rule_sync")).first()
        acked_cmd = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-already-acked")).first()
        assert rule_sync_cmd.ack_status is None
        assert acked_cmd.ack_status == "acked"


def test_sweep_does_not_touch_fresh_pending(mem_engine, agent_online):
    import app.modules.agents.command_ack_consumer as mod

    with Session(mem_engine) as s:
        s.add(PublishedCommand(
            command_type="restore_file", target_agent_id=agent_online.agent_id,
            command_id="cmd-fresh", ack_status="pending", ruleset_version=0,
            status="published", published_at=datetime.now(timezone.utc),
        ))
        s.commit()

    with patch.object(mod, "engine", mem_engine):
        mod._sweep_timeouts()

    with Session(mem_engine) as s:
        cmd = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-fresh")).first()
        assert cmd.ack_status == "pending"


# ── FIX 1: autorización cross-agent (confused deputy) ──────────────────────────


def test_ack_cross_agent_forge_rejected(mem_engine, agent_online, approved_event, secret):
    """
    Confused deputy: el stream `commands` es broadcast. Un agente A con SU secret
    válido NO debe poder confirmar el comando de la víctima V. El secret verificador
    se resuelve desde cmd.target_agent_id (V), NUNCA desde payload.agent_id (A).
    """
    attacker_secret = os.urandom(32)
    with Session(mem_engine) as s:
        s.add(Agent(
            agent_id="agent-attacker",
            status=AgentStatus.online,
            shared_secret_hex=attacker_secret.hex(),
            ruleset_version_applied=0,
        ))
        s.commit()

    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-victim-001",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,  # dueño = víctima V
        event_id=approved_event.id,
        ruleset_version=9,
    )
    # El atacante firma un ack para el command_id de V con SU propio secret + agent_id.
    forged = _make_ack_payload(
        cmd.command_id, "baseline_update", approved_event.id,
        "agent-attacker", attacker_secret,
    )

    _handle(mem_engine, forged)

    with Session(mem_engine) as s:
        row = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-victim-001")).first()
        assert row.ack_status == "pending", "el ack forjado de otro agente NO debe tocar el comando de V"
        assert row.acked_at is None
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5, "ruleset_version_applied de V no debe avanzar"
        entry = s.exec(select(BaselineEntry).where(BaselineEntry.path == approved_event.path)).first()
        assert entry is None, "el baseline de V no debe reconciliarse por un ack forjado"


def test_ack_spoofed_agent_id_wrong_secret_rejected(mem_engine, agent_online, approved_event, secret):
    """
    Variante: el atacante pone agent_id=V (spoof) pero firma con su propio secret.
    El secret verificador es el de V (por target_agent_id) → la firma no verifica.
    """
    attacker_secret = os.urandom(32)
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-victim-002",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,
        ruleset_version=9,
    )
    forged = _make_ack_payload(
        cmd.command_id, "baseline_update", approved_event.id,
        agent_online.agent_id, attacker_secret,  # agent_id=V, pero secret del atacante
    )

    _handle(mem_engine, forged)

    with Session(mem_engine) as s:
        row = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-victim-002")).first()
        assert row.ack_status == "pending", "firma con secret ajeno no verifica contra el secret de V"
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5


# ── FIX 2: baseline poisoning — command_type/event_id vienen de la fila ────────


def test_ack_payload_command_type_ignored_uses_row(mem_engine, agent_online, approved_event, secret):
    """
    Baseline poisoning: un ack legítimo (firmado por el dueño) que MIENTE declarando
    command_type=baseline_update+event_id sobre una fila restore_file NO debe tocar
    baseline_entries ni avanzar la versión: se usa cmd.command_type (restore_file).
    """
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-poison-001",
        command_type="restore_file",  # la fila NO es baseline_update
        target_agent_id=agent_online.agent_id,
        event_id=None,
        ruleset_version=9,
    )
    payload = _make_ack_payload(
        cmd.command_id, "baseline_update", approved_event.id,  # payload miente
        agent_online.agent_id, secret,
    )

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        row = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-poison-001")).first()
        assert row.ack_status == "acked", "el ack es válido → el comando restore_file se confirma"
        entry = s.exec(select(BaselineEntry).where(BaselineEntry.path == approved_event.path)).first()
        assert entry is None, "baseline NO debe reconciliarse: la fila es restore_file, no baseline_update"
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5, "restore_file no avanza ruleset_version_applied"


def test_ack_reconciles_row_event_id_not_payload(mem_engine, agent_online, approved_event, secret):
    """El event_id para reconciliar es el de la fila (real), no el del payload (mentido)."""
    cmd = _make_pending_command(
        mem_engine,
        command_id="cmd-eid-001",
        command_type="baseline_update",
        target_agent_id=agent_online.agent_id,
        event_id=approved_event.id,  # event_id real de confianza
        ruleset_version=7,
    )
    # payload miente event_id=999999 (inexistente); debe ignorarse y usar cmd.event_id.
    payload = _make_ack_payload(cmd.command_id, "baseline_update", 999999, agent_online.agent_id, secret)

    _handle(mem_engine, payload)

    with Session(mem_engine) as s:
        entry = s.exec(select(BaselineEntry).where(BaselineEntry.path == approved_event.path)).first()
        assert entry is not None, "reconcilió usando cmd.event_id (real), ignorando el event_id del payload"
        assert entry.hash == approved_event.hash_detected


# ── FIX 3: error transitorio (no XACK) vs error de datos (XACK, sin poison-loop) ─


class _FakeAckClient:
    """Cliente Valkey mínimo para ejercitar _process_batch: entrega un batch y registra XACKs."""

    def __init__(self, messages):
        self._messages = messages
        self.xack_calls: list[str] = []

    async def xreadgroup(self, group, name, streams, count, block):
        if self._messages is None:
            return None
        msgs, self._messages = self._messages, None
        from app.core.streams import STREAM_EVENT_ACK

        return [(STREAM_EVENT_ACK, msgs)]

    async def xack(self, stream, group, msg_id):
        self.xack_calls.append(msg_id)


async def test_process_batch_transient_db_error_does_not_xack():
    """DB caída (OperationalError) → NO XACK: el ack queda en el PEL para reintento."""
    import app.modules.agents.command_ack_consumer as mod
    from sqlalchemy.exc import OperationalError

    client = _FakeAckClient([("1-0", {"data": "{}"})])

    def _boom(_msg):
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    with patch.object(mod, "_handle_command_ack", _boom):
        await mod._process_batch(client, ">")

    assert client.xack_calls == [], "error transitorio de DB no debe hacer XACK"


async def test_process_batch_data_error_xacks_no_poison_loop():
    """
    Error de DATOS (IntegrityError) → SÍ XACK y descartar. Este es el fix crítico de
    C35: tratar un error de datos como transitorio genera un poison-loop infinito.
    """
    import app.modules.agents.command_ack_consumer as mod
    from sqlalchemy.exc import IntegrityError

    client = _FakeAckClient([("2-0", {"data": "{}"})])

    def _boom(_msg):
        raise IntegrityError("INSERT", {}, Exception("dup key"))

    with patch.object(mod, "_handle_command_ack", _boom):
        await mod._process_batch(client, ">")

    assert client.xack_calls == ["2-0"], "error de datos debe hacer XACK (sin poison-loop)"


async def test_process_batch_success_xacks():
    """Camino feliz: el handler no lanza → XACK normal."""
    import app.modules.agents.command_ack_consumer as mod

    client = _FakeAckClient([("3-0", {"data": "{}"})])

    with patch.object(mod, "_handle_command_ack", lambda _msg: None):
        await mod._process_batch(client, ">")

    assert client.xack_calls == ["3-0"]
