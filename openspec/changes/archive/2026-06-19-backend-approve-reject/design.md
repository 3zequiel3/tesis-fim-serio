## Context

C13 cierra el loop de decisión humana del M3. Los eventos llegan como `pending` después del ingreso (C11). Un administrador los aprueba (cambio legítimo) o rechaza (cambio no autorizado). El backend actualiza el estado atómicamente y le comunica la decisión al agente vía Valkey Streams. El agente actúa en consecuencia: actualiza su baseline local cifrado (approve) o restaura/pone en cuarentena el archivo (reject).

Restricciones activas:
- **D2**: el backend usa `event.hash` directamente en el approve, sin consultar al agente.
- **D8**: sin HTTP del backend al agente — todo vía streams.
- **D5**: `ruleset_version` es un counter global; `baseline_update` lleva `ruleset_version++` para que el agente rastree su estado.
- **D1**: `baseline_entries` en el backend guarda metadata (sin contenido cifrado); el agente sigue siendo el único custodio del contenido.

Estado existente relevante:
- `backend/app/core/streams.py` (C08): publisher y consumer Valkey ya implementados; stream `commands` ya existe.
- `backend/app/modules/events/` (C11): modelos Event con `version: int` y `status` enum; transiciones validadas.
- `backend/app/modules/rules/` (C12): `ruleset_version` counter en Valkey y lógica de fan-out HMAC-signed ya implementada.
- `agent/publisher.py` (C08): loop de lectura del stream `commands` ya existe.
- `agent/actions.py` (C10): lógica de restore y quarantine ya implementada por el decision engine.

## Goals / Non-Goals

**Goals:**
- Approve/reject atómico con optimistic locking — 409 claro ante concurrencia.
- Approve actualiza `baseline_entries` en backend y envía `baseline_update` HMAC-signed al agente.
- Reject envía `restore_file` o `quarantine_file` HMAC-signed al agente; baseline no se toca.
- Bulk con resultado por ítem (`succeeded[]`, `failed[]`), sin atomicidad global.
- Approve de evento con `hash=null` (archivo eliminado) requiere confirmación explícita (`confirm_absent: true`).
- Agente procesa los tres tipos de comando con verificación de firma, filtro de `target_agent_id` y confirmación `event_ack`.
- `audit_log` en cada acción (approve, reject, bulk).

**Non-Goals:**
- Confirmación síncrona del agente al backend — el backend fire-and-forgets el comando; el agente confirma async vía `event_ack`.
- Rollback del estado del evento si el agente falla al ejecutar el comando — inconsistencia aceptable (RN-104).
- Aprobación de eventos que no estén en estado `pending` — → 409.

## Decisions

### D-C13-01 — Módulo `actions` separado

Nuevo módulo `backend/app/modules/actions/` con `router.py`, `service.py`, `schemas.py`. No se mezcla con `modules/events/` para mantener la separación de concerns: events es consulta, actions es mutación de estado + comandos.

**Alternativa descartada**: enpoint en `/events/{id}/approve` — viola REST semántico y mezcla lectura con escritura en el mismo módulo.

### D-C13-02 — Optimistic lock con `version` del evento

```sql
UPDATE events
SET status = :new_status,
    version = version + 1,
    resolved_at = now(),
    resolved_by = :user_id
WHERE id = :event_id
  AND version = :expected_version
  AND status = 'pending'
```

Rowcount=0 → 409 `{"code": "conflict", "detail": "event already modified or not pending"}`.

El cliente debe enviar `{event_id, version}` en el body. La versión se obtiene del `GET /events/{id}`.

**Alternativa descartada**: lock pesimista (`SELECT FOR UPDATE`) — innecesario en single-instance backend (RN-76) y más lento.

### D-C13-03 — Firma HMAC de comandos (reutiliza patrón C12)

Todos los comandos publicados al stream `commands` se firman con HMAC-SHA256 usando el `shared_secret` del agente (obtenido en bootstrap C06). La firma se calcula sobre el JSON canónico del payload (claves ordenadas, sin el campo `signature`), se codifica como hex y se incluye en el campo `signature`.

