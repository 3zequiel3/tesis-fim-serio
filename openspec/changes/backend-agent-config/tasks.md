## 1. Backend — Modelo Agent: agregar watch_paths

- [x] 1.1 Agregar campo `watch_paths: list[str] = Field(default=[], sa_column=Column(JSON))` al modelo `Agent` en `backend/app/modules/agents/models.py`
- [x] 1.2 Verificar que `SQLModel.metadata.create_all()` crea la columna `watch_paths` (o agregar migración manual si el volumen ya existe)

## 2. Backend — Schemas de gestión de agentes

- [x] 2.1 Crear `AgentResponse` en `models.py` con todos los campos de consulta: `agent_id`, `status`, `last_heartbeat`, `queue_pressure`, `ruleset_version_applied`, `watch_paths`
- [x] 2.2 Crear `AgentListResponse` con `items: list[AgentResponse]` y `total: int`
- [x] 2.3 Crear `AgentConfigRequest` con `watch_paths: list[str]`
- [x] 2.4 Crear `AgentRescanRequest` con `force: bool = False`

## 3. Backend — Publicación de comandos HMAC-signed (agents/streams.py)

- [x] 3.1 Crear `backend/app/modules/agents/streams.py` con `publish_update_config(session, agent, new_paths, ruleset_version)`: payload con `type="update_config"`, `command_id`, `target_agent_id`, `watch_paths`, `ruleset_version`, `issued_at`, `signature` HMAC-SHA256
- [x] 3.2 Agregar `publish_rescan_baseline(session, agent)` en el mismo archivo: payload con `type="rescan_baseline"`, `command_id`, `target_agent_id`, `issued_at`, `signature`
- [x] 3.3 Obtener `shared_secret` del agente desde `agents.shared_secret_hex` (mismo patrón que `modules/actions/streams.py` de C13)
- [x] 3.4 Incrementar counter `ruleset_version` de Valkey antes de publicar `update_config` (mismo counter que C12/C13)

## 4. Backend — Servicio de gestión de agentes

- [x] 4.1 Implementar `list_agents(db)` en `backend/app/modules/agents/service.py` que retorna todos los agentes con sus campos
- [x] 4.2 Implementar `get_agent(db, agent_id)` que retorna el agente o raise 404
- [x] 4.3 Implementar `update_agent_config(db, agent_id, watch_paths, user_id)`: upsert `watch_paths`, incrementar `ruleset_version`, publicar `update_config`, registrar `audit_log` con `action="agent_config"`
- [x] 4.4 Implementar `rescan_agent(db, agent_id, force, user_id)`: si no `force` y hay pending → raise `PendingEventsExist(count=N)` (HTTP 409); si `force` → marcar pending del agente como `superseded`; publicar `rescan_baseline`; registrar `audit_log` con `action="agent_rescan"`

## 5. Backend — Router: nuevos endpoints

- [x] 5.1 Agregar `GET /agents` a `backend/app/modules/agents/router.py` — retorna `AgentListResponse`, requiere JWT admin
- [x] 5.2 Agregar `GET /agents/{agent_id}` — retorna `AgentResponse`, 404 si no existe, requiere JWT admin
- [x] 5.3 Agregar `POST /agents/{agent_id}/config` — acepta `AgentConfigRequest`, mapear `PendingEventsExist` → 409, requiere JWT admin
- [x] 5.4 Agregar `POST /agents/{agent_id}/rescan` — acepta `AgentRescanRequest`, mapear `PendingEventsExist` → 409 con `count`, requiere JWT admin

## 6. Backend — Transición dead en heartbeat consumer

- [x] 6.1 Agregar constante `_DEAD_THRESHOLD_S = 300.0` (5 minutos) en `backend/app/modules/agents/heartbeat_consumer.py`
- [x] 6.2 Extender `_sweep_offline()` con segunda pasada: `WHERE status='offline' AND last_heartbeat < now - 5min` → `status='dead'`
- [x] 6.3 Asegurar que `_handle_heartbeat` transiciona `dead → online` cuando llega un heartbeat (el agente puede volver a la vida)

## 7. Agente — BaselineEngine: exponer run_scan(paths)

- [x] 7.1 Implementar `BaselineEngine.run_scan(paths: list[str])` en `agent/baseline.py`: recorre cada path, escanea archivos regulares recursivamente, llama `update_from_command` (C13) para cada archivo encontrado con `baseline_status="present"`
- [x] 7.2 Si el path no existe, emitir log warning y continuar (no lanzar excepción)

## 8. Agente — FanotifyDetector: exponer reload_watch_paths

