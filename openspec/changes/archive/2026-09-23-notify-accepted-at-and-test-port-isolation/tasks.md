> **Orden — restricción, no preferencia.** El grupo 1 (columna y migración) va **antes** que el grupo
> 2 (captura): escribir la captura contra una columna que no existe produce un `ProgrammingError` en
> el primer evento `high`. El grupo 7 (protocolo de medición) va **después** del grupo 2: una batería
> que consulta una columna sin datos produce un CSV vacío, que es indistinguible de "el sistema no
> notificó". El grupo 9 (re-medición) va **al final**, con los grupos 1 a 8 completos: medir sobre una
> implementación parcial produce un número que no corresponde a nada.
>
> Los grupos 1-2 (defecto 1) y 3-4 (defecto 2) son **independientes entre sí** y pueden hacerse en
> cualquier orden relativo. Sólo la re-medición espera a las dos mitades.

> **Lo que NO se hace en ninguna tarea de esta change.** No se redefine la semántica de
> `delivered_at` (D-4 del design). No se hace backfill de la columna nueva (D-3). No se agrega la
> columna al payload canónico de notificación ni al modelo de respuesta de la API (D-4). No se cambia
> la firma de `send_n8n` ni la de ningún canal de la cascada (D-1, alternativa A descartada). No se
> liga `notifier.n8n_sent` a la alerta (D-1, alternativa B descartada). No se toca el bucle de
> reintentos, la cascada, `RETRY_DELAYS`, el `async with _delivery_slot()` ni el punto en que se
> adquiere el permiso (D76/RN-170). No se cambia el default del puerto en `pki.py` ni la invocación
> del lifespan en `main.py` (D-5). No se cambia `env_file` en `config.py` (D-6). No se editan los 41
> call sites de `TestClient` (D-5). No se toca `agent/` ni `frontend/`. No se declara por anticipado
> que esta change mejora ningún número medido (D-10). Si alguna de estas parece necesaria durante el
> apply: **detenerse**, cerrar la decisión en el appendix "Decisiones de implementación — Abril 2026"
> del doc canónico que corresponda, y recién entonces continuar.

## 1. Columna `channel_accepted_at` y migración 022

- [x] 1.1 En `backend/app/modules/alerts/models.py`, agregar a `Alert` el campo
  `channel_accepted_at: datetime | None = Field(default=None, sa_type=_TZ_AWARE)`, junto a
  `delivered_at` (`:32`) y `failed_at` (`:33`). El `sa_type=_TZ_AWARE` no es opcional: es el criterio
  de D39/RN-133 que ya aplica a las cuatro columnas de tiempo de la tabla (`:8`).
- [x] 1.2 Comentar el campo con la distinción que esta change existe para fijar, en el mismo estilo
  de comentario-con-fundamento que ya usa el bloque de `notification_id` (`:36-37`): esta marca
  registra el instante en que **un canal aceptó** la notificación, capturado en la corrutina apenas
  el envío devolvió éxito; `delivered_at` registra el instante en que **se persistió el éxito**,
  dentro del hilo del executor. No son sinónimos y no son intercambiables. Citar **D77/RN-171**.
- [x] 1.3 Crear `backend/db/migrations/022_add_alert_channel_accepted_at.sql`. **022 es el siguiente
  número libre**, verificado contra `backend/db/migrations/`, cuyo máximo actual es
  `021_add_agent_queue_pressure_high.sql`. Re-verificar antes de escribir: si el directorio creció,
  tomar el siguiente y no éste.
- [x] 1.4 El cuerpo de la migración es un único
  `ALTER TABLE alerts ADD COLUMN IF NOT EXISTS channel_accepted_at TIMESTAMPTZ;`, idempotente, mismo
  estilo que `014_add_alert_delivery_state.sql`. **Sin `NOT NULL`, sin `DEFAULT`, sin índice y sin
  `UPDATE` de backfill.**
