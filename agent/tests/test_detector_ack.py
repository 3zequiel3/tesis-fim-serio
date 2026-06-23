"""Tests del índice inverso _event_to_path y on_ack O(1) en FanotifyDetector (C21/C4)."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.detector import FanotifyDetector, FanotifyEvent


def _make_detector(tmp_path: Path) -> FanotifyDetector:
    baseline = MagicMock()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0
    stop_event = asyncio.Event()
    return FanotifyDetector(
        agent_id="agent-01",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=stop_event,
    )


# ── Invariante de los dos mapas ───────────────────────────────────────────────

def test_initial_state_both_maps_empty(tmp_path: Path) -> None:
    detector = _make_detector(tmp_path)
    assert detector._pending == {}
    assert detector._event_to_path == {}


@pytest.mark.asyncio
async def test_process_event_populates_reverse_index(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_bytes(b"content")
    detector = _make_detector(tmp_path)
    detector._baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(f), pid=100, uid=0, exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    event_id = detector._pending.get(str(f))
    assert event_id is not None
    assert detector._event_to_path.get(event_id) == str(f)


@pytest.mark.asyncio
async def test_superseded_event_removed_from_reverse_index(tmp_path: Path) -> None:
    """Cuando el mismo path genera dos eventos, el stale event_id se elimina del índice."""
    f = tmp_path / "file.txt"
    f.write_bytes(b"v1")
    detector = _make_detector(tmp_path)
    detector._baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(f), pid=100, uid=0, exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )

    # Primer evento
    await detector._process_event(fan_event)
    first_event_id = detector._pending[str(f)]
    assert first_event_id in detector._event_to_path

    # Segundo evento — escribe diferente contenido para que no se descarte
    f.write_bytes(b"v2")
    entry_mock = MagicMock()
    entry_mock.hash = hashlib.sha256(b"v1").hexdigest()
    entry_mock.content_b64 = None
    entry_mock.oversize = False
    detector._baseline.read_entry.return_value = entry_mock

    await detector._process_event(fan_event)
    second_event_id = detector._pending[str(f)]

    # El primer event_id ya no está en el índice inverso
    assert first_event_id not in detector._event_to_path
    # El segundo sí
    assert second_event_id in detector._event_to_path
    assert detector._event_to_path[second_event_id] == str(f)


# ── on_ack O(1) ───────────────────────────────────────────────────────────────

def test_on_ack_removes_forward_and_reverse(tmp_path: Path) -> None:
    detector = _make_detector(tmp_path)
    detector._pending["/etc/hosts"] = "event-abc"
    detector._event_to_path["event-abc"] = "/etc/hosts"

    detector.on_ack("event-abc")

    assert "/etc/hosts" not in detector._pending
    assert "event-abc" not in detector._event_to_path


def test_on_ack_unknown_event_is_safe_noop(tmp_path: Path) -> None:
    detector = _make_detector(tmp_path)
    detector._pending["/etc/hosts"] = "event-abc"
    detector._event_to_path["event-abc"] = "/etc/hosts"

    detector.on_ack("event-unknown")  # no debe lanzar ni modificar el estado

    assert "/etc/hosts" in detector._pending
    assert "event-abc" in detector._event_to_path


def test_on_ack_multiple_paths_only_removes_target(tmp_path: Path) -> None:
    detector = _make_detector(tmp_path)
    detector._pending["/etc/hosts"] = "event-abc"
    detector._event_to_path["event-abc"] = "/etc/hosts"
    detector._pending["/etc/passwd"] = "event-xyz"
    detector._event_to_path["event-xyz"] = "/etc/passwd"

    detector.on_ack("event-abc")

    assert "/etc/hosts" not in detector._pending
    assert "event-abc" not in detector._event_to_path
    # El otro path queda intacto
    assert "/etc/passwd" in detector._pending
    assert "event-xyz" in detector._event_to_path


def test_on_ack_stale_event_id_no_forward_removal(tmp_path: Path) -> None:
    """
    Si el path ya fue superseded por un nuevo evento, ackear el event_id viejo
    no debe eliminar el forward entry del nuevo evento.
    """
    detector = _make_detector(tmp_path)
    # El path ahora tiene event-new como evento actual
    detector._pending["/etc/hosts"] = "event-new"
    detector._event_to_path["event-new"] = "/etc/hosts"
    # event-old ya no está en el índice inverso (fue limpiado al superse)

    # Ack tardío de un event_id que ya no está en el índice — debe ser no-op
    detector.on_ack("event-old")

    assert detector._pending["/etc/hosts"] == "event-new"
    assert detector._event_to_path["event-new"] == "/etc/hosts"


@pytest.mark.asyncio
async def test_interleaved_acks_and_new_events_stay_consistent(tmp_path: Path) -> None:
    """
    Interleave de on_ack y _process_event en el mismo loop:
    los dos mapas permanecen consistentes y no hay RuntimeError.
    """
    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f1.write_bytes(b"a")
    f2.write_bytes(b"b")

    detector = _make_detector(tmp_path)
    detector._baseline.read_entry.return_value = None

    ev1 = FanotifyEvent(path=str(f1), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00")
    ev2 = FanotifyEvent(path=str(f2), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00")

    await detector._process_event(ev1)
    eid1 = detector._pending[str(f1)]

    await detector._process_event(ev2)
    eid2 = detector._pending[str(f2)]

    # Ack el primero mientras el segundo aún está pendiente
    detector.on_ack(eid1)
    assert str(f1) not in detector._pending
    assert eid1 not in detector._event_to_path
    assert detector._pending[str(f2)] == eid2
    assert detector._event_to_path[eid2] == str(f2)

    # Ack el segundo
    detector.on_ack(eid2)
    assert detector._pending == {}
    assert detector._event_to_path == {}
