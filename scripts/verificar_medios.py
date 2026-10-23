#!/usr/bin/env python3
"""Comprueba las figuras vectoriales que incrusta el documento (Anexo F.1).

Para cada imagen del documento que lleva una versión SVG (elemento svgBlip),
calcula el SHA-256 del SVG incrustado y lo busca entre los SVG versionados en
tesis/figuras/. Informa, además, las imágenes que solo tienen mapa de bits.

Uso, desde la raíz del clon:
    python3 scripts/verificar_medios.py <documento.docx> [--dir tesis/figuras] [--esperados 8]

Sale con código 1 si el número de SVG incrustados no es el esperado o si
alguno no coincide byte a byte con un SVG versionado.
"""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
EMBED = f"{{{NS['r']}}}embed"


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def relaciones(z: zipfile.ZipFile) -> dict[str, str]:
    """Identificador de relación → ruta de la parte dentro del paquete."""
    raiz = ET.fromstring(z.read("word/_rels/document.xml.rels"))
    rels = {}
    for r in raiz.findall("rel:Relationship", NS):
        if r.get("TargetMode") == "External":
            continue
        rels[r.get("Id")] = posixpath.normpath(posixpath.join("word", r.get("Target")))
    return rels


def medios(docx: Path) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Devuelve los SVG incrustados (ruta, contenido) y los mapas de bits sin SVG."""
    with zipfile.ZipFile(docx) as z:
        rels = relaciones(z)
        doc = ET.fromstring(z.read("word/document.xml"))
        svgs, solo_bitmap = [], []
        for blip in doc.iter(f"{{{NS['a']}}}blip"):
            svg = blip.find(".//asvg:svgBlip", NS)
            if svg is None:
                solo_bitmap.append(rels.get(blip.get(EMBED), "?"))
                continue
            ruta = rels[svg.get(EMBED)]
            svgs.append((ruta, z.read(ruta)))
    return svgs, solo_bitmap


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docx", type=Path)
    ap.add_argument("--dir", type=Path, default=Path("tesis/figuras"))
    ap.add_argument("--esperados", type=int, default=8)
    a = ap.parse_args(argv)

    versionados = {sha256(p.read_bytes()): p.name for p in sorted(a.dir.glob("*.svg"))}
    svgs, solo_bitmap = medios(a.docx)

    errores = 0
    for ruta, datos in svgs:
        h = sha256(datos)
        nombre = versionados.get(h)
        print(f"{'OK     ' if nombre else 'DIFIERE'}  {ruta}  {h[:16]}  {nombre or '-'}")
        errores += nombre is None
    for ruta in solo_bitmap:
        print(f"MAPA DE BITS  {ruta}  (sin versión SVG)")

    print(f"SVG incrustados: {len(svgs)} (esperados {a.esperados}); "
          f"coinciden con {a.dir.as_posix()}: {len(svgs) - errores}")
    print(f"Imágenes solo en mapa de bits: {len(solo_bitmap)}")
    return 1 if errores or len(svgs) != a.esperados else 0


if __name__ == "__main__":
    sys.exit(main())
