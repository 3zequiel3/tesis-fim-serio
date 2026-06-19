## Context

C14 agrega la capa de gestión operacional de agentes. El modelo `Agent` ya existe (C06) con `status`, `last_heartbeat`, `queue_pressure`, `ruleset_version_applied` — pero no tiene `watch_paths` ni expone endpoints de consulta o configuración. El heartbeat consumer (C08) ya maneja online/offline/draining pero no `dead`. El módulo de commands del agente (C13) ya tiene el dispatch + verificación HMAC y soporta extensión con nuevos handlers.

Estado actual relevante:
- `backend/app/modules/agents/models.py` — `Agent` sin campo `watch_paths`.
- `backend/app/modules/agents/router.py` — solo POST /register y POST /bootstrap.
- `backend/app/modules/agents/heartbeat_consumer.py` — `_sweep_offline()` corre cada 10s, transiciona a `offline` a los 30s; no tiene `dead`.
- `agent/commands.py` (C13) — `dispatch()` con handlers baseline_update, restore_file, quarantine_file; fácil de extender.
- `agent/detector.py` (C09) — fanotify con recarga en caliente conceptualmente definida; necesita exponer función pública.
- `agent/baseline.py` (C07/C13) — scan inicial ya implementado; necesita función pública `run_scan(paths)`.

## Goals / Non-Goals

**Goals:**
- Agregar `watch_paths: list[str]` al modelo `Agent` (campo JSON, autoritativo en backend).
- GET /agents y GET /agents/{id} con estado operacional completo.
- POST /agents/{id}/config persiste paths y publica `update_config` HMAC-signed.
- POST /agents/{id}/rescan con gestión de pending → supersede + publica `rescan_baseline`.
- Transición `dead` a los 5 minutos sin heartbeat (extiende el sweep existente).
- Agente: handlers `update_config` (recarga fanotify + baseline scan) y `rescan_baseline` (scan completo + event_ack).

**Non-Goals:**
- Creación de nuevos agentes desde este endpoint (sigue siendo POST /register de C06).
- Configuración de parámetros distintos a `watch_paths` (timeouts, thresholds, etc.) — fuera de scope C14.
- Confirmación síncrona del agente al backend en config/rescan — fire-and-forget (D8).

## Decisions

### D-C14-01 — watch_paths como JSON array en Agent

Se agrega `watch_paths: list[str] = Field(default=[], sa_column=Column(JSON))` al modelo `Agent`. Un array JSON en la misma tabla es suficiente para single-instance (RN-76) y evita una tabla join innecesaria.

**Alternativa descartada**: tabla `agent_watch_paths` separada — más compleja para operaciones simples como replace-all que es el patrón esperado.

### D-C14-02 — POST /agents/{id}/config reemplaza el array completo

La semántica de config es replace-all, no patch incremental. El body recibe `{watch_paths: list[str]}` y sobreescribe completamente `agents.watch_paths`. Esto simplifica el cliente y evita lógica de diff en el backend.

### D-C14-03 — rescan requiere confirmación explícita si hay pending

`POST /agents/{id}/rescan` sin confirmación verifica si hay eventos `pending` del agente. Si los hay, retorna 409 con `{"code": "pending_events_exist", "count": N}`. Si el cliente envía `{"force": true}`, el backend marca todos los pending del agente como `superseded` (con `parent_event_id=null` para indicar que fue un rescan, no una cadena natural) y publica `rescan_baseline`.

**Alternativa descartada**: parámetro de query `?force=true` — body es más explícito y REST-compatible para acciones destructivas.

### D-C14-04 — dead en el sweep del heartbeat consumer

Se extiende `_sweep_offline()` para hacer una segunda pasada: agentes con `status=offline` y `last_heartbeat < now - 5min` → `status=dead`. El sweep corre cada 10s, así que el lag máximo de detección de dead es 10s + 5min = ~5min10s — aceptable.

**Alternativa descartada**: job separado con scheduler — innecesario, el sweep ya corre y puede manejar dos umbrales.

### D-C14-05 — Comandos update_config y rescan_baseline en stream commands

Misma infraestructura HMAC de C12/C13. Se agregan dos funciones publish en `modules/agents/streams.py` (nuevo archivo, análogo a `modules/actions/streams.py` de C13).

Payload `update_config`:
```json
{"type": "update_config", "command_id": "<uuid>", "target_agent_id": "...",
 "watch_paths": [...], "ruleset_version": N, "issued_at": "...", "signature": "..."}
```

Payload `rescan_baseline`:
```json
{"type": "rescan_baseline", "command_id": "<uuid>", "target_agent_id": "...",
 "issued_at": "...", "signature": "..."}
```

### D-C14-06 — Agente: reload_watch_paths expuesto en detector.py

El `FanotifyDetector` (C09) ya soporta recarga en caliente conceptualmente. C14 exige que exponga un método público `reload_watch_paths(new_paths: list[str])` que desmarca los paths antiguos, marca los nuevos, y actualiza `config.yaml` local. El handler `update_config` en `commands.py` llama este método.

### D-C14-07 — Agente: run_scan(paths) expuesto en baseline.py

El `BaselineEngine` ya tiene el scan inicial (C07) y `update_from_command` (C13). C14 requiere exponer `run_scan(paths: list[str])` para escanear un conjunto de paths bajo demanda. El handler `rescan_baseline` llama este método para el scan completo; el handler `update_config` llama `run_scan(new_paths)` solo para los paths que no tenían baseline previo.

## Risks / Trade-offs

- **watch_paths reemplazado durante operación activa** → El agente recibe `update_config` y recarga fanotify. Durante la fracción de segundo de recarga, un evento puede perderse. Aceptable para el caso de uso (configuración manual poco frecuente). `[Low risk]`
- **rescan con force=true y muchos pending** → Marca N eventos como `superseded` en una transacción. Con cientos de pending podría ser lento; aceptable para single-instance con volumen de tesis. `[Low risk]`
- **Agente dead que recibe un comando** → El comando queda en el stream Valkey indefinidamente. Cuando el agente vuelva a conectarse (si lo hace), recibirá el comando. Si el agente nunca vuelve, el stream retiene el mensaje según la política de Valkey (sin expiración por defecto). No hay limpieza automática de comandos obsoletos — riesgo aceptado (RN-104). `[Accepted risk]`

## Migration Plan

1. `Agent` model agrega `watch_paths` — `create_all()` al arrancar backend lo agrega via ALTER TABLE implícito si usa `checkfirst=True`, o requiere migración manual en producción. Para tesis con Docker Compose fresh start, basta con recrear el volumen.
2. Heartbeat consumer modifica `_sweep_offline()` — sin breaking changes en el comportamiento existente.
3. Agente: nuevos métodos en clases existentes + 2 nuevos handlers en `commands.py` — no breaking.

## Open Questions

Ninguna — todas las suposiciones cerradas en D1-D8 (Abril 2026) más las decisiones D-C14-01 a D-C14-07 de este change.