- [x] 1.5 Encabezar la migración con el comentario que explica las tres ausencias, citando D-3 del
  design: anulable porque una alerta no entregada no tiene instante de aceptación; sin backfill porque
  el único valor derivable sería `delivered_at`, que es precisamente la magnitud equivocada y
  produciría una columna que aparenta medir la aceptación y mide otra cosa; sin índice porque es
  material de análisis sobre una ventana temporal, no predicado de consulta caliente.
- [x] 1.6 **Verificación del slice**: aplicar la migración sobre una base con filas existentes y
  comprobar que todas quedan con `channel_accepted_at IS NULL`; aplicarla dos veces seguidas y
  comprobar que la segunda no falla; comprobar que un backend de la versión anterior arranca sin
  error contra el esquema nuevo.

## 2. Captura del instante de aceptación en el camino de notificación

- [x] 2.1 En `backend/app/modules/alerts/service.py`, extender la firma de `_mark_delivered`
  (`:467-472`) con un parámetro para el instante de aceptación del canal. **Es el único cambio de
  firma de toda esta change.**
- [x] 2.2 En el cuerpo de `_mark_delivered` (`:480-487`), escribir ese valor en
  `db_alert.channel_accepted_at` dentro del mismo `with Session(engine)` y **antes del `commit` que
  ya existe**. **No agregar un `commit` propio, no abrir una segunda `Session` y no agregar un
  `refresh`.**
- [x] 2.3 **`db_alert.delivered_at = datetime.now(timezone.utc)` (`:483`) NO se toca.** Sigue
  evaluándose dentro del hilo del executor. Verificar leyendo el diff que esa línea es
  byte-idéntica. Fundamento en D-4 del design: hay mediciones emitidas que dependen de ese
  significado, y redefinirlo las invalidaría retroactivamente en vez de corregir la brecha.
- [x] 2.4 En el camino de éxito de n8n (`:428-432`), capturar `datetime.now(timezone.utc)`
  **inmediatamente después** de que `await send_n8n(...)` devolvió `True` y **antes** del
  `await loop.run_in_executor(get_notify_executor(), _mark_delivered, ...)` de `:429-431`. Pasar ese
  valor como argumento. El `run_in_executor` sigue referenciando `get_notify_executor()`
  explícitamente (D76/RN-170): **no** volver a `None`.
- [x] 2.5 En el camino de éxito de la cascada (`:447-457`), hacer lo mismo inmediatamente después de
  que `await _try_fallbacks(payload)` devolvió `success`. El canal que registra la fila sigue siendo
  el que devuelve `_try_fallbacks`; la marca corresponde a la aceptación de ese canal.
- [x] 2.6 Comentar los dos puntos de captura citando **D-1 del design**: el punto de éxito de la
  corrutina es el primer instante del proceso en que se sabe, con `alert.id` a la vista, que un canal
  aceptó; todo lo que viene después —el despacho al executor, la espera en la cola FIFO del pool, la
  `Session`, el `commit`— es exactamente lo que el protocolo de medición excluye
  (`tesis/plan_medicion_cap5.md:202-204`).
- [x] 2.7 Anotar en el mismo comentario el **error residual declarado**: entre el
  `response.raise_for_status()` de `notifier.py:47` y esta captura hay una línea de log, el cierre del
  `AsyncClient` de httpx y el retorno de la corrutina — del orden de microsegundos a un milisegundo,
  contra una magnitud objetivo que el protocolo acota en segundos. La alternativa exacta (devolver el
  instante desde `send_n8n`) está evaluada y descartada en D-1 por desproporción. **Se declara, no se
  oculta.**
- [x] 2.8 **No tocar nada más de `notify_event`** (`:383-465`): ni el `async with _delivery_slot()`
  (`:399`), ni el punto en que se adquiere el permiso, ni el `run_in_executor` de
  `_prepare_notification` (`:406`), ni el bucle de reintentos, ni `RETRY_DELAYS`. Verificar leyendo el
  diff que los únicos cambios de la función son las dos capturas y los dos argumentos extra.
