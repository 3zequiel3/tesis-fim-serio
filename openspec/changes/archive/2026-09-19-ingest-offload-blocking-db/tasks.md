> **Orden — restricción, no preferencia.** Los grupos 1 a 3 (configuración, engine, executor) van
> **antes** que los grupos 4 a 6 (call sites): mandar trabajo bloqueante al executor sin haber
> acotado el pool primero cambia un cuello de botella por **agotamiento de conexiones**, que además
> falla en vez de degradar (D75/RN-169, D-4 del design). El grupo 9 (re-medición de la Batería 5) va
> **al final**, con los grupos 1 a 8 completos: medir sobre una implementación parcial produce un
> número que no corresponde a nada.

> **Lo que NO se hace en ninguna tarea de esta change.** No se introduce `gather`, `TaskGroup` ni
> `create_task` por mensaje en el despacho del lote (D-2 del design). No se migra a `AsyncSession`
> (D75 lo excluye; RN-76 sigue vigente). No se cambia el valor por defecto de producción del rate
> limit de ingesta (D38/RN-132). No se redefine el umbral de 30 s del ítem 43 (D-9 del design). No se
> toca `agent/` ni `frontend/`. Si alguna de estas parece necesaria durante el apply: **detenerse**,
> cerrar la decisión en el appendix "Decisiones de implementación — Abril 2026" del doc canónico que
> corresponda, y recién entonces continuar.

## 1. Configuración explícita de pool y executor en `Settings`

