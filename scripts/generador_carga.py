#!/usr/bin/env python3
"""
Generador de carga reproducible — precondición P2 del plan de medición del Cap. 5.

Ver docs/plan_medicion_cap5.md §0 (P2) y el "Entregable esperado".

QUÉ HACE
--------
Produce cambios de filesystem controlados sobre el directorio vigilado por el
agente FIM (`fim-watch/` en el host -> `/watch` dentro del contenedor), a tasa
fija, con semilla explícita, y emite un **manifiesto JSON** con el timestamp
real de cada cambio.

QUÉ ÍTEMS DEL CAP. 5 ALIMENTA
-----------------------------
  * 9 y 48  -> eventos perdidos = |manifiesto| - eventos recibidos en `events`.
               El manifiesto es el minuendo; sin él el ítem 9 no se puede calcular.
  * 37      -> eventos generados durante la desconexión (Batería 5).
  * 45, 47, 49, 50 -> el manifiesto aporta el timestamp real de modificación
               contra el que se mide la latencia del grupo de control (P3).
  * 54      -> semilla y parámetros del generador: se loguean completos al
               arrancar (archivo `--log`) y quedan embebidos en el manifiesto.
  * Repetibilidad de las Baterías 3, 4, 5 y 7.

PATRONES CIEGOS PARA EL ESCÁNER PERIÓDICO
-----------------------------------------
El grupo de control (`scripts/control_hashing.py`) es estructuralmente incapaz
de ver dos cosas. El generador las produce a propósito para que el ítem 49 mida
algo real en vez de dar un empate artificial:

  1. `revertido`  (`--revert-frac`): un archivo se modifica y se restaura byte a
     byte poco después. Entre dos scans consecutivos el hash no cambió: el cron
     no ve nada, la plataforma FIM ve 2 eventos.
  2. `colapsado`  (`--burst-frac`, `--burst-size`): N modificaciones sucesivas al
     mismo archivo. El cron detecta 1 cambio, la plataforma ve N.
  3. `efimero`    (`--ephemeral-frac`): un archivo se crea y se borra antes del
     próximo scan. El cron nunca lo vio existir.

La columna `deteccion_control_esperada` del manifiesto registra esa *intención de
diseño*. La verificación empírica la hace `scripts/analisis_control.py` cruzando
el manifiesto contra el CSV real del control: no se asume, se mide.

USO
---
Batería 3 (500 eventos, 30 min sostenidos, mezcla 20/70/10):

    python3 scripts/generador_carga.py \
        --dir fim-watch \
        --seed 20260818 \
        --rate 0.2778 \
        --count 500 \
        --mix 20/70/10 \
        --manifest resultados/bateria3_manifiesto.json \
        --log resultados/bateria3_generador.log

Batería 5 (3.000 eventos durante el corte de 300 s -> 10 ev/s):

    python3 scripts/generador_carga.py \
        --dir fim-watch --seed 20260818 --rate 10 --count 3000 --mix 20/70/10 \
        --manifest resultados/bateria5_manifiesto.json \
        --log resultados/bateria5_generador.log

Inspeccionar el plan sin tocar el filesystem:

    python3 scripts/generador_carga.py --dir /tmp/x --seed 1 --rate 5 \
        --count 500 --mix 20/70/10 --dry-run

NOTAS
-----
  * No requiere root ni dependencias externas (solo stdlib).
  * `--seed`, `--rate`, `--count`, `--mix` y `--dir` son obligatorios a propósito:
    un default oculto es exactamente lo que hace irreproducible al ítem 54.
  * La cadencia es fija (1/rate), no jitterada: se prioriza reproducibilidad.
  * Cada cambio se escribe con un solo open/write/close para no multiplicar
    eventos fanotify por operación lógica.
  * El manifiesto se va escribiendo también como `.jsonl` incremental al lado
    del JSON final, para no perder una corrida de 30 min ante una interrupción.
  * Si el directorio vigilado tiene archivos previos de otra corrida (p. ej. los
    `c_51..c_100` residuales creados por root desde el contenedor), el generador
    no los toca: usa su propio prefijo `--prefix`. Igual conviene limpiarlo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Léxico ────────────────────────────────────────────────────────────────────

OP_CREATE = "create"
OP_MODIFY = "modify"
OP_DELETE = "delete"

PAT_SIMPLE = "simple"
PAT_REVERT = "revertido"
PAT_BURST = "colapsado"
PAT_EPHEMERAL = "efimero"

DET_VISIBLE = "visible"
DET_INVISIBLE_REVERT = "invisible_revertido"
DET_INVISIBLE_BURST = "invisible_colapsado"
DET_INVISIBLE_EPHEMERAL = "invisible_efimero"


# ── Plan ──────────────────────────────────────────────────────────────────────


@dataclass
class PlannedOp:
    """Una operación planificada. El plan se arma entero antes de tocar disco."""

    op: str
    pattern: str
    group_id: str | None
    expected: str
    restore: bool = False          # el contenido vuelve al estado previo al grupo
    capture: bool = False          # guardar el contenido previo para el revert
    target: str | None = None      # ruta relativa al directorio vigilado


@dataclass
class Unit:
    """Grupo de operaciones que ocupan slots consecutivos del cronograma."""

    kind: str
    ops: list[PlannedOp] = field(default_factory=list)

    @property
    def needs_existing_file(self) -> bool:
        return self.kind in ("modify", "delete", PAT_REVERT, PAT_BURST)

    @property
    def pool_delta(self) -> int:
        if self.kind == "create":
            return 1
        if self.kind == "delete":
            return -1
        return 0  # efimero crea y borra en el mismo grupo; revert/burst no alteran


def parse_mix(raw: str) -> dict[str, float]:
    """Acepta '20/70/10' (porcentajes) o '0.2/0.7/0.1' (fracciones)."""
    parts = [p.strip() for p in raw.replace(",", "/").split("/")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--mix espera 3 valores: creacion/modificacion/borrado")
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--mix inválido: {exc}") from exc
    if any(v < 0 for v in values):
        raise argparse.ArgumentTypeError("--mix no admite valores negativos")
    total = sum(values)
    if abs(total - 100.0) < 1e-6:
        values = [v / 100.0 for v in values]
    elif abs(total - 1.0) < 1e-9:
        pass
    else:
        raise argparse.ArgumentTypeError(
            f"--mix debe sumar 100 (porcentajes) o 1 (fracciones); suma {total}"
        )
    return {OP_CREATE: values[0], OP_MODIFY: values[1], OP_DELETE: values[2]}


def build_units(
    count: int,
    mix: dict[str, float],
    revert_frac: float,
    burst_frac: float,
    burst_size: int,
    ephemeral_frac: float,
) -> tuple[list[Unit], dict[str, Any]]:
    """Arma las unidades del plan respetando la mezcla y las cuotas de patrones."""
    n_create = round(count * mix[OP_CREATE])
    n_delete = round(count * mix[OP_DELETE])
    n_modify = count - n_create - n_delete
    if n_modify < 0:
        raise SystemExit("Mezcla inválida: creación + borrado supera el total de eventos")
    if n_create == 0 and count > 0:
        raise SystemExit("Mezcla inválida: se necesita al menos una creación")

    # Efímeros: consumen una creación y un borrado cada uno.
    n_ephemeral = int(min(n_create, n_delete) * ephemeral_frac)
    # Ráfagas: consumen burst_size modificaciones cada una.
    n_burst_groups = int(n_modify * burst_frac) // burst_size if burst_size > 0 else 0
    # Reversiones: consumen 2 modificaciones cada una (cambio + restauración).
    n_revert_pairs = int(n_modify * revert_frac) // 2

    used_modify = n_burst_groups * burst_size + n_revert_pairs * 2
    if used_modify > n_modify:
        raise SystemExit(
            f"--revert-frac + --burst-frac exceden las modificaciones disponibles "
            f"({used_modify} > {n_modify})"
        )

    units: list[Unit] = []

    for i in range(n_ephemeral):
        gid = f"efi_{i:04d}"
        units.append(
            Unit(
                PAT_EPHEMERAL,
                [
                    PlannedOp(OP_CREATE, PAT_EPHEMERAL, gid, DET_INVISIBLE_EPHEMERAL),
                    PlannedOp(OP_DELETE, PAT_EPHEMERAL, gid, DET_INVISIBLE_EPHEMERAL),
                ],
            )
        )

    for i in range(n_revert_pairs):
        gid = f"rev_{i:04d}"
        units.append(
            Unit(
                PAT_REVERT,
                [
                    PlannedOp(OP_MODIFY, PAT_REVERT, gid, DET_INVISIBLE_REVERT, capture=True),
                    PlannedOp(OP_MODIFY, PAT_REVERT, gid, DET_INVISIBLE_REVERT, restore=True),
                ],
            )
        )

    for i in range(n_burst_groups):
        gid = f"raf_{i:04d}"
        ops = [PlannedOp(OP_MODIFY, PAT_BURST, gid, DET_VISIBLE)]
        ops += [
            PlannedOp(OP_MODIFY, PAT_BURST, gid, DET_INVISIBLE_BURST)
            for _ in range(burst_size - 1)
        ]
        units.append(Unit(PAT_BURST, ops))

    for _ in range(n_create - n_ephemeral):
        units.append(Unit("create", [PlannedOp(OP_CREATE, PAT_SIMPLE, None, DET_VISIBLE)]))
    for _ in range(n_delete - n_ephemeral):
        units.append(Unit("delete", [PlannedOp(OP_DELETE, PAT_SIMPLE, None, DET_VISIBLE)]))
    for _ in range(n_modify - used_modify):
        units.append(Unit("modify", [PlannedOp(OP_MODIFY, PAT_SIMPLE, None, DET_VISIBLE)]))

    resumen = {
        "creaciones": n_create,
        "modificaciones": n_modify,
        "borrados": n_delete,
        "grupos_efimeros": n_ephemeral,
        "pares_revertidos": n_revert_pairs,
        "rafagas": n_burst_groups,
        "tamano_rafaga": burst_size,
        "operaciones_planificadas": sum(len(u.ops) for u in units),
    }
    return units, resumen


def repair_order(units: list[Unit]) -> list[Unit]:
    """
    Reordena para que ninguna unidad que necesita un archivo vivo caiga con el
    pool vacío. Determinístico: siempre intercambia con la creación simple más
    cercana hacia adelante.
    """
    units = list(units)
    pool = 0
    i = 0
    guard = 0
    limit = len(units) * len(units) + 10
    while i < len(units):
        guard += 1
        if guard > limit:
            raise SystemExit("No se pudo ordenar el plan: revisá la mezcla de operaciones")
        unit = units[i]
        if unit.needs_existing_file and pool == 0:
            swap = next((j for j in range(i + 1, len(units)) if units[j].kind == "create"), None)
            if swap is None:
                raise SystemExit(
                    "Mezcla inválida: no quedan creaciones para sostener las modificaciones"
                )
            units[i], units[swap] = units[swap], units[i]
            continue
        pool += unit.pool_delta
        i += 1
    return units


def assign_targets(
    units: list[Unit],
    rng: random.Random,
    prefix: str,
    critical_subdir: str | None,
    critical_frac: float,
) -> list[PlannedOp]:
    """Asigna rutas concretas y aplana el plan en la secuencia de slots."""
    pool: list[str] = []
    counter = 0
    flat: list[PlannedOp] = []

    def new_name() -> str:
        nonlocal counter
        counter += 1
        base = f"{prefix}_{counter:05d}.txt"
        if critical_subdir and rng.random() < critical_frac:
            return f"{critical_subdir}/{base}"
        return base

    for unit in units:
        if unit.kind == PAT_EPHEMERAL:
            name = new_name()
            for op in unit.ops:
                op.target = name
        elif unit.kind in (PAT_REVERT, PAT_BURST, "modify"):
            name = pool[rng.randrange(len(pool))]
            for op in unit.ops:
                op.target = name
        elif unit.kind == "create":
            name = new_name()
            pool.append(name)
            unit.ops[0].target = name
        elif unit.kind == "delete":
            name = pool.pop(rng.randrange(len(pool)))
            unit.ops[0].target = name
        else:  # pragma: no cover - defensivo
            raise SystemExit(f"Unidad desconocida: {unit.kind}")
        flat.extend(unit.ops)

    return flat


# ── Ejecución ─────────────────────────────────────────────────────────────────


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_file(path: Path, data: bytes) -> None:
    """Un solo open/write/close: una operación lógica -> un CLOSE_WRITE."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class Logger:
    """Escribe simultáneamente a stdout y al log archivable del ítem 54."""

    def __init__(self, path: Path | None, quiet: bool) -> None:
        self.quiet = quiet
        self.fh = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = path.open("a", encoding="utf-8")

    def write(self, line: str, always: bool = False) -> None:
        if always or not self.quiet:
            print(line, flush=True)
        if self.fh is not None:
            self.fh.write(line + "\n")
            self.fh.flush()

    def close(self) -> None:
        if self.fh is not None:
            self.fh.close()


