#!/usr/bin/env python3
"""A-1: P99 de latencia por archivo y combinado, con IC95 por bootstrap.

Lee la columna `latencia_ms` de cada CSV (la que exporta la Batería 3 en
latencia/run-0N/eventos.csv: (received_at - detected_at) en ms). Para cada archivo y
para el conjunto combinado (todas las muestras juntas) informa n, P99 muestral y el
IC95 percentil [2,5 %; 97,5 %] de 10.000 remuestreos con reemplazo.

P99 = interpolación lineal entre rangos (igual que pandas `quantile(0.99)` y que
lab/latencia.py), de modo que el valor puntual coincide con resumen.txt.

Reproducible: cada serie usa su propio random.Random(--seed) (default 20261001), así el
resultado de un archivo no depende de cuáles otros se pasaron ni del orden.

Uso:
    python3 scripts/p99_bootstrap.py <paquete|eventos.csv> [...] [--json]
    p. ej.: python3 scripts/p99_bootstrap.py tesis/cierre/evidencia/v5-eval-<ts>/latencia

Un directorio se expande a sus latencia/run-*/eventos.csv o run-*/eventos.csv.
Las latencias negativas NO se descartan (se informan: son reloj, no sistema).
Sólo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

COLUMNA = "latencia_ms"


def p99(valores_ordenados: list[float], p: float = 99.0) -> float:
    v = valores_ordenados
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def bootstrap_ic95(valores: list[float], iteraciones: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(valores)
    estimaciones = sorted(p99(sorted(rng.choices(valores, k=n))) for _ in range(iteraciones))
    return p99(estimaciones, 2.5), p99(estimaciones, 97.5)


def resumen(nombre: str, valores: list[float], iteraciones: int, seed: int) -> dict[str, object]:
    lo, hi = bootstrap_ic95(valores, iteraciones, seed)
    return {
        "serie": nombre,
        "n": len(valores),
        "negativos": sum(1 for x in valores if x < 0),
        "p99_ms": round(p99(sorted(valores)), 3),
        "ic95_bajo_ms": round(lo, 3),
        "ic95_alto_ms": round(hi, 3),
    }


def expandir(entradas: list[Path]) -> list[Path]:
    archivos: list[Path] = []
    for e in entradas:
        if e.is_dir():
            hallados = sorted(e.glob("latencia/run-*/eventos.csv")) or sorted(e.glob("run-*/eventos.csv")) \
                or sorted(e.glob("eventos.csv"))
            archivos.extend(hallados)
        else:
            archivos.append(e)
    return archivos


def leer(path: Path) -> list[float]:
    with path.open(newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        if COLUMNA not in (rd.fieldnames or []):
            raise ValueError(f"{path}: no tiene la columna {COLUMNA} (tiene {rd.fieldnames})")
        return [float(r[COLUMNA]) for r in rd if r[COLUMNA] not in ("", None)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entradas", nargs="+", type=Path)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--iteraciones", type=int, default=10_000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    archivos = expandir(args.entradas)
    if not archivos:
        print("ERROR: no se encontró ningún eventos.csv", file=sys.stderr)
        return 2
    try:
        por_archivo = [(a, leer(a)) for a in archivos]
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    vacios = [str(a) for a, v in por_archivo if not v]
    if vacios:
        print(f"ERROR: sin muestras: {vacios}", file=sys.stderr)
        return 2

    filas = [resumen(str(a), v, args.iteraciones, args.seed) for a, v in por_archivo]
    if len(por_archivo) > 1:
        combinado = [x for _, v in por_archivo for x in v]
        filas.append(resumen("combinado", combinado, args.iteraciones, args.seed))
    meta = {"seed": args.seed, "iteraciones": args.iteraciones, "ic": "percentil 2.5-97.5",
            "p99": "interpolacion lineal", "columna": COLUMNA}
    if args.json:
        print(json.dumps({"meta": meta, "series": filas}, indent=2))
    else:
        print(f"# seed={args.seed} bootstrap={args.iteraciones} IC95 percentil, P99 interpolacion lineal")
        print("serie\tn\tnegativos\tp99_ms\tic95_bajo_ms\tic95_alto_ms")
        for f in filas:
            print("\t".join(str(f[k]) for k in ("serie", "n", "negativos", "p99_ms", "ic95_bajo_ms", "ic95_alto_ms")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
