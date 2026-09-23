> **Orden — restricción, no preferencia.** El grupo 1 (presupuesto de conexiones) va **antes** que el
> grupo 2 (executor nuevo), y el grupo 2 **antes** que el grupo 4 (call sites). Crear el executor sin
> haber ampliado el pool deja una configuración que el validador rechaza —el arranque falla, que es
> correcto pero no es el orden útil—; cambiar los call sites antes de que el executor exista deja el
> accesor fallando en el primer evento `high`. El grupo 8 (re-medición) va **al final**, con los
> grupos 1 a 7 completos: medir sobre una implementación parcial produce un número que no corresponde
> a nada.

> **Lo que NO se hace en ninguna tarea de esta change.** No se separa la notificación a un stream de
> Valkey ni a un proceso propio (D-11 del design). No se agrega un barrido periódico de notificaciones
> pendientes (D-4). No se migra a `AsyncSession` (D75 lo excluye; RN-76 sigue vigente). No se
> introduce `gather`, `TaskGroup` ni `create_task` por mensaje en el despacho del lote (D75/RN-169).
> No se cambia el contrato de notificación (D40/RN-134), la cascada de canales, los `RETRY_DELAYS` ni
> el default de producción del rate limit (D38/RN-132). No se toca `agent/` ni `frontend/`. No se
> declara por anticipado que esta change mejora ningún número medido (D-10). Si alguna de estas
> parece necesaria durante el apply: **detenerse**, cerrar la decisión en el appendix "Decisiones de
> implementación — Abril 2026" del doc canónico que corresponda, y recién entonces continuar.

## 1. Presupuesto de conexiones con dos executors

- [x] 1.1 En `backend/app/core/config.py`, agregar a `Settings` el campo
  `db_notify_executor_max_workers: int = Field(default=8, ge=1)`, junto al bloque existente de
  `db_pool_size` / `db_max_overflow` / `db_executor_max_workers` (`:162-164`).
- [x] 1.2 Cambiar el default de `db_max_overflow` de 10 a **18**. `db_pool_size` (10),
  `db_executor_max_workers` (10) y `_DB_CONNECTIONS_RESERVED_NON_EXECUTOR` (10, `:33`) **no se
  tocan**: el carril de ingesta no cede capacidad para financiar su propio aislamiento (D-5 del
  design).
- [x] 1.3 Reescribir el comentario del bloque para dejar la aritmética nueva a la vista, con el mismo
  estilo de comentario-con-fundamento que ya usa: `10 + 8 = 18 ≤ 10 + 18 − 10 = 18`. Citar
  **D76/RN-170**, nombrar que la reserva de 10 conserva su reparto de D-4 de la Change 58 (6
  dependencias HTTP de FastAPI + 2 consumer de heartbeat + 2 corrutinas del lifespan con `Session`
  sobre el loop) porque esta change no agrega ningún consumidor fuera de executor, y dejar escrito
  que 28 conexiones corren contra el `max_connections=100` por defecto de `postgres:18.3`
  (`docker-compose.yml:46`, sin override) para un backend single-instance (RN-76).
- [x] 1.4 Modificar el `model_validator` de `:167-186` para que valide la **suma** de los dos
  executors contra la capacidad disponible. Documentar en el docstring por qué es **una** desigualdad
  sobre la suma y no dos independientes: los dos pools de hilos tiran del mismo pool de conexiones, y
  dos condiciones separadas admitirían una configuración donde cada executor cabe por su cuenta y
  juntos agotan el pool — el modo de falla que D75/RN-169 existe para prevenir, con la agravante de
  parecer validado (D-5 del design).
- [x] 1.5 Actualizar el mensaje de error para que nombre los cinco valores en juego, la reserva, el
  máximo permitido y la **suma** recibida. Mantener el criterio fail-fast: una configuración capaz de
  agotar el pool mata el arranque, no se descubre bajo carga como un `TimeoutError` intermitente.
- [x] 1.6 Verificar que `_DB_CONNECTIONS_RESERVED_NON_EXECUTOR` sigue siendo constante de módulo y
  **no** se convierte en un cuarto knob: un parámetro para la reserva permitiría desactivar el
  invariante ajustándolo (criterio heredado de D75/RN-169).
