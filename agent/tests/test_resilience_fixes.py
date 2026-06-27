"""
Tests for C29 — agent-resilience-fixes.

Covers:
  FIX-01  test_fim_restore_tmp_event_suppressed
  FIX-02  test_rehydrate_inside_try_block (structural)
  FIX-03  test_xadd_failure_keeps_event_in_pending
  FIX-04a test_quarantine_outside_watch_paths_rejected
  FIX-04b test_restore_outside_watch_paths_rejected
  FIX-04c test_quarantine_no_watch_paths_rejected
  FIX-04d test_restore_no_watch_paths_rejected
  FIX-05  test_plaintext_valkey_warning_emitted
  FIX-05b test_plaintext_valkey_no_warning_when_allowed
  FIX-06  test_corrupt_state_bak_has_timestamp
  FIX-07  test_rehydrate_oserror_continues_to_next_entry
  FIX-08a test_verify_cert_rejects_expired
  FIX-08b test_verify_cert_rejects_not_yet_valid
  FIX-09  test_save_state_calls_fsync
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from agent.config import AgentConfig, StorageConfig


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _make_config(
    tmp_path: Path,
    watch_paths: list[str] | None = None,
    valkey_url: str = "valkey://localhost:6379",
    allow_plaintext: bool = False,
) -> AgentConfig:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "shared_secret").write_bytes(os.urandom(32))
    return AgentConfig(
        agent_id="test-agent-c29",
        backend_url="http://localhost:8000",
        valkey_url=valkey_url,
        ca_cert_path="/tmp/ca.pem",
        watch_paths=watch_paths or ["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(secrets_dir),
            certs_dir=str(tmp_path / "certs"),
        ),
        allow_plaintext_valkey=allow_plaintext,
    )


def _generate_ca() -> tuple[Ed25519PrivateKey, x509.Certificate]:
    ca_key = Ed25519PrivateKey.generate()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(seconds=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    return ca_key, ca_cert


def _issue_cert(
    ca_key: Ed25519PrivateKey,
    ca_cert: x509.Certificate,
    subject_key: Ed25519PrivateKey,
    cn: str,
    not_before: datetime.datetime,
    not_after: datetime.datetime,
) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(ca_key, None)  # type: ignore[arg-type]
    )


def _cert_pem(cert: x509.Certificate) -> str:
    from cryptography.hazmat.primitives import serialization
    return cert.public_bytes(serialization.Encoding.PEM).decode()


# ── FIX-01: .fim_restore_tmp suppressed ───────────────────────────────────────


@pytest.mark.asyncio
async def test_fim_restore_tmp_event_suppressed() -> None:
    """_process_event returns immediately for .fim_restore_tmp paths (D19)."""
    from agent.detector import FanotifyDetector, FanotifyEvent

    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._baseline = MagicMock()
    detector._publisher = MagicMock()
    detector._decision_engine = None
    detector._pending = {}
    detector._event_to_path = {}

    tmp_event = FanotifyEvent(
        path="/etc/passwd.fim_restore_tmp",
        pid=1,
        uid=0,
        exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
        mask=0,
    )

    await detector._process_event(tmp_event)

    detector._baseline.read_entry.assert_not_called()
    detector._publisher.publish.assert_not_called()


@pytest.mark.asyncio
async def test_normal_event_not_suppressed() -> None:
    """Paths without .fim_restore_tmp suffix are processed normally."""
    from agent.detector import FanotifyDetector, FanotifyEvent

    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._baseline = MagicMock()
    detector._baseline.read_entry.return_value = None
    detector._publisher = MagicMock()
    detector._publisher.publish = AsyncMock()
    detector._decision_engine = None
    detector._pending = {}
    detector._event_to_path = {}

    normal_event = FanotifyEvent(
        path="/etc/passwd",
        pid=1,
        uid=0,
        exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
        mask=0,
    )

    await detector._process_event(normal_event)

    detector._baseline.read_entry.assert_called_once_with("/etc/passwd")


# ── FIX-02: rehydrate inside try block (structural) ───────────────────────────


def test_rehydrate_not_before_try_block() -> None:
    """In __main__.py, rehydrate() must be called after the try: keyword."""
    import ast

    src = (Path(__file__).parent.parent / "__main__.py").read_text()
    tree = ast.parse(src)

    # Find the main() async function
    main_fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "main"
    )

    # Find the outermost try block inside main (the one with finally)
    try_node = None
    for node in ast.walk(main_fn):
        if isinstance(node, ast.Try) and node.finalbody:
            try_node = node
            break

    assert try_node is not None, "main() must have a try/finally block"

    # rehydrate() must appear inside that try body, not before it
    rehydrate_lineno_in_try = None
    for stmt in ast.walk(ast.Module(body=try_node.body, type_ignores=[])):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Await):
            call_node = stmt.value.value
            if (
                isinstance(call_node, ast.Call)
                and isinstance(call_node.func, ast.Attribute)
                and call_node.func.attr == "rehydrate"
            ):
                rehydrate_lineno_in_try = stmt.lineno
                break

    assert rehydrate_lineno_in_try is not None, (
        "rehydrate() call must exist inside the try block in main()"
    )


# ── FIX-03: XADD failure keeps event in _pending ──────────────────────────────


@pytest.mark.asyncio
async def test_xadd_failure_keeps_event_in_pending(tmp_path: Path) -> None:
    """When _xadd raises, the event_id must still be in _pending for retry."""
    from agent.publisher import Publisher
    from agent.queue import EventQueue

    cfg = _make_config(tmp_path)
    queue = EventQueue(str(tmp_path / "queue"))

    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock(side_effect=ConnectionError("valkey down"))

    publisher = Publisher(cfg, queue, mock_client)

    event_data: dict[str, Any] = {
        "path": "/etc/passwd",
        "event_type": "file_modified",
        "previous_hash": None,
        "current_hash": "abc",
        "diff_text": None,
        "process_pid": 1,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    }

    await publisher.publish(event_data)

    assert len(publisher._pending) == 1, "event must be in _pending even when xadd fails"


@pytest.mark.asyncio
async def test_xadd_success_also_sets_pending(tmp_path: Path) -> None:
    """When _xadd succeeds, event is still in _pending (waiting for ack)."""
    from agent.publisher import Publisher
    from agent.queue import EventQueue

    cfg = _make_config(tmp_path)
    queue = EventQueue(str(tmp_path / "queue"))

    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock(return_value="1-0")
    publisher = Publisher(cfg, queue, mock_client)

    await publisher.publish({
        "path": "/etc/hosts",
        "event_type": "file_modified",
        "previous_hash": None,
        "current_hash": "def",
        "diff_text": None,
        "process_pid": 1,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    })

    assert len(publisher._pending) == 1


# ── FIX-04: path containment in file handlers ─────────────────────────────────


@pytest.mark.asyncio
async def test_quarantine_outside_watch_paths_rejected(tmp_path: Path) -> None:
    """handle_quarantine_file rejects paths outside watch_paths and publishes error ack."""
    from agent import commands

    cfg = _make_config(tmp_path, watch_paths=["/etc"])
    journal = MagicMock()
    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock()

    await commands.handle_quarantine_file(
        command={
            "command_id": "cmd-001",
            "event_id": "ev-001",
            "path": "/tmp/evil_file",
        },
        journal=journal,
        valkey_client=mock_client,
        config=cfg,
        quarantine_dir=str(tmp_path / "quarantine"),
    )

    mock_client.xadd.assert_called_once()
    ack = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert ack["status"] == "error"
    assert "path_outside_watch_paths" in ack["error"]
    journal.write_pending.assert_not_called()


@pytest.mark.asyncio
async def test_restore_outside_watch_paths_rejected(tmp_path: Path) -> None:
    """handle_restore_file rejects paths outside watch_paths and publishes error ack."""
    from agent import commands

    cfg = _make_config(tmp_path, watch_paths=["/etc"])
    journal = MagicMock()
    baseline = MagicMock()
    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock()

    await commands.handle_restore_file(
        command={
            "command_id": "cmd-002",
            "event_id": "ev-002",
            "path": "/tmp/not_monitored",
        },
        baseline_engine=baseline,
        journal=journal,
        valkey_client=mock_client,
        config=cfg,
    )

    mock_client.xadd.assert_called_once()
    ack = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert ack["status"] == "error"
    assert "path_outside_watch_paths" in ack["error"]
    journal.write_pending.assert_not_called()


@pytest.mark.asyncio
async def test_quarantine_no_watch_paths_rejected(tmp_path: Path) -> None:
    """handle_quarantine_file with empty watch_paths rejects and publishes error ack."""
    from agent import commands
    from agent.config import AgentConfig, StorageConfig

    # Override watch_paths with empty — must bypass the non-empty validator via __new__
    # Instead, we patch config.watch_paths directly at call time
    cfg = _make_config(tmp_path, watch_paths=["/etc"])
    cfg.__dict__["watch_paths"] = []

    journal = MagicMock()
    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock()

    await commands.handle_quarantine_file(
        command={
            "command_id": "cmd-003",
            "event_id": "ev-003",
            "path": "/etc/passwd",
        },
        journal=journal,
        valkey_client=mock_client,
        config=cfg,
        quarantine_dir=str(tmp_path / "quarantine"),
    )

    ack = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert ack["status"] == "error"
    assert "no_watch_paths" in ack["error"]


@pytest.mark.asyncio
async def test_restore_no_watch_paths_rejected(tmp_path: Path) -> None:
    """handle_restore_file with empty watch_paths rejects and publishes error ack."""
    from agent import commands

    cfg = _make_config(tmp_path, watch_paths=["/etc"])
    cfg.__dict__["watch_paths"] = []

    journal = MagicMock()
    baseline = MagicMock()
    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock()

    await commands.handle_restore_file(
        command={
            "command_id": "cmd-004",
            "event_id": "ev-004",
            "path": "/etc/passwd",
        },
        baseline_engine=baseline,
        journal=journal,
        valkey_client=mock_client,
        config=cfg,
    )

    ack = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert ack["status"] == "error"
    assert "no_watch_paths" in ack["error"]


# ── FIX-05: plaintext Valkey warning ──────────────────────────────────────────


def test_plaintext_valkey_warning_emitted(tmp_path: Path) -> None:
    """create_valkey_client emits WARNING when scheme is plain and allow_plaintext_valkey=False."""
    from agent.transport import create_valkey_client

    cfg = _make_config(tmp_path, valkey_url="valkey://localhost:6379", allow_plaintext=False)

    with patch("agent.transport.avalkey.Valkey.from_url") as mock_from_url, \
         patch("agent.transport.log") as mock_log:
        mock_from_url.return_value = MagicMock()
        create_valkey_client(cfg)

    mock_log.warning.assert_called_once()
    args = mock_log.warning.call_args
    assert "transport.plaintext_valkey_warning" in args[0]


def test_plaintext_valkey_no_warning_when_allowed(tmp_path: Path) -> None:
    """No warning when allow_plaintext_valkey=True."""
    from agent.transport import create_valkey_client

    cfg = _make_config(tmp_path, valkey_url="valkey://localhost:6379", allow_plaintext=True)

    with patch("agent.transport.avalkey.Valkey.from_url") as mock_from_url, \
         patch("agent.transport.log") as mock_log:
        mock_from_url.return_value = MagicMock()
        create_valkey_client(cfg)

    mock_log.warning.assert_not_called()


def test_tls_scheme_no_plaintext_warning(tmp_path: Path) -> None:
    """valkeys:// never triggers the plaintext warning."""
    from agent.transport import create_valkey_client

    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    for name in ("agent-cert.pem", "agent-key.pem", "ca.pem"):
        (certs_dir / name).write_text("placeholder")

    cfg = AgentConfig(
        agent_id="test",
        backend_url="http://localhost:8000",
        valkey_url="valkeys://localhost:6380",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
            certs_dir=str(certs_dir),
        ),
        allow_plaintext_valkey=False,
    )

    with patch("agent.transport.avalkey.Valkey.from_url") as mock_from_url, \
         patch("agent.transport.log") as mock_log:
        mock_from_url.return_value = MagicMock()
        create_valkey_client(cfg)

    mock_log.warning.assert_not_called()


