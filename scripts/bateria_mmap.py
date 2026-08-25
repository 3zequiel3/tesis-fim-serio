#!/usr/bin/env python3
"""
bateria_mmap.py — Batería 8: evasión de la detección por escritura mapeada en memoria.

Caracteriza la limitación documentada en fanotify(7): las modificaciones aplicadas a
través de un mapeo compartido (mmap/msync/munmap) no generan eventos del subsistema.

El agente de esta plataforma no se suscribe a FAN_MODIFY: su máscara es
FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE
(agent/detector.py::_mark_paths). La detección de modificación de contenido se
dispara, por lo tanto, al cierre de un descriptor abierto para escritura, y el hash
se computa en ese instante. De ahí que el resultado dependa del ORDEN entre el
cierre del descriptor y las escrituras sobre el mapeo:

  Caso A (evasión)   open → mmap → close(fd) → escribir → msync → munmap
                     El CLOSE_WRITE se emite ANTES de la modificación: el agente SÍ
                     produce un evento, pero hashea contenido todavía íntegro, de modo
                     que hash_detected == hash_antes y no hay violación que reportar.
                     La escritura posterior sobre el mapeo no genera evento adicional.
                     ESPERADO: un evento por operación, ninguno con
                     hash_detected == hash_despues (estado `evento_sin_cambio`).
                     Contar eventos sin mirar el hash da un falso "detectado".

  Caso B (control)   open → mmap → escribir → msync → munmap → close(fd)
                     El CLOSE_WRITE se emite DESPUÉS de la modificación.
                     ESPERADO: evento con el hash modificado.

  Caso C (control)   open/write/close convencional, sin mapeo.
                     ESPERADO: evento con el hash modificado.

La comparación A vs. B es lo que convierte la limitación en un resultado
caracterizado: no es que "mmap no se detecta", sino que la evasión ocurre cuando el
descriptor se cierra antes de escribir sobre el mapeo, condición que un adversario
controla trivialmente.

Alcance de la afirmación: el resultado es empírico, no una prueba de determinismo.
El desenlace del caso A depende de una carrera entre la secuencia in-process
(escritura sobre el mapeo → msync → munmap, sin syscalls de por medio) y el pipeline
cross-thread del agente (hilo lector de fanotify → call_soon_threadsafe → asyncio.Queue
→ hash asincrónico). Esta batería no mide ese margen temporal. Reportar, por lo tanto,
"consistente en las N repeticiones", nunca "determinística".

Uso:
    sudo ./bateria_mmap.py --dir /var/fim-lab --repeticiones 10 \
         --salida ./results/bateria8 --agent-prefix /var/fim-lab

Produce  <salida>/bateria8_cambios.jsonl  y  <salida>/bateria8_manifiesto.json
con el mismo esquema de campos que generador_carga.py, para que el análisis
posterior contra la tabla `events` reutilice el correlacionador existente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTENIDO_BASE = b"integridad-original-" + b"\x00" * 4076  # 4096 B exactos
CONTENIDO_EVIL = b"integridad-alterada-"                    # se escribe en offset 0


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def sha256_file(path: Path) -> str | None:
    # OSError y no FileNotFoundError: un PermissionError o un EIO acá no debe abortar
    # la corrida ni perder el manifiesto — se registra como hash nulo y sigue.
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def crear_archivo(path: Path) -> None:
    """Crea el archivo con un open/write/close convencional (queda en baseline)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, CONTENIDO_BASE)
    finally:
        os.close(fd)


def caso_a_evasion(path: Path) -> None:
    """mmap → close(fd) → escribir. El CLOSE_WRITE precede a la modificación."""
    fd = os.open(path, os.O_RDWR)
    mm = mmap.mmap(fd, 0, flags=mmap.MAP_SHARED, prot=mmap.PROT_WRITE | mmap.PROT_READ)
    os.close(fd)                      # ← CLOSE_WRITE se emite acá, sin modificación
    mm[0:len(CONTENIDO_EVIL)] = CONTENIDO_EVIL
    mm.flush()                        # msync
    mm.close()                        # munmap


def caso_b_mmap_close_posterior(path: Path) -> None:
    """mmap → escribir → close(fd). El CLOSE_WRITE sucede a la modificación."""
    fd = os.open(path, os.O_RDWR)
    mm = mmap.mmap(fd, 0, flags=mmap.MAP_SHARED, prot=mmap.PROT_WRITE | mmap.PROT_READ)
    mm[0:len(CONTENIDO_EVIL)] = CONTENIDO_EVIL
    mm.flush()
    mm.close()
    os.close(fd)


def caso_c_escritura_convencional(path: Path) -> None:
    """open/write/close: la vía que el generador de carga ejercita."""
    datos = bytearray(CONTENIDO_BASE)
    datos[0:len(CONTENIDO_EVIL)] = CONTENIDO_EVIL
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC)
    try:
        os.write(fd, bytes(datos))
    finally:
        os.close(fd)


