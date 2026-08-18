## 1. Configuración del agente (base — todo lo del agente la consume)

- [ ] 1.1 En `agent/config.py`, agregar a `StorageConfig` el campo `discard_dir: str = "/var/lib/fim-agent/discarded"`, con la misma validación `_not_empty` que ya aplica a `baseline_dir`, `queue_dir` y `journal_dir`.
- [ ] 1.2 En `agent/config.py`, agregar a `PublisherConfig` los tres parámetros de D37 con sus defaults del design: `max_publish_attempts: int = 20`, `max_retry_after_s: float = 60.0`, `max_discard_files: int = 1000`. Validar que los tres sean positivos.
- [ ] 1.3 Documentar los cuatro campos nuevos en `agent/deploy/config.yaml.example` con un comentario que explique qué acota cada uno. NO cambiar los valores por defecto de nada preexistente.

## 2. Cola: sobre con metadata de intentos y directorio de descarte (`agent/queue.py`)

- [ ] 2.1 Definir el sobre `{"payload": {...}, "attempts": int, "first_attempt_at": str|None}` y un helper de lectura `_load_envelope(path) -> dict` que **detecte el formato**: si el dict cargado no tiene la clave `payload`, envolverlo con `attempts=0` y `first_attempt_at=None` (formato anterior, D-7 del design). Sin script de migración.
- [ ] 2.2 Cambiar `enqueue(payload)` para que escriba el sobre. El nombre del archivo (`{detected_at_ms:016d}_{event_id}.json`), la escritura atómica `tmp` + `os.replace` con `fsync`, el `0o600`, el presupuesto de 100 MB y el drop-oldest **no cambian**. `enqueue` sigue leyendo `event_id` y `detected_at` del payload, ahora desde adentro del sobre.
- [ ] 2.3 Agregar `iter_entries() -> list[dict]` que devuelva sobres en orden FIFO (misma clave de orden que `_json_files`). Mantener `iter_fifo()` devolviendo solo los payloads, para no romper a los callers que solo quieren el payload.
- [ ] 2.4 Agregar `bump_attempts(event_id) -> int`: incrementa `attempts`, sella `first_attempt_at` si estaba en `None`, reescribe el sobre de forma atómica y devuelve el nuevo contador. Si el archivo no existe, devolver `0` sin crear nada.
- [ ] 2.5 Agregar `discard(event_id, reason) -> bool`: mueve el sobre del evento al `discard_dir` agregándole `discard_reason` y `discarded_at`, con el mismo esquema de nombre. Crear el directorio bajo demanda con los mismos permisos que el de cola. Devolver `False` si el evento no está en cola.
- [ ] 2.6 En `discard`, aplicar el drop-oldest propio del directorio de descarte por **cantidad de archivos** (`max_discard_files`), NO por bytes. El descarte **no** entra en `_total_bytes()` ni en `queue_pressure` — verificar que ninguna de las dos funciones mire el `discard_dir`.
- [ ] 2.7 Extender `_sweep_orphaned_tmp` para que también barra `.tmp` huérfanos en el `discard_dir`.
- [ ] 2.8 Verificar que `remove(event_id)` sigue funcionando sin cambios sobre el formato de sobre (opera sobre el nombre del archivo, no sobre el contenido).

## 3. Publisher: `sent_at`, firma al publicar, respuesta tipada (`agent/publisher.py`)