El agente verifica la firma antes de ejecutar cualquier comando. Esto ya existe para `rule_sync` (C12); se reutiliza el mismo patrón en `backend/app/core/streams.py`.

### D-C13-04 — Ausencia de archivo (RN-60) detectada por hash nulo

Si `event.hash is None`, el archivo fue eliminado. El backend detecta esto automáticamente. Si la request de approve no incluye `"confirm_absent": true`, el backend retorna 422 con `{"code": "absent_confirmation_required"}`. Con `confirm_absent: true`, crea `BaselineEntry{hash: null, status: "absent"}`.

**Alternativa descartada**: detectar ausencia desde el evento `status` — el status del evento no encode directamente la ausencia del archivo; el hash nulo es el dato canónico (D2).

### D-C13-05 — Agente: nuevo módulo `agent/commands.py`

El loop existente en `agent/publisher.py` ya lee el stream `commands`. Se agrega `agent/commands.py` con handlers para `baseline_update`, `restore_file`, `quarantine_file`. El loop llama a `commands.dispatch(command_dict)` que enruta según `command["type"]`.

Los handlers de restore y quarantine reutilizan la lógica ya implementada en `agent/actions.py` (C10) — misma función, distinto punto de entrada (stream vs. decision engine).

### D-C13-06 — Bulk: 200 OK con cuerpo parcial

`POST /actions/bulk-approve` y `bulk-reject` retornan siempre 200 con `{"succeeded": [...], "failed": [...]}`. Si todos fallan, sigue siendo 200 — el status HTTP indica que el endpoint funcionó; el contenido indica el resultado por ítem. No se usa 207 Multi-Status para simplificar el cliente.

### D-C13-07 — `ruleset_version` en `baseline_update`

El comando `baseline_update` incluye `ruleset_version` (incrementado igual que en `rule_sync`) para que el agente actualice `Agent.ruleset_version_applied` usando la misma semántica D5. El backend actualiza `Agent.ruleset_version_applied` al recibir el `event_ack` de confirmación.

### D-C13-08 — `reject` requiere `action` explícito en el body

El body de `POST /actions/reject` incluye `"action": "restore" | "quarantine"`. El administrador elige explícitamente qué acción tomar. No se infiere desde la regla que originó el evento (el humano puede contradecir la regla).

## Risks / Trade-offs

- **Comando enviado, agente offline** → El comando queda en el stream de Valkey hasta que el agente reconecte (semántica de consumer group, C08). El evento ya transitó a `approved`/`rejected` en el backend. Esto es correcto y esperado — la consistencia final la garantiza el stream. `[Low risk]`

- **Fallo entre UPDATE de DB y publicación en Valkey** → El evento queda en estado nuevo pero el agente nunca recibe el comando. Un retry del admin verá 409 (ya no está `pending`). Esta inconsistencia es aceptable en el contexto de tesis (RN-104). `[Accepted risk]` Mitigación futura: transactional outbox si se requiere.

- **Bulk de N ítems, algunos con 409** → La respuesta informa cuáles fallaron. El cliente puede reintentar solo los fallidos. `[Low risk]`

- **Reentrancy del agente** → Si el agente procesa un `baseline_update` dos veces (stream re-delivery por crash), la segunda escritura sobreescribe la misma entrada en el baseline. El resultado es idempotente porque escribe los mismos datos. `[Low risk]`

## Migration Plan

1. Deploy del backend incluye el nuevo módulo `actions/` — sin breaking changes en endpoints existentes.
2. El stream `commands` ya existe (C08) — se agregan nuevos tipos de mensajes sin cambiar el formato del consumer.
3. El agente se actualiza con `agent/commands.py` — sin cambios en el loop existente más allá del dispatch.
4. No se requieren migraciones de schema: `baseline_entries` y `audit_log` ya existen (C03).

## Open Questions

Ninguna — todas las suposiciones de este change están cerradas en D1, D2, D5, D8 (Abril 2026).
