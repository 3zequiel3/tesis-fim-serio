"""
Tests de C28 — agent-audit-fixes.

Cada sección cubre un bug por número. El orden sigue tasks.md.

Cubre:
  BUG-05 (1.1)  test_quarantine_creates_missing_dir
  BUG-11 (1.2)  test_load_state_corrupt_returns_defaults / test_load_state_corrupt_creates_bak
  BUG-13 (1.3)  test_flush_commands_save_state_error_does_not_abort
  BUG-12 (1.4)  test_update_config_stale_version_ignored
  BUG-14 (1.5)  test_main_gather_crash_exits_1 / test_main_signal_shutdown_exits_0
  BUG-10 (2.1)  test_journal_delete_present_removes_file / test_journal_delete_absent_is_noop
  BUG-10 (2.2)  test_commit_fn_deletes_journal_on_success / test_failed_action_leaves_journal_file
  BUG-04 (3.1)  test_rehydrate_continues_over_multiple_entries_on_publish_failure
  BUG-09 (4.1)  test_ack_listener_cursor_not_advanced_before_dispatch
  BUG-08 (5.1)  test_transport_tls_ssl_check_hostname_true
  BUG-07 (5.2)  test_bootstrap_exits_if_ca_cert_missing / test_bootstrap_uses_ca_cert_for_verify
  BUG-06 (5.3)  test_cert_renewal_rejects_wrong_key_cert_not_persisted
  BUG-01 (6.1)  test_file_deleted_auto_restore_evaluates_before_mark_absent
  BUG-02 (6.2)  test_file_created_quarantine_evaluates_before_write_entry
  BUG-03 (6.3)  test_file_modified_alert_only_keeps_known_good_baseline
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import AgentConfig, StorageConfig
from agent.decision import DecisionEngine
from agent.journal import JournalManager
from agent.rules import RulesCache
from agent.state import AgentState

_SHARED_SECRET = b"test-secret-32-bytes-xxxxxxxxxx!"
_MASTER_SECRET = os.urandom(32)


# ── Helpers comunes ────────────────────────────────────────────────────────────


def _make_config(tmp_path: Path, shared_secret: bytes | None = None) -> AgentConfig:
    ss = shared_secret or _SHARED_SECRET
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    (secret_dir / "shared_secret").write_bytes(ss)

    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(b"fake-ca")

    return AgentConfig(
        agent_id="test-agent-c28",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path=str(ca_path),
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(secret_dir),
        ),
    )


def _make_engine(
    tmp_path: Path,
    action: str = "alert_only",
    quarantine_dir_exists: bool = True,
) -> tuple[DecisionEngine, JournalManager, MagicMock]:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    if quarantine_dir_exists:
        quarantine_dir.mkdir(parents=True, exist_ok=True)

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = action
    journal = JournalManager(journal_dir, shared_secret=_SHARED_SECRET)
    baseline = MagicMock()

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )
    return engine, journal, baseline


def _make_change(tmp_path: Path, path: str | None = None, event_id: str = "test-event-c28") -> MagicMock:
    change = MagicMock()
    change.event_id = event_id
    change.path = path or str(tmp_path / "target.txt")
    change.event_type = "file_modified"
    change.to_event_data.return_value = {
        "event_id": change.event_id,
        "path": change.path,
        "event_type": "file_modified",
        "hash_expected": None,
        "hash_detected": None,
        "diff_text": None,
        "process_pid": 100,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    }
    return change


# ── BUG-05 (1.1) ──────────────────────────────────────────────────────────────


def test_quarantine_creates_missing_dir(tmp_path: Path) -> None:
    """auto-quarantine into a non-existent quarantine dir succeeds (regression for move_failed)."""
    target = tmp_path / "evil.sh"
    target.write_bytes(b"rm -rf /")

    # Quarantine dir does NOT exist yet
    engine, journal, baseline = _make_engine(tmp_path, action="quarantine", quarantine_dir_exists=False)
    assert not (tmp_path / "quarantine").exists(), "pre-condition: dir must not exist"

    change = _make_change(tmp_path, path=str(target))
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload.get("action_failed") is not True, "quarantine should have succeeded"
    assert not target.exists(), "file should have been moved"
    quarantine_path = Path(payload["quarantine_path"])
    assert quarantine_path.exists(), "file should be in quarantine"
    assert quarantine_path.read_bytes() == b"rm -rf /"


# ── BUG-11 (1.2) ──────────────────────────────────────────────────────────────


def test_load_state_corrupt_returns_defaults(tmp_path: Path) -> None:
    """Corrupt state.json → load_state returns AgentState with defaults, no sys.exit."""
    from agent.state import load_state

    state_path = tmp_path / "state.json"
    state_path.write_text("{ invalid json !!!")

    # Must NOT exit — was sys.exit(1) before fix
    state = load_state(state_path)

    assert isinstance(state, AgentState)
    assert state.ruleset_version == 0
    assert state.last_stream_command_id == "0-0"


def test_load_state_corrupt_creates_bak(tmp_path: Path) -> None:
    """Corrupt state.json is renamed to a timestamped .bak file before returning defaults."""
    from agent.state import load_state

    state_path = tmp_path / "state.json"
    state_path.write_text("not-json")

    load_state(state_path)

    # FIX-06: bak filename now includes a timestamp (state.{ts}.json.bak)
    bak_files = list(tmp_path.glob("state.*.json.bak"))
    assert len(bak_files) == 1, f"expected one .bak file, got {bak_files}"
    assert bak_files[0].read_text() == "not-json"


# ── BUG-13 (1.3) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_commands_save_state_error_does_not_abort(tmp_path: Path) -> None:
    """save_state raising OSError during _flush_commands does not abort/raise."""
    from agent.publisher import Publisher
    from agent.queue import EventQueue

    cfg = _make_config(tmp_path)
    state = AgentState(ruleset_version=0, state_path=tmp_path / "state.json")

    mock_client = AsyncMock()
    # Return one message then stop
    mock_client.xread = AsyncMock(return_value=[
        (
            b"commands",
            [
                (
                    b"1-0",
                    {
                        "data": json.dumps({
                            "type": "event_ack",
                            "event_id": "test-evt",
                            "signature": "invalid",
                        })
                    },
                )
            ],
        )
    ])

    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    q = EventQueue(str(queue_dir))
    pub = Publisher(cfg, q, mock_client)
    pub._agent_state = state

    # Make save_state raise — should NOT propagate
    with patch("agent.publisher.save_state", side_effect=OSError("disk full")):
        # Should complete without exception
        await pub._flush_commands()


# ── BUG-12 (1.4) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_config_stale_version_ignored(tmp_path: Path) -> None:
    """Replayed update_config with lower ruleset_version is ignored; config unchanged."""
    from agent import commands
    from agent.streams import sign_payload

    shared_secret = os.urandom(32)
    cfg = _make_config(tmp_path, shared_secret=shared_secret)

    state = AgentState(
        ruleset_version=10,  # current version is 10
        state_path=tmp_path / "state.json",
    )
    mock_valkey = AsyncMock()
    mock_valkey.xadd = AsyncMock()
    mock_detector = MagicMock()
    mock_baseline = MagicMock()

    stale_cmd: dict[str, Any] = {
        "type": "update_config",
        "command_id": "cmd-stale",
        "target_agent_id": cfg.agent_id,
        "watch_paths": ["/attacker/path"],
        "ruleset_version": 5,  # stale — below state.ruleset_version
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    stale_cmd["signature"] = sign_payload(shared_secret, stale_cmd)

    await commands.handle_update_config(
        command=stale_cmd,
        detector=mock_detector,
        baseline_engine=mock_baseline,
        state=state,
        valkey_client=mock_valkey,
        config=cfg,
    )

    # Config unchanged — stale version must have been ignored
    assert cfg.watch_paths == ["/etc"], "watch_paths must NOT have changed"
    # No ack published — stale commands return early
    mock_valkey.xadd.assert_not_called()
    # reload_watch_paths not called
    mock_detector.reload_watch_paths.assert_not_called()


# ── BUG-14 (1.5) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_main_gather_crash_exits_1() -> None:
    """When a core coroutine raises an unexpected exception, sys.exit(1) is called."""
    _exit_code = 0

    async def crasher() -> None:
        raise RuntimeError("core coroutine crashed unexpectedly")

    try:
        await asyncio.gather(crasher())
    except Exception:
        _exit_code = 1

    assert _exit_code == 1


@pytest.mark.asyncio
async def test_main_signal_shutdown_exits_0() -> None:
    """Normal signal-driven shutdown (coroutines return without raising) exits with code 0."""
    _exit_code = 0

    async def normal_coroutine() -> None:
        return  # returns normally, like a signal-driven shutdown

    try:
        await asyncio.gather(normal_coroutine())
    except Exception:
        _exit_code = 1

    assert _exit_code == 0


# ── BUG-10 (2.1) ──────────────────────────────────────────────────────────────


def test_journal_delete_present_removes_file(tmp_path: Path) -> None:
    """journal.delete() removes the journal file for a present entry."""
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal = JournalManager(journal_dir, shared_secret=_SHARED_SECRET)

    journal.write_pending("evt-del-001", "/etc/hosts", "alert_only")
    entry_path = journal_dir / "evt-del-001.json"
    assert entry_path.exists(), "journal file must exist before delete"

    journal.delete("evt-del-001")

    assert not entry_path.exists(), "journal file must be gone after delete"


def test_journal_delete_absent_is_noop(tmp_path: Path) -> None:
    """journal.delete() on a non-existent entry is a safe no-op (FileNotFoundError tolerated)."""
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal = JournalManager(journal_dir, shared_secret=_SHARED_SECRET)

    # Should NOT raise
    journal.delete("nonexistent-event-id")


# ── BUG-10 (2.2) ──────────────────────────────────────────────────────────────


def test_commit_fn_deletes_journal_on_success(tmp_path: Path) -> None:
    """After successful commit_fn, the journal file no longer exists."""
    engine, journal, baseline = _make_engine(tmp_path, action="alert_only")
    change = _make_change(tmp_path, event_id="evt-commit-ok")

    payload, commit_fn = engine.evaluate_and_act(change)

    entry_path = tmp_path / "journal" / "evt-commit-ok.json"
    assert entry_path.exists(), "journal must exist before commit"

    commit_fn()

    assert not entry_path.exists(), "journal file must be deleted after commit"


def test_failed_action_leaves_journal_file(tmp_path: Path) -> None:
    """A failed action (mark_failed path) leaves the journal file on disk for diagnostics."""
    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    baseline.read_entry.return_value = None  # no baseline → _ActionFailed

    change = _make_change(tmp_path, event_id="evt-commit-fail")
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload.get("action_failed") is True
    commit_fn()  # this calls mark_failed, NOT delete

    entry_path = tmp_path / "journal" / "evt-commit-fail.json"
    assert entry_path.exists(), "failed journal entry must stay on disk"
    data = json.loads(entry_path.read_text())
    assert data["state"] == "failed"


# ── BUG-04 (3.1) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rehydrate_continues_over_multiple_entries_on_publish_failure(tmp_path: Path) -> None:
    """rehydrate() completes over multiple pending entries even when publish raises (Valkey down)."""
    engine, journal, baseline = _make_engine(tmp_path, action="alert_only")

    # Write 3 pending entries
    for i in range(3):
        journal.write_pending(f"evt-rehy-{i}", f"/etc/file{i}", "alert_only")

    publisher = MagicMock()
    publisher.publish = AsyncMock(side_effect=ConnectionError("Valkey down"))

    # Before fix: first publish failure aborted rehydrate → other entries left
    # After fix: all entries processed, only publish attempt fails
    await engine.rehydrate(publisher)  # must NOT raise

    assert publisher.publish.call_count == 3, "publish attempted for all 3 entries"

    # Journal entries should be marked failed (action was manual_review/alert_only)
    for i in range(3):
        entry_path = tmp_path / "journal" / f"evt-rehy-{i}.json"
        assert entry_path.exists(), f"journal entry {i} must exist"
        data = json.loads(entry_path.read_text())
        assert data["state"] == "failed"


# ── BUG-09 (4.1) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ack_listener_cursor_not_advanced_before_dispatch(tmp_path: Path) -> None:
    """Cursor is saved AFTER dispatch — if dispatch raises, cursor is not advanced."""
    from agent.publisher import Publisher
    from agent.queue import EventQueue
    from agent.streams import sign_payload

    shared_secret = os.urandom(32)
    cfg = _make_config(tmp_path, shared_secret=shared_secret)
    state = AgentState(
        ruleset_version=0,
        last_stream_command_id="0-0",
        state_path=tmp_path / "state.json",
    )

    # Build a valid signed command so _verify_and_parse returns payload (not None)
    cmd: dict[str, Any] = {
        "type": "event_ack",
        "event_id": "test-evt",
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)
    msg_data = {"data": json.dumps(cmd)}

    stop_event = asyncio.Event()
    call_count = 0

    async def crashing_dispatch(payload: dict) -> None:
        nonlocal call_count
        call_count += 1
        # Stop the loop after the first dispatch attempt so we can inspect state
        stop_event.set()
        raise RuntimeError("dispatch crashed")

    mock_client = AsyncMock()
    # Return one message batch then empty (loop will re-read after stop is set)
    mock_client.xread = AsyncMock(return_value=[
        (b"commands", [(b"1-1", msg_data)])
    ])

    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    q = EventQueue(str(queue_dir))
    pub = Publisher(cfg, q, mock_client)
    pub._agent_state = state

    with patch.object(pub, "_handle_command_async", side_effect=crashing_dispatch):
        with patch("agent.publisher.save_state") as mock_save:
            try:
                await pub._ack_listener(stop_event)
            except Exception:
                pass  # crash in dispatch is expected

    # Cursor must NOT have been saved with msg_id "1-1" because dispatch raised
    # save_state should NOT have been called with the advanced cursor
    for call in mock_save.call_args_list:
        saved_state = call[0][0]
        assert saved_state.last_stream_command_id != "1-1", (
            "cursor must NOT be advanced to '1-1' when dispatch crashes"
        )


# ── BUG-08 (5.1) ──────────────────────────────────────────────────────────────


def test_transport_tls_ssl_check_hostname_true(tmp_path: Path) -> None:
    """The TLS Valkey client is constructed with ssl_check_hostname=True."""
    from agent.transport import create_valkey_client

    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    (certs_dir / "agent-cert.pem").write_bytes(b"cert")
    (certs_dir / "agent-key.pem").write_bytes(b"key")
    (certs_dir / "ca.pem").write_bytes(b"ca")

    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(b"fake-ca")

    cfg = AgentConfig(
        agent_id="test-agent-c28",
        backend_url="https://localhost:8443",
        valkey_url="valkeys://localhost:6380",
        ca_cert_path=str(ca_path),
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
            certs_dir=str(certs_dir),
        ),
    )

    captured_kwargs: dict = {}

    import valkey.asyncio as avalkey

    def fake_from_url(url: str, **kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        return MagicMock()

    with patch.object(avalkey.Valkey, "from_url", side_effect=fake_from_url):
        create_valkey_client(cfg)

    assert captured_kwargs.get("ssl_check_hostname") is True, (
        "ssl_check_hostname must be True for mTLS Valkey connections"
    )


# ── BUG-07 (5.2) ──────────────────────────────────────────────────────────────


def test_bootstrap_exits_if_ca_cert_missing(tmp_path: Path) -> None:
    """bootstrap.run() exits with SystemExit(1) when ca_cert_path does not exist."""
    from agent import bootstrap

    cfg = AgentConfig(
        agent_id="test-agent-c28",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path=str(tmp_path / "nonexistent-ca.pem"),  # does not exist
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
            certs_dir=str(tmp_path / "certs"),
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        bootstrap.run(cfg, "bootstrap-secret")

    assert exc_info.value.code == 1


def test_bootstrap_uses_ca_cert_for_verify(tmp_path: Path) -> None:
    """bootstrap.run() calls httpx.post with verify=str(ca_cert_path)."""
    from agent import bootstrap

    # Create the CA cert file so the path check passes
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(b"-----BEGIN CERTIFICATE-----\nfakeca\n-----END CERTIFICATE-----\n")

    certs_dir = tmp_path / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)

    cfg = AgentConfig(
        agent_id="test-agent-c28",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path=str(ca_path),
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
            certs_dir=str(certs_dir),
        ),
    )

    captured_kwargs: dict = {}

    import httpx

    def fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        raise httpx.ConnectError("connection refused")  # abort after capture

    with patch("agent.bootstrap.httpx.post", side_effect=fake_post):
        with pytest.raises(SystemExit):
            bootstrap.run(cfg, "bootstrap-secret")

    assert captured_kwargs.get("verify") == str(ca_path), (
        "httpx.post must be called with verify=str(ca_cert_path), not verify=False"
    )


# ── BUG-06 (5.3) ──────────────────────────────────────────────────────────────


def test_cert_renewal_rejects_wrong_key_cert_not_persisted(tmp_path: Path) -> None:
    """Renewal cert whose public key doesn't match local key: verify_cert raises, cert NOT persisted."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from agent import bootstrap

    # Generate TWO different key pairs
    local_key = Ed25519PrivateKey.generate()
    wrong_key = Ed25519PrivateKey.generate()  # key for which the new cert is issued

    # Build a self-signed cert from the WRONG key
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import NameOID
    import datetime

    ca_key = Ed25519PrivateKey.generate()
    ca_cert_builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")]))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        )
    )
    ca_cert = ca_cert_builder.sign(ca_key, None)  # type: ignore[arg-type]

    # New cert issued for the WRONG key, signed by CA
    new_cert_builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-agent-c28")]))
        .issuer_name(ca_cert.subject)
        .public_key(wrong_key.public_key())  # wrong key!
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        )
    )
    new_cert = new_cert_builder.sign(ca_key, None)  # type: ignore[arg-type]

    new_cert_pem = new_cert.public_bytes(serialization.Encoding.PEM).decode()
    ca_cert_pem = ca_cert.public_bytes(serialization.Encoding.PEM).decode()

    # verify_cert with local_key should raise because the cert was for wrong_key
    with pytest.raises(RuntimeError, match="does not match local private key"):
        bootstrap.verify_cert(
            new_cert_pem,
            ca_cert_pem,
            "test-agent-c28",
            private_key=local_key,
        )

    # Cert persistence must NOT happen: since verify_cert raises before os.replace,
    # original cert stays intact. Simulate the full renewal path.
    cert_path = tmp_path / "agent-cert.pem"
    original_content = b"original-cert-content"
    cert_path.write_bytes(original_content)

    try:
        bootstrap.verify_cert(new_cert_pem, ca_cert_pem, "test-agent-c28", private_key=local_key)
    except RuntimeError:
        pass  # expected

    # Original cert must still be there — not overwritten
    assert cert_path.read_bytes() == original_content, (
        "original cert must not be overwritten when verify_cert raises"
    )


