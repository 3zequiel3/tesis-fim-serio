"""
Tests del filtro de scope por watch_paths (C37, RN-04/RN-125, D31; refinado por
C39/RN-127, D33).

Cubre:
- Helper puro `_target_in_scope` (ex `_realpath_in_scope`; containment por destino
  resuelto, is_relative_to) — usado hoy solo para metadata / baseline de archivos
  regulares, nunca en el punto de descarte de `_read_loop`.
- Cache `_watch_paths_real` recomputado en start()/reload_paths()/reload_watch_paths().
- Filtro de descarte en `_read_loop` (antes de encolar) por UBICACIÓN
  (`_path_location_in_scope`) + contador `out_of_scope_drops`.
- Exposición de `out_of_scope_drops` en el payload del heartbeat.

pyfanotify no está disponible en este entorno (requiere kernel Linux + CAP_SYS_ADMIN),
por lo que el filtro se ejercita con paths reales/temporales + os.path.realpath/
is_relative_to, sin depender de fanotify real (ver `_HAS_FAN` en agent/detector.py).

La matriz de edge cases de symlinks (D33/RN-127: create/delete/modify de symlink,
dirs intermedios simbólicos, `hardlink_suspected`, degradación de auto_restore)
vive en `test_symlink_hardening.py` — este archivo se mantiene enfocado en el
containment "puro" heredado de C37.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.detector import FanotifyDetector, _target_in_scope
from agent.heartbeat import HeartbeatPublisher


# ── 1.2 Helper _target_in_scope (ex _realpath_in_scope) ──────────────────────

def test_target_in_scope_path_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "watched"
    root.mkdir()
    target = root / "file.txt"
    target.write_text("x")

    assert _target_in_scope(str(target), [os.path.realpath(str(root))]) is True


def test_target_in_scope_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "watched"
    root.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    target = outside / "file.txt"
    target.write_text("x")

    assert _target_in_scope(str(target), [os.path.realpath(str(root))]) is False


def test_target_in_scope_rejects_false_prefix(tmp_path: Path) -> None:
    """Root `.../app` NO debe matchear un sibling `.../apple` (D31: no startswith)."""
    root_app = tmp_path / "app"
    root_app.mkdir()
    sibling_apple = tmp_path / "apple"
    sibling_apple.mkdir()
    target = sibling_apple / "file.txt"
    target.write_text("x")

    assert _target_in_scope(str(target), [os.path.realpath(str(root_app))]) is False


def test_target_in_scope_symlink_resolves_inside(tmp_path: Path) -> None:
    root = tmp_path / "watched"
    root.mkdir()
    real_target = root / "real.txt"
    real_target.write_text("x")
    link = root / "link.txt"
    link.symlink_to(real_target)

    assert _target_in_scope(str(link), [os.path.realpath(str(root))]) is True


def test_target_in_scope_symlink_resolves_outside(tmp_path: Path) -> None:
    """
    `_target_in_scope` (destino resuelto) sigue reportando False para un symlink
    de escape — ese es su propósito de metadata. Pero esta función YA NO decide
    el descarte en `_read_loop` (ver test_symlink_event_escaping_scope_is_enqueued
    en test_symlink_hardening.py: por UBICACIÓN, el link SÍ se procesa).
    """
    root = tmp_path / "watched"
    root.mkdir()
    outside_dir = tmp_path / "secret"
    outside_dir.mkdir()
    outside_file = outside_dir / "id_rsa"
    outside_file.write_text("secret")
    link = root / "escape_link"
    link.symlink_to(outside_file)

    assert _target_in_scope(str(link), [os.path.realpath(str(root))]) is False


def test_target_in_scope_empty_roots_returns_false(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x")

    assert _target_in_scope(str(target), []) is False


# ── 2.3 Cache de watch_paths canonicalizados ──────────────────────────────────

@pytest.mark.asyncio
async def test_start_computes_watch_paths_real(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    stop_event = asyncio.Event()
    stop_event.set()  # el while de start() no debe iterar

    detector = FanotifyDetector(
        agent_id="agent-start-test",
        watch_paths=[str(watch_dir)],
        baseline=MagicMock(),
        publisher=MagicMock(),
        stop_event=stop_event,
    )
    detector._init_fan = MagicMock()
    detector._mark_paths = MagicMock()
    detector._mark_exclusion = MagicMock()

    with patch("threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value = MagicMock()
        await detector.start()

    assert detector._watch_paths_real == [os.path.realpath(str(watch_dir))]


@pytest.mark.asyncio
async def test_start_symlink_watch_path_represented_by_target(tmp_path: Path) -> None:
    real_dir = tmp_path / "real_watched"
    real_dir.mkdir()
    link_dir = tmp_path / "link_watched"
    link_dir.symlink_to(real_dir)

    stop_event = asyncio.Event()
    stop_event.set()

    detector = FanotifyDetector(
        agent_id="agent-start-symlink-test",
        watch_paths=[str(link_dir)],
        baseline=MagicMock(),
        publisher=MagicMock(),
        stop_event=stop_event,
    )
    detector._init_fan = MagicMock()
    detector._mark_paths = MagicMock()
    detector._mark_exclusion = MagicMock()

    with patch("threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value = MagicMock()
        await detector.start()

    assert detector._watch_paths_real == [os.path.realpath(str(real_dir))]


def _make_detector_with_mock_fan(tmp_path: Path) -> FanotifyDetector:
    baseline = MagicMock()
    baseline.init_scan = MagicMock()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    stop_event = MagicMock()
    detector = FanotifyDetector(
        agent_id="agent-cache-test",
        watch_paths=[str(tmp_path / "a")],
        baseline=baseline,
        publisher=publisher,
        stop_event=stop_event,
    )
    detector._flush_marks = MagicMock()
    detector._mark_paths = MagicMock()
    detector._mark_exclusion = MagicMock()
    return detector


def test_reload_paths_recomputes_watch_paths_real(tmp_path: Path) -> None:
    watch_b = tmp_path / "b"
    watch_b.mkdir()
    detector = _make_detector_with_mock_fan(tmp_path)

    detector.reload_paths([str(watch_b)])

    assert detector._watch_paths_real == [os.path.realpath(str(watch_b))]


def test_reload_watch_paths_noop_no_fan_recomputes_cache(tmp_path: Path) -> None:
    """Rama noop_no_fan (plataformas/tests sin pyfanotify) también recomputa el cache."""
    watch_b = tmp_path / "b"
    watch_b.mkdir()
    detector = _make_detector_with_mock_fan(tmp_path)

    with patch("agent.detector._HAS_FAN", False):
        detector.reload_watch_paths([str(watch_b)])

    assert detector._watch_paths_real == [os.path.realpath(str(watch_b))]


def test_reload_watch_paths_with_fan_recomputes_cache(tmp_path: Path) -> None:
    """Rama con fanotify disponible también recomputa el cache tras marcar/desmarcar."""
    watch_a = tmp_path / "a"
    watch_a.mkdir()
    watch_b = tmp_path / "b"
    watch_b.mkdir()

    detector = _make_detector_with_mock_fan(tmp_path)
    detector._watch_paths = [str(watch_a)]

    fake_fan_mod = MagicMock()
    fake_fan_mod.FAN_CLOSE_WRITE = 1
    fake_fan_mod.FAN_DELETE = 2
    fake_fan_mod.FAN_MOVED_FROM = 4
    fake_fan_mod.FAN_MOVED_TO = 8
    fake_fan_mod.FAN_CREATE = 16
    fake_fan_mod.FAN_MARK_REMOVE = 32
    fake_fan_mod.FAN_MARK_ADD = 64
    fake_fan_mod.FAN_MARK_FILESYSTEM = 128
    fake_fan_mod.mark = MagicMock()

    with patch("agent.detector._HAS_FAN", True), patch("agent.detector._fan_mod", fake_fan_mod):
        detector._fan = MagicMock()
        detector.reload_watch_paths([str(watch_b)])

    assert detector._watch_paths_real == [os.path.realpath(str(watch_b))]


# ── 3.3 / 3.4 Filtro de scope en _read_loop ───────────────────────────────────

def _make_scope_detector(watch_dir: Path) -> FanotifyDetector:
    return FanotifyDetector(
        agent_id="agent-scope-test",
        watch_paths=[str(watch_dir)],
        baseline=MagicMock(),
        publisher=MagicMock(),
        stop_event=asyncio.Event(),
    )


def _run_read_loop_once(detector: FanotifyDetector, events_batch: list) -> None:
    """
    Corre `_read_loop` real, entregando `events_batch` una vez y deteniendo
    el hilo lector poco después (mismo patrón que test_fanotify_null_path_dropped).

    `call_soon_threadsafe` se ejecuta sincrónicamente (sin loop corriendo) para
    poder observar el efecto de `_try_enqueue` sobre `_raw_queue` directamente.
    """
    detector._loop = MagicMock()
    detector._loop.call_soon_threadsafe.side_effect = lambda fn, arg: fn(arg)
    detector._raw_queue = asyncio.Queue(maxsize=1000)

    def _batches():
        yield events_batch
        while True:
            yield []

    gen = _batches()
    detector._read_fan_events = MagicMock(side_effect=lambda: next(gen))

    def _stop_soon() -> None:
        time.sleep(0.05)
        detector._stop_event.set()

    t = threading.Thread(target=_stop_soon)
    t.start()
    detector._read_loop()
    t.join()


def _make_raw_event(path: str) -> MagicMock:
    ev = MagicMock()
    ev.path = path
    ev.pid = 100
    ev.mask = 0
    return ev


def test_event_inside_watch_path_is_enqueued(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    detector = _make_scope_detector(watch_dir)

    _run_read_loop_once(detector, [_make_raw_event(str(watch_dir / "file.txt"))])

    assert detector._raw_queue.qsize() == 1
    assert detector.out_of_scope_drops == 0


def test_event_outside_watch_path_is_dropped_and_counted(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    detector = _make_scope_detector(watch_dir)
    detector._experiment_trace = MagicMock()

    _run_read_loop_once(detector, [_make_raw_event(str(outside_dir / "file.txt"))])

    assert detector._raw_queue.qsize() == 0
    assert detector.out_of_scope_drops == 1
    # An experiment trace commonly lives outside /watch on the same filesystem.
    # Tracing that out-of-scope write would recursively generate more fanotify
    # events and amplify forever.
    detector._experiment_trace.record.assert_not_called()


def test_in_scope_event_does_not_touch_counter(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    detector = _make_scope_detector(watch_dir)

    _run_read_loop_once(detector, [_make_raw_event(str(watch_dir / "ok.txt"))])

    assert detector.out_of_scope_drops == 0


def test_false_prefix_event_is_dropped(tmp_path: Path) -> None:
    """Root .../app no debe matchear un evento en el sibling .../apple."""
    root_app = tmp_path / "app"
    root_app.mkdir()
    sibling_apple = tmp_path / "apple"
    sibling_apple.mkdir()
    detector = _make_scope_detector(root_app)

    _run_read_loop_once(detector, [_make_raw_event(str(sibling_apple / "secret.txt"))])

    assert detector._raw_queue.qsize() == 0
    assert detector.out_of_scope_drops == 1


def test_symlink_event_escaping_scope_is_enqueued(tmp_path: Path) -> None:
    """
    D33/RN-127 (refina D31/RN-125, hallazgo MEDIUM-2 de la revisión de C37):
    un symlink de escape creado DENTRO de un watch_path está en scope por
    UBICACIÓN aunque su destino resuelto no lo esté. Ya NO se descarta en
    `_read_loop` — se encola para que `_process_event` lo reporte como objeto
    (symlink-as-object, ver test_symlink_hardening.py).
    """
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    outside_dir = tmp_path / "secret"
    outside_dir.mkdir()
    outside_file = outside_dir / "id_rsa"
    outside_file.write_text("secret")
    link = watch_dir / "escape_link"
    link.symlink_to(outside_file)
    detector = _make_scope_detector(watch_dir)

    _run_read_loop_once(detector, [_make_raw_event(str(link))])

    assert detector._raw_queue.qsize() == 1
    assert detector.out_of_scope_drops == 0


# ── 4.2 out_of_scope_drops en el heartbeat ────────────────────────────────────

def _make_heartbeat_config() -> MagicMock:
    cfg = MagicMock()
    cfg.agent_id = "agent-hb-scope-test"
    return cfg


@pytest.mark.asyncio
async def test_heartbeat_payload_includes_out_of_scope_drops() -> None:
    detector = MagicMock()
    detector.event_drops = 3
    detector.out_of_scope_drops = 7
    detector.hardlink_suspected = 0

    queue = MagicMock()
    queue.queue_size = 0
    queue.queue_pressure = 0.0
    state = MagicMock()
    state.ruleset_version = 1
    client = MagicMock()
    client.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=_make_heartbeat_config(),
        queue=queue,
        state=state,
        client=client,
        detector=detector,
    )
    await hb._publish(False)

    data = json.loads(client.xadd.call_args[0][1]["data"])
    assert data["out_of_scope_drops"] == 7


@pytest.mark.asyncio
async def test_heartbeat_payload_is_signed_and_verifiable() -> None:
    """El heartbeat va firmado con HMAC y el backend puede verificarlo.

    Regresión: el heartbeat se publicaba SIN el campo 'signature', así que el
    heartbeat_consumer del backend lo descartaba (invalid_signature) y marcaba al
    agente offline pese a estar sano. Ahora, con shared_secret inyectado, el
    payload lleva firma verificable con el mismo contrato que el backend.
    """
    from agent.streams import verify_payload

    secret = b"s" * 32
    queue = MagicMock()
    queue.queue_size = 0
    queue.queue_pressure = 0.0
    state = MagicMock()
    state.ruleset_version = 1
    client = MagicMock()
    client.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=_make_heartbeat_config(),
        queue=queue,
        state=state,
        client=client,
        shared_secret=secret,
    )
    await hb._publish(False)

    data = json.loads(client.xadd.call_args[0][1]["data"])
    assert "signature" in data
    assert verify_payload(secret, data) is True
    # La firma es real (no un placeholder): con otro secreto NO verifica.
    assert verify_payload(b"other-secret-32-bytes-long-xxxxx", data) is False


@pytest.mark.asyncio
async def test_heartbeat_out_of_scope_drops_zero_without_detector() -> None:
    queue = MagicMock()
    queue.queue_size = 0
    queue.queue_pressure = 0.0
    state = MagicMock()
    state.ruleset_version = 1
    client = MagicMock()
    client.xadd = AsyncMock(return_value="1-0")

    hb = HeartbeatPublisher(
        config=_make_heartbeat_config(),
        queue=queue,
        state=state,
        client=client,
        detector=None,
    )
    await hb._publish(False)

    data = json.loads(client.xadd.call_args[0][1]["data"])
    assert data["out_of_scope_drops"] == 0
