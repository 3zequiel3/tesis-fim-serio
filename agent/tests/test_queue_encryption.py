"""Tests de cifrado en reposo de la cola offline y del descarte (Change 53,
D63/RN-157). Cubre tasks.md sección 6.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import structlog

from agent.baseline import derive_baseline_key
from agent.queue import (
    _MAGIC_VERSION,
    EventQueue,
    QueueFileUnreadable,
    _iso_to_epoch_ms,
    derive_queue_key,
    read_queue_file,
)
from agent.quarantine import derive_quarantine_key
from agent.tests.conftest import TEST_AGENT_ID, TEST_MASTER_SECRET, decrypt_queue_file


def _make_event(
    event_id: str,
    detected_at: str | None = None,
    *,
    diff_text: str | None = "-old line\n+new line",
    path: str = "/etc/passwd",
) -> dict:
    if detected_at is None:
        detected_at = datetime.now(timezone.utc).isoformat()
    return {
        "event_id": event_id,
        "detected_at": detected_at,
        "path": path,
        "hash_detected": "abc123",
        "schema_version": 1,
        "diff_text": diff_text,
        "process_pid": 4242,
        "process_uid": 0,
        "process_exe": "/usr/bin/vim",
    }


@pytest.fixture()
def queue(tmp_path: Path) -> EventQueue:
    return EventQueue(
        tmp_path / "queue",
        master_secret=TEST_MASTER_SECRET,
        agent_id=TEST_AGENT_ID,
        discard_dir=tmp_path / "discarded",
    )


def _all_bytes(directory: Path) -> bytes:
    combined = b""
    for f in sorted(directory.glob("*.json")):
        combined += f.read_bytes()
    return combined


# ── 6.1 — Sin contenido legible en la cola ─────────────────────────────────


def test_queue_file_never_contains_readable_content(queue: EventQueue) -> None:
    evt = _make_event("e1", diff_text="-secret before\n+secret after", path="/etc/shadow")
    path = queue.enqueue(evt)
    raw = path.read_bytes()

    assert raw.startswith(_MAGIC_VERSION)
    assert b"secret before" not in raw
    assert b"secret after" not in raw
    assert b"/etc/shadow" not in raw
    assert b"diff_text" not in raw

    entries = queue.iter_entries()
    assert len(entries) == 1
    assert entries[0]["payload"] == evt


# ── 6.2 — Sin contenido legible en el descarte ─────────────────────────────


def test_discard_record_never_contains_readable_content(queue: EventQueue) -> None:
    evt = _make_event("d1", diff_text="-line a\n+line b")
    queue.enqueue(evt)
    assert queue.discard("d1", "clock_skew") is True

    discarded = list(queue._discard_dir.glob("*.json"))
    assert len(discarded) == 1
    raw = discarded[0].read_bytes()
    assert raw.startswith(_MAGIC_VERSION)
    assert b"line a" not in raw
    assert b"line b" not in raw
    assert b"discard_reason" not in raw
    assert b"clock_skew" not in raw

    record = decrypt_queue_file(discarded[0])
    assert record["payload"]["event_id"] == "d1"
    assert record["discard_reason"] == "clock_skew"
    assert record["discarded_at"] is not None


# ── 6.3 — Flujo completo sin contenido legible en disco ────────────────────


def test_full_lifecycle_leaves_no_readable_content(queue: EventQueue) -> None:
    queue.enqueue(_make_event("e2", diff_text="-alpha\n+beta"))
    queue.enqueue(_make_event("e3", diff_text="-gamma\n+delta"))
    queue.bump_attempts("e2")
    queue.discard("e2", "invalid_schema")
    queue.remove("e3")

    for directory in (queue._dir, queue._discard_dir):
        for f in directory.glob("*.json"):
            raw = f.read_bytes()
            assert b"alpha" not in raw
            assert b"beta" not in raw
            assert b"gamma" not in raw
            assert b"delta" not in raw
            assert b"diff_text" not in raw


# ── 6.4 — Nonce distinto en cada escritura ─────────────────────────────────


def test_bump_attempts_uses_a_fresh_nonce_each_time(queue: EventQueue) -> None:
    path = queue.enqueue(_make_event("e4"))
    queue.bump_attempts("e4")
    first_nonce = path.read_bytes()[len(_MAGIC_VERSION) : len(_MAGIC_VERSION) + 12]
    queue.bump_attempts("e4")
    second_nonce = path.read_bytes()[len(_MAGIC_VERSION) : len(_MAGIC_VERSION) + 12]
    assert first_nonce != second_nonce


# ── 6.5 — Separación de claves ─────────────────────────────────────────────


def test_queue_key_is_separated_from_baseline_and_quarantine_keys() -> None:
    queue_key = derive_queue_key(TEST_MASTER_SECRET, TEST_AGENT_ID)
    baseline_key = derive_baseline_key(TEST_MASTER_SECRET, TEST_AGENT_ID)
    quarantine_key = derive_quarantine_key(TEST_MASTER_SECRET, TEST_AGENT_ID)

    assert queue_key != baseline_key
    assert queue_key != quarantine_key
    assert baseline_key != quarantine_key

    other_agent_key = derive_queue_key(TEST_MASTER_SECRET, "another-agent")
    assert other_agent_key != queue_key


def test_derive_queue_key_rejects_wrong_length_secret() -> None:
    with pytest.raises(ValueError):
        derive_queue_key(b"too-short", TEST_AGENT_ID)
    with pytest.raises(ValueError):
        derive_queue_key(os.urandom(31), TEST_AGENT_ID)
    with pytest.raises(ValueError):
        derive_queue_key(os.urandom(33), TEST_AGENT_ID)


# ── 6.6 — Migración de cola en claro ───────────────────────────────────────


def test_legacy_plaintext_queue_is_migrated_on_open(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True)

    envelope_evt = _make_event("legacy-envelope", "2026-01-01T00:00:00+00:00")
    envelope_file = queue_dir / f"{_iso_to_epoch_ms(envelope_evt['detected_at']):016d}_legacy-envelope.json"
    envelope_file.write_text(json.dumps({
        "payload": envelope_evt,
        "attempts": 3,
        "first_attempt_at": "2026-01-01T00:00:01+00:00",
    }))

    bare_evt = _make_event("legacy-bare", "2026-01-02T00:00:00+00:00")
    bare_file = queue_dir / f"{_iso_to_epoch_ms(bare_evt['detected_at']):016d}_legacy-bare.json"
    bare_file.write_text(json.dumps(bare_evt))

    q = EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID)

    assert envelope_file.read_bytes().startswith(_MAGIC_VERSION)
    assert bare_file.read_bytes().startswith(_MAGIC_VERSION)
    assert q.get_attempts("legacy-envelope") == 3
    assert q.get_attempts("legacy-bare") == 0

    drained = [e["event_id"] for e in q.iter_fifo()]
    assert drained == ["legacy-envelope", "legacy-bare"]


# ── 6.7 — Migración del descarte en claro ──────────────────────────────────


def test_legacy_plaintext_discard_is_migrated_on_open(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    discard_dir = tmp_path / "discarded"
    discard_dir.mkdir(parents=True)

    evt = _make_event("legacy-discarded", "2026-01-01T00:00:00+00:00")
    record = {
        "payload": evt,
        "attempts": 1,
        "first_attempt_at": "2026-01-01T00:00:01+00:00",
        "discard_reason": "max_attempts_exceeded",
        "discarded_at": "2026-01-01T00:00:02+00:00",
    }
    discard_file = discard_dir / f"{_iso_to_epoch_ms(evt['detected_at']):016d}_legacy-discarded.json"
    discard_file.write_text(json.dumps(record))

    EventQueue(
        queue_dir,
        master_secret=TEST_MASTER_SECRET,
        agent_id=TEST_AGENT_ID,
        discard_dir=discard_dir,
        max_discard_files=5,
    )

    assert discard_file.read_bytes().startswith(_MAGIC_VERSION)
    assert len(list(discard_dir.glob("*.json"))) == 1


# ── 6.8 — Migración fallida no pierde el evento ────────────────────────────


def test_failed_migration_rewrite_keeps_event_plaintext_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True)
    evt = _make_event("legacy-fails", "2026-01-01T00:00:00+00:00")
    legacy_file = queue_dir / f"{_iso_to_epoch_ms(evt['detected_at']):016d}_legacy-fails.json"
    legacy_file.write_text(json.dumps({"payload": evt, "attempts": 0, "first_attempt_at": None}))

    import agent.queue as qmod

    original = qmod._atomic_write_envelope

    def _failing_write(key: bytes, final: Path, data_obj: dict) -> None:
        if final == legacy_file:
            raise OSError("simulated disk failure")
        original(key, final, data_obj)

    monkeypatch.setattr(qmod, "_atomic_write_envelope", _failing_write)

    q = EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID)

    raw = legacy_file.read_bytes()
    assert not raw.startswith(_MAGIC_VERSION)
    assert json.loads(raw)["payload"]["event_id"] == "legacy-fails"
    assert q.contains("legacy-fails")

    monkeypatch.setattr(qmod, "_atomic_write_envelope", original)
    q2 = EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID)
    assert legacy_file.read_bytes().startswith(_MAGIC_VERSION)
    assert q2.contains("legacy-fails")


# ── 6.9 — Idempotencia ──────────────────────────────────────────────────────


def test_second_startup_over_encrypted_queue_rewrites_nothing(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    q = EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID)
    path = q.enqueue(_make_event("stable"))
    before = path.read_bytes()

    EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID)

    after = path.read_bytes()
    assert before == after


# ── 6.10 — Byte alterado ⇒ ilegible ─────────────────────────────────────────


def test_tampered_ciphertext_is_skipped_and_logged(queue: EventQueue) -> None:
    t1, t2, t3 = (
        "2026-01-01T00:00:00+00:00",
        "2026-01-02T00:00:00+00:00",
        "2026-01-03T00:00:00+00:00",
    )
    queue.enqueue(_make_event("first", t1))
    second_path = queue.enqueue(_make_event("second", t2))
    queue.enqueue(_make_event("third", t3))

    raw = bytearray(second_path.read_bytes())
    raw[-1] ^= 0xFF
    second_path.write_bytes(bytes(raw))

    with structlog.testing.capture_logs() as captured:
        entries = queue.iter_entries()

    ids = [e["payload"]["event_id"] for e in entries]
    assert ids == ["first", "third"]

    unreadable_logs = [r for r in captured if r.get("event") == "queue.unreadable_file"]
    assert len(unreadable_logs) == 1
    assert unreadable_logs[0]["event_id"] == "second"
    assert unreadable_logs[0]["reason"] == "authentication_failed"
    for r in captured:
        serialized = json.dumps(r, default=str)
        assert "diff_text" not in serialized

    assert queue.get_attempts("second") == 0
    assert queue.bump_attempts("second") == 0
    assert second_path.read_bytes() == bytes(raw)


# ── 6.11 — Truncado y magic-sin-decifrar ────────────────────────────────────


def test_truncated_file_is_malformed(queue: EventQueue) -> None:
    path = queue.enqueue(_make_event("trunc"))
    path.write_bytes(_MAGIC_VERSION + b"\x00" * 4)  # menos que magic+nonce+tag

    with structlog.testing.capture_logs() as captured:
        entries = queue.iter_entries()

    assert entries == []
    logs = [r for r in captured if r.get("event") == "queue.unreadable_file"]
    assert len(logs) == 1
    assert logs[0]["reason"] == "malformed"


def test_magic_prefixed_json_is_not_reinterpreted_as_plaintext(queue: EventQueue) -> None:
    path = queue.enqueue(_make_event("fakemagic"))
    fake = _MAGIC_VERSION + json.dumps({"payload": {"event_id": "fakemagic"}}).encode()
    path.write_bytes(fake)

    entries = queue.iter_entries()
    assert entries == []
    # No se reescribe como si fuera legacy en claro: sigue empezando con el magic.
    assert path.read_bytes() == fake


# ── 6.12 — Clave distinta ───────────────────────────────────────────────────


def test_wrong_master_secret_never_authenticates_or_rewrites(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    q1 = EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID)
    path = q1.enqueue(_make_event("owned"))
    before = path.read_bytes()

    other_secret = os.urandom(32)
    q2 = EventQueue(queue_dir, master_secret=other_secret, agent_id=TEST_AGENT_ID)

    assert q2.iter_entries() == []
    assert q2.get_attempts("owned") == 0
    assert path.read_bytes() == before


# ── 6.13 — Nombre cambiado ───────────────────────────────────────────────────


def test_renamed_blob_does_not_authenticate(queue: EventQueue) -> None:
    path_a = queue.enqueue(_make_event("evt-a"))
    path_b = queue.enqueue(_make_event("evt-b"))

    swapped_bytes = path_a.read_bytes()
    path_b.write_bytes(swapped_bytes)

    with pytest.raises(QueueFileUnreadable) as excinfo:
        read_queue_file(path_b, queue._key)
    assert excinfo.value.reason == "authentication_failed"


# ── 6.14 — Presupuesto sobre bytes en disco ─────────────────────────────────


def test_budget_and_pressure_reflect_encrypted_disk_size(tmp_path: Path) -> None:
    import agent.queue as qmod

    original = qmod._MAX_BYTES
    try:
        qmod._MAX_BYTES = 200
        q = EventQueue(
            tmp_path / "queue", master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID
        )
        q.enqueue(_make_event("budget-1", "2026-01-01T00:00:00+00:00"))
        pressure_before = q.queue_pressure
        assert pressure_before > 0
        q.enqueue(_make_event("budget-2", "2026-01-02T00:00:00+00:00"))
        assert q.evicted_events == 1
        assert q._total_bytes() == sum(f.stat().st_size for f in q._dir.glob("*.json"))
    finally:
        qmod._MAX_BYTES = original


# ── 6.15 — Construcción sin clave ───────────────────────────────────────────


def test_construction_without_master_secret_creates_nothing(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    with pytest.raises(TypeError):
        EventQueue(queue_dir, agent_id=TEST_AGENT_ID)  # type: ignore[call-arg]
    assert not queue_dir.exists()


def test_construction_without_agent_id_creates_nothing(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    with pytest.raises(TypeError):
        EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET)  # type: ignore[call-arg]
    assert not queue_dir.exists()


def test_construction_with_invalid_master_secret_length_creates_nothing(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    with pytest.raises(ValueError):
        EventQueue(queue_dir, master_secret=b"short", agent_id=TEST_AGENT_ID)
    assert not queue_dir.exists()


# ── 6.16 — Arranque sin master_secret no toca archivos preexistentes ────────


def test_missing_master_secret_leaves_preexisting_files_untouched(tmp_path: Path) -> None:
    """Simula la secuencia de __main__.py: load_master_secret() falla antes
    de construir EventQueue. Un archivo preexistente (de una corrida previa
    con master_secret válido) debe quedar byte a byte igual."""
    queue_dir = tmp_path / "queue"
    q = EventQueue(queue_dir, master_secret=TEST_MASTER_SECRET, agent_id=TEST_AGENT_ID)
    path = q.enqueue(_make_event("untouched"))
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    from agent.baseline import load_master_secret

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        load_master_secret(secrets_dir)  # el arranque termina acá, sin abrir la cola

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime
