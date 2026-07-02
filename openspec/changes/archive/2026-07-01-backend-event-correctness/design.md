## Context

La auditoría del 2026-06-26 identificó nueve bugs en la capa backend del FIM Platform. Todos afectan módulos ya implementados en changes anteriores (C11–C15). No hay features nuevas: esta change es exclusivamente de remediación.

**Estado actual de los archivos involucrados:**
- `backend/app/modules/alerts/service.py` — `_try_cascade` siempre retorna `(True, AlertChannel.log_only)` como último recurso; el retry loop nunca ve `False` → las alertas con canales configurados que fallan nunca entran a la DLQ.
- `backend/app/modules/actions/service.py` — `publish_baseline_update` se llama en el paso 5 de `_approve_single` (post-flush, pre-commit); `publish_restore_file`/`publish_quarantine_file` se llaman en el paso 2 de `_reject_single` (también pre-commit). El agente puede recibir el comando antes de que la transacción sea durable.
- `backend/app/modules/events/service.py` — `ingest_event` retorna `None` inmediatamente cuando `mark_superseded` falla (carrera), sin re-consultar si el pending todavía existe. `compact_chain` usa `.order_by(created_at.desc())`, iterando de más nuevo a más viejo y borrando los más recientes. `retention_task` usa `datetime.utcnow()`.
- `backend/app/modules/events/router.py` — `list_events` carga todas las filas en memoria (`session.exec(q).all()`) y pagina en Python.
- `backend/app/modules/events/consumer.py` — el check de rate limit (paso 5) ocurre antes del dedup (paso 6); `event_id` vacío/ausente no es rechazado explícitamente; `detected_at` no es validado como UTC-aware antes del cálculo de clock skew.
- `backend/app/modules/rules/service.py` — `datetime.utcnow()` en `_increment_ruleset_version` y `update_rule`.

**Reglas de negocio activas:** RN-54 (log_only como piso), RN-56 (consumer group), RN-71 (léxico), RN-73 (dedup), RN-88 (rate limit), RN-90 (clock skew), RN-91 (schema_version), RN-98 (retención), RN-105 (audit de rechazos), RN-120 (D23), RN-121 (D25).

## Goals / Non-Goals

**Goals:**
- Corregir los 9 bugs de forma aislada, sin alterar la API HTTP ni los contratos de Valkey Streams.
- Dejar tests de regresión para cada fix usando el harness C33 (PostgreSQL real, TRUNCATE + RESTART IDENTITY CASCADE).
- Cerrar la ventana de inconsistencia en `_approve_single`/`_reject_single` (Valkey post-commit).
- Activar correctamente la DLQ de alertas cuando los canales primarios configurados fallan.
- Eliminar el full table scan en `list_events`.

**Non-Goals:**
- No introducir nuevos endpoints ni modelos de datos.
- No modificar migraciones SQL (ningún fix requiere cambio de schema).
- No tocar el frontend ni el agente FIM.
- No cambiar el comportamiento del consumer group o el sistema de retry de Valkey Streams.

## Decisions

### FIX-01 — Semántica de `_try_cascade` (D23 / RN-120)

**Problema**: `_try_cascade` siempre llama a `log_only` como último paso y retorna `(True, AlertChannel.log_only)`. El retry loop de `notify_event` ve `success=True` y termina, sin registrar que los canales configurados fallaron. La alerta nunca entra a la DLQ.

**Decisión**: `_try_cascade` distingue dos escenarios:
1. Al menos un canal configurado (n8n, SMTP, webhook) tiene éxito → retorna `(True, canal)`. Sin cambio.
2. Todos los canales configurados fallan → llama `log_only` como piso (RN-54) y retorna `(False, None)`.
3. Si NO hay ningún canal configurado → `log_only` es el canal intencional → retorna `(True, AlertChannel.log_only)`.

Con esto, el retry loop de `notify_event` activa sus 3 reintentos adicionales (RETRY_DELAYS = [5, 30, 120]s) y, tras agotarlos, setea `failed_at` en la fila `alerts`. Eso es la DLQ: `failed_at NOT NULL AND delivered_at IS NULL`.

**Log_only en cada retry**: cada intento llama `_try_cascade`, que siempre ejecuta `log_only`. Esto es correcto — RN-54 garantiza el piso en cada intento.

**Alternativa descartada**: hacer que `log_only` sea solo el piso del ÚLTIMO intento. Rechazada por complejidad sin beneficio claro.

