"""
Tests del agente para C14 (tasks 13.1–13.11).

Cubre:
  13.1  test_run_scan_creates_baseline_entries
  13.2  test_run_scan_skips_nonexistent_path
  13.3  test_reload_watch_paths_marks_new
  13.4  test_reload_watch_paths_unmarks_removed
  13.5  test_update_config_handler_reloads_detector
  13.6  test_update_config_handler_publishes_ack
  13.7  test_update_config_updates_state_ruleset_version
  13.8  test_rescan_baseline_handler_calls_run_scan
  13.9  test_rescan_baseline_handler_publishes_ack
  13.10 test_dispatch_routes_update_config
  13.11 test_dispatch_routes_rescan_baseline

US-22 (path selection + guard de versión en rescan_baseline):
  test_rescan_baseline_handler_scans_only_specified_paths
  test_rescan_baseline_handler_rejects_paths_outside_watch_roots
  test_rescan_baseline_handler_ignores_stale_version
  test_rescan_baseline_handler_updates_state_ruleset_version

Los tests que requieren el backend fanotify interno se mockean completamente.
Los tests que requieren chmod/operaciones Unix de bajo nivel se saltan en Windows.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.baseline import BaselineEngine
from agent.config import AgentConfig, StorageConfig
from agent.state import AgentState
from agent.streams import sign_payload

_LINUX = platform.system() == "Linux"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def master_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def shared_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def tmp_dirs(tmp_path: Path) -> dict[str, Path]:
    dirs = {
        "baseline": tmp_path / "baseline",
        "queue": tmp_path / "queue",
        "journal": tmp_path / "journal",
        "secrets": tmp_path / "secrets",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture()
def agent_config(tmp_dirs: dict[str, Path], shared_secret: bytes) -> AgentConfig:
    secret_path = tmp_dirs["secrets"] / "shared_secret"
    secret_path.write_bytes(shared_secret)

    return AgentConfig(
        agent_id="test-agent-c14",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_dirs["baseline"]),
            queue_dir=str(tmp_dirs["queue"]),
            journal_dir=str(tmp_dirs["journal"]),
            secrets_dir=str(tmp_dirs["secrets"]),
        ),
    )


@pytest.fixture()
def baseline_engine(agent_config: AgentConfig, master_secret: bytes) -> BaselineEngine:
    return BaselineEngine(agent_config, master_secret)


@pytest.fixture()
def agent_state(tmp_dirs: dict[str, Path]) -> AgentState:
    state_path = tmp_dirs["secrets"] / "state.json"
    return AgentState(ruleset_version=0, state_path=state_path)


@pytest.fixture()
def mock_valkey() -> AsyncMock:
    client = AsyncMock()
    client.xadd = AsyncMock()
    return client


def _make_command(
    agent_config: AgentConfig,
    shared_secret: bytes,
    cmd_type: str,
    extra: dict | None = None,
) -> dict:
    """Construye y firma un comando del stream commands."""
    payload: dict = {
        "type": cmd_type,
        "command_id": f"cmd-c14-{cmd_type}",
        "target_agent_id": agent_config.agent_id,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    if extra:
        payload.update(extra)
    payload["signature"] = sign_payload(shared_secret, payload)
    return payload


# ── 13.1 test_run_scan_creates_baseline_entries ───────────────────────────────


def test_run_scan_creates_baseline_entries(baseline_engine, tmp_path):
    """run_scan crea entradas de baseline para archivos en el path dado."""
    scan_dir = tmp_path / "scan_target"
    scan_dir.mkdir()

    # Crear archivos para escanear
    (scan_dir / "file1.txt").write_text("content 1")
    (scan_dir / "file2.conf").write_text("content 2")
    subdir = scan_dir / "subdir"
    subdir.mkdir()
    (subdir / "file3.txt").write_text("content 3")

    report = baseline_engine.run_scan([str(scan_dir)])

    assert report.scanned == 3
    assert report.errors == 0

    # Verificar que las entradas existen
    for fname in ["file1.txt", "file2.conf"]:
        entry = baseline_engine.read_entry(str(scan_dir / fname))
        assert entry is not None
        assert entry.status == "present"
        assert entry.hash is not None

    entry_sub = baseline_engine.read_entry(str(subdir / "file3.txt"))
    assert entry_sub is not None
    assert entry_sub.status == "present"


# ── 13.2 test_run_scan_skips_nonexistent_path ─────────────────────────────────


def test_run_scan_skips_nonexistent_path(baseline_engine, tmp_path):
    """Path inexistente → log warning, sin excepción, report normal."""
    report = baseline_engine.run_scan(["/nonexistent/path/that/does/not/exist"])

    # Sin excepción, sin archivos escaneados ni errores
    assert report.scanned == 0
    assert report.errors == 0


# ── 13.3 test_reload_watch_paths_marks_new ────────────────────────────────────


def _fake_fan_mod() -> MagicMock:
    """Mock del módulo ctypes de fanotify con las constantes reales usadas por
    ``FanotifyDetector.reload_watch_paths`` (agent/detector.py)."""
    fake = MagicMock()
    fake.FAN_CLOSE_WRITE = 1
    fake.FAN_DELETE = 2
    fake.FAN_MOVED_FROM = 4
    fake.FAN_MOVED_TO = 8
    fake.FAN_CREATE = 16
    fake.FAN_MARK_REMOVE = 32
    fake.FAN_MARK_ADD = 64
    fake.FAN_MARK_FILESYSTEM = 128
    fake.mark = MagicMock()
    return fake


def _make_reload_detector(watch_paths: list[str]):
    from agent.detector import FanotifyDetector

    baseline = MagicMock()
    baseline.init_scan = MagicMock()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    detector = FanotifyDetector(
        agent_id="agent-reload-test",
        watch_paths=watch_paths,
        baseline=baseline,
        publisher=publisher,
        stop_event=MagicMock(),
    )
    detector._fan = MagicMock()
    return detector


def test_reload_watch_paths_marks_new(tmp_path: Path) -> None:
    """Nuevo path marcado en fanotify: invoca el método real
    ``FanotifyDetector.reload_watch_paths`` (no reimplementa el delta a mano) y
    verifica que ``_fan_mod.mark`` se llame con ``FAN_MARK_ADD`` para el path
    agregado."""
    watch_a = tmp_path / "etc"
    watch_a.mkdir()
    watch_b = tmp_path / "usr_bin"
    watch_b.mkdir()

    detector = _make_reload_detector([str(watch_a)])
    fake_fan_mod = _fake_fan_mod()

    with patch("agent.detector._HAS_FAN", True), patch("agent.detector._fan_mod", fake_fan_mod):
        detector.reload_watch_paths([str(watch_a), str(watch_b)])

    calls = {call.args[4]: call.args[1] for call in fake_fan_mod.mark.call_args_list}
    assert str(watch_b) in calls
    assert calls[str(watch_b)] & fake_fan_mod.FAN_MARK_ADD
    assert not (calls[str(watch_b)] & fake_fan_mod.FAN_MARK_REMOVE)
    assert str(watch_a) not in calls
    assert detector._watch_paths == [str(watch_a), str(watch_b)]


# ── 13.4 test_reload_watch_paths_unmarks_removed ──────────────────────────────


def test_reload_watch_paths_unmarks_removed(tmp_path: Path) -> None:
    """Path eliminado desmarcado: invoca el método real
    ``FanotifyDetector.reload_watch_paths`` y verifica que ``_fan_mod.mark`` se
    llame con ``FAN_MARK_REMOVE`` para el path quitado."""
    watch_a = tmp_path / "etc"
    watch_a.mkdir()
    watch_tmp = tmp_path / "tmp_dir"
    watch_tmp.mkdir()

    detector = _make_reload_detector([str(watch_a), str(watch_tmp)])
    fake_fan_mod = _fake_fan_mod()

    with patch("agent.detector._HAS_FAN", True), patch("agent.detector._fan_mod", fake_fan_mod):
        detector.reload_watch_paths([str(watch_a)])

    calls = {call.args[4]: call.args[1] for call in fake_fan_mod.mark.call_args_list}
    assert str(watch_tmp) in calls
    assert calls[str(watch_tmp)] & fake_fan_mod.FAN_MARK_REMOVE
    assert not (calls[str(watch_tmp)] & fake_fan_mod.FAN_MARK_ADD)
    assert str(watch_a) not in calls
    assert detector._watch_paths == [str(watch_a)]


# ── 13.5 test_update_config_handler_reloads_detector ─────────────────────────


@pytest.mark.asyncio
async def test_update_config_handler_reloads_detector(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, tmp_path
):
    """Handler llama reload_watch_paths y run_scan para paths nuevos."""
    from agent import commands

    mock_detector = MagicMock()
    mock_detector.reload_watch_paths = MagicMock()
    mock_detector._watch_paths = ["/etc"]

    run_scan_calls = []
    original_run_scan = baseline_engine.run_scan

    def mock_run_scan(paths):
        run_scan_calls.append(list(paths))
        return original_run_scan(paths)

    with patch.object(baseline_engine, "run_scan", side_effect=mock_run_scan):
        cmd = _make_command(agent_config, shared_secret, "update_config", {
            "watch_paths": ["/etc", "/usr/bin"],
            "ruleset_version": 5,
        })

        await commands.handle_update_config(
            command=cmd,
            detector=mock_detector,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
        )

    # reload_watch_paths llamado con los nuevos paths
    mock_detector.reload_watch_paths.assert_called_once_with(["/etc", "/usr/bin"])

    # run_scan llamado solo para paths nuevos (/usr/bin es nuevo, /etc ya estaba)
    assert len(run_scan_calls) == 1
    assert "/usr/bin" in run_scan_calls[0]
    assert "/etc" not in run_scan_calls[0]


# ── 13.6 test_update_config_handler_publishes_ack ────────────────────────────


@pytest.mark.asyncio
async def test_update_config_handler_publishes_ack(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Handler publica event_ack con status=ok."""
    from agent import commands

    mock_detector = MagicMock()
    mock_detector.reload_watch_paths = MagicMock()

    cmd = _make_command(agent_config, shared_secret, "update_config", {
        "watch_paths": ["/var/log"],
        "ruleset_version": 3,
    })

    await commands.handle_update_config(
        command=cmd,
        detector=mock_detector,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "ok"
    assert ack_payload["command_type"] == "update_config"


# ── 13.7 test_update_config_updates_state_ruleset_version ────────────────────


@pytest.mark.asyncio
async def test_update_config_updates_state_ruleset_version(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Handler actualiza state.ruleset_version con el valor del comando."""
    from agent import commands

    mock_detector = MagicMock()
    mock_detector.reload_watch_paths = MagicMock()

    cmd = _make_command(agent_config, shared_secret, "update_config", {
        "watch_paths": ["/etc"],
        "ruleset_version": 42,
    })

    await commands.handle_update_config(
        command=cmd,
        detector=mock_detector,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    assert agent_state.ruleset_version == 42


# ── 13.8 test_rescan_baseline_handler_calls_run_scan ─────────────────────────


@pytest.mark.asyncio
async def test_rescan_baseline_handler_calls_run_scan(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Handler llama run_scan sobre todos los watch_paths de config."""
    from agent import commands

    run_scan_calls = []

    def mock_run_scan(paths):
        run_scan_calls.append(list(paths))
        from agent.baseline import ScanReport
        return ScanReport(scanned=0, skipped=0, oversize=0, errors=0)

    cmd = _make_command(agent_config, shared_secret, "rescan_baseline")

    with patch.object(baseline_engine, "run_scan", side_effect=mock_run_scan):
        await commands.handle_rescan_baseline(
            command=cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
        )

    assert len(run_scan_calls) == 1
    assert run_scan_calls[0] == list(agent_config.watch_paths)


# ── 13.9 test_rescan_baseline_handler_publishes_ack ──────────────────────────


@pytest.mark.asyncio
async def test_rescan_baseline_handler_publishes_ack(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Handler publica event_ack con status=ok tras rescan."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "rescan_baseline")

    await commands.handle_rescan_baseline(
        command=cmd,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "ok"
    assert ack_payload["command_type"] == "rescan_baseline"


# ── US-22: rescan_baseline con paths específicos + guard de versión ─────────


@pytest.mark.asyncio
async def test_rescan_baseline_handler_scans_only_specified_paths(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Con `paths` en el comando, sólo esos paths se re-escanean (US-22)."""
    from agent import commands

    agent_config.watch_paths = ["/etc", "/var/lib/fim"]

    run_scan_calls = []

    def mock_run_scan(paths):
        run_scan_calls.append(list(paths))
        from agent.baseline import ScanReport
        return ScanReport(scanned=0, skipped=0, oversize=0, errors=0)

    cmd = _make_command(agent_config, shared_secret, "rescan_baseline", {
        "paths": ["/etc"],
        "ruleset_version": 1,
    })

    with patch.object(baseline_engine, "run_scan", side_effect=mock_run_scan):
        await commands.handle_rescan_baseline(
            command=cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
        )

    assert run_scan_calls == [["/etc"]]


@pytest.mark.asyncio
async def test_rescan_baseline_handler_rejects_paths_outside_watch_roots(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Un path fuera de los watch_paths configurados se descarta, no se escanea."""
    from agent import commands

    agent_config.watch_paths = ["/etc"]

    run_scan_calls = []

    def mock_run_scan(paths):
        run_scan_calls.append(list(paths))
        from agent.baseline import ScanReport
        return ScanReport(scanned=0, skipped=0, oversize=0, errors=0)

    cmd = _make_command(agent_config, shared_secret, "rescan_baseline", {
        "paths": ["/root/escape"],
        "ruleset_version": 1,
    })

    with patch.object(baseline_engine, "run_scan", side_effect=mock_run_scan):
        await commands.handle_rescan_baseline(
            command=cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
        )

    assert run_scan_calls == [[]]
    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "ok"


@pytest.mark.asyncio
async def test_rescan_baseline_handler_ignores_stale_version(
    agent_config, shared_secret, baseline_engine, mock_valkey, tmp_dirs
):
    """rescan_baseline con ruleset_version menor al local se descarta sin ack
    (mismo guard monotónico que update_config, BUG-12)."""
    from agent import commands

    state = AgentState(ruleset_version=10, state_path=tmp_dirs["secrets"] / "state.json")

    run_scan = MagicMock()
    cmd = _make_command(agent_config, shared_secret, "rescan_baseline", {
        "ruleset_version": 5,
    })

    with patch.object(baseline_engine, "run_scan", run_scan):
        await commands.handle_rescan_baseline(
            command=cmd,
            baseline_engine=baseline_engine,
            state=state,
            valkey_client=mock_valkey,
            config=agent_config,
        )

    run_scan.assert_not_called()
    mock_valkey.xadd.assert_not_called()
    assert state.ruleset_version == 10


@pytest.mark.asyncio
async def test_rescan_baseline_handler_updates_state_ruleset_version(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Tras un rescan exitoso, state.ruleset_version avanza al del comando (C11)."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "rescan_baseline", {
        "ruleset_version": 7,
    })

    await commands.handle_rescan_baseline(
        command=cmd,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    assert agent_state.ruleset_version == 7


# ── 13.10 test_dispatch_routes_update_config ─────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_routes_update_config(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Tipo update_config llama al handler correcto."""
    from agent import commands

    mock_detector = MagicMock()

    cmd = _make_command(agent_config, shared_secret, "update_config", {
        "watch_paths": ["/etc"],
        "ruleset_version": 1,
    })

    called = []
    original_handler = commands.handle_update_config

    async def mock_handler(**kwargs):
        called.append("update_config")
        await original_handler(**kwargs)

    with patch.object(commands, "handle_update_config", side_effect=mock_handler):
        await commands.dispatch(
            cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
            detector=mock_detector,
        )

    assert "update_config" in called


# ── 13.11 test_dispatch_routes_rescan_baseline ───────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_routes_rescan_baseline(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Tipo rescan_baseline llama al handler correcto."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "rescan_baseline")

    called = []
    original_handler = commands.handle_rescan_baseline

    async def mock_handler(**kwargs):
        called.append("rescan_baseline")
        await original_handler(**kwargs)

    with patch.object(commands, "handle_rescan_baseline", side_effect=mock_handler):
        await commands.dispatch(
            cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
        )

    assert "rescan_baseline" in called
