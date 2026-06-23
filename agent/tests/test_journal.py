"""Tests de JournalManager (C10 + C23-H2: atomicidad e integridad HMAC)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.journal import JournalEntry, JournalManager

_SECRET = b"test-shared-secret-32bytes-xxxxx"


def _make_manager(tmp_path: Path, secret: bytes = _SECRET) -> JournalManager:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    return JournalManager(journal_dir, secret)


# ── Tests básicos (C10) ───────────────────────────────────────────────────────

def test_journal_write_pending(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    entry = mgr.write_pending("evt-001", "/etc/hosts", "auto_restore")

    assert entry.state == "pending"
    assert entry.event_id == "evt-001"
    assert entry.action == "auto_restore"

    p = tmp_path / "journal" / "evt-001.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["state"] == "pending"
    assert data["path"] == "/etc/hosts"
    # El HMAC debe estar presente tras la escritura
    assert data["hmac"] is not None


def test_journal_mark_completed(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-002", "/etc/passwd", "quarantine")
    mgr.mark_completed("evt-002")

    data = json.loads((tmp_path / "journal" / "evt-002.json").read_text())
    assert data["state"] == "completed"
    assert data["updated_at"] >= data["created_at"]


def test_journal_mark_failed(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-003", "/opt/app.py", "auto_restore")
    mgr.mark_failed("evt-003", "no_baseline_content")

    data = json.loads((tmp_path / "journal" / "evt-003.json").read_text())
    assert data["state"] == "failed"
    assert data["error"] == "no_baseline_content"


def test_journal_load_pending(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-010", "/a", "auto_restore")
    mgr.write_pending("evt-011", "/b", "alert_only")
    mgr.mark_completed("evt-011")  # este no debe aparecer

    pending = mgr.load_pending()
    assert len(pending) == 1
    assert pending[0].event_id == "evt-010"


def test_journal_delete(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-020", "/x", "quarantine")

    p = tmp_path / "journal" / "evt-020.json"
    assert p.exists()
    mgr.delete("evt-020")
    assert not p.exists()


# ── H2: regresión atomicidad e integridad HMAC ────────────────────────────────

def test_journal_hmac_valid_roundtrip(tmp_path: Path) -> None:
    """Entrada escrita con HMAC válido se lee correctamente."""
    mgr = _make_manager(tmp_path)
    mgr.write_pending("hmac-ok", "/etc/shadow", "auto_restore")

    # _read debe devolver la entrada sin problemas
    entry = mgr._read("hmac-ok")
    assert entry is not None
    assert entry.event_id == "hmac-ok"
    assert entry.hmac is not None


def test_journal_tampered_content_discarded(tmp_path: Path) -> None:
    """Entrada con contenido modificado (HMAC inválido) se descarta silenciosamente."""
    mgr = _make_manager(tmp_path)
    mgr.write_pending("tampered", "/var/log/syslog", "alert_only")

    p = tmp_path / "journal" / "tampered.json"
    data = json.loads(p.read_text())
    # Modificar el estado sin recalcular el HMAC
    data["state"] = "completed"
    p.write_text(json.dumps(data))

    entry = mgr._read("tampered")
    assert entry is None


def test_journal_truncated_entry_skipped_in_load_pending(tmp_path: Path) -> None:
    """Entrada truncada (simula muerte de proceso a mitad de escritura) se descarta en load_pending."""
    mgr = _make_manager(tmp_path)
    # Simula un .json truncado (contenido inválido)
    truncated = tmp_path / "journal" / "truncated-evt.json"
    truncated.write_bytes(b'{"event_id": "truncated-evt", "path": "/x"')  # JSON incompleto

    pending = mgr.load_pending()
    ids = [e.event_id for e in pending]
    assert "truncated-evt" not in ids


def test_journal_atomic_write_survives_and_rehydrates(tmp_path: Path) -> None:
    """Entrada escrita atómicamente sobrevive a una re-instanciación del manager."""
    mgr = _make_manager(tmp_path)
    mgr.write_pending("atomic-evt", "/etc/crontab", "auto_restore")

    # Nueva instancia del manager (simula restart)
    mgr2 = JournalManager(tmp_path / "journal", _SECRET)
    pending = mgr2.load_pending()

    assert len(pending) == 1
    assert pending[0].event_id == "atomic-evt"


def test_journal_missing_hmac_discarded(tmp_path: Path) -> None:
    """Entrada sin campo hmac (escrita por versión legacy) se descarta."""
    mgr = _make_manager(tmp_path)
    # Escribir manualmente un JSON sin hmac (formato previo al fix H2)
    legacy = tmp_path / "journal" / "legacy-evt.json"
    legacy.write_text(json.dumps({
        "event_id": "legacy-evt",
        "path": "/etc/hosts",
        "action": "auto_restore",
        "state": "pending",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "error": None,
    }))

    pending = mgr.load_pending()
    ids = [e.event_id for e in pending]
    assert "legacy-evt" not in ids


def test_journal_wiring_receives_correct_secret(tmp_path: Path) -> None:
    """JournalManager recibe el secreto correcto y lo usa para verificar HMAC."""
    secret_a = b"secret-A-32-bytes-xxxxxxxxxxxxxx"
    secret_b = b"secret-B-32-bytes-yyyyyyyyyyyyyy"

    mgr_a = JournalManager(tmp_path / "journal", secret_a)
    (tmp_path / "journal").mkdir(exist_ok=True)
    mgr_a.write_pending("cross-secret", "/tmp/test", "alert_only")

    # Manager con secreto diferente no debe poder leer la entrada
    mgr_b = JournalManager(tmp_path / "journal", secret_b)
    entry = mgr_b._read("cross-secret")
    assert entry is None

    # Manager con el secreto correcto sí puede
    mgr_a2 = JournalManager(tmp_path / "journal", secret_a)
    entry_ok = mgr_a2._read("cross-secret")
    assert entry_ok is not None
    assert entry_ok.event_id == "cross-secret"
