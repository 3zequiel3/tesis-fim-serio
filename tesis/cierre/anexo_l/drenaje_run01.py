"""Recalcula el drenaje de la primera repetición (Tabla 21) con t0 corregido."""
import csv, json
from datetime import datetime, timezone

D = "tesis/cierre/evidencia/v5-eval-20261003T102313Z/resiliencia/run-01/"
# FIN_CORTE de bateria5_run-01.log: 12:37:56.80393730, escrito sin el cero
# inicial de la fracción; el instante real es 12:37:56.080393730.
t0 = datetime(2026, 10, 3, 12, 37, 56, 80394, tzinfo=timezone.utc)

xadd = sorted(datetime.fromisoformat(json.loads(l)["timestamp"])
              for l in open(D + "traza_run-01.jsonl")
              if json.loads(l)["stage"] == "xadd_succeeded")
primer_xadd = next(t for t in xadd if t >= t0)

rec = sorted(datetime.fromisoformat(r["received_at"].replace("+00", "+00:00"))
             for r in csv.DictReader(open(D + "eventos.csv")))
reconexion = (primer_xadd - t0).total_seconds()
sin_consumo = (rec[0] - primer_xadd).total_seconds()
consumo = (rec[-1] - rec[0]).total_seconds()
print(f"eventos={len(rec)} reconexion={reconexion:.3f} sin_consumo={sin_consumo:.3f} "
      f"consumo={consumo:.3f} drenaje={(rec[-1] - t0).total_seconds():.3f} "
      f"caudal={len(rec) / consumo:.1f}")
