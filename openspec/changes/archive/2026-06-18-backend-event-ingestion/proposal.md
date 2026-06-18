## Why

C10 cerró el loop en el agente: el decision engine detecta, evalúa y actúa de forma autónoma. Ahora el backend necesita procesar esos eventos con lógica de negocio completa: validar transiciones de estado, encadenar eventos superseded, aplicar rate limiting por agente, y exponer la historia de eventos via REST. Sin C11 el backend recibe eventos pero no los procesa ni los hace visibles a la UI.

## What Changes

- Extiende el consumer de eventos (C08) con: validación de transiciones contra la máquina de estados canónica (409 si inválida), encadenamiento superseded (cuando existe `pending` en el mismo path → el anterior pasa a `superseded` y el nuevo lleva `parent_event_id`; compactación si >10 eventos por path), rate limit 100 eventos/min por `agent_id` con rechazo tipado, y política de retención 30 días para eventos terminales no referenciados en `audit_log`.
- Nuevos endpoints REST: `GET /events` paginado (50/pág) con filtros multi-select por estado/fecha/path (excluye `superseded` por defecto), y `GET /events/{id}` con timestamps dobles y contexto de proceso.
- Agrega el valor `rate_limited` al enum `RejectionReason` para registrar excedentes de rate limit en `rejected_events_audit`.

## Capabilities

### New Capabilities

- `backend-events-api`: Endpoints REST para consultar eventos — `GET /events` (paginado con filtros) y `GET /events/{id}` (detalle con timestamps dobles y contexto proceso).

### Modified Capabilities

- `backend-event-consumer`: Agrega lógica de negocio sobre la infraestructura de C08 — validación de transiciones de estado, encadenamiento superseded con compactación, rate limiting 100/min por `agent_id`, y retención 30 días.
- `domain-models`: Agrega `rate_limited` al enum `RejectionReason` para cubrir rechazos por rate limit (D7).

## Impact

- `backend/app/modules/events/consumer.py` — extensión con lógica de negocio (superseded chain, state machine, rate limit, retention)
- `backend/app/modules/events/router.py` — NUEVO: endpoints GET /events y GET /events/{id}
- `backend/app/modules/events/models.py` — agregar `rate_limited` a `RejectionReason`
- `backend/app/main.py` — registrar router de eventos
- Reglas cubiertas: RN-10, RN-11, RN-12, RN-13, RN-14, RN-21, RN-22, RN-23, RN-24, RN-71, RN-72, RN-88, RN-90, RN-91, RN-98, RN-105
- Decisiones aplicadas: D4 (RejectionReason tipado), D7 (rate limit viaja con primer feature que lo necesita)
