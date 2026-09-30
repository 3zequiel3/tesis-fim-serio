#!/usr/bin/env python3
"""Desglosa la latencia de la Batería 3 por tipo de operación (hallazgo M-24).

Cada evento persistido (latencia/eventos.csv) se empareja con la operación del
generador (latencia/bateria3_manifiesto.jsonl) sobre la misma ruta cuyo instante
es el más cercano anterior a detected_at. Cada operación se usa una sola vez.

Uso:
    python3 scripts/latencia_por_tipo.py <paquete>
    p. ej.: python3 scripts/latencia_por_tipo.py tesis/cierre/evidencia/v2-eval-20260923T215624Z

Percentiles: interpolación lineal (misma convención que latencia/resumen.txt).
Sin dependencias externas.
"""
import csv, json, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

def pct(v, p):
    v = sorted(v); k = (len(v) - 1) * p / 100; f = int(k); c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)

def ts(s):
    return datetime.fromisoformat(s.replace('+00', '+00:00')).timestamp()

pkg = Path(sys.argv[1])
ops = [json.loads(l) for l in open(pkg / 'latencia/bateria3_manifiesto.jsonl')]
evs = list(csv.DictReader(open(pkg / 'latencia/eventos.csv')))
por_ruta = defaultdict(list)
for o in ops:
    por_ruta[o['ruta_agente']].append(o)
usadas, lat, sin_par, desfases = set(), defaultdict(list), 0, []
for e in sorted(evs, key=lambda e: ts(e['detected_at'])):
    d = ts(e['detected_at'])
    cand = [o for o in por_ruta.get(e['path'], []) if o['ts_epoch'] <= d + 0.005 and o['seq'] not in usadas]
    if not cand:
        sin_par += 1; continue
    o = max(cand, key=lambda o: o['ts_epoch'])
    usadas.add(o['seq']); desfases.append(d - o['ts_epoch'])
    lat[o['operacion']].append(float(e['latencia_ms']))
print(f"eventos={len(evs)} emparejados={len(evs)-sin_par} sin_par={sin_par} desfase_max_ms={max(desfases)*1000:.1f}")
print("tipo\tn\tmedia\tp50\tp95\tp99\tmax")
for t in ('modify', 'create', 'delete'):
    v = lat[t]
    if v:
        print(f"{t}\t{len(v)}\t{sum(v)/len(v):.3f}\t{pct(v,50):.3f}\t{pct(v,95):.3f}\t{pct(v,99):.3f}\t{max(v):.3f}")
sin_evento = defaultdict(int)
for o in ops:
    if o['seq'] not in usadas:
        sin_evento[o['operacion']] += 1
print("operaciones sin evento por tipo:", dict(sin_evento))
