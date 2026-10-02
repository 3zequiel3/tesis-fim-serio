#!/usr/bin/env python3
"""A-2: orden de llegada frente a orden de detección en un eventos.csv.

Ordena las filas por received_at (desempate estable: el orden del archivo) y cuenta
las regresiones de detected_at: un evento es "fuera de orden" si su detected_at es
anterior al MÁXIMO detected_at ya recibido (llegó después de uno detectado más tarde).
Es la definición con la que se reportó fuera_de_orden=359 en run-03; comparar sólo
pares consecutivos da 1 en ese archivo y no mide el desorden del drenaje, por eso se
informa aparte como `regresiones_adyacentes`. También informa filas, event_id únicos
y duplicados.

Uso:
    python3 scripts/fuera_de_orden.py <eventos.csv> [--json]

Salida (una línea clave=valor por métrica; --json la emite como objeto):
    filas, unicos, duplicados, fuera_de_orden, fuera_de_orden_pct, regresiones_adyacentes

Acepta los dos formatos de marca de tiempo que produce el lab: ISO con 'T' y sufijo
'Z'/'+00:00', y el de psql \\copy '2026-09-23 23:13:06.162939+00' (desfase de hora
abreviado). Sólo biblioteca estándar. Verificación de referencia:
tesis/cierre/evidencia/v2-eval-20260923T215624Z/resiliencia/run-03/eventos.csv
=> fuera_de_orden=359.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_TZ_CORTO = re.compile(r"([+-]\d{2})$")  # '+00' -> '+00:00'


def parse_ts(valor: str) -> datetime:
    """Parsea las marcas de tiempo de psql ('... +00') y de ISO 8601 ('...Z')."""
    s = valor.strip().replace("Z", "+00:00")
    s = _TZ_CORTO.sub(r"\1:00", s)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def analizar(path: Path) -> dict[str, float | int]:
    with path.open(newline="", encoding="utf-8") as fh:
        filas = [(parse_ts(r["received_at"]), parse_ts(r["detected_at"]), r["event_id"])
                 for r in csv.DictReader(fh)]
    filas.sort(key=lambda f: f[0])  # sorted() es estable: empates conservan el orden del archivo
    maximo = None
    fuera = 0
    for _recv, det, _id in filas:
        if maximo is not None and det < maximo:
            fuera += 1
        if maximo is None or det > maximo:
            maximo = det
    adyacentes = sum(1 for prev, cur in zip(filas, filas[1:]) if cur[1] < prev[1])
    unicos = len({f[2] for f in filas})
    n = len(filas)
    return {
        "filas": n,
        "unicos": unicos,
        "duplicados": n - unicos,
        "fuera_de_orden": fuera,
        "fuera_de_orden_pct": round(100 * fuera / n, 3) if n else 0.0,
        "regresiones_adyacentes": adyacentes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path, help="eventos.csv con event_id, detected_at, received_at")
    ap.add_argument("--json", action="store_true", help="salida como objeto JSON")
    args = ap.parse_args(argv)
    if not args.csv.is_file():
        print(f"ERROR: {args.csv} no existe", file=sys.stderr)
        return 2
    res = analizar(args.csv)
    if args.json:
        print(json.dumps(res))
    else:
        for k, v in res.items():
            print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
