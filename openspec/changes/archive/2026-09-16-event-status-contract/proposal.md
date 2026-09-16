## Why

RN-13 establece que un evento sobre el que el agente ya ejecutó una acción se crea con estado `auto_restored`, `quarantined` o `alert_only` y **no pasa por `pending`**. Esa regla es hoy completamente inoperante en producción: el agente nunca emite un campo `status` en el payload (`DetectedChange.to_event_data()` no lo produce, `agent/detector.py:79-86`) y la ingesta del backend defaultea a `pending` (`status_str = event_data.get("status", "pending")`, `backend/app/modules/events/service.py:141`). El resultado es que los tres estados terminales de origen agente son **inalcanzables** en la base de datos: son miembros muertos del enum `EventStatus`, y todo el relato del decision engine de esta tesis es indemostrable. Un archivo ya restaurado automáticamente se le presenta al operador como pendiente de decisión, y aprobarlo emite un segundo comando redundante sobre un archivo ya resuelto.

El agente **ya publica** la información necesaria: `evaluate_and_act` setea `payload["action"]` (`agent/decision.py:65`) y `payload["action_failed"] = True` ante fallo (`agent/decision.py:80`), ambos cruzan el stream firmados por HMAC (`_build_payload` hace `**event_data`, `agent/publisher.py:145`) y el consumer pasa el payload completo a `ingest_event` sin allowlist (`backend/app/modules/events/consumer.py:241`). El backend simplemente descarta esas claves en el constructor `Event(...)` (`service.py:169-188`). D35/RN-129, cerrada el 2026-08-13 en el appendix "Decisiones de implementación — Abril 2026" de [reglas_de_negocio.md](../../../docs/reglas_de_negocio.md), define el contrato que esta change implementa.

## What Changes

- **Derivación del estado en el backend, no aceptación de un `status` del agente**: `ingest_event` deriva `Event.status` de `action` + `action_failed` según la tabla de D35/RN-129. La lectura actual de `event_data["status"]` **se elimina**: el backend es la única autoridad sobre `EventStatus`. La derivación es una decisión de seguridad, no de estilo — `action` es un vocabulario cerrado de cuatro valores producidos por el motor de reglas, mientras que un `status` de escritura libre permitiría a un agente comprometido inyectar eventos ya marcados como `approved` o `rejected`, salteándose el ciclo de decisión humano y su auditoría.
- **Acción fallida ⇒ `pending`, nunca terminal**: si la acción automática falló, el archivo sigue adulterado en disco y el incidente debe volver a la cola del operador con aprobar/rechazar disponibles.
- **Nueva columna persistida `Event.action_failed: bool`** (default `false`), expuesta en `EventOut`, con migración SQL idempotente `007_add_event_action_failed.sql` (convención D3, sin Alembic) y backfill `false`.
- **`resolved_at = received_at` y `resolved_by = NULL`** para los eventos terminales de origen agente: `resolved_by` nulo con `resolved_at` presente identifica una resolución automática sin operador humano.
- **Limpieza del léxico RN-71**: se elimina `payload["event_type"] = "auto_restored"` en `_auto_restore` (`agent/decision.py:188`). Ese campo tiene un vocabulario declarado (`file_modified | file_absent | file_deleted | file_created`, `agent/detector.py:66`) y `_quarantine` nunca hizo lo simétrico. El resultado de la acción viaja exclusivamente en `action` / `action_failed`.
- **Distinción visual en la UI** entre un `pending` normal y un `pending` con `action_failed = true`, que representa un fallo de remediación y tiene prioridad operativa.
- **Tests que cruzan el límite real de contrato**: la suite existente no detectó este bug precisamente porque construye payloads a mano con las claves correctas. Se agrega un test parametrizado sobre las 7 filas de la tabla de derivación que alimenta `ingest_event` con un payload producido por el agente real (`DetectedChange.to_event_data()` + `DecisionEngine.evaluate_and_act`).