# ── FIX-06: timestamped bak on corrupt state ──────────────────────────────────


def test_corrupt_state_bak_has_timestamp(tmp_path: Path) -> None:
    """load_state() creates a timestamped .bak file on JSON corruption."""
    from agent.state import load_state

    state_path = tmp_path / "state.json"
    state_path.write_text("{invalid json{{")

    before = datetime.datetime.now(datetime.timezone.utc).timestamp()
    load_state(state_path)
    after = datetime.datetime.now(datetime.timezone.utc).timestamp()

    bak_files = list(tmp_path.glob("state.*.json.bak"))
    assert len(bak_files) == 1, f"expected one .bak file, got {bak_files}"

    # Extract timestamp from filename — int(time.time()) truncates to seconds
    match = re.search(r"state\.(\d+)\.json\.bak", bak_files[0].name)
    assert match, f"unexpected bak filename format: {bak_files[0].name}"
    ts = int(match.group(1))
    assert int(before) <= ts <= int(after) + 1, (
        f"timestamp {ts} outside expected range [{int(before)}, {int(after) + 1}]"
    )


def test_two_corruptions_produce_two_baks(tmp_path: Path) -> None:
    """Each corruption event creates a distinct .bak file."""
    from agent.state import load_state

    state_path = tmp_path / "state.json"

    state_path.write_text("{bad}")
    load_state(state_path)
    import time; time.sleep(1.1)  # ensure different timestamp

    state_path.write_text("{also bad}")
    load_state(state_path)

    bak_files = list(tmp_path.glob("state.*.json.bak"))
    assert len(bak_files) == 2, f"expected 2 .bak files, got {[f.name for f in bak_files]}"
    names = {f.name for f in bak_files}
    assert len(names) == 2, "bak filenames must be distinct"