- [x] 8.1 Implementar `FanotifyDetector.reload_watch_paths(new_paths: list[str])` en `agent/detector.py`
- [x] 8.2 Desmarcar de fanotify los paths que están en `self.watch_paths` pero no en `new_paths`
- [x] 8.3 Marcar en fanotify los paths que están en `new_paths` pero no en `self.watch_paths` (paths nuevos)
- [x] 8.4 Actualizar `self.watch_paths = new_paths`
- [x] 8.5 Asegurar thread-safety: usar un lock asyncio o ejecutar en el event loop del detector

## 9. Agente — Handler update_config en commands.py

- [x] 9.1 Implementar `handle_update_config(command, detector, baseline_engine, state)` en `agent/commands.py`
- [x] 9.2 Determinar `added_paths = set(new_paths) - set(current_watch_paths)` y `removed_paths = set(current_watch_paths) - set(new_paths)`
- [x] 9.3 Llamar `detector.reload_watch_paths(new_paths)`
- [x] 9.4 Llamar `baseline_engine.run_scan(list(added_paths))` solo para paths nuevos
- [x] 9.5 Actualizar `config.yaml` local del agente con los nuevos `watch_paths`
- [x] 9.6 Actualizar `state.ruleset_version = command["ruleset_version"]` y persistir en `state.json`
- [x] 9.7 Publicar `event_ack` con `status="ok"` o `status="error"`
- [x] 9.8 Registrar el handler en el `dispatch` de `agent/commands.py`

## 10. Agente — Handler rescan_baseline en commands.py

- [x] 10.1 Implementar `handle_rescan_baseline(command, baseline_engine, state)` en `agent/commands.py`
- [x] 10.2 Obtener `watch_paths` actuales desde `config.yaml` del agente
- [x] 10.3 Llamar `baseline_engine.run_scan(watch_paths)` para scan completo
- [x] 10.4 Publicar `event_ack` con `status="ok"` o `status="error"`
- [x] 10.5 Registrar el handler en el `dispatch` de `agent/commands.py`

## 11. Agente — Integración en publisher.py

- [x] 11.1 Asegurar que `publisher.py` pasa `detector` y `baseline_engine` al `dispatch` para los nuevos handlers de `update_config` y `rescan_baseline`

## 12. Tests backend

- [x] 12.1 `test_get_agents_list` — retorna lista con todos los agentes y sus campos
- [x] 12.2 `test_get_agent_detail` — retorna detalle con watch_paths
- [x] 12.3 `test_get_agent_not_found` → 404
- [x] 12.4 `test_agent_config_updates_watch_paths` — watch_paths persiste en DB y comando update_config publicado
- [x] 12.5 `test_agent_config_hmac_valid` — payload tiene firma HMAC verificable
- [x] 12.6 `test_agent_config_not_found` → 404
- [x] 12.7 `test_rescan_no_pending_succeeds` — sin pending → rescan_baseline publicado
- [x] 12.8 `test_rescan_with_pending_no_force` → 409 con count
- [x] 12.9 `test_rescan_with_pending_force` — pending superseded + rescan_baseline publicado
- [x] 12.10 `test_dead_transition` — agente offline > 5min → status=dead en sweep
- [x] 12.11 `test_dead_to_online_on_heartbeat` — agente dead vuelve a online al recibir heartbeat
- [x] 12.12 `test_audit_log_on_config` — fila en audit_log con action="agent_config"
- [x] 12.13 `test_audit_log_on_rescan` — fila en audit_log con action="agent_rescan"

## 13. Tests agente

- [x] 13.1 `test_run_scan_creates_baseline_entries` — run_scan crea entradas cifradas para archivos en path
- [x] 13.2 `test_run_scan_skips_nonexistent_path` — path inexistente → log warning, no excepción
- [x] 13.3 `test_reload_watch_paths_marks_new` — nuevo path marcado en fanotify (mock)
- [x] 13.4 `test_reload_watch_paths_unmarks_removed` — path eliminado desmarcado (mock)
- [x] 13.5 `test_update_config_handler_reloads_detector` — handler llama reload_watch_paths y run_scan para paths nuevos
- [x] 13.6 `test_update_config_handler_publishes_ack`
- [x] 13.7 `test_update_config_updates_state_ruleset_version`
- [x] 13.8 `test_rescan_baseline_handler_calls_run_scan`
- [x] 13.9 `test_rescan_baseline_handler_publishes_ack`
- [x] 13.10 `test_dispatch_routes_update_config` — tipo correcto llama al handler correcto
- [x] 13.11 `test_dispatch_routes_rescan_baseline`
