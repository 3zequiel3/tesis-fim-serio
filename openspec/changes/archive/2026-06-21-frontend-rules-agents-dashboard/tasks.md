## 1. SystemBanner fix — health shape mismatch

- [x] 1.1 Reemplazar `interface HealthResponse { components: HealthComponent[] }` en `SystemBanner.tsx` por el shape real del backend: `{ postgres: string; valkey: string; n8n: string; agents: string }`
- [x] 1.2 Adaptar la lógica "any component down" para iterar `Object.values()` sobre el objeto plano en vez de `data?.components.filter()`
- [x] 1.3 Verificar que el banner rojo dispara cuando algún valor no es `"ok"`

## 2. API layer — types y fetch functions

- [x] 2.1 Crear `frontend/src/api/rules.ts` con `getRules()`, `createRule()`, `updateRule()`, `deleteRule()` consumiendo GET/POST/PUT/DELETE /rules; tipar `RuleSeverity` y `RuleAction` como enums
- [x] 2.2 Crear o ampliar `frontend/src/api/agents.ts` con `getAgents()`, `getAgent()`, `updateAgentConfig()`, `triggerRescan(force: boolean)` consumiendo GET /agents, GET /agents/{id}, POST /agents/{id}/config, POST /agents/{id}/rescan
- [x] 2.3 Ampliar `frontend/src/api/alerts.ts` (o crear si no existe) con `getAlerts(filters)`, `getFailedAlerts()`, `retryAlert()`, `discardAlert()` consumiendo GET /alerts, GET /alerts/failed, POST /alerts/{id}/retry, DELETE /alerts/{id}
- [x] 2.4 Crear `frontend/src/api/dashboard.ts` con `getDashboardSummary()` que agrega datos de /events, /agents y /health/components para los contadores del dashboard

## 3. Hooks TanStack Query

- [x] 3.1 Crear `frontend/src/hooks/useRules.ts` con queries `['rules']` y mutaciones para create/update/delete con invalidación automática
- [x] 3.2 Crear `frontend/src/hooks/useAgents.ts` con query `['agents']` y mutaciones para updateConfig y rescan; manejar el 409 de rescan y exponer el `count` del body
- [x] 3.3 Crear `frontend/src/hooks/useAlerts.ts` con queries `['alerts', filters]` y `['alerts', 'failed']`; mutaciones para retry y discard con invalidación automática
- [x] 3.4 Crear `frontend/src/hooks/useDashboard.ts` con query `['dashboard']` y `refetchInterval: 30000`

## 4. Componentes UI reutilizables

- [x] 4.1 Crear `frontend/src/components/ui/RuleForm.tsx`: formulario con campos pattern (texto), severity (select), action (select); validación client-side de pattern no vacío
- [x] 4.2 Crear `frontend/src/components/ui/AgentCard.tsx`: card con status badge, queue_pressure bar, last-seen; botones config y rescan deshabilitados cuando `status === "draining"` con tooltip
- [x] 4.3 Crear `frontend/src/components/ui/RescanConfirmModal.tsx`: modal que recibe `pendingCount: number` y callbacks onConfirm/onCancel; botones "Cancelar" y "Forzar rescan"

## 5. Página Rules

- [x] 5.1 Crear `frontend/src/pages/Rules.tsx`: listado de reglas usando `useRules`; columnas pattern, severity, action, sync status; botones "Nueva regla", editar, eliminar por fila
- [x] 5.2 Integrar `RuleForm.tsx` como modal/panel para crear y editar; cerrar y refetch al guardar
- [x] 5.3 Implementar delete con dialog de confirmación inline (sin modal separado)
- [x] 5.4 Implementar indicador de sync pending (RN-87): mostrar badge "sync pendiente" tras mutation hasta que el agente confirme `ruleset_version_applied` actualizado

## 6. Página Agents

- [x] 6.1 Crear `frontend/src/pages/Agents.tsx`: lista de `AgentCard.tsx` usando `useAgents`; layout de grilla o lista
- [x] 6.2 Implementar edición de watch paths inline en `AgentCard.tsx`: lista editable con add/remove; botón "Guardar paths" que llama `updateAgentConfig`
- [x] 6.3 Conectar botón rescan al flow two-step: call con `force=false`, si 409 → abrir `RescanConfirmModal`, si confirmado → call con `force=true`

## 7. Página Dashboard

- [x] 7.1 Crear `frontend/src/pages/Dashboard.tsx`: sección de contadores de eventos por estado usando `useDashboard`; polling cada 30s
- [x] 7.2 Agregar sección de contadores de agentes por status (online/offline/draining/dead)
- [x] 7.3 Agregar sección prominente de pending crítico/alto con emphasis visual diferenciado del total pending

## 8. Página Alerts

- [x] 8.1 Crear `frontend/src/pages/Alerts.tsx`: tabla paginada de alertas usando `useAlerts`; controles de filtro por status (pending/delivered/failed) y severity
- [x] 8.2 Persistir filtros seleccionados en URL query params (patrón del Events page de C18)

## 9. Página FailedAlerts

- [x] 9.1 Crear `frontend/src/pages/FailedAlerts.tsx`: tabla de alertas fallidas usando `useAlerts` con query `['alerts', 'failed']`; columnas alert_id, severity, failed_at, canal
- [x] 9.2 Implementar botón retry individual por fila: call POST /alerts/{id}/retry + invalidar query
- [x] 9.3 Implementar selección múltiple + bulk retry: checkbox por fila + botón "Reintentar seleccionadas"
- [x] 9.4 Implementar botón discard por fila con confirmación: call DELETE /alerts/{id} + invalidar query

## 10. Routing y navegación

- [x] 10.1 Agregar rutas `/rules`, `/agents`, `/dashboard`, `/alerts`, `/alerts/failed` en el router principal
- [x] 10.2 Agregar links a las nuevas páginas en el `Sidebar` con íconos apropiados
- [x] 10.3 Hacer `/dashboard` la ruta por defecto post-login (si no ya lo es)
