"""
Tests del estado final del journal tras `handle_restore_file` / `handle_quarantine_file`
(US-12, change `backlog-partial-stories-completion`, tasks 6.1-6.4).

Deliberately a SEPARATE file from `agent/tests/test_commands.py` (not an edit to it):
Change 53 (`agent-queue-encryption-at-rest`) is being applied concurrently in `agent/`,
so this file duplicates the small local fixtures it needs instead of touching a file
that change may also be editing.

The handlers never delete the journal entry after marking it (unlike DecisionEngine),
so the final state is observable by reading it back with a real `JournalManager` over
`tmp_path` — no espías necesarios.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agent.baseline import BaselineEngine, derive_baseline_key  # noqa: F401 — kept for parity/reference
from agent.config import AgentConfig, StorageConfig
from agent.journal import JournalManager
from agent.streams import sign_payload

_LINUX = sys.platform != "win32"


# ── Fixtures locales (duplicadas de test_commands.py a propósito) ────────────


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
        "quarantine": tmp_path / "quarantine",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture()
def agent_config(
    tmp_dirs: dict[str, Path], shared_secret: bytes, master_secret: bytes
) -> AgentConfig:
    secret_path = tmp_dirs["secrets"] / "shared_secret"
    secret_path.write_bytes(shared_secret)
    (tmp_dirs["secrets"] / "master_secret").write_bytes(master_secret)

    tmp_root = str(tmp_dirs["baseline"].parent)

    return AgentConfig(
        agent_id="test-agent-journal-001",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/etc", tmp_root],
        storage=StorageConfig(
            baseline_dir=str(tmp_dirs["baseline"]),
            queue_dir=str(tmp_dirs["queue"]),
            journal_dir=str(tmp_dirs["journal"]),
            secrets_dir=str(tmp_dirs["secrets"]),
        ),
        allow_plaintext_valkey=True,
    )


@pytest.fixture()
def baseline_engine(agent_config: AgentConfig, master_secret: bytes) -> BaselineEngine:
    return BaselineEngine(agent_config, master_secret)


@pytest.fixture()
def journal(tmp_dirs: dict[str, Path], shared_secret: bytes) -> JournalManager:
    return JournalManager(tmp_dirs["journal"], shared_secret)


@pytest.fixture()
def mock_valkey():
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.xadd = AsyncMock()
    return client


def _signed_command(agent_config: AgentConfig, shared_secret: bytes, cmd_type: str, path: str, command_id: str) -> dict:
    cmd: dict = {
        "type": cmd_type,
        "command_id": command_id,
        "event_id": 999,
        "target_agent_id": agent_config.agent_id,
        "path": path,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)
    return cmd


# ── 6.1 handle_restore_file exitoso → journal completed ──────────────────────


@pytest.mark.asyncio
async def test_handle_restore_file_success_leaves_journal_completed(
    agent_config, shared_secret, baseline_engine, mock_valkey, journal, tmp_path
):
    target = tmp_path / "restore-target.txt"
    content = b"content from baseline"
    target.write_bytes(content)
    baseline_engine.write_entry(str(target))
    target.write_bytes(b"corrupted content")

    command_id = "cmd-journal-restore-ok"
    cmd = _signed_command(agent_config, shared_secret, "restore_file", str(target), command_id)

    from agent import commands

    await commands.handle_restore_file(
        command=cmd,
        baseline_engine=baseline_engine,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    entry = journal._read(command_id)
    assert entry is not None
    assert entry.state == "completed"


# ── 6.2 handle_restore_file sin baseline → journal failed ────────────────────


@pytest.mark.asyncio
async def test_handle_restore_file_no_baseline_leaves_journal_failed(
    agent_config, shared_secret, baseline_engine, mock_valkey, journal
):
    command_id = "cmd-journal-restore-fail"
    # Dentro de /etc (watch_paths) pero sin entry de baseline.
    cmd = _signed_command(
        agent_config, shared_secret, "restore_file", "/etc/no_baseline_for_this_test_fim", command_id
    )

    from agent import commands

    await commands.handle_restore_file(
        command=cmd,
        baseline_engine=baseline_engine,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    entry = journal._read(command_id)
    assert entry is not None
    assert entry.state == "failed"
    assert entry.error == "no_baseline_content"


# ── 6.3 handle_quarantine_file exitoso → journal completed ───────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(not _LINUX, reason="chmod/quarantine dir requires Unix")
async def test_handle_quarantine_file_success_leaves_journal_completed(
    agent_config, shared_secret, master_secret, mock_valkey, journal, tmp_path
):
    target = tmp_path / "quarantine-target.sh"
    target.write_text("#!/bin/bash\necho hi\n")

    quarantine_dir = tmp_path / "quarantine-ok"
    quarantine_dir.mkdir(exist_ok=True)

    command_id = "cmd-journal-quarantine-ok"
    cmd = _signed_command(agent_config, shared_secret, "quarantine_file", str(target), command_id)

    from agent import commands

    await commands.handle_quarantine_file(
        command=cmd,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
        quarantine_dir=str(quarantine_dir),
    )

    entry = journal._read(command_id)
    assert entry is not None
    assert entry.state == "completed"


# ── 6.4 handle_quarantine_file con fallo del store → journal failed ─────────


@pytest.mark.asyncio
async def test_handle_quarantine_file_store_failure_leaves_journal_failed(
    agent_config, shared_secret, mock_valkey, journal, tmp_path
):
    from unittest.mock import MagicMock

    from agent.quarantine import QuarantineError

    target = tmp_path / "quarantine-fail-target.sh"
    target.write_text("#!/bin/bash\necho hi\n")

    command_id = "cmd-journal-quarantine-fail"
    cmd = _signed_command(agent_config, shared_secret, "quarantine_file", str(target), command_id)

    failing_store = MagicMock()
    failing_store.quarantine.side_effect = QuarantineError("encrypt_failed")

    from agent import commands

    await commands.handle_quarantine_file(
        command=cmd,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
        quarantine_store=failing_store,
    )

    entry = journal._read(command_id)
    assert entry is not None
    assert entry.state == "failed"
    assert entry.error

    # El error persistido en el journal coincide con el publicado en el ack.
    import json

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "error"
    assert ack_payload["error"] == entry.error
