## Context

Change 06 (`agent-mtls-bootstrap`) dejó al agente con un canal mTLS y dos secretos persistidos en disco: `shared_secret` (32 bytes raw en `/var/lib/fim-agent/secrets/shared_secret`, 0400) para HMAC de mensajes, y `master_secret` para baseline. Change 03 (`domain-models`) definió las tablas `Event`, `Agent` y `RejectedEventAudit` con sus enums. Lo que falta es el flujo de datos: ningún evento viaja del agente al backend ni el backend infiere el estado de un agente.

Este es un change **cross** (agente + backend) que construye la columna vertebral del loop de M2 sobre Valkey Streams (RN-55). Los tres streams ya están decididos: `events` (agente → backend), `agent_heartbeat` (agente → backend), `commands` (backend → agente). El agente no expone HTTP (D8, RN-108): todo es asincrónico sobre streams. El cliente Valkey del backend ya existe (`backend/app/core/valkey.py`); el agente abre su propia conexión Valkey con el cert mTLS.

Restricciones clave del dominio:
- **At-least-once + dedup idempotente** (RN-73, C3): el agente puede reenviar; el backend deduplica por `event_id`.
- **Borrado de cola solo tras `event_ack`** (RN-40): la cola local es la fuente de durabilidad hasta la confirmación end-to-end.
- **Defensa en profundidad**: además del canal mTLS, cada mensaje lleva HMAC-SHA256 (RN-79) y `schema_version` (RN-91).
- **Backend single-instance** (RN-76): un solo consumer en el group `fim-backend`; sin coordinación distribuida.

## Goals / Non-Goals

**Goals:**
- Publicar eventos firmados del agente al stream `events` con cola offline durable.
- Consumir, validar (schema, HMAC, clock skew), persistir y confirmar eventos en el backend con el protocolo ACK de 4 pasos (RN-73).
- Heartbeat periódico (10 s) y transiciones de estado de agente (`online → offline` a 30 s) inferidas del stream.
- Establecer el contrato reutilizable de mensajes de stream (`schema_version` + firma HMAC canónica) que consumen los changes 09, 10 y 11 (D7).

**Non-Goals:**
- Detección fanotify real (Change 09): aquí el publisher recibe eventos ya construidos por su llamador; los tests usan eventos sintéticos.
- Decision engine y acciones automáticas (Change 10).
- Publicación de comandos de negocio (`baseline_update`, `rule_sync`, `restore_file`, etc.) y su procesamiento en el agente (Changes 10/11) — este change solo publica `event_ack` y deja el helper de firma listo.
- Transición `offline → dead` a 5 min + webhook n8n (Change 12, notificaciones): aquí solo `online ↔ offline`.
- Endpoints HTTP de eventos / API de lectura (Change 11).

## Decisions

### D-1: Loop asyncio con tareas concurrentes, una conexión Valkey por proceso
El agente corre un event loop asyncio (`agent/__main__.py`) con tres tareas concurrentes: drenaje de cola (publisher), heartbeat, y escucha de `event_ack` en `commands`. El backend arranca dos tareas en el lifespan de FastAPI: `consumer` (events) y `heartbeat_consumer` (agent_heartbeat). 

Alternativa descartada: hilos. asyncio encaja con el modelo I/O-bound de streams (XREAD bloqueante con timeout) y con FastAPI, evita locks sobre la conexión Valkey y simplifica el shutdown cooperativo (RN-93). Una sola conexión Valkey por proceso (multiplexada por las tareas) es suficiente para single-instance.

### D-2: Cola local = archivos JSON, fuente de durabilidad hasta `event_ack`
La cola es `/var/lib/fim-agent/queue/{detected_at_epoch_ms}_{event_id}.json` con escritura atómica (escribir a `.tmp` → `os.replace()`). El nombre da ordering FIFO natural por prefijo de timestamp (RN-38, RN-39). El publisher **siempre** encola primero y luego intenta publicar; el archivo se borra **solo** al recibir `event_ack` para ese `event_id` (RN-40, RN-73). 

Esto unifica el camino online y offline: no hay rama separada "online → publicar directo". Si Valkey está disponible la latencia entre encolar y `event_ack` es de ms; si no, el archivo persiste. Trade-off aceptado: cada evento toca disco aunque el agente esté online (RN-41 ya documenta que la cola no es ACID; la durabilidad pesa más que el I/O extra en este caso de uso).

### D-3: Límite de cola 100 MB con drop-oldest y `queue_pressure`
El módulo `queue.py` calcula el tamaño total del directorio antes de encolar. Si encolar excediera 100 MB, borra los archivos más antiguos (por prefijo de timestamp) hasta hacer espacio (drop-oldest, RN-84). `queue_pressure` se expone como ratio `used_bytes / 100MB`; el heartbeat lleva el flag booleano `queue_pressure: true` cuando el ratio supera 0.8. 

Decisión de tipo: el modelo `Agent.queue_pressure` es `float | None` (domain-models), así que el heartbeat envía el **ratio float** y el backend lo persiste tal cual; el flag booleano `>0.8` es una vista derivada para la UI. Esto evita perder granularidad y respeta el schema existente.

