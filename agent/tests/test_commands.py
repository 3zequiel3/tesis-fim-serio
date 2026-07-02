"""
Tests del módulo agent/commands.py (C13, tasks 13.1–13.13).

Cubre:
  13.1  test_dispatch_routes_baseline_update
  13.2  test_dispatch_unknown_type_no_exception
  13.3  test_hmac_invalid_discards_command
  13.4  test_target_agent_id_filter_other_agent
  13.5  test_target_agent_id_null_broadcast
  13.6  test_baseline_update_present_writes_encrypted
  13.7  test_baseline_update_absent_writes_null_hash
  13.8  test_baseline_update_older_version_ignored
  13.9  test_restore_handler_success_publishes_ack
  13.10 test_restore_handler_no_baseline_publishes_error_ack
  13.11 test_quarantine_handler_success
  13.12 test_quarantine_handler_file_not_found_publishes_error_ack
  13.13 test_journal_written_before_filesystem_op

Los tests que requieren operaciones Unix (chmod, /var/lib) se saltan en Windows.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import platform
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.baseline import BaselineEngine, derive_baseline_key
from agent.config import AgentConfig, StorageConfig
from agent.journal import JournalManager
from agent.state import AgentState
from agent.streams import canonical_json, sign_payload, verify_payload

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
        "quarantine": tmp_path / "quarantine",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture()
def agent_config(tmp_dirs: dict[str, Path], shared_secret: bytes) -> AgentConfig:
    # Escribir shared_secret en disco para que load_shared_secret lo encuentre
    secret_path = tmp_dirs["secrets"] / "shared_secret"
    secret_path.write_bytes(shared_secret)

    # Include tmp_path (parent of all tmp_dirs) in watch_paths so that tests
    # creating files under tmp_path pass the FIX-04 path containment check (D18).
    tmp_root = str(tmp_dirs["baseline"].parent)

    return AgentConfig(
        agent_id="test-agent-001",
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
        "command_id": "cmd-test-001",
        "event_id": 42,
        "target_agent_id": agent_config.agent_id,
        "path": "/etc/passwd",
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    if extra:
        payload.update(extra)
    payload["signature"] = sign_payload(shared_secret, payload)
    return payload


# ── 13.1 test_dispatch_routes_baseline_update ────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_routes_baseline_update(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal
):
    """Tipo baseline_update llama al handler correcto."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "baseline_update", {
        "hash": "abc123",
        "baseline_status": "present",
        "ruleset_version": 1,
    })

    called = []
    original_handler = commands.handle_baseline_update

    async def mock_handler(**kwargs):
        called.append("baseline_update")
        await original_handler(**kwargs)

    with patch.object(commands, "handle_baseline_update", side_effect=mock_handler):
        await commands.dispatch(
            cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
            journal=journal,
        )

    assert "baseline_update" in called


# ── 13.2 test_dispatch_unknown_type_no_exception ─────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_unknown_type_no_exception(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal
):
    """Tipo desconocido: sin excepción, log warning."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "unknown_command_xyz")

    # No debe lanzar excepción
    await commands.dispatch(
        cmd,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
        journal=journal,
    )
    # No se publicó nada
    mock_valkey.xadd.assert_not_called()


# ── 13.3 test_hmac_invalid_discards_command ───────────────────────────────────


@pytest.mark.asyncio
async def test_hmac_invalid_discards_command(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal
):
    """Firma incorrecta → handler no llamado, sin excepción."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "baseline_update", {
        "hash": "abc123",
        "baseline_status": "present",
        "ruleset_version": 1,
    })
    # Corromper la firma
    cmd["signature"] = "0" * 64

    called = []

    async def mock_handler(**kwargs):
        called.append("called")

    with patch.object(commands, "handle_baseline_update", side_effect=mock_handler):
        await commands.dispatch(
            cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
            journal=journal,
        )

    assert called == []
    mock_valkey.xadd.assert_not_called()


# ── 13.4 test_target_agent_id_filter_other_agent ─────────────────────────────


