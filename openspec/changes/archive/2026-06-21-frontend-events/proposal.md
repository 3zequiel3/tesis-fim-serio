## Why

El shell del frontend (C17) ya autentica y enruta, pero `/events` es solo un placeholder. Esta change construye la pantalla central de operación de la plataforma FIM: el panel donde el admin revisa eventos de integridad, inspecciona el diff de cada archivo modificado, y aprueba o rechaza cambios. Sin esta pantalla, todo el backend de eventos (C11), aprobación/rechazo (C13) y alertas SSE (C16) no tiene consumidor de UI. Es el primer feature frontend que ejerce el ciclo de vida completo del evento de cara al usuario.

## What Changes

- **Página `Events.tsx`**: tabla paginada (50/pág, RN-99/W15) con filtros multi-select (status, path_prefix, date_from, date_to) y toggle "Mostrar superseded" — todo el estado de filtros/página vive en la URL como query params (deep-link friendly). Por defecto excluye `superseded` (RN-98/W1).
- **`EventsTable.tsx`**: tabla con checkbox por fila + "seleccionar todos en la página"; los `superseded` aparecen con ícono de cadena rota y link al `parent_event_id`.
- **`BulkActionBar.tsx`**: barra de acciones masivas (aprobar/rechazar selección) que aparece cuando hay ≥1 fila marcada, con modal de confirmación (RN-99/W15).
- **Detalle de evento** (`EventDetail`): path, hash, timestamps dobles (`detected_at`/`received_at`, RN-90), contexto de proceso (PID/UID/exe, RN-03), estado y cadena.
- **`DiffViewer.tsx`**: usa `react-diff-viewer-continued` con escapado activo; **PROHIBIDO** `dangerouslySetInnerHTML` (RN-96/W8). Auto-detección texto/binario; binario → hash + hex dump parcial.
- **`RejectModal.tsx`**: branch `baseline_absent` (oculta restore/quarantine, mensaje especial, RN-77/C10); manejo de HTTP 409 con toast + refresh.
- **`EventTimeline.tsx`**: visualiza la cadena de eventos por `parent_event_id` (RN-21–24).
- **Feed de alertas en tiempo real vía SSE**: hook `useAlertsSSE` consume `GET /alerts/stream?token=<jwt>` con `EventSource`; alertas nuevas disparan toast automáticamente.
- **Nueva dependencia**: `react-diff-viewer-continued` (diff seguro) y una librería de toasts (`sonner`).

## Capabilities

### New Capabilities
- `frontend-events`: pantalla de gestión de eventos del frontend — listado paginado con filtros sincronizados en URL, detalle con diff viewer seguro y timeline de cadena, aprobación/rechazo individual y masivo con optimistic locking (409), y feed de alertas en tiempo real vía SSE.

### Modified Capabilities
<!-- Ninguna. Esta change introduce una capacidad frontend nueva que consume specs backend ya existentes (backend-events-api C11, backend-approve-reject C13, sse-alerts C16) sin modificar sus requisitos. -->

## Impact

- **Código nuevo (frontend)**:
  - `frontend/src/api/events.ts`, `frontend/src/api/actions.ts`
  - `frontend/src/hooks/useEvents.ts`, `frontend/src/hooks/useEvent.ts`, `frontend/src/hooks/useEventActions.ts`, `frontend/src/hooks/useAlertsSSE.ts`
  - `frontend/src/components/ui/{DiffViewer,EventTimeline,EventsTable,BulkActionBar,RejectModal}.tsx`
  - `frontend/src/pages/Events.tsx`, `frontend/src/pages/EventDetail.tsx`
- **Código modificado**: `frontend/src/App.tsx` (registrar ruta real `/events` y `/events/:id`), `frontend/package.json` (deps).
- **APIs consumidas** (sin cambios): `GET /events`, `GET /events/{id}`, `POST /actions/{approve,reject,bulk-approve,bulk-reject}`, `GET /alerts/stream`.
- **Dependencias DAG**: C17 (`frontend-shell-auth`) y C13 (`backend-approve-reject`) — ambas archivadas. C16 (`backend-sse-alerts`) archivada (provee `/alerts/stream`).
- **Reglas cubiertas**: RN-03, RN-22, RN-23, RN-71, RN-74, RN-77, RN-96, RN-97, RN-98, RN-99.
- **Decisiones aplicadas**: W8 (DiffViewer seguro), W1 (toggle superseded en URL), W15 (bulk + paginación), W13 (timestamps dobles en detalle), RN-77/C10 (branch baseline_absent), D7 (cross-cutting con primer feature).
