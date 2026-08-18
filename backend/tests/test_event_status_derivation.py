"""
Tests de regresión para C40 — derivación del status terminal del evento en la
ingesta a partir de action/action_failed (D35/RN-129).

Cubre:
  - derive_event_status: tabla de derivación pura, sin base de datos.
  - El límite real agente -> backend: DetectedChange real -> DecisionEngine.
    evaluate_and_act real -> ingest_event real, para cada fila de la tabla.
    Las filas de fallo provocan un _ActionFailed genuino (baseline ausente /
    archivo inexistente), nunca un patch manual de action_failed.
  - El backend ignora cualquier `status` del payload y no lo deriva jamás en
    approved/rejected/superseded.
  - resolved_at = received_at / resolved_by = NULL para terminales; ambos
    None para pending (incluido el pending por acción fallida).
  - La cadena superseded: un evento entrante terminal supersede al pending
    activo del mismo path; un terminal ya persistido no es superseded después.
  - La ruta rehydrate produce un status consistente con la misma derivación
    y un event_type no contaminado.
  - La migración 007 es idempotente.
  - EventOut expone action_failed.

Sigue el mismo patrón de import de agent.detector/agent.decision desde tests
del backend ya usado en test_event_service.py (repo_root en sys.path) y el
patrón de Session real / mem_engine de test_event_symlink_metadata.py.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus
from app.modules.events.router import _get_ack_status_map, _to_event_out
from app.modules.events.service import derive_event_status, ingest_event

# El agente vive en <repo_root>/agent, fuera del árbol de paquetes del backend.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from agent.decision import DecisionEngine  # noqa: E402
from agent.detector import DetectedChange  # noqa: E402
from agent.journal import JournalManager  # noqa: E402
from agent.rules import RulesCache  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def mem_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _make_event(session: Session, path: str, status: EventStatus) -> Event:
    now = datetime.utcnow()
    e = Event(
        event_id=f"eid-{uuid.uuid4().hex[:8]}",
        agent_id="agent-test",
        path=path,
        hash_detected="abc",
        status=status,
        detected_at=now,
        received_at=now,
        created_at=now,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def _make_decision_engine(tmp_path: Path, action: str) -> tuple[DecisionEngine, MagicMock]:
    """Helper: DecisionEngine real con RulesCache fija, journal real, baseline mock.
    Mismo patrón que agent/tests/test_decision.py::_make_engine."""
    journal_dir = tmp_path / f"journal-{uuid.uuid4().hex[:8]}"
    journal_dir.mkdir()
    quarantine_dir = tmp_path / f"quarantine-{uuid.uuid4().hex[:8]}"
    quarantine_dir.mkdir()

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = action

    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")
    baseline = MagicMock()

    decision_engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )
    return decision_engine, baseline


def _make_change(event_id: str, path: str) -> DetectedChange:
    return DetectedChange(
        event_id=event_id,
        path=path,
        event_type="file_modified",
        operation_type="file_modified",
        hash_expected="e" * 64,
        hash_detected="d" * 64,
        diff_text=None,
        process_pid=42,
        process_uid=0,
        process_exe="/usr/bin/vim",
        detected_at="2026-08-13T00:00:00+00:00",
        parent_event_id=None,
    )


def _ingest(mem_engine, payload: dict, received_at: datetime, detected_at: datetime) -> Event | None:
    import app.modules.events.service as svc

    payload.setdefault("agent_id", "agent-test")
    with patch.object(svc, "engine", mem_engine):
        return ingest_event(payload, received_at, detected_at)


# ── 7.1 — derive_event_status: tabla de derivación pura ────────────────────────

@pytest.mark.parametrize(
    "action, action_failed, expected",
    [
        ("auto_restore", False, EventStatus.auto_restored),
        ("quarantine", False, EventStatus.quarantined),
        ("alert_only", False, EventStatus.alert_only),
        ("alert_only", True, EventStatus.alert_only),  # indiferente: no ejecuta acción física
        ("manual_review", False, EventStatus.pending),
        ("auto_restore", True, EventStatus.pending),
        ("quarantine", True, EventStatus.pending),
        (None, False, EventStatus.pending),
        ("some_future_action", False, EventStatus.pending),
    ],
)
def test_derive_event_status_table(action, action_failed, expected) -> None:
    assert derive_event_status(action, action_failed) == expected


# ── 7.2 / 7.3 — cruce real del límite agente -> backend, por fila de la tabla ──

def test_row_auto_restore_success_yields_auto_restored(mem_engine, tmp_path: Path) -> None:
    content = b"good content"
    content_hash = hashlib.sha256(content).hexdigest()
    target = tmp_path / "row1_target.txt"
    target.write_bytes(b"bad content")

    decision_engine, baseline = _make_decision_engine(tmp_path, "auto_restore")
    entry = MagicMock()
    entry.content_b64 = base64.b64encode(content).decode()
    entry.hash = content_hash
    # D36/RN-130 (D-6): la restauración exige mode/uid/gid del baseline; sin
    # ellos aborta con no_baseline_metadata. uid/gid del proceso actual para
    # que el fchown sea un no-op permitido sin CAP_CHOWN.
    entry.mode = "0o644"
    entry.uid = os.getuid()
    entry.gid = os.getgid()
    baseline.read_entry.return_value = entry

    change = _make_change("evt-row1", str(target))
    payload, _commit_fn = decision_engine.evaluate_and_act(change)

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.auto_restored
    assert event.action_failed is False
    # SQLite (mem_engine) no preserva tzinfo en el roundtrip; comparar naive.
    assert event.resolved_at == now.replace(tzinfo=None)
    assert event.resolved_by is None
    assert target.read_bytes() == content


def test_row_quarantine_success_yields_quarantined(mem_engine, tmp_path: Path) -> None:
    target = tmp_path / "row2_target.txt"
    target.write_bytes(b"content")

    decision_engine, _baseline = _make_decision_engine(tmp_path, "quarantine")
    change = _make_change("evt-row2", str(target))
    payload, _commit_fn = decision_engine.evaluate_and_act(change)

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.quarantined
    assert event.action_failed is False
    # SQLite (mem_engine) no preserva tzinfo en el roundtrip; comparar naive.
    assert event.resolved_at == now.replace(tzinfo=None)
    assert event.resolved_by is None
    assert not target.exists()  # movido a cuarentena


def test_row_alert_only_yields_alert_only(mem_engine, tmp_path: Path) -> None:
    decision_engine, _baseline = _make_decision_engine(tmp_path, "alert_only")
    change = _make_change("evt-row3", str(tmp_path / "row3_target.txt"))
    payload, _commit_fn = decision_engine.evaluate_and_act(change)

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.alert_only
    assert event.action_failed is False
    # SQLite (mem_engine) no preserva tzinfo en el roundtrip; comparar naive.
    assert event.resolved_at == now.replace(tzinfo=None)
    assert event.resolved_by is None


def test_row_manual_review_yields_pending(mem_engine, tmp_path: Path) -> None:
    decision_engine, _baseline = _make_decision_engine(tmp_path, "manual_review")
    change = _make_change("evt-row4", str(tmp_path / "row4_target.txt"))
    payload, _commit_fn = decision_engine.evaluate_and_act(change)

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.pending
    assert event.action_failed is False
    assert event.resolved_at is None
    assert event.resolved_by is None


def test_row_auto_restore_genuine_failure_yields_pending(mem_engine, tmp_path: Path) -> None:
    """Provoca un _ActionFailed genuino: sin entrada de baseline (no_baseline_content).
    NO se parchea action_failed a mano — es el resultado real de evaluate_and_act."""
    target = tmp_path / "row5_target.txt"
    target.write_bytes(b"tampered")

    decision_engine, baseline = _make_decision_engine(tmp_path, "auto_restore")
    baseline.read_entry.return_value = None  # fuerza _ActionFailed genuino

    change = _make_change("evt-row5", str(target))
    payload, _commit_fn = decision_engine.evaluate_and_act(change)
    assert payload["action_failed"] is True  # confirma que el fallo fue real, no simulado

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.pending
    assert event.action_failed is True
    assert event.resolved_at is None
    assert event.resolved_by is None
    assert target.read_bytes() == b"tampered"  # el archivo sigue adulterado


def test_row_quarantine_genuine_failure_yields_pending(mem_engine, tmp_path: Path) -> None:
    """Provoca un _ActionFailed genuino: el archivo a mover no existe (file_not_found)."""
    missing_target = tmp_path / "row6_missing.txt"  # nunca se crea

    decision_engine, _baseline = _make_decision_engine(tmp_path, "quarantine")
    change = _make_change("evt-row6", str(missing_target))
    payload, _commit_fn = decision_engine.evaluate_and_act(change)
    assert payload["action_failed"] is True

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.pending
    assert event.action_failed is True
    assert event.resolved_at is None
    assert event.resolved_by is None


def test_row_absent_action_from_older_agent_yields_pending(mem_engine) -> None:
    """Payload de un agente de versión anterior: to_event_data() real sin pasar
    por DecisionEngine, porque un agente viejo nunca produjo la clave `action`."""
    change = DetectedChange(
        event_id="evt-row7",
        path="/etc/older-agent-path",
        event_type="file_modified",
        operation_type="file_modified",
        hash_expected="e" * 64,
        hash_detected="d" * 64,
        diff_text=None,
        process_pid=1,
        process_uid=0,
        process_exe=None,
        detected_at="2026-08-13T00:00:00+00:00",
        parent_event_id=None,
    )
    payload = change.to_event_data()
    assert "action" not in payload

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.pending
    assert event.action_failed is False
    assert event.resolved_at is None
    assert event.resolved_by is None


# ── 7.4 — el backend ignora cualquier `status` del payload ────────────────────

def test_explicit_status_key_is_ignored(mem_engine) -> None:
    now = _now()
    payload = {
        "event_id": "uuid-ignore-status",
        "path": "/etc/ignored",
        "hash_detected": "abc",
        "status": "approved",  # debe ser ignorado por completo
    }
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.pending  # ausencia de action -> pending, NUNCA approved


@pytest.mark.parametrize("forged_status", ["approved", "rejected", "superseded"])
def test_forged_status_cannot_induce_backend_exclusive_transitions(mem_engine, forged_status: str) -> None:
    now = _now()
    payload = {
        "event_id": f"uuid-forge-{forged_status}",
        "path": f"/etc/forge-{forged_status}",
        "hash_detected": "abc",
        "status": forged_status,
        "action": forged_status,  # tampoco es un action reconocido
    }
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.pending


# ── 7.6 — cadena superseded con eventos terminales ─────────────────────────────

def test_incoming_terminal_event_supersedes_active_pending(mem_engine, tmp_path: Path) -> None:
    target = tmp_path / "supersede_target.txt"
    target.write_bytes(b"content")
    path = str(target)

    with Session(mem_engine) as session:
        old = _make_event(session, path, EventStatus.pending)
        old_id = old.id

    decision_engine, _baseline = _make_decision_engine(tmp_path, "quarantine")
    change = _make_change("evt-supersede", path)
    payload, _commit_fn = decision_engine.evaluate_and_act(change)

    now = _now()
    new_event = _ingest(mem_engine, payload, now, now)

    assert new_event is not None
    assert new_event.status == EventStatus.quarantined
    assert new_event.parent_event_id == old_id

    with Session(mem_engine) as session:
        old_refreshed = session.exec(select(Event).where(Event.id == old_id)).first()
    assert old_refreshed is not None
    assert old_refreshed.status == EventStatus.superseded


def test_persisted_terminal_event_is_never_superseded_afterward(mem_engine) -> None:
    path = "/etc/already-terminal"
    with Session(mem_engine) as session:
        terminal = _make_event(session, path, EventStatus.auto_restored)
        terminal_id = terminal.id

    now = _now()
    payload = {"event_id": "uuid-after-terminal", "path": path, "hash_detected": "abc"}
    new_event = _ingest(mem_engine, payload, now, now)

    assert new_event is not None
    assert new_event.parent_event_id is None  # la consulta de supersesión solo alcanza pending

    with Session(mem_engine) as session:
        terminal_refreshed = session.exec(select(Event).where(Event.id == terminal_id)).first()
    assert terminal_refreshed is not None
    assert terminal_refreshed.status == EventStatus.auto_restored  # sin cambios


# ── 7.7 — ruta rehydrate: status consistente, event_type no contaminado ───────

@pytest.mark.asyncio
async def test_rehydrate_auto_restore_yields_consistent_status(mem_engine, tmp_path: Path) -> None:
    content = b"good content"
    content_hash = hashlib.sha256(content).hexdigest()
    target = tmp_path / "rehydrate_target.txt"
    target.write_bytes(b"tampered")

    decision_engine, baseline = _make_decision_engine(tmp_path, "auto_restore")
    entry = MagicMock()
    entry.content_b64 = base64.b64encode(content).decode()
    entry.hash = content_hash
    # D36/RN-130 (D-6): ver nota en test_row_auto_restore_success_yields_auto_restored.
    entry.mode = "0o644"
    entry.uid = os.getuid()
    entry.gid = os.getgid()
    baseline.read_entry.return_value = entry

    decision_engine._journal.write_pending("evt-rehy-status", str(target), "auto_restore")

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    await decision_engine.rehydrate(publisher)

    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]
    # D35/RN-129: event_type conserva el valor del journal (RN-71), no se
    # sobrescribe con el resultado de la acción.
    assert payload["event_type"] == "file_modified"
    assert payload["action"] == "auto_restore"

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.auto_restored
    assert event.action_failed is False


@pytest.mark.asyncio
async def test_rehydrate_failed_entry_yields_pending(mem_engine, tmp_path: Path) -> None:
    missing_target = tmp_path / "rehydrate_missing.txt"

    decision_engine, baseline = _make_decision_engine(tmp_path, "auto_restore")
    baseline.read_entry.return_value = None  # _ActionFailed genuino en la rehidratación

    decision_engine._journal.write_pending("evt-rehy-fail", str(missing_target), "auto_restore")

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    await decision_engine.rehydrate(publisher)

    payload = publisher.publish.call_args[0][0]
    assert payload["action_failed"] is True
    assert payload["event_type"] == "file_modified"

    now = _now()
    event = _ingest(mem_engine, payload, now, now)

    assert event is not None
    assert event.status == EventStatus.pending
    assert event.action_failed is True


# ── 7.8 — migración 007: idempotencia y presencia de la columna ───────────────

def test_migration_007_is_idempotent() -> None:
    migration_path = _REPO_ROOT / "backend" / "db" / "migrations" / "007_add_event_action_failed.sql"
    sql = migration_path.read_text()

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        # Segunda ejecución: no debe lanzar (ADD COLUMN IF NOT EXISTS).
        conn.execute(text(sql))
        conn.commit()


def test_events_table_has_action_failed_column_after_migration() -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'events' AND column_name = 'action_failed'"
            )
        ).all()
    assert {r[0] for r in rows} == {"action_failed"}


# ── 7.9 — EventOut expone action_failed ────────────────────────────────────────

@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(agent_id=f"agent-evt-status-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_event_out_serializes_action_failed_true(session: Session, agent: Agent) -> None:
    event = Event(
        event_id=f"evt-action-failed-{uuid.uuid4().hex[:8]}",
        agent_id=agent.agent_id,
        path="/etc/failed-remediation",
        hash_detected="deadbeef",
        status=EventStatus.pending,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        action_failed=True,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.action_failed is True
    assert out.status == EventStatus.pending


def test_event_out_defaults_action_failed_false(session: Session, agent: Agent) -> None:
    event = Event(
        event_id=f"evt-action-ok-{uuid.uuid4().hex[:8]}",
        agent_id=agent.agent_id,
        path="/etc/ordinary",
        hash_detected="feedface",
        status=EventStatus.auto_restored,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.action_failed is False