- [x] 2.9 **No tocar** `_build_payload`, `_prepare_notification`, `_record_retry_attempt`,
  `_record_all_attempts_failed`, `_try_fallbacks` ni `recover_pending_notifications`. Verificar que
  `_build_payload` sigue invocándose exactamente una vez, dentro de `_prepare_notification` (`:321`) y
  fuera del bucle (D40/RN-134, D41/RN-135).
- [x] 2.10 **No tocar `backend/app/modules/alerts/notifier.py`.** Ni la firma de `send_n8n` (`:28`),
  ni la línea `notifier.n8n_sent` (`:48`), ni `backend_dispatched_at` (`:41-44`), ni los fallbacks.
- [x] 2.11 **No tocar `backend/app/modules/alerts/router.py`.** Verificar explícitamente que el modelo
  de respuesta (`:64`) no incorpora la columna y que el estado derivado (`:82-83`) sigue calculándose
  sólo desde `delivered_at` y `failed_at` (D-4 del design).
- [x] 2.12 **Verificación del slice**: entregar una notificación por n8n y comprobar que
  `channel_accepted_at` queda no nulo y `≤ delivered_at` en la misma fila; entregar por un canal de la
  cascada y comprobar lo mismo; hacer fallar toda la cascada y comprobar que `channel_accepted_at`
  queda en `NULL` y la fila cae en la DLQ.

## 3. Aislamiento del puerto de escucha en el arnés de pruebas

- [x] 3.1 Promover `_free_port()` a `backend/tests/conftest.py`, con el cuerpo exacto de
  `backend/tests/test_mtls_transport.py:111-118` —incluido el `except PermissionError` que hace
  `pytest.skip("sandbox does not permit local TCP sockets")`, que no es accesorio: sin él la suite
  falla en cualquier entorno que no permita abrir sockets locales.
- [x] 3.2 Actualizar `test_mtls_transport.py` y `test_agent_cert_renewal_e2e.py` para importar el
  helper del conftest en lugar de definirlo. **Sin cambiar el comportamiento de esos tests**: siguen
  invocando `start_mtls_server` directamente, fuera del lifespan, con `port=` explícito
  (`test_mtls_transport.py:143-151`).
- [x] 3.3 Agregar al conftest raíz una fixture de aplicación automática que neutralice el arranque del
  servidor mTLS del lifespan, siguiendo el mecanismo ya establecido en
  `backend/tests/test_rejected_events_retention.py:299-300` y
  `backend/tests/test_notify_isolate_executor_lifespan.py:46-47`
  (`monkeypatch.setattr(main_module, "start_mtls_server", lambda *a, **k: None)`).
- [x] 3.4 Evaluar y decidir lo mismo para `start_bootstrap_server`, que los dos precedentes neutralizan
  en la línea siguiente y que el arnés de suites también debe liberar
  (`scripts/correr_suites_candidato.sh:83`, *"stopping the lab backend to free 8443/8444"*). Si tiene
  el mismo defecto, cubrirlo con la misma fixture; si no, dejar escrito por qué no.
- [x] 3.5 Documentar la fixture con el fundamento de **D-5 del design**: una fixture cubre los 41 call
  sites de hoy **y los que se escriban mañana**; editar 41 sitios cubre 41 sitios, y el 42.º vuelve a
  colisionar con un error que no nombra la causa (`RuntimeError: This portal is not running`, que es
  el síntoma del teardown y no del bind).
- [x] 3.6 **Los 41 `with TestClient(app)` no se tocan** — `test_notifications.py` (16),
  `test_sse_alerts.py` (14), `test_sse_stream_ticket.py` (10), `test_logging_sanitize.py` (1).
  Verificar leyendo el diff que ninguno de los cuatro archivos cambió por esta tarea.
- [x] 3.7 **`backend/app/core/pki.py` y `backend/app/main.py` no se tocan.** Verificar que
  `start_mtls_server` conserva su firma completa (`:638-645`), incluido `port: int = 8443`, y que la
  invocación del lifespan (`main.py:92-97`) es byte-idéntica. Esta verificación es la obligación dura
  del spec: *sin cambiar ninguna ruta de código de producción*.
