#!/usr/bin/env python3
"""A-3: descompone el drenaje de la Batería 5 (resiliencia) en cuatro tramos.

Entradas
    --log      log de la batería (bateria5_<run>.log). Instante t0: la línea
               `FIN_CORTE` (Valkey restaurado); si el log es anterior a esa marca,
               la línea que contiene `(t0)`. El instante es el prefijo [..] de la línea.
    --traza    traza del agente (JSONL, también .gz). Se toma el PRIMER registro
               `xadd_succeeded` estrictamente posterior a t0.
    --eventos  eventos.csv del backend (columna received_at): primer y último received_at.
    --backend-pre / --backend-post   (opcionales) salida de `docker inspect` del
               backend antes y después del corte: JSON de `docker inspect` o líneas
               clave=valor (`id=`, `started_at=`, `restart_count=`).

Salida (clave=valor, o JSON con --json), en segundos
    reconexion_agente = primer xadd_succeeded - t0         (el agente vuelve a publicar)
    sin_consumo       = primer received_at - primer xadd   (publicado, nadie consume)
    consumo           = último received_at - primer received_at   (ventana de ingesta activa)
    drenaje           = último received_at - t0            (= suma de los tres)
    + backend_started_at_pre/post, restart_count_pre/post, backend_reiniciado si se dieron.

Sólo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_TZ_CORTO = re.compile(r"([+-]\d{2})$")
_PREFIJO = re.compile(r"^\[([^\]]+)\]")


def parse_ts(valor: str) -> datetime:
    """ISO 8601 con 'Z', '+00:00' o '+00' (psql); hasta nanosegundos en la fracción."""
    s = valor.strip().replace("Z", "+00:00")
    s = _TZ_CORTO.sub(r"\1:00", s)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)  # el log de la batería trae nanosegundos
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def abrir(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8")


def instante_t0(log: Path) -> tuple[datetime, str]:
    fin = alt = None
    for linea in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _PREFIJO.match(linea)
        if not m:
            continue
        if "FIN_CORTE" in linea and fin is None:
            fin = (parse_ts(m.group(1)), "FIN_CORTE")
        elif "(t0)" in linea and alt is None:
            alt = (parse_ts(m.group(1)), "(t0)")
    if fin or alt:
        return fin or alt  # type: ignore[return-value]
    raise ValueError(f"{log}: sin línea FIN_CORTE ni '(t0)'")


def primer_xadd_posterior(traza: Path, t0: datetime) -> datetime:
    for linea in abrir(traza):
        if "xadd_succeeded" not in linea:
            continue
        try:
            rec = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if rec.get("stage") != "xadd_succeeded":
            continue
        ts = parse_ts(rec["timestamp"])
        if ts > t0:
            return ts
    raise ValueError(f"{traza}: ningún xadd_succeeded posterior a t0")


def extremos_received(csv_path: Path) -> tuple[datetime, datetime]:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        vals = [parse_ts(r["received_at"]) for r in csv.DictReader(fh)]
    if not vals:
        raise ValueError(f"{csv_path}: sin filas")
    return min(vals), max(vals)


def leer_inspect(path: Path) -> dict[str, str]:
    texto = path.read_text(encoding="utf-8").strip()
    if texto.startswith("["):
        d = json.loads(texto)[0]
        return {"id": d.get("Id", ""), "started_at": d["State"]["StartedAt"],
                "restart_count": str(d.get("RestartCount", 0))}
    out: dict[str, str] = {}
    for tok in re.findall(r"(\w+)=(\S+)", texto):
        out[tok[0]] = tok[1]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--traza", type=Path, required=True)
    ap.add_argument("--eventos", type=Path, required=True)
    ap.add_argument("--backend-pre", type=Path)
    ap.add_argument("--backend-post", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        t0, origen = instante_t0(args.log)
        xadd = primer_xadd_posterior(args.traza, t0)
        primero, ultimo = extremos_received(args.eventos)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    seg = lambda a, b: round((a - b).total_seconds(), 3)  # noqa: E731
    res: dict[str, object] = {
        "t0_origen": origen,
        "t0": t0.isoformat(),
        "primer_xadd": xadd.isoformat(),
        "primer_received_at": primero.isoformat(),
        "ultimo_received_at": ultimo.isoformat(),
        "reconexion_agente": seg(xadd, t0),
        "sin_consumo": seg(primero, xadd),
        "consumo": seg(ultimo, primero),
        "drenaje": seg(ultimo, t0),
    }
    if args.backend_pre and args.backend_post and args.backend_pre.is_file() and args.backend_post.is_file():
        pre, post = leer_inspect(args.backend_pre), leer_inspect(args.backend_post)
        res.update({
            "backend_started_at_pre": pre.get("started_at"),
            "backend_started_at_post": post.get("started_at"),
            "restart_count_pre": pre.get("restart_count"),
            "restart_count_post": post.get("restart_count"),
            "backend_reiniciado": (pre.get("id") != post.get("id")
                                   or pre.get("started_at") != post.get("started_at")
                                   or pre.get("restart_count") != post.get("restart_count")),
        })
    if args.json:
        print(json.dumps(res))
    else:
        for k, v in res.items():
            print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