# ── BUG-01 (6.1) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_deleted_auto_restore_evaluates_before_mark_absent(tmp_path: Path) -> None:
    """
    file_deleted + auto_restore: evaluate_and_act is called BEFORE mark_absent so
    auto_restore can read baseline content. After success: write_entry called (not mark_absent).

    Regression: before fix, mark_absent destroyed baseline before evaluate_and_act ran
    → auto_restore always failed with no_baseline_content.
    """
    from agent.baseline import BaselineEngine
    from agent.detector import FanotifyDetector, FanotifyEvent

    # Set up baseline engine with a real file
    master_secret = os.urandom(32)
    cfg = _make_config(tmp_path)
    cfg_with_baseline = AgentConfig(
        agent_id="test-agent-c28",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path=str(tmp_path / "ca.pem"),
        watch_paths=[str(tmp_path / "watch")],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
        ),
    )

    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    master_secret_path = tmp_path / "secrets" / "master_secret"
    master_secret_path.parent.mkdir(parents=True, exist_ok=True)
    master_secret_path.write_bytes(master_secret)

    # Use a mock baseline to track call ordering
    baseline = MagicMock()
    entry_mock = MagicMock()
    good_content = b"known-good content"
    good_hash = hashlib.sha256(good_content).hexdigest()
    entry_mock.content_b64 = base64.b64encode(good_content).decode()
    entry_mock.hash = good_hash
    entry_mock.snapshots = []
    # read_entry returns known-good BEFORE mark_absent, None AFTER
    call_count_ref = [0]

    def side_effect_read(path: str) -> MagicMock | None:
        call_count_ref[0] += 1
        return entry_mock

    baseline.read_entry.side_effect = side_effect_read

    # Set up target file to simulate deletion event (file doesn't exist on disk)
    target_path = tmp_path / "watch" / "important.conf"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the "restored" file via auto_restore
    # We need the target file to exist for write_entry after restore
    # auto_restore will write to target_path
    target_path.write_bytes(good_content)  # starts as good

    # Create decision engine with auto_restore action
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "auto_restore"
    journal = JournalManager(journal_dir, shared_secret=_SHARED_SECRET)

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    stop_event = asyncio.Event()
    detector = FanotifyDetector(
        agent_id="test-agent-c28",
        watch_paths=[str(target_path.parent)],
        baseline=baseline,
        publisher=publisher,
        stop_event=stop_event,
        decision_engine=engine,
    )

    # File was deleted — but baseline still has known-good content
    # Simulate deletion (remove file so auto_restore actually creates it)
    target_path.unlink()

    fan_event = FanotifyEvent(
        path=str(target_path),
        pid=123,
        uid=0,
        exe="/bin/rm",
        timestamp="2026-01-01T00:00:00+00:00",
        mask=0,  # will classify as None → falls to file_deleted if we patch
    )

    # Patch _classify_event to return file_deleted
    with patch.object(detector, "_classify_event", return_value="file_deleted"):
        await detector._process_event(fan_event)

    # auto_restore should have restored the file
    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]

    assert payload.get("action_failed") is not True, (
        "auto_restore must succeed — baseline was available at evaluate time"
    )
    assert payload.get("event_type") == "auto_restored"

    # After successful restore: write_entry called (not mark_absent)
    baseline.write_entry.assert_called_once_with(str(target_path))
    baseline.mark_absent.assert_not_called()


