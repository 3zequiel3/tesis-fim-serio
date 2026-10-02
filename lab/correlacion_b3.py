"""Item 9: attribute the gap between generated operations and persisted events.

Joins on time, not path: the Battery 3 export carries no path column. At 0.28
operations per second the spacing is wide except inside collapsed, reverted and
ephemeral groups — which is precisely where the gap is expected to fall.
"""
import csv
import json
import sys
from collections import Counter
from datetime import datetime

TOL_S = 1.5

man = json.load(open(sys.argv[1]))
ops = man["cambios"]

events = []
with open(sys.argv[2]) as fh:
    for row in csv.DictReader(fh):
        ts = datetime.fromisoformat(row["detected_at"]).timestamp()
        events.append([ts, False])
events.sort()

unmatched = []
for op in ops:
    target = op["ts_epoch"]
    best, best_d = None, TOL_S
    for ev in events:
        if ev[1]:
            continue
        d = abs(ev[0] - target)
        if d < best_d:
            best, best_d = ev, d
    if best is None:
        unmatched.append(op)
    else:
        best[1] = True

print(f"operaciones={len(ops)}  eventos={len(events)}  sin_correlacion={len(unmatched)}")
print(f"eventos_no_atribuidos={sum(1 for e in events if not e[1])}")
print()
print("operaciones sin evento, por patrón y operación:")
for (pat, oper), n in sorted(Counter((o["patron"], o["operacion"]) for o in unmatched).items(), key=lambda t: -t[1]):
    print(f"  {pat:10s} {oper:8s} {n}")
print()
print("total de operaciones por patrón (denominador):")
for pat, n in sorted(Counter(o["patron"] for o in ops).items()):
    print(f"  {pat:10s} {n}")
print()
print("muestra de las primeras 8 sin evento:")
for o in unmatched[:8]:
    print(f"  seq={o['seq']:4d} {o['patron']:10s} {o['operacion']:8s} grupo={o['grupo']} {o['ruta_relativa']}")
