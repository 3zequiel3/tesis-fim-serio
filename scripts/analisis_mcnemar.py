#!/usr/bin/env python3
"""McNemar test and Newcombe paired interval over the operation-by-operation table.

Section 3.6 of the thesis specifies this procedure but it was never executed,
because the paired table was missing: the descriptive comparison comes from two
separate marginal counts, which does not support an inference about the paired
difference. This builds the table operation by operation and runs the test.

Each of the generator's operations is one paired observation: whether the FIM
platform reported it, and whether the control scanner reported it. Both arms see
exactly the same operations on the same host in the same window, which is what
makes the pairing legitimate.

Reference for the interval: Newcombe, R. G. (1998). Improved confidence intervals
for the difference between binomial proportions based on paired data. Statistics
in Medicine, 17(22), 2635-2650 (method 10, score intervals with correlation
correction). No external dependencies.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

Z = 1.959963984540054  # two-sided 95 %


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    """Wilson score interval, the building block Newcombe's method 10 uses."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 2 * (n + z * z)
    centre = (2 * n * p + z * z) / denom
    half = z * math.sqrt(z * z + 4 * n * p * (1 - p)) / denom
    return centre - half, centre + half


def newcombe_paired(a: int, b: int, c: int, d: int) -> tuple[float, float, float]:
    """Difference of paired proportions with Newcombe's method 10 interval.

    The table is FIM (rows) by control (columns): a both, b FIM only,
    c control only, d neither.
    """
    n = a + b + c + d
    p1 = (a + b) / n  # FIM detection rate
    p2 = (a + c) / n  # control detection rate
    delta = p1 - p2

    l1, u1 = wilson(a + b, n)
    l2, u2 = wilson(a + c, n)

    # Correlation correction. Undefined when a margin is empty, and Newcombe
    # sets it to zero there rather than leaving the interval undefined.
    margins = (a + b) * (c + d) * (a + c) * (b + d)
    phi = ((a * d - b * c) / math.sqrt(margins)) if margins > 0 else 0.0

    lo_term = (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2
    hi_term = (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2
    lower = delta - math.sqrt(max(lo_term, 0.0))
    upper = delta + math.sqrt(max(hi_term, 0.0))
    return delta, lower, upper


def mcnemar(b: int, c: int) -> tuple[float, float]:
    """McNemar statistic with continuity correction, and its p-value.

    Only the discordant pairs carry information: an operation both arms caught,
    or both missed, says nothing about which arm is better.
    """
    if b + c == 0:
        return 0.0, 1.0
    chi2 = (abs(b - c) - 1) ** 2 / (b + c)
    p = math.erfc(math.sqrt(chi2 / 2))  # survival of chi-square with 1 df
    return chi2, p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifiesto", required=True, help="bateria3_manifiesto.json — the operations performed")
    ap.add_argument("--eventos", required=True, help="eventos_backend.csv — what the FIM platform persisted")
    ap.add_argument("--control", required=True, help="bateria7_latencias.csv — attributed control detections")
    ap.add_argument("--salida", help="CSV with one row per paired observation")
    ap.add_argument("--tolerancia-s", type=float, default=1.5,
                    help="Window to match an event to its operation by time (default 1.5 s)")
    args = ap.parse_args()

    manifiesto = json.loads(Path(args.manifiesto).read_text())
    ops = manifiesto["cambios"]

    # FIM arm. The export carries no path column, so the match is by time; at
    # 0.28 operations per second the spacing dwarfs the observed latency, whose
    # maximum was under 80 ms.
    eventos = []
    with open(args.eventos) as fh:
        for row in csv.DictReader(fh):
            eventos.append([datetime.fromisoformat(row["detected_at"]).timestamp(), False])
    eventos.sort()

    fim = {}
    for op in ops:
        best, best_d = None, args.tolerancia_s
        for ev in eventos:
            if ev[1]:
                continue
            dist = abs(ev[0] - op["ts_epoch"])
            if dist < best_d:
                best, best_d = ev, dist
        fim[op["seq"]] = best is not None
        if best is not None:
            best[1] = True

    # Control arm, already attributed to a manifest operation by analisis_control.py.
    control = set()
    with open(args.control) as fh:
        for row in csv.DictReader(fh):
            control.add(int(row["seq_manifiesto"]))

    a = b = c = d = 0
    filas = []
    for op in ops:
        f, k = fim[op["seq"]], op["seq"] in control
        if f and k:
            a += 1
        elif f and not k:
            b += 1
        elif not f and k:
            c += 1
        else:
            d += 1
        filas.append({"seq": op["seq"], "patron": op["patron"], "operacion": op["operacion"],
                      "ruta_agente": op["ruta_agente"], "fim": int(f), "control": int(k)})

    n = a + b + c + d
    delta, lo, hi = newcombe_paired(a, b, c, d)
    chi2, p = mcnemar(b, c)

    print("=" * 72)
    print("  Tabla pareada — una observación por operación del generador")
    print("=" * 72)
    print(f"  {'':22s}{'control sí':>12s}{'control no':>12s}{'total':>10s}")
    print(f"  {'FIM sí':22s}{a:>12d}{b:>12d}{a + b:>10d}")
    print(f"  {'FIM no':22s}{c:>12d}{d:>12d}{c + d:>10d}")
    print(f"  {'total':22s}{a + c:>12d}{b + d:>12d}{n:>10d}")
    print("-" * 72)
    print(f"  proporción detectada, FIM      = {(a + b) / n:.4f}  ({a + b}/{n})")
    print(f"  proporción detectada, control  = {(a + c) / n:.4f}  ({a + c}/{n})")
    print(f"  diferencia pareada             = {delta:.4f}")
    print(f"  IC 95 % de Newcombe (pareado)  = [{lo:.4f}, {hi:.4f}]")
    print("-" * 72)
    print(f"  pares discordantes             = b {b}  /  c {c}")
    print(f"  McNemar con corrección chi2(1) = {chi2:.4f}")
    print(f"  valor p                        = {p:.6g}" + ("  (bajo el mínimo representable)" if p == 0.0 else ""))
    print("=" * 72)

    if args.salida:
        with open(args.salida, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0]))
            w.writeheader()
            w.writerows(filas)
        print(f"  tabla pareada escrita en {args.salida}")


if __name__ == "__main__":
    main()
