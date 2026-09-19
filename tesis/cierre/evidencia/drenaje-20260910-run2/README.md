# Evaluación de drenaje 2026-09-10 — Run 2

Nueva evaluación instrumentada del trayecto real:

`cola local → XADD events → XREADGROUP → HMAC → PostgreSQL COMMIT → XACK → event_ack firmado → borrado local`.

No reinterpreta ni reemplaza la corrida histórica de 2.988 eventos en 153 s.

## Condiciones

- Código evaluado: se registra en `environment.json`.
- Topología: un único anfitrión físico; PostgreSQL y Valkey en contenedores aislados.
- Volumen: 3.000 eventos preencolados, rutas únicas, acción `manual_review`.
- Rate limit experimental: 100.000 eventos/60 s; default de producción: 100/60 s.
- Activos: firma y validación HMAC, persistencia PostgreSQL, consumer group, XACK, `event_ack` firmado y eliminación durable de cola.
- El tiempo principal empieza antes del flush de comandos previo al drenaje y termina cuando PostgreSQL contiene los 3.000 eventos y la cola local queda vacía.
- La construcción de la cola offline se mide pero se excluye del drenaje.
- Reloj: `time.perf_counter_ns`, monotónico, mismo proceso/anfitrión.

## Reproducción

```bash
docker run -d --rm --name fim-drain-postgres \
  -e POSTGRES_DB=fim_drain -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=controlled \
  -p 127.0.0.1:55441:5432 postgres:18.3
docker run -d --rm --name fim-drain-valkey \
  -p 127.0.0.1:56380:6379 valkey/valkey:9.0.3

until docker exec fim-drain-postgres pg_isready -U fim -d fim_drain; do sleep 1; done
until docker exec fim-drain-valkey valkey-cli ping | grep -q PONG; do sleep 1; done

env PYTHONPATH=backend:. \
  DATABASE_URL=postgresql+psycopg://fim:controlled@127.0.0.1:55441/fim_drain \
  VALKEY_URL=valkey://127.0.0.1:56380/0 \
  JWT_SECRET_CURRENT=controlled-not-a-production-secret \
  RATE_LIMIT_INGEST_EVENTS=100000 \
  RATE_LIMIT_INGEST_WINDOW_SECONDS=60 \
  backend/.venv/bin/python docs/cierre/evidencia/drenaje-20260910-run2/run_profile.py \
  | tee docs/cierre/evidencia/drenaje-20260910-run2/stdout.log

docker stop fim-drain-postgres fim-drain-valkey
```

## Artefactos

- `summary.json`: resultados agregados y contraste histórico/umbral.
- `metrics.jsonl`: timestamps monotónicos crudos por evento.
- `environment.json`: entorno sanitizado e identidad del código.
- `stdout.log`: salida de la ejecución.
- `SHA256SUMS`: integridad del paquete.

Los endpoints, credenciales y secretos del comando son exclusivamente locales y controlados.