- [x] 1.7 Documentar `DB_NOTIFY_EXECUTOR_MAX_WORKERS` en el template de entorno del backend, junto a
  las tres ya documentadas, con su default y una línea de fundamento. **Anotar explícitamente el
  cambio de default de `DB_MAX_OVERFLOW` (10 → 18)**: un despliegue que hoy lo fije en 10 y no lo
  actualice va a fallar el arranque con el `ValidationError` del invariante. Es el comportamiento
  buscado, pero tiene que estar documentado y no descubrirse en el despliegue (Migration Plan del
  design).
- [x] 1.8 **Verificación del slice**: importar `Settings` con los defaults y comprobar que el
  invariante se cumple (10 + 8 ≤ 18); construir una instancia con `db_notify_executor_max_workers=9`
  sobre los defaults y comprobar que levanta `ValidationError`; comprobar el caso que sólo la suma
  detecta —dos executors que caben por separado pero no juntos— y comprobar que
  `db_notify_executor_max_workers=0` también aborta.

## 2. Executor de notificación y módulo de handles

- [x] 2.1 Crear el módulo nuevo bajo `backend/app/core/` que guarda los dos executors y expone sus
  accesores. Ubicación fundamentada en **D-3 del design**: `alerts/service.py` no puede importar
  `main.py` sin ciclo —`main.py` importa los routers, que importan los services—, y `core/` es donde
  el proyecto ya aloja los recursos de proceso compartidos (`core/database.py`, `core/config.py`).
- [x] 2.2 El accesor del executor de notificación **falla de forma explícita** si se lo invoca antes
  de que el lifespan lo haya instalado. **No** implementar un fallback silencioso al executor por
  defecto: volvería a mezclar los pools en cualquier camino que corra fuera del lifespan —los tests
  son el caso obvio— y el aislamiento se perdería sin que nada lo señale (D-3 del design).
- [x] 2.3 En el lifespan de `backend/app/main.py`, junto al `db_executor` existente (`:114-118`),
  construir el executor de notificación con `max_workers=settings.db_notify_executor_max_workers` y
  un `thread_name_prefix` propio y distinguible, y registrar ambos en el módulo de handles.
- [x] 2.4 **Conservar `asyncio.get_running_loop().set_default_executor(db_executor)` sin cambios**
  (`:118`). El carril de ingesta mantiene el executor por defecto en exclusiva; el de notificación se
  nombra explícitamente (D-2 del design).
- [x] 2.5 Actualizar el comentario de `main.py:104-113`, que hoy declara *"Deliberado: NO se crea un
  executor separado para el carril de ingesta — eso partiría el presupuesto en dos números"*. Esa
  premisa queda **parcialmente derogada** por D76/RN-170 y el comentario nuevo debe decirlo: un
  presupuesto único era más verificable mientras el único consumidor relevante fuera la ingesta, y
  deja de serlo cuando dos carriles con reglas de admisión opuestas —secuencial contra no acotado—
  comparten ese número. La verificabilidad se preserva porque la desigualdad de D-5 los **suma**:
  sigue habiendo una sola cuenta, ahora con dos términos.
- [x] 2.6 En la rama de shutdown del lifespan, cerrar los dos executors con `shutdown(wait=True)`
  **después** del `gather` de cancelación de tasks que ya existe, y el de **notificación antes** que
  el de ingesta. Comentar el orden citando **D-9 del design**: las corrutinas de notificación son las
  últimas en tener trabajo pendiente y las únicas que alimentan su propio executor.
- [x] 2.7 **Verificación del slice**: con el backend levantado, comprobar que existen los dos
  executors con sus prefijos de nombre distintos y sus tamaños configurados, y que el executor por
  defecto del loop es el de ingesta.

## 3. Cota de entregas concurrentes

- [x] 3.1 Agregar a `Settings` el parámetro de cota de entregas concurrentes, default **32**, y el
  umbral de advertencia de backlog, default **200**. Comentar por qué la cota es **mayor** que los 8
  hilos del executor de notificación, citando **D-6 del design**: acotan recursos distintos —el
  executor acota el paralelismo de base de datos del carril, la cota acota corrutinas que pasan la
  mayor parte de su vida esperando en la red o durmiendo entre reintentos, sin ocupar hilo ni
  conexión—. Igualarlos haría que 8 entregas durmiendo sus 120 s de tercer reintento bloquearan el
  carril completo con los 8 hilos ociosos.
- [x] 3.2 Introducir el semáforo **dentro de `notify_event`** (`alerts/service.py:277`), envolviendo
  su cuerpo **después** de la guarda `if alert.id is None` (`:295-296`). **No** ponerlo en el call
  site de `_fire_and_forget`.