- [x] 3.8 **Verificación del slice**: correr `test_notifications.py` y `test_sse_alerts.py` juntos en
  la misma sesión, **con el puerto 8443 ocupado a propósito por otro proceso**, y comprobar que no
  aparece ningún `RuntimeError: This portal is not running`. Comprobar que
  `test_mtls_transport.py` y `test_agent_cert_renewal_e2e.py` siguen pasando con su listener real.

## 4. Entorno de configuración determinado en el arnés

- [x] 4.1 En `backend/tests/conftest.py`, junto al bloque que ya fija el entorno canónico antes del
  primer import de la aplicación (`:51-66`), neutralizar la lectura del archivo de entorno que
  `backend/app/core/config.py:40` resuelve contra el directorio de trabajo. La suite debe producir el
  mismo resultado corrida desde la raíz del repositorio —donde hay un `.env` real— que desde un
  directorio sin él.
- [x] 4.2 Documentar el bloque con la precisión de **D-6 del design**, porque determina el arreglo:
  `test_notification_settings.py:23-39` **ya** hace `monkeypatch.delenv` sobre las seis claves y eso
  es correcto; lo que ninguna limpieza de `os.environ` puede hacer es impedir que pydantic-settings
  lea el archivo. La prueba de que la fuga es el archivo y no el proceso es que la aserción sobre
  `n8n_health_url` falla, y `n8n_health_url` es una clave que el `delenv` sí borra del proceso.
- [x] 4.3 Aplicar el criterio fail-fast que el conftest ya sostiene en `pytest_sessionstart`
  (`:37-49`): si el mecanismo de aislamiento no puede establecerse, **abortar la sesión** en lugar de
  correr una suite cuyo resultado depende del directorio de invocación. El argumento es el mismo que
  el de `psycopg`: un resultado que no describe el producto es peor que una falla.
- [x] 4.4 **No cambiar `backend/app/core/config.py`.** `env_file=".env"` (`:40`) es correcto y
  necesario para el despliegue; el defecto no es que la aplicación lea su `.env`, es que la **suite**
  lo herede. Verificar que el archivo es byte-idéntico.
- [x] 4.5 Revisar si `test_notification_settings.py` sigue necesitando su `_fresh_settings`
  (`:23-39`) una vez que el conftest garantiza el entorno. Si el `delenv` queda redundante,
  **conservarlo igual** y anotar por qué: es la defensa explícita del test contra una variable
  exportada, y quitarla dejaría la prueba dependiendo de un mecanismo que vive en otro archivo.
- [x] 4.6 **Verificación del slice**: correr `backend/tests/core/test_notification_settings.py` desde
  la raíz del repositorio, con el `.env` presente **y** con `N8N_WEBHOOK_URL` y `N8N_HEALTH_URL`
  exportadas en el entorno del proceso, y comprobar que las cuatro pruebas pasan. Comprobar que la
  defensa de D43/RN-137 que esas pruebas sostienen —el health check no se deriva del webhook— sigue
  siendo verificada de verdad y no aprobada por vacío.

## 5. Tests del defecto 1

- [x] 5.1 Test: entrega exitosa por n8n en el primer intento → `channel_accepted_at` no nulo,
  `delivered_at` no nulo, y `channel_accepted_at <= delivered_at` en la misma fila.
- [x] 5.2 Test: entrega exitosa por cada canal de la cascada (`smtp_fallback`, `webhook_fallback`,
  `log_only`) → `channel_accepted_at` no nulo en los tres, con el `channel` correspondiente.
- [x] 5.3 Test: la cascada completa falla → `channel_accepted_at` permanece en `NULL`, `failed_at` no
  nulo, y la alerta aparece en la DLQ.
- [x] 5.4 Test: entrega exitosa en el tercer intento de la escalera → `channel_accepted_at` marca el
  intento que aceptó, no el primero, y `notification_id` es el mismo en los tres intentos.
