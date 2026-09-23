#!/usr/bin/env python3
"""Atribuye una causa a cada operación del generador que no produjo un evento persistido.

Sin este cruce, el criterio de cero falsos negativos queda indeterminado: la
Batería 3 ejecuta 500 operaciones y la plataforma persiste 484 eventos, y las 16
restantes son indistinguibles entre «el sistema no las vio» y «el sistema las vio
y decidió, correctamente, no reportarlas». Lo primero sería un falso negativo; lo
segundo es la política documentada, que reporta desviaciones respecto de la línea
base y no operaciones de entrada/salida en bruto.

La diferencia no se puede establecer restando. Se establece con la traza causal
del agente, que registra una entrada por etapa: `kernel_received`, `baseline_read`,
`change_classified` para lo que se convierte en evento, y `decision_suppressed`
con su motivo para lo que se descarta deliberadamente.

El cruce es por ruta, por hash resultante y por cercanía temporal, en ese orden de
prioridad. Una operación se atribuye a lo sumo una vez: cada registro de la traza
se consume al emparejarse, de modo que una ráfaga de escrituras sucesivas sobre el
mismo archivo no puede atribuirse toda al mismo registro.

Salida: una fila por operación no persistida, con su causa, y un veredicto. El
programa termina con código 1 si alguna operación queda sin atribuir, porque una
atribución parcial no cierra el criterio y no debe informarse como si lo hiciera.

Uso:
    python3 scripts/atribuir_operaciones_sin_evento.py \\
        --manifiesto <paquete>/latencia/bateria3_manifiesto.jsonl \\
        --eventos    <paquete>/latencia/eventos.csv \\
        --traza      <paquete>/diagnostico/traza_lat.jsonl \\
        [--salida    <paquete>/latencia/atribucion_sin_evento.csv] \\
        [--tolerancia-s 5.0]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# Etapas de la traza que importan para este cruce.
ETAPA_CLASIFICADO = "change_classified"
ETAPA_SUPRIMIDO = "decision_suppressed"
ETAPA_NUCLEO = "kernel_received"


def _epoch(valor: str) -> float:
    return datetime.fromisoformat(valor).timestamp()


def _leer_jsonl(ruta: Path) -> list[dict[str, Any]]:
    filas: list[dict[str, Any]] = []
    with ruta.open(encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if linea:
                filas.append(json.loads(linea))
    return filas


def _emparejar(
    ops: list[dict[str, Any]],
    registros: list[dict[str, Any]],
    tolerancia_s: float,
) -> dict[int, dict[str, Any]]:
    """Empareja operaciones con registros de la traza, consumiendo cada registro.

    Cada registro se usa una sola vez. Para cada operación se elige, entre los
    registros de la misma ruta cuyo hash resultante coincide y que ocurrieron
    dentro de la tolerancia, el más cercano en el tiempo. Consumir el registro es
    lo que impide que cinco escrituras sucesivas sobre el mismo archivo se
    atribuyan todas al mismo registro y produzcan una atribución inflada.
    """
    disponibles: dict[str, list[dict[str, Any]]] = {}
    for reg in registros:
        disponibles.setdefault(reg.get("path") or "", []).append(reg)
    for lista in disponibles.values():
        lista.sort(key=lambda r: _epoch(r["timestamp"]))

    emparejado: dict[int, dict[str, Any]] = {}
    for op in sorted(ops, key=lambda o: o["ts_epoch"]):
        candidatos = disponibles.get(op["ruta_agente"], [])
        mejor_idx, mejor_delta = None, None
        for idx, reg in enumerate(candidatos):
            if reg.get("_usado"):
                continue
            # El hash resultante tiene que coincidir. Para un borrado ambos son
            # nulos, y esa coincidencia también cuenta.
            if reg.get("hash_after") != op["hash_despues"]:
                continue
            delta = _epoch(reg["timestamp"]) - op["ts_epoch"]
            # La detección nunca precede a la operación salvo por desfase de
            # reloj; se admite un margen pequeño hacia atrás y la tolerancia
            # completa hacia adelante.
            if delta < -1.0 or delta > tolerancia_s:
                continue
            if mejor_delta is None or abs(delta) < abs(mejor_delta):
                mejor_idx, mejor_delta = idx, delta
        if mejor_idx is not None:
            candidatos[mejor_idx]["_usado"] = True
            emparejado[op["seq"]] = candidatos[mejor_idx]
    return emparejado


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifiesto", required=True, help="bateria3_manifiesto.jsonl — las operaciones ejecutadas")
    ap.add_argument("--eventos", required=True, help="eventos.csv — lo que la plataforma persistió")
    ap.add_argument("--traza", required=True, help="traza_lat.jsonl — la traza causal del agente")
    ap.add_argument("--salida", help="CSV con una fila por operación no persistida")
    ap.add_argument("--tolerancia-s", type=float, default=5.0,
                    help="ventana máxima entre la operación y su registro en la traza (por defecto 5 s)")
    args = ap.parse_args()

    ops = _leer_jsonl(Path(args.manifiesto))
    traza = _leer_jsonl(Path(args.traza))
    with Path(args.eventos).open(encoding="utf-8") as fh:
        eventos = list(csv.DictReader(fh))

    clasificados = [r for r in traza if r.get("stage") == ETAPA_CLASIFICADO]
    suprimidos = [r for r in traza if r.get("stage") == ETAPA_SUPRIMIDO]
    nucleo = [r for r in traza if r.get("stage") == ETAPA_NUCLEO]

    print("=" * 72)
    print("  Atribución de las operaciones sin evento persistido")
    print("=" * 72)
    print(f"  operaciones del manifiesto        = {len(ops)}")
    print(f"  eventos persistidos               = {len(eventos)}")
    print(f"  registros de la traza causal      = {len(traza)}")
    print(f"    {ETAPA_NUCLEO:<28s} = {len(nucleo)}")
    print(f"    {ETAPA_CLASIFICADO:<28s} = {len(clasificados)}")
    print(f"    {ETAPA_SUPRIMIDO:<28s} = {len(suprimidos)}")

    # Primera comprobación, independiente del cruce: todo lo que el agente
    # clasificó tiene que haberse persistido. Si no coinciden, la pérdida está
    # entre la clasificación y la base de datos y ninguna atribución la explica.
    ids_clasificados = {r["event_id"] for r in clasificados if r.get("event_id")}
    ids_persistidos = {e["event_id"] for e in eventos}
    solo_clasificados = ids_clasificados - ids_persistidos
    solo_persistidos = ids_persistidos - ids_clasificados
    print("-" * 72)
    print(f"  clasificados que no se persistieron = {len(solo_clasificados)}")
    print(f"  persistidos que no se clasificaron  = {len(solo_persistidos)}")
    if solo_clasificados or solo_persistidos:
        print("  ATENCIÓN: hay pérdida entre la clasificación y la persistencia.")

    emp_clasificado = _emparejar(ops, clasificados, args.tolerancia_s)
    sin_evento = [op for op in ops if op["seq"] not in emp_clasificado]
    emp_suprimido = _emparejar(sin_evento, suprimidos, args.tolerancia_s)

    print("-" * 72)
    print(f"  operaciones con evento persistido = {len(emp_clasificado)}")
    print(f"  operaciones SIN evento            = {len(sin_evento)}")

    filas: list[dict[str, Any]] = []
    causas: Counter[str] = Counter()
    for op in sorted(sin_evento, key=lambda o: o["seq"]):
        reg = emp_suprimido.get(op["seq"])
        if reg is not None:
            causa = reg.get("reason") or "suprimido_sin_motivo_declarado"
            decision = reg.get("decision") or ""
        else:
            causa = "SIN_ATRIBUIR"
            decision = ""
        causas[causa] += 1
        filas.append({
            "seq": op["seq"],
            "operacion": op["operacion"],
            "patron": op["patron"],
            "ruta_agente": op["ruta_agente"],
            "deteccion_control_esperada": op.get("deteccion_control_esperada") or "",
            "hash_despues": op["hash_despues"] or "",
            "causa": causa,
            "decision": decision,
            "baseline_status": (reg or {}).get("baseline_status") or "",
            "ts_operacion": op["ts_utc"],
            "ts_traza": (reg or {}).get("timestamp") or "",
        })

    print("-" * 72)
    print("  Causa de cada operación sin evento")
    for causa, n in causas.most_common():
        print(f"    {causa:<34s} = {n}")

    sin_atribuir = causas.get("SIN_ATRIBUIR", 0)
    atribuidas = len(sin_evento) - sin_atribuir
    print("-" * 72)
    print(f"  ATRIBUIDAS = {atribuidas} de {len(sin_evento)}")

    if args.salida:
        destino = Path(args.salida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()) if filas else ["seq"])
            w.writeheader()
            w.writerows(filas)
        print(f"  detalle escrito en {destino}")

    print("=" * 72)
    if sin_atribuir:
        print(f"  VEREDICTO: {sin_atribuir} operación(es) sin atribuir.")
        print("  El criterio de cero falsos negativos NO queda cerrado.")
        print("=" * 72)
        return 1
    print("  VEREDICTO: toda operación sin evento tiene causa registrada.")
    print("  Ninguna es un falso negativo: el sistema las vio y decidió no reportarlas.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
