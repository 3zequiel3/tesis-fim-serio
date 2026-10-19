#!/usr/bin/env python3
"""Comprueba que los textos de tesis/autoria/ coincidan con el documento (C-2).

Cada archivo .md de tesis/autoria/ que empieza con un título de sección (por
ejemplo «## 7.5 Contribución formativa») se compara, párrafo por párrafo, con
la sección del .docx que lleva ese título: desde el título hasta el siguiente
título del documento. El Markdown se lee como texto: se quitan las marcas de
título (#), de negrita (**), de lista («- ») y los escapes (\\&), y se ignoran
los marcadores entre corchetes, como «*[Tabla 28 sin cambios]*». Las tablas del
documento, con su leyenda y su nota, no se comparan.

La única diferencia admitida es la oración del apartado 7.1 que la herramienta
actualizó con autorización de los autores; se declara en DECLARADAS y el
script la informa.

Uso, desde la raíz del clon:
    python scripts/verificar_autoria.py <documento.docx> [--dir tesis/autoria]

Sale con código 1 si algún texto no coincide.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import zipfile
from pathlib import Path

VIEJA_71 = ("La custodia de la evidencia de versiones anteriores tiene tres defectos, que no afectan cifras de "
            "v5.1-tesis: cinco de los 35 manifiestos no verifican íntegros, el paquete sellado de v1.0-tesis fue "
            "sobrescrito y las tres trazas de resiliencia de v2.0-tesis son copias de una misma corrida de "
            "diagnóstico (Anexo F.1).")
NUEVA_71 = ("La custodia de la evidencia de versiones anteriores no afecta cifras de v5.1-tesis: tres de los 38 "
            "manifiestos no verifican íntegros (los dos de custodia de v5.1-tesis, excluidos por tamaño, y el de "
            "v2.0-tesis, cuyas tres trazas de resiliencia son copias de una misma corrida de diagnóstico), y los "
            "archivos sobrescritos después de sellar los paquetes de v1.0-tesis y v2.0-tesis fueron restaurados "
            "desde sus commits originales (Anexo F.1).")
DECLARADAS = {"7_1_castro_gonzalez.md": [(VIEJA_71, NUEVA_71)]}
# Archivos de tesis/autoria/ que no son el texto de una sección.
SIN_SECCION = {"credit.md": "declaración de contribuciones; el Anexo I la resume"}


def bloques_md(texto: str) -> list[list[str]]:
    """Secciones del archivo (separadas por «---»), cada una como lista de párrafos de texto."""
    secciones, actual = [], []
    for b in re.split(r"\n\s*\n", texto.replace("\r\n", "\n")):
        b = b.strip("\n")
        if not b.strip():
            continue
        if b.strip() == "---":
            secciones.append(actual); actual = []
            continue
        if re.fullmatch(r"\*\[[^\]]*\]\*", b.strip()):
            continue
        lineas = b.split("\n")
        if all(l.startswith("- ") for l in lineas):
            actual += [limpiar(l[2:]) for l in lineas]
        else:
            actual.append(limpiar(" ".join(lineas)))
    if actual:
        secciones.append(actual)
    return secciones


def limpiar(s: str) -> str:
    s = re.sub(r"^#+\s*", "", s.strip())
    s = s.replace("**", "")
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!&])", r"\1", s)
    return s


def items_docx(docx: Path) -> list[tuple[str, str, bool]]:
    """Elementos del cuerpo en orden: ('p', texto, es_título) o ('tbl', '', False)."""
    x = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    x = x[x.find("<w:body>"):]
    out = []
    for m in re.finditer(r"<w:p[ >].*?</w:p>|<w:tbl>.*?</w:tbl>", x, flags=re.S):
        g = m.group()
        if g.startswith("<w:tbl>"):
            out.append(("tbl", "", False))
            continue
        texto = html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", g)))
        titulo = bool(re.search(r'<w:pStyle w:val="(Heading\d|Title)"', g))
        # Un salto de página antes del texto también cierra la sección (p. ej., tras el Abstract).
        corte = bool(re.search(r'w:type="page"|<w:pageBreakBefore(?: w:val="(?:1|true)")?/>', g))
        out.append(("p", texto, titulo or corte))
    return out


def seccion_docx(items, titulo: str) -> list[str] | None:
    idx = [i for i, (k, t, h) in enumerate(items) if k == "p" and t == titulo and h]
    if len(idx) != 1:
        return None
    pars, i = [], idx[0] + 1
    while i < len(items):
        k, t, h = items[i]
        if k == "p" and h and not re.match(re.escape(titulo.split(" ")[0]) + r"\.\d", t):
            break  # siguiente título que no es un subapartado de esta sección
        if k == "tbl":
            i += 1
            continue
        if re.match(r"Tabla \d+\. ", t) and i + 1 < len(items) and items[i + 1][0] == "tbl":
            i += 1
            continue
        if t.startswith("Nota. ") and i > 0 and items[i - 1][0] == "tbl":
            i += 1
            continue
        if t.strip():
            pars.append(t)
        i += 1
    return pars


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docx", type=Path)
    ap.add_argument("--dir", type=Path, default=Path("tesis/autoria"))
    args = ap.parse_args()
    items = items_docx(args.docx)
    malos = 0
    for f in sorted(args.dir.glob("*.md")):
        if f.name in SIN_SECCION:
            print(f"--      {f.name}: {SIN_SECCION[f.name]}; no se compara")
            continue
        texto = f.read_text(encoding="utf-8")
        declaradas = DECLARADAS.get(f.name, [])
        for vieja, nueva in declaradas:
            texto = texto.replace(vieja, nueva)
        secciones = bloques_md(texto)
        if not secciones or not re.match(r"^(#|\d)", texto.lstrip()):
            print(f"--      {f.name}: no es el texto de una sección del documento; no se compara")
            continue
        partes = []
        for sec in secciones:
            titulo, cuerpo = sec[0], sec[1:]
            doc = seccion_docx(items, titulo)
            if doc is None:
                partes.append((False, f"«{titulo}»: el documento no tiene un título único con ese texto"))
                continue
            if doc == cuerpo:
                partes.append((True, f"«{titulo}»: {len(cuerpo)} párrafos idénticos"))
                continue
            dif = next((j for j, (a, b) in enumerate(zip(cuerpo, doc)) if a != b), min(len(cuerpo), len(doc)))
            partes.append((False, f"«{titulo}»: difiere en el párrafo {dif + 1} "
                                  f"(archivo {len(cuerpo)} párrafos, documento {len(doc)})"))
        ok = all(p[0] for p in partes)
        malos += not ok
        nota = f"; {len(declaradas)} oración actualizada con autorización, declarada" if declaradas else ""
        print(f"{'OK     ' if ok else 'DIFIERE'} {f.name}: " + "; ".join(p[1] for p in partes) + nota)
    print(f"archivos con diferencias: {malos}")
    sys.exit(1 if malos else 0)


if __name__ == "__main__":
    main()
