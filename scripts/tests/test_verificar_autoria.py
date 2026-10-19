"""Los textos de tesis/autoria/ coinciden con el documento versionado (C-2)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("verificar_autoria", REPO / "scripts" / "verificar_autoria.py")
assert SPEC and SPEC.loader
va = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(va)


def test_markdown_is_read_as_text() -> None:
    assert va.limpiar("## 7.5 Contribución formativa") == "7.5 Contribución formativa"
    assert va.limpiar("**Objetivo 1.** Texto") == "Objetivo 1. Texto"
    assert va.limpiar("Syairozi \\& Arizal") == "Syairozi & Arizal"


def test_list_items_and_markers() -> None:
    secciones = va.bloques_md("## T\n\nA:\n\n- uno;\n- dos.\n\n*[Tabla 28 sin cambios]*\n\nB.")
    assert secciones == [["T", "A:", "uno;", "dos.", "B."]]


def test_authors_texts_match_the_versioned_document() -> None:
    entrega = REPO / "tesis" / "entrega"
    documentos = sorted(entrega.glob("*.docx")) if entrega.is_dir() else []
    if not documentos:
        pytest.skip("no hay un documento versionado en tesis/entrega/")
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "verificar_autoria.py"), str(documentos[-1])],
                       cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout
