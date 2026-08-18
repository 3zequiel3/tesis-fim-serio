# Anexo — Matriz de trazabilidad: historias de usuario ↔ tests automatizados

> Elaborado el 2026-08-18 sobre la rama `devel`.
> Responde al punto "El requisito '31 de 31 historias' necesita trabajo aparte" de
> [`docs/plan_medicion_cap5.md`](plan_medicion_cap5.md) (Batería 2), opción **(b)**: matriz manual
> versionada como anexo.

## 1. Por qué existe este documento

El Capítulo 5 afirma "31 de 31 historias de usuario cubiertas". El repositorio tiene 31 historias
(`docs/historias_de_usuario.md`, US-01 … US-31) y aproximadamente 890 tests automatizados, pero
**ningún test cita una historia**: están indexados por change (C22, C31, C32…) y por regla de
negocio (RN-xx). Los conteos de la Batería 2 miden cuántos tests pasan, no qué historias cubren.

Sin una matriz, la afirmación es una aserción; con ella, es verificable. Ese es el único objetivo
de este anexo: que un lector pueda tomar cualquier fila, abrir el archivo de test citado y
comprobar por sí mismo si el criterio está o no verificado.

## 2. Método

1. Se extrajeron los criterios de aceptación de las 31 historias de `docs/historias_de_usuario.md`,
   incluidos los appendices de decisiones (C1-C11, W1-W20), que **prevalecen** sobre el texto
   previo en caso de conflicto.
2. Para cada criterio se identificó el camino de código que lo implementa (backend, agente o
   frontend).
3. Recién entonces se buscaron los tests que **assertan ese comportamiento**. No se aceptó el
   nombre de un test como evidencia: se leyó el cuerpo y sus aserciones. Varios tests cuyo nombre
   promete una cosa assertan otra, y quedan señalados en las observaciones.
4. Se usó la cadena US → RN → test como pista de búsqueda, nunca como prueba: que un test mencione
   una RN no significa que verifique la historia que esa RN sostiene.

### Criterio de clasificación

| Valor | Se asigna cuando |
|---|---|
| `completa` | **todos** los criterios sustantivos de la historia tienen al menos un test que los asserta |
| `parcial` | algunos criterios están asertados y otros no; o la única cobertura es un test unitario de un helper puro mientras la historia describe un flujo de usuario de punta a punta |
| `sin cobertura` | ningún test asserta el comportamiento que la historia describe |

Es un criterio estricto y deliberadamente exigente: una historia con nueve criterios de los cuales
ocho están asertados es `parcial`, no `completa`. Se eligió así porque el valor de este anexo está
en que sea falsable, no en que el número quede alto.

### Alcance de la evidencia

- **Backend**: 440 funciones `test_*` en `backend/tests/`.
- **Agente**: 408 funciones `test_*` en `agent/tests/`.
- **Frontend**: 43 casos `it()` en 7 archivos `*.test.ts`.

Los conteos salen de un recuento estático de definiciones (`def test_` / `it(`), no de la
colección de `pytest`/`vitest`; sirven para dimensionar, no como dato oficial de la Batería 2.

Los tests de backend corren contra SQLite en memoria en varios módulos, de modo que "se persiste en
PostgreSQL" está verificado a nivel de ORM, no contra el motor de producción.

## 3. Resumen

| Cobertura | Historias | Cuáles |
|---|---|---|
| `completa` | **0** | — |
| `parcial` | **28** | US-01, US-02, US-03, US-06, US-07, US-08, US-10, US-11, US-12, US-13, US-14, US-15, US-16, US-17, US-18, US-19, US-20, US-21, US-22, US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31 |
| `sin cobertura` | **3** | US-04, US-05, US-09 |

**Lo que el Capítulo 5 puede afirmar con esta evidencia:** que las 31 historias tienen
implementación y que 28 de ellas tienen al menos un test automatizado que asserta parte de sus
criterios de aceptación — concentrado en el backend y el agente —, pero **no** que las 31 historias
estén cubiertas, porque ninguna historia tiene todos sus criterios verificados y tres no tienen
ningún test que ejercite su comportamiento.

Tres matices que conviene declarar junto al número, porque explican la forma del resultado:

1. **El sesgo es estructural, no de esfuerzo.** La suite es densa donde el sistema es riesgoso
   (máquina de estados de eventos, HMAC, outbox transaccional, cola offline, cifrado de baseline) y
   nula donde el sistema es visual. Las historias son mayormente relatos de interfaz; los tests son
   mayormente invariantes de dominio. La brecha es la distancia entre ambos vocabularios.
2. **Cuatro historias están muy cerca de `completa`**: US-13, US-18, US-22 y US-24. En cada una
   falla un solo criterio, y en tres de esos cuatro casos el criterio no está implementado (ver §6).
3. **Varias historias fallan por implementación, no por test.** En 18 de las 31 hay al menos un
   criterio que ningún test podría verificar porque la funcionalidad no existe. Se listan aparte en
   §6 para no confundir "falta un test" con "falta la función".

## 4. Matriz

Convención de la columna **Tests**: se nombran los archivos principales y la cantidad de tests
relevantes; los identificadores `archivo::nombre_del_test` completos están en el detalle por
historia (§5), al que remite cada fila.

