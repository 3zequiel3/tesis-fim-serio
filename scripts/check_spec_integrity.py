#!/usr/bin/env python3
"""Guarda de integridad de openspec/specs/ — CORRER ANTES DE CADA `openspec archive`.

POR QUE EXISTE
    Varios archives crearon la main spec copiando el archivo delta verbatim en
    vez de mergearlo. Eso produjo dos danos, ambos silenciosos:

      1. Truncamiento. Un encabezado de delta (`## ADDED Requirements`) dentro de
         una main spec corta la seccion `## Requirements`: el parser deja de ver
         todo lo que sigue. Llego a haber 29 specs asi, con 110 requisitos
         invisibles para validate/list/archive.
      2. Borrado. Lo que el delta no mencionaba desaparecia. Se perdieron 48
         requisitos en 9 capabilities; dos capabilities enteras quedaron sin
         main spec.

    Ninguna herramienta lo senalo. Un `validate` en verde sobre una spec truncada
    no dice "esto esta bien": dice "no vi nada".

    Al menos un caso (commit 5355465) fue un archive escrito A MANO, sin invocar
    el CLI. Por eso la guarda vive fuera del CLI y se corre como paso de proceso.

USO
    python3 scripts/check_spec_integrity.py            # verifica, exit 1 si falla
    python3 scripts/check_spec_integrity.py --json     # salida estructurada

Sin dependencias externas: corre con el Python del sistema.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "openspec" / "specs"
ARCH = ROOT / "openspec" / "changes" / "archive"

# Anclado a inicio de linea (JD-025): el texto de una spec puede MENCIONAR
# `## ADDED Requirements` en prosa sin ser un encabezado.
DELTA_H2 = re.compile(r'^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements\s*$', re.M)
REQ_RE = re.compile(r'^### Requirement:\s*(.+?)\s*$', re.M)

# Capabilities fusionadas: los deltas viven bajo un nombre, la main spec bajo otro.
MERGED_INTO = {
    "agent-baseline-merge": "agent-baseline",
    "agent-bootstrap-verification": "agent-bootstrap",
}

# Renombres hechos via MODIFIED con el header cambiado. NO son perdidas.
# Este proyecto nunca uso `## RENAMED Requirements`, asi que sin este mapa la
# guarda exigiria requisitos que fueron legitimamente renombrados.
CONFIRMED_RENAMES: dict[str, dict[str, str]] = {
    "backend-event-consumer": {
        "Cadena superseded en ingesta con optimistic locking":
            "Cadena superseded en ingesta con optimistic locking y re-consulta ante race",
        "Compactación de cadena a máximo 10 eventos por path":
            "Compactación de cadena — retiene los más recientes",
    },
}


def _git_first_seen(path: Path) -> str:
    """Fecha del commit que introdujo el directorio.

    El prefijo YYYY-MM-DD del nombre NO es confiable: difiere de la fecha real de
    commit hasta en 4 dias, y 7 archives comparten el mismo prefijo. El orden de
    aplicacion se toma de git, que si es un orden total.
    """
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%cI", "--reverse", "--",
             str(path.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        ).stdout.strip().splitlines()
        if out:
            return out[0]
    except Exception:
        pass
    return path.name[:10] + "T00:00:00"


def _parse_delta(text: str) -> list[tuple[str, str]]:
    ops: list[tuple[str, str]] = []
    current = "ADDED"
    for line in text.splitlines():
        m = DELTA_H2.match(line)
        if m:
            current = m.group(1)
            continue
        rm = re.match(r'^### Requirement:\s*(.+?)\s*$', line)
        if rm:
            ops.append((current, rm.group(1).strip()))
    return ops


def expected_for(cap: str, deltas: list[Path]) -> list[str]:
    order: list[str] = []
    rmap = CONFIRMED_RENAMES.get(cap, {})
    for dpath in deltas:
        for op, hdr in _parse_delta(dpath.read_text(encoding="utf-8")):
            if op == "REMOVED":
                order = [h for h in order if h != hdr]
                continue
            src = next((o for o, n in rmap.items() if n == hdr and o in order), None)
            if src is not None:
                order = [hdr if h == src else h for h in order]
            elif hdr not in order:
                order.append(hdr)
    return order


def check() -> dict:
    problems: list[dict] = []

    deltas: dict[str, list[tuple[str, Path]]] = {}
    for d in ARCH.glob("*/specs/*/spec.md"):
        cap = MERGED_INTO.get(d.parent.name, d.parent.name)
        deltas.setdefault(cap, []).append((_git_first_seen(d.parents[2]), d))
    ordered = {c: [p for _, p in sorted(v, key=lambda t: t[0])] for c, v in deltas.items()}

    main_specs = {p.parent.name: p for p in SPECS.glob("*/spec.md")}

    # --- 1. invariante estructural ---
    for cap, p in sorted(main_specs.items()):
        t = p.read_text(encoding="utf-8")
        for h in DELTA_H2.findall(t):
            problems.append({"capability": cap, "kind": "delta_header_in_main_spec",
                             "detail": f"## {h} Requirements"})
        if not re.match(r'^#\s+\S', t.lstrip()):
            problems.append({"capability": cap, "kind": "missing_h1_title", "detail": ""})
        if not re.search(r'^## Purpose\s*$', t, re.M):
            problems.append({"capability": cap, "kind": "missing_purpose", "detail": ""})
        if not re.search(r'^## Requirements\s*$', t, re.M):
            problems.append({"capability": cap, "kind": "missing_requirements_section", "detail": ""})

        headers = [h.strip() for h in REQ_RE.findall(t)]
        dups = {h for h in headers if headers.count(h) > 1}
        for h in sorted(dups):
            problems.append({"capability": cap, "kind": "duplicate_requirement", "detail": h})

        # requisitos fuera de la seccion (el parser no los ve)
        mreq = re.search(r'^## Requirements\s*$', t, re.M)
        if mreq:
            for m in REQ_RE.finditer(t):
                if m.start() < mreq.start():
                    problems.append({"capability": cap, "kind": "requirement_outside_section",
                                     "detail": m.group(1).strip()})

    # --- 2. invariante de completitud, POR ARCHIVO (nunca agregada) ---
    for cap, dl in sorted(ordered.items()):
        expected = expected_for(cap, dl)
        if cap not in main_specs:
            problems.append({"capability": cap, "kind": "capability_has_no_main_spec",
                             "detail": f"{len(expected)} requisitos archivados sin destino"})
            continue
        cur = {h.strip() for h in REQ_RE.findall(main_specs[cap].read_text(encoding="utf-8"))}
        for h in expected:
            if h not in cur:
                problems.append({"capability": cap, "kind": "requirement_lost", "detail": h})

    return {"ok": not problems, "problems": problems,
            "n_specs": len(main_specs),
            "n_requirements": sum(len(REQ_RE.findall(p.read_text(encoding='utf-8')))
                                  for p in main_specs.values())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    r = check()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif r["ok"]:
        print(f"OK — {r['n_specs']} main specs, {r['n_requirements']} requisitos, sin problemas.")
    else:
        print(f"FALLO — {len(r['problems'])} problema(s):\n")
        for p in r["problems"]:
            print(f"  [{p['kind']}] {p['capability']}"
                  + (f"\n      {p['detail']}" if p["detail"] else ""))
        print("\nUn requisito 'perdido' que en realidad fue RENOMBRADO via MODIFIED debe")
        print("agregarse a CONFIRMED_RENAMES en este archivo, con evidencia del delta.")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
