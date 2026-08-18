"""
Test de contrato cross-boundary: DetectedChange.to_event_data() → payload real (C35 / FIX-01).

Este es el test que faltaba: los tests anteriores mockeaban `to_event_data()`
(`change = MagicMock(); change.to_event_data.return_value = {...}`) con las claves
ya correctas a mano, por lo que nunca ejercitaban la serialización real del
dataclass `DetectedChange`. Ese gap dejó pasar el bug donde el dataclass emitía
`current_hash`/`previous_hash` mientras el backend leía `hash_detected`/
`hash_expected` (RN-71), y todo evento real persistía con `hash_detected == ""`.

Este test construye un `DetectedChange` real, llama al `to_event_data()` real
(sin mocks), y verifica que el dict resultante habla el léxico canónico que
consume `backend/app/modules/events/service.py:210`
(`event_data.get("hash_detected") or ""`).

D35/RN-129 (C40) agrega dos tests más: que el vocabulario de claves que
`to_event_data()` emite no incluye `action`/`action_failed` (esas las agrega
`DecisionEngine.evaluate_and_act`, no el dataclass), y que `event_type`
conserva su vocabulario declarado (`file_modified | file_absent |
file_deleted | file_created`, RN-71) incluso cuando la acción real ejecutada
es `auto_restore` — la sobrescritura `payload["event_type"] = "auto_restored"`
fue eliminada de `agent/decision.py::_auto_restore`.
"""
from __future__ import annotations

import base64
import hashlib
import os
from unittest.mock import MagicMock

from agent.decision import DecisionEngine
from agent.detector import DetectedChange
from agent.journal import JournalManager
from agent.rules import RulesCache


def test_to_event_data_emits_canonical_hash_keys() -> None:
    """to_event_data() real debe emitir hash_detected/hash_expected, no current_hash/previous_hash."""
    detected_hash = "a" * 64  # sha256 hex simulado
    expected_hash = "b" * 64

    change = DetectedChange(
        event_id="test-contract-001",
        path="/etc/passwd",
        event_type="file_modified",
        operation_type="file_modified",
        hash_expected=expected_hash,
        hash_detected=detected_hash,
        diff_text=None,
        process_pid=123,
        process_uid=0,
        process_exe="/usr/bin/vim",
        detected_at="2026-07-02T00:00:00+00:00",
        parent_event_id=None,
    )

    payload = change.to_event_data()

    # La clave que backend/app/modules/events/service.py:172 realmente lee.
    assert "hash_detected" in payload
    assert payload["hash_detected"] == detected_hash
    assert payload["hash_detected"] != ""

    assert "hash_expected" in payload
    assert payload["hash_expected"] == expected_hash

    # El bug original emitía estas claves en su lugar — deben haber desaparecido.
    assert "current_hash" not in payload
    assert "previous_hash" not in payload


def test_to_event_data_file_absent_normalizes_hash_detected_to_empty_string() -> None:
    """file_absent/file_deleted (hash ausente): to_event_data() debe normalizar hash_detected a "".

    D-C13-04: "" (string vacío) = "hash ausente". El contrato con el backend exige
    hash_detected str NOT NULL; emitir None provocaba IntegrityError + poison loop en el
    consumer (C35 CRITICAL). Este test antes asertaba `is None` — codificaba el bug.
    """
    change = DetectedChange(
        event_id="test-contract-002",
        path="/etc/shadow",
        event_type="file_absent",
        operation_type="file_absent",
        hash_expected="c" * 64,
        hash_detected=None,
        diff_text=None,
        process_pid=1,
        process_uid=0,
        process_exe=None,
        detected_at="2026-07-02T00:00:00+00:00",
        parent_event_id=None,
    )

    payload = change.to_event_data()

    assert payload["hash_detected"] == ""
    assert payload["hash_detected"] is not None
    assert "current_hash" not in payload
    # hash_expected NO se normaliza: puede seguir siendo el hash conocido de baseline.
    assert payload["hash_expected"] == "c" * 64


# ── D35/RN-129 (C40) — vocabulario de claves y limpieza de event_type ─────────

def test_to_event_data_does_not_emit_action_keys() -> None:
    """to_event_data() no agrega action/action_failed — esas claves las agrega
    exclusivamente DecisionEngine.evaluate_and_act, nunca el dataclass."""
    change = DetectedChange(
        event_id="test-contract-003",
        path="/etc/vocab-test",
        event_type="file_modified",
        operation_type="file_modified",
        hash_expected=None,
        hash_detected=None,
        diff_text=None,
        process_pid=1,
        process_uid=0,
        process_exe=None,
        detected_at="2026-08-13T00:00:00+00:00",
        parent_event_id=None,
    )

    payload = change.to_event_data()

    assert "action" not in payload
    assert "action_failed" not in payload


def test_auto_restore_does_not_pollute_event_type_with_action_result(tmp_path) -> None:
    """D35/RN-129: la sobrescritura `payload["event_type"] = "auto_restored"` fue
    eliminada de `_auto_restore`. event_type conserva el tipo de operación de
    filesystem; el resultado de la acción viaja exclusivamente en
    action/action_failed."""
    content = b"good content"
    content_hash = hashlib.sha256(content).hexdigest()
    target = tmp_path / "vocab_target.txt"
    target.write_bytes(b"tampered")

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "auto_restore"
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")
    baseline = MagicMock()
    entry = MagicMock()
    entry.content_b64 = base64.b64encode(content).decode()
    entry.hash = content_hash
    # D36/RN-130 (D-6): metadata requerida para que la restauración no aborte
    # con no_baseline_metadata. Misma uid/gid del proceso => fchown no-op.
    entry.mode = "0o644"
    entry.uid = os.getuid()
    entry.gid = os.getgid()
    baseline.read_entry.return_value = entry

    engine = DecisionEngine(
        rules=rules_cache, journal=journal, baseline=baseline, quarantine_dir=quarantine_dir
    )

    change = DetectedChange(
        event_id="test-contract-004",
        path=str(target),
        event_type="file_modified",
        operation_type="file_modified",
        hash_expected=content_hash,
        hash_detected="d" * 64,
        diff_text=None,
        process_pid=1,
        process_uid=0,
        process_exe=None,
        detected_at="2026-08-13T00:00:00+00:00",
        parent_event_id=None,
    )

    payload, _commit_fn = engine.evaluate_and_act(change)

    assert payload["event_type"] == "file_modified"  # vocabulario declarado, RN-71
    assert payload["action"] == "auto_restore"
    assert payload.get("action_failed") is not True