- [x] 5.5 Test que **falla si `_build_payload` se invoca más de una vez por entrega**. Ya existe
  cobertura equivalente de D76/RN-170; verificar que sigue pasando y extenderla para cubrir el camino
  con la marca nueva.
- [x] 5.6 Test: la recuperación del arranque y el reintento manual desde la DLQ también escriben
  `channel_accepted_at` cuando entregan.
- [x] 5.7 Test: escribir la marca **no agrega transacciones**. Contar los despachos al executor y los
  `commit` del camino de entrega exitosa y comprobar que son los mismos que antes del cambio.
- [x] 5.8 Test: el payload canónico enviado al canal **no** contiene `channel_accepted_at`
  (D40/RN-134), y la respuesta de la API de alertas **tampoco** (D-4 del design).
- [x] 5.9 Test: el estado derivado de la alerta (`delivered` / `failed` / `pending`) no cambia por la
  existencia de la columna. En particular, una fila con `channel_accepted_at` no nulo y
  `delivered_at` nulo —que en régimen no debería existir, pero que el test construye a propósito— no
  se reporta como `delivered`.
- [x] 5.10 Test de no regresión: la cota de entregas concurrentes, su desborde en orden de llegada y
  la advertencia disparada por flanco siguen comportándose igual (D76/RN-170).

## 6. Tests del defecto 2

- [x] 6.1 Test: dos pruebas que ejecutan el lifespan corren en la misma sesión sin que ninguna falle
  por puerto ocupado, y sin que el portal compartido quede inutilizado para las siguientes.
- [x] 6.2 Test: con el puerto por defecto del servidor mTLS ocupado a propósito, la suite produce el
  mismo resultado que con el puerto libre.
- [x] 6.3 Test: una prueba que necesita un listener real obtiene un puerto efímero y lo pasa
  explícitamente; no depende del default.
- [x] 6.4 Test de guarda sobre producción: `start_mtls_server` conserva `port: int = 8443` como default
  y la invocación del lifespan no pasa `port`. **Un test que falla si alguien "arregla" la suite
  moviendo el default de producción.**
- [x] 6.5 Test: las pruebas de configuración producen el mismo resultado corridas desde un directorio
  con archivo de entorno presente que desde uno sin él.
- [x] 6.6 Test: una variable de configuración de la aplicación exportada en el proceso invocante no
  altera el resultado de una prueba que afirma el valor por defecto.
- [x] 6.7 Test de guarda: `config.py` sigue declarando `env_file=".env"`. **Un test que falla si
  alguien "arregla" la suite cambiando la configuración de la aplicación.**

## 7. Verificación integral

- [x] 7.1 Correr la suite completa de backend desde la raíz del repositorio, con el `.env` presente y
  sin bajar ningún servicio del laboratorio. Registrar el conteo. **La línea de base son las 15 fallas
  del artefacto sellado** (`tesis/cierre/evidencia/v2-eval-20260923T010103Z/suites/backend.xml`: 864
  tests, 15 fallas, 4 omitidos).
- [x] 7.2 **Clasificar cada falla que quede antes de tocarla.** Ninguna se "arregla" devolviéndole una
  variable de entorno ni liberando un puerto. Si una falla nueva aparece porque un test dependía sin
  saberlo del `.env` del desarrollador, ése es el resultado correcto: el test no estaba probando nada
  (Risks del design).
- [ ] 7.3 Correr la suite completa de backend **dos veces en órdenes distintos** (`-p no:randomly` y
  con aleatorización) y comprobar que el conteo es el mismo. El defecto del puerto es sensible al
  orden, de modo que un solo orden verde no demuestra nada.
- [x] 7.4 Correr la suite de `agent/` y la de `frontend/` y comprobar que siguen en 642/0/1 y 260/0/0.
  Esta change no toca ninguna de las dos; una diferencia sería señal de que sí.
