#!/usr/bin/env python3
"""
Grupo de control: escáner periódico por hashing — precondición P3 del Cap. 5.

Ver docs/plan_medicion_cap5.md §0 (P3) y "Batería 7 — Grupo de control".

QUÉ ES
------
El sustituto experimental del enfoque clásico tipo AIDE/Tripwire: un cron que
cada 15 minutos hashea el directorio vigilado y compara contra el hash de la
corrida anterior. Es el término de comparación contra el que se mide la
detección reactiva de la plataforma FIM.

Hasta hoy el Cap. 5 llenaba esa columna con `E[Uniform(0, 900 s)] = 450 s` — la
esperanza matemática de un script que nunca se escribió — y la presentaba como
comparación experimental. Este script es lo que cierra esa brecha.

QUÉ ÍTEMS DEL CAP. 5 ALIMENTA
-----------------------------
  * 45 -> mediana de latencia del script cron
  * 47 -> P99 de latencia del script cron
  * 49 -> eventos perdidos por el cron (manifiesto - detectados)
  * 50 -> factor de mejora (ítem 45 / ítem 44)

La latencia del control es `ts_deteccion - ts_modificacion_real`, donde el
timestamp real sale del manifiesto del generador (P2, scripts/generador_carga.py).
El join lo hace `scripts/analisis_control.py` por `ruta_agente`; por eso este
script emite tanto la ruta del host como la ruta tal cual la ve el agente.

CRITERIO DE COMPARACIÓN
-----------------------
Por default compara **solo el contenido** (SHA-256), que es el mismo criterio de
integridad que usa la plataforma FIM contra su baseline. Con `--incluir-metadatos`
además marca cambios de tamaño/mtime/modo. Es una diferencia con consecuencias
sobre el ítem 49 y hay que declararla en el capítulo:

  * solo hash  -> una modificación revertida dentro de la ventana es invisible;
  * con mtime  -> la reversión se detecta, pero N cambios sucesivos al mismo
                  archivo siguen colapsando en 1. La ceguera estructural del
                  muestreo periódico no desaparece.

USO
---
Corrida bajo demanda (y baseline inicial — correr ANTES del generador):

    python3 scripts/control_hashing.py \
        --dir fim-watch \
        --csv resultados/bateria7_control.csv \
        --state resultados/control_estado.json

Modo loop en primer plano, sin tocar crontab (declarar cuál se usó en el Cap. 5):

    python3 scripts/control_hashing.py --dir fim-watch \
        --csv resultados/bateria7_control.csv \
        --state resultados/control_estado.json --loop --interval 900

Entrada de crontab (cada 15 minutos = 900 s, alineada a :00 :15 :30 :45).
`crontab -e` y pegar, ajustando la ruta absoluta del repo:

    */15 * * * * cd /ruta/al/repo && /usr/bin/python3 scripts/control_hashing.py \
      --dir fim-watch --csv resultados/bateria7_control.csv \
      --state resultados/control_estado.json >> resultados/control_cron.log 2>&1

O directamente:  python3 scripts/control_hashing.py --print-cron --dir fim-watch

SALIDA
------
`bateria7_control.csv`, una fila por cambio detectado:

    scan_id, ts_scan_utc, ts_scan_epoch, ts_scan_previo_epoch,
    operacion, ruta_host, ruta_agente, hash_antes, hash_despues, bytes, motivo

`operacion` usa el mismo léxico que el manifiesto del generador:
`create` / `modify` / `delete`.

NOTAS
-----
  * No requiere root ni dependencias externas (solo stdlib).
  * El primer scan es la línea de base: no emite filas, solo deja el estado.
    Correrlo antes de arrancar el generador; si no, el primer scan real
    reportaría como "creados" todos los archivos preexistentes.
  * El estado (`--state`) es el equivalente a la base de datos de AIDE. Borrarlo
    con `--reset` reinicia la serie.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CSV_COLUMNS = [
    "scan_id",
    "ts_scan_utc",
    "ts_scan_epoch",
    "ts_scan_previo_epoch",
    "operacion",
    "ruta_host",
    "ruta_agente",
    "hash_antes",
    "hash_despues",
    "bytes",
    "motivo",
]


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def scan_tree(root: Path, glob: str, follow_symlinks: bool = False) -> dict[str, dict[str, Any]]:
    """Recorre el árbol y devuelve {ruta_relativa: {hash, bytes, mtime, modo}}."""
    snapshot: dict[str, dict[str, Any]] = {}
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        for name in filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root))
            if glob != "*" and not full.match(glob):
                continue
            try:
                st = full.stat()
                if not os.path.isfile(full):
                    continue
                snapshot[rel] = {
                    "hash": sha256_file(full),
                    "bytes": st.st_size,
                    "mtime": st.st_mtime,
                    "modo": st.st_mode & 0o7777,
                }
            except OSError as exc:
                # Un archivo puede desaparecer entre el walk y el stat: es
                # exactamente el punto ciego del muestreo periódico, se registra
                # pero no se interrumpe el scan.
                print(f"aviso: no se pudo hashear {full}: {exc}", file=sys.stderr)
    return snapshot


def diff_snapshots(
    previo: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
    incluir_metadatos: bool,
) -> list[dict[str, Any]]:
    """Compara dos snapshots y devuelve los cambios detectados."""
    cambios: list[dict[str, Any]] = []

    for rel in sorted(set(actual) - set(previo)):
        cambios.append({
            "operacion": "create",
            "rel": rel,
            "hash_antes": "",
            "hash_despues": actual[rel]["hash"],
            "bytes": actual[rel]["bytes"],
            "motivo": "alta",
        })

    for rel in sorted(set(previo) - set(actual)):
        cambios.append({
            "operacion": "delete",
            "rel": rel,
            "hash_antes": previo[rel]["hash"],
            "hash_despues": "",
            "bytes": "",
            "motivo": "baja",
        })

    for rel in sorted(set(previo) & set(actual)):
        antes, despues = previo[rel], actual[rel]
        motivos = []
        if antes["hash"] != despues["hash"]:
            motivos.append("hash")
        if incluir_metadatos:
            if antes["bytes"] != despues["bytes"]:
                motivos.append("tamano")
            if antes["mtime"] != despues["mtime"]:
                motivos.append("mtime")
            if antes["modo"] != despues["modo"]:
                motivos.append("modo")
        if motivos:
            cambios.append({
                "operacion": "modify",
                "rel": rel,
                "hash_antes": antes["hash"],
                "hash_despues": despues["hash"],
                "bytes": despues["bytes"],
                "motivo": "+".join(motivos),
            })

    return cambios


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"scan_id": 0, "ts_scan_epoch": None, "snapshot": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def append_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        if nuevo:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_scan(args: argparse.Namespace) -> int:
    root = Path(args.dir).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} no existe o no es un directorio", file=sys.stderr)
        return 2

    state_path = Path(args.state)
    csv_path = Path(args.csv)
    state = load_state(state_path)

    inicio = time.time()
    snapshot = scan_tree(root, args.glob, args.follow_symlinks)
    fin = time.time()

    scan_id = int(state.get("scan_id", 0)) + 1
    previo_epoch = state.get("ts_scan_epoch")
    baseline = previo_epoch is None

    if baseline:
        cambios: list[dict[str, Any]] = []
    else:
        cambios = diff_snapshots(state.get("snapshot", {}), snapshot, args.incluir_metadatos)

    prefix = args.agent_prefix.rstrip("/")
    rows = [{
        "scan_id": scan_id,
        "ts_scan_utc": iso_utc(fin),
        "ts_scan_epoch": f"{fin:.6f}",
        "ts_scan_previo_epoch": "" if previo_epoch is None else f"{previo_epoch:.6f}",
        "operacion": c["operacion"],
        "ruta_host": str(root / c["rel"]),
        "ruta_agente": f"{prefix}/{c['rel']}",
        "hash_antes": c["hash_antes"],
        "hash_despues": c["hash_despues"],
        "bytes": c["bytes"],
        "motivo": c["motivo"],
    } for c in cambios]

    if rows:
        append_rows(csv_path, rows)
    elif baseline and not csv_path.exists():
        append_rows(csv_path, [])  # deja el CSV con encabezado desde el arranque

    save_state(state_path, {
        "scan_id": scan_id,
        "ts_scan_epoch": fin,
        "ts_scan_utc": iso_utc(fin),
        "dir": str(root),
        "glob": args.glob,
        "incluir_metadatos": args.incluir_metadatos,
        "snapshot": snapshot,
    })

    etiqueta = "baseline" if baseline else "diff"
    print(
        f"[control] scan_id={scan_id} ({etiqueta}) ts={iso_utc(fin)} "
        f"archivos={len(snapshot)} cambios={len(rows)} "
        f"duracion_scan_s={fin - inicio:.3f} csv={csv_path}",
        flush=True,
    )
    return 0


def print_cron(args: argparse.Namespace) -> int:
    repo = Path.cwd()
    minutos = max(1, int(args.interval // 60))
    print(
        f"*/{minutos} * * * * cd {repo} && {sys.executable} scripts/control_hashing.py "
        f"--dir {args.dir} --csv {args.csv} --state {args.state} "
        f"--agent-prefix {args.agent_prefix} >> resultados/control_cron.log 2>&1"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="control_hashing.py",
        description="Grupo de control: escáner periódico por hashing (P3, Batería 7).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dir", required=True, help="Directorio vigilado en el host (ej: fim-watch)")
    ap.add_argument("--csv", default="resultados/bateria7_control.csv",
                    help="CSV acumulativo de detecciones (ítems 45, 47, 49).")
    ap.add_argument("--state", default="resultados/control_estado.json",
                    help="Estado del scan previo — el equivalente a la base de AIDE.")
    ap.add_argument("--agent-prefix", default="/watch",
                    help="Prefijo con el que el agente ve el directorio (join con el manifiesto).")
    ap.add_argument("--glob", default="*", help="Filtro de archivos a hashear.")
    ap.add_argument("--follow-symlinks", action="store_true",
                    help="Seguir symlinks al recorrer el árbol (default: no).")
    ap.add_argument("--incluir-metadatos", action="store_true",
                    help="Además del hash, marcar cambios de tamaño/mtime/modo.")
    ap.add_argument("--interval", type=float, default=900.0,
                    help="Segundos entre scans en modo --loop / --print-cron (default 900 = 15 min).")
    ap.add_argument("--loop", action="store_true",
                    help="Corre indefinidamente cada --interval segundos, sin cron.")
    ap.add_argument("--iterations", type=int, default=0,
                    help="Con --loop, cantidad de scans a ejecutar (0 = infinito).")
    ap.add_argument("--reset", action="store_true",
                    help="Descarta el estado previo antes de arrancar (reinicia la serie).")
    ap.add_argument("--print-cron", action="store_true",
                    help="Imprime la entrada de crontab y sale.")
    args = ap.parse_args(argv)

    if args.print_cron:
        return print_cron(args)

    if args.reset:
        Path(args.state).unlink(missing_ok=True)
        print(f"[control] estado {args.state} descartado (--reset)")

    if not args.loop:
        return run_scan(args)

    if args.interval <= 0:
        ap.error("--interval debe ser > 0")

    i = 0
    base = time.monotonic()
    while True:
        rc = run_scan(args)
        if rc != 0:
            return rc
        i += 1
        if args.iterations and i >= args.iterations:
            return 0
        objetivo = base + i * args.interval
        pendiente = objetivo - time.monotonic()
        if pendiente > 0:
            try:
                time.sleep(pendiente)
            except KeyboardInterrupt:
                print("[control] interrumpido")
                return 130


if __name__ == "__main__":
    raise SystemExit(main())