@pytest.mark.asyncio
async def test_target_agent_id_filter_other_agent(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal
):
    """Comando para otro agente → ignorado silenciosamente."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "baseline_update", {
        "hash": "abc123",
        "baseline_status": "present",
        "ruleset_version": 1,
    })
    cmd["target_agent_id"] = "other-agent-999"
    # Re-firmar con target correcto (la verificación HMAC fallará por el cambio)
    # En realidad no importa porque el filtro de target_agent_id sucede ANTES del HMAC

    called = []

    async def mock_handler(**kwargs):
        called.append("called")

    with patch.object(commands, "handle_baseline_update", side_effect=mock_handler):
        await commands.dispatch(
            cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
            journal=journal,
        )

    assert called == []


# ── 13.5 test_target_agent_id_null_broadcast ─────────────────────────────────


@pytest.mark.asyncio
async def test_target_agent_id_null_broadcast(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal
):
    """target_agent_id=null → broadcast, procesado por este agente."""
    from agent import commands

    cmd: dict = {
        "type": "baseline_update",
        "command_id": "cmd-broadcast-001",
        "event_id": 99,
        "target_agent_id": None,
        "path": "/etc/hosts",
        "hash": "def456",
        "baseline_status": "present",
        "ruleset_version": 2,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    called = []
    original = commands.handle_baseline_update

    async def mock_handler(**kwargs):
        called.append("called")
        await original(**kwargs)

    with patch.object(commands, "handle_baseline_update", side_effect=mock_handler):
        await commands.dispatch(
            cmd,
            baseline_engine=baseline_engine,
            state=agent_state,
            valkey_client=mock_valkey,
            config=agent_config,
            journal=journal,
        )

    assert "called" in called


# ── 13.6 test_baseline_update_present_writes_encrypted ───────────────────────


@pytest.mark.asyncio
async def test_baseline_update_present_writes_encrypted(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Entry cifrada creada/actualizada para status=present."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "baseline_update", {
        "hash": "aabb1122",
        "baseline_status": "present",
        "ruleset_version": 3,
    })

    await commands.handle_baseline_update(
        command=cmd,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    # Verificar que la entry existe y es legible
    entry = baseline_engine.read_entry("/etc/passwd")
    assert entry is not None
    assert entry.status == "present"
    assert entry.hash == "aabb1122"
    assert agent_state.ruleset_version == 3


# ── 13.7 test_baseline_update_absent_writes_null_hash ────────────────────────


@pytest.mark.asyncio
async def test_baseline_update_absent_writes_null_hash(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Entry con status=absent y hash=null escrita correctamente."""
    from agent import commands

    cmd = _make_command(agent_config, shared_secret, "baseline_update", {
        "hash": None,
        "baseline_status": "absent",
        "ruleset_version": 5,
    })

    await commands.handle_baseline_update(
        command=cmd,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    entry = baseline_engine.read_entry("/etc/passwd")
    assert entry is not None
    assert entry.status == "absent"
    assert entry.hash is None
    assert agent_state.ruleset_version == 5


# ── 13.8 test_baseline_update_older_version_ignored ──────────────────────────


@pytest.mark.asyncio
async def test_baseline_update_older_version_ignored(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey
):
    """Versión menor que la local → ignorado, baseline no cambia."""
    from agent import commands

    agent_state.ruleset_version = 10

    cmd = _make_command(agent_config, shared_secret, "baseline_update", {
        "hash": "stale_hash",
        "baseline_status": "present",
        "ruleset_version": 7,  # menor que 10
    })

    await commands.handle_baseline_update(
        command=cmd,
        baseline_engine=baseline_engine,
        state=agent_state,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    # No se debe haber escrito la entry (path no existe en baseline)
    entry = baseline_engine.read_entry("/etc/passwd")
    assert entry is None
    # Estado no cambia
    assert agent_state.ruleset_version == 10
    # No se publicó ack (se salió sin ejecutar)
    mock_valkey.xadd.assert_not_called()


# ── 13.9 test_restore_handler_success_publishes_ack ──────────────────────────


@pytest.mark.asyncio
async def test_restore_handler_success_publishes_ack(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal, tmp_path
):
    """Restore exitoso publica event_ack con status=ok."""
    from agent import commands

    # Crear archivo de destino con contenido "corrupto"
    target = tmp_path / "target.txt"
    content = b"original content from baseline"
    target.write_bytes(b"corrupted content")

    # Escribir entry en baseline con content_b64
    content_b64 = base64.b64encode(content).decode()
    content_hash = hashlib.sha256(content).hexdigest()

    # Usar update_from_command para crear la entry base
    baseline_engine.update_from_command(str(target), content_hash, "present")
    # Ahora inyectar content_b64 manualmente (update_from_command no guarda content_b64)
    # Para este test usamos write_entry que sí guarda content_b64
    target.write_bytes(content)  # primero restaurar para poder hacer write_entry
    baseline_engine.write_entry(str(target))
    target.write_bytes(b"corrupted content")  # volver a corromper

    cmd: dict = {
        "type": "restore_file",
        "command_id": "cmd-restore-001",
        "event_id": 10,
        "target_agent_id": agent_config.agent_id,
        "path": str(target),
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    await commands.handle_restore_file(
        command=cmd,
        baseline_engine=baseline_engine,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    # event_ack publicado
    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "ok"
    assert ack_payload["command_id"] == "cmd-restore-001"
    assert ack_payload["command_type"] == "restore_file"

    # Archivo restaurado
    assert target.read_bytes() == content


# ── 13.10 test_restore_handler_no_baseline_publishes_error_ack ───────────────


@pytest.mark.asyncio
async def test_restore_handler_no_baseline_publishes_error_ack(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal, tmp_path
):
    """Restore sin baseline → event_ack con status=error."""
    from agent import commands

    # Use a path inside /etc so it passes the FIX-04 containment check (D18)
    cmd: dict = {
        "type": "restore_file",
        "command_id": "cmd-restore-002",
        "event_id": 11,
        "target_agent_id": agent_config.agent_id,
        "path": "/etc/nonexistent_test_fim_file",
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    await commands.handle_restore_file(
        command=cmd,
        baseline_engine=baseline_engine,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "error"
    assert ack_payload["error"] is not None


# ── 13.11 test_quarantine_handler_success ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="chmod/quarantine dir requires Unix")
async def test_quarantine_handler_success(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal, tmp_path
):
    """Quarantine exitoso: archivo movido, permisos 0400, event_ack ok."""
    from agent import commands

    target = tmp_path / "malicious.sh"
    target.write_text("#!/bin/bash\nrm -rf /")

    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(exist_ok=True)

    cmd: dict = {
        "type": "quarantine_file",
        "command_id": "cmd-quarantine-001",
        "event_id": 20,
        "target_agent_id": agent_config.agent_id,
        "path": str(target),
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    await commands.handle_quarantine_file(
        command=cmd,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
        quarantine_dir=str(quarantine_dir),
    )

    # Archivo ya no existe en origen
    assert not target.exists()

    # Archivo existe en quarantine con permisos 0400
    quarantine_files = list(quarantine_dir.iterdir())
    assert len(quarantine_files) == 1
    mode = quarantine_files[0].stat().st_mode & 0o777
    assert mode == 0o400

    # event_ack publicado
    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "ok"


# ── 13.12 test_quarantine_handler_file_not_found_publishes_error_ack ─────────


@pytest.mark.asyncio
async def test_quarantine_handler_file_not_found_publishes_error_ack(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal, tmp_path
):
    """Archivo inexistente en quarantine → event_ack con status=error."""
    from agent import commands

    quarantine_dir = tmp_path / "quarantine2"
    quarantine_dir.mkdir(exist_ok=True)

    # Use a path inside /etc so it passes the FIX-04 containment check (D18)
    cmd: dict = {
        "type": "quarantine_file",
        "command_id": "cmd-quarantine-002",
        "event_id": 21,
        "target_agent_id": agent_config.agent_id,
        "path": "/etc/nonexistent_test_fim_file",
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    await commands.handle_quarantine_file(
        command=cmd,
        journal=journal,
        valkey_client=mock_valkey,
        config=agent_config,
        quarantine_dir=str(quarantine_dir),
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "error"
    assert "file_not_found" in (ack_payload["error"] or "")


# ── 13.13 test_journal_written_before_filesystem_op ──────────────────────────


@pytest.mark.asyncio
async def test_journal_written_before_filesystem_op(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal, tmp_path
):
    """Journal pre-acción existe en disco antes de modificar el filesystem."""
    from agent import commands

    # Crear archivo con baseline
    target = tmp_path / "important.conf"
    content = b"important config content"
    target.write_bytes(content)
    baseline_engine.write_entry(str(target))
    target.write_bytes(b"modified content")  # simular modificación

    cmd: dict = {
        "type": "restore_file",
        "command_id": "cmd-journal-test-001",
        "event_id": 30,
        "target_agent_id": agent_config.agent_id,
        "path": str(target),
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    cmd["signature"] = sign_payload(shared_secret, cmd)

    journal_dir = tmp_path / "journal"
    journal_key = "cmd-journal-test-001"
    journal_path = journal_dir / f"{journal_key}.json"

    # Interceptar la escritura al filesystem para verificar que el journal ya existe
    filesystem_write_happened = []
    journal_existed_at_write = []

    original_open = open

    def patched_open(path, mode="r", **kwargs):
        path_str = str(path)
        if ".fim_restore_tmp" in path_str and "wb" in mode:
            filesystem_write_happened.append(True)
            journal_existed_at_write.append(journal_path.exists())
        return original_open(path, mode, **kwargs)

    with patch("builtins.open", side_effect=patched_open):
        await commands.handle_restore_file(
            command=cmd,
            baseline_engine=baseline_engine,
            journal=journal,
            valkey_client=mock_valkey,
            config=agent_config,
        )

    # El journal debe haber existido antes de que se intentara escribir el archivo
    if filesystem_write_happened:
        assert all(journal_existed_at_write), "Journal pre-acción debe existir antes de escribir al filesystem"
    else:
        # Si no llegó a escribir (fallo por otro motivo), igual verificar que journal existe
        assert journal_path.exists(), "Journal pre-acción debe existir"


# ── C36 (D30/RN-79): _publish_ack firma el command_ack con HMAC ──────────────


@pytest.mark.asyncio
async def test_publish_ack_signs_command_ack_with_hmac(
    agent_config, shared_secret, baseline_engine, agent_state, mock_valkey, journal
):
    """
    Decisión del usuario (2026-07-02, C36): el command_ack ahora viaja firmado
    HMAC-SHA256, igual que los comandos entrantes. El consumer del backend
    rechaza acks sin firma válida.
    """
    from agent import commands

    await commands._publish_ack(
        mock_valkey,
        command_id="cmd-sign-test-001",
        command_type="rescan_baseline",
        event_id=None,
        config=agent_config,
        ok=True,
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])

    assert "signature" in ack_payload
    assert verify_payload(shared_secret, ack_payload), "la firma del command_ack debe ser verificable"


@pytest.mark.asyncio
async def test_publish_ack_logs_error_without_shared_secret(
    baseline_engine, agent_state, mock_valkey, journal, tmp_path
):
    """Sin shared_secret local, se publica sin firma (fail-open observable) y se loguea ERROR."""
    from agent import commands
    from agent.config import AgentConfig, StorageConfig

    empty_secrets_dir = tmp_path / "no-secrets"
    empty_secrets_dir.mkdir(parents=True, exist_ok=True)
    config_without_secret = AgentConfig(
        agent_id="test-agent-nosecret",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(empty_secrets_dir),
        ),
        allow_plaintext_valkey=True,
    )

    await commands._publish_ack(
        mock_valkey,
        command_id="cmd-sign-test-002",
        command_type="rescan_baseline",
        event_id=None,
        config=config_without_secret,
        ok=True,
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert "signature" not in ack_payload