**Archivo**: `backend/app/modules/alerts/service.py`, función `_try_cascade`.

---

### FIX-02 — Publicación Valkey post-commit en `_approve_single` y `_reject_single`

**Problema**: el agente puede recibir `baseline_update`, `restore_file`, o `quarantine_file` antes de que la transacción de Postgres sea durable. Si el backend crashea entre la publicación y el commit, el agente actúa sobre un estado que nunca se persistió.

**Decisión**: Mover las tres llamadas de publicación Valkey a DESPUÉS de `db.commit()`. El orden correcto en `_approve_single`:
1. Verificar hash_detected / confirm_absent
2. UPDATE optimista
3. flush + refresh
4. `_increment_ruleset_version`
5. `_upsert_baseline_entry`
6. `_write_audit`
7. `db.commit()`
8. `db.refresh(event)`
9. `publish_baseline_update(...)` ← POST-COMMIT

En `_reject_single`:
1. UPDATE optimista
2. flush + refresh
3. Consultar baseline_entry
4. `_write_audit`
5. `db.commit()`
6. `db.refresh(event)`
7. `publish_restore_file(...)` o `publish_quarantine_file(...)` ← POST-COMMIT

**Trade-off**: si el backend crashea entre commit y publish, el agente no recibe el comando. En ese caso, la fila de la DB tiene el estado correcto (approved/rejected) pero el agente no lo sabe. Este gap es aceptado — el operador puede re-triggerear manualmente o se detecta en la próxima sincronización de baseline. El riesgo inverso (agente actúa sin commit) es más grave.

**Archivo**: `backend/app/modules/actions/service.py`, funciones `_approve_single` y `_reject_single`.

---

### FIX-03 — Re-consulta de pending cuando `mark_superseded` falla (D25 / RN-121)

**Problema**: `ingest_event` retorna `None` inmediatamente cuando `mark_superseded` falla (0 filas afectadas). Pero el fallo puede deberse a que el evento pending fue approved/rejected concurrentemente (no hay más pending) — en ese caso, el nuevo evento debería insertarse como pending independiente.

**Decisión** (D25): cuando `mark_superseded` retorna `False`:
1. Re-consultar con `get_pending_event_for_path(session, path)`.
2. Si sigue habiendo pending → skip legítimo, retornar `None`.
3. Si no hay pending → insertar el nuevo evento como pending independiente (sin `parent_event_id`).

La re-consulta ocurre dentro de la misma transacción abierta, usando el mismo `Session`. El nuevo evento se inserta y se hace commit normalmente.

**Archivo**: `backend/app/modules/events/service.py`, función `ingest_event`.

---

### FIX-04 — Paginación SQL real en `list_events`

**Problema**: `session.exec(q).all()` carga todas las filas en memoria. Con tablas grandes, esto es O(N) en memoria y tiempo.

**Decisión**: aplicar la misma estrategia que `list_alerts` ya usa: COUNT sobre subquery + `LIMIT/OFFSET/ORDER BY` en la query de items.

```python
from sqlalchemy import func
count_q = select(func.count()).select_from(q.subquery())
total = session.exec(count_q).one()
items_q = q.order_by(Event.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
items = list(session.exec(items_q).all())
```

`ORDER BY created_at DESC` es consistente con el orden que se usaba implícitamente en la query (el más reciente primero, que es lo que el frontend muestra).

**Archivo**: `backend/app/modules/events/router.py`, función `list_events`.

---

### FIX-05 — `compact_chain` de `.desc()` a `.asc()`

**Problema**: con `.order_by(created_at.desc())`, la lista `superseded` tiene los más nuevos primero. La iteración borra los primeros `excess` elementos → borra los MÁS NUEVOS. Esto es incorrecto para compactación: se deben retener los eventos más recientes (representan el historial más actual) y descartar los más antiguos.

**Decisión**: cambiar a `.order_by(Event.created_at.asc())`. Con esto, los más viejos vienen primero y se borran primero; los más recientes se retienen. Se mantiene `_MAX_CHAIN = 10` como límite.

**Archivo**: `backend/app/modules/events/service.py`, función `compact_chain`, línea 100.

---

### FIX-06 — Rate limit movido después del dedup

**Problema**: el orden actual es: (5) rate limit → (6) dedup. Una re-entrega legítima de un evento ya procesado consume presupuesto de rate limit del agente.

