#!/usr/bin/env python3
"""Recalcula los valores del Capítulo 5 desde la evidencia y los compara con la tesis (P-10).

Toma el paquete sellado de v5.1-tesis y el paquete de análisis, ejecuta los
scripts publicados que produjeron cada tabla y compara cada valor con
tesis/cierre/valores_esperados.json, que transcribe lo que informa la tesis:

    Tabla 17  latencia por repetición, combinada y por tipo   p99_bootstrap.py, latencia_por_tipo.py
    Tabla 18  grupo de control por réplica                    analisis_control.py
    Tabla 19  comparación pareada (con y sin corrección de φ) analisis_mcnemar.py
    Tabla 20  tiempo de notificación por escenario            notificacion/*.csv
    Tabla 21  resiliencia ante el corte de Valkey             recalculo_drenaje.py, fuera_de_orden.py
    Tabla 23  resultados de las suites                        informes JUnit de suites/

Cada valor esperado lleva los decimales con que la tesis lo informa; la
comparación acepta solo la diferencia de redondeo de esos decimales. Sale con
código 1 si algún valor difiere o falta, y con 0 si todos coinciden.

Uso, desde la raíz del clon:
    python scripts/recalcular_cap5.py [--esperados tesis/cierre/valores_esperados.json] [--solo-diferencias]

Sólo biblioteca estándar; los scripts que invoca, también.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RUNS = ("run-01", "run-02", "run-03")
SCRIPTS = Path(__file__).resolve().parent
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def pct(v: list[float], p: float) -> float:
    """Percentil con interpolación lineal entre rangos, la convención de lab/latencia.py."""
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def resumen(v: list[float]) -> dict:
    return {"n": len(v), "media": sum(v) / len(v), "p50": pct(v, 50), "p95": pct(v, 95),
            "p99": pct(v, 99), "min": min(v), "max": max(v)}


def correr(*args: str) -> str:
    r = subprocess.run([sys.executable, *args], capture_output=True, env=ENV)
    # En Windows, Python escribe CRLF cuando su salida va a otro proceso.
    salida = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:1])} terminó con {r.returncode}: {r.stderr.decode('utf-8', 'replace')[-400:]}")
    return salida


def num(patron: str, texto: str, grupo: int = 1) -> float:
    m = re.search(patron, texto, flags=re.M)
    if not m:
        raise ValueError(f"no se encontró {patron!r}")
    return float(m.group(grupo))


# ── Tabla 17 ────────────────────────────────────────────────────────────────
def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("+00", "+00:00")).timestamp()


def por_tipo(run_dir: Path) -> tuple[dict[str, list[float]], int, int]:
    """El emparejamiento de scripts/latencia_por_tipo.py: cada evento con la operación
    anterior más cercana sobre la misma ruta, usando cada operación una sola vez."""
    with open(run_dir / "bateria3_manifiesto.jsonl", encoding="utf-8") as fh:
        ops = [json.loads(l) for l in fh]
    with open(run_dir / "eventos.csv", encoding="utf-8", newline="") as fh:
        evs = list(csv.DictReader(fh))
    por_ruta = defaultdict(list)
    for o in ops:
        por_ruta[o["ruta_agente"]].append(o)
    usadas, lat = set(), defaultdict(list)
    for e in sorted(evs, key=lambda e: ts(e["detected_at"])):
        d = ts(e["detected_at"])
        cand = [o for o in por_ruta.get(e["path"], []) if o["ts_epoch"] <= d + 0.005 and o["seq"] not in usadas]
        if cand:
            o = max(cand, key=lambda o: o["ts_epoch"])
            usadas.add(o["seq"])
            lat[o["operacion"]].append(float(e["latencia_ms"]))
    return lat, len(ops), len(ops) - len(usadas)


def tabla17(E: Path) -> dict:
    out, todas, tipos, ops, sin_evento = {}, [], defaultdict(list), 0, 0
    boot = json.loads(correr(str(SCRIPTS / "p99_bootstrap.py"), str(E / "latencia"), "--json"))
    ic = {("combinado" if s["serie"] == "combinado" else Path(s["serie"]).parent.name): s for s in boot["series"]}
    for run in RUNS:
        d = E / "latencia" / run
        with open(d / "eventos.csv", encoding="utf-8", newline="") as fh:
            v = [float(r["latencia_ms"]) for r in csv.DictReader(fh)]
        todas += v
        out[run] = {**resumen(v), "ic_bajo": ic[run]["ic95_bajo_ms"], "ic_alto": ic[run]["ic95_alto_ms"]}
        lat, n_ops, n_sin = por_tipo(d)
        ops += n_ops
        sin_evento += n_sin
        # Coherencia con el script publicado, repetición por repetición.
        publicado = correr(str(SCRIPTS / "latencia_por_tipo.py"), str(d))
        for t, valores in lat.items():
            fila = re.search(rf"^{t}\t(\d+)\t[\d.]+\t([\d.]+)\t([\d.]+)\t([\d.]+)\t([\d.]+)$", publicado, flags=re.M)
            propio = (len(valores), pct(valores, 50), pct(valores, 95), pct(valores, 99), max(valores))
            if not fila or int(fila.group(1)) != propio[0] or any(
                    abs(float(fila.group(i + 2)) - propio[i + 1]) > 0.0015 for i in range(4)):
                raise RuntimeError(f"el emparejamiento por tipo no coincide con latencia_por_tipo.py en {run}/{t}")
            tipos[t] += valores
    out["combinado"] = {**resumen(todas), "ic_bajo": ic["combinado"]["ic95_bajo_ms"],
                        "ic_alto": ic["combinado"]["ic95_alto_ms"]}
    for t, v in tipos.items():
        out[t] = resumen(v)
    out["operaciones"] = ops
    out["operaciones_sin_evento"] = sin_evento
    return out


# ── Tabla 18 ────────────────────────────────────────────────────────────────
def tabla18(E: Path) -> dict:
    out = {}
    for run in RUNS:
        with tempfile.TemporaryDirectory() as tmp:
            t = correr(str(SCRIPTS / "analisis_control.py"),
                       "--manifiesto", str(E / "latencia" / run / "bateria3_manifiesto.json"),
                       "--control", str(E / "control" / run / "bateria7_control.csv"),
                       "--salida", str(Path(tmp) / "atribucion.csv"))
        total = num(r"cambios reales \(manifiesto\)\s*=\s*(\d+)", t)
        perdidos = num(r"eventos perdidos por el cron\s*=\s*(\d+)", t)
        nunca = num(r"causa no_detectado\s*=\s*(\d+)", t)
        out[run] = {
            "detectadas": num(r"detecciones atribuidas\s*=\s*(\d+)", t),
            "no_detectadas": perdidos,
            "no_detectadas_pct": 100 * perdidos / total,
            "colapso": num(r"causa colapsado\s*=\s*(\d+)", t),
            "nunca_observadas": nunca,
            "archivo_marcado": total - nunca,
            "archivo_marcado_pct": 100 * (total - nunca) / total,
            "invisibles_pct": 100 * nunca / total,
            "patron_simple": num(r"patrón simple\s*=\s*(\d+)", t),
            "patron_colapsado": num(r"patrón colapsado\s*=\s*(\d+)", t),
            "patron_revertido": num(r"patrón revertido\s*=\s*(\d+)", t),
            "patron_efimero": num(r"patrón efimero\s*=\s*(\d+)", t),
            "mediana_ms": num(r"mediana latencia control \(ms\)\s*=\s*([\d.]+)", t),
            "p99_ms": num(r"P99 latencia control \(ms\)\s*=\s*([\d.]+)", t),
            "media_ms": num(r"media \(ms\)\s*=\s*([\d.]+)", t),
            "desvio_ms": num(r"desvío muestral ddof=1 \(ms\)\s*=\s*([\d.]+)", t),
            "min_ms": num(r"mínimo / máximo \(ms\)\s*=\s*([\d.]+)", t),
            "max_ms": num(r"mínimo / máximo \(ms\)\s*=\s*[\d.]+ / ([\d.]+)", t),
        }
    return out


# ── Tabla 19 ────────────────────────────────────────────────────────────────
def tabla19(E: Path, A: Path) -> dict:
    out = {}
    for i, run in enumerate(RUNS, start=1):
        base = [str(SCRIPTS / "analisis_mcnemar.py"),
                "--manifiesto", str(E / "latencia" / run / "bateria3_manifiesto.json"),
                "--eventos", str(E / "latencia" / run / "eventos.csv"),
                "--control", str(A / f"control_run-0{i}.csv")]
        con, sin = correr(*base), correr(*base, "--sin-correccion-phi")
        ic = r"IC 95 % de Newcombe \(pareado\)\s*=\s*\[([\d.]+), ([\d.]+)\]"
        out[run] = {
            "a": num(r"FIM sí\s+(\d+)\s+(\d+)", con), "b": num(r"FIM sí\s+(\d+)\s+(\d+)", con, 2),
            "c": num(r"FIM no\s+(\d+)\s+(\d+)", con), "d": num(r"FIM no\s+(\d+)\s+(\d+)", con, 2),
            "prop_artefacto": num(r"proporción detectada, FIM\s*=\s*([\d.]+)", con),
            "prop_control": num(r"proporción detectada, control\s*=\s*([\d.]+)", con),
            "diferencia": num(r"diferencia pareada\s*=\s*([-\d.]+)", con),
            "ic_con_phi": [num(ic, con), num(ic, con, 2)],
            "ic_sin_phi": [num(ic, sin), num(ic, sin, 2)],
            "mcnemar": num(r"McNemar con corrección chi2\(1\)\s*=\s*([\d.]+)", con),
            "p": num(r"valor p\s*=\s*([\d.eE+-]+)", con),
        }
    return out


# ── Tabla 20 ────────────────────────────────────────────────────────────────
def tabla20(E: Path) -> dict:
    out = {}
    for esc in ("secuencial", "conc50", "conc100"):
        with open(E / "notificacion" / f"{esc}.csv", encoding="utf-8", newline="") as fh:
            filas = list(csv.DictReader(fh))
        out[esc] = {"aceptacion": resumen([float(r["ms_aceptacion"]) for r in filas]),
                    "entrega": resumen([float(r["ms_entrega"]) for r in filas])}
    return out


# ── Tabla 21 ────────────────────────────────────────────────────────────────
def tabla21(E: Path) -> dict:
    sys.path.insert(0, str(SCRIPTS))
    import recalculo_drenaje  # noqa: E402  (mismo directorio)
    out = {}
    for i, run in enumerate(RUNS, start=1):
        d = E / "resiliencia" / run
        orden = json.loads(correr(str(SCRIPTS / "fuera_de_orden.py"), str(d / "eventos.csv"), "--json"))
        with open(d / f"traza_{run}.jsonl", encoding="utf-8") as fh:
            etapas = Counter(json.loads(l)["stage"] for l in fh)
        metricas = json.loads((d / "metricas.json").read_text(encoding="utf-8"))
        r = recalculo_drenaje.recalcular(i)
        out[run] = {
            "encolados": etapas["queue_enqueue_persisted"],
            "persistidos": orden["filas"], "unicos": orden["unicos"], "duplicados": orden["duplicados"],
            "descartados": sum(n for s, n in etapas.items() if "drop" in s or "discard" in s),
            "fuera_de_orden": orden["fuera_de_orden"],
            "reconexion_s": r["reconexion"], "sin_consumo_s": r["sin_consumo"], "consumo_s": r["consumo"],
            "drenaje_s": r["drenaje"], "caudal": r["caudal"],
            "backend_reiniciado": int(bool(metricas["drenaje"]["backend_reiniciado"])),
        }
    r = recalculo_drenaje.recalcular(1, "campo-t")
    out["run-01_t0_campo_t"] = {"drenaje_s": r["drenaje"], "reconexion_s": r["reconexion"]}
    return out


# ── Tabla 23 ────────────────────────────────────────────────────────────────
def tabla23(E: Path) -> dict:
    out = {}
    for comp, archivo in (("agente", "agente.xml"), ("backend", "backend.xml"), ("frontend", "frontend.xml")):
        raiz = ET.parse(E / "suites" / archivo).getroot()
        suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
        suma = lambda k: sum(int(s.get(k, 0)) for s in suites)  # noqa: E731
        out[comp] = {"pruebas": suma("tests"), "fallidas": suma("failures"),
                     "con_error": suma("errors"), "omitidas": suma("skipped")}
    return out


# ── comparación ─────────────────────────────────────────────────────────────
def comparar(esperado, obtenido, ruta: str, filas: list) -> None:
    if isinstance(esperado, dict):
        for k, v in esperado.items():
            if k.startswith("_"):
                continue
            sub = obtenido.get(k) if isinstance(obtenido, dict) else None
            comparar(v, sub, f"{ruta}.{k}" if ruta else k, filas)
        return
    if isinstance(esperado, list) and esperado and isinstance(esperado[0], list):
        for j, par in enumerate(esperado):
            comparar(par, obtenido[j] if isinstance(obtenido, list) and j < len(obtenido) else None,
                     f"{ruta}[{j}]", filas)
        return
    valor, dec = esperado
    if obtenido is None:
        filas.append((False, ruta, None, valor, dec))
        return
    if dec == "rel":
        ok = abs(obtenido / valor - 1) <= 0.01
    else:
        ok = abs(obtenido - valor) <= 0.5 * 10 ** -dec + 1e-9
    filas.append((ok, ruta, obtenido, valor, dec))


def formato(x, dec, extra: int = 0) -> str:
    """Con los decimales de la tesis; extra agrega dígitos para ver el redondeo."""
    if x is None:
        return "(falta)"
    if dec == "rel":
        return f"{x:.{3 + extra}g}"
    return f"{x:.{dec + extra}f}" if dec or extra else f"{x:.0f}"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esperados", type=Path, default=Path("tesis/cierre/valores_esperados.json"))
    ap.add_argument("--solo-diferencias", action="store_true", help="no lista los valores que coinciden")
    args = ap.parse_args()
    esperados = json.loads(args.esperados.read_text(encoding="utf-8"))
    E, A = Path(esperados["paquete"]), Path(esperados["analisis"])
    obtenido = {"tabla17": tabla17(E), "tabla18": tabla18(E), "tabla19": tabla19(E, A),
                "tabla20": tabla20(E), "tabla21": tabla21(E), "tabla23": tabla23(E)}
    filas: list = []
    comparar({k: v for k, v in esperados.items() if k.startswith("tabla")}, obtenido, "", filas)
    malos = [f for f in filas if not f[0]]
    print(f"paquete: {E}\nanálisis: {A}\nesperados: {args.esperados}")
    for ok, ruta, obt, esp, dec in filas:
        if ok and args.solo_diferencias:
            continue
        print(f"{'OK     ' if ok else 'DIFIERE'} {ruta}: obtenido {formato(obt, dec, 2 if dec else 0)}, tesis {formato(esp, dec)}")
    print(f"valores comparados: {len(filas)}; coinciden: {len(filas) - len(malos)}; difieren o faltan: {len(malos)}")
    sys.exit(1 if malos else 0)


if __name__ == "__main__":
    main()
