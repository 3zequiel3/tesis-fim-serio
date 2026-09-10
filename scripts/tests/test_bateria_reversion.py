from __future__ import annotations

import importlib.util

import pytest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("bateria_reversion", Path(__file__).parents[1] / "bateria_reversion.py")
assert SPEC and SPEC.loader
battery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(battery)


def test_dry_run_is_non_mutating_and_accepts_explicit_run_id(tmp_path: Path) -> None:
    output = tmp_path / "result"
    assert battery.main([
        "--dir", str(tmp_path), "--salida", str(output), "--run-id", "run-test", "--dry-run",
    ]) == 0
    assert output.is_dir()
    assert not (output / "bateria9_operaciones.jsonl").exists()


def test_approved_sequence_records_successive_changes_and_suppressed_return(tmp_path: Path) -> None:
    path = tmp_path / "baseline.bin"
    records: list[dict] = []
    with (tmp_path / "ops.jsonl").open("w", encoding="utf-8") as sink:
        next_seq = battery.run_approved_sequence(
            path, "/watch/baseline.bin", sink, records,
            run_id="run-test", seq=1, baseline_wait=0, event_wait=0,
        )
    assert next_seq == 4
    assert [record["case"] for record in records] == [
        "B_sucesivo_c1", "B_sucesivo_c2", "B_retorno_baseline_aprobada",
    ]
    assert [record["deteccion_agente_esperada"] for record in records] == [True, True, False]
    assert records[-1]["hash_despues"] == battery.sha256_file(path)


def test_same_run_id_is_rejected_without_truncating_existing_evidence(tmp_path: Path) -> None:
    output = tmp_path / "result"; output.mkdir()
    operations = output / "bateria9_operaciones.jsonl"
    operations.write_text('{"run_id":"run-test"}\n', encoding="utf-8")
    assert battery.main(["--dir", str(tmp_path), "--salida", str(output), "--run-id", "run-test"]) == 2
    assert operations.read_text(encoding="utf-8") == '{"run_id":"run-test"}\n'


def test_run_slug_is_safe_and_scoped(tmp_path: Path) -> None:
    slug = battery.safe_run_slug("run_A-1")
    assert "/" not in slug and ".." not in slug
    path = battery.scoped_run_path(tmp_path, "baseline", slug, 1)
    assert path.is_relative_to(tmp_path.resolve())
    with pytest.raises(ValueError):
        battery.safe_run_slug("../outside")


def test_append_record_uses_caller_captured_clock_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_clock() -> float:
        raise AssertionError("append_record must not read the clock")
    monkeypatch.setattr(battery.time, "time", forbidden_clock)
    records: list[dict] = []
    with (tmp_path / "ops.jsonl").open("w", encoding="utf-8") as sink:
        battery.append_record(
            sink, records, run_id="run-test", seq=1, case="case", operation="modify",
            host_path=tmp_path / "file", agent_path="/watch/file", before_hash=None, after_hash=None,
            expected=True, content_size=0, started_epoch=100.0, started_monotonic_ns=10,
            completed_epoch=101.0, completed_monotonic_ns=11,
        )
    assert records[0]["ts_epoch"] == records[0]["started_epoch"] == 100.0
    assert records[0]["completed_monotonic_ns"] == 11
