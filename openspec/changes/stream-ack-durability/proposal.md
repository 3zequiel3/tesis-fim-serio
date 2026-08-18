## Why

El transporte agente↔backend no tiene un contrato de durabilidad: tiene un camino feliz y nada más. La consecuencia no es teórica ni intermitente — **la cola offline no puede drenar nunca**, y **los comandos de aprobación y rechazo pueden perderse sin que nadie se entere**. Son tres defectos con una sola raíz, y cada uno rompe una capacidad que la tesis presenta como resuelta.

**1. La cola de resiliencia solo funciona mientras no haga falta.** RN-90 rechaza todo evento con `abs(received_at - detected_at) > 5 min` (`backend/app/modules/events/consumer.py:207`, con `_CLOCK_SKEW_S = 300` en `:50`). RN-38 a RN-41 definen una cola en disco de 100 MB cuyo propósito explícito es sobrevivir una caída del backend. Las dos reglas se anulan entre sí: cualquier corte mayor a cinco minutos convierte el contenido íntegro de la cola en eventos irrecibibles. El agente drena, el backend rechaza los 100 MB uno por uno, y el operador pierde toda la ventana de detección justo cuando el sistema estuvo degradado.

**2. El rechazo no se comunica, y el resultado es un livelock que crece en disco.** `_reject` (`consumer.py:331-353`) inserta `RejectedEventAudit`, hace `XACK` y **no publica nada**. El docstring del módulo lo documenta como intencional (`consumer.py:15`: "Rechazos: inserta RejectedEventAudit, XACK, sin event_ack (D4, RN-105)"). Del otro lado, el agente borra un archivo de cola **solo** al recibir `event_ack` (`agent/queue.py:112`, `agent/publisher.py:319-326`) y `_retry_loop` (`agent/publisher.py:366-378`) republica cada evento sin ack cada `_ACK_TIMEOUT_S = 60.0` (`:45`) indefinidamente. Un evento rechazado entra en un ciclo permanente: se republica, se vuelve a rechazar, y cada vuelta agrega una fila a `rejected_events_audit` — tabla que ninguna política de retención toca (la retención de `events/service.py` cubre únicamente `events`). El agente gasta ancho de banda para siempre en un evento que jamás va a entrar.

**3. Los comandos de decisión no tienen outbox.** Solo `rule_sync` es durable (`backend/app/modules/rules/service.py:130-229`), y `rules/models.py:51-53` documenta explícitamente que el resto lo evita: "El resto de los comandos (baseline_update, restore_file, quarantine_file — C13/D10) se siguen insertando como `published` de forma síncrona, sin pasar por el outbox". `actions/service.py` comitea la mutación del evento en `:205` y `:279`, y **después** publica. Hay dos modos de pérdida, ambos reales:

- Si `_get_agent_secret` levanta `ValueError`, el publicador **loguea y retorna** (`actions/streams.py:109-110`, `:164-165`, `:208-209`) mientras `actions/router.py` responde `200`. El evento queda `approved` o `rejected` y ningún comando se emitió.
- Si el `XADD` falla, la excepción se propaga como `500` con el evento igualmente terminal y ya comiteado.

En ambos casos el operador cree haber restaurado un archivo que nadie tocó. El mismo hueco existe en `agents/service.py`: `update_agent_config` comitea en `:175` y publica en `:179`; `rescan_agent` comitea en `:232` y publica en `:235`.

**D37 / RN-131** se cerró el 2026-08-16 en el appendix "Decisiones de implementación — Abril 2026" de [reglas_de_negocio.md](../../../docs/reglas_de_negocio.md) (líneas 1187-1216) y fija el contrato que esta change implementa, incluida la matriz de respuestas y las cláusulas que **prevalecen sobre RN-90 y sobre RN-88**.

## What Changes

