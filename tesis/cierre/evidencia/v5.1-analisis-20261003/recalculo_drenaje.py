#!/usr/bin/env python3
"""Recalcula el drenaje del corte de Valkey de v5.1-tesis (Tabla 21, Anexo L.4).

Toma t0 de la línea FIN_CORTE de bateria5_run-0N.log, el primer xadd exitoso
posterior en la traza del agente y los instantes de recepción de eventos.csv,
y descompone el drenaje en reconexión, tramo sin consumo y consumo.

En la primera repetición, la utilidad date escribió la fracción de segundo sin
sus ceros iniciales (12:37:56.80393730 por 12:37:56.080393730). El script
completa la fracción a nueve dígitos, que es la corrección de la nota de la
Tabla 21; en run-02 y run-03 la fracción ya tiene nueve dígitos y no cambia.

Por defecto t0 es la marca de la línea, la lectura que adopta la Tabla 21.
Con --t0 campo-t se toma el campo t= de la misma línea, la segunda lectura que
informa su nota (27,006 s en run-01).

Uso, desde la raíz del clon:
    python scripts/recalculo_drenaje.py [--run 1 2 3] [--t0 marca|campo-t]

Salida esperada para run-01 con la marca:
    eventos=2998 reconexion=0.470 sin_consumo=0.947 consumo=25.584 drenaje=27.000 caudal=117.2
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("tesis/cierre/evidencia/v5-eval-20261003T102313Z/resiliencia")
LINEA = re.compile(r"^\[(?P<marca>[^\]]+)\] FIN_CORTE t=(?P<campo_t>\S+)\s*$")
INSTANTE = re.compile(r"^(?P<base>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(?P<frac>\d+)Z$")


def leer_instante(texto: str) -> datetime:
    """Instante UTC con la fracción completada a nueve dígitos y redondeada al microsegundo."""
    m = INSTANTE.match(texto)
    if not m:
        raise ValueError(f"instante con formato inesperado: {texto!r}")
    ns = int(m["frac"].rjust(9, "0"))
    base = datetime.fromisoformat(m["base"]).replace(tzinfo=timezone.utc)
    return base + timedelta(microseconds=round(ns / 1000))


def t0_de(run_dir: Path, run: int, lectura: str) -> datetime:
    log = run_dir / f"bateria5_run-0{run}.log"
    for linea in log.read_text(encoding="utf-8").splitlines():
        m = LINEA.match(linea)
        if m:
            return leer_instante(m["marca"] if lectura == "marca" else m["campo_t"])
    raise ValueError(f"{log} no tiene línea FIN_CORTE")


def recalcular(run: int, lectura: str = "marca") -> dict:
    d = BASE / f"run-0{run}"
    t0 = t0_de(d, run, lectura)
    with open(d / f"traza_run-0{run}.jsonl", encoding="utf-8") as fh:
        xadd = sorted(datetime.fromisoformat(r["timestamp"])
                      for r in map(json.loads, fh) if r["stage"] == "xadd_succeeded")
    primer_xadd = next(t for t in xadd if t >= t0)
    with open(d / "eventos.csv", encoding="utf-8", newline="") as fh:
        rec = sorted(datetime.fromisoformat(r["received_at"].replace("+00", "+00:00"))
                     for r in csv.DictReader(fh))
    consumo = (rec[-1] - rec[0]).total_seconds()
    return {
        "eventos": len(rec),
        "reconexion": (primer_xadd - t0).total_seconds(),
        "sin_consumo": (rec[0] - primer_xadd).total_seconds(),
        "consumo": consumo,
        "drenaje": (rec[-1] - t0).total_seconds(),
        "caudal": len(rec) / consumo,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=int, nargs="+", choices=[1, 2, 3], default=[1, 2, 3])
    ap.add_argument("--t0", choices=["marca", "campo-t"], default="marca")
    args = ap.parse_args()
    for run in args.run:
        r = recalcular(run, args.t0)
        print(f"run-0{run}: eventos={r['eventos']} reconexion={r['reconexion']:.3f} "
              f"sin_consumo={r['sin_consumo']:.3f} consumo={r['consumo']:.3f} "
              f"drenaje={r['drenaje']:.3f} caudal={r['caudal']:.1f}")


if __name__ == "__main__":
    main()