- [ ] 3.1 Cambiar `_build_payload` para que **no** firme y **no** incluya `sent_at`: devuelve el payload estable (`event_id`, `detected_at`, `schema_version`, datos del cambio). Ese es el payload que va al sobre de la cola.
- [ ] 3.2 Agregar `_stamp_and_sign(payload) -> dict`: copia el payload, agrega `sent_at = datetime.now(timezone.utc).isoformat()`, calcula `signature = sign_payload(secret, ...)` y devuelve el resultado. Es el **único** punto de firma de eventos del agente.
- [ ] 3.3 Cambiar `_xadd` para que reciba el payload estable y llame a `_stamp_and_sign` justo antes de serializar. Así los tres caminos (`publish`, `_retry_loop`, `_drain_queue`) re-sellan sin duplicar lógica.
- [ ] 3.4 En `publish`, conservar el orden actual (encolar → registrar en `_pending` → `xadd`) y agregar `self._queue.bump_attempts(event_id)` en cada `xadd` efectivo. `publish` MUST seguir encolando aunque el envío no se ejecute.
- [ ] 3.5 En `_drain_queue`, consumir `iter_entries()` en vez de `iter_fifo()` para tener el contador de intentos, y sembrar `_pending` con el payload estable del sobre.
- [ ] 3.6 En `_handle_command_async`, agregar la rama `event_nack`: leer `event_id`, `reason` y `retry_after`. Si `retry_after` está presente → backpressure (tarea 4). Si está ausente → nack terminal: `self._queue.discard(event_id, reason)`, sacar de `_pending`, loguear.
- [ ] 3.7 En las ramas `event_ack` y `event_nack`, **ignorar el mensaje si el `event_id` no está en la cola local** (D-4 del design). Loguear y retornar sin tocar archivos ni estado. Vale para ambos tipos.
- [ ] 3.8 Verificar que la cadena `if/elif` de `_handle_command_async` sigue **sin rama `else` con efecto**: un `type` desconocido tiene que ser un no-op (tolerancia hacia adelante, RN-91).

## 4. Publisher: backpressure y techo de intentos

- [ ] 4.1 Agregar el estado `_paused_until: float` (reloj monotónico del loop, inicial `0.0`) y un helper `_is_paused() -> bool`.
- [ ] 4.2 Ante `event_nack` con `reason="rate_limited"`: `_paused_until = loop.time() + min(float(retry_after), config.publisher.max_retry_after_s)`. **NO** contar el intento y **NO** borrar el evento. Loguear con el valor efectivo aplicado.
- [ ] 4.3 Acotar también por abajo: un `retry_after` ausente, no numérico o negativo en un mensaje con `reason="rate_limited"` se trata como el mínimo positivo, nunca como cero ni como el techo.
- [ ] 4.4 Hacer que `publish`, `_retry_loop` y `_drain_queue` respeten `_is_paused()`: ninguno emite `XADD` mientras dure la pausa. `publish` **sí** encola — es el punto que no se puede romper.
- [ ] 4.5 En `_retry_loop`, antes de re-publicar, consultar el contador de intentos del sobre. Si `attempts >= config.publisher.max_publish_attempts` → `self._queue.discard(event_id, "max_attempts_exceeded")`, sacar de `_pending`, incrementar el contador de descartes, y NO publicar.
- [ ] 4.6 Agregar el contador acumulativo `_discarded_events: int` con propiedad de solo lectura, incrementado en cada descarte (por techo y por nack terminal), siguiendo el patrón de `FanotifyDetector.n_drops`.
- [ ] 4.7 Actualizar el docstring del módulo (`agent/publisher.py:1-14`): el flujo por evento ya no es "esperar ack o reintentar para siempre", son cuatro desenlaces con sus efectos.

## 5. Heartbeat del agente

- [ ] 5.1 En `agent/heartbeat.py`, agregar `"discarded_events": self._publisher.discarded_events` al payload, inyectando el publisher igual que ya se inyecta el detector para `n_drops`. Actualizar el docstring de `:4-5` con la clave nueva.
- [ ] 5.2 Verificar que la clave queda **dentro** del canonical JSON firmado (antes de `sign_payload`), como el resto de los campos del heartbeat.

## 6. Backend — ventana de skew sobre `sent_at` (`backend/app/modules/events/consumer.py`)

- [ ] 6.1 Reescribir el paso 4 de `_handle_message` (`:195-213`): parsear `detected_at` y mantener el rechazo `clock_skew` / `clock_skew.unparseable` si no es parseable, pero **quitarle la ventana**.
- [ ] 6.2 Agregar la evaluación de `sent_at`: si viene, MUST ser parseable (si no → `clock_skew` con log `clock_skew.unparseable_sent_at`) y cumplir `abs(received_at - sent_at) <= _CLOCK_SKEW_S` (si no → `clock_skew` con log `clock_skew.out_of_range`). Reutilizar `_parse_datetime`, que ya normaliza a UTC-aware.
- [ ] 6.3 Si `sent_at` **no** viene: evaluar la ventana sobre `detected_at`, exactamente como hoy. Ausencia = comportamiento anterior (D33/D35/D36). Loguear a nivel debug que se usó el fallback, para poder ver en producción cuántos agentes quedan sin actualizar.
- [ ] 6.4 Actualizar el comentario de `_CLOCK_SKEW_S` (`:50`) para que cite RN-90 **enmendada por D37/RN-131** y diga sobre qué campo se aplica.
- [ ] 6.5 **NO** persistir `sent_at` en la tabla `events` ni agregar columna. Verificar que `_ingest` no lo pase a `ingest_event`.
- [ ] 6.6 **NO** bumpear `SCHEMA_VERSION` en `backend/app/core/streams.py` ni en `agent/streams.py` (D-9 del design). Confirmar explícitamente que ambos siguen en el mismo valor.