## Capabilities

### New Capabilities
<!-- Ninguna. Esta change cierra el contrato de una capability existente que quedó inoperante. -->

### Modified Capabilities

- `backend-event-consumer`: `ingest_event` deriva el estado terminal desde `action`/`action_failed` en lugar de defaultear a `pending`, ignora cualquier `status` del payload, y setea `resolved_at`/`resolved_by` para los terminales de origen agente. La cadena superseded se amplía: un evento entrante terminal también supersede al `pending` activo del mismo path.
- `backend-events-api`: el modelo `Event` gana la columna `action_failed` con migración idempotente, y `EventOut` la expone.
- `agent-decision-engine`: el motor de decisión deja de sobrescribir `event_type` con el resultado de la acción; `action` y `action_failed` son los únicos portadores de ese resultado, tanto en la ruta normal como en la rehidratación del journal.
- `frontend-events`: la tabla y el detalle de eventos distinguen visualmente un evento con `action_failed = true`.

## Impact

- **Archivos afectados (backend)**: `backend/app/modules/events/service.py` (derivación + constructor `Event`), `backend/app/modules/events/models.py` (columna `action_failed`), `backend/app/modules/events/router.py` (`EventOut`), `backend/db/migrations/007_add_event_action_failed.sql` (nueva).
- **Archivos afectados (agente)**: `agent/decision.py` (eliminar la sobrescritura de `event_type` en `_auto_restore`; verificar la ruta `rehydrate`, líneas 95-154).
- **Archivos afectados (frontend)**: `frontend/src/api/events.ts` (campo `action_failed`), `frontend/src/utils/actionFailed.ts` (nueva, patrón de `ackStatus.ts`), `frontend/src/components/ui/EventsTable.tsx`, `frontend/src/pages/EventDetail.tsx`.
- **Tests**: `backend/tests/test_event_service.py` (los dos tests cross-boundary de las líneas 155-197 y 200-250 pasan a producir estados no-`pending` y deben actualizarse), nuevo `backend/tests/test_event_status_derivation.py`, test de idempotencia de migración según el molde de `test_event_severity.py:201-223`, `agent/tests/test_event_payload_contract.py`, y un vitest para el mapper del frontend según `frontend/src/utils/ackStatus.test.ts`.
- **Migración de BD**: sí — `007_add_event_action_failed.sql`, `ADD COLUMN IF NOT EXISTS`, aplicación manual por `psql` (D3, sin Alembic). No hay runner automatizado en el proyecto.
- **Sin cambio de API HTTP** más allá de un campo aditivo en `EventOut`. No hay breaking changes para clientes existentes.
- **Dependencias del DAG**: 38 (`frontend-contract-fixes` — migración 006, `severity` y el tipo de evento del frontend) y 39 (`agent-scope-filter-symlink-hardening` — patrón de badge `is_symlink` que esta change replica). El código de ambas está presente y verificado en el working tree; ninguna de las dos figura como archivada en `openspec list`.
- **Reglas cubiertas**: RN-13, RN-06, RN-71, RN-72, RN-77, RN-129. **Decisiones aplicadas**: D35 (D3 para la convención de migración, D33 como precedente de tolerancia hacia adelante y de patrón de badge).
- **Roadmap**: change 40 en [CHANGES.md](../../../CHANGES.md).
- **Contexto de riesgo**: por el problema de `ProtectSystem=strict` en la unit de systemd (fuera de scope, change separada), `action_failed = true` es hoy la ruta **común** en un host real, no un caso de borde. La rama `pending + action_failed` es la que efectivamente se va a ejercitar en la demo hasta que esa change aterrice.

**Fuera de scope** (los aborda otra change; no traerlos acá): persistir `diff_text` / `operation_type` / `hash_expected`; las capabilities de la unit systemd que hacen fallar físicamente el auto_restore; durabilidad de ack/outbox del stream; n8n; tooling de migraciones; hardening de auth.
