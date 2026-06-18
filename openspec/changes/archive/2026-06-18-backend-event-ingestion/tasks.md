## 1. Domain model — RejectionReason

- [x] 1.1 Agregar `rate_limited` al enum `RejectionReason` en `backend/app/modules/events/models.py`
- [x] 1.2 Verificar que `create_all()` sigue siendo idempotente con el nuevo valor del enum (SQLModel usa VARCHAR, no necesita ALTER TYPE)

## 2. Event service — máquina de estados

- [x] 2.1 Crear `backend/app/modules/events/service.py` con `InvalidTransitionError` (excepción de dominio con `from_status` y `to_status`)
- [x] 2.2 Definir `VALID_TRANSITIONS: dict[EventStatus, set[EventStatus]]` con la tabla canónica RN-72 (`pending → {approved, rejected, superseded}`; terminales con set vacío)
- [x] 2.3 Implementar `validate_transition(from_status, to_status)` que lanza `InvalidTransitionError` si la transición no está en `VALID_TRANSITIONS`
- [x] 2.4 Implementar `get_pending_event_for_path(session, path) -> Event | None` que retorna el evento `pending` más reciente para un path dado

## 3. Event service — superseded chain y compactación

- [x] 3.1 Implementar `mark_superseded(session, event_id, version) -> bool` con `UPDATE events SET status='superseded', version=version+1 WHERE id=? AND version=? AND status='pending'`; retorna `True` si afectó 1 fila, `False` si carrera (0 filas)
- [x] 3.2 Implementar `compact_chain(session, path)`: cuenta `superseded` para el path; si >10, elimina los más antiguos (por `created_at asc`) excluyendo los referenciados en `audit_log.target_id` con `target_type='event'`, hasta dejar exactamente 10
- [x] 3.3 Implementar `ingest_event(session, event_data) -> Event` que orquesta: (1) buscar pending para el path, (2) si existe → `mark_superseded` → si carrera → retornar `None`, (3) crear nuevo `Event` con `parent_event_id` si hubo superseded, (4) llamar `compact_chain` en la misma transacción

## 4. Event consumer — rate limiting

- [x] 4.1 Implementar `RateLimiter` en `backend/app/modules/events/consumer.py`: `dict[str, deque[float]]` con `asyncio.Lock`, ventana deslizante 60s, límite 100/min por `agent_id`
- [x] 4.2 Exponer `reset_rate_limiter()` en el módulo para facilitar tests
- [x] 4.3 Integrar el rate check en el consumer loop: antes de procesar el evento, llamar `rate_limiter.check(agent_id)`. Si excede → `XACK` + insertar `RejectedEventAudit(reason=rate_limited)` + continuar al siguiente mensaje

## 5. Event consumer — integración con service

- [x] 5.1 Extender el consumer loop en `backend/app/modules/events/consumer.py` para llamar `service.ingest_event()` en lugar de persistir inline: reemplaza la inserción directa con la función de service que incluye la superseded chain
- [x] 5.2 Capturar `InvalidTransitionError` en el consumer: hacer `XACK`, loguear warning con `from_status` y `to_status`, y continuar sin persistir

## 6. Retención

- [x] 6.1 Implementar `retention_task(session_factory)` async en `backend/app/modules/events/service.py`: elimina eventos terminales con `created_at < now() - 30 days` cuyo `id` no aparece en `audit_log.target_id` con `target_type='event'`
- [x] 6.2 Registrar `retention_task` en lifespan de `backend/app/main.py`: loop async que ejecuta cada 3600 segundos

## 7. REST API — eventos

- [x] 7.1 Crear `backend/app/modules/events/router.py` con `GET /events`: parámetros `status` (multi-value), `path_prefix`, `date_from`, `date_to`, `include_superseded` (bool, default `false`), `page` (default `1`), `page_size` (default `50`, max `200`); respuesta `{"total", "page", "page_size", "items"}`
- [x] 7.2 Agregar `GET /events/{id}` al router: retorna el evento completo o `404 Not Found`; incluye todos los campos del modelo `Event`
- [x] 7.3 Ambos endpoints requieren autenticación JWT (mismo dependency de C04)
- [x] 7.4 Registrar el router en `backend/app/main.py` con `prefix="/events"` y `tags=["events"]`

## 8. Tests

- [x] 8.1 Tests `validate_transition`: transición válida no lanza, transición desde terminal lanza, `pending → alert_only` lanza
- [x] 8.2 Tests `ingest_event`: path sin pending (no cadena), path con pending (genera cadena), carrera en mark_superseded (retorna None)
- [x] 8.3 Tests `compact_chain`: cadena <10 no borra nada, cadena llega a 11 borra el más antiguo, respeta referencias en audit_log
- [x] 8.4 Tests `RateLimiter`: bajo límite pasa, sobre límite rechaza, ventana deslizante expira, `reset_rate_limiter` limpia estado
- [x] 8.5 Tests consumer — rate limit: evento 101 genera `RejectedEventAudit(reason=rate_limited)` y hace XACK
- [x] 8.6 Tests consumer — InvalidTransitionError: consumer hace XACK y no persiste si `validate_transition` lanza
- [x] 8.7 Tests `retention_task`: elimina terminal >30 días sin referencia, preserva referenciado en audit_log, preserva terminal <30 días
- [x] 8.8 Tests `GET /events`: default excluye superseded, `include_superseded=true` los incluye, filtro por status, filtro por path_prefix, paginación correcta, sin auth → 401
- [x] 8.9 Tests `GET /events/{id}`: retorna evento existente con todos los campos, retorna 404 si no existe, evento superseded accesible por ID
