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

Con --docx, comprueba además que cada valor esperado figure, con el formato de
la tesis (41,73; 16.193,6; 1,21 × 10⁻⁹⁴), en la celda que le corresponde de la
tabla del documento: así la cadena queda cerrada de punta a punta, evidencia →
scripts → valores_esperados.json → documento. Los valores que el documento no
informa en una tabla se buscan en la nota de la tabla o en el Anexo L.3.

Uso, desde la raíz del clon:
    python scripts/recalcular_cap5.py [--esperados tesis/cierre/valores_esperados.json]
                                      [--docx tesis/entrega/<documento>.docx] [--solo-diferencias]

Sólo biblioteca estándar; los scripts que invoca, también.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
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


# ── comparación con el documento (.docx) ──────────────────────────────────────
SUPER = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def formato_tesis(valor, dec) -> str:
    """El número como lo escribe la tesis: coma decimal, punto de miles, potencias de 10."""
    if dec == "rel":
        exp = math.floor(math.log10(abs(valor)))
        mant = valor / 10 ** exp
        return f"{mant:.2f}".replace(".", ",") + " × 10" + str(exp).translate(SUPER)
    texto = f"{valor:,.{dec}f}" if dec else f"{round(valor):,}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def leer_docx(docx: Path) -> tuple[dict, list[str]]:
    """Tablas numeradas (filas de celdas y nota) y párrafos del documento."""
    x = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    body = x[x.find("<w:body>"):]
    texto = lambda s: html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", s)))  # noqa: E731
    items = re.findall(r"<w:p[ >].*?</w:p>|<w:tbl>.*?</w:tbl>", body, flags=re.S)
    tablas, parrafos = {}, []
    for i, g in enumerate(items):
        if not g.startswith("<w:p"):
            continue
        t = texto(g)
        parrafos.append(t)
        m = re.match(r"Tabla (\d+)\.", t)
        if m and i + 1 < len(items) and items[i + 1].startswith("<w:tbl>"):
            filas = [[texto(c) for c in re.findall(r"<w:tc>.*?</w:tc>", r, flags=re.S)]
                     for r in re.findall(r"<w:tr[ >].*?</w:tr>", items[i + 1], flags=re.S)]
            nota = texto(items[i + 2]) if i + 2 < len(items) and texto(items[i + 2]).startswith("Nota.") else ""
            tablas[int(m.group(1))] = {"filas": filas, "nota": nota}
    return tablas, parrafos


# Para cada valor: tabla, fila (comienzo del rótulo) y columna (rótulo o réplica).
FILAS = {
    "tabla17": {"n": "Eventos", "media": "Media", "p50": "P50", "p95": "P95", "p99": "P99",
                "ic_bajo": "IC 95 % del P99", "ic_alto": "IC 95 % del P99", "min": "Mín.", "max": "Máx."},
    "tabla18": {"detectadas": "Detectadas por el control", "no_detectadas": "No detectadas",
                "no_detectadas_pct": "No detectadas", "colapso": "No detectadas por colapso",
                "nunca_observadas": "No detectadas por colapso", "archivo_marcado": "Archivo marcado",
                "archivo_marcado_pct": "Archivo marcado", "invisibles_pct": "Invisibles",
                "patron_simple": "No detectadas por patrón", "patron_colapsado": "No detectadas por patrón",
                "patron_revertido": "No detectadas por patrón", "patron_efimero": "No detectadas por patrón",
                "mediana_ms": "Mediana", "p99_ms": "Percentil 99", "media_ms": "Media / desvío",
                "desvio_ms": "Media / desvío", "min_ms": "Mínimo / máximo", "max_ms": "Mínimo / máximo"},
    "tabla19": {"prop_artefacto": "Proporción detectada, artefacto", "prop_control": "Proporción detectada, control",
                "diferencia": "Diferencia de proporciones", "b": "Pares discordantes", "c": "Pares discordantes",
                "ic_con_phi": "IC 95 % de Newcombe", "mcnemar": "McNemar", "p": "McNemar"},
    "tabla21": {"encolados": "Eventos encolados", "persistidos": "Persistidos", "unicos": "Persistidos",
                "duplicados": "Persistidos", "descartados": "Descartados", "fuera_de_orden": "Entregas fuera de orden",
                "reconexion_s": "Reconexión", "sin_consumo_s": "Tramo sin consumo", "consumo_s": "Consumo",
                "drenaje_s": "Drenaje total", "caudal": "Caudal", "backend_reiniciado": "Backend reiniciado"},
}
RUN_COL = {"run-01": "Réplica 1", "run-02": "Réplica 2", "run-03": "Réplica 3"}
FILA17 = {"run-01": "run-01", "run-02": "run-02", "run-03": "run-03", "combinado": "Combinado",
          "create": "Creación", "modify": "Modificación", "delete": "Eliminación"}
ESC20 = {"secuencial": "Secuencial", "conc50": "Concurrencia 50", "conc100": "Concurrencia 100"}
INT20 = {"aceptacion": "Aceptación", "entrega": "Entrega"}
COL20 = {"n": "n", "media": "Media", "p50": "P50", "p95": "P95", "p99": "P99", "max": "Máx."}
COMP23 = {"agente": "Agente", "backend": "Backend", "frontend": "Frontend"}
COL23 = {"pruebas": "Pruebas", "fallidas": "Fallidas", "con_error": "Con error", "omitidas": "Omitidas"}
NUMERO = re.compile(r"\d+(?:\.\d{3})*(?:,\d+)?(?: × 10[⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)?")


