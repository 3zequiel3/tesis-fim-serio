#!/usr/bin/env python3
"""Verifica que cada ruta del repositorio citada en la tesis exista en una referencia git.

USO
    python3 scripts/verificar_rutas_tesis.py Tesis_vNN.docx entrega-tesis
    python3 scripts/verificar_rutas_tesis.py tesis.md devel

Acepta .docx (se lee con zipfile, sin pandoc) o texto plano/markdown.
Las citas con número de línea (agent/detector.py:588) se normalizan a la ruta.
Exit 1 si falta alguna ruta.
"""
import re
import subprocess
import sys
import zipfile
from html import unescape

PREFIJOS = r"(?:tesis|scripts|agent|backend|frontend|docs|n8n|openspec|lab|deploy)"
PATRON = re.compile(PREFIJOS + r"/[\w./\-]+")


def texto_de(ruta: str) -> str:
    if ruta.lower().endswith(".docx"):
        with zipfile.ZipFile(ruta) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        # Cada run <w:t> es un fragmento; los párrafos se separan con salto de línea.
        xml = re.sub(r"</w:p>", "\n", xml)
        return unescape(re.sub(r"<[^>]+>", "", xml))
    with open(ruta, encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    documento, ref = sys.argv[1], sys.argv[2]
    citadas = sorted({m.rstrip(".,;:)/") for m in PATRON.findall(texto_de(documento))})
    arbol = set(subprocess.run(["git", "ls-tree", "-r", "--name-only", ref],
                               capture_output=True, text=True, check=True).stdout.split())
    dirs = {p.rsplit("/", i)[0] for p in arbol for i in range(1, p.count("/") + 1)}
    faltan = [c for c in citadas if c not in arbol and c not in dirs]
    print(f"Rutas citadas: {len(citadas)}  Faltantes en {ref}: {len(faltan)}")
    for f in faltan:
        print("  FALTA", f)
    return 1 if faltan else 0


if __name__ == "__main__":
    sys.exit(main())
