## Why

El backend no tiene forma de consultar el estado operacional de los agentes ni de actualizar su configuración de paths o forzar un re-scan; estas acciones son centrales para el ciclo de operación del M3. Este change agrega los endpoints de gestión de agentes (consulta + configuración + re-scan) y los handlers del agente para los comandos `update_config` y `rescan_baseline` que el backend publica como consecuencia.

## What Changes

- `GET /agents` — lista todos los agentes con `status`, `last_heartbeat`, `queue_pressure`, `ruleset_version_applied`.
- `GET /agents/{id}` — detalle de un agente incluyendo `watch_paths` configurados.
- `POST /agents/{id}/config` — persiste `watch_paths` en PostgreSQL y publica `update_config` firmado HMAC + `ruleset_version++` al agente; éste recarga fanotify en caliente y escanea baseline para paths nuevos.
- `POST /agents/{id}/rescan` — si hay eventos `pending` del agente requiere confirmación; marca pending como `superseded`; publica `rescan_baseline` firmado HMAC al agente.
- Transición de estado `dead` para agentes sin heartbeat por más de 5 minutos (completando el ciclo online/offline/draining/dead).
- Agente: handler para `update_config` — recarga `watch_paths` en fanotify y lanza baseline scan para paths nuevos.
- Agente: handler para `rescan_baseline` — lanza scan completo de baseline, confirma via `event_ack`.
- `audit_log` en config y rescan.

Reglas cubiertas: RN-18, RN-55, RN-57, RN-68, RN-69, RN-70, RN-75, RN-92, RN-94.

## Capabilities

### New Capabilities

- `backend-agent-management`: Endpoints REST de gestión de agentes — GET /agents (lista), GET /agents/{id} (detalle), POST /agents/{id}/config (actualizar paths + publicar update_config HMAC-signed), POST /agents/{id}/rescan (forzar re-scan con gestión de pending), transición `dead` a los 5 minutos sin heartbeat.
- `agent-config-commands`: Handlers del agente para los comandos de configuración entrantes — `update_config` (recarga de watch_paths en fanotify + baseline scan de paths nuevos) y `rescan_baseline` (scan completo + event_ack), integrados en el dispatch de `agent/commands.py` (C13).

### Modified Capabilities

- `backend-agents`: Los endpoints GET /agents y GET /agents/{id} son nuevos verbos sobre el mismo recurso `/agents` que ya tiene POST /register y POST /bootstrap; se agrega como ADDED requirement para que el spec refleje la capacidad completa del recurso.

## Impact

- **Backend**: nuevo módulo `backend/app/modules/agents_mgmt/` (o extensión del módulo `agents` existente) con router.py, service.py, schemas.py para los 4 nuevos endpoints; modificaciones a `core/streams.py` para publicar `update_config` y `rescan_baseline`; job de transición `dead` (puede ser tarea en el lifespan o consumer heartbeat ya existente).
- **Agente**: `agent/commands.py` recibe 2 nuevos handlers; `agent/detector.py` expone una función pública `reload_watch_paths(new_paths)` para que el handler la llame; `agent/baseline.py` expone `run_scan(paths)` para el re-scan.
- **DB**: tabla `agents` ya tiene todos los campos necesarios (status, last_heartbeat, watch_paths como JSON o tabla separada — ver domain-models C03); `audit_log` recibe nuevas entradas.
- **Valkey Streams**: nuevos tipos de comando en stream `commands` — `update_config` y `rescan_baseline`.
