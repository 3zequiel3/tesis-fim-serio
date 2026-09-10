from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("analisis_ausencias", Path(__file__).parents[1] / "analisis_ausencias.py")
assert SPEC and SPEC.loader
analysis = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(analysis)


def operation() -> dict:
    return {"operation_id": "run-1:1", "run_id": "run-1", "case": "B_retorno_baseline_aprobada",
            "operation": "modify", "ruta_agente": "/watch/file", "ts_utc": "2026-01-01T00:00:00+00:00",
            "deteccion_agente_esperada": False}


def test_return_to_approved_baseline_is_explained_as_suppression() -> None:
    trace = [{"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:01+00:00",
              "stage": "decision_suppressed", "event_id": None}]
    result = analysis.classify(operation(), analysis.stages_for_operation(operation(), trace, 5), None)
    assert result["suppressed"] is True
    assert result["interpretation"] == "suppressed_by_active_baseline"
    assert result["backend_persisted"] == "unknown"


def test_missing_db_lookup_is_unknown_not_false() -> None:
    trace = [
        {"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:01+00:00", "stage": "kernel_received"},
        {"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:02+00:00", "stage": "decision_evaluated"},
        {"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:03+00:00", "stage": "queue_enqueue_persisted", "event_id": "e1"},
        {"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:04+00:00", "stage": "xadd_succeeded", "event_id": "e1"},
    ]
    result = analysis.classify(operation(), analysis.stages_for_operation(operation(), trace, 5), None)
    assert result["backend_persisted"] == "unknown"
    assert result["interpretation"] == "backend_lookup_unknown"


def test_duplicate_suppression_does_not_hide_a_persisted_event() -> None:
    stages = {"kernel_received", "decision_evaluated", "queue_enqueue_persisted",
              "xadd_succeeded", "ack_valid", "decision_suppressed"}
    backend = {"e1": {"status": "alert_only", "received_at": "2026-01-01T00:00:04+00:00"}}
    assert analysis.interpretation(stages, {"e1"}, backend) == "fully_correlated"


def _op(seq: int, started_epoch: float, started_mono: int) -> dict:
    row = operation() | {"operation_id": f"run-1:{seq}", "seq": seq, "started_epoch": started_epoch,
                         "started_monotonic_ns": started_mono, "ts_epoch": started_epoch}
    return row


def test_non_overlapping_windows_exclude_later_suppression_from_prior_writes() -> None:
    c1, c2, c0 = _op(1, 100.0, 1_000), _op(2, 105.0, 5_000), _op(3, 110.0, 10_000)
    trace = [
        {"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:01+00:00", "monotonic_ns": 1_100, "stage": "decision_evaluated"},
        {"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:11+00:00", "monotonic_ns": 10_100, "stage": "decision_suppressed"},
    ]
    windows = analysis.operation_windows([c1, c2, c0], 30)
    c1_stages = analysis.stages_for_operation(c1, trace, 30, end=windows[0][0], end_monotonic_ns=windows[0][1], end_inclusive=windows[0][2])
    c0_stages = analysis.stages_for_operation(c0, trace, 30, end=windows[2][0], end_monotonic_ns=windows[2][1], end_inclusive=windows[2][2])
    assert {row["stage"] for row in c1_stages} == {"decision_evaluated"}
    assert {row["stage"] for row in c0_stages} == {"decision_suppressed"}


def test_kernel_stage_between_start_and_completion_is_included() -> None:
    op = _op(1, 100.0, 1_000) | {"completed_epoch": 101.0, "completed_monotonic_ns": 2_000}
    trace = [{"run_id": "run-1", "path": "/watch/file", "timestamp": "2026-01-01T00:00:00+00:00", "monotonic_ns": 1_500, "stage": "kernel_received"}]
    assert analysis.stages_for_operation(op, trace, 30)[0]["stage"] == "kernel_received"