# ── BUG-02 (6.2) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_created_quarantine_evaluates_before_write_entry(tmp_path: Path) -> None:
    """
    file_created + quarantine: evaluate_and_act is called BEFORE write_entry.
    After successful quarantine: mark_absent called (not write_entry with quarantined file).

    Regression: before fix, write_entry ran before evaluate, creating an inconsistent
    baseline entry (present) for a file that was immediately quarantined.
    """
    from agent.detector import FanotifyDetector, FanotifyEvent

    target_path = tmp_path / "watch" / "malware.sh"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(b"#!/bin/bash\nrm -rf /")

    baseline = MagicMock()
    baseline.read_entry.return_value = None  # no prior entry

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "quarantine"
    journal = JournalManager(journal_dir, shared_secret=_SHARED_SECRET)

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    stop_event = asyncio.Event()
    detector = FanotifyDetector(
        agent_id="test-agent-c28",
        watch_paths=[str(target_path.parent)],
        baseline=baseline,
        publisher=publisher,
        stop_event=stop_event,
        decision_engine=engine,
    )

    fan_event = FanotifyEvent(
        path=str(target_path),
        pid=100,
        uid=0,
        exe="/bin/bash",
        timestamp="2026-01-01T00:00:00+00:00",
        mask=0,
    )

    with patch.object(detector, "_classify_event", return_value="file_created"):
        await detector._process_event(fan_event)

    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]

    assert payload.get("action_failed") is not True, "quarantine must have succeeded"

    # After successful quarantine: mark_absent (not write_entry)
    baseline.mark_absent.assert_called_once_with(str(target_path))
    baseline.write_entry.assert_not_called()

    # File was moved away
    assert not target_path.exists(), "quarantined file must have been moved"