| US | Criterios (resumidos) | Tests | Cobertura | Observaciones |
|---|---|---|---|---|
| **US-01** Inicio de sesión | Formulario; tokens JWT 15 min / 7 días con rotación; error genérico; token en memoria; cookie `httpOnly`/`Secure`/`SameSite=Strict`; Argon2id C9; rate limit 5/15 min; scope `password_change_only` | `test_auth.py` (6), `test_c22_auth.py` (1), `core/test_rate_limit_load.py` (4) — [§5.1](#us-01) | parcial | El rate limit W5 es el criterio mejor cubierto (end-to-end + unitario). Sin test: parámetros Argon2id, atributos de la cookie, vida de los tokens, almacenamiento en memoria, formulario. El error genérico se verifica sólo por código 401, nunca por el contenido del mensaje. La cookie además **diverge**: `samesite="lax"` y `path="/"` en `auth/router.py` |
| **US-02** Cierre de sesión | Botón; limpieza de token; blacklist del `jti` en Valkey con TTL; redirección; 401 posterior | `test_auth.py` (1) — [§5.2](#us-02) | parcial | El único test de logout no verifica lo que su nombre promete: asserta `mock_valkey.setex.called` y consulta `GET /health`, que es público. El criterio central —"tokens invalidados son rechazados con 401"— **no está asertado en ningún test del repositorio** |
| **US-03** Renovación de sesión | Refresh anticipado; rotación single-use; blacklist → login; transparencia; multi-key JWT | `test_auth.py` (5), `test_c22_auth.py` (2) — [§5.3](#us-03) | parcial | La rotación single-use del refresh está bien cubierta, incluida la ventana de gracia para refresh concurrente. Sin test: el multi-key signing C8 — la rama existe en `core/security.py` pero `conftest.py:33` fija `JWT_SECRET_PREVIOUS = ""`, con lo que nunca se ejecuta — y todo el lado cliente |
| **US-04** Métricas del dashboard | Conteo por los 7 estados; léxico en minúsculas C1; carga al entrar; indicadores numéricos | `test_domain_models.py` (2, sólo el enum) — [§5.4](#us-04) | **sin cobertura** | No existe endpoint de dashboard: la agregación vive en `frontend/src/api/dashboard.ts`, que hace N llamadas a `/events?status=X&page_size=1`. Ningún test —backend ni frontend— ejercita ese camino. Lo único asertado es que el enum `EventStatus` acepta los 7 valores canónicos en minúscula, que respalda C1 pero no la historia. Además el agregado del cliente **omite `superseded`** |
| **US-05** Estado general del sistema | Pendientes sin resolver; conectividad de agentes; realce de críticos; banner rojo; banner amarillo | `test_domain_models.py` (1, sólo el enum) — [§5.5](#us-05) | **sin cobertura** | Todos los criterios se componen en el cliente. Los dos banners heredan la cobertura parcial de US-28 y la nula de US-29, siempre a nivel de servicio, nunca de UI |
| **US-06** Listado de eventos | Tabla paginada 50/página; fila con path, estado, acción, severidad, fecha y proceso causante; orden desc; excluye `superseded` | `test_c31_backend_event_correctness.py` (1), `eventFilters.test.ts` (2) — [§5.6](#us-06) | parcial | El orden `created_at DESC` y la exclusión por defecto de `superseded` están implementados y **sin ningún test**. El criterio de contenido de fila no sólo carece de test: `EventsTable.tsx` no renderiza severidad, tipo de acción ni contexto de proceso |
| **US-07** Filtrado por estado | Selector de los 7 estados; multi-selección; `superseded` excluido; toggle; actualización dinámica | `eventFilters.test.ts` (4) — [§5.7](#us-07) | parcial | Ningún test asserta la selectividad del filtro de estado. El más cercano, `test_event_severity.py::test_list_events_filters_by_severity`, envía `status=pending` sobre un fixture donde los 4 eventos son `pending`: el parámetro no discrimina nada. Los filtros `path_prefix`, `date_from` y `date_to` tampoco tienen test |
| **US-08** Detalle de un evento | Vista de detalle; campos; timestamps dobles con clock skew W13; contexto forense del proceso; enlace al padre; posición en la cadena | `test_stream_ack_durability_consumer.py` (8), `test_consumer.py` (1), `test_c31_backend_event_correctness.py` (2), `test_event_severity.py` (1), `test_event_symlink_metadata.py` (2), `test_event_ack_status_field.py` (3), `test_detector_context.py` (4) — [§5.8](#us-08) | parcial | El clock skew W13 es el criterio mejor cubierto de la historia, aunque **el límite exacto de 5 minutos nunca se prueba**: los casos usan valores claramente dentro o fuera. No existe test de `GET /events/{id}` que devuelva 200 y verifique el conjunto de campos. El contexto forense se testea al capturarlo en el agente, nunca al persistirlo ni al exponerlo |
| **US-09** Diff de un evento | Diff lado a lado/unificado; sólo texto; binarios con hashes y hex dump; detección automática; escapado W8; nunca loguear el diff W6 | `DiffViewer.test.ts` (7, helpers de un componente que ya no se monta), `test_detector_diff.py` (7, lado agente) — [§5.9](#us-09) | **sin cobertura** | El panel de diff **fue removido del detalle** (commit `9e566ed`); `EventDetail.tsx` sólo conserva un comentario explicando la remoción, y `DiffViewer.tsx` ya no se importa desde ningún módulo de la aplicación. Citar `DiffViewer.test.ts` como cobertura de esta historia sería engañoso. W6 es doblemente huérfano: `hash_before`, `hash_after` y `size_delta` no existen en ninguna parte del código |
| **US-10** Cadena de eventos | Acceso a la cadena del path; orden cronológico con marca de `superseded`; navegación; ícono de cadena rota y `parent_event_id` | `test_event_service.py` (5), `test_event_status_derivation.py` (2), `test_c31_backend_event_correctness.py` (3), `test_c22_fk_chain.py` (3), `modules/events/test_retention.py` (3) — [§5.10](#us-10) | parcial | El **modelo de datos** de la cadena está entre lo mejor cubierto del repositorio (supersesión optimista, `parent_event_id`, compactación a 10, protección por `audit_log`, carreras). La **funcionalidad de usuario** no existe: no hay endpoint que devuelva la cadena de un path, y `EventTimeline.tsx` documenta que quedó fuera de alcance (sólo muestra el padre inmediato) |
| **US-11** Aprobación de un evento | Botón; UPDATE optimista C5; `approved` + `resolved_at`/`resolved_by`; baseline con hash actual; comando firmado C7 + C11; agente rechaza firma/versión; re-cifrado W10; `event_ack` C3; warning de archivo ausente; `audit_log`; 409 + toast | `test_actions.py` (7), `test_c31_backend_event_correctness.py` (1), `test_stream_ack_durability_outbox.py` (4), `test_command_ack_consumer.py` (9), `test_commands.py` (5), `test_baseline.py` (7) — [§5.11](#us-11) | parcial | El criterio "baseline con el **hash actual** del archivo" no sólo no tiene test: `test_actions.py::test_no_get_file_hash_published` **asserta la decisión contraria** (D2: se usa `event.hash_detected`). Divergencia deliberada entre historia y diseño vigente, que conviene resolver en el documento, no en el código. No existe ningún test HTTP del router de actions (ver §5, nota transversal) |
| **US-12** Rechazo de un evento | Botón; elección `restore`/`quarantine`; modal ante baseline `absent` C10; no-op con warning; UPDATE optimista; `rejected` + campos; comando firmado C7 + C11; journal pre-acción W2; `audit_log` | `test_actions.py` (5), `test_stream_ack_durability_outbox.py` (3), `test_published_command_ack_tracking.py` (2), `test_commands.py` (5), `test_journal.py` (9), `test_baseline_restore.py` (2) — [§5.12](#us-12) | parcial | El journal pre-acción W2 tiene la mejor prueba del lote (`test_journal_written_before_filesystem_op` intercepta `os.open` y verifica que el journal ya existe). Pero **ningún test asserta que los handlers dejen el journal en `completed`/`failed`** tras ejecutar: eso se prueba sólo aislado en el gestor. Los tests de reject no verifican `resolved_at`/`resolved_by`, a diferencia de los de approve. `ruleset_version` no se incluye en estos comandos por diseño explícito → criterio no implementado |
| **US-13** Superseded automático | Nuevo evento supersede al `pending`; vínculo `parent_event_id`; no aparece en pendientes; transición validada C2; accesible por el toggle | `test_event_service.py` (7), `test_event_status_derivation.py` (5), `test_c31_backend_event_correctness.py` (2), `test_event_consumer_c11.py` (1), `test_c22_consumer.py` (1) — [§5.13](#us-13) | parcial | **La más cerca de `completa` de todo el anexo.** La lógica de dominio está sólidamente cubierta, incluidas las carreras y la resistencia a un `status` forjado por el agente. Falla un solo criterio: que el evento `superseded` no aparezca en el listado por defecto. El filtro existe en `events/router.py:85-86` y **ningún test lo ejercita** |
| **US-14** Listado de reglas | Tabla; fila con patrón, severidad y acción; leyenda del default `alert_only`; `ruleset_version` del sistema | `test_rules_service.py` (3), `test_rules_router.py` (2), `test_rules.py` (1) — [§5.14](#us-14) | parcial | Sólo el listado y su orden canónico por severidad están asertados. El `ruleset_version` global del sistema **no lo expone ningún endpoint**: lo que la UI muestra es `ruleset_version_applied` por agente, que es otra cosa |
| **US-15** Creación de regla | Formulario; glob y negación `!`; la exclusiva gana; persistencia; patrón no duplicado; `ruleset_version++` C11 + sync; `audit_log` | `test_rules_service.py` (10), `test_rules_router.py` (3), `test_ruleset_version_atomic.py` (2), `test_rules.py` (3) — [§5.15](#us-15) | parcial | La precedencia de reglas exclusivas está probada **sólo en el agente**: `rules/service.py::determine_severity_for_path` hace `fnmatch` sin tratar el prefijo `!`, de modo que la semántica de negación no existe en el cálculo de severidad del backend. La validación de patrón duplicado no está implementada (sin `unique=True` ni constraint) |
| **US-16** Edición de regla | Formulario precargado; modificar patrón/severidad/acción; persistencia; `ruleset_version++` + sync; `audit_log` | `test_rules_service.py` (2), `test_rules_router.py` (3) — [§5.16](#us-16) | parcial | **El núcleo de la historia no está asertado**: los tests de `update_rule` verifican únicamente efectos laterales (fila de auditoría y contador), nunca que los campos hayan cambiado en la fila persistida |
| **US-17** Eliminación de regla | Opción de borrar; confirmación; eliminación de la fila; `ruleset_version++` + sync; caída al default `alert_only`; `audit_log` | `test_rules_service.py` (2), `test_rules_router.py` (3), `test_rules.py` (1), `test_decision.py` (1) — [§5.17](#us-17) | parcial | Igual que US-16: ningún test verifica la ausencia de la fila tras el borrado. El criterio 5 tiene cobertura indirecta (el default `alert_only` de `RulesCache.evaluate`), no una prueba del escenario "regla borrada → el path cae al default" |
| **US-18** Sync automática de reglas | Publica `rule_sync`; firma C7 + `ruleset_version` C11; el agente verifica firma; descarta versiones menores; reemplaza caché sin reiniciar; persiste en `state.json`; comandos antes que eventos W4; `event_ack` C3 | `test_rules_service.py` (8), `test_rule_sync_outbox.py` (4), `test_c32_sse_security_fixes.py` (1), `test_rules.py` (5), `test_stability_fixes.py` (2), `test_reconnect_order.py` (7) — [§5.18](#us-18) | parcial | **Muy cerca de `completa`**: siete de ocho criterios asertados, incluido el orden de reconexión W4 y la persistencia del `ruleset_version` en `state.json`. El único que falla —`event_ack` tras `rule_sync`— no está implementado, y los tests **documentan la decisión contraria** (`test_rule_sync_persists_with_null_ack_status`). La confirmación llega en la práctica por otro canal: `ruleset_version_applied` vía heartbeat |
| **US-19** Listado de alertas | Lista ordenada por fecha desc; fila con path, severidad, acción, fecha y canal; navegación al evento | `test_sse_alerts.py` (10) — [§5.19](#us-19) | parcial | El endpoint, sus filtros y la paginación están bien cubiertos; los tres criterios *de la historia*, no. `AlertResponse` no expone `path` ni tipo de acción, la navegación al evento no está implementada, y el `ORDER BY created_at DESC` no lo asserta ningún test |
| **US-20** Alertas en tiempo real | Conexión SSE; alerta ante nuevo evento; notificación visual; reconexión automática | `test_sse_alerts.py` (12), `test_c32_sse_security_fixes.py` (4) — [§5.20](#us-20) | parcial | El backend SSE está bien cubierto: auth por query param, replay con `Last-Event-ID`, keepalive, cierre de sesión de DB y cola acotada a 100. El hueco relevante es la cadena real evento → `notify_if_applicable` → `alerts_broadcaster.publish`, que **ningún test recorre**: de `notify_if_applicable` sólo se prueban los tres casos de *skip* |
| **US-21** Estado de agentes | Lista; identificador, estado, última actividad, `ruleset_version`, `queue_size`; realce de no-ok; heartbeat 10 s / 30 s → offline / 5 min → dead + webhook / `shutdown` → draining; banner de `queue_pressure` W3 | `test_agent_mgmt.py` (5), `test_heartbeat_consumer.py` (4), `test_agent_watch_path_status.py` (2), `test_domain_models.py` (1), `test_queue.py` (4) — [§5.21](#us-21) | parcial | La máquina de estados del heartbeat (online → draining → offline@30s → dead@5min → vuelta a online) es lo mejor cubierto de las historias de agentes. Sin cobertura: el intervalo de 10 s, el webhook n8n al pasar a `dead` (no implementado), `queue_size` en la vista (no se persiste; lo que se guarda es `queue_pressure` como float) y el umbral del 80% de W3, que no existe en el código |
| **US-22** Re-scan de baseline | Botón con selección de paths; diálogo con los `pending` afectados; confirmación explícita; supersesión + comando firmado C7 con `ruleset_version++` C11; el agente verifica firma y versión; regenera baseline cifrado W10; `event_ack` C3; confirmación visual; `audit_log`; deshabilitado si `draining` | `test_agent_mgmt.py` (4), `test_published_command_ack_tracking.py` (1), `test_stream_ack_durability_outbox.py` (1), `test_agent_config.py` (5), `test_commands.py` (3), `test_baseline.py` (7) — [§5.22](#us-22) | parcial | El flujo existe de punta a punta y ese eje está bien cubierto. Tres criterios fallan por implementación: no hay selección de paths (`AgentRescanRequest` sólo tiene `force`), el comando no lleva `ruleset_version++`, y `handle_rescan_baseline` no tiene guard de versión (a diferencia de `handle_baseline_update` y `handle_update_config`). La supersesión alcanza a **todos** los pending del agente, no a los paths seleccionados |
| **US-23** Notificación externa | Webhook n8n ante `critical`/`high`; payload con contexto de proceso y timestamps; n8n como enrutador; retry 5/30/120 s; cascada SMTP → webhook → log; fila en DLQ; n8n caído no compromete la operación | `test_notifications.py` (16), `test_c31_backend_event_correctness.py` (2), `test_health_n8n_check.py` (8) — [§5.23](#us-23) | parcial | El retry con los delays exactos y la caída a DLQ son el núcleo mejor asertado (`test_notify_event_retry_3x_then_dlq` compara la secuencia real contra `RETRY_DELAYS`). El criterio "sólo `critical`/`high`" se demuestra **por exclusión** (low/medium/superseded no crean alerta), nunca por inclusión. El payload no incluye `process_pid`/`uid`/`exe`, `received_at` ni la acción tomada → criterio incumplido en el código. La entrega efectiva por SMTP y por webhook directo nunca se asserta con éxito |
| **US-24** Paths monitoreados | Lista de paths por agente; agregar; quitar; persistencia; `update_config` firmado C7 + `ruleset_version++` C11; el agente verifica y recarga en caliente; baseline scan de paths nuevos W10; `event_ack` C3; bootstrap desde YAML → autoridad en PostgreSQL; `audit_log`; deshabilitado si `draining` | `test_agent_mgmt.py` (5), `test_agent_watch_path_status.py` (3), `test_published_command_ack_tracking.py` (2), `test_agent_config.py` (6), `test_commands.py` (5), `test_stability_fixes.py` (2), `test_audit_fixes.py` (1) — [§5.24](#us-24) | parcial | La historia mejor cubierta del lado backend + agente. Advertencia metodológica: `test_agent_config.py::test_reload_watch_paths_marks_new` y `::test_reload_watch_paths_unmarks_removed` **no invocan el método que dicen probar** — reimplementan la aritmética de conjuntos dentro del propio test. La reconfiguración real de las marcas de `fanotify` no está verificada por ningún test |
| **US-25** Bulk approve/reject | Checkbox por fila y "todo en la página"; botones bulk; modal con los primeros 10 paths; elección de acción; `POST /actions/bulk-*`; locking individual C5; `succeeded[]`/`failed[]`; baseline firmado por cada aprobado; `audit_log`; resumen visual; refresco | `test_actions.py` (6) — [§5.25](#us-25) | parcial | Lo bien cubierto es exclusivamente el nivel de servicio: aislamiento transaccional por ítem y partición `succeeded`/`failed`. No existe **ninguna** prueba HTTP de los endpoints bulk. Nota de fidelidad: el contrato real no es `event_ids[]` sino `items[]` con `{event_id, version, …}`; `baseline_absent` no es razón de fallo sino un mapa en la respuesta exitosa |
| **US-26** Paginación | 50 por página; navegación numerada; input "ir a página"; `?page=N&page_size=50`; respeta los filtros activos | `test_c31_backend_event_correctness.py` (1), `test_event_router.py` (1), `eventFilters.test.ts` (3) — [§5.26](#us-26) | parcial | `test_fix04_pagination_sql` es sólido (120 eventos, valida que el `COUNT` es SQL real y no un full scan). Los criterios 2 y 3 no tienen test porque **no están implementados**: sólo hay "Anterior"/"Siguiente", sin números ni input de salto. El criterio 5 es el riesgo mayor sin cubrir: un `total` que ignorara los filtros rompería la paginación y ningún test lo detectaría |
| **US-27** Cambio obligatorio de password | Seed con el flag; scope `password_change_only`; redirect forzado; formulario con complejidad; validación de la actual; Argon2id C9; flag a `false` + tokens nuevos; bloqueo de otras rutas; re-exigencia; `audit_log` | `test_auth.py` (5), `test_c22_auth.py` (1), `test_c22_scope_gate.py` (5), `modules/users/test_user_management.py` (3) — [§5.27](#us-27) | parcial | El gate de scope en backend está bien cubierto (5 tests dedicados). Sin test: validación de la contraseña actual, reglas de complejidad (no implementadas: sólo se valida longitud ≥ 12), Argon2id, `audit_log` de `change_password`, persistencia del flag en `false` y re-exigencia tras cerrar sesión. Dos divergencias: la ruta real es `/change-password`, y el backend fuerza re-login en vez de emitir tokens nuevos |
| **US-28** Banner de degradación | Poll cada 10 s; estado de `postgres`, `valkey`, `n8n` y agentes; banner rojo con componente y timestamp; cerrable y reaparece; no bloquea; webhook ante cambio de estado | `test_notifications.py` (5), `test_health_n8n_check.py` (8) — [§5.28](#us-28) | parcial | La mitad backend está razonablemente cubierta, con dos huecos: **la porción `agents` del resultado nunca se asserta**, y `GET /health/components` como endpoint HTTP nunca se invoca en un test (todos llaman `check_components()` directamente). Dos criterios de UI ni siquiera están implementados: el banner no muestra el timestamp del último check saludable ni tiene botón de cierre |
| **US-29** Webhooks fallidos | Banner amarillo con `retry_count >= 3`; link a la vista; tabla con `event_id`, primer intento, error y `retry_count`; reintentar/descartar por fila; bulk; eliminación tras reintento exitoso; el banner desaparece; `audit_log` | `test_notifications.py` (7), `test_sse_alerts.py` (3) — [§5.29](#us-29) | parcial | La tabla `failed_notifications` **no existe**: su rol lo cumple `alerts` con `failed_at NOT NULL`, sin `payload_json`. Descartar está bien cubierto; reintentar sólo tiene tests de 404/409, **no del camino feliz**. El banner no filtra por `retry_count >= 3`, no hay endpoint bulk, la fila no se elimina tras el reintento (se marca `delivered_at`) y no hay ninguna escritura de `audit_log` en el módulo de alertas |
| **US-30** Agente en shutdown graceful | Deja de aceptar eventos; drena con timeout 30 s; heartbeat con `shutdown: true`; backend marca `draining`; indicador "Drenando N eventos"; botones deshabilitados con tooltip; pasa a `offline`/`dead` | `test_shutdown_heartbeat.py` (5), `test_stability_fixes.py` (1), `test_heartbeat_consumer.py` (1), `test_agent_mgmt.py` (1), `test_publisher.py` (1), `test_reconnect_order.py` (2) — [§5.30](#us-30) | parcial | Sólo dos criterios están genuinamente asertados: el heartbeat con `shutdown: true` y el marcado `draining`. El cese de aceptación de eventos de `fanotify` no está implementado (`set_shutdown` no afecta al detector), `_drain_then_stop(..., timeout=30.0)` **no es invocado por ningún test**, y la transición `draining → offline` está implementada pero nunca se ejercita desde ese estado |
| **US-31** Toggle de superseded | Oculto por defecto; checkbox; ícono de cadena rota y `parent_event_id`; persistencia en la URL; `GET /events` respeta el parámetro | `eventFilters.test.ts` (7) — [§5.31](#us-31) | parcial | El único criterio realmente cubierto es la persistencia en la URL, y sólo sobre `eventFilters.ts`. Además `frontend/src/api/events.ts:88-97` **duplica** la serialización de filtros en un `paramsSerializer` sin ningún test: el camino que realmente llega al backend es el no cubierto. El criterio 5 —la regla W1 del lado servidor— es el vacío más significativo |

## 5. Detalle por historia

### Nota transversal sobre el frontend

`frontend/vitest.config.ts` declara `test: { environment: 'node' }`, y `frontend/package.json` no
incluye `jsdom` ni `@testing-library/*`; tampoco hay Playwright ni Cypress. **Por construcción,
ningún criterio de renderizado puede tener test automatizado hoy.** Los 7 archivos de test del
frontend prueban exclusivamente funciones puras: `frontend/src/utils/{eventFilters, ackStatus,
actionError, actionFailed, discardedEvents, watchPathStatus}.test.ts` y
`frontend/src/components/ui/DiffViewer.test.ts`. Toda cobertura de frontend citada en este anexo es
de ese tipo, y no verifica que el componente use realmente el helper.

Esto no es una deficiencia del esfuerzo de testing sino una decisión de alcance, y explica por qué
las historias más orientadas a interfaz (US-04, US-05, US-09) quedan sin cobertura pese a estar
implementadas.

### Nota transversal sobre el router de acciones

No existe **ningún** test que atraviese `backend/app/modules/actions/router.py`. Quedan sin asertar
el mapeo `ConflictError → HTTP 409`, `AbsentConfirmationRequired → HTTP 422`, la exigencia de
`require_admin` en los cuatro endpoints y la forma de las respuestas `ActionResponse` /
`BulkResultResponse`. Afecta a US-11, US-12 y US-25.

### Nota transversal sobre aserciones débiles

Algunos tests aceptan varios códigos de respuesta como válidos y por lo tanto pasan aunque el
endpoint no funcione. No deben citarse como evidencia de comportamiento:

- `backend/tests/test_rules_router.py::test_post_rules_creates_rule_returns_201` — asserta
  `status_code in (201, 401, 422, 500)`.
- `backend/tests/test_rules_router.py::test_get_rules_returns_200_with_auth`,
  `::test_get_rule_not_found_returns_404`, `::test_put_rule_not_found_returns_404`,
  `::test_delete_rule_not_found_returns_404` — aceptan `401` como resultado válido.
- `backend/tests/test_event_router.py::test_get_event_not_found_returns_404` — asserta
  `status_code in (404, 401)`.
- `backend/tests/test_auth.py::test_scope_password_change_only_en_access_token` — la aserción está
  dentro de un `if`.
- `backend/tests/test_auth.py::test_require_full_access_bloquea_scope_password_change_only` — el
  nombre promete un bloqueo; el cuerpo asserta que `/users/change-password` devuelve 200. El bloqueo
  real lo prueban los tests de `test_c22_scope_gate.py`.

---

<a id="us-01"></a>
### 5.1 US-01: Inicio de sesión — `parcial`

| Criterio | Tests |
|---|---|
| Formulario con usuario y contraseña | SIN TEST (UI: `frontend/src/pages/Login.tsx`) |
| Credenciales válidas → par de tokens y redirección | `backend/tests/test_auth.py::test_login_exitoso_retorna_200`, `backend/tests/test_auth.py::test_login_incluye_objeto_user`. La vida de 15 min / 7 días: SIN TEST. Redirección: SIN TEST |
| Credenciales inválidas → error genérico | `backend/tests/test_auth.py::test_login_password_incorrecta_retorna_401`, `backend/tests/test_auth.py::test_login_usuario_inexistente_retorna_401` (sólo el código; el `detail` nunca se compara) |
| Access token en memoria, nunca en `localStorage` (W9) | SIN TEST |
| Refresh token como cookie `httpOnly`/`Secure`/`SameSite=Strict`/`Path=/auth/refresh` (W9) | SIN TEST |
| Argon2id `time_cost=3, memory_cost=65536, parallelism=4` (C9) | SIN TEST |
| Rate limit 5 intentos / 15 min por `(username + IP)` (W5) | `backend/tests/test_auth.py::test_rate_limit_login_6to_intento_retorna_429`, `backend/tests/test_auth.py::test_rate_limit_login_5_intentos_pasan`, `backend/tests/core/test_rate_limit_load.py::test_login_n_requests_dentro_del_bucket_no_rechazados`, `backend/tests/core/test_rate_limit_load.py::test_login_n_mas_1_request_retorna_429`, `backend/tests/core/test_rate_limit_load.py::test_login_ventana_se_resetea_en_primer_request`, `backend/tests/core/test_rate_limit_load.py::test_login_ttl_siempre_presente_tras_incrementos_count_mayor_a_1` |
| `must_change_password` → scope `password_change_only` | `backend/tests/test_auth.py::test_login_primer_admin_must_change_password_true`, `backend/tests/test_auth.py::test_scope_password_change_only_en_access_token`, `backend/tests/test_c22_auth.py::test_create_access_token_scope_password_change_only_sigue_teniendo_type_access` |

Los tests de rate limit leen `settings.rate_limit_login_attempts` en vez de fijar 5 y 900, de modo
que los valores del criterio quedan verificados sólo en tanto se respeten los defaults de
`backend/app/core/config.py:51-52`.

---

<a id="us-02"></a>
### 5.2 US-02: Cierre de sesión — `parcial`

| Criterio | Tests |
|---|---|
| Botón de logout visible | SIN TEST (UI) |
| Limpieza del access token e invalidación de la cookie | SIN TEST |
| `jti` del refresh en blacklist con TTL restante (C8) | `backend/tests/test_auth.py::test_logout_invalida_access_token` (sólo asserta `mock_valkey.setex.called`; no distingue el `jti` ni verifica el TTL) |
| Redirección al login | SIN TEST (UI) |
| Solicitudes posteriores con token invalidado → 401 | SIN TEST |

El último criterio es el corazón de la historia. El test que intenta cubrirlo consulta `GET /health`,
que es público, y su propio comentario lo admite. La comprobación de blacklist existe en
`backend/app/core/deps.py:54` y ningún test la ejercita.

---

<a id="us-03"></a>
### 5.3 US-03: Renovación automática de sesión — `parcial`

| Criterio | Tests |
|---|---|
| El frontend pide un token nuevo antes de que expire | SIN TEST (además el cliente es reactivo a 401, no proactivo) |
| El refresh rota en cada uso (C8) | `backend/tests/test_auth.py::test_refresh_valido_rota_token`, `backend/tests/test_auth.py::test_refresh_con_token_revocado_retorna_401` |
| Refresh expirado o revocado → login | `backend/tests/test_auth.py::test_refresh_con_token_revocado_retorna_401`, `backend/tests/test_auth.py::test_refresh_sin_cookie_retorna_401`, `backend/tests/test_c22_auth.py::test_refresh_token_como_bearer_retorna_401_token_type_invalid`, `backend/tests/test_c22_auth.py::test_token_sin_type_claim_retorna_401_token_type_invalid` |
| Renovación transparente | `backend/tests/test_auth.py::test_refresh_concurrente_dentro_de_gracia_reusa_la_sesion_rotada`, `backend/tests/test_auth.py::test_refresh_incluye_objeto_user` (lado servidor; el single-flight del cliente: SIN TEST) |
| Multi-key `JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS` (C8) | SIN TEST — rama muerta en la suite: `backend/tests/conftest.py:33` y ~12 módulos fijan `JWT_SECRET_PREVIOUS = ""` |

---

<a id="us-04"></a>
### 5.4 US-04: Métricas generales del dashboard — `sin cobertura`

| Criterio | Tests |
|---|---|
| Conteo de eventos por los 7 estados | SIN TEST — no existe endpoint de agregación |
| Léxico canónico en minúsculas (C1) | `backend/tests/test_domain_models.py::TestEventStatus::test_all_canonical_values`, `backend/tests/test_domain_models.py::TestEventStatus::test_rejects_uppercase` (test del enum, no del dashboard) |
| Las métricas se cargan al entrar | SIN TEST |
| Indicadores numéricos claros | SIN TEST |

El criterio 1 tampoco está implementado por completo: `EVENT_STATUSES` en `Dashboard.tsx:75-82` y la
lista `statuses` de `frontend/src/api/dashboard.ts` omiten `superseded`.

---

<a id="us-05"></a>
### 5.5 US-05: Estado general del sistema — `sin cobertura`

| Criterio | Tests |
|---|---|
| Cantidad de `pending` sin resolver | SIN TEST |
| Conectividad de agentes | SIN TEST (sólo el enum: `backend/tests/test_domain_models.py::TestAgentStatus::test_all_canonical_values`) |
| Realce de `pending` con severidad `critical`/`high` | SIN TEST |
| Banner rojo de degradación | Ver US-28 (backend parcial; banner SIN TEST) |
| Banner amarillo de notificaciones fallidas | Ver US-29 (SIN TEST) |

---

<a id="us-06"></a>
### 5.6 US-06: Listado de eventos — `parcial`

| Criterio | Tests |
|---|---|
| Tabla paginada, 50 por página por defecto | `backend/tests/test_c31_backend_event_correctness.py::test_fix04_pagination_sql` (pasa `page_size=50` explícito, no ejerce el default); `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío`. Default del backend: SIN TEST |
| Fila con path, estado, acción, severidad, fecha y proceso causante | SIN TEST — y sin implementación: `EventsTable.tsx` no renderiza severidad, acción ni contexto de proceso |
| Orden por fecha de creación descendente | SIN TEST (`events/router.py:107`) |
| El filtro default excluye `superseded` (W1) | SIN TEST en backend; cliente: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — include_superseded=false queda como undefined` |

---

<a id="us-07"></a>
### 5.7 US-07: Filtrado de eventos por estado — `parcial`

| Criterio | Tests |
|---|---|
| Selector con los 7 estados | SIN TEST — `ALL_STATUSES` en `Events.tsx:10-17` enumera 6 |
| Selección múltiple simultánea | `frontend/src/utils/eventFilters.test.ts::parseEventFilters — parsea multi-select status`, `::serializeEventFilters — serializa multi-select status como repeated params`. El filtrado SQL (`status.in_()`): SIN TEST |
| `superseded` excluido por defecto (W1) | SIN TEST en backend; cliente: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío` |
| Toggle "Mostrar superseded" | Ver US-31 |
| Actualización dinámica al filtrar | SIN TEST |

---

<a id="us-08"></a>
### 5.8 US-08: Detalle de un evento — `parcial`

| Criterio | Tests |
|---|---|
| Vista de detalle al seleccionar | `backend/tests/test_event_router.py::test_get_event_by_id_no_auth_returns_401`, `backend/tests/test_event_router.py::test_get_event_not_found_returns_404` — **no existe test de camino feliz con 200** |
| Campos: path, hash, estado, acción, severidad, fechas, resolución | `backend/tests/test_event_severity.py::test_event_out_serializes_severity`, `backend/tests/test_event_symlink_metadata.py::test_event_out_serializes_symlink_metadata`, `backend/tests/test_event_symlink_metadata.py::test_event_out_defaults_for_regular_file`, `backend/tests/test_event_status_derivation.py::test_event_out_serializes_action_failed_true`, `backend/tests/test_event_status_derivation.py::test_event_out_defaults_action_failed_false`, `backend/tests/test_event_ack_status_field.py::test_event_with_confirmed_command_exposes_ack_status`, `backend/tests/test_event_ack_status_field.py::test_event_without_confirmable_command_has_no_ack_status`, `backend/tests/test_event_ack_status_field.py::test_event_uses_most_recent_published_command`, `backend/tests/test_event_service.py::test_ingest_event_from_real_agent_payload_persists_hash_detected`, `backend/tests/test_event_service.py::test_ingest_event_from_real_file_deleted_payload_persists_empty_hash`. "Tipo de acción": SIN TEST y sin campo en el modelo |
| Timestamps dobles con clock skew de 5 min (W13) | `backend/tests/test_stream_ack_durability_consumer.py::test_detected_at_old_sent_at_recent_is_accepted`, `::test_sent_at_out_of_range_rejected`, `::test_sent_at_in_future_rejected`, `::test_sent_at_unparseable_rejected`, `::test_sent_at_naive_interpreted_as_utc`, `::test_no_sent_at_within_window_accepted`, `::test_no_sent_at_old_detected_at_rejected`, `::test_response_matrix_clock_skew_terminal_nack`; `backend/tests/test_consumer.py::test_reject_clock_skew`; `backend/tests/test_c31_backend_event_correctness.py::test_fix08_unparseable_detected_at_rejected_as_clock_skew`, `::test_fix08_naive_datetime_within_range_accepted`; `backend/tests/test_integration_transport.py::test_event_lifecycle` |
| Contexto forense del proceso (PID, UID, `exe`) | `agent/tests/test_detector_context.py::test_get_exe_returns_none_on_oserror`, `::test_get_exe_returns_path_on_success`, `::test_get_uid_returns_zero_on_oserror`, `::test_get_uid_parses_uid_from_proc_status` — sólo la captura en el agente; la persistencia y exposición: SIN TEST |
| Enlace al evento padre | `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain` (el campo se puebla); el link: SIN TEST |
| Posición en la cadena y navegación | SIN TEST — fuera de alcance según `EventTimeline.tsx:9-12` |

El valor de frontera `_CLOCK_SKEW_S = 300` no está verificado: los casos usan valores claramente
dentro (ahora) o fuera (10 min, 2 h, 6 h) de la ventana.

---

<a id="us-09"></a>
### 5.9 US-09: Visualización de diff — `sin cobertura`

Estado verificado: el panel de diff fue removido del detalle (commit `9e566ed`).
`frontend/src/pages/EventDetail.tsx:224-228` conserva sólo un comentario explicando la remoción, y
`DiffViewer.tsx` ya no se importa desde ningún módulo de la aplicación. El modelo `Event` no tiene
campo de contenido ni de diff, e `ingest_event` descarta el `diff_text` que el agente sí emite.

| Criterio | Tests |
|---|---|
| Diff lado a lado o unificado en el detalle | SIN TEST — sin implementación activa |
| Diff textual sólo para archivos de texto | `agent/tests/test_detector_diff.py::test_is_text_returns_true_for_text_file`, `::test_is_text_returns_false_for_binary`, `::test_is_text_returns_false_when_file_missing`, `::test_generate_diff_returns_unified_diff`, `::test_generate_diff_returns_none_for_binary`, `::test_generate_diff_returns_none_for_large_file`, `::test_generate_diff_returns_none_when_no_diff` — lado agente, no la UI |
| Binarios: hashes + hex dump | `frontend/src/components/ui/DiffViewer.test.ts::toHexDump — convierte texto ASCII a hex`, `::trunca a maxBytes`, `::trunca al default de 256 bytes`, `::maneja string vacío` (helper de un componente que no se monta). Comparación visual de hashes: SIN TEST |
| Detección automática texto/binario | `frontend/src/components/ui/DiffViewer.test.ts::isBinaryContent — retorna false para texto normal`, `::retorna true para strings con byte nulo`, `::retorna true para ELF header (binario real)` — sólo el predicado |
| Escapado activo; prohibido `dangerouslySetInnerHTML` (W8) | SIN TEST — no hay regla de lint que lo enforce (verificado: no aparece en `frontend/src`) |
| El diff nunca se loguea (W6) | SIN TEST — `hash_before`, `hash_after` y `size_delta` no existen en el código |

---

<a id="us-10"></a>
### 5.10 US-10: Cadena de eventos — `parcial`

| Criterio | Tests |
|---|---|
| Acceso a la cadena del path desde el detalle | SIN TEST — no existe endpoint de cadena |
| Cadena ordenada con marca de `superseded` | SIN TEST — sin implementación |
| Cada evento navegable a su detalle | SIN TEST (link al padre implementado en `EventTimeline.tsx:23-29`) |
| Ícono de cadena rota y referencia al `parent_event_id` | Render SIN TEST. Formación del vínculo: `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`, `::test_mark_superseded_success`, `::test_mark_superseded_wrong_version_returns_false`, `::test_get_pending_returns_most_recent`, `::test_get_pending_returns_none_when_no_pending`; `backend/tests/test_event_status_derivation.py::test_incoming_terminal_event_supersedes_active_pending`, `::test_persisted_terminal_event_is_never_superseded_afterward`; `backend/tests/test_c31_backend_event_correctness.py::test_fix03_race_no_pending_inserts_independent`, `::test_fix03_race_still_pending_returns_none`, `::test_fix05_compact_chain_retains_newest`; `backend/tests/test_c22_fk_chain.py::test_delete_parent_nulls_child_parent_event_id`, `::test_compact_chain_long_chain_no_integrity_error`, `::test_ingest_event_keeps_new_event_after_compaction`; `backend/tests/modules/events/test_retention.py::test_compact_chain_compacta_cadena_mayor_10`, `::test_compact_chain_no_elimina_si_10_o_menos`, `::test_compact_chain_preserva_protegidos_por_audit_log` |

Toda la cobertura listada es de la invariante de datos subyacente, no de la historia.

---

<a id="us-11"></a>
### 5.11 US-11: Aprobación de un evento `pending` — `parcial`

| Criterio | Tests |
|---|---|
| Botón "Aprobar" | SIN TEST (UI) |
| UPDATE optimista `version = :expected_version` (C5) | `backend/tests/test_actions.py::test_approve_conflict`, `backend/tests/test_actions.py::test_approve_success` |
| `approved` + `resolved_at` + `resolved_by` | `backend/tests/test_actions.py::test_approve_success` |
| Baseline con el hash **actual** del archivo | SIN TEST — y no implementado: `backend/tests/test_actions.py::test_no_get_file_hash_published` asserta la decisión contraria (D2) |
| Comando firmado con HMAC-SHA256 (C7) | `backend/tests/test_actions.py::test_baseline_update_hmac_valid`; `backend/tests/test_c31_backend_event_correctness.py::test_fix02_approve_publish_is_post_commit`; `backend/tests/test_stream_ack_durability_outbox.py::test_approve_pending_row_born_in_same_transaction`, `::test_approve_valkey_down_leaves_event_approved_and_command_pending`, `::test_approve_rollback_leaves_no_published_command_row`, `::test_approve_without_secret_reverts_and_raises` |
| `ruleset_version` monotónico (C11) | Indirecto: `backend/tests/test_ruleset_version_atomic.py::test_concurrent_increments_no_lost_update`, `::test_actions_and_rules_share_single_implementation`. El valor dentro del payload de approve no se asserta |
| El agente rechaza firma inválida | `agent/tests/test_commands.py::test_hmac_invalid_discards_command` |
| El agente descarta versión menor | `agent/tests/test_commands.py::test_baseline_update_older_version_ignored` |
| Baseline local re-cifrada AES-256-GCM (W10) | `agent/tests/test_commands.py::test_baseline_update_present_writes_encrypted`; motor: `agent/tests/test_baseline.py::test_encrypt_decrypt_roundtrip`, `::test_key_derivation_deterministic`, `::test_key_derivation_different_agents`, `::test_tampered_blob_raises`, `::test_unique_nonce_per_write`, `::test_gcm_detects_path_swap`, `::test_baseline_file_permissions` |
| Confirma con `event_ack` (C3) | Lado agente: SIN TEST para `baseline_update`. Lado backend: `backend/tests/test_command_ack_consumer.py::test_ack_ok_baseline_update_marks_acked`, `::test_ack_ok_baseline_update_reconciles_baseline_entries`, `::test_ack_ok_baseline_update_advances_ruleset_version_applied`, `::test_ack_ok_monotonic_does_not_regress`, `::test_ack_error_marks_failed_no_reconciliation`, `::test_ack_invalid_signature_rejected`, `::test_ack_repeated_is_idempotent`, `::test_ack_cross_agent_forge_rejected`, `::test_ack_spoofed_agent_id_wrong_secret_rejected`; firma del ack: `agent/tests/test_commands.py::test_publish_ack_signs_command_ack_with_hmac` |
| Warning de archivo ausente | SIN TEST (el texto real difiere del de la historia) |
| Confirmación explícita del admin | `backend/tests/test_actions.py::test_approve_absent_no_confirm` |
| Baseline registra el path como `absent` (hash null) | `backend/tests/test_actions.py::test_approve_absent_confirmed`; `agent/tests/test_commands.py::test_baseline_update_absent_writes_null_hash` |
| Creación futura del path tratada como anomalía | SIN TEST |
| Registro en `audit_log` (W18) | `backend/tests/test_actions.py::test_audit_log_on_approve` |
| HTTP 409 + toast al perder la carrera | `backend/tests/test_actions.py::test_approve_conflict` (excepción de dominio). El mapeo a 409 y el toast: SIN TEST |

---

<a id="us-12"></a>
### 5.12 US-12: Rechazo de un evento `pending` — `parcial`

| Criterio | Tests |
|---|---|
| Botón "Rechazar" | SIN TEST (UI) |
| Selección de `restore` o `quarantine` | `backend/tests/test_actions.py::test_reject_restore`, `backend/tests/test_actions.py::test_reject_quarantine` |
| Modal oculta acciones si el baseline está `absent` (C10) | SIN TEST — rama de UI eliminada en C38; el caso se resuelve del lado del servidor |
| Rechazo sobre baseline `absent` = no-op con warning | `backend/tests/test_actions.py::test_reject_absent_baseline_noop`, `backend/tests/test_stream_ack_durability_outbox.py::test_reject_baseline_absent_noop_enqueues_no_command` |
| UPDATE optimista (C5); 409 → toast | Parcial: la ruta de conflicto sólo se asserta dentro de `backend/tests/test_actions.py::test_bulk_reject_partial` y `::test_bulk_reject_rollback_isolates_failed_item` |
| `rejected` + `resolved_at` + `resolved_by` | `backend/tests/test_actions.py::test_reject_restore`, `::test_reject_quarantine` assertan el estado pero **no** `resolved_at` ni `resolved_by` |
| Comando firmado (C7) con `ruleset_version` (C11) | Firma: indirecto — `backend/tests/test_published_command_ack_tracking.py::test_enqueue_restore_file_requires_caller_commit`, `::test_enqueue_restore_file_persists_once_caller_commits`; `backend/tests/test_stream_ack_durability_outbox.py::test_reject_valkey_down_leaves_event_rejected_and_command_pending`, `::test_reject_without_secret_reverts_and_raises`; `backend/tests/test_c31_backend_event_correctness.py::test_fix02_reject_publish_is_post_commit`. `ruleset_version` no se incluye por diseño → criterio no implementado |
| Journal pre-acción (W2) | `agent/tests/test_commands.py::test_journal_written_before_filesystem_op` |
| Journal a `completed`/`failed` con detalle | Indirecto: `agent/tests/test_journal.py::test_journal_mark_completed`, `::test_journal_mark_failed`, `::test_journal_write_pending`, `::test_journal_load_pending`, `::test_journal_delete`, `::test_journal_hmac_valid_roundtrip`, `::test_journal_tampered_content_discarded`, `::test_journal_atomic_write_survives_and_rehydrates`, `::test_journal_missing_hmac_discarded`, `::test_journal_wiring_receives_correct_secret`. Ejecución y ack: `agent/tests/test_commands.py::test_restore_handler_success_publishes_ack`, `::test_restore_handler_no_baseline_publishes_error_ack`, `::test_quarantine_handler_success`, `::test_quarantine_handler_file_not_found_publishes_error_ack`; `agent/tests/test_baseline_restore.py::test_handle_restore_file_from_snapshot`, `::test_handle_restore_file_no_restorable_content` |
| Registro en `audit_log` (W18) | `backend/tests/test_actions.py::test_audit_log_on_reject` |

---

<a id="us-13"></a>
### 5.13 US-13: Superseded automático — `parcial`

| Criterio | Tests |
|---|---|
| El evento anterior pasa a `superseded` | `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`, `::test_mark_superseded_success`, `::test_mark_superseded_wrong_version_returns_false`, `::test_get_pending_returns_most_recent`, `::test_get_pending_returns_none_when_no_pending`; `backend/tests/test_event_status_derivation.py::test_incoming_terminal_event_supersedes_active_pending`, `::test_persisted_terminal_event_is_never_superseded_afterward`; `backend/tests/test_c31_backend_event_correctness.py::test_fix03_race_no_pending_inserts_independent`, `::test_fix03_race_still_pending_returns_none` |
| Vínculo por `parent_event_id` | `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`, `::test_ingest_no_pending_creates_event_without_parent`; `backend/tests/test_event_status_derivation.py::test_incoming_terminal_event_supersedes_active_pending` |
| No aparece en la lista de pendientes | **SIN TEST** — el filtro existe en `events/router.py:85-86` y ningún test lo ejercita |
| Transición validada contra la máquina de estados (C2) | `backend/tests/test_event_service.py::test_validate_valid_pending_to_superseded`, `::test_validate_valid_pending_to_approved`, `::test_validate_valid_pending_to_rejected`, `::test_validate_invalid_terminal_to_pending`, `::test_validate_invalid_pending_to_alert_only`, `::test_validate_all_terminals_have_no_out_edges`; `backend/tests/test_event_consumer_c11.py::test_consumer_invalid_transition_xacks_and_does_not_persist`; `backend/tests/test_event_status_derivation.py::test_forged_status_cannot_induce_backend_exclusive_transitions`, `::test_explicit_status_key_is_ignored` |
| Accesibles para auditoría vía el toggle | Parcial: sólo la serialización del parámetro (`frontend/src/utils/eventFilters.test.ts`) |

---

<a id="us-14"></a>
### 5.14 US-14: Listado de reglas — `parcial`

| Criterio | Tests |
|---|---|
| Tabla con las reglas existentes | `backend/tests/test_rules_service.py::TestListRules::test_empty_returns_empty_list`, `::TestListRules::test_order_critical_before_high_before_medium_before_low`, `::TestListRules::test_same_severity_ordered_by_id`; `backend/tests/test_rules_router.py::test_get_rules_returns_200_with_auth`, `::test_get_rules_list_is_sorted_by_severity` |
| Fila con patrón, severidad y acción | SIN TEST (render) |
| Indicación del default `alert_only` | SIN TEST y no implementado. Comportamiento en el agente: `agent/tests/test_rules.py::test_rules_evaluate_no_match_default` |
| `ruleset_version` actual del sistema (C11) | SIN TEST y no implementado — ningún endpoint expone el contador global |

---

<a id="us-15"></a>
### 5.15 US-15: Creación de una regla — `parcial`

| Criterio | Tests |
|---|---|
| Formulario con patrón, severidad y acción | SIN TEST (UI). Validación de enums: `backend/tests/test_rules_router.py::test_post_rules_invalid_severity_returns_422`, `::test_post_rules_invalid_action_returns_422` |
| Glob estándar y negación `!` | Glob: `backend/tests/test_rules_service.py::TestValidatePattern::test_valid_glob_star`, `::test_valid_glob_question`, `::test_valid_literal_path`, `::test_valid_bracket`, `::test_empty_string_raises`, `::test_whitespace_only_raises`; `backend/tests/test_rules_router.py::test_post_rules_empty_pattern_returns_422`. Negación en el backend: SIN TEST |
| La regla exclusiva gana sobre la inclusiva | `agent/tests/test_rules.py::test_rules_evaluate_exclusive_wins` (sólo en el agente) |
| La regla se persiste | Indirecto: `backend/tests/test_rule_sync_outbox.py::test_create_rule_with_valkey_down_persists_pending_command` |
| Patrón no duplicado | SIN TEST y no implementado |
| `ruleset_version++` (C11) + sync | `backend/tests/test_rules_service.py::TestWriteOperations::test_create_rule_increments_counter`, `::test_multiple_writes_increment_counter_each_time`; `backend/tests/test_ruleset_version_atomic.py::test_concurrent_increments_no_lost_update`, `::test_actions_and_rules_share_single_implementation` |
| `audit_log` (W18) | `backend/tests/test_rules_service.py::TestWriteOperations::test_create_rule_writes_audit_log`, `::test_audit_log_target_type_is_rule` |

---

<a id="us-16"></a>
### 5.16 US-16: Edición de una regla — `parcial`

| Criterio | Tests |
|---|---|
| Formulario precargado | SIN TEST (UI) |
| Modificación de patrón, severidad y acción | SIN TEST — los tests invocan `update_rule` con valores nuevos pero no assertan el cambio |
| Los cambios se persisten | SIN TEST. Sólo ruta de error: `backend/tests/test_rules_router.py::test_put_rule_not_found_returns_404` (aserción débil) |
| `ruleset_version++` (C11) + sync | `backend/tests/test_rules_service.py::TestWriteOperations::test_update_rule_increments_counter` |
| `audit_log` (W18) | `backend/tests/test_rules_service.py::TestWriteOperations::test_update_rule_writes_audit_log` |

Autorización sí cubierta: `backend/tests/test_rules_router.py::test_put_rule_non_admin_returns_403`,
`::test_put_rule_no_auth_returns_401`.

---

<a id="us-17"></a>
### 5.17 US-17: Eliminación de una regla — `parcial`

| Criterio | Tests |
|---|---|
| Opción de eliminar | SIN TEST (UI) |
| Confirmación previa | SIN TEST (UI) |
| La regla se elimina | SIN TEST — no se verifica la ausencia de la fila |
| `ruleset_version++` (C11) + sync | `backend/tests/test_rules_service.py::TestWriteOperations::test_delete_rule_increments_counter` |
| Los paths pasan al default `alert_only` | Indirecto: `agent/tests/test_rules.py::test_rules_evaluate_no_match_default`, `agent/tests/test_decision.py::test_decision_alert_only` |
| `audit_log` (W18) | `backend/tests/test_rules_service.py::TestWriteOperations::test_delete_rule_writes_audit_log` |

Autorización sí cubierta: `backend/tests/test_rules_router.py::test_delete_rule_non_admin_returns_403`,
`::test_delete_rule_no_auth_returns_401`.

---

<a id="us-18"></a>
### 5.18 US-18: Sincronización automática de reglas — `parcial`

| Criterio | Tests |
|---|---|
| Publica el set actualizado como `rule_sync` en `commands` | `backend/tests/test_rules_service.py::TestPublishRuleSync::test_one_agent_publishes_one_message`, `::test_no_agents_returns_zero`, `::test_two_agents_two_messages`, `::test_agent_without_secret_is_skipped`, `::test_target_agent_id_is_correct`, `::test_rules_included_in_payload`, `::test_inserts_published_command_row`; `backend/tests/test_rule_sync_outbox.py::test_create_rule_with_valkey_down_persists_pending_command`, `::test_pending_command_redelivered_when_valkey_recovers`, `::test_transient_failure_stops_batch_without_losing_pending_rows`, `::test_outbox_poller_survives_unexpected_exception`; `backend/tests/test_c32_sse_security_fixes.py::test_published_command_inserted_for_rule_sync` |
| Firma HMAC-SHA256 (C7) y `ruleset_version` (C11) | `backend/tests/test_rules_service.py::TestPublishRuleSync::test_signature_is_verifiable`; `backend/tests/test_rule_sync_outbox.py::test_pending_command_redelivered_when_valkey_recovers`. El campo `ruleset_version` dentro del JSON no se asserta directamente |
| El agente verifica firma y rechaza si es inválida | `agent/tests/test_reconnect_order.py::test_invalid_hmac_cursor_still_advances`; adyacente: `agent/tests/test_commands.py::test_hmac_invalid_discards_command` |
| Descarta versiones menores | `agent/tests/test_rules.py::test_rules_update_rejects_older_version`; `agent/tests/test_stability_fixes.py::test_rule_sync_rejects_older_version`, `::test_rule_sync_idempotent_same_version` |
| Reemplaza la caché sin reiniciar | `agent/tests/test_rules.py::test_rules_update_applies_newer_version`, `::test_rules_evaluate_inclusive_match` |
| Persiste el `ruleset_version` en `state.json` | `agent/tests/test_rules.py::test_rules_update_applies_newer_version`, `::test_rules_persist_via_state_not_direct`, `::test_save_state_preserves_rules`, `::test_cursor_persist_does_not_erase_rules` |
| Comandos pendientes antes que eventos encolados (W4) | `agent/tests/test_reconnect_order.py::test_drain_runs_after_command_flush`, `::test_cursor_loaded_on_restart`, `::test_first_start_uses_zero_cursor`, `::test_first_start_xread_from_origin`, `::test_cursor_persisted_on_each_message`, `::test_flush_timeout_continues_to_drain`, `::test_ack_listener_uses_persisted_cursor` |
| Confirma con `event_ack` (C3) | SIN TEST y no implementado — la decisión contraria está asertada en `backend/tests/test_published_command_ack_tracking.py::test_rule_sync_persists_with_null_ack_status` y `backend/tests/test_command_ack_consumer.py::test_sweep_excludes_null_ack_status_and_terminal_rows` |

---

<a id="us-19"></a>
### 5.19 US-19: Listado de alertas — `parcial`

| Criterio | Tests |
|---|---|
| Lista ordenada por fecha descendente | Existencia del listado: `backend/tests/test_sse_alerts.py::test_list_alerts_no_filters`, `::test_get_alerts_returns_all`, `::test_get_alerts_pagination`, `::test_list_alerts_pagination`, `::test_list_alerts_empty`, `::test_get_alerts_no_auth_returns_401`. El orden: SIN TEST |
| Fila con path, severidad, acción, fecha y canal | SIN TEST y parcialmente no implementado. Severidad y estado sí: `backend/tests/test_sse_alerts.py::test_list_alerts_filter_severity_critical`, `::test_get_alerts_filter_severity_high`, `::test_get_alerts_serializa_status_derivado`, `::test_get_alerts_status_delivered_gana_sobre_failed` |
| Navegación al detalle del evento | SIN TEST y no implementado |

---

<a id="us-20"></a>
### 5.20 US-20: Alertas en tiempo real — `parcial`

| Criterio | Tests |
|---|---|
| Conexión SSE | `backend/tests/test_sse_alerts.py::test_stream_alerts_valid_token_content_type`, `::test_stream_alerts_invalid_token_returns_401`, `::test_stream_alerts_no_token_returns_422`. Lado cliente: SIN TEST |
| Alerta ante nuevo evento | Por tramos: `backend/tests/test_sse_alerts.py::test_broadcaster_publish_delivers_to_all_subscribers`, `::test_broadcaster_unsubscribe_removes_queue`, `::test_broadcaster_unsubscribe_idempotent`, `::test_sse_realtime_frame_carries_event_alert`, `::test_sse_keepalive_frame_has_no_event_type`. **La cadena consumer → `notify_if_applicable` → `publish` no la recorre ningún test** |
| Notificación visual sin recargar | SIN TEST (UI) |
| Reconexión automática | Lado servidor: `backend/tests/test_sse_alerts.py::test_sse_replay_yields_missed_alerts`, `::test_sse_no_last_event_id_no_replay`, `::test_sse_replay_frames_carry_event_alert`, `::test_sse_replay_last_event_id_current_no_extra`. La reconexión del cliente: SIN TEST |
| Robustez de la conexión (C32) | `backend/tests/test_c32_sse_security_fixes.py::test_session_closed_after_replay_before_sse_loop`, `::test_session_closed_when_no_replay`, `::test_broadcaster_queue_bounded_at_100`, `::test_broadcaster_queue_full_logs_warning` |

De las ramas de `_require_admin_from_token` sólo están asertadas el JWT inválido y el token ausente;
el `jti` en blacklist, el scope `password_change_only` y el 403 `admin_required` no tienen test.

---

<a id="us-21"></a>
### 5.21 US-21: Estado de agentes — `parcial`

| Criterio | Tests |
|---|---|
| Lista de agentes registrados | `backend/tests/test_agent_mgmt.py::test_get_agents_list`, `::test_get_agent_detail`, `::test_get_agent_not_found`; `backend/tests/test_agent_watch_path_status.py::test_list_agents_exposes_watch_path_status`, `::test_get_agent_exposes_watch_path_status` |
| Identificador, estado, última actividad, `ruleset_version`, `queue_size` | Estados: `backend/tests/test_domain_models.py::TestAgentStatus::test_all_canonical_values`. Última actividad: `backend/tests/test_heartbeat_consumer.py::test_heartbeat_marks_online`, `backend/tests/test_agent_mgmt.py::test_dead_to_online_on_heartbeat`. `ruleset_version` en la vista: SIN TEST. `queue_size`: SIN TEST y no persistido |
| Realce visual de los no-ok | SIN TEST (UI) |
| Heartbeat cada 10 s | SIN TEST |
| Sin heartbeat 30 s → `offline` | `backend/tests/test_heartbeat_consumer.py::test_sweep_marks_offline_after_30s`, `::test_sweep_does_not_mark_offline_if_recent` |
| Sin heartbeat 5 min → `dead` + webhook | `backend/tests/test_agent_mgmt.py::test_dead_transition`, `::test_dead_to_online_on_heartbeat`. El webhook: SIN TEST y no implementado |
| Flag `shutdown` → `draining` | `backend/tests/test_heartbeat_consumer.py::test_heartbeat_shutdown_marks_draining` |
| Banner de `queue_pressure` (W3) | Banner SIN TEST. Persistencia y cálculo: `backend/tests/test_heartbeat_consumer.py::test_heartbeat_marks_online`; `agent/tests/test_queue.py::test_queue_pressure_zero_when_empty`, `::test_queue_pressure_positive_after_enqueue`, `::test_drop_oldest_on_limit`, `::test_drop_oldest_removes_chronologically_oldest`. El umbral del 80% no existe en el código |

---

<a id="us-22"></a>
### 5.22 US-22: Re-scan de baseline — `parcial`

| Criterio | Tests |
|---|---|
| Botón con selección de paths específicos | SIN TEST; la selección de paths no está implementada |
| Diálogo con los `pending` que serán superseded | `backend/tests/test_agent_mgmt.py::test_rescan_with_pending_no_force` (asserta el conteo y que no se publica nada). El diálogo: SIN TEST |
| Confirmación explícita | `backend/tests/test_agent_mgmt.py::test_rescan_with_pending_no_force` |
| Supersesión + comando firmado (C7) con `ruleset_version++` (C11) | `backend/tests/test_agent_mgmt.py::test_rescan_with_pending_force`, `::test_rescan_no_pending_succeeds`; `backend/tests/test_published_command_ack_tracking.py::test_enqueue_rescan_baseline_creates_pending_command`; `backend/tests/test_stream_ack_durability_outbox.py::test_rescan_without_secret_reverts_and_raises`. Verificación de la firma del payload: SIN TEST. `ruleset_version++`: no implementado |
| El agente verifica firma y versión | Firma: `agent/tests/test_commands.py::test_hmac_invalid_discards_command`; ruteo: `agent/tests/test_agent_config.py::test_dispatch_routes_rescan_baseline`. Guard de versión: no implementado |
| Regenera el baseline cifrado (W10) | `agent/tests/test_agent_config.py::test_rescan_baseline_handler_calls_run_scan`, `::test_run_scan_creates_baseline_entries`, `::test_run_scan_skips_nonexistent_path`; cifrado: `agent/tests/test_baseline.py::test_encrypt_decrypt_roundtrip`, `::test_key_derivation_deterministic`, `::test_key_derivation_different_agents`, `::test_unique_nonce_per_write`, `::test_tampered_blob_raises`, `::test_gcm_detects_path_swap`, `::test_baseline_file_permissions` |
| Confirma con `event_ack` (C3) | `agent/tests/test_agent_config.py::test_rescan_baseline_handler_publishes_ack`; `agent/tests/test_commands.py::test_publish_ack_signs_command_ack_with_hmac`, `::test_publish_ack_logs_error_without_shared_secret` |
| Confirmación visual del envío | SIN TEST (UI) |
| `audit_log` (W18) | `backend/tests/test_agent_mgmt.py::test_audit_log_on_rescan` |
| Botón deshabilitado si el agente está `draining` | SIN TEST (UI) |

---

<a id="us-23"></a>
### 5.23 US-23: Notificación externa ante eventos críticos — `parcial`

| Criterio | Tests |
|---|---|
| Webhook ante `critical`/`high` | Por exclusión: `backend/tests/test_notifications.py::test_notify_skip_low_severity`, `::test_notify_skip_medium_severity`, `::test_notify_skip_superseded`. Severidad: `::test_determine_severity_critical`, `::test_determine_severity_high_over_low`, `::test_determine_severity_no_match`, `::test_determine_severity_no_rules`. Envío dado un `Alert`: `::test_notify_event_delivers_on_first_attempt`. El disparo positivo de `notify_if_applicable`: SIN TEST |
| Payload con `event_id`, path, severidad, acción, contexto de proceso y timestamps | SIN TEST y no implementado: `_build_payload` no incluye `process_pid`/`uid`/`exe`, `received_at` ni la acción tomada |
| n8n limitado a enrutador | SIN TEST dedicado (sostenido por construcción) |
| n8n reencamina por el canal configurado | Fuera del sistema |
| Retry con delays 5 s / 30 s / 120 s (W11) | `backend/tests/test_notifications.py::test_notify_event_retry_3x_then_dlq` (compara la secuencia real contra `RETRY_DELAYS`) |
| Cascada SMTP → webhook directo → log crítico | Parcial: `backend/tests/test_notifications.py::test_send_smtp_skipped_when_no_host`, `::test_send_webhook_fallback_skipped_when_no_url`, `::test_send_n8n_skipped_when_no_url`, `::test_send_n8n_success`, `::test_send_n8n_failure`, `::test_send_log_only_always_succeeds`, `::test_log_only_no_entrega_si_hay_primarios_configurados`; `backend/tests/test_c31_backend_event_correctness.py::test_fix01_no_primaries_log_only_delivers`. **La entrega efectiva por SMTP o por webhook directo nunca se asserta con éxito** |
| Fila persistida con `last_error`, `failed_at`, `retry_count` | `backend/tests/test_notifications.py::test_notify_event_retry_3x_then_dlq`; `backend/tests/test_c31_backend_event_correctness.py::test_fix01_primary_fails_dlq_activated`. `payload_json` no se persiste |
| La caída de n8n no compromete la operación | Indirecto: `::test_send_n8n_failure`, `::test_notify_event_retry_3x_then_dlq`, `::test_log_only_no_entrega_si_hay_primarios_configurados` |

---

<a id="us-24"></a>
### 5.24 US-24: Gestión de paths monitoreados — `parcial`

| Criterio | Tests |
|---|---|
| Lista de paths por agente | `backend/tests/test_agent_mgmt.py::test_get_agents_list`, `::test_get_agent_detail`; `backend/tests/test_agent_watch_path_status.py::test_list_agents_exposes_watch_path_status`, `::test_get_agent_exposes_watch_path_status`, `::test_agent_that_never_reported_has_null_status_map`. Render: SIN TEST |
| Agregar un path | UI SIN TEST; efecto: `backend/tests/test_agent_mgmt.py::test_agent_config_updates_watch_paths` |
| Quitar un path | UI SIN TEST; mismo test (replace-all) |
| Persistencia de la configuración | `backend/tests/test_agent_mgmt.py::test_agent_config_updates_watch_paths`, `::test_agent_config_not_found` |
| `update_config` firmado (C7) con `ruleset_version++` (C11) | `backend/tests/test_agent_mgmt.py::test_agent_config_updates_watch_paths`, `::test_agent_config_hmac_valid`; `backend/tests/test_published_command_ack_tracking.py::test_enqueue_update_config_creates_pending_command_without_advancing_version`; `backend/tests/test_stream_ack_durability_outbox.py::test_update_config_without_secret_reverts_and_raises`. El incremento efectivo del contador: SIN TEST |
| El agente verifica firma y versión y recarga en caliente | `agent/tests/test_agent_config.py::test_dispatch_routes_update_config`, `::test_update_config_handler_reloads_detector`; `agent/tests/test_commands.py::test_hmac_invalid_discards_command`, `::test_update_config_preflight_rerun_does_not_block_reload`; `agent/tests/test_audit_fixes.py::test_update_config_stale_version_ignored` |
| Baseline scan de paths nuevos cifrado (W10) | `agent/tests/test_agent_config.py::test_update_config_handler_reloads_detector` (asserta `run_scan` sólo con el path nuevo), `::test_run_scan_creates_baseline_entries`; cifrado: `agent/tests/test_baseline.py::test_encrypt_decrypt_roundtrip`, `::test_unique_nonce_per_write`, `::test_tampered_blob_raises`, `::test_key_derivation_deterministic`, `::test_gcm_detects_path_swap` |
| Confirma con `event_ack` (C3) | `agent/tests/test_agent_config.py::test_update_config_handler_publishes_ack`, `::test_update_config_updates_state_ruleset_version`; `agent/tests/test_commands.py::test_update_config_without_registry_still_works`, `::test_update_config_write_failure_marks_registry_and_logs_error`. El avance de `ruleset_version_applied` en el backend ante este ack: SIN TEST |
| Bootstrap desde YAML; autoridad en PostgreSQL | `agent/tests/test_stability_fixes.py::test_update_config_writes_to_loaded_path`, `::test_update_config_falls_back_to_default_path`; `agent/tests/test_commands.py::test_update_config_missing_file_is_logged_and_marks_registry_false`, `::test_update_config_successful_write_clears_degraded_persistence_state`, `::test_update_config_reruns_preflight_and_updates_registry`. La reconciliación al arrancar: SIN TEST |
| `audit_log` (W18) | `backend/tests/test_agent_mgmt.py::test_audit_log_on_config`, `::test_audit_log_detail_is_valid_json_with_quotes_and_backslashes` |
| Botones deshabilitados si el agente está `draining` | SIN TEST; implementación incompleta (el botón "Guardar paths" no se deshabilita) |

**Advertencia metodológica.** `agent/tests/test_detector_reload.py` prueba `FanotifyDetector.reload_paths`,
que es un método distinto del que invoca `handle_update_config` (`reload_watch_paths`). Y
`agent/tests/test_agent_config.py::test_reload_watch_paths_marks_new` y
`::test_reload_watch_paths_unmarks_removed` **no invocan el método que dicen probar**: reimplementan
la aritmética de conjuntos dentro del propio test y assertan sobre variables locales. La
reconfiguración real de las marcas de `fanotify` no está verificada por ningún test.

---

<a id="us-25"></a>
### 5.25 US-25: Bulk approve/reject — `parcial`

| Criterio | Tests |
|---|---|
| Checkbox por fila y "seleccionar todo en la página" | SIN TEST (UI) |
| Botones bulk al seleccionar ≥ 1 | SIN TEST (UI) |
| Modal con cantidad y primeros 10 paths | SIN TEST (UI) |
| Elección de acción para el rechazo bulk | SIN TEST (UI) |
| `POST /actions/bulk-approve` / `bulk-reject` | SIN TEST — no hay prueba HTTP de estos endpoints |
| Optimistic locking individual (C5) | `backend/tests/test_actions.py::test_bulk_approve_partial`, `::test_bulk_reject_partial`, `::test_bulk_approve_rollback_isolates_failed_item`, `::test_bulk_reject_rollback_isolates_failed_item` |
| `succeeded[]` y `failed[]` con razón | `backend/tests/test_actions.py::test_bulk_approve_partial`, `::test_bulk_reject_partial`, `::test_bulk_approve_rollback_isolates_failed_item`, `::test_bulk_reject_rollback_isolates_failed_item`. Sin test: `absent_confirmation_required` |
| Baseline firmado por cada aprobado (C7, C11) | Indirecto: `backend/tests/test_actions.py::test_baseline_update_hmac_valid`; `backend/tests/test_ruleset_version_atomic.py::test_concurrent_increments_no_lost_update` |
| `audit_log` por operación exitosa (W18) | Indirecto: `backend/tests/test_actions.py::test_audit_log_on_approve`, `::test_audit_log_on_reject` (ruta unitaria, no el camino bulk) |
| Resumen visual con detalle expandible | SIN TEST; implementado sólo como toast agregado, sin detalle por evento |
| Refresco automático de la tabla | SIN TEST (UI) |

---

<a id="us-26"></a>
### 5.26 US-26: Paginación de eventos — `parcial`

| Criterio | Tests |
|---|---|
| 50 eventos por página por defecto | `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío`. El default del backend: SIN TEST |
| Navegación numerada | SIN TEST y no implementado |
| Input "ir a página" con validación | SIN TEST y no implementado |
| `GET /events?page=N&page_size=50` | `backend/tests/test_c31_backend_event_correctness.py::test_fix04_pagination_sql`; `backend/tests/test_event_router.py::test_list_events_returns_200_with_auth`; `frontend/src/utils/eventFilters.test.ts::serializeEventFilters — omite page cuando es 1 (default)`, `::incluye page cuando es mayor a 1` |
| La paginación respeta los filtros activos | SIN TEST directo. Indirecto y sólo para severidad: `backend/tests/test_event_severity.py::test_list_events_filters_by_severity` |

---

<a id="us-27"></a>
### 5.27 US-27: Primer login con cambio obligatorio de password — `parcial`

| Criterio | Tests |
|---|---|
| El seed crea el admin con `must_change_password: true` | Indirecto: `backend/tests/test_auth.py::test_login_primer_admin_must_change_password_true`, `::test_login_incluye_objeto_user`. Los tests de seed (`backend/tests/modules/users/test_user_management.py::test_seed_admin_usa_admin_email_configurado`, `::test_seed_admin_usa_default_cuando_no_hay_admin_email`, `::test_seed_admin_idempotente_con_admin_existente`) sólo assertan email e idempotencia |
| Tokens con scope `password_change_only` | `backend/tests/test_auth.py::test_scope_password_change_only_en_access_token`, `::test_login_primer_admin_must_change_password_true`; `backend/tests/test_c22_auth.py::test_create_access_token_scope_password_change_only_sigue_teniendo_type_access` |
| Redirect forzado al formulario | SIN TEST (la ruta real es `/change-password`) |
| Formulario con password actual, complejidad y confirmación | SIN TEST y no implementado (sólo longitud ≥ 12) |
| El backend valida la actual y la complejidad | Longitud: `backend/tests/test_auth.py::test_change_password_short_retorna_422`. La validación de `current_password`: SIN TEST |
| Argon2id (C9) | SIN TEST |
| Flag a `false` y tokens nuevos | Indirecto vía `backend/tests/modules/users/test_user_management.py` (`::test_admin_puede_listar_usuarios`, `::test_admin_crea_usuario_201_y_audit_log`, `::test_post_users_email_duplicado_retorna_409`, `::test_post_users_password_corto_retorna_422`, `::test_post_users_email_invalido_retorna_422`). El backend fuerza re-login en vez de emitir tokens nuevos |
| Bloqueo de otras rutas | `backend/tests/test_c22_scope_gate.py::test_get_events_scope_password_change_only_retorna_403`, `::test_get_event_by_id_scope_password_change_only_retorna_403`, `::test_get_rules_scope_password_change_only_retorna_403`, `::test_get_rule_by_id_scope_password_change_only_retorna_403`, `::test_get_events_full_access_token_no_recibe_403_por_scope`; `backend/tests/test_auth.py::test_change_password_con_scope_password_change_only` |
| Re-exigencia si cierra sin completar | SIN TEST |
| `audit_log` (W18) | SIN TEST — no hay aserciones sobre filas `login`, `logout` ni `change_password` |

---

<a id="us-28"></a>
### 5.28 US-28: Banner de degradación del sistema — `parcial`

| Criterio | Tests |
|---|---|
| Poll de `GET /health/components` cada 10 s | SIN TEST |
| Estado de `postgres`, `valkey`, `n8n` y agentes | `backend/tests/test_notifications.py::test_health_all_ok`, `::test_health_valkey_down`, `::test_health_n8n_degraded_when_not_configured`; `backend/tests/test_health_n8n_check.py::test_n8n_ok_on_200_head`, `::test_n8n_down_on_500`, `::test_n8n_fallback_to_get_when_head_returns_404`, `::test_n8n_fallback_to_get_when_head_returns_405`, `::test_n8n_down_on_403_no_fallback`, `::test_n8n_fallback_to_get_still_fails`, `::test_n8n_fallback_to_get_on_connection_error`, `::test_n8n_degraded_when_not_configured`. **La porción `agents` nunca se asserta** |
| Banner rojo con componente y timestamp | SIN TEST; el timestamp no está implementado |
| Cerrable y reaparece en el siguiente poll | SIN TEST y no implementado |
| No bloquea la UI | SIN TEST |
| Webhook n8n ante cambio de estado | `backend/tests/test_notifications.py::test_health_state_change_triggers_webhook`, `::test_health_no_webhook_on_first_call` |

`GET /health/components` como endpoint HTTP nunca se invoca en un test: todos llaman
`check_components()` directamente. Los tests de `backend/tests/test_health.py` apuntan a `GET /health`
(liveness simple), no a `/health/components`.

---

<a id="us-29"></a>
### 5.29 US-29: Visualización y reintento de webhooks fallidos — `parcial`

| Criterio | Tests |
|---|---|
| Banner amarillo con `retry_count >= 3` | SIN TEST; el banner no filtra por `retry_count`. Endpoint que lo alimenta: `backend/tests/test_sse_alerts.py::test_get_alerts_filter_status_failed`, `::test_list_alerts_filter_status_failed` |
| Link a la vista de fallidas | SIN TEST (apunta a `/alerts`, no a `/notifications/failed`) |
| Tabla con `event_id`, primer intento, error y `retry_count` | `backend/tests/test_notifications.py::test_get_failed_alerts_returns_only_failed`, `::test_get_failed_alerts_empty`; `backend/tests/test_sse_alerts.py::test_get_failed_alerts_serializa_status`. Los campos `last_error`, `retry_count` y `failed_at` en la respuesta HTTP: SIN TEST |
| Reintentar / Descartar por fila | Descartar: `backend/tests/test_notifications.py::test_delete_alert_204`, `::test_delete_alert_404_if_not_found`, `::test_delete_alert_service`. Reintentar: sólo errores — `::test_retry_alert_already_delivered`, `::test_retry_alert_not_found`, `::test_post_retry_alert_409_if_delivered`, `::test_post_retry_alert_404_if_not_found`. **El camino feliz del reintento: SIN TEST** |
| Bulk "Reintentar todos" | SIN TEST y sin endpoint (la UI itera reintentos individuales) |
| La fila se elimina tras un reintento exitoso | SIN TEST y no implementado así (se marca `delivered_at`) |
| El banner desaparece con la tabla vacía | SIN TEST |
| `audit_log` (W18) | SIN TEST y no implementado |

La tabla `failed_notifications` no existe: su rol lo cumple `alerts` con `failed_at NOT NULL` y
`delivered_at IS NULL`, sin columna de payload.

---

<a id="us-30"></a>
### 5.30 US-30: Indicador de agente en shutdown graceful — `parcial`

| Criterio | Tests |
|---|---|
| Ante `SIGTERM` deja de aceptar eventos de `fanotify` | SIN TEST y no implementado (`set_shutdown` no afecta al detector) |
| Drena la cola con timeout de 30 s | SIN TEST — `_drain_then_stop(..., timeout=30.0)` no es invocado por ningún test. Mecánica genérica: `agent/tests/test_publisher.py::test_drain_queue_publishes_in_fifo_order`; `agent/tests/test_reconnect_order.py::test_drain_runs_after_command_flush`, `::test_flush_timeout_continues_to_drain` |
| Heartbeats con `shutdown: true` | `agent/tests/test_shutdown_heartbeat.py::test_shutdown_flag_set_on_sigterm`, `::test_publisher_set_shutdown_changes_property`, `::test_heartbeat_reads_publisher_shutdown`, `::test_heartbeat_fallback_to_shutdown_flag_when_no_publisher`, `::test_heartbeat_publisher_beats_shutdown_flag`; `agent/tests/test_stability_fixes.py::test_shutdown_handler_safe_before_queue_created` |
| El backend marca `draining` | `backend/tests/test_heartbeat_consumer.py::test_heartbeat_shutdown_marks_draining` |
| Indicador "Drenando N eventos" | SIN TEST y no implementado |
| Botones deshabilitados con tooltip | SIN TEST (implementado con otro texto) |
| Pasa a `offline` o `dead` tras el drenaje | `draining → offline`: SIN TEST. `offline → dead`: `backend/tests/test_agent_mgmt.py::test_dead_transition` |

---

<a id="us-31"></a>
### 5.31 US-31: Toggle para mostrar eventos superseded — `parcial`

| Criterio | Tests |
|---|---|
| El filtro oculta `superseded` por defecto | SIN TEST en backend; cliente: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío`, `::include_superseded=false queda como undefined` |
| Checkbox "Mostrar superseded" | SIN TEST |
| Ícono de cadena rota y `parent_event_id` visible | SIN TEST |
| Persistencia en la URL | `frontend/src/utils/eventFilters.test.ts::parseEventFilters — parsea include_superseded=true`, `::serializeEventFilters — serializa include_superseded=true`, `::omite include_superseded cuando es false/undefined`, `::round-trip parse/serialize — preserva filtros complejos en ida y vuelta`, `::filtros vacíos round-trip produce URLSearchParams vacío` |
| `GET /events` respeta el parámetro | SIN TEST — `test_fix04_pagination_sql` lo envía, pero los 120 eventos del fixture son `pending`: el flag no cambia el resultado y su efecto no se asserta |

---

## 6. Criterios sin test porque no están implementados

Distinguirlos importa: cerrarlos requiere desarrollo, no sólo escribir un test. La lista siguiente
salió del rastreo de código, no del texto de las historias.

| Historia | Criterio | Estado real |
|---|---|---|
| US-01, US-02, US-03 | Cookie de refresh `SameSite=Strict` + `Path=/auth/refresh` | Implementado como `samesite="lax"`, `path="/"` |
| US-04 | Conteo del estado `superseded` en el dashboard | `EVENT_STATUSES` omite `superseded` |
| US-06 | Fila con severidad, tipo de acción y proceso causante | `EventsTable.tsx` no los renderiza |
| US-07 | Selector con los 7 estados | `ALL_STATUSES` enumera 6 |
| US-08 | "Tipo de acción" del evento | No existe el campo en `Event` ni en `EventOut` |
| US-08, US-10 | Posición en la cadena y navegación | Fuera de alcance declarado; sólo se muestra el padre inmediato |
| US-09 | Panel de diff en el detalle | Removido (commit `9e566ed`); `DiffViewer.tsx` es código muerto |
| US-09 | `hash_before`, `hash_after`, `size_delta` (W6) | No existen en el código |
| US-10 | Endpoint de cadena de eventos por path | No existe |
| US-11 | Baseline con el hash actual del filesystem | Decisión D2 en contra: se usa `event.hash_detected` |
| US-12 | `ruleset_version` en `restore_file` / `quarantine_file` | Excluido por diseño |
| US-14 | `ruleset_version` global del sistema expuesto | Ningún endpoint lo expone |
| US-15 | Validación de patrón duplicado | Sin `unique=True` ni constraint |
| US-15 | Precedencia de la negación `!` en el backend | `determine_severity_for_path` usa `fnmatch` sin tratar `!` |
| US-18 | `event_ack` tras `rule_sync` | No implementado; `ack_status` queda NULL a propósito |
| US-19 | `path` y tipo de acción en `AlertResponse`; link al evento | No implementados |
| US-21 | `queue_size` del agente | Se envía en el heartbeat pero no se persiste ni se expone |
| US-21 | Webhook n8n al pasar un agente a `dead` | `_sweep_offline` sólo cambia el estado |
| US-21 | Umbral del 80% para `queue_pressure` (W3) | Se reporta un float continuo; el umbral no existe |
| US-22 | Selección de paths para el re-scan | `AgentRescanRequest` sólo tiene `force` |
| US-22 | `ruleset_version++` en `rescan_baseline` y guard en el agente | No implementados |
| US-23 | Contexto de proceso, `received_at` y acción en el payload del webhook | `_build_payload` no los incluye |
| US-25 | Detalle expandible del resumen bulk | Sólo un toast agregado |
| US-26 | Navegación numerada e input "ir a página" | Sólo "Anterior"/"Siguiente" |
| US-27 | Reglas de complejidad de la contraseña | Sólo se valida longitud ≥ 12 |
| US-27 | `audit_log` de `login` / `logout` / `change_password` | La llamada existe para `change_password`; no hay aserciones ni filas verificadas para login/logout |
| US-28 | Timestamp del último check saludable y cierre manual del banner | No implementados |
| US-29 | Tabla `failed_notifications` con `payload_json` | Su rol lo cumple `alerts`, sin payload |
| US-29 | Umbral `retry_count >= 3` en el banner; bulk retry; `audit_log` | No implementados |
| US-30 | Cese de aceptación de eventos ante `SIGTERM`; "Drenando N eventos" | No implementados |

## 7. Brechas ordenadas por costo de cierre

De más barata a más cara. El costo estimado es de esfuerzo de escritura de test, asumiendo la
infraestructura existente.

### Nivel 1 — un test cada una, infraestructura ya disponible (alto rendimiento por unidad de esfuerzo)

1. **`GET /events` y el filtro de `superseded`.** Crear un evento `superseded` y comprobar que no
   aparece por defecto y sí con `include_superseded=true`. Un solo test cierra el criterio faltante
   de **US-13** (la lleva a `completa`) y el criterio central de **US-31**, y cubre criterios de
   **US-06** y **US-07**.
2. **Orden y default de paginación.** Insertar eventos con `created_at` distintos y verificar el
   orden descendente; llamar a `GET /events` sin `page_size` y verificar que devuelve 50. Cierra
   criterios de **US-06** y **US-26**.
3. **La paginación respeta los filtros.** Verificar que `total` refleja el filtro aplicado para
   estado, `path_prefix` y fechas. Es el riesgo silencioso más grande de **US-26**.
4. **`GET /events/{id}` camino feliz.** Un test con 200 que asserte el conjunto de campos, incluidos
   `process_pid` / `process_uid` / `process_exe`. Cierra el criterio principal de **US-08**.
5. **`update_rule` y `delete_rule` verifican su efecto.** Releer la fila tras editar y comprobar su
   ausencia tras borrar. Cierra el núcleo de **US-16** y **US-17**, hoy asertado sólo por sus
   efectos laterales.
6. **`reject` asserta `resolved_at` y `resolved_by`.** Dos líneas en tests que ya existen. **US-12**.
7. **Camino feliz del reintento de notificación.** Que `retry_alert` resetee `failed_at`,
   `last_error` y `retry_count` y dispare la cascada. **US-29**.
8. **`draining → offline` en el barrido.** Partir del estado `draining` en lugar de `online`.
   **US-30**.
9. **Mensaje de error genérico en login.** Comparar que el `detail` de "password incorrecta" y
   "usuario inexistente" es idéntico. **US-01**.
10. **Límite de frontera del clock skew.** Casos a 299 s y 301 s para fijar `_CLOCK_SKEW_S = 300`.
    **US-08**.

### Nivel 2 — un archivo de tests nuevo, sin cambios de infraestructura

11. **Tests HTTP del router de acciones.** `ConflictError → 409`, `AbsentConfirmationRequired → 422`,
    `require_admin` en los cuatro endpoints, forma de `ActionResponse` y `BulkResultResponse`, y los
    endpoints bulk con `items[]`. Cierra el hueco transversal de **US-11**, **US-12** y **US-25**.
12. **Camino positivo de `notify_if_applicable`.** Que un evento `critical`/`high` cree la `Alert`, la
    publique al broadcaster y dispare el envío, más la forma del payload. Cierra el criterio
    demostrado-sólo-por-exclusión de **US-23** y el eslabón faltante de **US-20**.
13. **Entrega efectiva por SMTP y por webhook directo.** Hoy la cascada sólo se prueba en sus ramas
    de "no configurado". **US-23**.
14. **Porción `agents` de `check_components` y el endpoint HTTP `/health/components`.** **US-28**,
    con efecto sobre **US-05** y **US-21**.
15. **Blacklist de tokens post-logout.** Un endpoint autenticado real (no `GET /health`) que devuelva
    401 tras el logout, y el TTL de la entrada de blacklist. Cierra el criterio central de **US-02**.
16. **Argon2id, atributos de la cookie y vida de los tokens.** Verificar el prefijo `$argon2id$` y los
    parámetros C9, el `Set-Cookie` emitido y el `exp` de los tokens. **US-01**. Nota: la cookie
    fallará contra el criterio tal como está escrito; hay que decidir si se corrige el código o el
    documento.
17. **Multi-key JWT (C8).** Requiere dejar de fijar `JWT_SECRET_PREVIOUS = ""` en `conftest.py` para
    un caso específico. **US-03**.
18. **Reconfiguración real de las marcas de `fanotify`.** Reemplazar los dos tests que reimplementan
    la aritmética de conjuntos por uno que invoque `reload_watch_paths` y verifique
    `FAN_MARK_ADD` / `FAN_MARK_REMOVE`. **US-24**.
19. **Ciclo de vida del journal integrado con los handlers.** Que `handle_restore_file` y
    `handle_quarantine_file` dejen el journal en `completed` o `failed`. **US-12**.
20. **`event_ack` de `baseline_update` del lado agente** y avance de `ruleset_version_applied` ante el
    ack de `update_config`. **US-11**, **US-24**.

### Nivel 3 — requiere infraestructura nueva

21. **Tests de render del frontend.** Agregar `jsdom` y `@testing-library/react` a
    `frontend/package.json` y cambiar `environment` en `vitest.config.ts`. Es la inversión de mayor
    rendimiento del anexo: desbloquea criterios en **28 de las 31 historias** y es la única vía para
    que **US-04**, **US-05** y **US-09** dejen de estar en `sin cobertura`. Un primer lote razonable:
    `Login`, `Dashboard`, `SystemBanner`, `EventsTable` (selección bulk y toggle de superseded),
    `RejectModal` y `AgentCard` (estado `draining`).
22. **Tests contra PostgreSQL real.** Varios módulos usan SQLite en memoria; las afirmaciones sobre
    persistencia son a nivel de ORM. Afecta la fuerza probatoria de todas las historias con
    persistencia, no su clasificación.

### Nivel 4 — requiere decidir antes de codificar

23. **Divergencias historia ↔ implementación.** Antes de escribir un test hay que resolver cuál de
    los dos textos manda, y asentarlo en el appendix de decisiones del documento canónico
    correspondiente. Los casos son: el hash del baseline en approve (US-11 vs. D2), los atributos de
    la cookie de refresh (US-01/W9), el `event_ack` de `rule_sync` (US-18 vs. la decisión de
    `ack_status` NULL), la re-emisión de tokens tras el cambio de password (US-27), la tabla
    `failed_notifications` (US-29) y el `ruleset_version` en los comandos de acción correctiva
    (US-12) y de re-scan (US-22).

---

## 8. Reproducción

Este anexo se construyó leyendo el código; no depende de una corrida. Para verificar cualquier fila:

```bash
# Un test puntual del backend
pytest backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain -v

# Un test puntual del agente
pytest agent/tests/test_commands.py::test_journal_written_before_filesystem_op -v

# Los tests puros del frontend
cd frontend && pnpm test
```

Si en el futuro se adopta la opción (a) del plan de medición (`@pytest.mark.us("US-07")`), esta
matriz sirve como fuente para el marcado inicial y como control cruzado del resultado.