def celda(tabla: dict, fila: str, col: str, fila2: str | None = None) -> str | None:
    cab = tabla["filas"][0]
    if col not in cab:
        return None
    j = cab.index(col)
    for f in tabla["filas"][1:]:
        if f[0].startswith(fila) and (fila2 is None or (len(f) > 1 and f[1].startswith(fila2))):
            return f[j]
    return None


def ubicar(ruta: list[str], tablas: dict, parrafos: list[str]) -> tuple[str, str | None]:
    """Dónde debería figurar el valor: (descripción, texto en el que buscarlo)."""
    tab, *resto = ruta
    T = tablas.get(int(tab[5:]))
    if T is None:
        return f"Tabla {tab[5:]}", None
    if ruta == ["tabla17", "operaciones"]:
        p = next((p for p in parrafos if "1.494 produjeron evento" in p), None)
        return "apartado 5.2 (De las 1.500 operaciones…)", p
    if ruta == ["tabla17", "operaciones_sin_evento"]:
        fila = next((f for f in tablas.get(26, {"filas": []})["filas"] if f and f[0].startswith("Falsos negativos")), None)
        return "Tabla 26, Falsos negativos", " ".join(fila) if fila else None
    if tab == "tabla17" and resto[0] in FILA17:
        col = FILAS[tab][resto[1]]
        return f"Tabla 17, {FILA17[resto[0]]} / {col}", celda(T, FILA17[resto[0]], col)
    if tab in ("tabla18", "tabla19") and resto[0] in RUN_COL and resto[1] in FILAS[tab]:
        fila = FILAS[tab][resto[1]]
        return f"Tabla {tab[5:]}, {fila} / {RUN_COL[resto[0]]}", celda(T, fila, RUN_COL[resto[0]])
    if tab == "tabla19" and resto[1] in ("a", "b", "c", "d", "ic_sin_phi"):
        l3 = " ".join(p for p in parrafos if "REPLICAS = {" in p or p.startswith("La salida reproduce la Tabla 19"))
        return "Tabla 19, nota, y Anexo L.3", T["nota"] + " " + l3
    if tab == "tabla20":
        col = COL20[resto[2]]
        return f"Tabla 20, {ESC20[resto[0]]} / {INT20[resto[1]]} / {col}", celda(T, ESC20[resto[0]], col, INT20[resto[1]])
    if tab == "tabla21" and resto[0] in RUN_COL:
        fila = FILAS[tab][resto[1]]
        return f"Tabla 21, {fila} / {resto[0]}", celda(T, fila, resto[0])
    if tab == "tabla21":
        return "Tabla 21, nota", T["nota"]
    if tab == "tabla23":
        col = COL23[resto[1]]
        return f"Tabla 23, {COMP23[resto[0]]} / {col}", celda(T, COMP23[resto[0]], col)
    return f"Tabla {tab[5:]} (sin celda propia)", None


def comparar_docx(esperados: dict, docx: Path) -> list:
    tablas, parrafos = leer_docx(docx)
    filas = []

    def recorrer(nodo, ruta):
        if isinstance(nodo, dict):
            for k, v in nodo.items():
                if not k.startswith("_"):
                    recorrer(v, ruta + [k])
        elif isinstance(nodo, list) and nodo and isinstance(nodo[0], list):
            texto = "[" + "; ".join(formato_tesis(v, d) for v, d in nodo) + "]"
            donde, ambito = ubicar(ruta, tablas, parrafos)
            filas.append((ambito is not None and texto in ambito, ".".join(ruta), texto, donde, ambito))
        else:
            valor, dec = nodo
            donde, ambito = ubicar(ruta, tablas, parrafos)
            if ruta[-1] in ("a", "b", "c", "d") and ruta[0] == "tabla19":
                r = esperados["tabla19"][ruta[1]]
                texto = "(" + ", ".join(str(r[k][0]) for k in "abcd") + ")"
                ok = ambito is not None and texto in ambito
                if ruta[-1] in ("b", "c"):
                    cel = celda(tablas[19], "Pares discordantes", RUN_COL[ruta[1]])
                    texto, ok = f"{r['b'][0]} / {r['c'][0]}", cel is not None and f"{r['b'][0]} / {r['c'][0]}" in cel
                    donde, ambito = f"Tabla 19, Pares discordantes / {RUN_COL[ruta[1]]}", cel
            elif ruta[-1] == "backend_reiniciado":
                texto = "Sí" if valor else "No"
                ok = ambito is not None and ambito.strip() == texto
            else:
                texto = formato_tesis(valor, dec)
                ok = ambito is not None and texto in NUMERO.findall(ambito)
            filas.append((ok, ".".join(ruta), texto, donde, ambito))

    recorrer({k: v for k, v in esperados.items() if k.startswith("tabla")}, [])
    return filas


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
    ap.add_argument("--docx", type=Path, help="además, comprueba que los valores figuren en este documento")
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
    malos_doc = []
    if args.docx:
        doc = comparar_docx(esperados, args.docx)
        malos_doc = [f for f in doc if not f[0]]
        print(f"documento: {args.docx}")
        for ok, ruta, texto, donde, ambito in doc:
            if ok and args.solo_diferencias:
                continue
            print(f"{'OK     ' if ok else 'NO ESTÁ'} {ruta}: {texto!r} en {donde}"
                  + ("" if ok else f" (el documento dice: {ambito!r})"))
        print(f"valores buscados en el documento: {len(doc)}; figuran: {len(doc) - len(malos_doc)}; "
              f"no figuran: {len(malos_doc)}")
    sys.exit(1 if malos or malos_doc else 0)


if __name__ == "__main__":
    main()