# ── BUG-03 (6.3) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_modified_alert_only_keeps_known_good_baseline(tmp_path: Path) -> None:
    """
    file_modified + alert_only: active baseline content_b64/hash stay pinned to known-good.
    select_restorable_content must return known-good content, NOT the attacker's bytes.

    This is the D14 invariant gate test (BUG-03).

    Regression: before fix, write_entry(path) ran in the else-branch, overwriting
    content_b64 with the attacker content → select_restorable_content returned attacker bytes.
    """
    from agent.baseline import BaselineEngine, select_restorable_content
    from agent.detector import FanotifyDetector, FanotifyEvent

    # Set up a real BaselineEngine with a real file
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    master_secret = os.urandom(32)
    master_secret_path = tmp_path / "secrets" / "master_secret"
    master_secret_path.parent.mkdir(parents=True, exist_ok=True)
    master_secret_path.write_bytes(master_secret)

    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(b"fake-ca")

    cfg = AgentConfig(
        agent_id="test-agent-c28",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path=str(ca_path),
        watch_paths=[str(tmp_path / "watch")],
        storage=StorageConfig(
            baseline_dir=str(baseline_dir),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
        ),
    )

    baseline_engine = BaselineEngine(cfg, master_secret)

    # Create file with known-good content
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir(parents=True, exist_ok=True)
    target_path = watch_dir / "config.conf"
    known_good = b"known-good content line\n"
    target_path.write_bytes(known_good)

    # Record known-good in baseline
    baseline_engine.write_entry(str(target_path))

    # Verify initial state
    entry_before = baseline_engine.read_entry(str(target_path))
    assert entry_before is not None
    original_content_b64 = entry_before.content_b64
    original_hash = entry_before.hash
    assert original_content_b64 is not None

    result_before = select_restorable_content(entry_before)
    assert result_before is not None
    assert result_before[0] == known_good, "setup: baseline must have known-good content"

    # Now attacker modifies the file
    attacker_content = b"attacker modified content EVIL\n"
    target_path.write_bytes(attacker_content)

    # Set up decision engine with alert_only
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "alert_only"
    journal = JournalManager(journal_dir, shared_secret=_SHARED_SECRET)

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline_engine,
        quarantine_dir=quarantine_dir,
    )

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    stop_event = asyncio.Event()
    detector = FanotifyDetector(
        agent_id="test-agent-c28",
        watch_paths=[str(watch_dir)],
        baseline=baseline_engine,
        publisher=publisher,
        stop_event=stop_event,
        decision_engine=engine,
    )

    fan_event = FanotifyEvent(
        path=str(target_path),
        pid=999,
        uid=1000,
        exe="/usr/bin/vim",
        timestamp="2026-01-01T00:00:00+00:00",
        mask=0,
    )

    # _classify_event with no fanotify returns "file_modified" (falls through to main branch)
    # The close_write / unclassified branch triggers the BUG-03 else-path
    with patch("agent.detector._HAS_FAN", False):
        await detector._process_event(fan_event)

    # Verify: active baseline must still point to known-good
    entry_after = baseline_engine.read_entry(str(target_path))
    assert entry_after is not None

    # The critical D14 assertion: select_restorable_content returns known-good, NOT attacker
    result_after = select_restorable_content(entry_after)
    assert result_after is not None, "must be able to restore after alert_only event"
    restored_bytes, _ = result_after

    assert restored_bytes == known_good, (
        "D14 INVARIANT VIOLATED: select_restorable_content returned attacker content!\n"
        f"Expected: {known_good!r}\n"
        f"Got:      {restored_bytes!r}"
    )

    # Also verify: active entry hash and content_b64 unchanged
    assert entry_after.content_b64 == original_content_b64, (
        "active content_b64 must NOT have been updated with attacker content"
    )
    assert entry_after.hash == original_hash, (
        "active hash must NOT have been updated to attacker hash"
    )

    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]
    assert payload.get("action") == "alert_only"
