#!/usr/bin/env python3
"""
bateria_reversion.py — Batería 9: qué significa exactamente "no hubo cambio real".

Dirime la indeterminación del ítem 9 (los 7 cambios sin evento de la Batería 3).

EL PROBLEMA QUE RESUELVE
------------------------
La nota del ítem 9 conjetura que "una reversión al contenido vigente no es una
violación de integridad y el agente correctamente no reporta". La Batería 5 la
contradice: 210 cambios repiten un hash previo y sólo 12 quedaron sin evento. Si
repetir cualquier hash anterior bastara para suprimir, esos 210 habrían quedado
todos sin evento.

La distinción real —y la que esta batería mide— es entre:

  (a) "el contenido repite CUALQUIER hash anterior del archivo", y
  (b) "el contenido coincide con el hash que el agente tiene HOY en su baseline".

El código dice (b). `agent/detector.py:460` toma `previous_hash` de la baseline
(`entry.hash`), no de un histórico, y suprime en `:640` sólo si el hash actual
coincide con ése. Y hay un detalle decisivo: tras emitir un evento de modificación
el agente **actualiza la baseline** (`agent/detector.py:611-613`), aunque nadie
haya aprobado nada. La baseline se mueve sola.

Consecuencia, que es lo que esta batería verifica empíricamente: revertir un
archivo a su contenido ORIGINAL **sí se detecta**, porque para cuando se revierte
la baseline ya no es el original — es el contenido intermedio.

LOS CASOS
---------
  Caso A (supresión)   escribir los MISMOS bytes que ya tiene la baseline.
                       El agente hashea y encuentra el hash vigente.
                       ESPERADO: ningún evento. El `CLOSE_WRITE` se emite, pero
                       `_process_event` descarta por `discard_no_real_change`.

  Caso B (reversión)   C0 (baseline) → C1, esperar → volver a C0.
                       Cuando se revierte, la baseline ya es C1, así que C0 es
                       una divergencia.
                       ESPERADO: evento con el hash de C0.
                       Este caso es el que refuta la conjetura del ítem 9.

  Caso C (testigo)     C0 (baseline) → contenido nuevo, nunca visto.
                       ESPERADO: evento. Es el corte de validez de la corrida.

CÓMO SE LEE EL RESULTADO
------------------------
  A sin evento  +  B detectado  → la regla es (b): coincidencia con la baseline
                                  vigente. La conjetura del ítem 9 es FALSA tal
                                  como está redactada, y los 7 sin evento hay que
                                  explicarlos por otra vía (p. ej. dos eventos
                                  para un mismo contenido final).
  A sin evento  +  B sin evento → la regla sería (a). Contradiría al código y a
                                  la Batería 5; habría que revisar las tres cosas
                                  antes de escribir nada en el capítulo.

El caso B es el que carga el resultado. Sin él, un cero en A no distingue entre
las dos hipótesis: las dos predicen que A no genera evento.

TIEMPOS
-------
`--espera-evento` (default 5 s) tiene que ser holgadamente mayor que la latencia
de detección para que la baseline ya se haya actualizado antes de la operación
siguiente. La Batería 8 midió una mediana de 9,5 ms, así que 5 s es de sobra;
bajarlo por debajo de ~1 s vuelve el resultado una carrera y no una medición.

Uso:
    ./bateria_reversion.py --dir fim-watch --agent-prefix /watch \
         --repeticiones 10 --salida ./resultados/bateria9

Produce  <salida>/bateria9_cambios.jsonl  y  <salida>/bateria9_manifiesto.json
con el mismo esquema de campos que generador_carga.py.

El cruce contra la tabla `events` lo hace `analisis_mmap.py` sin modificaciones:
el caso testigo se llama `C_escritura_convencional` a propósito, que es el nombre
que su corte de validez espera.

    # El servicio `db` del compose no publica el 5432 al host: usar la IP del
    # contenedor (docker inspect tesis-fim-serio-db-1), no localhost.
    export DATABASE_URL='postgresql://fim:...@<ip-del-contenedor>:5432/fim'
    python3 scripts/analisis_mmap.py \
        --jsonl  resultados/bateria9/bateria9_cambios.jsonl \
        --salida resultados/bateria9/bateria9_correlacion.csv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RELLENO = b"\x00" * 4076

CONTENIDO_BASE = b"integridad-original-" + RELLENO  # C0 — el que va a baseline
CONTENIDO_INTERMEDIO = b"integridad-intermedia" + RELLENO[:-1]  # C1
CONTENIDO_NUEVO = b"integridad-nueva-xyz" + RELLENO  # C2 — nunca visto


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def sha256_file(path: Path) -> str | None:
    # OSError y no FileNotFoundError: un PermissionError o un EIO acá no debe
    # abortar la corrida ni perder el manifiesto — se registra hash nulo y sigue.
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def escribir(path: Path, datos: bytes) -> None:
    """open/write/close convencional — una sola operación lógica, un CLOSE_WRITE."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, datos)
    finally:
        os.close(fd)


def caso_a_reescritura_identica(path: Path, espera: float) -> None:
    """Reescribe el contenido que la baseline ya tiene. No hay divergencia."""
    escribir(path, CONTENIDO_BASE)


def caso_b_revierte_al_original(path: Path, espera: float) -> None:
    """C0 → C1 (la baseline pasa a C1) → C0. La vuelta es una divergencia."""
    escribir(path, CONTENIDO_INTERMEDIO)
    time.sleep(espera)  # que el agente detecte C1 y mueva la baseline a C1
    escribir(path, CONTENIDO_BASE)


def caso_c_escritura_convencional(path: Path, espera: float) -> None:
    """Contenido nuevo, nunca visto. Testigo de validez."""
    escribir(path, CONTENIDO_NUEVO)


