#!/usr/bin/env python3
"""
analisis_mmap.py — Cruce del manifiesto de la Batería 8 contra la tabla `events`.

Toma `bateria8_cambios.jsonl` (producido por bateria_mmap.py) y, para cada
operación, busca en PostgreSQL si el agente emitió un evento sobre esa ruta
dentro de la ventana posterior a la modificación. Produce las filas de la
Tabla 17 del Capítulo 5.

CRITERIO DE ATRIBUCIÓN
----------------------
Una operación se considera DETECTADA si existe al menos un evento en la tabla
`events` que cumpla las tres condiciones:

  1. `path` coincide con `ruta_agente` de la operación;
  2. `detected_at` cae en la ventana `(ts_operacion, ts_operacion + tolerancia]`;
  3. `hash_detected` coincide con `hash_despues` del manifiesto.

La tercera condición es la que importa y es la que distingue este análisis de
un simple recuento de eventos. En el caso A el agente SÍ emite un evento —el
CLOSE_WRITE del descriptor— pero con el hash del contenido todavía íntegro.
Contar eventos sin mirar el hash daría "detectado" y sería falso: el evento
existe, la detección de la modificación no.

Por eso el reporte desglosa tres estados por operación:

  detectada          evento con el hash posterior a la modificación
  evento_sin_cambio  hubo evento, pero con el hash previo → EVASIÓN
  sin_evento         no hubo evento alguno

USO
---
    export DATABASE_URL='postgresql://fim:...@localhost:5432/fim'
    python3 scripts/analisis_mmap.py \
        --jsonl  results/bateria8/bateria8_cambios.jsonl \
        --salida results/bateria8/bateria8_correlacion.csv \
        --tolerancia-s 30
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
except ImportError:
    print("Falta psycopg. Instalar con: pip install 'psycopg[binary]'", file=sys.stderr)
    raise SystemExit(2)


CONSULTA = """
SELECT event_id, path, status, hash_detected, detected_at, received_at
FROM events
WHERE path = %(path)s
  AND detected_at > %(desde)s
  AND detected_at <= %(hasta)s
ORDER BY detected_at ASC
"""


def parse_iso(valor: str) -> datetime:
    dt = datetime.fromisoformat(valor)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True, type=Path)
    ap.add_argument("--salida", type=Path, default=Path("bateria8_correlacion.csv"))
    ap.add_argument("--tolerancia-s", type=float, default=30.0,
                    help="Ventana posterior a la operación en la que se busca el evento")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = ap.parse_args(argv)

    if not args.database_url:
        print("Falta DATABASE_URL (variable de entorno o --database-url)", file=sys.stderr)
        return 2

    operaciones = [json.loads(linea) for linea in args.jsonl.read_text().splitlines() if linea.strip()]
    print(f"Operaciones en el manifiesto: {len(operaciones)}")

    filas: list[dict[str, Any]] = []
    with psycopg.connect(args.database_url) as conn:
        for op in operaciones:
            ts = parse_iso(op["ts_utc"])
            with conn.cursor() as cur:
                cur.execute(CONSULTA, {
                    "path": op["ruta_agente"],
                    "desde": ts - timedelta(seconds=1),   # margen por redondeo del reloj
                    "hasta": ts + timedelta(seconds=args.tolerancia_s),
                })
                eventos = cur.fetchall()

            hashes = {e[3] for e in eventos}
            if op["hash_despues"] in hashes:
                estado = "detectada"
            elif eventos:
                estado = "evento_sin_cambio"
            else:
                estado = "sin_evento"

            filas.append({
                "seq": op["seq"],
                "caso": op["patron"],
                "ruta_agente": op["ruta_agente"],
                "ts_utc": op["ts_utc"],
                "modificacion_efectiva": op["modificacion_efectiva"],
                "deteccion_esperada": op["deteccion_agente_esperada"],
                "eventos_encontrados": len(eventos),
                "hash_antes": op["hash_antes"],
                "hash_despues": op["hash_despues"],
                "hashes_en_eventos": "|".join(sorted(h or "" for h in hashes)),
                "estado": estado,
            })

    # Guarda antes de tocar filas[0]: un JSONL vacío o truncado (corrida abortada,
    # --repeticiones 0) daría IndexError crudo y ni siquiera se llegaría al corte
    # de validez, que es lo único que dice si la corrida sirve.
    if not filas:
        print("CORRIDA NO VÁLIDA: el manifiesto no tiene operaciones correlacionables.")
        print(f"Revisar que {args.jsonl} exista y tenga líneas.")
        return 1

    with args.salida.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)

    # ── Resumen: las filas de la Tabla 17 ─────────────────────────────────────
    resumen: dict[str, dict[str, int]] = {}
    for f in filas:
        d = resumen.setdefault(f["caso"], {
            "n": 0, "modificacion_efectiva": 0, "detectada": 0,
            "evento_sin_cambio": 0, "sin_evento": 0, "eventos_totales": 0,
        })
        d["n"] += 1
        d["modificacion_efectiva"] += int(bool(f["modificacion_efectiva"]))
        d[f["estado"]] += 1
        d["eventos_totales"] += f["eventos_encontrados"]

    print(f"\nCSV: {args.salida}\n")
    print("TABLA 17 — filas para el Capítulo 5")
    print("-" * 96)
    print(f"{'Caso':28} {'Mod.efectivas':>14} {'Eventos':>9} {'Detectadas':>11} "
          f"{'Ev.sin cambio':>14} {'Sin evento':>11}")
    for caso in sorted(resumen):
        d = resumen[caso]
        print(f"{caso:28} {d['modificacion_efectiva']:>7}/{d['n']:<6} {d['eventos_totales']:>9} "
              f"{d['detectada']:>7}/{d['n']:<3} {d['evento_sin_cambio']:>14} {d['sin_evento']:>11}")
    print("-" * 96)

    # ── Validez de la corrida ─────────────────────────────────────────────────
    testigo = resumen.get("C_escritura_convencional")
    print()
    if testigo is None:
        print("AVISO: no hay caso C en el manifiesto. La corrida no tiene testigo de validez.")
    elif testigo["detectada"] != testigo["n"]:
        print(f"CORRIDA NO VÁLIDA: el testigo (caso C) detectó {testigo['detectada']}/{testigo['n']}.")
        print("El agente no estaba monitoreando el directorio o no estaba corriendo.")
        print("Un cero en el caso A NO prueba evasión mientras el testigo no dé 100 %.")
        return 1
    else:
        print(f"Corrida válida: el testigo (caso C) detectó {testigo['n']}/{testigo['n']}.")

    a = resumen.get("A_mmap_close_previo")
    b = resumen.get("B_mmap_close_posterior")
    if a and b:
        print(f"\nEvasión (caso A): {a['n'] - a['detectada']}/{a['n']} modificaciones no detectadas.")
        if a["evento_sin_cambio"]:
            print(f"  De ellas, {a['evento_sin_cambio']} produjeron evento con el hash PREVIO:")
            print("  el CLOSE_WRITE se emitió antes de la escritura sobre el mapeo.")
        print(f"Control (caso B): {b['detectada']}/{b['n']} detectadas.")
        print("\nEl contraste A vs. B es el resultado. Si B detecta y A no, la evasión")
        print("depende del orden de operaciones y no del mapeo en sí.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
