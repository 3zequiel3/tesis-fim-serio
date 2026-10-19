"""scripts/recalcular_cap5.py reproduce el Capítulo 5 y detecta cualquier diferencia (P-10)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("recalcular_cap5", REPO / "scripts" / "recalcular_cap5.py")
assert SPEC and SPEC.loader
rc5 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(rc5)


def test_rounding_tolerance_matches_reported_decimals() -> None:
    filas: list = []
    rc5.comparar({"x": [41.73, 2], "y": [41.73, 2], "p": [6.74e-88, "rel"]},
                 {"x": 41.7315, "y": 41.736, "p": 6.7428e-88}, "", filas)
    assert [f[0] for f in filas] == [True, False, True]


def test_missing_value_is_a_difference() -> None:
    filas: list = []
    rc5.comparar({"x": [1, 0]}, {}, "", filas)
    assert filas[0][0] is False


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO / "scripts" / "recalcular_cap5.py"), *args],
                          cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=600)


def test_chapter_5_reproduces_the_thesis() -> None:
    result = run("--solo-diferencias")
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "difieren o faltan: 0" in result.stdout


def test_a_changed_expected_value_fails(tmp_path: Path) -> None:
    esperados = json.loads((REPO / "tesis/cierre/valores_esperados.json").read_text(encoding="utf-8"))
    esperados["tabla17"]["combinado"]["p99"] = [41.74, 2]
    alterado = tmp_path / "esperados.json"
    alterado.write_text(json.dumps(esperados), encoding="utf-8")
    result = run("--esperados", str(alterado), "--solo-diferencias")
    assert result.returncode == 1
    assert "DIFIERE tabla17.combinado.p99" in result.stdout


def test_thesis_number_format() -> None:
    assert rc5.formato_tesis(41.73, 2) == "41,73"
    assert rc5.formato_tesis(16193.6, 1) == "16.193,6"
    assert rc5.formato_tesis(1494, 0) == "1.494"
    assert rc5.formato_tesis(1.21e-94, "rel") == "1,21 × 10⁻⁹⁴"


def test_values_appear_in_the_versioned_document() -> None:
    documentos = sorted((REPO / "tesis" / "entrega").glob("*.docx")) if (REPO / "tesis" / "entrega").is_dir() else []
    if not documentos:
        import pytest
        pytest.skip("no hay un documento versionado en tesis/entrega/")
    result = run("--docx", str(documentos[-1]), "--solo-diferencias")
    assert result.returncode == 0, result.stdout[-2000:]
    assert "no figuran: 0" in result.stdout