## 7. Backend — respuesta tipada (`consumer.py`)

- [ ] 7.1 Agregar `_publish_event_nack(client, event_id, agent_id, shared_secret, reason, retry_after=None)`, calcado de `_publish_event_ack` (`:358-368`): `type="event_nack"`, `event_id`, `target_agent_id`, `reason`, `schema_version`, `timestamp`, y `retry_after` **solo** cuando no sea `None`. Firmar con `sign_payload` y `XADD` a `STREAM_COMMANDS`.
- [ ] 7.2 Extender `_reject` con el parámetro del secreto compartido (o resolverlo adentro) y hacer que, después del `XACK`, emita la respuesta que corresponda: nack terminal para `invalid_schema` y `clock_skew`; nack con `retry_after` para `rate_limited`; **nada** para `invalid_signature` y `unknown_agent`. La tabla de decisión vive en un solo lugar, no repartida por los call sites.
- [ ] 7.3 Para el rechazo por `schema_version` (paso 1, `:171-174`) — que ocurre antes de resolver el secreto — intentar resolver el `shared_secret` del `agent_id` declarado y emitir el nack **solo si el agente existe**; si no existe, no responder (D-4 del design).
- [ ] 7.4 Para el rechazo por `event_id` vacío (paso 5, `:216-219`), **no** emitir respuesta: no hay `event_id` al que dirigirla. Dejarlo comentado en el código como el único `invalid_schema` mudo.
- [ ] 7.5 Verificar que el descarte de agente revocado (`:183-188`) sigue sin emitir respuesta, y anotar por qué junto al `XACK`.
- [ ] 7.6 En el manejo de `InvalidTransitionError` (`:243-260`), agregar el nack terminal con `reason=invalid_schema` después del `XACK` y de escribir la auditoría.
- [ ] 7.7 En el skip por carrera de supersesión (`:274-277`), agregar `_publish_event_ack`: para el agente el evento está resuelto y sin respuesta republicaría para siempre.
- [ ] 7.8 Verificar que el camino de `SQLAlchemyError` (`:261-265`) sigue **sin `XACK` y sin respuesta**.
- [ ] 7.9 Reescribir el docstring del módulo (`:1-17`), que hoy dice "Rechazos: inserta RejectedEventAudit, XACK, sin event_ack (D4, RN-105)". Reemplazar por la matriz de D37 y citar la enmienda a D4/RN-105.

## 8. Backend — `retry_after` derivado del rate limiter (`consumer.py`)

- [ ] 8.1 Agregar a `_RateLimiter` un método `seconds_until_available(key) -> float`: `window_s - (now - timestamps[0])` si la ventana está llena, con piso en un mínimo positivo pequeño; `0.0` si hay cupo. NO exponer el `deque`.
- [ ] 8.2 Usarlo en el rechazo por rate limit (`:234-237`) para armar el `retry_after` del nack.
- [ ] 8.3 Confirmar que `reset_rate_limiter()` sigue limpiando todo el estado, incluido lo que use el método nuevo.

## 9. Backend — outbox de comandos de decisión (`actions/`)

