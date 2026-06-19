## Why

Los eventos `pending` detectados por el agente FIM acumulan sin resolución hasta que un administrador los revisa: este change cierra ese gap exponiendo los endpoints de aprobación y rechazo e implementando en el agente los handlers de los comandos que el backend le envía como consecuencia (baseline_update, restore_file, quarantine_file). Es el change central del M3 que habilita el ciclo de decisión humana completo.

## What Changes

- `POST /actions/approve` — aprueba un evento pending con optimistic lock; persiste baseline en backend (D1) y publica `baseline_update` HMAC-signed al agente (D5).
- `POST /actions/reject` — rechaza un evento pending con optimistic lock; publica `restore_file` o `quarantine_file` HMAC-signed al agente; **no actualiza** baseline.
- `POST /actions/bulk-approve` y `POST /actions/bulk-reject` — procesamiento individual por ítem con respuesta `{succeeded[], failed[]}`.
- Approve con `absent` (RN-60): requiere confirmación explícita; persiste `BaselineEntry{hash: null, status: "absent"}`.
- Agente: handler para `baseline_update` — verifica firma+versión, re-cifra baseline local AES-GCM, confirma vía `event_ack`.
- Agente: handler para `restore_file` / `quarantine_file` — filtra `target_agent_id`, journal pre-acción, ejecuta, confirma.
- **BREAKING**: ningún flujo emite `get_file_hash`; el hash del evento se usa directamente en approve (D2, D8).

Reglas cubiertas: RN-14, RN-16, RN-17 (D2), RN-25, RN-26, RN-27, RN-28, RN-29, RN-59, RN-60, RN-66, RN-74, RN-77, RN-94, RN-99, RN-104, RN-106.
Decisiones aplicadas: D1, D2, D5, D8.

## Capabilities

### New Capabilities

- `backend-approve-reject`: Endpoints REST de aprobación y rechazo de eventos — optimistic locking, publicación de comandos HMAC-signed a Valkey Streams, upsert de `baseline_entries`, `audit_log`, soporte de bulk con respuesta parcial.
- `agent-approve-reject-handler`: Handlers del agente para los comandos entrantes desde el backend — `baseline_update` (re-cifrado baseline local), `restore_file` (restauración con journal), `quarantine_file` (cuarentena con journal); todos con verificación de firma, filtro `target_agent_id` y confirmación `event_ack`.

### Modified Capabilities

- `backend-events-api`: El campo `status` de los eventos transiciona a `approved` o `rejected` como resultado de las acciones de este change; se agrega el campo `resolved_at` / `resolved_by` en las respuestas (RN-14).
- `agent-baseline`: La actualización del baseline local ahora puede dispararse desde un comando externo `baseline_update` además del scan inicial (D1) — nuevo código path de escritura re-cifrada con verificación de versión.

## Impact

- **Backend**: nuevo módulo `backend/app/modules/actions/` (router, service, schemas); modificaciones a `backend/app/modules/events/` (transiciones de estado) y `backend/app/core/streams.py` (publicación de comandos nuevos).
- **Agente**: `agent/commands.py` (nuevo módulo handler) integrado al loop de `agent/publisher.py` ya existente para la lectura del stream `commands`.
- **DB**: tabla `baseline_entries` (ya existe en domain-models) recibe upserts en approve; tabla `audit_log` recibe entradas en cada acción.
- **Valkey Streams**: nuevos tipos de comando en el stream `commands` — `baseline_update`, `restore_file`, `quarantine_file`.
- **Dependencias nuevas**: ninguna (usa cryptography, valkey-py, SQLModel ya fijados).
