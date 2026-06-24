"""
Tests de C25 — agent-reconnect-order.

Cubre:
  5.1 Orden: _drain_queue no inicia hasta que _flush_commands termina
  5.2 Cursor cargado: XREAD arranca desde el cursor persistido, no desde "$"
  5.3 Primer arranque: sin state.json, cursor es "0-0"
  5.4 Persistencia: cursor se actualiza en disco tras cada mensaje procesado
  5.5 Timeout: flush continúa al drain si se supera command_flush_timeout_s
  5.6 Firma inválida: el cursor avanza aunque el mensaje no se aplique
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agent.config import AgentConfig, PublisherConfig, StorageConfig
from agent.publisher import Publisher
from agent.queue import EventQueue
from agent.state import AgentState, load_state, save_state
from agent.streams import sign_payload


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_signed_msg(secret: bytes, payload: dict) -> dict[str, str]:
    sig = sign_payload(secret, payload)
    full = {**payload, "signature": sig}
    return {"data": json.dumps(full, sort_keys=True, separators=(",", ":"))}


def _stream_entry(secret: bytes, msg_id: str, payload: dict) -> tuple[str, dict]:
    return (msg_id, _make_signed_msg(secret, payload))


# ── fixtures ──────────────────────────────────────────────────────────────────


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
            secrets_dir=str(secrets_dir),
            certs_dir=str(tmp_path / "certs"),
        ),
        publisher=PublisherConfig(command_flush_timeout_s=2.0),
    )


@pytest.fixture()
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


@pytest.fixture()
def agent_state(state_path: Path) -> AgentState:
    st = AgentState(state_path=state_path)
    return st


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1-0")
    client.xread = AsyncMock(return_value=[])
    return client


@pytest.fixture()
def publisher(config: AgentConfig, mock_client: AsyncMock, agent_state: AgentState) -> Publisher:
    queue = EventQueue(config.storage.queue_dir)
    pub = Publisher(config, queue, mock_client)
    pub.register_command_handlers(
        baseline_engine=MagicMock(),
        state=agent_state,
        journal=MagicMock(),
        quarantine_dir=None,
        detector=None,
    )
    return pub


# ── 5.1 Orden de arranque ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drain_runs_after_command_flush(
    publisher: Publisher, mock_client: AsyncMock
) -> None:
    """_drain_queue no inicia hasta que _flush_commands termina."""
    call_order: list[str] = []

    original_flush = publisher._flush_commands
    original_drain = publisher._drain_queue

    async def _tracked_flush():
        call_order.append("flush_start")
        await original_flush()
        call_order.append("flush_end")

    async def _tracked_drain():
        call_order.append("drain_start")
        await original_drain()

    publisher._flush_commands = _tracked_flush
    publisher._drain_queue = _tracked_drain

    # xread retorna vacío inmediatamente (sin comandos pendientes)
    mock_client.xread = AsyncMock(return_value=[])

    stop_event = asyncio.Event()
    stop_event.set()

    await publisher.run(stop_event)

    assert call_order.index("flush_end") < call_order.index("drain_start"), (
        "drain_queue debe iniciar después de que flush_commands termine"
    )


# ── 5.2 Cursor cargado desde estado previo ────────────────────────────────────


@pytest.mark.asyncio
async def test_cursor_loaded_on_restart(
    publisher: Publisher,
    mock_client: AsyncMock,
    agent_state: AgentState,
) -> None:
    """XREAD arranca desde el cursor guardado, no desde '$'."""
    saved_cursor = "1718000000000-0"
    agent_state.last_stream_command_id = saved_cursor

    # xread retorna vacío — sólo nos interesa con qué cursor se llamó
    mock_client.xread = AsyncMock(return_value=[])

    await publisher._flush_commands()

    # La primera llamada a xread debe usar el cursor guardado
    first_call = mock_client.xread.call_args_list[0]
    stream_arg: dict = first_call[0][0]
    assert stream_arg.get("commands") == saved_cursor, (
        f"XREAD debe arrancar desde '{saved_cursor}', no desde '$'"
    )


# ── 5.3 Primer arranque sin state.json ────────────────────────────────────────


def test_first_start_uses_zero_cursor(state_path: Path) -> None:
    """Sin state.json, AgentState.last_stream_command_id es '0-0'."""
    assert not state_path.exists()
    st = load_state(state_path)
    assert st.last_stream_command_id == "0-0"


@pytest.mark.asyncio
async def test_first_start_xread_from_origin(
    publisher: Publisher,
    mock_client: AsyncMock,
    agent_state: AgentState,
) -> None:
    """Sin estado previo, XREAD arranca desde '0-0' (origen del stream)."""
    assert agent_state.last_stream_command_id == "0-0"
    mock_client.xread = AsyncMock(return_value=[])

    await publisher._flush_commands()

    first_call = mock_client.xread.call_args_list[0]
    stream_arg: dict = first_call[0][0]
    assert stream_arg.get("commands") == "0-0"


# ── 5.4 Persistencia del cursor tras cada mensaje ─────────────────────────────


@pytest.mark.asyncio
async def test_cursor_persisted_on_each_message(
    publisher: Publisher,
    mock_client: AsyncMock,
    agent_state: AgentState,
    state_path: Path,
    shared_secret: bytes,
) -> None:
    """El cursor se actualiza en disco tras cada mensaje procesado."""
    msg1_id = "1000000000000-0"
    msg2_id = "1000000000001-0"

    ack_payload = {
        "type": "event_ack",
        "event_id": "evt-abc",
        "agent_id": "test-agent-01",
    }

    entry1 = _stream_entry(shared_secret, msg1_id, ack_payload)
    entry2 = _stream_entry(shared_secret, msg2_id, ack_payload)

    # Primera ronda: dos mensajes; segunda ronda: vacío
    mock_client.xread = AsyncMock(side_effect=[
        [("commands", [entry1, entry2])],
        [],
    ])

    saves: list[str] = []
    original_save = publisher._flush_commands.__func__ if hasattr(publisher._flush_commands, '__func__') else None

    # Patch save_state para registrar cuándo se llama y con qué cursor
    import agent.publisher as pub_module
    original_save_state = pub_module.save_state

    def _tracking_save(state: AgentState) -> None:
        saves.append(state.last_stream_command_id)
        original_save_state(state)

    with patch.object(pub_module, "save_state", side_effect=_tracking_save):
        await publisher._flush_commands()

    # Se deben haber hecho exactamente 2 saves (uno por mensaje)
    assert len(saves) == 2, f"Esperaba 2 saves, hubo {len(saves)}: {saves}"
    assert saves[0] == msg1_id
    assert saves[1] == msg2_id

    # El cursor en disco debe ser el del último mensaje
    loaded = load_state(state_path)
    assert loaded.last_stream_command_id == msg2_id


# ── 5.5 Timeout: flush continúa al drain sin bloquearse ──────────────────────


@pytest.mark.asyncio
async def test_flush_timeout_continues_to_drain(
    config: AgentConfig,
    mock_client: AsyncMock,
    agent_state: AgentState,
) -> None:
    """Si se supera command_flush_timeout_s, el flush termina y continúa al drain."""
    # Timeout muy corto para que expire rápido
    config = config.model_copy(
        update={"publisher": PublisherConfig(command_flush_timeout_s=0.05)}
    )

    queue = EventQueue(config.storage.queue_dir)
    pub = Publisher(config, queue, mock_client)
    pub.register_command_handlers(
        baseline_engine=MagicMock(),
        state=agent_state,
        journal=MagicMock(),
        quarantine_dir=None,
        detector=None,
    )

    async def _slow_xread(streams, block, count):
        # Simula latencia mayor que el timeout
        await asyncio.sleep(0.2)
        return []

    mock_client.xread = AsyncMock(side_effect=_slow_xread)

    drain_called = False
    original_drain = pub._drain_queue

    async def _tracking_drain():
        nonlocal drain_called
        drain_called = True
        await original_drain()

    pub._drain_queue = _tracking_drain

    stop_event = asyncio.Event()
    stop_event.set()

    # No debe bloquearse ni lanzar excepción
    await pub.run(stop_event)

    assert drain_called, "_drain_queue debe llamarse incluso cuando el flush agota el timeout"


# ── 5.6 Firma inválida: cursor avanza igualmente ─────────────────────────────


@pytest.mark.asyncio
async def test_invalid_hmac_cursor_still_advances(
    publisher: Publisher,
    mock_client: AsyncMock,
    agent_state: AgentState,
    state_path: Path,
) -> None:
    """Un mensaje con firma inválida no se aplica, pero el cursor avanza."""
    bad_msg_id = "2000000000000-0"
    bad_entry = (bad_msg_id, {"data": json.dumps({"type": "event_ack", "signature": "bad"})})

    mock_client.xread = AsyncMock(side_effect=[
        [("commands", [bad_entry])],
        [],
    ])

    handle_calls: list = []
    original_handle = publisher._handle_command_async

    async def _tracking_handle(payload):
        handle_calls.append(payload)
        await original_handle(payload)

    publisher._handle_command_async = _tracking_handle

    await publisher._flush_commands()

    # El mensaje con firma inválida no pasa a _handle_command_async
    assert handle_calls == [], "Mensaje con HMAC inválida no debe despacharse"

    # Pero el cursor sí debe haber avanzado al id del mensaje
    assert agent_state.last_stream_command_id == bad_msg_id, (
        f"El cursor debe avanzar a '{bad_msg_id}' incluso si la firma es inválida"
    )
    loaded = load_state(state_path)
    assert loaded.last_stream_command_id == bad_msg_id


# ── 5.extra: ack_listener arranca desde cursor, no desde "$" ─────────────────


@pytest.mark.asyncio
async def test_ack_listener_uses_persisted_cursor(
    publisher: Publisher,
    mock_client: AsyncMock,
    agent_state: AgentState,
) -> None:
    """_ack_listener arranca desde el cursor persistido, no desde '$'."""
    saved_cursor = "9990000000000-0"
    agent_state.last_stream_command_id = saved_cursor

    stop_event = asyncio.Event()
    calls_made: list[dict] = []

    async def _capture_and_stop(streams, block, count):
        calls_made.append(dict(streams))
        stop_event.set()
        return []

    mock_client.xread = AsyncMock(side_effect=_capture_and_stop)

    await publisher._ack_listener(stop_event)

    assert calls_made, "_ack_listener debe haber llamado a xread al menos una vez"
    first_stream_arg = calls_made[0]
    assert first_stream_arg.get("commands") == saved_cursor, (
        f"_ack_listener debe arrancar desde '{saved_cursor}', no desde '$'"
    )