- [ ] 9.1 En `backend/app/modules/actions/streams.py`, cambiar `_record_published_command` para que acepte el `payload` serializado y lo persista con `status="pending"` y `published_at=None`. Conservar `command_id`, `event_id` y `ack_status="pending"` intactos (D30/RN-124).
- [ ] 9.2 En `publish_baseline_update`, `publish_restore_file` y `publish_quarantine_file`: firmar y serializar igual que hoy, insertar la fila `pending`, y **eliminar** el `valkey_client.xadd(...)` y el `session.commit()` propio. Renombrar las tres a `enqueue_*` para que el nombre no mienta; actualizar los call sites.
- [ ] 9.3 Quitar el `except ValueError: log.error + return` de las tres (`:108-110`, `:163-165`, `:207-209`): la excepción de `_get_agent_secret` MUST propagarse para revertir la transacción. Un `200` con el evento terminal y sin comando emitido deja de ser posible.
- [ ] 9.4 Reescribir el docstring del módulo (`:1-25`), que documenta el `XADD` inmediato, el `session.commit()` propio y el rollback-on-XADD-failure — los tres desaparecen.
- [ ] 9.5 En `actions/service.py`, mover la llamada del publicador de después del `db.commit()` (`:212`) a **antes** (`_approve_single`, entre `_write_audit` y el commit). Mismo movimiento en `_reject_single` (`:294-296` → antes del `db.commit()` de `:279`), respetando el no-op de baseline `absent` de RN-74.
- [ ] 9.6 Agregar en ambos, después del `db.commit()`, el intento inmediato best-effort de `publish_pending_commands` — mismo patrón que `publish_rule_sync` — para no agregar la latencia del poller al camino feliz.
- [ ] 9.7 Verificar que `approve_bulk` y `reject_bulk` heredan el comportamiento por delegar en las funciones single, y que el fallo de un ítem no arrastra a los demás.
- [ ] 9.8 En `backend/app/modules/rules/models.py:51-53`, corregir el docstring de `PublishedCommand` que afirma que los demás comandos no pasan por el outbox. Es ahora exactamente al revés.

## 10. Backend — outbox de comandos de agente (`agents/`)

- [ ] 10.1 Aplicar el mismo cambio de 9.1–9.4 a `backend/app/modules/agents/streams.py` para `update_config` y `rescan_baseline`.
- [ ] 10.2 En `agents/service.py`, mover `publish_update_config` (`:179`) a antes del `db.commit()` de `:175`, y `publish_rescan_baseline` (`:235`) a antes del `db.commit()` de `:232`. Agregar en ambos el intento inmediato best-effort post-commit.
- [ ] 10.3 Confirmar que `ruleset_version_applied` sigue avanzando **solo** desde el consumer de `command_ack` (D5/RN-106, C36) y que nada de esta change lo toca.
- [ ] 10.4 Verificar que `publish_pending_commands` (`rules/service.py:188-229`) publica correctamente los cinco tipos de comando sin ningún cambio: ya es genérico y hace `XADD` del `payload` persistido. Si hiciera falta tocarlo, es señal de que 9.1 quedó mal.

## 11. Backend — `discarded_events` del heartbeat

- [ ] 11.1 Crear `backend/db/migrations/010_add_agent_discarded_events.sql` con `ALTER TABLE agents ADD COLUMN IF NOT EXISTS discarded_events INTEGER` (nullable, sin default — D3, SQL idempotente, sin Alembic).
- [ ] 11.2 Agregar el campo al modelo `Agent` en `backend/app/modules/agents/models.py` como `int | None = Field(default=None)`.
- [ ] 11.3 En `heartbeat_consumer.py`, leer la clave con el mismo criterio tolerante de `queue_pressure`: numérica → persistir; ausente → **no tocar** el valor guardado; no numérica → ignorar con log y procesar el resto del heartbeat normalmente.
- [ ] 11.4 Exponerlo en `AgentResponse` (`agents/service.py`, `_agent_to_response`) para `GET /agents` y `GET /agents/{id}`, conservando el `null` como estado distinguible de `0`.

## 12. Frontend

- [ ] 12.1 Agregar el campo al tipo del agente en `frontend/src/api/agents.ts`, como `number | null | undefined`.
- [ ] 12.2 Crear `frontend/src/utils/discardedEvents.ts` con un mapper puro de tres estados (positivo / cero / desconocido), siguiendo el patrón de `frontend/src/utils/watchPathStatus.ts` y `actionError.ts`.
- [ ] 12.3 Consumirlo desde `frontend/src/components/ui/AgentCard.tsx`, junto a la presión de cola. Un conteo positivo se presenta como anomalía; desconocido **NO** se renderiza como cero.

## 13. Tests — agente, puros y con filesystem real

