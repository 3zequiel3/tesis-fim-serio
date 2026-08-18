"""Tests de la cola offline durable del agente FIM (Change 08, task 9.1)."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.queue import EventQueue, _MAX_BYTES


def _make_event(event_id: str, detected_at: str | None = None) -> dict:
    if detected_at is None:
        detected_at = datetime.now(timezone.utc).isoformat()
    return {
        "event_id": event_id,
        "detected_at": detected_at,
        "path": "/etc/passwd",
        "hash_detected": "abc123",
        "schema_version": 1,
    }


@pytest.fixture()
def queue(tmp_path: Path) -> EventQueue:
    return EventQueue(tmp_path / "queue")


# ── Escritura atómica ─────────────────────────────────────────────────────────

def test_enqueue_creates_json_file(queue: EventQueue) -> None:
    evt = _make_event("e1")
    path = queue.enqueue(evt)
    assert path.exists()
    assert path.suffix == ".json"
    assert path.name.endswith(f"_e1.json")


def test_enqueue_no_tmp_after_write(queue: EventQueue) -> None:
    queue.enqueue(_make_event("e2"))
    tmps = list(queue._dir.glob("*.tmp"))
    assert tmps == []


def test_enqueue_content_roundtrip(queue: EventQueue) -> None:
    evt = _make_event("e3")
    path = queue.enqueue(evt)
    loaded = json.loads(path.read_bytes())
    # D-7: el archivo guarda un sobre {payload, attempts, first_attempt_at},
    # no el payload desnudo.
    assert loaded["payload"]["event_id"] == "e3"
    assert loaded["attempts"] == 0
    assert loaded["first_attempt_at"] is None


# ── FIFO ─────────────────────────────────────────────────────────────────────

def test_iter_fifo_order(queue: EventQueue) -> None:
    # t1 < t2: e1 debe salir antes que e2
    t1 = "2026-01-01T00:00:00+00:00"
    t2 = "2026-01-02T00:00:00+00:00"
    queue.enqueue(_make_event("e2", t2))
    queue.enqueue(_make_event("e1", t1))

    events = queue.iter_fifo()
    assert [e["event_id"] for e in events] == ["e1", "e2"]


# ── remove ────────────────────────────────────────────────────────────────────

def test_remove_existing(queue: EventQueue) -> None:
    queue.enqueue(_make_event("r1"))
    assert queue.queue_size == 1
    assert queue.remove("r1") is True
    assert queue.queue_size == 0


def test_remove_nonexistent_returns_false(queue: EventQueue) -> None:
    assert queue.remove("ghost") is False


# ── drop-oldest a 100 MB ───────────────────────────────────────────────────────

def test_drop_oldest_on_limit(queue: EventQueue) -> None:
    """Cuando agregar un evento supera 100 MB se borra el más antiguo."""
    # Forzamos _MAX_BYTES pequeño creando archivos que casi llenen el límite
    # Usamos monkeypatching de la constante para hacer el test manejable
    import agent.queue as qmod
    original = qmod._MAX_BYTES
    try:
        qmod._MAX_BYTES = 200  # límite tiny para el test

        # Primer evento (~150 bytes) ocupa la mayoría del límite
        q = EventQueue(queue._dir)
        e1 = _make_event("oldest", "2026-01-01T00:00:00+00:00")
        q.enqueue(e1)
        size_after_e1 = q._total_bytes()
        assert size_after_e1 > 0

        # Segundo evento empuja sobre el límite → e1 debe borrarse
        e2 = _make_event("newer", "2026-01-02T00:00:00+00:00")
        q.enqueue(e2)

        ids = {e["event_id"] for e in q.iter_fifo()}
        assert "newer" in ids
        assert "oldest" not in ids
    finally:
        qmod._MAX_BYTES = original


# ── queue_pressure ─────────────────────────────────────────────────────────────

def test_queue_pressure_zero_when_empty(queue: EventQueue) -> None:
    assert queue.queue_pressure == 0.0


def test_queue_pressure_positive_after_enqueue(queue: EventQueue) -> None:
    queue.enqueue(_make_event("p1"))
    assert 0.0 < queue.queue_pressure <= 1.0


# ── barrido de .tmp huérfanos ─────────────────────────────────────────────────

def test_sweep_orphaned_tmp_on_init(tmp_path: Path) -> None:
    qdir = tmp_path / "queue"
    qdir.mkdir()
    orphan = qdir / "1234_abc.json.tmp"
    orphan.write_text("{}")
    assert orphan.exists()

    EventQueue(qdir)  # __init__ barre los .tmp

    assert not orphan.exists()


# ── H1: regresión zero-pad y sort robusto ─────────────────────────────────────

def test_enqueue_filename_zero_padded(queue: EventQueue) -> None:
    """El nombre de archivo usa zero-pad a 16 dígitos en el prefijo timestamp."""
    path = queue.enqueue(_make_event("pad-e1", "2026-01-01T00:00:00+00:00"))
    # El stem tiene la forma {16 dígitos}_{uuid}
    stem = path.stem
    prefix = stem.split("_", 1)[0]
    assert len(prefix) == 16
    assert prefix.isdigit()


def test_json_files_sorts_mixed_legacy_padded(queue: EventQueue) -> None:
    """_json_files ordena correctamente con timestamps de longitud distinta (legacy y padded)."""
    qdir = queue._dir
    # Simula un archivo legacy con timestamp de 13 dígitos (enero 2026)
    legacy_ts = 1751260800000  # 13 dígitos
    # Simula un archivo padded con timestamp más reciente (16 dígitos)
    padded_ts = 1751260900000
    old_id = "aaaaaaaa-0000-0000-0000-000000000001"
    new_id = "aaaaaaaa-0000-0000-0000-000000000002"
    # Escribe primero el más nuevo para verificar que el sort no depende del orden de glob
    (qdir / f"{padded_ts:016d}_{new_id}.json").write_text("{}")
    (qdir / f"{legacy_ts}_{old_id}.json").write_text("{}")

    files = queue._json_files()
    prefixes = [int(f.stem.split("_", 1)[0]) for f in files]
    assert prefixes == sorted(prefixes), "Los archivos deben estar en orden cronológico ascendente"
    assert prefixes[0] == legacy_ts
    assert prefixes[1] == padded_ts


def test_drop_oldest_removes_chronologically_oldest(queue: EventQueue) -> None:
    """Bajo presión de capacidad, drop-oldest borra el evento más viejo (no el más nuevo).

    El límite se fija en 1 byte para garantizar que cualquier evento nuevo provoque
    la eliminación del anterior, independientemente del tamaño real del payload.
    """
    import agent.queue as qmod
    original = qmod._MAX_BYTES
    try:
        # 1 byte: cualquier evento nuevo supera el límite y dispara drop-oldest
        qmod._MAX_BYTES = 1
        q = EventQueue(queue._dir)

        t_old = "2026-01-01T00:00:00+00:00"
        t_new = "2026-06-01T00:00:00+00:00"
        q.enqueue(_make_event("oldest-event", t_old))
        q.enqueue(_make_event("newest-event", t_new))

        ids = {e["event_id"] for e in q.iter_fifo()}
        assert "newest-event" in ids
        assert "oldest-event" not in ids
    finally:
        qmod._MAX_BYTES = original


def test_iter_fifo_oldest_first(queue: EventQueue) -> None:
    """iter_fifo devuelve los eventos en orden oldest-first (FIFO estricto)."""
    times = [
        "2026-03-01T00:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
        "2026-06-01T00:00:00+00:00",
    ]
    ids = ["mid", "oldest", "newest"]
    for eid, ts in zip(ids, times):
        queue.enqueue(_make_event(eid, ts))

    events = queue.iter_fifo()
    result_ids = [e["event_id"] for e in events]
    assert result_ids == ["oldest", "mid", "newest"]
