## 1. Contrato compartido de mensajes (D7)

- [x] 1.1 Crear `backend/app/core/streams.py` con `canonical_json(payload)` (serializa con `sort_keys=True`, separadores compactos, excluyendo `signature`)
- [x] 1.2 Agregar `sign_payload(secret, payload)` y `verify_payload(secret, payload)` en `streams.py` usando `hmac.new(secret, canonical_json(payload).encode(), hashlib.sha256)`
- [x] 1.3 Definir constante `SCHEMA_VERSION` soportada y helper `check_schema_version(payload)` (rechaza mayor, ignora campos desconocidos) — RN-91
- [x] 1.4 Definir nombres de streams (`events`, `agent_heartbeat`, `commands`) y group (`fim-backend`) como constantes compartidas
- [x] 1.5 Crear el espejo del helper de firma en el agente (`agent/streams.py`): `canonical_json`, `sign_payload` (lee `shared_secret` de `/var/lib/fim-agent/secrets/shared_secret`)

## 2. Agente — cola offline (queue.py)

- [x] 2.1 Crear `agent/queue.py` con `enqueue(event)` que escribe a `{detected_at_ms}_{event_id}.json.tmp` + `os.replace()` al nombre final — RN-38, RN-41
- [x] 2.2 Implementar `iter_fifo()` que lista archivos ordenados por prefijo de timestamp — RN-39
- [x] 2.3 Implementar `remove(event_id)` que borra el archivo de cola del evento confirmado — RN-40
- [x] 2.4 Implementar límite de 100 MB con drop-oldest antes de encolar — RN-84
- [x] 2.5 Exponer `queue_size` (conteo) y `queue_pressure` (ratio `used_bytes/100MB`) — RN-84
- [x] 2.6 Barrer archivos `.tmp` huérfanos al inicializar el módulo

## 3. Agente — publisher (publisher.py)

- [x] 3.1 Crear `agent/publisher.py` que arma el payload (`event_id` UUID v4, `detected_at`, `schema_version`, datos del cambio) y lo firma con `sign_payload` — RN-56, RN-79, RN-91
- [x] 3.2 Implementar `publish(event)`: encolar primero, luego `XADD` al stream `events`
- [x] 3.3 Implementar drenaje FIFO de la cola al (re)conectar con Valkey — RN-39
- [x] 3.4 Implementar reintento de publicación si no llega `event_ack` en 60 s — RN-40, RN-73

## 4. Agente — listener de event_ack y heartbeat

- [x] 4.1 Implementar escucha del stream `commands` filtrando `target_agent_id IN (self.agent_id, null)` — D5, RN-106
- [x] 4.2 Al recibir `event_ack`, llamar `queue.remove(event_id)` — RN-40, RN-73
- [x] 4.3 Crear `agent/heartbeat.py` que publica en `agent_heartbeat` cada 10 s `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, shutdown, schema_version}` — RN-92
- [x] 4.4 Leer `ruleset_version` desde `state.json` para el heartbeat
- [x] 4.5 Propagar `shutdown: true` en heartbeats durante drenaje SIGTERM — RN-93

## 5. Agente — cableado del loop

- [x] 5.1 Cablear en `agent/__main__.py` las tareas asyncio: drenaje de cola, listener de `commands`, heartbeat (una conexión Valkey por proceso) — D8
- [x] 5.2 Asegurar que el agente NO abre ningún socket TCP en LISTEN — D8, RN-108

## 6. Backend — event consumer (consumer.py)

- [x] 6.1 Crear `backend/app/modules/events/consumer.py` con creación del group `fim-backend` (`MKSTREAM`) sobre `events` — RN-56
- [x] 6.2 Al arrancar, releer pendientes con `XREADGROUP ... 0` antes de leer nuevos (`>`) — RN-76
- [x] 6.3 Implementar pipeline de validación barato→caro: `schema_version` → `unknown_agent` → HMAC → clock skew (5 min) — RN-90, RN-91, RN-79
- [x] 6.4 Persistir rechazos en `rejected_events_audit` con `RejectionReason` tipado y `payload_dump` truncado a 4 KB; `XACK` sin `event_ack` — D4, RN-105
- [x] 6.5 Implementar dedup idempotente por `event_id`: si ya existe, `XACK` + re-publicar `event_ack` sin re-insertar ni auditar — RN-73
- [x] 6.6 Camino feliz: persistir `Event` (agregando `received_at`), `XACK`, publicar `event_ack` firmado en `commands` con `target_agent_id` — RN-73, D5, RN-106

## 7. Backend — heartbeat consumer (heartbeat_consumer.py)

- [x] 7.1 Crear `backend/app/modules/agents/heartbeat_consumer.py` que consume `agent_heartbeat`
- [x] 7.2 Por heartbeat: actualizar `Agent.last_heartbeat`, `Agent.queue_pressure`, `status = online`; `shutdown: true` → `draining` — RN-92, RN-93
- [x] 7.3 Tarea de barrido periódica (~10 s): marcar `offline` a agentes con `last_heartbeat` > 30 s — RN-92

## 8. Backend — arranque en lifespan

- [x] 8.1 Arrancar `consumer` y `heartbeat_consumer` (+ barrido) como tareas asyncio en el lifespan de `backend/app/main.py`
- [x] 8.2 Asegurar cancelación cooperativa de las tareas en el shutdown del lifespan

## 9. Tests

- [x] 9.1 Test `queue.py`: escritura atómica, FIFO, drop-oldest a 100 MB, `queue_pressure`, barrido de `.tmp`
- [x] 9.2 Test `publisher.py`: payload firmado verificable, encolar offline, drenaje FIFO, reintento a 60 s
- [x] 9.3 Test `streams.py`: `canonical_json` determinístico, `verify_payload` rechaza firma alterada, `schema_version` mayor rechazado
- [x] 9.4 Test consumer: rechazos (`clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`) → `rejected_events_audit`; dedup idempotente; camino feliz persiste + `event_ack`
- [x] 9.5 Test heartbeat consumer: `online`/`draining` por heartbeat, `offline` por barrido a 30 s
- [x] 9.6 Test de integración del done criterion: evento publicado → consumido → `XACK` → `event_ack` → agente borra de cola; heartbeat visible con `online`