- [x] 1.1 En `backend/app/core/config.py`, agregar a `Settings` los tres campos nuevos con sus defaults de D-4: `db_pool_size: int = Field(default=10, ge=1)`, `db_max_overflow: int = Field(default=10, ge=0)` y `db_executor_max_workers: int = Field(default=10, ge=1)`. Ubicarlos como bloque propio, con el mismo estilo de comentario-con-fundamento que usa el bloque de rate limit de ingesta (D38/RN-132) y `rejected_events_retention_days` (D65/RN-159).
- [x] 1.2 Escribir el comentario del bloque citando **D75/RN-169** y dejando la aritmética a la vista, para que la próxima lectura no la reconstruya desde cero: hoy el engine no pasa `pool_size` ni `max_overflow`, así que rigen los defaults de SQLAlchemy (`pool_size=5` + `max_overflow=10` = 15 conexiones, verificado en ejecución como `QueuePool size=5 overflow_max=10`) contra un executor por defecto de `min(32, cpu_count + 4)` = 16 hilos en el anfitrión de medición de 12 CPUs. Nombrar el reparto de D-4: capacidad 20 = 6 (dependencias HTTP de FastAPI) + 2 (consumer de heartbeat) + 2 (corrutinas del lifespan con `Session` sobre el loop) + 10 (executor).
- [x] 1.3 Agregar la constante de módulo `_DB_CONNECTIONS_RESERVED_NON_EXECUTOR = 10` con el comentario que explique por qué es constante y **no** un cuarto parámetro configurable: D75 pide que el pool y el executor sean configurables, no la reserva, y un knob para la reserva permitiría desactivar el invariante ajustándolo (D-4 del design).
- [x] 1.4 Agregar un `model_validator` a `Settings` que aborte el arranque con `ValidationError` si `db_executor_max_workers > db_pool_size + db_max_overflow - _DB_CONNECTIONS_RESERVED_NON_EXECUTOR`. Mensaje de error explícito: los tres valores en juego, la reserva, el máximo permitido y el valor recibido. Mismo criterio fail-fast que el `ge=1` de `rejected_events_retention_days`: una configuración capaz de agotar el pool tiene que matar el arranque, no descubrirse bajo carga como un `TimeoutError` intermitente.
- [x] 1.5 Documentar las tres variables (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_EXECUTOR_MAX_WORKERS`) en el template de entorno del backend, junto a las otras variables ya documentadas, con su default y una línea de fundamento. Las tres son **opcionales**: un despliegue que no las declare arranca con los valores de D-4.
- [x] 1.6 **Verificación del slice**: importar `Settings` con los defaults y comprobar que el invariante se cumple (10 ≤ 20 − 10); construir una instancia con `db_executor_max_workers=11` sobre los defaults y comprobar que levanta `ValidationError`; comprobar que `db_pool_size=0`, `db_max_overflow=-1` y `db_executor_max_workers=0` también abortan.

## 2. Engine con pool explícito

- [x] 2.1 En `backend/app/core/database.py`, pasar `pool_size=settings.db_pool_size`, `max_overflow=settings.db_max_overflow` y `pool_timeout=30` a `create_engine`, junto a los `pool_pre_ping=True` y `echo=False` que ya están. **No** tocar `get_session`.
- [x] 2.2 Actualizar el docstring del módulo (que hoy sólo explica `pool_pre_ping`) para documentar el dimensionamiento citando **D75/RN-169**: por qué los valores son explícitos, de dónde salen, y que `pool_timeout=30` se escribe aunque sea el default de SQLAlchemy para dejar claro que el agotamiento del pool **falla de forma visible** con un `TimeoutError` en vez de colgarse. Anotar que convertir `pool_timeout` en knob sería un parámetro nuevo que D75 no enumera, es decir una suposición nueva que va al appendix primero.
- [x] 2.3 **Verificación del slice**: con el backend levantado, comprobar en ejecución que el pool reporta el tamaño configurado (equivalente a la verificación `QueuePool size=5 overflow_max=10` que documentó el estado previo) y dejar el valor observado en el reporte de apply.

## 3. Executor acotado instalado como executor por defecto del loop

- [x] 3.1 En el lifespan de `backend/app/main.py`, antes de crear las tasks de consumers, construir `ThreadPoolExecutor(max_workers=settings.db_executor_max_workers, thread_name_prefix="fim-db")` e instalarlo con `asyncio.get_running_loop().set_default_executor(...)`. Comentar citando **D75/RN-169** y **D-3 del design**: con un único executor acotado como default, todos los `run_in_executor(None, ...)` del proceso —los tres que ya existen por D21 y los que agrega esta change— tiran del mismo presupuesto, y ese presupuesto es un solo número contrastable contra la capacidad del pool.
- [x] 3.2 En la rama de shutdown del lifespan, cerrar el executor con `shutdown(wait=True)` después de cancelar y recolectar las tasks, dentro del mismo bloque que ya gestiona el cierre del resto de los recursos. Verificar que un `wait=True` no pueda colgar el shutdown indefinidamente por una task todavía en vuelo: el cierre va **después** del `gather` de cancelación que ya existe.
- [x] 3.3 Verificar leyendo el código que **no** se agrega ningún executor adicional: el objetivo es que haya uno solo. Si aparece la tentación de darle un executor propio al carril de ingesta, **detenerse**: D-3 lo evaluó y lo rechazó porque partiría el presupuesto en dos números y volvería el invariante no verificable con una sola cuenta.
- [x] 3.4 **Verificación del slice**: con el backend levantado, comprobar que los hilos del executor llevan el prefijo configurado y que su cantidad máxima coincide con `db_executor_max_workers`; comprobar que un `run_in_executor(None, ...)` cualquiera corre en uno de esos hilos y no en el default de asyncio.

## 4. Consumer de eventos — el carril feliz sale del event loop

- [x] 4.1 En `backend/app/modules/events/consumer.py:305`, reemplazar `agent_auth = _get_agent_auth(agent_id)` por `agent_auth = await loop.run_in_executor(None, _get_agent_auth, agent_id)`. El `loop` ya está resuelto en la línea inmediatamente anterior (`loop = asyncio.get_running_loop()`), hoy sólo usado más abajo en `:420`.
- [x] 4.2 Reemplazar el comentario que hoy justifica la llamada síncrona ("La ingesta ya usa SQLModel sincrónico en este carril ordenado; resolver la única fila de autenticación evita un cambio de executor redundante") por uno que **cite su derogación**: **D75/RN-169** deroga esa premisa porque el carril ordenado es precisamente donde el bloqueo se acumula —cada evento espera a que el anterior termine su viaje a la base—, y el carril de rechazo del mismo archivo ya hacía lo contrario (`:420`, `:554`, `:563`). Nombrar el costo medido de `_get_agent_auth` (1,329 ms) para que la próxima lectura no "arregle" el call site de vuelta.
- [x] 4.3 En `:400`, reemplazar `outcome = _ingest(payload, received_at, detected_at, agent_id)` por la versión en executor, usando `functools.partial` o un lambda cerrado sobre los cuatro argumentos. **No** tocar `_ingest` (`:459`): conserva su firma, su cuerpo y su docstring.
- [x] 4.4 Verificar que el `try/except InvalidTransitionError / SQLAlchemyError` que envuelve `:400` sigue **exactamente donde estaba** y captura lo mismo: `run_in_executor` re-lanza la excepción en el `await`, así que la semántica de `XACK` + audit + nack terminal para `InvalidTransitionError`, y de no-`XACK` (dejar en PEL) para `SQLAlchemyError`, no cambia. Comentar esa equivalencia en el call site para que no se lea como un cambio de manejo de errores.
- [x] 4.5 **No tocar `:268-269`.** Verificar leyendo el diff que el bucle de despacho sigue siendo `for msg_id, msg_data in messages: await _handle_message(client, msg_id, msg_data)`, sin `gather`, sin `TaskGroup` y sin `create_task` por mensaje. Agregar un comentario sobre el bucle citando **D-2 del design**: el despacho es secuencial por contrato (ítems 40 y 41 del protocolo), y la ganancia buscada es de **solapamiento** —que la cadena de notificación de eventos previos avance mientras la ingesta del actual espera a la base en un hilo—, no de paralelismo.
- [x] 4.6 Verificar que el resto de `_handle_message` no cambió: parseo, `check_schema_version`, la rama de agente revocado, la verificación HMAC, la validación de `clock_skew`, la validación de `event_id` no vacío, el despacho por `IngestDisposition` y el `_fire_and_forget(notify_if_applicable(...))` de `:449` quedan idénticos.
- [x] 4.7 **Verificación del slice**: correr los tests existentes del consumer de eventos sin modificarlos y dejar el resultado en el reporte de apply. Si alguno falla, la change se pasó de alcance: revisar antes de tocar el test.

## 5. `_RateLimiter` thread-safe

- [x] 5.1 En `backend/app/modules/events/consumer.py:141-205`, agregar `self._lock = threading.Lock()` a `_RateLimiter.__init__` y envolver con él el cuerpo de `check()`, `seconds_until_available()` y `reset()`. El algoritmo de la ventana deslizante **no cambia**: mismos `popleft` de purga, mismo `append`, mismo `_MIN_RETRY_AFTER_S`.
- [x] 5.2 Reescribir el docstring de la clase, que hoy afirma "**Single-threaded asyncio.**". Esa premisa deja de valer con 4.3: `check()` llega desde un hilo del executor (por el `accept_new=lambda: _rate_limiter.check(agent_id)` que `_ingest` pasa a `_ingest_event_outcome`) mientras `seconds_until_available()` se invoca desde el event loop en el camino de rechazo. Decir explícitamente que el limiter se toca desde los dos lados y por qué lleva lock, citando **D-6 del design**.
- [x] 5.3 Verificar que ni RN-88 (límite efectivo por `agent_id`) ni D37/RN-131 (el `retry_after` derivado del mismo `_window_s`) cambian de comportamiento: el lock no altera el valor devuelto por ninguna de las dos funciones.
- [x] 5.4 **Verificación del slice**: correr los tests existentes del rate limit de ingesta sin modificarlos. Agregar un test que ejercite `check()` desde varios hilos concurrentes sobre el mismo `agent_id` y verifique que el número total de admisiones es exactamente el límite configurado, ni uno más.

## 6. Notificaciones — las `Session` del camino por evento salen del event loop

- [x] 6.1 En `backend/app/modules/alerts/service.py:116-119`, extraer el bloque `with Session(engine)` que crea la fila `Alert` (add + commit + refresh) a un helper **síncrono** de módulo, e invocarlo desde `notify_if_applicable` con `await loop.run_in_executor(None, ...)`. El helper devuelve la instancia `Alert` ya utilizable fuera de la sesión. Comentar citando **D75/RN-169**: la notificación ya era fire-and-forget y por eso no bloqueaba a `_handle_message` de forma directa, pero su `Session` **sí frenaba el event loop**, y frenar el loop es frenar el bucle de despacho secuencial.
- [x] 6.2 Verificar que la instancia `Alert` que el helper devuelve al loop puede leerse (`id`, `event_id`, `severity`, `notification_id`, `created_at`) **sin disparar I/O**, aplicando el mismo criterio que `events/service.py` ya usa para el `Event` (`session.expunge(...)` antes de cerrar). Si el `refresh` + cierre de sesión dejara atributos expirados, el `log.info("notify.alert_created", ...)` y el `alerts_broadcaster.publish({...})` inmediatamente posteriores lo harían fallar en el loop.
- [x] 6.3 Verificar que el payload publicado al broadcaster SSE (`:123-138`) y el orden de las operaciones —crear fila, loguear `notify.alert_created`, publicar al broadcaster, `await notify_event(...)`— quedan **idénticos**. Esta tarea mueve dónde corre el trabajo, no qué hace.
- [x] 6.4 Aplicar el mismo tratamiento a las `Session` del camino de entrega que corre **por evento**: `:203`, `:246`, `:268` (dentro de `notify_event`) y `:286` (`_mark_delivered`, que ya es una función síncrona y sólo necesita cambiar su call site). Fundamento en **D-7 del design**: los ~5,7 ms medidos de la cadena de notificación se miden de `notify.alert_created` a `notify.delivered`, así que incluyen estas líneas; desbloquear sólo `:116` dejaría el resto frenando el loop y derrotaría el solapamiento que esta change busca. Cae dentro de la **Condición** textual de D75 ("cualquier camino que abra una `Session` síncrona dentro de una corrutina").
- [x] 6.5 Verificar que la cascada de canales (n8n → SMTP → webhook_fallback → log_only) y la política de reintentos con espera exponencial **no cambian**: mismos umbrales, mismos contadores, mismos campos escritos en `alerts`.
- [x] 6.6 **No tocar** `recover_pending_notifications` (`:332-361`), `retention_task` (`events/service.py:467`) ni la lectura de `outbox_publisher_task` (`rules/service.py:441`). Corren una vez en el arranque o con baja frecuencia periódica, están fuera del carril por evento, y su consumo de conexiones ya está **reservado** en el presupuesto de D-4. Dejarlo anotado en el reporte de apply como relevado y deliberadamente fuera de alcance (D-8 del design).
- [x] 6.7 **Verificación del slice**: correr los tests existentes de notificaciones y de la DLQ de alertas sin modificarlos, y dejar el resultado en el reporte de apply.

## 7. Tests — FIFO, no-duplicación y despacho secuencial no degradados

- [x] 7.1 Test: **el despacho del lote sigue siendo secuencial**. Con un lote de mensajes y un `_handle_message` instrumentado que registre entradas y salidas, verificar que en ningún instante hay más de uno en vuelo. Este test es la red de contención de D-2: existe para fallar si alguien "aprovecha y paraleliza el lote".
- [x] 7.2 Test: **orden FIFO preservado** (ítem 40). Ingerir un lote de eventos con sufijo monótono del generador y verificar que el orden de inserción, ordenando por `detected_at`, reproduce el orden de generación. Mismo criterio de verificación que usa el protocolo del Capítulo 5.
- [x] 7.3 Test: **cero duplicados** (ítem 41). Reentregar el mismo `event_id` (incluyendo el caso de reentrega del PEL tras un error transitorio de base de datos) y verificar que la tabla de eventos no tiene ningún `event_id` repetido, y que el camino de duplicado resuelve con ACK sin reinsertar ni consumir cupo de rate limit.
- [x] 7.4 Test: **el `Event` cruza el límite del executor sin disparar I/O**. Verificar que la instancia devuelta por `_ingest` tiene sus atributos materializados fuera de la `Session` (el `session.expunge(event)` previo al `commit` de `events/service.py:446-448` es carga, no casualidad) y que leerla desde el loop no emite ninguna consulta. Este test existe para que una change futura no borre ese `expunge` por parecer redundante.
- [x] 7.5 Test: **`_get_agent_auth` e `_ingest` se invocan fuera del event loop**. Verificar en los dos call sites que la ejecución ocurre en un hilo distinto del hilo del loop.
- [x] 7.6 Test: **la semántica de errores del carril feliz no cambió**. `InvalidTransitionError` levantada dentro del executor sigue produciendo `XACK` + fila de auditoría de rechazo + nack terminal; `SQLAlchemyError` sigue produciendo **no**-`XACK` (el mensaje queda en el PEL para reintento).
- [x] 7.7 Test: **la creación de la fila `Alert` y la marca de entrega ocurren fuera del event loop**, y el payload publicado al broadcaster SSE es idéntico al previo.
- [x] 7.8 Test: **invariante de dimensionamiento** (complementa 1.6 desde el lado de la aplicación): con la configuración por defecto, el número de hilos del executor instalado es menor o igual que `pool_size + max_overflow` menos la reserva documentada.

## 8. Verificación integral

- [x] 8.1 Correr la suite completa del backend y dejar el resultado —número de tests, fallos, duración— en el reporte de apply. Comparar contra el baseline previo a la change: la diferencia debe explicarse exactamente por los tests agregados en los grupos 5 y 7.
- [x] 8.2 Verificar con una búsqueda sobre `backend/app/modules/events/consumer.py` que **no queda ninguna** llamada síncrona a base de datos en el carril feliz de `_handle_message`, y sobre `backend/app/modules/alerts/service.py` que no queda ninguna `Session` abierta directamente sobre una corrutina del camino por evento.
- [x] 8.3 Verificar con una búsqueda sobre `backend/` que no se introdujo ningún `gather`, `TaskGroup` ni `create_task` en el bucle de despacho del consumer de eventos, y que no aparece ninguna referencia a `AsyncSession`.
- [x] 8.4 Correr `python3 scripts/check_spec_integrity.py` y dejar el resultado en el reporte de apply (D47/RN-141).
- [x] 8.5 Levantar el stack completo y verificar en el arranque del backend que el pool y el executor reportan los valores configurados, y que ningún componente de `GET /health/components` se degradó respecto del estado previo.

## 9. Re-medición de la Batería 5 (después de los grupos 1 a 8)
> **Estado del grupo 9.** La re-medición se hizo el **2026-09-18**. Evidencia:
> `tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/bateria5/corte-valkey-post-d75/`.
> **El ítem 43 sigue sin cumplirse y la change no lo mejoró.** Ese resultado, y la causa raíz que
> lo explica, están registrados abajo tarea por tarea y en la sección «Resultado de la re-medición»
> de `design.md`. Ninguna tarea de este grupo declara un cumplimiento que no ocurrió.

- [x] 9.1 Desplegar el backend con la change aplicada y dejar constancia de la fecha y del commit desplegado en el reporte de apply.
  - **Fecha:** 2026-09-18 (arnés 12:56:17Z → 13:02:41Z).
  - **Commit desplegado:** `7a906c202e417aec5f03d9a7545e216a724aca81` (tag `v1.0-tesis`) **con la Change 58 aún sin commitear**. `procedencia.txt` lo declara explícitamente: `git_status_clean=no`, `uncommitted_change=ingest-offload-blocking-db (Change 58, D75/RN-169)`, y enumera los archivos modificados.
  - **Trazabilidad del binario medido:** procedencia del contenedor verificada contra el árbol, hash agregado del backend `d55fb734ae22a90c431c643cd73db2d4822fc4e057b686e80a128d6bd7de009d`. Ese hash es lo que hace auditable una medición tomada sobre un árbol sucio: el commit solo no alcanzaría para identificar qué se corrió.
- [x] 9.2 Re-correr la **Batería 5 (corte de Valkey)** con el protocolo del ítem 43: corte de Valkey con la duración **real** registrada (ítem 36), manifiesto del generador (ítem 37), cola local preservada verificada **antes** de reconectar (ítem 38) y cola drenada a 0 (ítem 39).
  - Corte de **Valkey** —el que pide `tesis/plan_medicion_cap5.md:338`—, no el del backend.
  - **Ítem 36:** Valkey caído 12:56:18.974Z, restaurado 13:01:26.667Z ⇒ **307,7 s** reales de corte.
  - **Ítem 37:** manifiesto del generador presente (`..._manifiesto.json`, `..._manifiesto.jsonl`, 3000 cambios a 10/s en 299,901 s, 0 errores).
  - **Ítem 38:** cola local preservada verificada **antes** de reconectar — `generator finished; queue+discarded=2678 0` a las 13:01:20.854Z, previo a la fase 3.
  - **Ítem 39:** `DRAIN COMPLETE: events=2678 queue=0 discarded=0`; `final: events=2678 queue+discarded=0 0`.
  - **0 descartados y 0 rechazos de cualquier tipo:** `rechazos.csv` solo tiene el encabezado.
- [x] 9.3 Declarar el **límite de ingesta efectivo** usado en la corrida, según **D38/RN-132**, igual que se hizo en la corrida del 2026-09-18 (100000/60 s). El valor por defecto de producción del rate limit **no se cambia** en función de estas mediciones.
  - Declarado en el encabezado del log del arnés: `=== Battery 5 — label=corte-valkey-post-d75 rate_limit=100000/60s ===`.
  - El default de producción **no se tocó**. La elevación es del arnés de medición, para que el rate limit no sea la variable medida.
- [ ] 9.4 Medir el drenaje **desde `received_at` en la base, no desde el sondeo del arnés**: los dos extremos de la ventana salen de la columna `received_at` de la tabla `events`. El sondeo del arnés tiene su propio período y su propia latencia, y midiendo desde él se estaría midiendo el instrumento además del sistema. Dejar la query usada en la evidencia.
  - **Sin marcar a propósito.** La medición desde `received_at` **sí se hizo**; lo que falta es la segunda cláusula: **el texto de la query usada no quedó guardado en la evidencia**. Solo está su resultado (`item43.txt`) y el volcado de filas (`eventos_backend.csv`, con la columna `received_at`). Reconstruir el SQL a partir del encabezado de la salida sería escribir una query que nadie corrió, así que la tarea queda abierta en vez de aproximada.
  - **Medición (la parte que sí se cumplió):** ventana **58,809 s** (`2026-09-18 13:01:23.948502+00` → `13:02:22.757883+00`), **2678 eventos**, **2678 únicos**, **45,54 ev/s**.
  - **Por qué la distinción no es cosmética:** el arnés reportó `drain_duration_s=73,583476962` y `throughput_ev_s=36,3940`. Esos ~14,8 s de diferencia son histéresis de su propio bucle de estabilidad (~15-20 s), no del sistema. **El número válido es el de la base: 58,809 s.** Usar el del arnés habría inflado el incumplimiento con latencia del instrumento.
- [x] 9.5 Re-verificar el **ítem 40** (monotonía del sufijo del generador ordenando por `detected_at`) y el **ítem 41** (la query de duplicados del protocolo, que debe devolver 0 filas). Si cualquiera de los dos se degradó, la change se detiene acá: son no degradables y no se ajusta el criterio.
  - **Ítem 40 — orden FIFO: 0 inversiones.** Ordenando por `received_at`, `detected_at` nunca retrocede. Verificado sobre **las dos** corridas: 2893 filas (previa) + 2678 filas (post-D75) = **5571 eventos, 0 inversiones**.
  - **Ítem 41 — duplicación: 0 duplicados** de `event_id` en las dos corridas.
  - **Esto es el resultado más importante del grupo.** Sacar la ingesta del event loop a un executor de hilos ponía en riesgo justamente el orden FIFO, y ése era el riesgo principal del diseño (D-2). **La change no lo degradó.**
  - Evidencia y comando reproducible: `verificacion-items-40-41.txt` en el directorio de la corrida.
- [x] 9.6 Registrar el resultado del ítem 43 con el número medido, junto al número previo (2.893 eventos en 59,389 s = 48,7 ev/s ≈ 20,4 ms por evento) para que la comparación sea directa. Guardar la evidencia con la misma estructura que `tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/bateria5/corte-valkey/`.
  - | Corrida | Eventos | Ventana (desde `received_at`) | Tasa | ms/evento |
    |---|---|---|---|---|
    | Previa a D75 (`corte-valkey`) | 2893 | 59,389 s | 48,7 ev/s | ~20,4 ms |
    | Con D75 (`corte-valkey-post-d75`) | 2678 | 58,809 s | 45,54 ev/s | ~21,96 ms |
  - **La change NO mejoró el ítem 43.** La tasa bajó de 48,7 a 45,54 ev/s. El umbral del ítem 43 (drenaje completo en < 30 s) exigía **> 96,4 ev/s**; se está a menos de la mitad. No hay lectura optimista disponible acá y no se ofrece ninguna.
  - Evidencia con la misma estructura que la corrida previa, más `procedencia.txt`, `item43.txt`, `verificacion-items-40-41.txt` y `distribucion-llegadas.txt`.
- [x] 9.7 **No declarar incumplimiento anticipado ni redefinir el umbral de 30 s.** Si el drenaje medido queda por encima del umbral, eso abre un **ajuste de criterio declarado propio, con el número nuevo a la vista**, en la tabla de ajustes — y esa declaración es una tarea posterior a esta medición, nunca previa. Declararla antes de medir sería exactamente la reinterpretación silenciosa que la tabla de ajustes del Change 57 existe para evitar (D75/RN-169, D-9 del design).
  - **Cumplida:** no se declaró incumplimiento antes de medir y **el umbral de 30 s no se redefinió en esta change**.
  - El ajuste de criterio que el incumplimiento medido habilita **queda pendiente como tarea posterior**, fuera de esta change, exactamente como D-9 lo pide. Esta change cierra registrando el número, no reinterpretándolo.
- [x] 9.8 Volver a correr `python3 scripts/check_spec_integrity.py` antes de archivar la change (D47/RN-141) y dejar el resultado en el reporte.
  - **Antes de archivar:** `OK — 54 main specs, 385 requisitos, sin problemas.` (exit 0).

## 10. Causa raíz del ítem 43 — identificada después de la re-medición

> Esta sección **no agrega tareas**. Registra por qué el ítem 43 no se cumplió, para que la change
> no se archive dejando el número sin explicación y para que la próxima lectura no vuelva a buscar
> la causa en el backend.

**El drenaje no está limitado por rendimiento. Está limitado por una espera en el agente.**

- `agent/publisher.py:62` fija `_ACK_TIMEOUT_S = 60.0` y `agent/publisher.py:613` corre el bucle de
  reintento con `await asyncio.sleep(5)`. Durante el corte los eventos quedan en `_pending` con su
  timestamp original y **solo se republican cuando superan los 60 s**. Los eventos generados en el
  último minuto del corte tienen que **envejecer** antes de volver a salir.
- **Evidencia en la distribución de llegadas** (`distribucion-llegadas.txt`): los primeros 15 s traen
  **1047 eventos a ~69,9 ev/s** —bastante por encima del promedio de 45,54— y después la cola llega
  en **grupos separados por huecos de ~4,6 s** (medidos en t=43,7 s, 48,9 s y 54,1 s), que es la
  cadencia del `sleep(5)`. El backend absorbe rápido cuando tiene material; se queda esperando
  porque el agente todavía no se lo ofreció.
- **Perfilado que descarta las otras hipótesis** (medido en la VM, con los módulos del agente):
  `bump_attempts` 1,665 ms · escritura atómica 1,687 ms · lo mismo sin cripto 1,655 ms (o sea que el
  costo es el **fsync**, no el cifrado) · firma HMAC 0,008 ms · `queue.remove` 0,033 ms · XADD sobre
  mTLS 0,457 ms. **Suma conocida ~2,2 ms contra 21,96 ms observados: la diferencia es espera, no
  trabajo.**

**Consecuencia para esta change.** La Change 58 atacó el backend —sacar del event loop las `Session`
síncronas del carril de ingesta y de notificación— y ese trabajo está hecho y verificado. Pero el
cuello del ítem 43 **no estaba ahí**. Por eso la change no mueve el número. Corregir la cadencia y el
timeout del publisher del agente es un cambio distinto, sobre `agent/`, que esta change declara
explícitamente fuera de alcance (ver el bloque «Lo que NO se hace en ninguna tarea de esta change»).
