## 1. Dependencias

- [x] 1.1 Agregar `react-diff-viewer-continued` a `frontend/package.json` y fijar versión
- [x] 1.2 Agregar `sonner` (toasts) a `frontend/package.json` y fijar versión
- [x] 1.3 Instalar con pnpm y verificar que el build (`pnpm build`) sigue verde
- [x] 1.4 Montar `<Toaster />` de sonner en `App.tsx` (o `MainLayout`) para que los toasts funcionen globalmente

## 2. Capa API y tipos

- [x] 2.1 Crear `frontend/src/api/events.ts` con tipos `EventListItem`, `EventDetail`, `EventListResponse` y `EventFilters` derivados de los contratos de `backend-events-api`
- [x] 2.2 Implementar en `events.ts` `getEvents(filters): Promise<EventListResponse>` que serializa `status[]`, `path_prefix`, `date_from`, `date_to`, `include_superseded`, `page`, `page_size` como query params sobre `apiClient`
- [x] 2.3 Implementar en `events.ts` `getEvent(id): Promise<EventDetail>` sobre `GET /events/{id}`
- [x] 2.4 Crear `frontend/src/api/actions.ts` con tipos `BulkItem`, `BulkResult` y la unión de `reason` de fallos
- [x] 2.5 Implementar `approve({event_id, version, confirm_absent?})` y `reject({event_id, version, action})` sobre `POST /actions/approve` y `/actions/reject`
- [x] 2.6 Implementar `bulkApprove({items})` y `bulkReject({items, action})` sobre `POST /actions/bulk-approve` y `/actions/bulk-reject`

## 3. Sincronización de filtros en URL

- [x] 3.1 Crear módulo puro `parseEventFilters(searchParams): EventFilters` que lee `status[]`, `path_prefix`, `date_from`, `date_to`, `include_superseded`, `page` desde `URLSearchParams` con defaults (page=1, page_size=50, include_superseded=false)
- [x] 3.2 Crear `serializeEventFilters(filters): URLSearchParams` (inversa de 3.1), omitiendo valores default
- [x] 3.3 Agregar tests unitarios de round-trip parse/serialize (incluye multi-select status y toggle superseded)

## 4. Hooks (TanStack Query + SSE)

- [x] 4.1 Crear `frontend/src/hooks/useEvents.ts` con `useQuery` cuyo query key deriva de `EventFilters` y llama `getEvents`
- [x] 4.2 Crear `frontend/src/hooks/useEvent.ts` con `useQuery` por `id` que llama `getEvent`
- [x] 4.3 Crear `frontend/src/hooks/useEventActions.ts` con mutaciones approve/reject/bulkApprove/bulkReject; en 409 mostrar toast e invalidar queries del evento + lista; en 422 `absent_confirmation_required` exponer el flag para que la UI reintente con `confirm_absent`
- [x] 4.4 Crear `frontend/src/hooks/useAlertsSSE.ts` que abre `EventSource` a `GET /alerts/stream?token=<accessToken>` (token desde `useAuthStore`), dispara toast por alerta nueva, y cierra la conexión en cleanup

## 5. DiffViewer seguro

- [x] 5.1 Crear `frontend/src/components/ui/DiffViewer.tsx` con `react-diff-viewer-continued`, opciones de escapado activas, vista split por defecto; NUNCA `dangerouslySetInnerHTML`
- [x] 5.2 Implementar detección de binario (byte nulo / no-UTF8); binario → renderizar hash + hex dump de los primeros 256 bytes en lugar del diff de texto
- [x] 5.3 Test unitario de la detección binario (texto vs. contenido con byte nulo)

## 6. EventTimeline

- [x] 6.1 Crear `frontend/src/components/ui/EventTimeline.tsx` que arma la cadena por `parent_event_id` en orden cronológico, marca los `superseded` y destaca el evento accionable más reciente

## 7. EventsTable con selección

- [x] 7.1 Crear `frontend/src/components/ui/EventsTable.tsx` con columnas `path`, `status`, `detected_at` y apertura de detalle por fila
- [x] 7.2 Agregar checkbox por fila + checkbox de cabecera "seleccionar todos en la página"; la selección se mantiene como `Set<number>` en estado del padre y se limpia al cambiar página/filtro
- [x] 7.3 Mostrar ícono de cadena rota + link a `parent_event_id` para filas `superseded`

## 8. BulkActionBar

- [x] 8.1 Crear `frontend/src/components/ui/BulkActionBar.tsx` que se renderiza solo cuando hay ≥1 seleccionado, con acciones aprobar/rechazar y el conteo
- [x] 8.2 Modal de confirmación de bulk approve: mostrar conteo + primeras 10 paths → `bulkApprove`
- [x] 8.3 Modal de confirmación de bulk reject: pedir acción `restore`/`quarantine` → `bulkReject`
- [x] 8.4 Traducir `{succeeded[], failed[]}` en toast con conteos e invalidar la query de la lista

## 9. RejectModal

- [x] 9.1 Crear `frontend/src/components/ui/RejectModal.tsx` con selector `restore`/`quarantine` para reject normal → `reject`
- [x] 9.2 Branch `baseline_absent`: si `hash_detected === null`, ocultar el selector, mostrar mensaje de archivo ausente, y al confirmar llamar `reject` con `action:"restore"` (backend no-op, 200)

## 10. EventDetail

- [x] 10.1 Crear `frontend/src/pages/EventDetail.tsx` (page o drawer) que consume `useEvent` y muestra `path`, `hash_detected`, timestamps dobles (`detected_at`/`received_at`), contexto de proceso (`process_pid`/`process_uid`/`process_exe`), `status`, `resolved_at`/`resolved_by`
- [x] 10.2 Integrar `DiffViewer` y `EventTimeline` en el detalle
- [x] 10.3 Botones approve/reject individuales cableados a `useEventActions` (reject abre `RejectModal`); manejo de 404 sin romper la app

## 11. Página Events y routing

- [x] 11.1 Crear `frontend/src/pages/Events.tsx` que cablea `useSearchParams` + `parseEventFilters` + `useEvents`, los controles de filtro multi-select, el toggle "Mostrar superseded", la paginación y `EventsTable`
- [x] 11.2 Integrar la selección y `BulkActionBar` en `Events.tsx`
- [x] 11.3 Montar `useAlertsSSE` en la vista (o en `MainLayout`) para el feed de alertas
- [x] 11.4 Registrar en `App.tsx` la ruta real `/events` (reemplaza el placeholder de C17) y la ruta nueva `/events/:id`

## 12. Verificación y commit

- [x] 12.1 Correr `pnpm build` y `pnpm lint`; verificar 0 usos de `dangerouslySetInnerHTML` en todo `frontend/src`
- [x] 12.2 Correr los tests unitarios (filtros, detección binario) y dejarlos verdes
- [ ] 12.3 Commit con conventional commit (`feat(frontend): ...`), sin Co-Authored-By
