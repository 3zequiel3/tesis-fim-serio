"""
Guarda de integridad de los artefactos de OpenSpec (C49).

Wrapper de pytest sobre `scripts/check_spec_integrity.py`. La lógica vive en el
script y no acá, por dos razones concretas:

  - El daño histórico incluye al menos un archive escrito **a mano** (commit
    5355465), sin invocar el CLI. Una guarda que sólo corre dentro de la suite de
    un módulo no cubre ese camino; el script se invoca como paso de proceso antes
    de cualquier `openspec archive`.
  - `openspec/specs/` es un artefacto de repositorio, no del backend. El script no
    tiene dependencias y corre con el Python del sistema.

Este test existe para que la guarda tenga un punto de enforcement automático
además del manual.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_spec_integrity.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_spec_integrity", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_spec_integrity"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_guard_script_exists() -> None:
    assert _SCRIPT.is_file(), f"falta la guarda en {_SCRIPT}"


def test_main_specs_are_structurally_valid_and_complete() -> None:
    """
    Tres invariantes en una sola aserción, todas por archivo:

      1. Ninguna main spec contiene encabezados de delta.
      2. Todas tienen título, ``## Purpose`` y ``## Requirements``.
      3. Ninguna tiene menos requisitos que sus deltas archivados.

    La tercera es la que hubiera atajado los 48 requisitos borrados el día que
    ocurrieron. Es **por archivo**, nunca un total agregado: una capability que
    pierde 3 y otra que gana 3 se cancelarían en un total y el daño pasaría.
    """
    result = _load().check()

    assert result["ok"], "integridad de specs rota:\n" + "\n".join(
        f"  [{p['kind']}] {p['capability']}" + (f" — {p['detail']}" if p["detail"] else "")
        for p in result["problems"]
    )


def test_guard_detects_a_deleted_requirement(tmp_path: pytest.TempPathFactory) -> None:
    """
    La guarda tiene que fallar cuando debe, no sólo pasar cuando todo está bien.

    Un test de integridad que nunca se vio fallar no es evidencia de nada — es
    exactamente el modo de falla que este change vino a corregir.
    """
    mod = _load()
    ops = mod._parse_delta(
        "## ADDED Requirements\n"
        "### Requirement: Alpha\n#### Scenario: s\n- **WHEN** x\n- **THEN** y\n"
        "### Requirement: Beta\n#### Scenario: s\n- **WHEN** x\n- **THEN** y\n"
    )
    assert ops == [("ADDED", "Alpha"), ("ADDED", "Beta")]

    removed = mod._parse_delta(
        "## ADDED Requirements\n### Requirement: Alpha\n"
        "## REMOVED Requirements\n### Requirement: Alpha\n"
    )
    assert removed == [("ADDED", "Alpha"), ("REMOVED", "Alpha")]


def test_delta_header_detection_is_anchored() -> None:
    """
    La detección debe anclar a ``^##``. El texto de la propia capability
    ``openspec-artifact-integrity`` menciona ``## ADDED Requirements`` en prosa;
    sin anclaje la guarda fallaría sobre sí misma.
    """
    mod = _load()
    assert not mod.DELTA_H2.findall(
        "El sistema SHALL NOT contener `## ADDED Requirements` dentro de una main spec.\n"
    )
    assert mod.DELTA_H2.findall("## ADDED Requirements\n")
