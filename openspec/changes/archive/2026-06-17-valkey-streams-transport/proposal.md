## Why

Tras el bootstrap mTLS (Change 06) el agente y el backend comparten un canal seguro y secretos (`shared_secret`, `master_secret`), pero todavía no intercambian datos: no hay forma de que un evento detectado llegue al backend ni de que el backend sepa si un agente está vivo. Este change construye el transporte bidireccional sobre Valkey Streams (RN-55), el loop nervioso de M2 sobre el que se apoyan el detector fanotify (Change 09) y la ingesta de eventos (Change 11). Sin él no existe el sistema FIM end-to-end.

## What Changes

- **Agente — `publisher.py`**: publica eventos en el stream `events` con `event_id` (UUID v4), `detected_at`, `schema_version`, payload del cambio y firma `HMAC-SHA256(shared_secret, canonical_json(payload))` (RN-56, RN-79, RN-91). Espera `event_ack` antes de limpiar la cola local; reintenta si no llega en 60 s (RN-40, RN-73).
- **Agente — `queue.py`**: cola offline en disco (`/var/lib/fim-agent/queue/{timestamp}_{event_id}.json`) con escritura atómica `write + rename`, límite 100 MB, política drop-oldest, y cálculo de `queue_pressure` cuando el uso supera 80% (RN-38, RN-39, RN-41, RN-84). Envío FIFO al reconectar; borrado de archivo solo tras `event_ack`.
- **Agente — `heartbeat.py`**: publica en el stream `agent_heartbeat` cada 10 s con `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, shutdown, schema_version}` (RN-92). Reporta `shutdown: true` durante drenaje graceful (RN-93).
- **Backend — `consumer.py`**: consumer group `fim-backend` sobre `events`; valida `schema_version` (RN-91), firma HMAC (RN-79) y timestamps dobles `|received_at - detected_at| <= 5 min` (RN-90); persiste el evento, ejecuta `XACK` y publica `event_ack` en `commands` (RN-73). Eventos rechazados → `rejected_events_audit` con `RejectionReason` tipado (D4, RN-105). Dedup idempotente por `event_id`.
- **Backend — `heartbeat_consumer.py`**: consume `agent_heartbeat`, actualiza `Agent.last_heartbeat`, `Agent.queue_pressure` y `Agent.status`; transición `online → offline` tras 30 s sin heartbeat (RN-92).
- **Backend — esquema de mensajes y publicación de comandos**: helper de firma HMAC y publicación de `event_ack` en `commands` con `target_agent_id` (D5, RN-106), reutilizable por changes posteriores que emitan comandos.

## Capabilities

### New Capabilities
- `agent-transport`: capa de transporte del agente FIM — publisher de eventos firmados, heartbeat periódico y cola offline atómica con confirmación bidireccional sobre Valkey Streams.
- `backend-event-consumer`: consumers del backend para los streams `events` y `agent_heartbeat` — validación (schema, HMAC, clock skew), persistencia, protocolo ACK end-to-end y transiciones de estado de agente por heartbeat.

### Modified Capabilities
<!-- Ninguna. Los modelos de dominio (Event, Agent, RejectedEventAudit) ya fueron definidos por domain-models (Change 03) y se consumen tal cual; este change no modifica requisitos de spec existentes. -->

## Impact

- **Agente** (nuevos módulos): `agent/publisher.py`, `agent/heartbeat.py`, `agent/queue.py`; cableado en `agent/__main__.py` (loop asyncio). Lee `shared_secret` desde `/var/lib/fim-agent/secrets/shared_secret` y `ruleset_version` desde `state.json`.
- **Backend** (nuevos módulos): `backend/app/modules/events/consumer.py`, `backend/app/modules/agents/heartbeat_consumer.py`, helper de mensajes/firma (p. ej. `backend/app/core/streams.py`); arranque de ambos consumers como tareas asyncio en el lifespan de `backend/app/main.py`. Persiste `Event` y `RejectedEventAudit` (ya existentes), actualiza `Agent`.
- **Infra**: usa los 3 streams Valkey (`events`, `agent_heartbeat`, `commands`) y el cliente Valkey ya inicializado (`backend/app/core/valkey.py`). Sin servidor HTTP en el agente (D8, RN-108).
- **Cross-cutting (D7)**: este change introduce el contrato de `schema_version` y la firma HMAC de mensajes de stream, que los changes 09, 10 y 11 reutilizan.
- **Reglas cubiertas**: RN-38, RN-39, RN-40, RN-41, RN-55, RN-56, RN-73, RN-84, RN-90, RN-91, RN-92. **Decisiones aplicadas**: D4 (RN-105), D5 (RN-106), D7, D8 (RN-108).