- [ ] 13.1 `agent/tests/`: sobre de cola — `enqueue` escribe el sobre; `_load_envelope` envuelve un archivo de formato anterior con `attempts=0`; un directorio mixto drena completo en orden FIFO.
- [ ] 13.2 `bump_attempts` persiste el incremento y sobrevive a releer el archivo; sobre un `event_id` inexistente devuelve `0` sin crear nada.
- [ ] 13.3 `discard` mueve el sobre con motivo y timestamp, aplica el drop-oldest por cantidad, y **no** altera `queue_pressure` ni `_total_bytes`.
- [ ] 13.4 Firma al publicar: dos `xadd` del mismo `event_id` producen `sent_at` distintos y **ambas firmas verifican**; el payload en disco no tiene `signature` ni `sent_at`.
- [ ] 13.5 Rotación de secreto: encolar con un secreto, rotar, publicar, y verificar que la firma corresponde al secreto nuevo.
- [ ] 13.6 Nack terminal: el evento sale de la cola, aparece en `discard_dir` con el motivo del nack, y el contador de descartes sube.
- [ ] 13.7 Nack de rate limit: el evento **permanece** en cola, `attempts` no cambia, y ningún `XADD` ocurre mientras dura la pausa — incluyendo el de `publish` de un evento nuevo, que sí debe quedar encolado.
- [ ] 13.8 `retry_after` desmedido se acota al techo; `retry_after` ausente o negativo con `reason=rate_limited` aplica el mínimo positivo.
- [ ] 13.9 Techo de intentos: publicar hasta el límite sin respuesta produce descarte con `max_attempts_exceeded` y detiene el `XADD`. Con un reloj inyectado, sin esperas reales.
- [ ] 13.10 El contador de intentos sobrevive a un reinicio simulado (instanciar un `Publisher` nuevo sobre el mismo directorio de cola).
- [ ] 13.11 Una respuesta con `event_id` que no está en cola no borra archivos, no escribe descarte y no altera el backpressure.
- [ ] 13.12 Un mensaje verificado con `type` desconocido no produce ningún efecto.
- [ ] 13.13 El heartbeat lleva `discarded_events` y la clave queda cubierta por la firma.

## 14. Tests — backend

- [ ] 14.1 Ventana de skew: `detected_at` de hace seis horas con `sent_at` reciente **se acepta**, y el `detected_at` persistido es el original. Es el test que representa el defecto de la cola atascada.
- [ ] 14.2 `sent_at` fuera de rango, `sent_at` en el futuro y `sent_at` no parseable → `clock_skew`, cada uno con su log distintivo.
- [ ] 14.3 Sin `sent_at`: dentro de 5 min se acepta, fuera se rechaza — el comportamiento anterior íntegro.
- [ ] 14.4 `sent_at` alterado tras la firma → `invalid_signature`, y la ventana de skew ni se evalúa.
- [ ] 14.5 Matriz de respuestas completa, con un cliente Valkey falso que colecciona los `XADD`: seis motivos, y aserciones **negativas** para `invalid_signature`, `unknown_agent`, agente revocado y `event_id` vacío — que el stream `commands` quede vacío es tan importante como las positivas.
- [ ] 14.6 `invalid_schema` con agente conocido → nack firmado con el secreto de ese agente; con agente desconocido → silencio.
- [ ] 14.7 `InvalidTransitionError` → `XACK` + auditoría + nack terminal. Carrera de supersesión → `XACK` + `event_ack`. `SQLAlchemyError` → ni `XACK` ni respuesta.
- [ ] 14.8 `retry_after`: presupuesto recién agotado ≈ 60 s; ventana casi expirada ≈ el resto; nunca cero ni negativo.
- [ ] 14.9 Outbox: aprobar inserta la fila `pending` **en la misma transacción**; con Valkey caído el evento queda `approved`, el endpoint responde `200` y la fila queda `pending`; el despachador la publica después y la marca `published`.
- [ ] 14.10 Rollback: una transacción de aprobación que falla no deja fila `PublishedCommand`.
- [ ] 14.11 Un agente sin `shared_secret_hex` hace fallar approve, reject, `update_config` y `rescan` — con la mutación revertida en los cuatro. Reemplaza al test que hoy afirma el `log + return`.
- [ ] 14.12 El no-op de baseline `absent` (RN-74) no encola comando.
- [ ] 14.13 `discarded_events`: se persiste; una clave ausente no pisa el valor guardado; un valor no numérico se ignora sin romper el heartbeat; un agente que nunca reportó expone `null`.
- [ ] 14.14 Revisar y actualizar los tests existentes que asumían el contrato viejo — en particular los que afirman que un rechazo no publica nada y los que afirman publicación post-commit (`backend/tests/`).