- [x] 3.3 Comentar la ubicación citando **D-4 del design**: `notify_event` tiene tres puertas de
  entrada —el consumer (`consumer.py:497` → `notify_if_applicable` → `:164`), la recuperación del
  arranque (`recover_pending_notifications`, cuyo `asyncio.gather` dispara **todas** las pendientes
  de golpe justo cuando el consumer empieza a drenar) y el reintento manual desde la DLQ (`:578`)—.
  Un semáforo en el call site del consumer no tocaría las otras dos; adentro de `notify_event` cubre
  las tres y ninguna puerta futura se lo puede saltear por olvido.
- [x] 3.4 **El permiso se adquiere UNA sola vez, ANTES de `_prepare_notification` (`:304`), y se
  sostiene hasta que la entrega termina** — entregada, fallida en todos los canales, o cortocircuitada
  por el `return` de idempotencia cuando `_prepare_notification` devuelve `None` (`:305-306`).
  Verificar que la liberación ocurre en **todos** los caminos de salida, incluidos los `return` de
  `:306`, `:329` y `:353` y cualquier excepción. Fundamento en **D-7 del design**: adquirirlo después
  de preparar el payload dejaría una `Session` con `commit` y `refresh` fuera de la cota; readquirirlo
  por vuelta del bucle movería `_build_payload` adentro del bucle y produciría un `notification_id`
  por intento.
- [x] 3.5 **No tocar el bucle de reintentos** (`:314-340`), ni la cascada de fallbacks (`:342-351`),
  ni `RETRY_DELAYS` (`:55`). Verificar leyendo el diff que el único cambio estructural de
  `notify_event` es el envoltorio del semáforo.
- [x] 3.6 **No liberar el permiso durante los `asyncio.sleep`** de la escalera. Está evaluado y
  descartado en D-4: con los permisos liberados durante las esperas —que son la mayor parte del
  tiempo de vida de una entrega que falla— el número de corrutinas vivas vuelve a no tener cota, y la
  cota deja de acotar lo que dice acotar. Si durante el apply parece una mejora obvia: **detenerse**.
- [x] 3.7 **La creación de la fila `Alert` queda FUERA del semáforo.** Verificar que
  `_create_alert_row` (`:144`), el `log.info("notify.alert_created", ...)` (`:146`) y el
  `alerts_broadcaster.publish({...})` (`:149-162`) siguen ocurriendo **antes** de entrar a
  `notify_event`, sin permiso de por medio. Fundamento en D-4: una alerta que tarda en entregarse
  sigue siendo visible; una que tarda en **crearse** no existe para nadie, y de esa fila dependen la
  DLQ (RN-86/RN-102), el stream SSE y la recuperación.
- [x] 3.8 Implementar el contador de entregas en espera y la advertencia **disparada por flanco**
  —una vez al cruzar el umbral hacia arriba y una al volver hacia abajo—, con el conteo en el log.
  **Nunca** una línea por notificación: bajo saturación sería exactamente la amplificación que agrava
  la condición que pretende reportar (D-4 del design).
- [x] 3.9 Documentar en el docstring de `notify_event`, junto al INVARIANTE que ya está escrito, que
  el desborde de la cota **espera en orden de llegada** y que descartar o diferir está descartado con
  fundamento: descartar viola la semántica al-menos-una-vez que el mismo docstring declara
  (`:291-293`), y diferir dependería de un barrido periódico que **no existe** —
  `recover_pending_notifications` corre una sola vez, en el arranque—, de modo que significaría
  "entregar en el próximo reinicio".
- [x] 3.10 **Verificación del slice**: comprobar que con la cota en N y 3N notificaciones disparadas
  nunca hay más de N entregas en curso, que las 3N terminan entregándose, y que ninguna se descarta
  ni se marca fallida por la cota.

## 4. Call sites del camino de notificación al executor dedicado

- [x] 4.1 En `backend/app/modules/alerts/service.py`, cambiar los **seis** `run_in_executor` del
  camino por evento para que referencien el executor de notificación en lugar de `None`: `:144`
  (`_create_alert_row`), `:304` (`_prepare_notification`), `:327` y `:344` (`_mark_delivered`),
  `:338` (`_record_retry_attempt`) y `:357` (`_record_all_attempts_failed`).
