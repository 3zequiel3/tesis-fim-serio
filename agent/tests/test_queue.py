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
    assert loaded["event_id"] == "e3"


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