**Decisión**: invertir el orden: (5) dedup → (6) rate limit. Si la re-entrega es detectada en dedup, se retorna sin consumir rate budget. El orden completo queda:
1. schema_version
2. agent_id
3. HMAC
4. clock skew
5. **dedup** (event_id ya existe → XACK + event_ack, sin consumir rate)
6. **rate limit** (solo para eventos genuinamente nuevos)

**Archivo**: `backend/app/modules/events/consumer.py`, función `_handle_message`.

---

### FIX-07 — Validación explícita de `event_id` no-vacío

**Problema**: si `event_id` es `""` o `None`, la rama del dedup queda en `event_exists = False` (por la guardia `if event_id else False`), y el evento sigue al camino feliz con un `event_id` inválido. Esto inserta una fila con `event_id = ""`, que viola la unicidad del identificador.

**Decisión**: agregar validación explícita de `event_id` no-vacío inmediatamente después de extraer el valor del payload, antes del dedup. Si ausente/vacío → rechazar con `RejectionReason.invalid_schema` (consistente con el rechazo de schema_version).

Ubicación: después del check de clock skew y antes del dedup (en el nuevo orden post-FIX-06).

**Archivo**: `backend/app/modules/events/consumer.py`, función `_handle_message`.

---

### FIX-08 — Normalización UTC-aware de `detected_at`

**Problema**: `_parse_datetime` puede retornar un `datetime` naive (sin tzinfo) si el valor parseado no tiene info de zona. Restar un datetime naive de `received_at` (UTC-aware) lanza `TypeError`. Además, si `detected_at` no es parseable, el rechazo con `clock_skew` no es explícito — la guardia `detected_at is None` lo atrapa pero el log no distingue "no-parseable" de "fuera de rango".

**Decisión**:
1. `_parse_datetime` siempre retorna un datetime UTC-aware o `None`. Si el valor tiene tzinfo, se usa `astimezone(timezone.utc)`. Si es naive, se asume UTC y se agrega `tzinfo=timezone.utc`.
2. El check de clock skew distingue dos sub-casos en el log: `clock_skew.unparseable` y `clock_skew.out_of_range`. El código de rechazo es `RejectionReason.clock_skew` en ambos.

**Archivo**: `backend/app/modules/events/consumer.py`, funciones `_handle_message` y `_parse_datetime`.

---

### FIX-09 — Reemplazo de `datetime.utcnow()` por `datetime.now(timezone.utc)`

**Problema**: `datetime.utcnow()` retorna un datetime naive (deprecated en Python 3.12+). En Python 3.13 genera `DeprecationWarning`.

**Decisión**: reemplazo mecánico en los 6 puntos de uso:
- `events/service.py:189` — `retention_task`
- `actions/service.py:72` — `_increment_ruleset_version`
- `actions/service.py:110` — `_upsert_baseline_entry` (INSERT)
- `actions/service.py:117` — `_upsert_baseline_entry` (UPDATE)
- `rules/service.py:79` — `_increment_ruleset_version`
- `rules/service.py:217` — `update_rule`

Se agrega `timezone` al import `from datetime import datetime, timezone` donde faltaba (verificar por archivo).

---

## Risks / Trade-offs

- **FIX-01 — gap post-commit en cascada**: si el backend crashea entre commit y publish_baseline_update, el agente no recibe el comando. Mitigación: este escenario es mucho menos grave que el inverso (agente actúa sin commit); es aceptado en D23.

- **FIX-02 — gap post-último-retry en notificaciones**: después de agotar los reintentos, la alerta entra a la DLQ con `failed_at`. El operador debe revisar y re-triggerear manualmente vía `POST /alerts/{id}/retry`. Mitigación: existe el endpoint; es la semántica correcta de DLQ.

- **FIX-03 — race window en re-consulta**: entre `mark_superseded` devuelve `False` y la re-consulta, otro proceso puede insertar un nuevo pending. En ese caso, la re-consulta ve un pending y retorna `None` (skip correcto). No hay riesgo de doble inserción.

- **FIX-04 — COUNT + subquery**: agregar una query extra por request. Costo mínimo comparado con el full table scan. No requiere índice adicional — `created_at` ya está indexado vía el índice de la PK y el ORDER BY de las queries existentes.

- **FIX-06 — orden dedup-before-rate-limit**: el dedup ahora hace un `run_in_executor` (query DB) antes del rate limit. Para re-entregas frecuentes de un agente malfuncionante, esto puede ser overhead. Mitigación: el dedup query es O(1) por índice en `event_id`; el overhead es negligible.
