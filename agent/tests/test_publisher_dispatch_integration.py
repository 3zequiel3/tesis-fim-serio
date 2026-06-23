"""
Integración C1/C3 (C21): verifica que un comando válido firmado pasa por commands.dispatch
después de register_command_handlers, sin logear command_handler_not_registered. (tasks 6.4)
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import AgentConfig, StorageConfig
from agent.publisher import Publisher
from agent.queue import EventQueue
from agent.streams import sign_payload


@pytest.fixture()
def shared_secret(tmp_path: Path) -> bytes:
    secret = os.urandom(32)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    p = secrets_dir / "shared_secret"
    fd = os.open(str(p), os.O_CREAT | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(secret)
    return secret


@pytest.fixture()
def config(tmp_path: Path, shared_secret: bytes) -> AgentConfig:
    secrets_dir = tmp_path / "secrets"
    return AgentConfig(
        agent_id="test-agent-01",
        backend_url="http://localhost:8000",
        valkey_url="redis://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/tmp"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
            certs_dir=str(tmp_path / "certs"),
        ),
    )


@pytest.fixture()
def publisher(config: AgentConfig, tmp_path: Path) -> Publisher:
    queue = EventQueue(config.storage.queue_dir)
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1-0")
    return Publisher(config, queue, client)


def _make_signed_msg(secret: bytes, payload: dict) -> dict[str, str]:
    sig = sign_payload(secret, payload)
    full = {**payload, "signature": sig}
    return {"data": json.dumps(full, sort_keys=True, separators=(",", ":"))}


@pytest.mark.asyncio
async def test_restore_file_dispatched_after_register_command_handlers(
    publisher: Publisher, shared_secret: bytes
) -> None:
    """
    Con register_command_handlers registrado, un restore_file válido llega a commands.dispatch
    y no se loguea command_handler_not_registered.
    """
    baseline_engine = MagicMock()
    agent_state = MagicMock()
    journal = MagicMock()

    publisher.register_command_handlers(
        baseline_engine=baseline_engine,
        state=agent_state,
        journal=journal,
        quarantine_dir="/tmp/quarantine",
        detector=None,
    )

    payload = {
        "type": "restore_file",
        "command_id": "cmd-001",
        "target_agent_id": "test-agent-01",
        "path": "/etc/passwd",
    }

    dispatch_called: list[dict] = []

    async def _mock_dispatch(pl, **kwargs):
        dispatch_called.append(pl)

    with patch("agent.commands.dispatch", side_effect=_mock_dispatch) as mock_dispatch:
        verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, payload))
        assert verified is not None
        await publisher._handle_command_async(verified)

    assert len(dispatch_called) == 1
    assert dispatch_called[0]["type"] == "restore_file"


@pytest.mark.asyncio
async def test_update_config_dispatched_via_commands_not_direct_callback(
    publisher: Publisher, shared_secret: bytes
) -> None:
    """
    update_config ya no tiene branch directo — va a commands.dispatch (C3).
    El on_update_config_cb NO debe ser invocado directamente.
    """
    direct_callback_called: list[bool] = []
    publisher.register_callbacks(
        on_update_config=lambda paths: direct_callback_called.append(True),
    )

    baseline_engine = MagicMock()
    agent_state = MagicMock()

    publisher.register_command_handlers(
        baseline_engine=baseline_engine,
        state=agent_state,
        journal=MagicMock(),
        quarantine_dir=None,
        detector=None,
    )

    payload = {
        "type": "update_config",
        "command_id": "cmd-002",
        "target_agent_id": "test-agent-01",
        "watch_paths": ["/new/path"],
        "ruleset_version": 1,
    }

    dispatch_called: list[dict] = []

    async def _mock_dispatch(pl, **kwargs):
        dispatch_called.append(pl)

    with patch("agent.commands.dispatch", side_effect=_mock_dispatch):
        verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, payload))
        assert verified is not None
        await publisher._handle_command_async(verified)

    # El branch directo fue eliminado (C3): direct callback no se invoca
    assert direct_callback_called == []
    # Pero sí llega a commands.dispatch
    assert len(dispatch_called) == 1
    assert dispatch_called[0]["type"] == "update_config"


@pytest.mark.asyncio
async def test_command_without_handlers_logs_not_registered(
    publisher: Publisher, shared_secret: bytes
) -> None:
    """Sin register_command_handlers, los comandos C13 logean command_handler_not_registered."""
    # publisher sin register_command_handlers (estado inicial)
    payload = {
        "type": "restore_file",
        "command_id": "cmd-003",
        "target_agent_id": "test-agent-01",
        "path": "/etc/passwd",
    }

    warning_logged: list[str] = []

    with patch("agent.publisher.log") as mock_log:
        mock_log.warning = MagicMock(side_effect=lambda key, **kw: warning_logged.append(key))
        verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, payload))
        assert verified is not None
        await publisher._handle_command_async(verified)

    assert "publisher.command_handler_not_registered" in warning_logged