# El valor es (función, detección esperada del ÚLTIMO cambio de la secuencia).
CASOS = {
    "A_reescritura_identica": (caso_a_reescritura_identica, False),
    "B_revierte_al_original": (caso_b_revierte_al_original, True),
    "C_escritura_convencional": (caso_c_escritura_convencional, True),
}

# Contenido final de cada caso — el que el evento debería reportar si detecta.
CONTENIDO_FINAL = {
    "A_reescritura_identica": CONTENIDO_BASE,
    "B_revierte_al_original": CONTENIDO_BASE,
    "C_escritura_convencional": CONTENIDO_NUEVO,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, type=Path, help="Directorio monitoreado por el agente")
    ap.add_argument("--repeticiones", type=int, default=10, help="Repeticiones por caso (default 10)")
    ap.add_argument("--espera-baseline", type=float, default=5.0,
                    help="Segundos tras crear el archivo, para que el agente lo incorpore")
    ap.add_argument("--espera-evento", type=float, default=5.0,
                    help="Segundos entre cambios y tras cada operación. Debe superar holgadamente "
                         "la latencia de detección (Batería 8: mediana 9,5 ms)")
    ap.add_argument("--salida", type=Path, default=Path("./resultados/bateria9"))
    ap.add_argument("--agent-prefix", default=None,
                    help="Prefijo de ruta tal como lo ve el agente (default: --dir)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.dir.is_dir():
        print(f"ERROR: {args.dir} no existe o no es un directorio")
        return 2
    if args.espera_evento < 1.0:
        print(f"ERROR: --espera-evento {args.espera_evento}s es demasiado corto. Por debajo de 1 s "
              "el caso B mide una carrera contra el pipeline del agente, no la regla de supresión.")
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
    jsonl_path = args.salida / "bateria9_cambios.jsonl"

    # `with`: si algo escapa del bucle, el JSONL queda cerrado y el manifiesto
    # agregado se escribe igual con lo que se alcanzó a medir.
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for seq, (nombre_caso, rep) in enumerate(plan, start=1):
            fn, deteccion_esperada = CASOS[nombre_caso]
            rel = f"rev_{nombre_caso}_{rep:03d}.bin"
            path = args.dir / rel

            escribir(path, CONTENIDO_BASE)
            hash_baseline = sha256_file(path)
            time.sleep(args.espera_baseline)  # el agente incorpora el archivo a la baseline

            ts = time.time()
            error: str | None = None
            try:
                fn(path, args.espera_evento)
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"

            hash_despues = sha256_file(path)
            esperado = hashlib.sha256(CONTENIDO_FINAL[nombre_caso]).hexdigest()

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
                "bytes": len(CONTENIDO_FINAL[nombre_caso]),
                # En A y B el contenido final ES el de la baseline inicial, así que
                # `modificacion_efectiva` es False respecto del arranque. Eso es
                # correcto y no invalida nada: lo que se mide es si el agente
                # reporta el ÚLTIMO cambio, no si el archivo terminó distinto.
                "modificacion_efectiva": hash_baseline != hash_despues,
                "contenido_final_esperado": esperado,
                "coincide_contenido_esperado": hash_despues == esperado,
                "deteccion_agente_esperada": deteccion_esperada,
                "error": error,
            }
            cambios.append(registro)
            jsonl.write(json.dumps(registro, ensure_ascii=False) + "\n")
            jsonl.flush()

            marca = "!" if error or not registro["coincide_contenido_esperado"] else " "
            print(f"{marca}[{seq:04d}/{len(plan)}] {nombre_caso:26} {rel} "
                  f"contenido_ok={registro['coincide_contenido_esperado']} "
                  f"esperado={deteccion_esperada}")

            time.sleep(args.espera_evento)

    fin = time.time()

    por_caso: dict[str, dict[str, Any]] = {}
    for c in cambios:
        d = por_caso.setdefault(c["patron"], {"n": 0, "contenido_ok": 0, "errores": 0})
        d["n"] += 1
        d["contenido_ok"] += int(bool(c["coincide_contenido_esperado"]))
        d["errores"] += int(bool(c["error"]))

    manifiesto = {
        "version_manifiesto": 1,
        "bateria": 9,
        "titulo": "Reversion al contenido vigente vs. repeticion de un hash anterior",
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
    manifiesto_path = args.salida / "bateria9_manifiesto.json"
    manifiesto_path.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nJSONL:      {jsonl_path}")
    print(f"Manifiesto: {manifiesto_path}")

    incoherentes = [c for c in cambios if not c["coincide_contenido_esperado"]]
    if incoherentes:
        print(f"\nAVISO: {len(incoherentes)} operaciones no dejaron el contenido esperado. "
              "La instrumentación falló; no correlacionar hasta entender por qué.")

    print("\nCruzar con analisis_mmap.py (el testigo se llama C_escritura_convencional,")
    print("que es el nombre que su corte de validez espera):")
    print("  python3 scripts/analisis_mmap.py \\")
    print(f"      --jsonl  {jsonl_path} \\")
    print(f"      --salida {args.salida / 'bateria9_correlacion.csv'}")
    print("\nLectura del resultado:")
    print("  - Caso A sin evento + caso B detectado → la supresión es por coincidencia")
    print("    con la baseline VIGENTE. La conjetura del ítem 9 queda refutada.")
    print("  - Caso A sin evento + caso B sin evento → la supresión sería por repetir")
    print("    cualquier hash anterior. Contradice al código y a la Batería 5: revisar")
    print("    las tres cosas antes de escribir nada en el capítulo.")
    print("\nSi el caso C no produce eventos, la corrida NO es válida: el agente no")
    print("estaba monitoreando el directorio o no estaba corriendo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
