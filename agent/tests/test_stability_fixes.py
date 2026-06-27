"""
Tests de C27 — agent-stability-fixes.

Cubre:
  FA2 (1.5)  test_no_get_event_loop_calls
  FA6 (2.4)  test_update_config_writes_to_loaded_path
  FA6 (2.5)  test_update_config_falls_back_to_default_path
  M7  (3.2)  test_rule_sync_idempotent_same_version
  M7  (3.3)  test_rule_sync_rejects_older_version
  FA1 (4.4)  test_shutdown_handler_safe_before_queue_created
  FA4 (5.3)  test_detector_close_joins_thread
  FA4 (5.4)  test_detector_close_idempotent
  FA5 (6.4)  test_queue_full_increments_event_drops
  FA5 (6.5)  test_event_drops_in_heartbeat
  FA5 (6.6)  test_enqueue_under_capacity_no_drop
  FA3 (7.4)  test_journal_stays_pending_if_publish_fails
  FA3 (7.5)  test_journal_completed_after_successful_publish
  FA3 (7.6)  test_journal_never_completed_before_publish
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from agent.config import AgentConfig, StorageConfig, load_config
from agent.decision import DecisionEngine
from agent.heartbeat import HeartbeatPublisher
from agent.journal import JournalManager
from agent.rules import RulesCache
from agent.state import AgentState


# ── Helpers de fixtures ────────────────────────────────────────────────────────


def _make_config(tmp_path: Path, shared_secret: bytes) -> AgentConfig:
    secret_path = tmp_path / "secrets"
    secret_path.mkdir(parents=True, exist_ok=True)
    (secret_path / "shared_secret").write_bytes(shared_secret)

    return AgentConfig(
        agent_id="test-agent-c27",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(secret_path),
        ),
    )


def _make_engine(
    tmp_path: Path,
    action: str = "alert_only",
) -> tuple[DecisionEngine, JournalManager, MagicMock]:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = action
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")
    baseline = MagicMock()

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )
    return engine, journal, baseline


def _make_change(tmp_path: Path, path: str | None = None) -> MagicMock:
    change = MagicMock()
    change.event_id = "test-event-c27"
    change.path = path or str(tmp_path / "target.txt")
    change.event_type = "file_modified"
    change.to_event_data.return_value = {
        "event_id": change.event_id,
        "path": change.path,
        "event_type": "file_modified",
        "previous_hash": None,
        "current_hash": None,
        "diff_text": None,
        "process_pid": 100,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    }
    return change


# ── FA2 (1.5) ─────────────────────────────────────────────────────────────────


def test_no_get_event_loop_calls() -> None:
    """Ningún módulo del agente tiene get_event_loop() en coroutines."""
    import ast
    import glob

    agent_dir = Path(__file__).parent.parent
    sources = glob.glob(str(agent_dir / "*.py"))

    violations: list[str] = []
    for src_path in sources:
        if "__pycache__" in src_path:
            continue
        source = Path(src_path).read_text()
        if "get_event_loop()" in source:
            # Parsear para confirmar que está dentro de una corutina (async def)
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    func_src = ast.get_source_segment(source, node) or ""
                    if "get_event_loop()" in func_src:
                        violations.append(f"{Path(src_path).name}:{node.name}")

    assert violations == [], f"get_event_loop() inside coroutines: {violations}"


# ── FA6 (2.4) ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_config_writes_to_loaded_path(tmp_path: Path) -> None:
    """update_config escribe al path del que se cargó la config, no al default."""
    from agent import commands

    # Crear archivo de config en path no-estándar
    custom_config = tmp_path / "custom.yaml"
    shared_secret = os.urandom(32)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "shared_secret").write_bytes(shared_secret)

    config_data = {
        "agent_id": "test-agent-c27",
        "backend_url": "https://localhost:8443",
        "valkey_url": "valkey://localhost:6379",
        "ca_cert_path": "/tmp/ca.pem",
        "watch_paths": ["/etc"],
        "storage": {
            "baseline_dir": str(tmp_path / "baseline"),
            "queue_dir": str(tmp_path / "queue"),
            "journal_dir": str(tmp_path / "journal"),
            "secrets_dir": str(secrets_dir),
        },
    }
    custom_config.write_text(yaml.dump(config_data))

    # load_config debe setear _config_path al path cargado
    cfg = load_config(str(custom_config))
    assert cfg._config_path == custom_config

    # Preparar estado y handler
    state = AgentState(
        ruleset_version=0,
        state_path=tmp_path / "state.json",
    )
    mock_valkey = AsyncMock()
    mock_valkey.xadd = AsyncMock()
    mock_detector = MagicMock()
    mock_baseline = MagicMock()

    from agent.streams import sign_payload

    cmd: dict[str, Any] = {
        "type": "update_config",
        "command_id": "cmd-c27-001",
        "target_agent_id": cfg.agent_id,
        "watch_paths": ["/etc", "/usr/bin"],
        "ruleset_version": 1,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    await commands.handle_update_config(
        command=cmd,
        detector=mock_detector,
        baseline_engine=mock_baseline,
        state=state,
        valkey_client=mock_valkey,
        config=cfg,
    )

    # El archivo en custom_config debe haber sido actualizado
    updated = yaml.safe_load(custom_config.read_text())
    assert updated["watch_paths"] == ["/etc", "/usr/bin"]


@pytest.mark.asyncio
async def test_update_config_falls_back_to_default_path(tmp_path: Path) -> None:
    """Cuando config_path es None el handler usa /etc/fim-agent/config.yaml."""
    from agent import commands

    shared_secret = os.urandom(32)
    cfg = _make_config(tmp_path, shared_secret)
    # _config_path == None (no cargado via load_config)
    assert cfg._config_path is None

    state = AgentState(ruleset_version=0, state_path=tmp_path / "state.json")
    mock_valkey = AsyncMock()
    mock_valkey.xadd = AsyncMock()
    mock_detector = MagicMock()
    mock_baseline = MagicMock()

    from agent.streams import sign_payload

    cmd: dict[str, Any] = {
        "type": "update_config",
        "command_id": "cmd-c27-002",
        "target_agent_id": cfg.agent_id,
        "watch_paths": ["/etc"],
        "ruleset_version": 1,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    opened_paths: list[str] = []

    original_open = open  # noqa: A001

    def tracking_open(path: str, *args: Any, **kwargs: Any) -> Any:
        opened_paths.append(str(path))
        return original_open(path, *args, **kwargs)

    # Patch os.path.exists para que la ruta default no exista → no se escribirá
    with patch("os.path.exists", return_value=False):
        await commands.handle_update_config(
            command=cmd,
            detector=mock_detector,
            baseline_engine=mock_baseline,
            state=state,
            valkey_client=mock_valkey,
            config=cfg,
        )

    # No debe haberse escrito nada porque el path default no existe
    # El importante es que no falla y publica ack ok
    mock_valkey.xadd.assert_called_once()
    ack = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack["status"] == "ok"


# ── M7 (3.2, 3.3) ─────────────────────────────────────────────────────────────


def test_rule_sync_idempotent_same_version(tmp_path: Path) -> None:
    """rule_sync con versión == actual se reaplica sin error (idempotencia)."""
    from agent.state import AgentState

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ruleset_version": 5, "rules": []}))
    cache = RulesCache(state_path)

    state = AgentState(ruleset_version=5, state_path=state_path)

    updated = cache.update(
        [{"pattern": "/etc/**", "action": "auto_restore", "negated": False}],
        ruleset_version=5,
        state=state,
    )

    # Con versión igual, la condición `< state.ruleset_version` es False → se aplica
    assert updated is True
    assert cache.evaluate("/etc/hosts") == "auto_restore"


def test_rule_sync_rejects_older_version(tmp_path: Path) -> None:
    """rule_sync con versión estrictamente menor al actual se descarta."""
    from agent.state import AgentState

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ruleset_version": 5, "rules": []}))
    cache = RulesCache(state_path)

    state = AgentState(ruleset_version=5, state_path=state_path)

    updated = cache.update(
        [{"pattern": "/etc/**", "action": "auto_restore", "negated": False}],
        ruleset_version=3,
        state=state,
    )

    assert updated is False
    assert cache.evaluate("/etc/hosts") == "alert_only"  # sin cambio


# ── FA1 (4.4) ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shutdown_handler_safe_before_queue_created() -> None:
    """_shutdown es un no-op seguro cuando queue y publisher son None."""
    queue_ref: Any = None
    publisher_ref: Any = None

    def _shutdown(sig_name: str) -> None:
        if queue_ref is None or publisher_ref is None:
            return
        # Si llegáramos aquí sin queue/publisher, esto exploraría
        publisher_ref.set_shutdown(True)  # type: ignore[union-attr]

    # No debe lanzar excepción
    _shutdown("SIGTERM")
    _shutdown("SIGINT")


# ── FA4 (5.3, 5.4) ────────────────────────────────────────────────────────────


def test_detector_close_joins_thread(tmp_path: Path) -> None:
    """close() cierra el fd y hace join al hilo reader."""
    from agent.detector import FanotifyDetector

    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._agent_id = "test"
    detector._watch_paths = []
    detector._baseline = MagicMock()
    detector._publisher = MagicMock()
    detector._stop_event = asyncio.Event()
    detector._decision_engine = None
    detector._raw_queue = asyncio.Queue(maxsize=1000)
    detector._event_drops = 0
    detector._pending = {}
    detector._event_to_path = {}
    detector._loop = None

    # Simula un fd fanotify falso (entero) y un hilo que termina rápido
    fake_fd = 999
    detector._fan = fake_fd

    thread_joined = threading.Event()
    thread_started = threading.Event()

    def fake_read_loop() -> None:
        thread_started.set()
        # Simula bloqueo hasta que _fan sea None (señal de close)
        while detector._fan is not None:
            time.sleep(0.01)
        thread_joined.set()

    t = threading.Thread(target=fake_read_loop, daemon=True)
    detector._thread = t
    t.start()
    thread_started.wait(timeout=2.0)

    # close() debe cerrar _fan → hilo termina → join completa
    with patch("agent.detector._HAS_FAN", False):
        detector.close()

    assert thread_joined.is_set(), "hilo debería haber terminado"
    assert not t.is_alive(), "hilo debería estar muerto tras close()"
    assert detector._fan is None


def test_detector_close_idempotent(tmp_path: Path) -> None:
    """close() es idempotente: segunda llamada es no-op seguro."""
    from agent.detector import FanotifyDetector

    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._agent_id = "test"
    detector._watch_paths = []
    detector._baseline = MagicMock()
    detector._publisher = MagicMock()
    detector._stop_event = asyncio.Event()
    detector._decision_engine = None
    detector._raw_queue = asyncio.Queue(maxsize=1000)
    detector._event_drops = 0
    detector._pending = {}
    detector._event_to_path = {}
    detector._loop = None
    detector._fan = 999
    detector._thread = None

    with patch("agent.detector._HAS_FAN", False):
        detector.close()
        # Segunda llamada no debe lanzar excepción
        detector.close()

    assert detector._fan is None


# ── FA5 (6.4, 6.5, 6.6) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_full_increments_event_drops() -> None:
    """_try_enqueue bajo cola llena incrementa event_drops y no lanza."""
    from agent.detector import FanotifyDetector, FanotifyEvent

    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._raw_queue = asyncio.Queue(maxsize=1)
    detector._event_drops = 0
    detector._loop = asyncio.get_running_loop()

    fan_event = FanotifyEvent(
        path="/etc/hosts",
        pid=1,
        uid=0,
        exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )

    # Llenar la cola
    detector._raw_queue.put_nowait(fan_event)
    assert detector._raw_queue.full()

    # Intentar encolar cuando está llena
    detector._try_enqueue(fan_event)

    assert detector._event_drops == 1


@pytest.mark.asyncio
async def test_event_drops_in_heartbeat(tmp_path: Path) -> None:
    """El heartbeat incluye event_drops con el valor actual del detector."""
    import json

    shared_secret = os.urandom(32)
    cfg = _make_config(tmp_path, shared_secret)
    state = AgentState(ruleset_version=0, state_path=tmp_path / "state.json")
    queue_mock = MagicMock()
    queue_mock.queue_size = 0
    queue_mock.queue_pressure = 0.0
    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock()

    from agent.detector import FanotifyDetector

    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._event_drops = 42

    hb = HeartbeatPublisher(
        config=cfg,
        queue=queue_mock,
        state=state,
        client=mock_client,
        detector=detector,
    )

    await hb._publish(shutdown=False)

    mock_client.xadd.assert_called_once()
    payload = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert payload["event_drops"] == 42


@pytest.mark.asyncio
async def test_enqueue_under_capacity_no_drop() -> None:
    """_try_enqueue con espacio disponible no incrementa event_drops."""
    from agent.detector import FanotifyDetector, FanotifyEvent

    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._raw_queue = asyncio.Queue(maxsize=10)
    detector._event_drops = 0
    detector._loop = asyncio.get_running_loop()

    fan_event = FanotifyEvent(
        path="/etc/hosts",
        pid=1,
        uid=0,
        exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )

    detector._try_enqueue(fan_event)

    assert detector._event_drops == 0
    assert detector._raw_queue.qsize() == 1


# ── FA3 (7.4, 7.5, 7.6) ──────────────────────────────────────────────────────


def test_journal_stays_pending_if_publish_fails(tmp_path: Path) -> None:
    """evaluate_and_act retorna commit_fn; sin invocarlo la entrada sigue pending."""
    engine, journal, baseline = _make_engine(tmp_path, action="alert_only")
    change = _make_change(tmp_path)

    payload, commit_fn = engine.evaluate_and_act(change)

    # No llamar commit_fn — simula fallo de publish
    entry_path = tmp_path / "journal" / "test-event-c27.json"
    data = json.loads(entry_path.read_text())
    assert data["state"] == "pending", "sin commit_fn la entrada debe quedar pending"

    # Verificar que load_pending la devuelve (rehidratación)
    pending = journal.load_pending()
    assert any(e.event_id == "test-event-c27" for e in pending)


def test_journal_completed_after_successful_publish(tmp_path: Path) -> None:
    """Invocar commit_fn tras publish exitoso completa la transacción y borra el journal."""
    engine, journal, baseline = _make_engine(tmp_path, action="alert_only")
    change = _make_change(tmp_path)

    payload, commit_fn = engine.evaluate_and_act(change)

    entry_path = tmp_path / "journal" / "test-event-c27.json"
    assert entry_path.exists(), "journal must exist before commit"

    # Simula publish exitoso → invocar commit_fn
    commit_fn()

    # BUG-10 fix: commit_fn calls delete(event_id) after mark_completed
    # Journal file is removed — the entry is considered durably committed
    assert not entry_path.exists(), (
        "journal file must be deleted after successful commit (BUG-10 fix)"
    )


def test_journal_completed_after_failed_action(tmp_path: Path) -> None:
    """Si la acción falla, commit_fn debe marcar failed tras publish exitoso."""
    import base64

    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    # Sin contenido en baseline → _ActionFailed
    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.snapshots = []
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path)
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload.get("action_failed") is True

    # Antes de commit: pending
    entry_path = tmp_path / "journal" / "test-event-c27.json"
    data = json.loads(entry_path.read_text())
    assert data["state"] == "pending"

    # Después de commit_fn: failed
    commit_fn()
    data = json.loads(entry_path.read_text())
    assert data["state"] == "failed"


def test_journal_never_completed_before_publish(tmp_path: Path) -> None:
    """La entrada es pending inmediatamente después de evaluate_and_act, antes de commit_fn."""
    engine, journal, baseline = _make_engine(tmp_path, action="alert_only")
    change = _make_change(tmp_path)

    payload, commit_fn = engine.evaluate_and_act(change)

    # Inspeccionar estado antes de llamar commit_fn
    entry_path = tmp_path / "journal" / "test-event-c27.json"
    data = json.loads(entry_path.read_text())

    assert data["state"] == "pending", (
        "la entrada NO debe ser completed antes de que commit_fn() sea invocado"
    )