- [x] 4.2 **No cambiar ninguna firma ni ningún cuerpo.** `_build_payload` (`:169`),
  `_prepare_notification` (`:212`), `_mark_delivered` (`:361`), `_record_retry_attempt` (`:242`),
  `_record_all_attempts_failed` (`:262`), `_create_alert_row` (`:91`) y `_try_fallbacks` (`:388`)
  conservan firma, cuerpo y docstring. Sólo cambia el argumento del call site — mismo criterio que
  D21 y D75.
- [x] 4.3 Comentar en los call sites citando **D76/RN-170** y **D-2 del design** por qué el argumento
  es explícito y no `None`: `set_default_executor` más `run_in_executor(None, ...)` es exactamente el
  mecanismo que compartía los pools, así que mientras un call site pase `None` está pidiendo el
  executor de ingesta, diga lo que diga el comentario que tenga al lado.
- [x] 4.4 **Verificar que NO se tocan** los demás `run_in_executor(None, ...)` del proceso:
  `events/consumer.py:342`, `:446`, `:468`, `:602`, `:611`; `agents/heartbeat_consumer.py:66`,
  `:207`; `agents/command_ack_consumer.py:150`, `:326`; `rules/service.py:453`; `core/health.py:51`,
  `:65`. Siguen en el executor por defecto, que ahora tiene un competidor menos. Esta change no le
  quita hilos al carril de ingesta; le quita un competidor.
- [x] 4.5 Verificar que `session.expunge(...)` sigue donde está (`:108` en `_create_alert_row`, y en
  `recover_pending_notifications`) y que ningún objeto ORM cruza el límite del executor nuevo sin
  estar desligado con sus atributos materializados. Un segundo executor invita a la idea de "un
  executor con estado propio": no lo hay, ninguna `Session` se comparte entre hilos ni cruza el
  límite, en ninguno de los dos (**D-8 del design**).
- [x] 4.6 **Verificación del slice**: correr los tests existentes de notificaciones y de la DLQ de
  alertas **sin modificarlos** y dejar el resultado en el reporte de apply. Si alguno falla, la change
  se pasó de alcance: revisar antes de tocar el test.

## 5. Tests — aislamiento, cota y desborde

- [x] 5.1 Test: **el trabajo de notificación corre en el executor de notificación**. Verificar en los
  seis call sites que el hilo de ejecución pertenece al pool de notificación (por prefijo de nombre) y
  **no** al de ingesta.
- [x] 5.2 Test: **ningún call site del camino de notificación pasa `None`**. Inspección del código,
  con el mismo criterio con el que `test_notification_payload_contract.py:151-168` ya inspecciona la
  posición de `_prepare_notification`. Este test existe porque el modo de falla es **silencioso**: un
  `run_in_executor` nuevo que olvide el argumento funciona igual y el aislamiento desaparece sin
  señal.
- [x] 5.3 Test: **una ráfaga de notificaciones no retrasa la ingesta**. Con el executor de
  notificación saturado, verificar que una operación de base de datos del carril de ingesta obtiene
  un hilo sin esperar a que el trabajo de notificación termine. Éste es el test que corresponde
  directamente al problema que la change existe para resolver.
- [x] 5.4 Test: **la cota de entregas se respeta en las tres puertas de entrada** — consumer,
  `recover_pending_notifications` y reintento manual desde la DLQ. En particular, verificar que la
  recuperación del arranque, cuyo `asyncio.gather` hoy dispara todas las pendientes de golpe, procesa
  respetando la cota.
- [x] 5.5 Test: **el desborde espera, no descarta**. Con más notificaciones que permisos, verificar
  que todas terminan entregándose, que ninguna se marca `failed_at` por causa de la cota, y que
  ninguna se pierde.
- [x] 5.6 Test: **la creación de la fila `Alert` no espera a la cota**. Con la cota completa,
  verificar que un evento `critical` o `high` obtiene su fila en `alerts` y su publicación al
  broadcaster SSE sin esperar un permiso de entrega.
- [x] 5.7 Test: **`notification_id` es estable a lo largo de la escalera completa**. Forzar el
  recorrido de los cuatro intentos de n8n más la cascada de fallbacks y verificar que todos los
  intentos transportan el mismo `notification_id`. **Y un test que falla si `_build_payload` se
  invoca más de una vez por entrega.** Es el riesgo más grave de la change porque el daño no se ve:
  el sistema sigue entregando y lo que se rompe es la deduplicación del **receptor** (D40/RN-134,
  D41/RN-135, **D-7 del design**).