## 15. Tests — frontend

- [ ] 15.1 `frontend/src/utils/discardedEvents.test.ts`: los tres estados, y que el mapper nunca lance ante `null` o `undefined`.
- [ ] 15.2 Test de `AgentCard` que verifique que "nunca reportó" NO se renderiza como `0`.

## 16. Verificación manual (NO simulable en tests unitarios)

- [ ] 16.1 Con backend y Valkey reales: parar el backend, generar eventos durante más de cinco minutos, levantarlo, y verificar que **la cola drena completa**. Es la demostración del defecto principal.
- [ ] 16.2 Verificar el mismo drenaje partiendo de una cola escrita por la versión anterior del agente (formato sin sobre), sin tocar el directorio a mano.
- [ ] 16.3 Generar una tormenta que supere los 100 eventos/min y observar que el agente frena, no pierde eventos, y los entrega cuando se libera el presupuesto.
- [ ] 16.4 Aprobar un evento con Valkey caído: verificar `200`, evento `approved`, fila `pending`, y entrega del comando al levantar Valkey.
- [ ] 16.5 Confirmar que un agente **sin actualizar** contra el backend nuevo sigue funcionando exactamente como antes (fila 2 de la matriz de despliegue de D-9).

## 17. Documentación canónica

- [ ] 17.1 En `docs/reglas_de_negocio.md`, RN-90 (`:676-680`): agregar la nota de que D37/RN-131 la enmienda — la ventana se evalúa sobre `sent_at` y `detected_at` deja de tenerla. No borrar el texto original; marcarlo como superado, igual que se hizo con otras reglas enmendadas.
- [ ] 17.2 En `docs/reglas_de_negocio.md`, RN-88 (`:659-668`): marcar que la frase "se descartan con alerta (eventos)" queda superada por D37/RN-131 — el evento se retiene con backpressure y no se emite alerta.
- [ ] 17.3 En `docs/reglas_de_negocio.md`, D4/RN-105 (`:793-806`): agregar que un rechazo ahora produce además la respuesta tipada de D37 para tres de los seis motivos, y que la persistencia en `rejected_events_audit` no cambia.
- [ ] 17.4 En `docs/arquitectura_stack.md`, contrato de mensajes de streams: documentar `sent_at` en el payload de evento, el mensaje `event_nack` con su forma completa, y la matriz de respuestas.
- [ ] 17.5 En `docs/arquitectura_stack.md`, dejar asentado que a partir de esta change un bump de `SCHEMA_VERSION` **exige desplegar el backend antes que los agentes**, porque `invalid_schema` pasó a ser terminal (D-9 del design). Antes era buena práctica; ahora cuesta eventos.
- [ ] 17.6 En `docs/operations.md`, documentar el directorio de descarte: dónde está, qué contiene, que es evidencia y no basura, y que su presencia con contenido es una anomalía a investigar.

## 18. Roadmap y cierre

- [ ] 18.1 Agregar la fila `| 42 | stream-ack-durability | agente + backend + frontend | — (auditoría 2026-08-16) | 40, 41 |` a la tabla de `CHANGES.md`, siguiendo el formato de las filas 40 y 41.
- [ ] 18.2 Agregar la sección `### Change 42 — stream-ack-durability` a `CHANGES.md` con el mismo patrón de las changes de remediación: nota de contexto con el defecto, lista de capacidades, reglas y decisiones aplicadas, y criterio de **Done**.
- [ ] 18.3 En el **Done**, exigir lo verificable: una cola que sobrevivió un corte largo drena completa; un evento rechazado deja de republicarse y queda archivado con su motivo; una tormenta de rate limit no pierde un solo evento; y un approve con Valkey caído entrega el comando al recuperarse.
- [ ] 18.4 Revisar que los follow-ups declarados fuera de scope queden nombrados en la sección: `event-payload-persistence` y la retención de `rejected_events_audit` y demás tablas sin cota.
