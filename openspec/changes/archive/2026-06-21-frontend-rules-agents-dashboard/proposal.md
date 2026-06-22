## Why

C19 completa la interfaz operativa del FIM Platform con las páginas faltantes de M4: gestión de reglas, agentes, dashboard de estado y alertas. Sin estas vistas, el operador no puede crear reglas de detección, gestionar agentes ni monitorear el estado general del sistema desde la UI.

## What Changes

- Nueva página `Rules.tsx`: listado y CRUD de reglas de monitoreo (pattern glob con `!`, severity, action), eliminar con confirmación; sincronización visible tras save
- Nueva página `Agents.tsx`: estado operacional de agentes (online/offline/draining/dead), indicador `queue_pressure`, lista editable de paths, botón re-scan con confirmación de pendientes a supersede; `AgentCard.tsx` con `draining` visible y botones deshabilitados en ese estado
- Nueva página `Dashboard.tsx`: contadores de estado de eventos, agentes registrados, pending crítico/alto
- Nueva página `Alerts.tsx`: historial de alertas desde tabla unificada `alerts` (D6) con filtros por estado (pending/delivered/failed) y severidad
- Nueva página `FailedAlerts.tsx`: vista filtrada de alertas fallidas; reintento individual/bulk vía `POST /alerts/{id}/retry`; descarte vía `DELETE /alerts/{id}`
- Fix de `SystemBanner.tsx`: la implementación actual espera `{components: HealthComponent[]}` pero `GET /health/components` retorna un objeto plano `{postgres, valkey, n8n, agents}`; se reconcilia tipo y parsing en este change

## Capabilities

### New Capabilities

- `frontend-rules`: CRUD de reglas de monitoreo FIM via `/rules` API; RuleSeverity {critical,high,medium,low}, RuleAction {auto_restore,quarantine,manual_review,alert_only}
- `frontend-agents`: gestión operacional de agentes FIM via `/agents` API; incluyendo config de watch_paths (replace-all), re-scan con gate RN-70 (409 `pending_events_exist`) y soporte completo del ciclo `draining`
- `frontend-dashboard`: dashboard de estado general; contadores de eventos por estado, agentes registrados, pending crítico/alto
- `frontend-alerts`: listado histórico y gestión de alertas fallidas via `/alerts` API; retry y descarte bulk

### Modified Capabilities

_(ninguna — consumo puro de contratos backend ya definidos en C12, C13, C14, C15, C16)_

## Impact

- `frontend/src/pages/`: Rules.tsx, Agents.tsx, Dashboard.tsx, Alerts.tsx, FailedAlerts.tsx (nuevos)
- `frontend/src/components/ui/`: AgentCard.tsx, RuleForm.tsx, RescanConfirmModal.tsx (nuevos)
- `frontend/src/components/layout/SystemBanner.tsx`: fix de shape mismatch contra backend real
- `frontend/src/api/`: rules.ts, agents.ts (ampliados o nuevos)
- `frontend/src/hooks/`: useRules, useAgents, useAlerts (nuevos)
- `frontend/src/stores/`: dashboardStore si aplica
- Reglas cubiertas: RN-70, RN-87, RN-92, RN-93, RN-101, RN-102, RN-103