- **`sent_at` en el payload del evento, y la ventana de skew se muda a él.** El agente sella `sent_at` en el momento de publicar y **lo vuelve a sellar en cada republicación**. La ventana de cinco minutos pasa a evaluarse sobre `sent_at`; `detected_at` permanece como verdad forense y **deja de tener ventana**. Un evento legítimamente encolado durante un corte de horas llega con `detected_at` antiguo y `sent_at` reciente, y se acepta. El propósito original de RN-90 se conserva y se afila: `sent_at` es exactamente el timestamp que un tercero tendría que falsificar para que un mensaje capturado parezca actual, y va dentro del canonical JSON firmado. **Enmienda RN-90.**
- **`sent_at` va firmado, así que la firma se calcula en el momento de publicar, no en el de encolar.** El archivo de cola deja de guardar `signature` y `sent_at`: guarda el payload estable y el publicador estampa y firma justo antes de cada `XADD`. Hoy `_build_payload` firma y `_drain_queue` reenvía la firma guardada (`agent/publisher.py:143-152`, `:160-174`), lo que sería incompatible con un `sent_at` re-sellado.
- **Respuesta tipada a todo evento**, según la matriz de D37: `event_ack` para ingesta exitosa y para `duplicate_event` (el camino de dedup ya hace `XACK` + `_publish_event_ack`, `consumer.py:226-229` — es la forma que se reutiliza); **`event_nack` terminal** para `invalid_schema` y `clock_skew`; **`event_nack` con `retry_after`** para `rate_limited`; y **ninguna respuesta** para `invalid_signature` y `unknown_agent`.
- **Sin respuesta para fallos de autenticación.** Un `invalid_signature` o un `unknown_agent` no permiten firmar una respuesta verificable ni identificar al destinatario, y responder convertiría al backend en un oráculo que confirma qué `agent_id` existen. El emisor caduca por su propio límite de reintentos. Lo mismo aplica al descarte de agente revocado que ya existe (`consumer.py:183-188`).
- **Backpressure del agente ante `rate_limited`, y el evento nunca se destruye.** El agente deja de reintentar cada 60 s y frena la publicación hasta que haya presupuesto, **conservando el evento en cola**. Un evento de integridad descartado es una detección perdida, y una tormenta de cambios es precisamente el momento en que un atacante se mueve. El límite real de recursos sigue siendo el drop-oldest de los 100 MB de RN-40/RN-84, que ya es una decisión tomada y acotada. **Prevalece sobre la frase "se descartan con alerta" de RN-88**, que además nunca se implementó: hoy no se emite ninguna alerta.
- **Límite de reintentos por evento y directorio local de descarte.** Un evento que no recibe respuesta de ningún tipo no puede reintentarse para siempre. El contador de intentos se persiste **en el archivo de cola** (no en memoria: `Publisher._pending` se pierde en cada reinicio y `_drain_queue` recomienza de cero, así que un contador en RAM no acota nada). Superado el límite, el evento se mueve a un directorio local de descarte con su motivo, se contabiliza en el heartbeat y se deja de publicar.
- **Outbox para los comandos.** `baseline_update`, `restore_file` y `quarantine_file` pasan por el mismo outbox transaccional de `rule_sync`: la fila `PublishedCommand` se escribe con `status="pending"` **en la misma transacción** que la mutación del evento, y `publish_pending_commands` la publica después, con reintento. Deja de existir el estado en que un evento es terminal y su comando no se emitió; un fallo de publicación se vuelve un reintento del despachador, no una pérdida silenciosa ni un `500`. Se extiende también a `update_config` y `rescan_baseline`, que tienen el hueco idéntico (ver "Desviación explícita" más abajo).
- **Reconciliación normativa**: el docstring de `consumer.py:14-15` y D4/RN-105 dejan de decir que un rechazo no produce respuesta; RN-88 y RN-90 apuntan a D37 donde las supersede.
- **NO se bumpea `SCHEMA_VERSION`.** `check_schema_version` acepta `v <= SCHEMA_VERSION` (`backend/app/core/streams.py:47-52`): un agente con `schema_version=2` contra un backend en `1` cae en `invalid_schema`, que a partir de esta change es **terminal** — el agente borraría el evento. `sent_at` es aditivo y opcional, y `event_nack` es un `type` nuevo que el agente viejo ignora en silencio. Ver D-9 del design.

## Capabilities

### New Capabilities

- `agent-event-durability`: contrato de durabilidad del publicador del agente — sellado y re-sellado de `sent_at`, firma en el momento de publicar, consumo de la respuesta tipada (`event_ack` / `event_nack`), backpressure ante `rate_limited`, límite de reintentos por evento, directorio local de descarte con motivo, y contador de descartes en el heartbeat.

### Modified Capabilities

