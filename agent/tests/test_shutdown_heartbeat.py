"""Tests de G4 — propagación de shutdown flag al heartbeat (C26 task 4.x)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.heartbeat import HeartbeatPublisher
from agent.publisher import Publisher


def _make_config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.agent_id = "agent-shutdown-test"
    cfg.storage.secrets_dir = str(tmp_path / "secrets")
    cfg.publisher.command_flush_timeout_s = 2.0
    return cfg


def _make_publisher(tmp_path: Path) -> Publisher:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "shared_secret").write_bytes(b"x" * 32)

    cfg = _make_config(tmp_path)
    queue = MagicMock()
    queue.queue_size = 0
    queue.evicted_events = 0
    client = MagicMock()

    with patch("agent.publisher.load_shared_secret", return_value=b"x" * 32):
        pub = Publisher(cfg, queue, client)
    return pub


# ── publisher.set_shutdown ────────────────────────────────────────────────────

def test_publisher_set_shutdown_changes_property(tmp_path: Path) -> None:
    pub = _make_publisher(tmp_path)
    assert pub.shutdown is False
    pub.set_shutdown(True)
    assert pub.shutdown is True
    pub.set_shutdown(False)
    assert pub.shutdown is False


# ── HeartbeatPublisher._is_shutdown ──────────────────────────────────────────

def test_heartbeat_reads_publisher_shutdown(tmp_path: Path) -> None:
    pub = _make_publisher(tmp_path)
    cfg = MagicMock()
    queue = MagicMock()
    state = MagicMock()
    client = MagicMock()

    hb = HeartbeatPublisher(cfg, queue, state, client, publisher=pub)

    assert hb._is_shutdown(None) is False
    pub.set_shutdown(True)
    assert hb._is_shutdown(None) is True


def test_heartbeat_fallback_to_shutdown_flag_when_no_publisher() -> None:
    hb = HeartbeatPublisher(
        config=MagicMock(),
        queue=MagicMock(),
        state=MagicMock(),
        client=MagicMock(),
        publisher=None,
    )
    flag = asyncio.Event()
    assert hb._is_shutdown(flag) is False
    flag.set()
    assert hb._is_shutdown(flag) is True


def test_heartbeat_publisher_beats_shutdown_flag(tmp_path: Path) -> None:
    """publisher.shutdown=True gana aunque shutdown_flag no esté seteado."""
    pub = _make_publisher(tmp_path)
    pub.set_shutdown(True)

    hb = HeartbeatPublisher(
        config=MagicMock(),
        queue=MagicMock(),
        state=MagicMock(),
        client=MagicMock(),
        publisher=pub,
    )
    flag = asyncio.Event()  # no seteado
    assert hb._is_shutdown(flag) is True


# ── heartbeat publica shutdown=true durante drenaje ──────────────────────────

@pytest.mark.asyncio
async def test_shutdown_flag_set_on_sigterm(tmp_path: Path) -> None:
    """Simula SIGTERM: publisher.set_shutdown(True) se llama antes de stop_event."""
    pub = _make_publisher(tmp_path)

    state = MagicMock()
    state.ruleset_version = 1

    queue_mock = MagicMock()
    queue_mock.queue_size = 0
    queue_mock.queue_pressure = 0.0

    client_mock = MagicMock()
    client_mock.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=_make_config(tmp_path),
        queue=queue_mock,
        state=state,
        client=client_mock,
        publisher=pub,
    )

    stop_event = asyncio.Event()

    # Simular el handler de shutdown: set_shutdown ANTES de stop_event
    async def _sim_shutdown() -> None:
        await asyncio.sleep(0.02)
        pub.set_shutdown(True)
        await asyncio.sleep(0.015)
        stop_event.set()

    # Correr heartbeat con intervalo muy corto para capturar la publicación
    async def _hb_with_short_interval() -> None:
        while not stop_event.is_set():
            is_shutdown = hb._is_shutdown(None)
            await hb._publish(is_shutdown)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.01)
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(_sim_shutdown(), _hb_with_short_interval())

    # Al menos una publicación con shutdown=True
    calls = client_mock.xadd.call_args_list
    assert len(calls) > 0
    shutdown_payloads = []
    for call in calls:
        data = json.loads(call[0][1]["data"])
        if data.get("shutdown") is True:
            shutdown_payloads.append(data)

    assert len(shutdown_payloads) > 0, "Expected at least one heartbeat with shutdown=true"


# ── watch_path_status en el heartbeat (D36/RN-130 D-5) ───────────────────────


@pytest.mark.asyncio
async def test_heartbeat_carries_full_watch_path_status_map(tmp_path: Path) -> None:
    """El mapa completo viaja, no solo los degradados (D-5): omitir los
    escribibles haría ambiguo un path ausente (¿escribible, o agente viejo
    que no reporta?)."""
    from agent.preflight import PreflightRegistry

    registry = PreflightRegistry()
    registry.update({
        "/etc": "writable",
        "/usr/bin": "read_only_mount",
        "/srv/ghost": "missing",
    })

    state = MagicMock()
    state.ruleset_version = 1
    queue_mock = MagicMock()
    queue_mock.queue_size = 0
    queue_mock.queue_pressure = 0.0
    client_mock = MagicMock()
    client_mock.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=_make_config(tmp_path),
        queue=queue_mock,
        state=state,
        client=client_mock,
        preflight_registry=registry,
    )

    await hb._publish(shutdown=False)

    data = json.loads(client_mock.xadd.call_args[0][1]["data"])
    assert data["watch_path_status"] == {
        "/etc": "writable",
        "/usr/bin": "read_only_mount",
        "/srv/ghost": "missing",
    }


@pytest.mark.asyncio
async def test_heartbeat_reports_config_persisted_state() -> None:
    """El agente también reporta si el último intento de persistir
    config.yaml tuvo éxito (D-5)."""
    from agent.preflight import PreflightRegistry

    registry = PreflightRegistry()
    registry.update({"/etc": "writable"})
    registry.set_config_persisted(False)

    state = MagicMock()
    state.ruleset_version = 1
    queue_mock = MagicMock()
    queue_mock.queue_size = 0
    queue_mock.queue_pressure = 0.0
    client_mock = MagicMock()
    client_mock.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=MagicMock(agent_id="agent-cfg-persist"),
        queue=queue_mock,
        state=state,
        client=client_mock,
        preflight_registry=registry,
    )

    await hb._publish(shutdown=False)

    data = json.loads(client_mock.xadd.call_args[0][1]["data"])
    assert data["config_persisted"] is False


@pytest.mark.asyncio
async def test_heartbeat_omits_watch_path_status_without_registry() -> None:
    """Sin PreflightRegistry inyectado (tests legacy / wiring viejo), el
    heartbeat no emite la clave — no defaultea a un mapa vacío engañoso."""
    state = MagicMock()
    state.ruleset_version = 1
    queue_mock = MagicMock()
    queue_mock.queue_size = 0
    queue_mock.queue_pressure = 0.0
    client_mock = MagicMock()
    client_mock.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=MagicMock(agent_id="agent-no-preflight"),
        queue=queue_mock,
        state=state,
        client=client_mock,
    )

    await hb._publish(shutdown=False)

    data = json.loads(client_mock.xadd.call_args[0][1]["data"])
    assert "watch_path_status" not in data
    assert "config_persisted" not in data


@pytest.mark.asyncio
async def test_heartbeat_omits_config_persisted_before_first_update_config() -> None:
    """config_persisted es None hasta que handle_update_config corre al
    menos una vez — no se emite un valor inventado."""
    from agent.preflight import PreflightRegistry

    registry = PreflightRegistry()
    registry.update({"/etc": "writable"})  # nunca se llamó set_config_persisted

    state = MagicMock()
    state.ruleset_version = 1
    queue_mock = MagicMock()
    queue_mock.queue_size = 0
    queue_mock.queue_pressure = 0.0
    client_mock = MagicMock()
    client_mock.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=MagicMock(agent_id="agent-fresh-registry"),
        queue=queue_mock,
        state=state,
        client=client_mock,
        preflight_registry=registry,
    )

    await hb._publish(shutdown=False)

    data = json.loads(client_mock.xadd.call_args[0][1]["data"])
    assert data["watch_path_status"] == {"/etc": "writable"}
    assert "config_persisted" not in data


@pytest.mark.asyncio
async def test_heartbeat_adding_watch_path_status_keeps_signature_valid() -> None:
    """Agregar la clave es seguro para la firma: canonical_json firma el dict
    completo ordenado, sin allowlist por clave (D-5)."""
    from agent.preflight import PreflightRegistry
    from agent.streams import verify_payload

    shared_secret = b"x" * 32
    registry = PreflightRegistry()
    registry.update({"/etc": "writable", "/usr/bin": "permission_denied"})

    state = MagicMock()
    state.ruleset_version = 1
    queue_mock = MagicMock()
    queue_mock.queue_size = 0
    queue_mock.queue_pressure = 0.0
    client_mock = MagicMock()
    client_mock.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=MagicMock(agent_id="agent-sig-test"),
        queue=queue_mock,
        state=state,
        client=client_mock,
        preflight_registry=registry,
        shared_secret=shared_secret,
    )

    await hb._publish(shutdown=False)

    data = json.loads(client_mock.xadd.call_args[0][1]["data"])
    assert "watch_path_status" in data


# ── US-30: el shutdown handler propaga draining al detector (RN-93/W17) ──────
#
# `__main__._shutdown` es una closure anidada dentro de `main()` (no
# importable de forma aislada). Igual que test_stability_fixes.py::
# test_shutdown_handler_safe_before_queue_created, estos tests replican su
# cuerpo real (mismo orden de llamadas que agent/__main__.py) para verificar
# el contrato de la propagación sin requerir un loop asyncio real con signal
# handlers.


def test_shutdown_handler_sets_detector_draining_before_publisher_shutdown() -> None:
    """_shutdown() llama detector.set_draining(True) además de
    publisher.set_shutdown(True) — el detector deja de aceptar eventos de
    fanotify nuevos apenas arranca el drenaje, no solo cuando el drenaje del
    lado de la cola termina."""
    calls: list[str] = []

    queue_ref = MagicMock()
    publisher_ref = MagicMock()
    publisher_ref.set_shutdown = MagicMock(side_effect=lambda v: calls.append(f"publisher.set_shutdown({v})"))
    detector_ref = MagicMock()
    detector_ref.set_draining = MagicMock(side_effect=lambda v: calls.append(f"detector.set_draining({v})"))

    def _shutdown(sig_name: str) -> None:
        if queue_ref is None or publisher_ref is None:
            return
        if detector_ref is not None:
            detector_ref.set_draining(True)
        publisher_ref.set_shutdown(True)

    _shutdown("SIGTERM")

    detector_ref.set_draining.assert_called_once_with(True)
    publisher_ref.set_shutdown.assert_called_once_with(True)
    assert calls == ["detector.set_draining(True)", "publisher.set_shutdown(True)"]


def test_shutdown_handler_safe_when_detector_is_none() -> None:
    """Sin detector (no-Linux, D-C14: `detector = None` en __main__), el
    shutdown handler no debe romper — mismo criterio que queue/publisher None
    en test_stability_fixes.py::test_shutdown_handler_safe_before_queue_created."""
    queue_ref = MagicMock()
    publisher_ref = MagicMock()
    detector_ref = None

    def _shutdown(sig_name: str) -> None:
        if queue_ref is None or publisher_ref is None:
            return
        if detector_ref is not None:
            detector_ref.set_draining(True)
        publisher_ref.set_shutdown(True)

    # No debe lanzar excepción
    _shutdown("SIGTERM")
    publisher_ref.set_shutdown.assert_called_once_with(True)
