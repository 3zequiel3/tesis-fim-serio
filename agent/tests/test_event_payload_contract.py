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
consume `backend/app/modules/events/service.py:172`
(`event_data.get("hash_detected", "")`).
"""
from __future__ import annotations

from agent.detector import DetectedChange


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