- [ ] 7.5 Levantar el backend contra el esquema migrado y comprobar el arranque limpio: la
  recuperación de notificaciones pendientes, los dos executors de D76/RN-170 y el validador de
  dimensionamiento de D75/RN-169 siguen funcionando sin cambio.
- [ ] 7.6 Emitir una notificación real end-to-end contra un canal vivo y comprobar en la base que
  `channel_accepted_at` y `delivered_at` están los dos, en ese orden, con una diferencia que el
  operador pueda leer.

## 8. Documentación canónica

- [x] 8.1 Agregar **D77 / RN-171** al appendix "Decisiones de implementación — Abril 2026" de
  `docs/reglas_de_negocio.md`, con el formato exacto de **D76/RN-170** (`:2480` y siguientes):
  encabezado `#### D77 / RN-171: <título>`, cuerpo con **Descripción** normativa en SHALL/MUST,
  anclas a archivo y línea, evidencia medida y **Reglas afectadas**. Título propuesto: *"El instante
  de aceptación del canal se registra de forma durable y distinta de la marca de entregado"*.
- [x] 8.2 Agregar **D78 / RN-172** al mismo appendix, con el mismo formato. Título propuesto: *"La
  suite de pruebas no depende de recursos ambientales compartidos, y su aislamiento no cambia código
  de producción"*. **Dos decisiones y no una**: los dos enunciados normativos son distintos —uno
  gobierna el modelo de datos y el camino de notificación, el otro el arnés de pruebas— y fundirlos
  produciría una regla que no se puede citar para ninguno de los dos casos por separado.
- [x] 8.3 **Verificar los números antes de escribirlos.** D76/RN-170 es el máximo actual en
  `docs/reglas_de_negocio.md` y `docs/arquitectura_stack.md`, y RN-170 el máximo de RN. Re-verificar
  con una búsqueda sobre los dos archivos: si alguno creció, tomar los siguientes.
- [x] 8.4 Actualizar el párrafo introductorio del appendix (`docs/reglas_de_negocio.md:788`), que
  enumera cronológicamente qué decisiones se agregaron y cuándo, con la entrada de D77-D78
  (RN-171 a RN-172) y su fecha.
- [x] 8.5 Agregar las **dos filas** correspondientes a la tabla del appendix de
  `docs/arquitectura_stack.md`, con el formato exacto de la fila de D76 (`:2715`): una celda por
  decisión, con anclas a archivo y línea, la evidencia medida y la fecha de agregado.
- [x] 8.6 Incluir en la fila de D77 las cifras que la motivan, con su procedencia: medianas de
  `delivered_at − received_at` de **13,170 s**, **11,671 s** y **10,537 s** en los tres escenarios de
  la Batería 4 del candidato `v3.0-tesis` (`22f393d`), y la constatación de que la línea
  `notifier.n8n_sent` (`notifier.py:48`) marca el instante correcto pero no lleva identidad de alerta,
  de modo que bajo las hasta 32 entregas concurrentes de D76/RN-170 ningún join por proximidad
  temporal es una función.
- [x] 8.7 Incluir en la fila de D78 el desglose medido sobre el artefacto sellado
  (`tesis/cierre/evidencia/v2-eval-20260923T010103Z/suites/`, `candidate_tag=v3.0-tesis`,
  `candidate_commit=22f393d`): backend 864 tests, **15 fallas**, 4 omitidos — **13**
  `RuntimeError: This portal is not running` (`tests.test_notifications` 7, `tests.test_sse_alerts` 6)
  y **2** `AssertionError` de configuración heredada (`tests.core.test_notification_settings`);
  agente 642/0/1 y frontend 260/0/0. **Y el matiz, sin adornos**: la misma suite contra contenedores
  efímeros reporta 0 fallas, y eso no significa que estén corregidas — significa que ese entorno evita
  el conflicto.