- [x] 5.8 Test: **la advertencia de backlog se dispara por flanco**. Verificar que cruzar el umbral
  con N notificaciones en espera produce **una** línea de log, no N.
- [x] 5.9 Test: **invariante de dimensionamiento desde el lado de la aplicación** (complementa 1.8):
  con la configuración por defecto, la suma de los hilos de los dos executors instalados es menor o
  igual que `pool_size + max_overflow` menos la reserva documentada.
- [x] 5.10 Test: **la cascada de canales y la política de reintentos no cambiaron**. Mismos umbrales,
  mismos contadores, mismos campos escritos en `alerts`, mismo orden n8n → SMTP → webhook_fallback →
  log_only.
- [x] 5.11 Test: **FIFO y no-duplicación no se degradaron** (ítems 40 y 41 del protocolo). Los tests
  que la Change 58 dejó como red de contención deben pasar sin modificarse.

## 6. Verificación integral

- [x] 6.1 Correr la suite completa del backend y dejar el resultado —número de tests, fallos,
  duración— en el reporte de apply. Comparar contra el baseline: la diferencia debe explicarse
  exactamente por los tests agregados en el grupo 5. **Nota de baseline**: `suites/RESULTADO.md` del
  paquete `v2-eval-20260922T175053Z` documenta **8 fallos preexistentes** del backend por colisión de
  puerto 8443 del arnés (`OSError: [Errno 98]`), no por defecto del candidato. Esos 8 no cuentan como
  regresión; cualquier otro sí.
- [x] 6.2 Verificar con una búsqueda sobre `backend/app/modules/alerts/service.py` que **no queda
  ningún** `run_in_executor(None, ...)` en el camino de notificación por evento.
- [x] 6.3 Verificar con una búsqueda sobre `backend/` que no se introdujo ningún `gather`,
  `TaskGroup` ni `create_task` en el bucle de despacho del consumer de eventos, que el bucle sigue
  siendo `for msg_id, msg_data in messages: await _handle_message(...)` (`consumer.py:299-300`), y
  que no aparece ninguna referencia a `AsyncSession`.
- [x] 6.4 Verificar que no se agregó ningún tercer executor ni ningún barrido periódico de
  notificaciones pendientes. Si alguno pareció necesario durante el apply, **detenerse**: son las dos
  cosas que D-4 y D-11 dejaron explícitamente fuera de alcance.
- [x] 6.5 Levantar el stack completo y verificar en el arranque que los dos executors y el pool
  reportan los valores configurados, y que ningún componente de `GET /health/components` se degradó
  respecto del estado previo.
- [x] 6.6 Verificar el arranque con `DB_MAX_OVERFLOW=10` heredado —la configuración que un despliegue
  existente podría tener— y comprobar que **falla con el `ValidationError` del invariante** y un
  mensaje que explica qué subir. Es el comportamiento buscado; la tarea existe para confirmar que el
  mensaje sirve para actuar.
- [x] 6.7 Correr `python3 scripts/check_spec_integrity.py` y dejar el resultado en el reporte de apply
  (D47/RN-141).

## 7. Documentación canónica

- [x] 7.1 Verificar que **D76/RN-170** está en el appendix "Decisiones de implementación — Abril 2026"
  de `docs/reglas_de_negocio.md`, con el mismo formato que D75/RN-169 (Descripción / Condición /
  Motivo / Excepciones / Reglas afectadas) y que el párrafo introductorio del appendix lo incluye en
  su enumeración de fechas.
- [x] 7.2 Verificar que la fila **D76** está en la tabla del appendix de `docs/arquitectura_stack.md`,
  con el mismo nivel de detalle y anclas que la fila D75.
- [x] 7.3 Verificar que la **Change 59** está en `CHANGES.md` con su capa, dependencias del DAG,
  origen, decisiones y bloque **Done**, siguiendo el formato de la Change 58.

## 8. Re-medición del candidato (después de los grupos 1 a 7)

> **Esta change invalida el candidato congelado `v2.0-tesis`** (`9c523f4`, `env/procedencia.txt`).
> Las mediciones de notificación y de resiliencia del paquete `v2-eval-20260922T175053Z` describen un
> binario con un solo executor compartido; después de esta change no describen nada. El paquete
> previo queda como línea de base de comparación: **no se borra ni se sobrescribe**.