### D-4: Firma HMAC canónica compartida (contrato D7)
Tanto eventos (agente) como `event_ack` (backend) se firman con `HMAC-SHA256(shared_secret, canonical_json(payload))`, donde `canonical_json` = `json.dumps(payload, sort_keys=True, separators=(",", ":"))` sin el campo `signature`. El agente lee `shared_secret` de `/var/lib/fim-agent/secrets/shared_secret`; el backend lo deriva/almacena por agente (entregado en bootstrap). 

Se centraliza en un helper `backend/app/core/streams.py` (`sign_payload`, `verify_payload`, `canonical_json`) y su espejo en `agent/` (p. ej. dentro de `publisher.py` o un `agent/streams.py`). Esto es el cross-cutting que viaja con este feature (D7): los changes 10/11 reutilizan el mismo helper para firmar comandos de negocio. Alternativa descartada: firmar el string del stream entry completo — frágil ante reordenamiento de campos por Valkey.

### D-5: Validación del consumer en orden barato → caro, con `RejectionReason` tipado (D4)
El backend valida en este orden y rechaza al primer fallo, persistiendo en `rejected_events_audit` (D4, RN-105) con `payload_dump` truncado a 4 KB:
1. `schema_version` parseable y `<=` soportado → `invalid_schema` (RN-91).
2. `agent_id` existe en tabla `agents` → `unknown_agent`.
3. HMAC válido contra `shared_secret` del agente → `invalid_signature` (RN-79).
4. `|received_at - detected_at| <= 5 min` → `clock_skew` (RN-90).
5. `event_id` no persistido previamente → `duplicate_event` (dedup idempotente, RN-73).

Tras pasar las 5: persiste `Event`, `XACK`, publica `event_ack`. Orden barato-primero (parseo) antes de caro (lookup DB, HMAC) reduce trabajo en ataques o ruido. El dedup (paso 5) NO es un rechazo "de error": un `event_id` ya persistido igual recibe `XACK` + `event_ack` (re-entrega legítima), pero no se re-inserta ni se audita como rechazo — solo los 4 primeros van a `rejected_events_audit`.

### D-6: `event_ack` lleva `target_agent_id` (D5, RN-106)
El `event_ack` publicado en `commands` incluye `target_agent_id = <agent_id del evento>` (no broadcast). El agente filtra `commands` por `target_agent_id IN (self.agent_id, null)` antes de procesar. Aunque `event_ack` no toca `ruleset_version`, se respeta la convención D5 de que todo mensaje en `commands` lleva el campo, para que el filtro del agente sea uniforme.

### D-7: Transición de estado por barrido temporal, no por evento
`heartbeat_consumer.py` actualiza `last_heartbeat`, `queue_pressure` y pone `status = online` en cada heartbeat recibido. Una tarea de barrido periódica (cada ~10 s) marca `offline` a los agentes con `last_heartbeat` más viejo que 30 s. La transición `online → offline` es por **ausencia** de heartbeat, no se puede disparar por evento entrante; por eso requiere el barrido. Se deja explícito que `offline → dead` (5 min) + webhook queda fuera de scope (Change 12). Durante shutdown graceful el heartbeat trae `shutdown: true` → `status = draining` (RN-93).

## Risks / Trade-offs

- **[Re-entrega duplicada satura el consumer]** → dedup idempotente por `event_id` (índice/lookup en `events`); re-entregas reciben `XACK` + `event_ack` sin re-insertar (D-5).
- **[Crash del agente entre `write` y `rename`]** → escritura atómica deja el `.tmp` huérfano, nunca un JSON corrupto en la cola; los `.tmp` se barren al arrancar (RN-41 acepta la no-transaccionalidad).
- **[Pérdida de los últimos ms de Valkey por AOF periódico]** → la cola local es el buffer: el evento solo se borra tras `event_ack`, así que un crash de Valkey antes de persistir hace que el agente reenvíe (RN-73).
- **[Clock skew legítimo entre host y backend rechaza eventos válidos]** → tolerancia de 5 min (RN-90) es la decisión cerrada; documentar que los hosts deben tener NTP. Out-of-scope corregir relojes aquí.
- **[Consumer group sin XAUTOCLAIM deja entries pending si el consumer muere mid-process]** → single-instance (RN-76): al rearrancar, el consumer lee sus propios pending con `XREADGROUP ... 0` antes de leer nuevos (`>`), reprocesando idempotentemente.
- **[`queue_pressure` como float vs flag bool]** → se persiste el float (schema existente) y se deriva el flag `>0.8` en la UI; el heartbeat manda ambos para no acoplar al consumidor (D-3).
- **[Backpressure de fanotify (Change 09) inunda la cola]** → fuera de scope aquí, pero `queue_pressure` ya es el canal de señalización previsto (RN-84, riesgo #3 de arquitectura).

## Open Questions

Ninguna que bloquee la implementación. Todas las decisiones de comportamiento están cerradas en los appendices (D4, D5, D8, RN-73, RN-84, RN-90, RN-91, RN-92, RN-93). El detalle de cómo el publisher recibe los eventos a publicar (interfaz con el detector) se define en Change 09; aquí se asume una cola/callback de entrada sintética para test.