- [x] 8.8 Agregar **Change 60 — `notify-accepted-at-and-test-port-isolation`** a `CHANGES.md`,
  siguiendo el formato exacto de la Change 59 (`:1220` y siguientes): línea de metadatos
  (**Capa** · **Depende de** · **Paralelizable con** · **Origen** · **Decisiones**), bloques de cita
  con el diagnóstico, la evidencia y el principio, sección **Capacidades**, línea de **Reglas**,
  supuestos abiertos si los hubiera, y bloque **Done** con criterios verificables.
- [x] 8.9 El bloque **Done** de la Change 60 debe incluir, como mínimo: existe una marca durable de
  aceptación del canal, distinta de `delivered_at`, escrita en el mismo `commit` y nunca cuando la
  cascada falla; `delivered_at` conserva su semántica y hay un test que lo demuestra; ningún test de
  la suite depende del puerto 8443 ni del `.env` del directorio de invocación; `pki.py`, `main.py` y
  `config.py` son byte-idénticos; la suite de backend pasa sin las 15 fallas de referencia y con el
  mismo conteo en dos órdenes distintos; `scripts/check_spec_integrity.py` pasa antes y después de
  archivar; y queda registrada la re-corrida completa del arnés unificado con tag nuevo y su
  resultado, **sin declarar mejora anticipada**.
- [x] 8.10 **No declarar en `CHANGES.md` ninguna cifra esperada de la re-medición.** El único número
  que puede figurar antes de medir es la línea de base (D-10 del design).

## 9. Protocolo de medición

- [x] 9.1 En `tesis/plan_medicion_cap5.md`, Batería 4 (`:200-240`), reescribir la Fuente A
  (`:222-230`) para que calcule
  `EXTRACT(EPOCH FROM (a.channel_accepted_at - e.received_at)) * 1000` y filtre
  `a.channel_accepted_at IS NOT NULL`.
- [x] 9.2 Anotar junto a ese filtro por qué es obligatorio: una ventana temporal que incluya alertas
  anteriores a la migración 022 produciría un `n` menor que el esperado, y **un `n` chico por filas
  históricas y un `n` chico por "el sistema no notificó" se ven idénticos en la planilla** — mismo
  criterio que la nota de la Batería 3 sobre el conteo de `clock_skew` (`:192-195`).
- [x] 9.3 **Corregir la Fuente B** (`:233-237`), que hoy ofrece `notify.delivered` como *"emisión
  exitosa (`alerts/service.py:154`)"*. No lo es: `notify.delivered` se emite **después** del
  `run_in_executor` de `_mark_delivered` (`service.py:432`, `:457`), de modo que marca lo mismo que
  `delivered_at`. Dejarla en pie mantendría una segunda fuente igual de equivocada, presentada como
  validación cruzada de la primera — dos errores que se confirman entre sí (D-8 del design).
- [x] 9.4 Agregar a la Batería 4 la nota que **declara la serie anterior en lugar de reemplazarla**:
  las medianas de 13,170 / 11,671 / 10,537 s **no son erróneas** — miden correctamente el intervalo
  recepción → persistencia del éxito, que bajo D76/RN-170 incluye la espera por un permiso del cupo.
  Lo erróneo fue presentarlas como si midieran lo que la Batería 4 define. Quedan nombradas, con su
  intervalo, y no se borran.
- [x] 9.5 Documentar en la Batería 4 el **error residual de captura** de D-1: la marca se toma en el
  retorno de la corrutina y no en el `raise_for_status()`, con un desfasaje del orden de microsegundos
  a un milisegundo, y la alternativa exacta está evaluada y descartada por desproporción.
- [x] 9.6 Revisar el "Riesgo a vigilar en el escenario de 100 concurrentes" (`:262-266`), que todavía
  dice que `notify_if_applicable` abre sesiones DB síncronas dentro del event loop
  (`alerts/service.py:92-172`). **Eso ya no es cierto**: D75/RN-169 lo corrigió y D76/RN-170 aisló el
  carril. Actualizarlo a lo que hoy sí distorsiona los ítems 13, 16, 19 y 22 —la espera por un permiso
  del cupo de entregas, que es exactamente lo que la marca nueva deja de absorber— o retirarlo si ya
  no aplica.