- [x] 8.1 Desplegar el backend con la change aplicada y dejar constancia en el reporte de apply de la
  fecha, el commit desplegado y el hash agregado del árbol del backend en el contenedor. Ese hash es
  lo que hace auditable una medición: el commit solo no alcanza para identificar qué se corrió, sobre
  todo si el árbol no está limpio. Mismo criterio que `env/procedencia.txt` del paquete previo.
- [x] 8.2 Re-correr el arnés unificado **completo** `~/fim-lab/corrida_unificada.sh` —no un
  subconjunto— y emitir un **tag nuevo** para el candidato.
- [x] 8.3 **Antes de cada repetición de resiliencia, verificar `initial: events=0`.** Es una
  precondición del protocolo, no una formalidad: `run-02` del paquete previo arrancó con
  `initial: events=35` (`resiliencia/run-02/bateria5_run-02.log`) y esos residuales corrieron
  `min(received_at)` hacia atrás, inflando una ventana calculada como
  `max(received_at) − min(received_at)` de 120,366 s a 566,004 s. De ahí salió una "varianza de 4×"
  que no existe. Dejar el conteo inicial registrado en la evidencia de cada repetición.
- [x] 8.4 Registrar la **latencia de notificación** de los tres escenarios (secuencial, concurrencia
  50, concurrencia 100) junto a los números previos, para que la comparación sea directa:

  | Escenario | n | Media | p95 | Máx |
  |---|---|---|---|---|
  | secuencial | 300 | 5.233,672 ms | 6.469,887 | 6.532,691 |
  | conc50 | 300 | 4.503,563 ms | 6.075,028 | 6.114,594 |
  | conc100 | 300 | 4.270,074 ms | 5.966,762 | 5.989,352 |

  Contra **302,8 ms** de una notificación aislada (`notificacion/procedencia.txt`), es decir ~17× de
  inflación. Ésta es la métrica que el aislamiento debería mover, y es la evidencia principal del
  diagnóstico.
- [x] 8.5 Registrar el **drenaje** de las tres repeticiones junto a los números previos:

  | Repetición | Encolados | Entregados | Descartados | Ventana | Tasa |
  |---|---|---|---|---|---|
  | run-01 | 2671 | 2671 | 0 | 141,061 s | 18,94 ev/s |
  | run-02 | 2664 | 2664 (+35 residuales) | 0 | 120,366 s | 22,13 ev/s |
  | run-03 | 2663 | 2663 | 0 | 150,150 s | 17,74 ev/s |

  Mediana 141,061 s ≈ 18,9 ev/s, contra ≈ 49,7 ev/s del canal `log_only` (2.920 eventos en 58,809 s):
  degradación atribuible al acoplamiento ≈ **2,6×**. Registrar también la preservación y los
  descartes, que en el paquete previo son 100 % y 0 en las tres repeticiones.
- [x] 8.6 Re-verificar los **ítems 40** (orden FIFO) y **41** (cero duplicados) del protocolo. Si
  cualquiera se degradó, la change se detiene acá: no son degradables y no se ajusta el criterio.
- [x] 8.7 **No declarar mejora por anticipado ni reinterpretar el resultado.** Se implementa, se mide,
  y se registra el número medido sea cual sea. Si el aislamiento no mueve los números, eso se escribe
  con la misma claridad con la que la Change 58 escribió que no había mejorado el ítem 43: un diseño
  correcto sobre un cuello que estaba en otro lado sigue siendo un diseño correcto **y** un resultado
  nulo, y confundir las dos cosas es lo que la tabla de ajustes del Change 57 existe para impedir
  (**D-10 del design**).
- [ ] 8.8 Dejar registrado en la evidencia el **supuesto abierto** que esta change declara y no
  resuelve: la contabilidad causal de las operaciones no encoladas no cierra —3.000 operaciones
  emitidas por el generador, 420 líneas `modify colapsado` en el log del agente por repetición, y
  `420 + 2.671 = 3.091 > 3.000`—, de modo que el marcador de colapso **no particiona** el universo de
  operaciones. **No inferir una explicación.** La atribución causal por operación no encolada queda
  sin cerrar con la instrumentación vigente.
- [ ] 8.9 Volver a correr `python3 scripts/check_spec_integrity.py` antes de archivar la change
  (D47/RN-141) y dejar el resultado en el reporte.