# ── FIX-07: OSError in rehydrate loop continues ───────────────────────────────


@pytest.mark.asyncio
async def test_rehydrate_oserror_continues_to_next_entry(tmp_path: Path) -> None:
    """If mark_completed raises OSError, rehydrate continues to remaining entries."""
    from agent.decision import DecisionEngine
    from agent.journal import JournalManager
    from agent.rules import RulesCache

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    rules = MagicMock(spec=RulesCache)
    rules.evaluate.return_value = "alert_only"
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")
    baseline = MagicMock()

    engine = DecisionEngine(rules=rules, journal=journal, baseline=baseline, quarantine_dir=quarantine_dir)

    # Write two pending entries: first triggers OSError in mark_completed, second is alert_only
    journal.write_pending("event-oserr", "/etc/hosts", "auto_restore")
    journal.write_pending("event-alert", "/etc/resolv.conf", "alert_only")

    published: list[str] = []

    async def mock_publish(payload: dict) -> None:
        published.append(payload["event_id"])

    publisher = MagicMock()
    publisher.publish = mock_publish

    # Patch mark_completed to raise OSError only for the first entry
    original_mark = journal.mark_completed

    def raising_mark(event_id: str) -> None:
        if event_id == "event-oserr":
            raise OSError("disk full")
        return original_mark(event_id)

    with patch.object(journal, "mark_completed", side_effect=raising_mark):
        await engine.rehydrate(publisher)

    # The second entry must have been published despite the first failing
    assert "event-alert" in published, (
        "second entry must be processed even if first raises OSError"
    )