- [x] 9.7 Verificar que los ítems 11-22 y sus umbrales (P99 < 5.000 ms, ítems 20-22) siguen
  refiriéndose a la magnitud correcta ahora que la fuente cambió, y **anotar explícitamente que el
  umbral se evalúa contra el intervalo nuevo**. Un umbral heredado de una magnitud mayor evaluado
  contra una menor se aprueba solo, y eso no es una medición.

## 10. Re-medición del candidato (después de los grupos 1 a 9)

- [x] 10.1 Confirmar que los grupos 1 a 9 están completos y que la suite de backend está en el estado
  que el grupo 7 registró. **Medir sobre una implementación parcial produce un número que no
  corresponde a nada** (D-9 del design).
- [x] 10.2 Congelar el candidato nuevo: commit, tag nuevo y registro del commit exacto. El candidato
  `v3.0-tesis` (`22f393d`) queda **invalidado** por esta change y su paquete
  `tesis/cierre/evidencia/v2-eval-20260923T010103Z/` pasa a ser línea de base de comparación, no
  descripción del binario.
- [x] 10.3 Correr el arnés unificado completo `~/fim-lab/corrida_unificada.sh` con `TAG=<tag-nuevo>`.
  **No correr baterías sueltas**: el paquete vale como conjunto.
- [x] 10.4 Verificar que el arnés de suites recibe `CAND`, `CAND_TAG` y `SUITES_OUT`
  (`scripts/correr_suites_candidato.sh:22`) y que la procedencia emitida
  (`$OUT/procedencia.txt`, `:52-60`) lleva el `candidate_tag` y el `candidate_commit` del candidato
  nuevo. El defecto que ese script documenta en `:15-20` —artefactos de un candidato archivados bajo
  otro— ya ocurrió una vez y la verificación existe para que no vuelva a ocurrir.
- [x] 10.5 Verificar `initial: events=0` antes de cada repetición de la batería de resiliencia. Es la
  guarda que la Change 59 dejó escrita tras la corrección de contabilidad de `run-02`.
- [ ] 10.6 Registrar el intervalo de notificación nuevo, derivado de `channel_accepted_at`, en los tres
  escenarios. **Registrar el número que salga.** Es esperable que sea menor que 13,170 s porque mide un
  subconjunto estricto — pero *"es esperable"* no es un resultado, y esta change no existe para
  producir un número más chico sino **el número correcto** (D-10 del design).
- [x] 10.7 Registrar el conteo de fallas de la suite del candidato nuevo, con su procedencia sellada,
  contra las 15 de referencia.
- [x] 10.8 Sellar el paquete de evidencia nuevo y actualizar las referencias del capítulo de
  evaluación a las cifras nuevas, **dejando nombrada la serie anterior** con el intervalo que medía.

## 11. Integridad de specs y cierre

- [x] 11.1 Correr `python3 scripts/check_spec_integrity.py` **antes** de archivar. Exit 0 obligatorio
  (D47/RN-141).
- [x] 11.2 Verificar que las dos delta specs de esta change son `## MODIFIED Requirements` y que
  reproducen el **texto completo** del requisito que modifican, no sólo el fragmento agregado. Un
  `MODIFIED` parcial es exactamente el mecanismo que borró 48 requisitos en 9 capabilities.
- [ ] 11.3 Archivar **con el CLI** (`openspec archive`). **Nunca escribir a mano un directorio bajo
  `openspec/changes/archive/`** (D47/RN-141).
- [ ] 11.4 Correr `python3 scripts/check_spec_integrity.py` **después** de archivar. Exit 0
  obligatorio. Si reporta un requisito perdido, **no bajar el umbral ni relajar la verificación**:
  investigar el archive.
- [ ] 11.5 Verificar a mano que `openspec/specs/backend-notifications/spec.md` conserva sus 10
  requisitos y que `openspec/specs/backend-test-harness/spec.md` conserva sus 4, con el texto nuevo
  integrado y nada perdido.
