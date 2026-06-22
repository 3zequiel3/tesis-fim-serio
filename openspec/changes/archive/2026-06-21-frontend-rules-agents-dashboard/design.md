## Context

C19 construye las últimas páginas operativas de M4 consumiendo contratos backend establecidos en C12 (rules), C13 (approve/reject), C14 (agent config/rescan), C15 (notifications), C16 (SSE alerts). El shell y auth están en pie desde C17; el patrón TanStack Query, DiffViewer y SSE feed fueron establecidos en C18. C19 agrega 5 páginas nuevas y corrige un mismatch de shape en un componente existente.

## Goals / Non-Goals

**Goals:**
- Página Rules con CRUD completo consumiendo GET/POST/PUT/DELETE /rules
- Página Agents con ciclo draining awareness y gate RN-70 para rescan
- Página Dashboard con contadores agregados (eventos por estado, agentes, pending crítico/alto)
- Página Alerts con historial y filtros; FailedAlerts con retry/descarte
- Fix de `SystemBanner.tsx` para consumir la forma real del backend

**Non-Goals:**
- No hay endpoints backend nuevos (consumo puro de contratos existentes)
- No hay push en tiempo real en Rules/Agents/Dashboard (polling es suficiente)
- No hay role expansion ni multi-tenant

## Decisions

### D1: Fix de SystemBanner — reconciliación de health shape
El backend (`GET /health/components`) retorna un objeto plano `{"postgres":"ok","valkey":"ok","n8n":"ok","agents":"ok"}`. `SystemBanner.tsx` (líneas 4-11, 22) declara `interface HealthResponse { components: HealthComponent[] }` y lee `data?.components.filter(...)` — siempre `undefined`, el banner nunca dispara. Fix: reemplazar la interface para mapear el objeto plano; la lógica "any component down" se adapta iterando `Object.values()`.

**Alternativa descartada**: wrapper en el backend que normalice la respuesta — rechazado, el backend ya es correcto y nosotros somos dueños del frontend.

### D2: Gate RN-70 para rescan — flujo two-step mutation
`POST /agents/{id}/rescan?force=false` retorna 409 `{"code":"pending_events_exist","count":N}` cuando hay pending. El componente `RescanConfirmModal.tsx` captura el 409, extrae `count` del body, y ofrece "Cancelar" o "Forzar rescan" (que llama nuevamente con `force=true`). Ambas calls son mutaciones TanStack Query separadas; la primera es no-destructiva si retorna 409.

**Alternativa descartada**: siempre `force=true` — rechazado, RN-70 requiere confirmación explícita.

### D3: Draining deshabilita acciones (RN-92)
`AgentCard.tsx` recibe el status como prop. Cuando `status === "draining"`, todos los botones de acción (config, rescan) se deshabilitan con tooltip descriptivo. No se necesita enforcement adicional en el frontend — el backend ya rechaza operaciones sobre agentes draining.

### D4: TanStack Query key strategy (extensión del patrón C18)
```
['rules']                          → lista de reglas
['agents']                         → lista de agentes
['agents', id]                     → detalle de un agente
['alerts', { status, severity, page }] → lista paginada de alertas
['alerts', 'failed']               → alertas fallidas
['dashboard']                      → contadores (refetchInterval: 30000)
```

### D5: Alerts sin store global
Alerts y FailedAlerts usan estado local TanStack Query, no Zustand — no hay estado de alertas cross-page que gestionar. El SSE feed de alertas live ya está manejado por el hook de C18.

### D6: RuleForm — validación client-side de glob
El form valida que el pattern no esté vacío antes de enviar al backend. No se implementa validación de sintaxis glob completa en el cliente (complejidad innecesaria). El backend retorna 422 si el pattern es inválido; se muestra como error de campo.

## Risks / Trade-offs

- **[Risk] Health shape mismatch en producción** → Mitigation: fix localizado en `SystemBanner.tsx` types y parsing; sin cambio de backend.
- **[Risk] Rescan 409 → confusión si el modal no muestra el count** → Mitigation: el body del 409 incluye `count`; siempre se extrae y muestra en el modal.
- **[Risk] Dashboard con datos stale** → Mitigation: `refetchInterval: 30000` en TanStack Query para todos los queries del dashboard.
