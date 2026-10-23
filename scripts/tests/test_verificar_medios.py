"""verificar_medios.py compara los SVG del documento con los versionados."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("verificar_medios", REPO / "scripts" / "verificar_medios.py")
assert SPEC and SPEC.loader
vm = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(vm)

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
PNG = b"\x89PNG\r\n\x1a\n"
RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
    '<Relationship Id="rIdSvgfig1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/fig1.svg"/>'
    "</Relationships>"
)


def documento(con_svg: bool) -> str:
    ext = (
        '<a:extLst><a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}">'
        '<asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" r:embed="rIdSvgfig1"/>'
        "</a:ext></a:extLst>"
    ) if con_svg else ""
    return (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<w:body><a:blip r:embed="rId1">{ext}</a:blip></w:body></w:document>'
    )


def armar(tmp: Path, con_svg: bool, svg: bytes = SVG) -> Path:
    ruta = tmp / ("con.docx" if con_svg else "sin.docx")
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("word/document.xml", documento(con_svg))
        z.writestr("word/_rels/document.xml.rels", RELS)
        z.writestr("word/media/image1.png", PNG)
        z.writestr("word/media/fig1.svg", svg)
    return ruta


@pytest.fixture
def figuras(tmp_path: Path) -> Path:
    d = tmp_path / "figuras"; d.mkdir()
    (d / "fig1.svg").write_bytes(SVG)
    return d


def test_svg_identico_al_versionado(tmp_path: Path, figuras: Path, capsys) -> None:
    rc = vm.main([str(armar(tmp_path, True)), "--dir", str(figuras), "--esperados", "1"])
    assert rc == 0
    assert "coinciden con" in capsys.readouterr().out


def test_documento_sin_svg_falla(tmp_path: Path, figuras: Path, capsys) -> None:
    rc = vm.main([str(armar(tmp_path, False)), "--dir", str(figuras), "--esperados", "1"])
    assert rc == 1
    assert "MAPA DE BITS" in capsys.readouterr().out


def test_svg_distinto_del_versionado_falla(tmp_path: Path, figuras: Path, capsys) -> None:
    rc = vm.main([str(armar(tmp_path, True, svg=SVG + b"\n")), "--dir", str(figuras), "--esperados", "1"])
    assert rc == 1
    assert "DIFIERE" in capsys.readouterr().out


def test_identificadores_de_relacion_no_numericos(tmp_path: Path) -> None:
    svgs, solo = vm.medios(armar(tmp_path, True))
    assert [r for r, _ in svgs] == ["word/media/fig1.svg"] and solo == []