def dump_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="generador_carga.py",
        description="Generador de carga reproducible para las baterías del Cap. 5 (P2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dir", required=True, help="Directorio vigilado en el host (ej: fim-watch)")
    ap.add_argument("--seed", required=True, type=int, help="Semilla (ítem 54). Obligatoria.")
    ap.add_argument("--rate", required=True, type=float, help="Eventos por segundo. Obligatoria.")
    ap.add_argument("--count", required=True, type=int, help="Cantidad total de cambios.")
    ap.add_argument(
        "--mix",
        required=True,
        type=parse_mix,
        help="Mezcla creacion/modificacion/borrado, ej: 20/70/10",
    )
    ap.add_argument("--manifest", default="resultados/bateria3_manifiesto.json",
                    help="Manifiesto JSON de salida (ítems 9, 48, 54).")
    ap.add_argument("--log", default="resultados/bateria3_generador.log",
                    help="Log de configuración y progreso (ítem 54).")
    ap.add_argument("--agent-prefix", default="/watch",
                    help="Prefijo con el que el agente ve el directorio (join con events.path).")
    ap.add_argument("--prefix", default="gen", help="Prefijo de los archivos generados.")
    ap.add_argument("--file-size", type=int, default=64, help="Bytes aproximados por archivo.")
    ap.add_argument("--revert-frac", type=float, default=0.20,
                    help="Fracción de modificaciones usadas en pares revertidos (ítem 49).")
    ap.add_argument("--burst-frac", type=float, default=0.20,
                    help="Fracción de modificaciones usadas en ráfagas colapsables (ítem 49).")
    ap.add_argument("--burst-size", type=int, default=5,
                    help="Modificaciones sucesivas por ráfaga.")
    ap.add_argument("--ephemeral-frac", type=float, default=0.20,
                    help="Fracción de creaciones/borrados que forman archivos efímeros.")
    ap.add_argument("--critical-subdir", default="critico",
                    help="Subdirectorio para severidad critical (ver scripts/seed-reglas-lab.sh).")
    ap.add_argument("--critical-frac", type=float, default=0.0,
                    help="Fracción de archivos nuevos ubicados en --critical-subdir.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Planifica e informa sin tocar el filesystem.")
    ap.add_argument("--quiet", action="store_true", help="No imprime una línea por operación.")
    args = ap.parse_args(argv)

    if args.rate <= 0:
        ap.error("--rate debe ser > 0")
    if args.count <= 0:
        ap.error("--count debe ser > 0")
    if args.burst_size < 2:
        ap.error("--burst-size debe ser >= 2 para que exista colapso")
    for name, value in (("--revert-frac", args.revert_frac),
                        ("--burst-frac", args.burst_frac),
                        ("--ephemeral-frac", args.ephemeral_frac),
                        ("--critical-frac", args.critical_frac)):
        if not 0.0 <= value <= 1.0:
            ap.error(f"{name} debe estar entre 0 y 1")

    target_dir = Path(args.dir).resolve()
    manifest_path = Path(args.manifest)
    log = Logger(Path(args.log) if args.log else None, args.quiet)

    rng_plan = random.Random(args.seed)
    rng_data = random.Random(args.seed + 1)

    units, resumen_plan = build_units(
        args.count, args.mix, args.revert_frac, args.burst_frac,
        args.burst_size, args.ephemeral_frac,
    )
    rng_plan.shuffle(units)
    units = repair_order(units)
    plan = assign_targets(
        units, rng_plan, args.prefix,
        args.critical_subdir if args.critical_frac > 0 else None,
        args.critical_frac,
    )
    resumen_plan["archivos_distintos"] = len({op.target for op in plan})

    interval = 1.0 / args.rate
    config = {
        "generador": "scripts/generador_carga.py",
        "seed": args.seed,
        "rate_eventos_por_segundo": args.rate,
        "count": args.count,
        "mix": {"creacion": args.mix[OP_CREATE],
                "modificacion": args.mix[OP_MODIFY],
                "borrado": args.mix[OP_DELETE]},
        "revert_frac": args.revert_frac,
        "burst_frac": args.burst_frac,
        "burst_size": args.burst_size,
        "ephemeral_frac": args.ephemeral_frac,
        "critical_subdir": args.critical_subdir,
        "critical_frac": args.critical_frac,
        "file_size_bytes": args.file_size,
        "prefix": args.prefix,
        "dir_host": str(target_dir),
        "agent_prefix": args.agent_prefix,
        "intervalo_s": interval,
        "duracion_estimada_s": (args.count - 1) * interval,
        "manifiesto": str(manifest_path),
        "log": args.log,
        "dry_run": args.dry_run,
        "python": sys.version.split()[0],
        "host": os.uname().nodename,
    }

    # ── Ítem 54: configuración completa al arrancar ───────────────────────────
    log.write("=" * 72, always=True)
    log.write(f"generador_carga.py — arranque {iso_utc(time.time())}", always=True)
    log.write("=" * 72, always=True)
    for key, value in config.items():
        log.write(f"  {key:28} = {value}", always=True)
    for key, value in resumen_plan.items():
        log.write(f"  plan.{key:23} = {value}", always=True)
    log.write("=" * 72, always=True)

    if args.dry_run:
        log.write("Primeras 25 operaciones del plan:", always=True)
        for idx, op in enumerate(plan[:25]):
            log.write(
                f"  [{idx + 1:05d}] {op.op:6} {op.pattern:10} "
                f"{args.agent_prefix.rstrip('/')}/{op.target}",
                always=True,
            )
        log.write("--dry-run: no se tocó el filesystem.", always=True)
        log.close()
        return 0

    if not target_dir.is_dir():
        log.write(f"ERROR: {target_dir} no existe o no es un directorio", always=True)
        log.close()
        return 2

    # Subdirectorios creados ANTES de arrancar el reloj, para no inyectar
    # eventos de directorio en el medio de la ventana medida.
    subdirs = {Path(op.target).parent for op in plan if "/" in (op.target or "")}
    for sub in sorted(subdirs):
        (target_dir / sub).mkdir(parents=True, exist_ok=True)

    contents: dict[str, bytes] = {}
    restore_source: dict[str, bytes] = {}
    cambios: list[dict[str, Any]] = []
    errores = 0

    jsonl_path = manifest_path.with_suffix(".jsonl")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl = jsonl_path.open("w", encoding="utf-8")

    interrumpido = {"flag": False}

    def _on_signal(signum, _frame):  # noqa: ANN001
        interrumpido["flag"] = True
        log.write(f"señal {signum} recibida: cerrando y volcando el manifiesto", always=True)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    def build_manifest(fin_epoch: float | None) -> dict[str, Any]:
        por_operacion: dict[str, int] = {}
        por_patron: dict[str, int] = {}
        for c in cambios:
            por_operacion[c["operacion"]] = por_operacion.get(c["operacion"], 0) + 1
            por_patron[c["patron"]] = por_patron.get(c["patron"], 0) + 1
        return {
            "version_manifiesto": 1,
            "config": config,
            "plan": resumen_plan,
            "inicio_utc": iso_utc(inicio_epoch),
            "inicio_epoch": inicio_epoch,
            "fin_utc": iso_utc(fin_epoch) if fin_epoch else None,
            "fin_epoch": fin_epoch,
            "interrumpido": interrumpido["flag"],
            "resumen": {
                "cambios_registrados": len(cambios),
                "errores": errores,
                "por_operacion": por_operacion,
                "por_patron": por_patron,
            },
            "cambios": cambios,
        }

    inicio_epoch = time.time()
    inicio_mono = time.monotonic()
    log.write(f"inicio_utc = {iso_utc(inicio_epoch)}", always=True)

    for idx, op in enumerate(plan):
        if interrumpido["flag"]:
            break
        objetivo_mono = inicio_mono + idx * interval
        pendiente = objetivo_mono - time.monotonic()
        if pendiente > 0:
            time.sleep(pendiente)
        if interrumpido["flag"]:
            break

        rel = op.target or ""
        path = target_dir / rel
        previo = contents.get(rel)
        hash_antes = sha256_hex(previo) if previo is not None else None
        error: str | None = None
        data: bytes | None = None

        try:
            if op.op == OP_DELETE:
                os.unlink(path)
                contents.pop(rel, None)
            else:
                if op.restore:
                    data = restore_source.get(op.group_id or "", b"")
                else:
                    if op.capture and previo is not None:
                        restore_source[op.group_id or ""] = previo
                    n = max(1, args.file_size // 2)
                    data = (rng_data.randbytes(n).hex() + "\n").encode("ascii")
                write_file(path, data)
                contents[rel] = data
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
            errores += 1

        ahora = time.time()
        programado = inicio_epoch + idx * interval
        registro = {
            "seq": idx + 1,
            "operacion": op.op,
            "patron": op.pattern,
            "grupo": op.group_id,
            "ruta_host": str(path),
            "ruta_relativa": rel,
            "ruta_agente": f"{args.agent_prefix.rstrip('/')}/{rel}",
            "ts_utc": iso_utc(ahora),
            "ts_epoch": ahora,
            "ts_programado_epoch": programado,
            "desvio_ms": (ahora - programado) * 1000.0,
            "hash_antes": hash_antes,
            "hash_despues": sha256_hex(data) if data is not None else None,
            "bytes": len(data) if data is not None else None,
            "deteccion_control_esperada": op.expected,
            "error": error,
        }
        cambios.append(registro)
        jsonl.write(json.dumps(registro, ensure_ascii=False) + "\n")
        jsonl.flush()

        if not args.quiet:
            marca = "!" if error else " "
            log.write(
                f"{marca}[{idx + 1:05d}/{len(plan)}] {op.op:6} {op.pattern:10} "
                f"{registro['ruta_agente']} ts={registro['ts_utc']}"
            )

    fin_epoch = time.time()
    jsonl.close()
    dump_manifest(manifest_path, build_manifest(fin_epoch))

    log.write("=" * 72, always=True)
    log.write(f"fin_utc = {iso_utc(fin_epoch)}  duracion_s = {fin_epoch - inicio_epoch:.3f}", always=True)
    log.write(f"cambios_registrados = {len(cambios)}  errores = {errores}", always=True)
    log.write(f"manifiesto = {manifest_path}", always=True)
    log.write(f"manifiesto incremental = {jsonl_path}", always=True)
    log.write("=" * 72, always=True)
    log.close()
    return 130 if interrumpido["flag"] else (1 if errores else 0)


if __name__ == "__main__":
    raise SystemExit(main())
