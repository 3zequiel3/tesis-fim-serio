## Context

C08 (`valkey-streams-transport`) implementó la infraestructura de transporte: consumer group `fim-backend`, helpers HMAC-SHA256, validaciones básicas (schema_version, signature, clock skew, agent desconocido), deduplicación por `event_id`, protocolo ACK end-to-end, y consumer de heartbeat. Esa capa es infraestructura de tuberías; los eventos llegan, se validan criptográficamente y se persisten, pero no hay lógica de negocio sobre el estado resultante ni visibilidad REST.

C11 agrega la capa de negocio sobre esa infraestructura: determina cómo un evento llega al estado correcto, qué pasa cuando hay cambios concurrentes en el mismo path, protege al backend de floods por agente, y expone la historia de eventos vía REST.

## Goals / Non-Goals

**Goals:**
- Validación de transiciones contra la máquina de estados canónica (RN-72); rechazo con 409 para transiciones inválidas
- Cadena superseded: cuando un path tiene un evento `pending` y llega uno nuevo, marcar el anterior como `superseded` y vincularlo (RN-21–24); compactación automática si la cadena supera 10 eventos por path (RN-98)
- Rate limiting 100 eventos/min por `agent_id` en el consumer, con rechazo registrado en `rejected_events_audit` (RN-88, D7)
- Retención 30 días para eventos terminales no referenciados en `audit_log` (RN-98)
- REST API: `GET /events` paginado con filtros y `GET /events/{id}` con timestamps dobles

**Non-Goals:**
- Endpoints approve/reject (C13)
- Notificaciones n8n (C15)
- SSE de alertas en tiempo real (C16)
- Frontend (C17–C19)
- Alta disponibilidad o réplicas (RN-76 lo prohíbe explícitamente para M1–M4)

## Decisions

### D-C11-1: Separación consumer.py / service.py

`consumer.py` maneja el protocolo Valkey (XREADGROUP, XACK, re-entrega, rate limit check). Toda la lógica de negocio (superseded chain, validación de transición, compactación) vive en `backend/app/modules/events/service.py`. Razón: `service.py` será invocado también por el HTTP handler de approve/reject (C13) para la misma máquina de estados — si la lógica viviera solo en el consumer, se duplicaría.

**Alternativa descartada**: lógica inline en consumer.py. Mezcla protocolo y negocio; imposible reutilizar en C13.

### D-C11-2: Rate limit en memoria con ventana deslizante

Single instance (RN-76) → `dict[str, deque[float]]` en memoria, clave `agent_id`, valores timestamps. Ventana de 60s. Inicializado en el módulo, protegido con `asyncio.Lock` (el consumer es async). No requiere Valkey ni Redis para esto; no hay réplicas que sincronizar.

Cuando se supera el límite, el evento recibe `XACK` (no se reintenta) y se persiste en `rejected_events_audit` con `reason = rate_limited`.

**Alternativa descartada**: contador en Valkey con INCR+EXPIRE. Más robusto para HA, pero innecesario dado RN-76 y añade overhead de red por cada evento.

### D-C11-3: Compactación inline en la misma transacción DB

Cuando el consumer crea un evento nuevo y marca el anterior como `superseded`, chequea inmediatamente cuántos eventos `superseded` existen para ese path. Si la cadena supera 10, elimina los más antiguos (por `created_at asc`) en la misma transacción de base de datos. Garantiza que la restricción `max 10 por path` (RN-98) sea siempre verdadera y no haya ventanas inconsistentes.

**Alternativa descartada**: tarea de compactación periódica separada. Introduce ventana donde la cadena puede tener >10; complica la garantía RN-98.

### D-C11-4: Retención vía tarea asyncio periódica

Background task lanzada en lifespan de FastAPI, se ejecuta cada hora. Elimina eventos con estado terminal (`approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`) cuyo `created_at < now() - 30 days`, excluyendo los que tengan su `id` referenciado en `audit_log.target_id`. Consistente con el patrón del heartbeat sweeper de C08.

**Alternativa descartada**: trigger PostgreSQL. Añade lógica en la DB; más difícil de testear y de mantener.

### D-C11-5: `InvalidTransitionError` en service.py mapeado a log + XACK en consumer

`service.py` define `VALID_TRANSITIONS: dict[EventStatus, set[EventStatus]]` (RN-72). Si la transición es inválida, lanza `InvalidTransitionError(from_status, to_status)`. El consumer la captura, hace `XACK` (no se reintenta indefinidamente), y loguea el intento. El HTTP handler de C13 la capturará y retornará 409.

### D-C11-6: GET /events excluye superseded por defecto, ?include_superseded para habilitarlos

El parámetro query `include_superseded: bool = False` controla la exclusión (RN-98). Los filtros soportados: `status` (multi-value), `path_prefix`, `date_from`, `date_to`, `page` (1-based), `page_size` (default 50, max 200). La respuesta incluye `total`, `page`, `page_size`, `items`.

## Risks / Trade-offs

- **Rate limit no persiste entre reinicios** → al reiniciar el backend, el contador se resetea. Riesgo de burst corto post-reinicio. Aceptable: RN-76 (single instance, reinicios son infrecuentes) y el burst se registra igual.
- **Compactación borra datos de auditoría** → solo se compactan `superseded`, que por RN-11 son terminales e inmutables. Los referenciados en `audit_log` están protegidos por la cláusula de retención. Sin embargo, la compactación de la cadena no verifica referencias en `audit_log` — si un superseded fue referenciado, se podría borrar. **Mitigación**: la compactación aplica la misma cláusula que retención: excluye `id in (SELECT target_id FROM audit_log WHERE target_type = 'event')`.
- **Optimistic locking en superseded chain** → cuando el consumer marca un evento como `superseded`, usa `UPDATE events SET status='superseded', version=version+1 WHERE id=? AND version=? AND status='pending'`. Si hay carrera (improbable en single instance), la UPDATE afecta 0 filas → consumer registra warning y continúa sin crear el nuevo evento (para evitar cadena inconsistente).
