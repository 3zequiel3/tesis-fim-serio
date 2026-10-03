#!/usr/bin/env python3
"""Resume el strace del generador (B-1): llamadas openat/write/close por operacion."""
import json, re, sys, collections, statistics as st
d = sys.argv[1]
ops = [json.loads(l) for l in open(f"{d}/b1_strace_v51_manifiesto.jsonl")]
rx = re.compile(r'^(\d+)\s+(\d+\.\d+)\s+(openat|write|close)\((.*)\)\s+=\s+(-?\d+|\?)(.*)$')
calls = collections.defaultdict(list)  # ruta -> [(t, syscall, args, ret)]
for l in open(f"{d}/b1_strace_v51.txt"):
    m = rx.match(l.rstrip("\n"))
    if not m: continue
    _, t, sc, args, ret, rest = m.groups()
    p = re.search(r'/srv/fim-watch/[^\s",>]+', args + rest)
    if p: calls[p.group(0)].append((float(t), sc, args, ret))
cnt = collections.Counter(); filas = []
for ruta, lst in calls.items():
    mine = sorted([o for o in ops if o["ruta_agente"] == ruta], key=lambda o: o["ts_epoch"])
    for i, o in enumerate(mine):
        t0 = o["ts_epoch"] - 0.005
        t1 = mine[i+1]["ts_epoch"] - 0.005 if i+1 < len(mine) else t0 + 5
        w = [c for c in lst if t0 <= c[0] < t1]
        c = collections.Counter(x[1] for x in w)
        wr = [x for x in w if x[1] == "write"]
        filas.append((o["operacion"], o["seq"], c["openat"], c["write"], c["close"],
                      sum(1 for x in wr if int(x[3]) != o["bytes"]),
                      (max(x[0] for x in w) - min(x[0] for x in w)) * 1000 if w else 0.0))
for op in ("create", "modify"):
    f = [x for x in filas if x[0] == op]
    print(f"{op}: n={len(f)} openat/op={st.mean(x[2] for x in f):.2f} write/op={st.mean(x[3] for x in f):.2f} "
          f"close/op={st.mean(x[4] for x in f):.2f}  distribucion (openat,write,close)={dict(collections.Counter((x[2],x[3],x[4]) for x in f))}")
    print(f"   escrituras con retorno != bytes del manifiesto: {sum(x[5] for x in f)}; "
          f"duracion open..close mediana={st.median(x[6] for x in f):.3f} ms max={max(x[6] for x in f):.3f} ms")
tot = [x for x in filas if x[0] == "modify"]
print(f"total modify: openat={sum(x[2] for x in tot)} write={sum(x[3] for x in tot)} close={sum(x[4] for x in tot)}")
print(f"lineas strace totales: {sum(1 for _ in open(f'{d}/b1_strace_v51.txt'))}")
