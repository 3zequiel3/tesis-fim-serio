#!/usr/bin/env python3
"""
Cruce manifiesto (P2) x grupo de control (P3) — ítems 45, 47, 49 y 50 del Cap. 5.

Ver docs/plan_medicion_cap5.md, "Batería 7 — Grupo de control".

QUÉ HACE
--------
Toma el manifiesto del generador (`bateria3_manifiesto.json`, timestamp real de
cada cambio) y el CSV del escáner periódico (`bateria7_control.csv`, timestamp de
detección) y los cruza por `ruta_agente` para producir:

  * ítem 45 -> mediana de la latencia del script cron
  * ítem 47 -> P99 de la latencia del script cron
  * ítem 49 -> eventos perdidos por el script cron, con el desglose de la causa
  * ítem 50 -> factor de mejora, si se le pasa la mediana de la plataforma FIM

ATRIBUCIÓN
----------
Cada detección del control corresponde a un archivo y a un intervalo
`(scan_previo, scan]`. Puede haber N cambios reales del manifiesto dentro de ese
intervalo para el mismo archivo, y el cron solo ve uno: ese es el colapso.

  * `--criterio primer_cambio` (default): la detección se atribuye al primer
    cambio del intervalo — el instante en que el archivo dejó de coincidir con
    el último estado conocido como bueno. Es la lectura de seguridad: mide
    cuánto tiempo estuvo comprometido sin ser visto.
  * `--criterio ultimo_cambio`: se atribuye al último cambio del intervalo. Es
    la cota inferior de la latencia. Reportar cuál se usó.

Los cambios del manifiesto que no reciben atribución son los perdidos (ítem 49),
clasificados por causa: `colapsado` (hubo detección del archivo en el intervalo,
pero se la llevó otro cambio), `no_detectado` (revertido o efímero: el cron nunca
vio nada) y `fuera_de_ventana` (ocurrió antes del primer scan o después del
último; se informa aparte y por default NO cuenta como pérdida).

PERCENTILES
-----------
Interpolación lineal, idéntica a `pandas.Series.quantile(q)` con su default
(`interpolation="linear"`), y desvío muestral (ddof=1). No requiere pandas; si
se prefiere la agregación oficial con pandas, `bateria7_latencias.csv` trae una
fila por latencia lista para `pd.read_csv(...)["latencia_ms"]`.

USO
---
    python3 scripts/analisis_control.py \
        --manifiesto resultados/bateria3_manifiesto.json \
        --control    resultados/bateria7_control.csv \
        --salida     resultados/bateria7_latencias.csv \
        --mediana-fim-ms 13.92

NOTAS
-----
  * No requiere root ni dependencias externas (solo stdlib).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SALIDA_COLUMNS = [
    "scan_id",
    "ruta_agente",
    "operacion_control",
    "operacion_manifiesto",
    "patron_manifiesto",
    "seq_manifiesto",
    "ts_cambio_epoch",
    "ts_cambio_utc",
    "ts_deteccion_epoch",
    "ts_deteccion_utc",
    "latencia_ms",
]


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def quantile_lineal(datos: list[float], q: float) -> float:
    """Percentil con interpolación lineal — mismo resultado que Series.quantile(q)."""
    if not datos:
        return float("nan")
    ordenados = sorted(datos)
    if len(ordenados) == 1:
        return ordenados[0]
    pos = q * (len(ordenados) - 1)
    bajo = math.floor(pos)
    alto = math.ceil(pos)
    if bajo == alto:
        return ordenados[int(pos)]
    return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (pos - bajo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="analisis_control.py",
        description="Cruza el manifiesto del generador con el CSV del grupo de control.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--manifiesto", required=True, help="bateria3_manifiesto.json (P2)")
    ap.add_argument("--control", required=True, help="bateria7_control.csv (P3)")
    ap.add_argument("--salida", default="resultados/bateria7_latencias.csv",
                    help="CSV con una fila por detección atribuida.")
    ap.add_argument("--criterio", choices=("primer_cambio", "ultimo_cambio"),
                    default="primer_cambio", help="Cambio al que se atribuye cada detección.")
    ap.add_argument("--mediana-fim-ms", type=float, default=None,
                    help="Ítem 44 (mediana de la plataforma FIM) para calcular el ítem 50.")
    ap.add_argument("--p99-fim-ms", type=float, default=None,
                    help="Ítem 46 (P99 de la plataforma FIM), para el cociente de P99.")
    ap.add_argument("--incluir-fuera-de-ventana", action="store_true",
                    help="Contar como perdidos los cambios previos al primer scan o "
                         "posteriores al último.")
    ap.add_argument("--inicio-cobertura-epoch", type=float, default=None,
                    help="Override del inicio de la cobertura del control.")
    ap.add_argument("--fin-cobertura-epoch", type=float, default=None,
                    help="Override del fin de la cobertura del control.")
    args = ap.parse_args(argv)

    manifiesto = json.loads(Path(args.manifiesto).read_text(encoding="utf-8"))
    cambios: list[dict[str, Any]] = manifiesto["cambios"]

    por_ruta: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cambios:
        if c.get("error"):
            continue
        por_ruta[c["ruta_agente"]].append(c)
    for lista in por_ruta.values():
        lista.sort(key=lambda c: c["ts_epoch"])

    with Path(args.control).open(newline="", encoding="utf-8") as fh:
        detecciones = [row for row in csv.DictReader(fh) if row.get("scan_id")]

    if not detecciones:
        print("aviso: el CSV del control no tiene ninguna detección", file=sys.stderr)

    atribuidos: set[int] = set()
    filas: list[dict[str, Any]] = []
    detecciones_por_intervalo: dict[tuple[str, str], bool] = {}
    sin_correspondencia = 0

    for row in detecciones:
        ts_scan = float(row["ts_scan_epoch"])
        prev_raw = row.get("ts_scan_previo_epoch") or ""
        ts_prev = float(prev_raw) if prev_raw else float("-inf")
        ruta = row["ruta_agente"]
        detecciones_por_intervalo[(ruta, row["scan_id"])] = True

        candidatos = [c for c in por_ruta.get(ruta, []) if ts_prev < c["ts_epoch"] <= ts_scan]
        if not candidatos:
            sin_correspondencia += 1
            continue

        elegido = candidatos[0] if args.criterio == "primer_cambio" else candidatos[-1]
        atribuidos.add(elegido["seq"])
        filas.append({
            "scan_id": row["scan_id"],
            "ruta_agente": ruta,
            "operacion_control": row["operacion"],
            "operacion_manifiesto": elegido["operacion"],
            "patron_manifiesto": elegido["patron"],
            "seq_manifiesto": elegido["seq"],
            "ts_cambio_epoch": f"{elegido['ts_epoch']:.6f}",
            "ts_cambio_utc": elegido["ts_utc"],
            "ts_deteccion_epoch": f"{ts_scan:.6f}",
            "ts_deteccion_utc": row["ts_scan_utc"],
            "latencia_ms": f"{(ts_scan - elegido['ts_epoch']) * 1000.0:.3f}",
        })

    # Cobertura temporal del control.
    prevs = [float(r["ts_scan_previo_epoch"]) for r in detecciones if r.get("ts_scan_previo_epoch")]
    scans = [float(r["ts_scan_epoch"]) for r in detecciones]
    inicio_cob = args.inicio_cobertura_epoch if args.inicio_cobertura_epoch is not None else (
        min(prevs) if prevs else (min(scans) if scans else None))
    fin_cob = args.fin_cobertura_epoch if args.fin_cobertura_epoch is not None else (
        max(scans) if scans else None)

    # Clasificación de los cambios no atribuidos (ítem 49).
    causas: dict[str, int] = defaultdict(int)
    patrones_perdidos: dict[str, int] = defaultdict(int)
    fuera_de_ventana = 0
    perdidos = 0
    con_error = sum(1 for c in cambios if c.get("error"))

    scans_ordenados = sorted(set(scans))

    def scan_del_cambio(ts: float) -> str | None:
        """Primer scan posterior o igual al cambio (el que debería haberlo visto)."""
        for s in scans_ordenados:
            if ts <= s:
                return f"{s:.6f}"
        return None

    scan_id_por_ts = {f"{float(r['ts_scan_epoch']):.6f}": r["scan_id"] for r in detecciones}

    for c in cambios:
        if c.get("error"):
            continue
        if c["seq"] in atribuidos:
            continue
        ts = c["ts_epoch"]
        if inicio_cob is None or fin_cob is None or ts <= inicio_cob or ts > fin_cob:
            fuera_de_ventana += 1
            if not args.incluir_fuera_de_ventana:
                continue
            causas["fuera_de_ventana"] += 1
            perdidos += 1
            patrones_perdidos[c["patron"]] += 1
            continue
        clave_ts = scan_del_cambio(ts)
        scan_id = scan_id_por_ts.get(clave_ts or "")
        hubo_deteccion = bool(scan_id) and detecciones_por_intervalo.get(
            (c["ruta_agente"], scan_id), False)
        causas["colapsado" if hubo_deteccion else "no_detectado"] += 1
        patrones_perdidos[c["patron"]] += 1
        perdidos += 1

    latencias = [float(f["latencia_ms"]) for f in filas]

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    with salida.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SALIDA_COLUMNS)
        writer.writeheader()
        for fila in filas:
            writer.writerow(fila)

    total_manifiesto = len(cambios) - con_error
    p = print
    p("=" * 72)
    p("Batería 7 — grupo de control (cron de hashing) vs. manifiesto del generador")
    p("=" * 72)
    p(f"  manifiesto              = {args.manifiesto}")
    p(f"  control                 = {args.control}")
    p(f"  criterio de atribución  = {args.criterio}")
    p(f"  salida                  = {salida}")
    if inicio_cob is not None and fin_cob is not None:
        p(f"  cobertura del control   = {iso_utc(inicio_cob)} .. {iso_utc(fin_cob)}")
    p("-" * 72)
    p(f"  cambios reales (manifiesto)      = {total_manifiesto}")
    if con_error:
        p(f"  cambios con error (excluidos)    = {con_error}")
    p(f"  detecciones del control          = {len(detecciones)}")
    p(f"  detecciones atribuidas           = {len(filas)}")
    if sin_correspondencia:
        p(f"  detecciones sin correspondencia  = {sin_correspondencia} "
          f"(archivos ajenos al generador)")
    p(f"  cambios fuera de la cobertura    = {fuera_de_ventana}"
      f"{'' if args.incluir_fuera_de_ventana else ' (no contados como pérdida)'}")
    p("-" * 72)
    p("  ÍTEMS DEL CAPÍTULO 5")
    if latencias:
        p(f"  45  mediana latencia control (ms) = {quantile_lineal(latencias, 0.50):.3f}")
        p(f"  47  P99 latencia control (ms)     = {quantile_lineal(latencias, 0.99):.3f}")
        p(f"      media (ms)                    = {statistics.fmean(latencias):.3f}")
        if len(latencias) > 1:
            p(f"      desvío muestral ddof=1 (ms)   = {statistics.stdev(latencias):.3f}")
        p(f"      mínimo / máximo (ms)          = {min(latencias):.3f} / {max(latencias):.3f}")
        p(f"      n                             = {len(latencias)}")
    else:
        p("  45/47  sin latencias: el control no atribuyó ninguna detección")
    porcentaje = f" ({100.0 * perdidos / total_manifiesto:.1f} %)" if total_manifiesto else ""
    p(f"  49  eventos perdidos por el cron  = {perdidos} de {total_manifiesto}{porcentaje}")
    for causa, n in sorted(causas.items()):
        p(f"        causa {causa:18} = {n}")
    for patron, n in sorted(patrones_perdidos.items()):
        p(f"        patrón {patron:17} = {n}")
    if args.mediana_fim_ms is not None and latencias:
        mediana_control = quantile_lineal(latencias, 0.50)
        p(f"  50  factor de mejora (mediana)    = "
          f"{mediana_control / args.mediana_fim_ms:.1f}x "
          f"({mediana_control:.3f} ms / {args.mediana_fim_ms:.3f} ms)")
    if args.p99_fim_ms is not None and latencias:
        p99_control = quantile_lineal(latencias, 0.99)
        p(f"      factor de mejora (P99)        = "
          f"{p99_control / args.p99_fim_ms:.1f}x")
    p("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