# ── FIX-08: cert validity period check ────────────────────────────────────────


def test_verify_cert_rejects_expired() -> None:
    """verify_cert raises RuntimeError for a cert whose not_valid_after is in the past."""
    from agent.bootstrap import verify_cert

    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    now = datetime.datetime.now(datetime.timezone.utc)

    expired_cert = _issue_cert(
        ca_key, ca_cert, agent_key, "test-agent",
        not_before=now - datetime.timedelta(days=10),
        not_after=now - datetime.timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="cert validity period invalid"):
        verify_cert(
            _cert_pem(expired_cert),
            _cert_pem(ca_cert),
            "test-agent",
        )


def test_verify_cert_rejects_not_yet_valid() -> None:
    """verify_cert raises RuntimeError for a cert whose not_valid_before is in the future."""
    from agent.bootstrap import verify_cert

    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    now = datetime.datetime.now(datetime.timezone.utc)

    future_cert = _issue_cert(
        ca_key, ca_cert, agent_key, "test-agent",
        not_before=now + datetime.timedelta(hours=1),
        not_after=now + datetime.timedelta(days=90),
    )

    with pytest.raises(RuntimeError, match="cert validity period invalid"):
        verify_cert(
            _cert_pem(future_cert),
            _cert_pem(ca_cert),
            "test-agent",
        )


def test_verify_cert_accepts_valid_period() -> None:
    """verify_cert passes for a cert with current not_before/not_after."""
    from agent.bootstrap import verify_cert

    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    now = datetime.datetime.now(datetime.timezone.utc)

    valid_cert = _issue_cert(
        ca_key, ca_cert, agent_key, "test-agent",
        not_before=now - datetime.timedelta(seconds=1),
        not_after=now + datetime.timedelta(days=90),
    )

    result = verify_cert(
        _cert_pem(valid_cert),
        _cert_pem(ca_cert),
        "test-agent",
    )
    assert result is not None


# ── FIX-09: fsync in save_state ───────────────────────────────────────────────


def test_save_state_calls_fsync(tmp_path: Path) -> None:
    """save_state() calls os.fsync after writing the tmp file."""
    from agent.state import AgentState, save_state

    state = AgentState(
        ruleset_version=3,
        last_stream_command_id="1-2",
        rules=[],
        state_path=tmp_path / "state.json",
    )

    fsync_called = []
    original_fsync = os.fsync

    def tracking_fsync(fd: int) -> None:
        fsync_called.append(fd)
        return original_fsync(fd)

    with patch("agent.state.os.fsync", side_effect=tracking_fsync):
        save_state(state)

    assert len(fsync_called) == 1, "os.fsync must be called exactly once during save_state"


def test_save_state_persists_data(tmp_path: Path) -> None:
    """save_state() writes correct JSON to the target path."""
    from agent.state import AgentState, load_state, save_state

    state_path = tmp_path / "state.json"
    state = AgentState(
        ruleset_version=7,
        last_stream_command_id="5-3",
        rules=[{"pattern": "/etc/**", "action": "auto_restore"}],
        state_path=state_path,
    )
    save_state(state)

    loaded = load_state(state_path)
    assert loaded.ruleset_version == 7
    assert loaded.last_stream_command_id == "5-3"
    assert len(loaded.rules) == 1