CASOS = {
    "A_mmap_close_previo": (caso_a_evasion, False),
    "B_mmap_close_posterior": (caso_b_mmap_close_posterior, True),
    "C_escritura_convencional": (caso_c_escritura_convencional, True),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, type=Path, help="Directorio monitoreado por el agente")
    ap.add_argument("--repeticiones", type=int, default=10, help="Repeticiones por caso (default 10)")
    ap.add_argument("--espera-baseline", type=float, default=5.0,
                    help="Segundos de espera tras crear el archivo, para que el agente lo incorpore")
    ap.add_argument("--espera-evento", type=float, default=5.0,
                    help="Segundos de espera tras cada modificación, antes de la siguiente")
    ap.add_argument("--salida", type=Path, default=Path("./results/bateria8"))
    ap.add_argument("--agent-prefix", default=None,
                    help="Prefijo de ruta tal como lo ve el agente (default: --dir)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.dir.is_dir():
        print(f"ERROR: {args.dir} no existe o no es un directorio")
        return 2

    prefijo = (args.agent_prefix or str(args.dir)).rstrip("/")
    args.salida.mkdir(parents=True, exist_ok=True)

    plan = [(nombre, i + 1) for nombre in CASOS for i in range(args.repeticiones)]
    print(f"Plan: {len(plan)} operaciones ({args.repeticiones} por caso, {len(CASOS)} casos)")
    if args.dry_run:
        for nombre, rep in plan[:12]:
            print(f"  {nombre} #{rep}")
        print("--dry-run: no se tocó el filesystem.")
        return 0

    inicio = time.time()
    cambios: list[dict[str, Any]] = []
    jsonl_path = args.salida / "bateria8_cambios.jsonl"

    # `with`: si algo escapa del bucle, el JSONL queda cerrado y el manifiesto
    # agregado se escribe igual con lo que se alcanzó a medir.
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for seq, (nombre_caso, rep) in enumerate(plan, start=1):
            fn, deteccion_esperada = CASOS[nombre_caso]
            rel = f"mmap_{nombre_caso}_{rep:03d}.bin"
            path = args.dir / rel

            crear_archivo(path)
            hash_baseline = sha256_file(path)
            time.sleep(args.espera_baseline)   # el agente incorpora el archivo a la baseline

            ts = time.time()
            error: str | None = None
            try:
                fn(path)
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"

            hash_despues = sha256_file(path)

            registro = {
                "seq": seq,
                "operacion": "modify",
                "patron": nombre_caso,
                "grupo": nombre_caso,
                "ruta_host": str(path),
                "ruta_relativa": rel,
                "ruta_agente": f"{prefijo}/{rel}",
                "ts_utc": iso_utc(ts),
                "ts_epoch": ts,
                "hash_antes": hash_baseline,
                "hash_despues": hash_despues,
                "bytes": len(CONTENIDO_BASE),
                "modificacion_efectiva": hash_baseline != hash_despues,
                "deteccion_agente_esperada": deteccion_esperada,
                "error": error,
            }
            cambios.append(registro)
            jsonl.write(json.dumps(registro, ensure_ascii=False) + "\n")
            jsonl.flush()

            marca = "!" if error else " "
            print(f"{marca}[{seq:04d}/{len(plan)}] {nombre_caso:26} {rel} "
                  f"modificado={registro['modificacion_efectiva']} esperado={deteccion_esperada}")

            time.sleep(args.espera_evento)

    fin = time.time()

    por_caso: dict[str, dict[str, Any]] = {}
    for c in cambios:
        d = por_caso.setdefault(c["patron"], {"n": 0, "modificacion_efectiva": 0, "errores": 0})
        d["n"] += 1
        d["modificacion_efectiva"] += int(bool(c["modificacion_efectiva"]))
        d["errores"] += int(bool(c["error"]))

    manifiesto = {
        "version_manifiesto": 1,
        "bateria": 8,
        "titulo": "Evasion de la deteccion por escritura mapeada en memoria",
        "config": {
            "dir": str(args.dir),
            "agent_prefix": prefijo,
            "repeticiones": args.repeticiones,
            "espera_baseline_s": args.espera_baseline,
            "espera_evento_s": args.espera_evento,
            "kernel": os.uname().release,
        },
        "inicio_utc": iso_utc(inicio),
        "fin_utc": iso_utc(fin),
        "resumen": {"cambios_registrados": len(cambios), "por_caso": por_caso},
        "cambios": cambios,
    }
    manifiesto_path = args.salida / "bateria8_manifiesto.json"
    manifiesto_path.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nJSONL:      {jsonl_path}")
    print(f"Manifiesto: {manifiesto_path}")
    print("\nCorrelacionar contra la tabla `events` filtrando por ruta_agente y ts_utc.")
    print("NO alcanza con contar eventos: hay que comparar hash_detected contra hash_despues.")
    print("  - Caso A: 1 evento por operación, con hash_detected == hash_antes")
    print("            (estado `evento_sin_cambio`) → confirma la evasión")
    print("  - Casos B y C: 1 evento por operación, con hash_detected == hash_despues")
    print("            (estado `detectada`) → confirman que la instrumentación es válida")
    print("\nUsar analisis_mmap.py para el cruce: clasifica cada operación en")
    print("detectada / evento_sin_cambio / sin_evento y aplica el corte de validez.")
    print("\nSi el caso C no produce eventos, la corrida NO es válida: el agente no")
    print("estaba monitoreando el directorio o no estaba corriendo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