- `backend-event-consumer`: la ventana de skew se evalúa sobre `sent_at` con fallback tolerante a su ausencia; todo rechazo produce la respuesta tipada que le corresponde según la matriz de D37, salvo los dos motivos de autenticación, que no producen ninguna; `retry_after` derivado del rate limiter.
- `agent-transport`: el publicador estampa `sent_at`, firma al publicar, respeta el backpressure y consume `event_nack`; el borrado de cola deja de estar atado exclusivamente al `event_ack`.
- `agent-queue-durability`: el archivo de cola pasa a un sobre con metadata de intentos, tolerando los archivos con formato previo; se agrega el directorio de descarte como destino terminal local.
- `backend-approve-reject`: `baseline_update`, `restore_file` y `quarantine_file` se encolan en el outbox dentro de la transacción del evento en lugar de publicarse post-commit.
- `backend-agent-management`: `update_config` y `rescan_baseline` se encolan en el outbox dentro de su propia transacción; el consumer de heartbeat persiste el contador de eventos descartados por el agente y los endpoints de agentes lo exponen.
- `frontend-agents`: la tarjeta del agente muestra el contador de eventos descartados localmente, junto a la presión de cola que ya expone.

## Impact

- **Agente**: `agent/publisher.py` (sellado de `sent_at`, firma al publicar, handler de `event_nack`, backpressure, límite de reintentos, descarte), `agent/queue.py` (sobre con metadata de intentos, lectura tolerante del formato previo, directorio de descarte), `agent/heartbeat.py` (clave `discarded_events`), `agent/config.py` (`storage.discard_dir`, parámetros del publicador).
- **Backend**: `backend/app/modules/events/consumer.py` (ventana sobre `sent_at`, `_publish_event_nack`, matriz de respuestas, docstring), `backend/app/core/streams.py` (sin bump de versión; helpers de firma reutilizados), `backend/app/modules/actions/streams.py` y `actions/service.py` (encolado transaccional), `backend/app/modules/agents/streams.py` y `agents/service.py` (idem + `discarded_events`), `backend/app/modules/agents/models.py` y `heartbeat_consumer.py`, `backend/app/modules/rules/service.py` (el despachador ya es genérico — no se duplica mecanismo).
- **Frontend**: `frontend/src/api/agents.ts`, `frontend/src/components/ui/AgentCard.tsx`.
- **Migración de BD**: una, aditiva y nullable — `backend/db/migrations/010_add_agent_discarded_events.sql` (D3: SQL idempotente, sin Alembic, aplicación manual). La más alta existente es la `009`.
- **Docs**: `docs/reglas_de_negocio.md` (RN-88, RN-90, D4/RN-105), `docs/arquitectura_stack.md` (contrato de mensajes del stream).
- **Dependencias del DAG**: 40 (`event-status-contract`) y 41 (`agent-deployment-caps`) — ambas implementadas y comiteadas en `feat/event-status-y-deployment-caps`; esta change numera su migración a partir de la `009` que dejó la 41.
- **Reglas cubiertas**: RN-38, RN-39, RN-40, RN-41, RN-71, RN-73, RN-79, RN-84, RN-88, RN-90, RN-91, RN-105, RN-106, RN-108, RN-131. **Decisiones aplicadas**: D37 (D3 para la convención de migración; D4 reconciliada; D9/D10 como base del outbox que se extiende; D30/RN-124 sin alterar; D33/D35/D36 como precedente de tolerancia hacia adelante).
- **Roadmap**: change 42 en [CHANGES.md](../../../CHANGES.md).
- **Sin breaking change de API HTTP.** El único cambio de contrato de red es aditivo y tolerante en ambas direcciones (ver D-9 del design).

### Desviación explícita respecto de la letra de D37

D37 enumera tres comandos para el outbox: `baseline_update`, `restore_file` y `quarantine_file`. Esta change incluye además `update_config` y `rescan_baseline`, que tienen el hueco **idéntico** (`agents/service.py:175-179` y `:232-235`) y comparten el mismo publicador síncrono. Se interpreta como aplicación del principio que D37 fija — "deja de existir el estado en que un evento es terminal y su comando no se emitió" — y no como una suposición nueva: no introduce mecanismo, tabla ni semántica que D37 no haya cerrado. Dejarlos afuera además los convertiría en los dos únicos publicadores síncronos del sistema, con el defecto intacto y sin nadie que lo cubra. **Se marca acá para que quede a la vista y pueda revertirse a la enumeración literal si se prefiere.**

**Fuera de scope** (no traerlos acá):

- Persistencia de `diff_text` / `operation_type` / `hash_expected` — corresponde a la change `event-payload-persistence`.
- Los bugs de desempaquetado de `detail` en el frontend, n8n, el runner de migraciones, el hardening de auth, el barrido de integridad, `FAN_ATTRIB`.
- **Retención de `rejected_events_audit`** y del resto de las tablas sin cota. Está emparentado — el livelock del punto 2 la hace crecer — pero pertenece al trabajo de retención, no acá. Esta change corta el crecimiento en su origen; no borra lo ya acumulado ni instala la política.
