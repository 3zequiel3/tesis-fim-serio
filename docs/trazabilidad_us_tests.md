# Anexo — Matriz de trazabilidad: historias de usuario ↔ tests automatizados

> Elaborado el 2026-08-18 sobre la rama `devel`. **Revisado el 2026-08-19** tras los commits
> `faf7771` (backend, +45 tests) y `cff86fb` (frontend, infraestructura de componentes).
> Responde al punto "El requisito '31 de 31 historias' necesita trabajo aparte" de
> [`docs/plan_medicion_cap5.md`](plan_medicion_cap5.md) (Batería 2), opción **(b)**: matriz manual
> versionada como anexo.

## 1. Por qué existe este documento

El Capítulo 5 afirma "31 de 31 historias de usuario cubiertas". El repositorio tiene 31 historias
(`docs/historias_de_usuario.md`, US-01 … US-31) y aproximadamente 950 tests automatizados, pero
**ningún test cita una historia**: están indexados por change (C22, C31, C32…) y por regla de
negocio (RN-xx). Los conteos de la Batería 2 miden cuántos tests pasan, no qué historias cubren.

Sin una matriz, la afirmación es una aserción; con ella, es verificable. Ese es el único objetivo
de este anexo: que un lector pueda tomar cualquier fila, abrir el archivo de test citado y
comprobar por sí mismo si el criterio está o no verificado.

La revisión del 2026-08-19 lo confirma como instrumento de trabajo y no sólo de reporte: la primera
versión identificó 22 brechas ordenadas por costo, y las dos tandas de tests que siguieron cerraron
las diez más baratas más dos de nivel 2, además de destapar un defecto real en el dashboard (§6).

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

Un caso limítrofe merece regla explícita: cuando la **implementación es más angosta que el texto del
criterio** (por ejemplo, un umbral que la historia exige y el código no aplica), el test que asserta
la conducta implementada **no** cierra el criterio. Se anota como cobertura parcial y la diferencia
queda registrada en §6, para no confundir "el test verifica lo que el código hace" con "el test
verifica lo que la historia pide".

### Alcance de la evidencia

- **Backend**: 479 funciones `test_*` en `backend/tests/` (492 casos recolectados por `pytest`, por
  parametrización). Última corrida informada: 492 pasados, 0 fallidos.
- **Agente**: 408 funciones `test_*` en `agent/tests/`.
- **Frontend**: 61 casos `it()` en 10 archivos `*.test.ts`/`*.test.tsx`.

Los conteos de definiciones salen de un recuento estático (`def test_` / `it(`); sirven para
dimensionar y no reemplazan al dato oficial de la Batería 2, que debe salir del `--junitxml`.

Sobre el motor de base: `backend/tests/conftest.py` apunta a un PostgreSQL real
(`postgresql+psycopg://fim:test@localhost:5432/fim_test`) con `TRUNCATE ... RESTART IDENTITY` por
test, pero varios módulos siguen el "patrón A" y montan su propio SQLite en memoria. Los dos
archivos nuevos (`test_event_listing_contract.py` y `test_actions_router.py`) corren contra el
Postgres real y se saltean por completo si `psycopg` no está disponible: conviene verificar en la
salida de la Batería 2 que no aparezcan como `skipped`, porque sostienen buena parte de esta matriz.

## 3. Resumen

| Cobertura | Historias | Cuáles |
|---|---|---|
| `completa` | **3** | US-04, US-06, US-13 |
| `parcial` | **27** | US-01, US-02, US-03, US-05, US-07, US-08, US-10, US-11, US-12, US-14, US-15, US-16, US-17, US-18, US-19, US-20, US-21, US-22, US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31 |
| `sin cobertura` | **1** | US-09 |

Situación anterior a la revisión (2026-08-18): 0 `completa`, 28 `parcial`, 3 `sin cobertura`.
Situación tras la change `frontend-severity-triage` (2026-08-21): US-06 cierra su cuarto y último
criterio (fila con severidad y proceso causante) y pasa de `parcial` a `completa`.

**Lo que el Capítulo 5 puede afirmar con esta evidencia:** que las 31 historias tienen
implementación, que 30 de ellas tienen al menos un test automatizado que asserta parte de sus
criterios de aceptación y que 3 los tienen asertados por completo — pero **no** que las 31 historias
estén cubiertas, porque 27 conservan criterios sin verificar y una (US-09) describe una función que
fue removida del producto.

Tres matices que conviene declarar junto al número, porque explican la forma del resultado:

1. **El sesgo era estructural y se corrigió en parte.** La suite era densa donde el sistema es
   riesgoso (máquina de estados de eventos, HMAC, outbox transaccional, cola offline, cifrado de
   baseline) y nula donde el sistema es visual, porque `vitest` corría sin DOM. Con `jsdom` y
   Testing Library ya instalados, la brecha dejó de ser infraestructural y pasó a ser de alcance:
   hay tres componentes con tests y el resto sin ellos.
2. **De las 28 `parcial`, en 19 el criterio que falta no es un test sino una función.** Se listan en
   §6. Cerrar esas filas exige desarrollo o una decisión de producto, no escribir un test.
3. **El resto de las `parcial` son mayoritariamente criterios de interfaz** en pantallas que todavía
   no tienen test de componente: Events, EventDetail, Rules, Agents, Login.

## 4. Matriz

Convención de la columna **Tests**: se nombran los archivos principales y la cantidad de tests
relevantes; los identificadores `archivo::nombre_del_test` completos están en el detalle por
historia (§5), al que remite cada fila.

| US | Criterios (resumidos) | Tests | Cobertura | Observaciones |
|---|---|---|---|---|
| **US-01** Inicio de sesión | Formulario; tokens JWT 15 min / 7 días con rotación; error genérico; token en memoria; cookie `httpOnly`/`Secure`/`SameSite=Strict`; Argon2id C9; rate limit 5/15 min; scope `password_change_only` | `test_auth.py` (7), `test_c22_auth.py` (1), `core/test_rate_limit_load.py` (4) — [§5.1](#us-01) | parcial | El error genérico quedó cerrado: `test_login_error_es_identico_para_password_mala_y_usuario_inexistente` compara los cuerpos completos de las dos respuestas y verifica que ninguna nombra al usuario probado. Siguen sin test los parámetros Argon2id, los atributos de la cookie, la vida de los tokens y el almacenamiento en memoria. La cookie además **diverge**: `samesite="lax"` y `path="/"` en `auth/router.py` |
| **US-02** Cierre de sesión | Botón; limpieza de token; blacklist del `jti` en Valkey con TTL; redirección; 401 posterior | `test_auth.py` (2) — [§5.2](#us-02) | parcial | **El criterio central quedó cerrado.** `test_logout_invalida_access_token` fue reescrito: pide `GET /events` con el mismo token antes (200) y después del logout (401), y comprueba el TTL de la entrada de blacklist. La causa de que nadie lo hubiera cerrado antes es estructural y vale registrarla: `logout` escribe la blacklist con el cliente Valkey **síncrono** y `get_current_user` la lee con el **asíncrono**, y el conftest le daba a cada uno un mock independiente, de modo que la escritura nunca podía leerse. Los fixtures `blacklist_store`/`blacklist_valkey`/`blacklist_client` les dan un único store en memoria. Siguen sin test los dos criterios de cliente (botón, limpieza del token en memoria, redirección) |
| **US-03** Renovación de sesión | Refresh anticipado; rotación single-use; blacklist → login; transparencia; multi-key JWT | Backend previo más `test_jwt_key_rotation.py` (2); frontend: `auth.test.ts` (2), `auth.store.test.ts` (3), `client.test.ts` (1), `ProtectedRoute.test.tsx` (1) — [§5.3](#us-03) | parcial | Las capacidades automatizables quedaron implementadas y verificadas: timer 60 s antes de `exp`, single-flight, retry transparente, limpieza + navegación y dual-key. Resta aceptación integrada en navegador/backend real. |
| **US-04** Métricas del dashboard | Conteo por los 7 estados; léxico en minúsculas C1; carga al entrar; indicadores numéricos | `Dashboard.test.tsx` (4) — [§5.4](#us-04) | **completa** | Los cuatro criterios asertados sobre el componente real. El test mockea `@/api/client` y no `@/api/dashboard`, así que ejercita la agregación real del cliente (N requests a `/events`, una por estado). **Encontró un defecto real**: el dashboard enumeraba 6 de los 7 estados canónicos — faltaba `superseded` en `EVENT_STATUSES` (`Dashboard.tsx`) y en `statuses` (`api/dashboard.ts`) —, de modo que los eventos `superseded` no aparecían en ningún contador. Corregido en ambas listas |
| **US-05** Estado general del sistema | Pendientes sin resolver; conectividad de agentes; realce de críticos; banner rojo; banner amarillo | `Dashboard.test.tsx` (5), `SystemBanner.test.tsx` (4), `AlertsBanner.test.tsx` (5) — [§5.5](#us-05) | parcial | Cuatro de los cinco criterios quedaron asertados sobre componentes reales, incluido el realce visual de los `pending critical + high` con su caso negativo. El quinto no cierra por la regla de §2: la historia condiciona el banner amarillo a `retry_count >= 3` y `AlertsBanner` lo muestra ante **cualquier** alerta fallida, sin ese umbral; el test asserta la conducta implementada, no la pedida |
| **US-06** Listado de eventos | Tabla paginada 50/página; fila con path, estado, acción, severidad, fecha y proceso causante; orden desc; excluye `superseded` | `test_event_listing_contract.py` (4), `test_c31_backend_event_correctness.py` (1), `eventFilters.test.ts` (2), `EventsTable.test.tsx` (5) — [§5.6](#us-06) | **completa** | Change `frontend-severity-triage` (2026-08-21) cerró el cuarto criterio: `EventsTable.tsx` ahora renderiza severidad (banda de borde + texto canónico) y proceso causante como sublínea del path, con caso negativo para el evento sin contexto de proceso. El "tipo de acción" del criterio se satisface por la columna Estado (D35/RN-129: el `status` derivado *es* la acción ejecutada), sin campo nuevo. Los cuatro criterios quedan asertados sobre el componente real |
| **US-07** Filtrado por estado | Selector de los 7 estados; multi-selección; `superseded` excluido; toggle; actualización dinámica | `test_event_listing_contract.py` (3), `eventFilters.test.ts` (4) — [§5.7](#us-07) | parcial | La selectividad real del filtro quedó probada: `test_pagination_total_respects_status_filter` verifica que `total` cuenta sólo el estado pedido y que el ítem devuelto es de ese estado, y `test_status_filter_accepts_multiple_values` que el parámetro repetible es una unión. Siguen sin test los tres criterios de interfaz, y el selector **enumera 6 estados**, no 7 |
| **US-08** Detalle de un evento | Vista de detalle; campos; timestamps dobles con clock skew W13; contexto forense del proceso; enlace al padre; posición en la cadena | `test_event_listing_contract.py` (2), `test_stream_ack_durability_consumer.py` (11), `test_consumer.py` (1), `test_c31_backend_event_correctness.py` (2), `test_event_severity.py` (1), `test_event_symlink_metadata.py` (2), `test_event_ack_status_field.py` (3), `test_detector_context.py` (4) — [§5.8](#us-08) | parcial | Dos huecos grandes cerrados. `test_get_event_by_id_returns_full_detail` es el primer test de camino feliz del detalle: 200 y el conjunto de campos, con el contexto forense (`process_pid`/`uid`/`exe`) verificado ya persistido y expuesto, no sólo capturado en el agente. Y la frontera del clock skew quedó fijada a 299 s / 301 s en las **dos** ramas (con `sent_at` y por fallback sobre `detected_at`), incluida una aserción de que `_CLOCK_SKEW_S == 300`. Falta "tipo de acción", que no existe como campo, y la posición en la cadena |
| **US-09** Diff de un evento | Diff lado a lado/unificado; sólo texto; binarios con hashes y hex dump; detección automática; escapado W8; nunca loguear el diff W6 | `DiffViewer.test.ts` (7, helpers de un componente que ya no se monta), `test_detector_diff.py` (7, lado agente) — [§5.9](#us-09) | **sin cobertura** | Sin cambios, y debe seguir así: el panel de diff sigue ausente de `EventDetail.tsx` y `DiffViewer.tsx` no lo importa ningún módulo de la aplicación. Es una función faltante, no un test faltante; escribir un test sobre un componente que nadie renderiza sería cobertura falsa. W6 es doblemente huérfano: `hash_before`, `hash_after` y `size_delta` no existen en ninguna parte del código |
| **US-10** Cadena de eventos | Acceso a la cadena del path; orden cronológico con marca de `superseded`; navegación; ícono de cadena rota y `parent_event_id` | `test_event_service.py` (5), `test_event_status_derivation.py` (2), `test_c31_backend_event_correctness.py` (3), `test_c22_fk_chain.py` (3), `modules/events/test_retention.py` (3) — [§5.10](#us-10) | parcial | Sin cambios. El **modelo de datos** de la cadena está entre lo mejor cubierto del repositorio (supersesión optimista, `parent_event_id`, compactación a 10, protección por `audit_log`, carreras). La **funcionalidad de usuario** no existe: no hay endpoint que devuelva la cadena de un path, y `EventTimeline.tsx` documenta que quedó fuera de alcance |
| **US-11** Aprobación de un evento | Botón; UPDATE optimista C5; `approved` + `resolved_at`/`resolved_by`; baseline con hash actual; comando firmado C7 + C11; agente rechaza firma/versión; re-cifrado W10; `event_ack` C3; warning de archivo ausente; `audit_log`; 409 + toast | `test_actions_router.py` (11), `test_actions.py` (7), `test_c31_backend_event_correctness.py` (1), `test_stream_ack_durability_outbox.py` (4), `test_command_ack_consumer.py` (9), `test_commands.py` (5), `test_baseline.py` (7) — [§5.11](#us-11) | parcial | El hueco transversal del router quedó cerrado: `ConflictError → 409` con `detail.code`, `AbsentConfirmationRequired → 422` **contrastado contra un 422 de validación de Pydantic**, `require_admin` parametrizado sobre los cuatro endpoints, y la forma exacta de `ActionResponse` con el evento releído de la base. El criterio "baseline con el **hash actual**" sigue sin test y sin implementación: `test_no_get_file_hash_published` asserta la decisión contraria (D2). Falta el toast del 409 y el warning de archivo ausente en la UI |
| **US-12** Rechazo de un evento | Botón; elección `restore`/`quarantine`; modal ante baseline `absent` C10; no-op con warning; UPDATE optimista; `rejected` + campos; comando firmado C7 + C11; journal pre-acción W2; `audit_log` | `test_actions_router.py` (8), `test_actions.py` (5), `test_stream_ack_durability_outbox.py` (3), `test_published_command_ack_tracking.py` (2), `test_commands.py` (5), `test_journal.py` (9), `test_baseline_restore.py` (2) — [§5.12](#us-12) | parcial | `resolved_at`/`resolved_by` ahora sí se assertan en las tres rutas de reject (restore, quarantine y el no-op de baseline `absent`), y el no-op es observable por HTTP vía `baseline_absent: true`. El journal pre-acción W2 conserva la mejor prueba del lote (`test_journal_written_before_filesystem_op` intercepta `os.open`). Sigue sin asertarse que los handlers dejen el journal en `completed`/`failed` tras ejecutar. `ruleset_version` no se incluye en estos comandos por diseño → criterio no implementado |
| **US-13** Superseded automático | Nuevo evento supersede al `pending`; vínculo `parent_event_id`; no aparece en pendientes; transición validada C2; accesible por el toggle | `test_event_listing_contract.py` (3), `test_event_service.py` (7), `test_event_status_derivation.py` (5), `test_c31_backend_event_correctness.py` (2), `test_event_consumer_c11.py` (1), `test_c22_consumer.py` (1) — [§5.13](#us-13) | **completa** | Era la más cerca de cerrarse y se cerró. `test_list_events_excludes_superseded_by_default` cubre el único criterio que faltaba, y `test_superseded_filter_applies_to_total_not_only_to_the_page` agrega el matiz que hacía falta para que la exclusión sea coherente con la paginación: el `superseded` excluido tampoco cuenta en `total`. El acceso para auditoría queda cubierto por `test_list_events_includes_superseded_when_flag_is_true` |
| **US-14** Listado de reglas | Tabla; fila con patrón, severidad y acción; leyenda del default `alert_only`; `ruleset_version` del sistema | `test_rules_service.py` (3), `test_rules_router.py` (2), `test_rules.py` (1) — [§5.14](#us-14) | parcial | Sin cambios. Sólo el listado y su orden canónico por severidad están asertados. El `ruleset_version` global del sistema **no lo expone ningún endpoint**: lo que la UI muestra es `ruleset_version_applied` por agente, que es otra cosa |
| **US-15** Creación de regla | Formulario; glob y negación `!`; la exclusiva gana; persistencia; patrón no duplicado; `ruleset_version++` C11 + sync; `audit_log` | `test_rules_service.py` (10), `test_rules_router.py` (3), `test_ruleset_version_atomic.py` (2), `test_rules.py` (3) — [§5.15](#us-15) | parcial | Sin cambios. La precedencia de reglas exclusivas está probada **sólo en el agente**: `rules/service.py::determine_severity_for_path` hace `fnmatch` sin tratar el prefijo `!`. La validación de patrón duplicado no está implementada |
| **US-16** Edición de regla | Formulario precargado; modificar patrón/severidad/acción; persistencia; `ruleset_version++` + sync; `audit_log` | `test_rules_service.py` (4), `test_rules_router.py` (3) — [§5.16](#us-16) | parcial | El núcleo de la historia dejó de estar sin asertar: `test_update_rule_persists_the_new_field_values` relee la fila desde la base tras un `expire_all()` —para no leer el objeto en memoria que el servicio ya mutó— y verifica los tres campos, que no se creó una fila nueva y que `updated_at` avanzó; `test_update_rule_partial_payload_keeps_untouched_fields` cubre el payload parcial. Sólo queda sin test el formulario precargado |
| **US-17** Eliminación de regla | Opción de borrar; confirmación; eliminación de la fila; `ruleset_version++` + sync; caída al default `alert_only`; `audit_log` | `test_rules_service.py` (3), `test_rules_router.py` (3), `test_rules.py` (1), `test_decision.py` (1) — [§5.17](#us-17) | parcial | `test_delete_rule_removes_the_row` cierra el criterio central y agrega el control de que sólo se borró la regla pedida. Siguen sin test los dos criterios de interfaz y el criterio 5 conserva cobertura indirecta (el default `alert_only` de `RulesCache.evaluate`), no una prueba del escenario "regla borrada → el path cae al default" |
| **US-18** Sync automática de reglas | Publica `rule_sync`; firma C7 + `ruleset_version` C11; el agente verifica firma; descarta versiones menores; reemplaza caché sin reiniciar; persiste en `state.json`; comandos antes que eventos W4; `event_ack` C3 | `test_rules_service.py` (8), `test_rule_sync_outbox.py` (4), `test_c32_sse_security_fixes.py` (1), `test_rules.py` (5), `test_stability_fixes.py` (2), `test_reconnect_order.py` (7) — [§5.18](#us-18) | parcial | Sin cambios. Siete de ocho criterios asertados, incluido el orden de reconexión W4 y la persistencia del `ruleset_version` en `state.json`. El único que falla —`event_ack` tras `rule_sync`— no está implementado, y los tests **documentan la decisión contraria** (`test_rule_sync_persists_with_null_ack_status`) |
| **US-19** Listado de alertas | Lista ordenada por fecha desc; fila con path, severidad, acción, fecha y canal; navegación al evento | `test_sse_alerts.py` (10) — [§5.19](#us-19) | parcial | Sin cambios. El endpoint, sus filtros y la paginación están bien cubiertos; los tres criterios *de la historia*, no. `AlertResponse` no expone `path` ni tipo de acción, la navegación al evento no está implementada, y el `ORDER BY created_at DESC` no lo asserta ningún test |
| **US-20** Alertas en tiempo real | Conexión SSE; alerta ante nuevo evento; notificación visual; reconexión automática | `test_sse_alerts.py` (12), `test_c32_sse_security_fixes.py` (4) — [§5.20](#us-20) | parcial | Sin cambios. El backend SSE está bien cubierto: auth por query param, replay con `Last-Event-ID`, keepalive, cierre de sesión de DB y cola acotada a 100. El hueco relevante es la cadena real evento → `notify_if_applicable` → `alerts_broadcaster.publish`, que **ningún test recorre**: de `notify_if_applicable` sólo se prueban los tres casos de *skip* |
| **US-21** Estado de agentes | Lista; identificador, estado, última actividad, `ruleset_version`, `queue_size`; realce de no-ok; heartbeat 10 s / 30 s → offline / 5 min → dead + webhook / `shutdown` → draining; banner de `queue_pressure` W3 | `test_agent_mgmt.py` (5), `test_heartbeat_consumer.py` (6), `test_agent_watch_path_status.py` (2), `test_domain_models.py` (1), `test_queue.py` (4) — [§5.21](#us-21) | parcial | La máquina de estados del heartbeat quedó completa en sus transiciones (online → draining → offline@30s → dead@5min → vuelta a online, y ahora también draining → offline). Sin cobertura: el intervalo de 10 s, el webhook n8n al pasar a `dead` (no implementado), `queue_size` en la vista (no se persiste) y el umbral del 80% de W3, que no existe en el código |
| **US-22** Re-scan de baseline | Botón con selección de paths; diálogo con los `pending` afectados; confirmación explícita; supersesión + comando firmado C7 con `ruleset_version++` C11; el agente verifica firma y versión; regenera baseline cifrado W10; `event_ack` C3; confirmación visual; `audit_log`; deshabilitado si `draining` | `test_agent_mgmt.py` (4), `test_published_command_ack_tracking.py` (1), `test_stream_ack_durability_outbox.py` (1), `test_agent_config.py` (5), `test_commands.py` (3), `test_baseline.py` (7) — [§5.22](#us-22) | parcial | Sin cambios. El flujo existe de punta a punta y ese eje está bien cubierto. Tres criterios fallan por implementación: no hay selección de paths, el comando no lleva `ruleset_version++`, y `handle_rescan_baseline` no tiene guard de versión. La supersesión alcanza a **todos** los pending del agente, no a los paths seleccionados |
| **US-23** Notificación externa | Webhook n8n ante `critical`/`high`; payload con contexto de proceso y timestamps; n8n como enrutador; retry 5/30/120 s; cascada SMTP → webhook → log; fila en DLQ; n8n caído no compromete la operación | `test_notifications.py` (16), `test_c31_backend_event_correctness.py` (2), `test_health_n8n_check.py` (8) — [§5.23](#us-23) | parcial | Sin cambios. El retry con los delays exactos y la caída a DLQ son el núcleo mejor asertado. El criterio "sólo `critical`/`high`" se demuestra **por exclusión**, nunca por inclusión. El payload no incluye `process_pid`/`uid`/`exe`, `received_at` ni la acción tomada → criterio incumplido en el código. La entrega efectiva por SMTP y por webhook directo nunca se asserta con éxito |
| **US-24** Paths monitoreados | Lista de paths por agente; agregar; quitar; persistencia; `update_config` firmado C7 + `ruleset_version++` C11; el agente verifica y recarga en caliente; baseline scan de paths nuevos W10; `event_ack` C3; bootstrap desde YAML → autoridad en PostgreSQL; `audit_log`; deshabilitado si `draining` | `test_agent_mgmt.py` (5), `test_agent_watch_path_status.py` (3), `test_published_command_ack_tracking.py` (2), `test_agent_config.py` (6), `test_commands.py` (5), `test_stability_fixes.py` (2), `test_audit_fixes.py` (1) — [§5.24](#us-24) | parcial | Sin cambios. La historia mejor cubierta del lado backend + agente. Se mantiene la advertencia metodológica: `test_reload_watch_paths_marks_new` y `::test_reload_watch_paths_unmarks_removed` **no invocan el método que dicen probar** — reimplementan la aritmética de conjuntos dentro del propio test. La reconfiguración real de las marcas de `fanotify` no está verificada por ningún test |
| **US-25** Bulk approve/reject | Checkbox por fila y "todo en la página"; botones bulk; modal con los primeros 10 paths; elección de acción; `POST /actions/bulk-*`; locking individual C5; `succeeded[]`/`failed[]`; baseline firmado por cada aprobado; `audit_log`; resumen visual; refresco | Backend previo; frontend: `EventsTable.test.tsx` (2 casos US-25), `BulkActionBar.test.tsx` (4) — [§5.25](#us-25) | parcial | El resumen expandible por path, la invalidación y la conciliación segura de selecciones concurrentes quedaron implementados y verificados. Resta aceptación visual e integración con backend real. |
| **US-26** Paginación | 50 por página; navegación numerada; input "ir a página"; `?page=N&page_size=50`; respeta los filtros activos | `test_event_listing_contract.py` (5), `test_c31_backend_event_correctness.py` (1), `test_event_router.py` (1), `eventFilters.test.ts` (3) — [§5.26](#us-26) | parcial | El riesgo silencioso más grande quedó cubierto con tres tests: `total` respeta el filtro de estado, el `path_prefix` y el rango de fechas — cada uno con `page_size=1` para que un `total` mal calculado no se disimule. Los criterios 2 y 3 siguen sin test porque **no están implementados**: sólo hay "Anterior"/"Siguiente" |
| **US-27** Cambio obligatorio de password | Seed con el flag; scope `password_change_only`; redirect forzado; formulario con complejidad; validación de la actual; Argon2id C9; flag a `false` + tokens nuevos; bloqueo de otras rutas; re-exigencia; `audit_log` | `test_auth.py` (5), `test_c22_auth.py` (1), `test_c22_scope_gate.py` (5), `modules/users/test_user_management.py` (3) — [§5.27](#us-27) | parcial | El gate de scope en backend está bien cubierto. El flujo completo (login inicial → cambio → login con scope pleno) ahora se ejercita como precondición del helper `_full_access_login` de los tests de logout, aunque de forma incidental. Sin test: validación de la contraseña actual, reglas de complejidad (no implementadas), Argon2id, `audit_log` y re-exigencia tras cerrar sesión |
| **US-28** Banner de degradación | Poll cada 10 s; estado de `postgres`, `valkey`, `n8n` y agentes; banner rojo con componente y timestamp; cerrable y reaparece; no bloquea; webhook ante cambio de estado | `SystemBanner.test.tsx` (4), `test_notifications.py` (5), `test_health_n8n_check.py` (8) — [§5.28](#us-28) | parcial | El banner dejó de estar sin test: se asserta que no aparece con todo `ok`, que nombra el componente caído, que trata el subsistema `agents` como degradado y que nombra varios caídos a la vez sin inventar uno sano. Quedan tres huecos: el poll de 10 s (`refetchInterval: 10_000` existe en `SystemBanner.tsx` y ningún test lo verifica), la porción `agents` de `check_components` **del lado backend**, y `GET /health/components` como endpoint HTTP, que ningún test invoca. Dos criterios de UI no están implementados: timestamp del último check saludable y botón de cierre |
| **US-29** Webhooks fallidos | Banner amarillo con `retry_count >= 3`; link a la vista; tabla con `event_id`, primer intento, error y `retry_count`; reintentar/descartar por fila; bulk; eliminación tras reintento exitoso; el banner desaparece; `audit_log` | `test_notifications.py` (9), `AlertsBanner.test.tsx` (5), `test_sse_alerts.py` (3) — [§5.29](#us-29) | parcial | Dos criterios cerrados. El reintento tiene por fin camino feliz, en dos capas: `test_retry_alert_resets_dlq_state_and_reschedules` verifica el reseteo de `failed_at`/`last_error`/`retry_count` y que la cascada se vuelve a disparar sobre la misma alerta y el mismo evento; `test_retry_alert_delivers_and_leaves_the_dlq` cierra el ciclo hasta que la fila desaparece de `list_failed_alerts`. Y el banner desaparece con la DLQ vacía. Persisten las divergencias: sin umbral `retry_count >= 3`, el link va a `/alerts` y no a `/notifications/failed`, no hay bulk ni `audit_log`, y la tabla `failed_notifications` no existe |
| **US-30** Agente en shutdown graceful | Deja de aceptar eventos; drena con timeout 30 s; heartbeat con `shutdown: true`; backend marca `draining`; indicador "Drenando N eventos"; botones deshabilitados con tooltip; pasa a `offline`/`dead` | `test_shutdown_heartbeat.py` (5), `test_heartbeat_consumer.py` (3), `test_stability_fixes.py` (1), `test_agent_mgmt.py` (1), `test_publisher.py` (1), `test_reconnect_order.py` (2) — [§5.30](#us-30) | parcial | La transición `draining → offline` quedó cubierta con su caso negativo (un agente drenando que sigue latiendo no se marca offline): era la rama del `status.in_([online, draining])` que nunca se ejercitaba. Siguen sin test o sin implementación el cese de aceptación de eventos de `fanotify`, el timeout de 30 s del drenaje (`_drain_then_stop(..., timeout=30.0)` no lo invoca ningún test) y los dos criterios de interfaz |
| **US-31** Toggle de superseded | Oculto por defecto; checkbox; ícono de cadena rota y `parent_event_id`; persistencia en la URL; `GET /events` respeta el parámetro | `test_event_listing_contract.py` (2), `eventFilters.test.ts` (7) — [§5.31](#us-31) | parcial | El vacío más significativo quedó cerrado: el criterio 5 (la regla W1 del lado servidor) lo assertan ahora dos tests con eventos `superseded` reales, uno por cada lado del flag. Persisten sin test los dos criterios de interfaz, y sigue vigente la advertencia de que `frontend/src/api/events.ts:88-97` **duplica** la serialización de filtros en un `paramsSerializer` sin ningún test |

## 5. Detalle por historia

### Nota transversal sobre el frontend

**Actualizada tras `cff86fb`.** La infraestructura de tests de componente ya existe:
`frontend/vitest.config.ts` corre con `environment: 'jsdom'` y `setupFiles: ['./src/test/setup.ts']`,
y `frontend/package.json` incluye `jsdom`, `@testing-library/react`, `@testing-library/jest-dom` y
`@testing-library/user-event`. El helper `frontend/src/test/renderWithProviders.tsx` monta los
componentes con los mismos providers que producción (TanStack Query + router), con reintentos y
refetch desactivados para que cada caso controle exactamente qué respuestas ve el componente.

Hay tres componentes con tests: `frontend/src/pages/Dashboard.test.tsx` (9),
`frontend/src/components/layout/SystemBanner.test.tsx` (4) y
`frontend/src/components/layout/AlertsBanner.test.tsx` (5). Los siete archivos de funciones puras
preexistentes siguen intactos y sin migrar.

Todos mockean `@/api/client` y no el módulo de API correspondiente, lo cual es una decisión
metodológica que conviene señalar a favor: el test ejercita la capa de agregación real del cliente
en vez de saltearla. En el caso del dashboard eso es lo que permitió detectar el defecto de los
estados canónicos.

Sigue sin haber tests de componente para Events, EventDetail, Rules, Agents, Login ni
ForcePasswordChange, ni tests de interacción con `user-event`, ni pruebas de routing o de guardas de
ruta. Ahí viven la mayoría de los criterios de interfaz que este anexo marca como SIN TEST, y ahora
la razón es de alcance y no de infraestructura.

### Nota transversal sobre el router de acciones — cerrada

`backend/tests/test_actions_router.py` (16 definiciones, 22 casos por parametrización sobre los
cuatro endpoints) cubre lo que antes no atravesaba ningún test: el mapeo `ConflictError → HTTP 409`
con `detail.code == "conflict"`, `AbsentConfirmationRequired → HTTP 422` con su código de dominio y
contrastado contra un 422 de validación de Pydantic (que devuelve una lista, no un objeto con
`code`), `require_admin` en los cuatro endpoints —401 sin token, 403 `admin_required` con un usuario
autenticado no admin, antes de validar el cuerpo— y la forma exacta de `ActionResponse` y
`BulkResultResponse`. Los tests firman tokens para usuarios que existen en la base y no
sobreescriben `get_current_user`, así que el gate se ejercita de verdad.

### Nota transversal sobre aserciones débiles

Algunos tests aceptan varios códigos de respuesta como válidos y por lo tanto pasan aunque el
endpoint no funcione. No deben citarse como evidencia de comportamiento:

- `backend/tests/test_rules_router.py::test_post_rules_creates_rule_returns_201` — asserta
  `status_code in (201, 401, 422, 500)`.
- `backend/tests/test_rules_router.py::test_get_rules_returns_200_with_auth`,
  `::test_get_rule_not_found_returns_404`, `::test_put_rule_not_found_returns_404`,
  `::test_delete_rule_not_found_returns_404` — aceptan `401` como resultado válido.
- `backend/tests/test_event_router.py::test_get_event_not_found_returns_404` — asserta
  `status_code in (404, 401)`. Su equivalente estricto ya existe:
  `test_event_listing_contract.py::test_get_event_by_id_unknown_returns_404`.
- `backend/tests/test_auth.py::test_scope_password_change_only_en_access_token` — la aserción está
  dentro de un `if`.
- `backend/tests/test_auth.py::test_require_full_access_bloquea_scope_password_change_only` — el
  nombre promete un bloqueo; el cuerpo asserta que `/users/change-password` devuelve 200. El bloqueo
  real lo prueban los tests de `test_c22_scope_gate.py`.

`test_logout_invalida_access_token` **salió de esta lista**: fue reescrito y hoy es una de las
pruebas más estrictas de la suite de auth (§5.2).

---

<a id="us-01"></a>
### 5.1 US-01: Inicio de sesión — `parcial`

| Criterio | Tests |
|---|---|
| Formulario con usuario y contraseña | SIN TEST (UI: `frontend/src/pages/Login.tsx`) |
| Credenciales válidas → par de tokens y redirección | `backend/tests/test_auth.py::test_login_exitoso_retorna_200`, `::test_login_incluye_objeto_user`. La vida de 15 min / 7 días: SIN TEST directo (se usa como cota en los tests de logout). Redirección: SIN TEST |
| Credenciales inválidas → error genérico | `backend/tests/test_auth.py::test_login_error_es_identico_para_password_mala_y_usuario_inexistente` (compara los cuerpos completos, el `detail` literal y que ninguna respuesta nombra al usuario probado), `::test_login_password_incorrecta_retorna_401`, `::test_login_usuario_inexistente_retorna_401` |
| Access token en memoria, nunca en `localStorage` (W9) | SIN TEST |
| Refresh token como cookie `httpOnly`/`Secure`/`SameSite=Strict`/`Path=/auth/refresh` (W9) | SIN TEST |
| Argon2id `time_cost=3, memory_cost=65536, parallelism=4` (C9) | SIN TEST |
| Rate limit 5 intentos / 15 min por `(username + IP)` (W5) | `backend/tests/test_auth.py::test_rate_limit_login_6to_intento_retorna_429`, `::test_rate_limit_login_5_intentos_pasan`, `backend/tests/core/test_rate_limit_load.py::test_login_n_requests_dentro_del_bucket_no_rechazados`, `::test_login_n_mas_1_request_retorna_429`, `::test_login_ventana_se_resetea_en_primer_request`, `::test_login_ttl_siempre_presente_tras_incrementos_count_mayor_a_1` |
| `must_change_password` → scope `password_change_only` | `backend/tests/test_auth.py::test_login_primer_admin_must_change_password_true`, `::test_scope_password_change_only_en_access_token`, `backend/tests/test_c22_auth.py::test_create_access_token_scope_password_change_only_sigue_teniendo_type_access` |

Los tests de rate limit leen `settings.rate_limit_login_attempts` en vez de fijar 5 y 900, de modo
que los valores del criterio quedan verificados sólo en tanto se respeten los defaults de
`backend/app/core/config.py:51-52`.

---

<a id="us-02"></a>
### 5.2 US-02: Cierre de sesión — `parcial`

| Criterio | Tests |
|---|---|
| Botón de logout visible | SIN TEST (UI) |
| Limpieza del access token e invalidación de la cookie | Lado servidor: `backend/tests/test_auth.py::test_logout_invalida_tambien_el_refresh_token`. La limpieza del store en memoria del cliente: SIN TEST |
| `jti` del refresh en blacklist con TTL restante (C8) | `backend/tests/test_auth.py::test_logout_invalida_access_token` (TTL del access acotado a `ACCESS_TOKEN_EXPIRE_MINUTES * 60` y verificado como recién emitido), `::test_logout_invalida_tambien_el_refresh_token` (TTL del refresh dentro de la ventana de `REFRESH_TOKEN_EXPIRE_DAYS`) |
| Redirección al login | SIN TEST (UI) |
| Solicitudes posteriores con token invalidado → 401 | `backend/tests/test_auth.py::test_logout_invalida_access_token` (200 en `GET /events` antes del logout, 401 después con el mismo token), `::test_logout_invalida_tambien_el_refresh_token` (el refresh revocado ya no rota la sesión) |

**Por qué este criterio estuvo tanto tiempo sin cerrar.** No era desidia sino un artefacto del
arnés de tests: `logout` escribe la blacklist a través del cliente Valkey **síncrono**
(dependencia `get_valkey_client`) mientras `get_current_user` la consulta a través del
**asíncrono** (`get_async_valkey_client`), y el conftest entregaba a cada uno un mock
independiente. La escritura era por lo tanto imposible de leer, y cualquier intento de escribir el
test terminaba forzando `mock_valkey.exists.return_value = 1` a mano, que es justamente lo que la
versión anterior hacía. Los fixtures `blacklist_store` / `blacklist_valkey` / `blacklist_client` de
`backend/tests/test_auth.py` les dan un único store en memoria compartido, y recién con eso el
criterio se vuelve verificable de punta a punta.

---

<a id="us-03"></a>
### 5.3 US-03: Renovación automática de sesión — `parcial`

| Criterio | Tests |
|---|---|
| El frontend pide un token nuevo antes de que expire | `frontend/src/stores/auth.store.test.ts::renueva una vez sesenta segundos antes de expirar y reemplaza el token en memoria`; `::un token ilegible no dispara refresh basado en claims no verificadas` |
| El refresh rota en cada uso (C8) | `backend/tests/test_auth.py::test_refresh_valido_rota_token`, `::test_refresh_con_token_revocado_retorna_401`; single-flight cliente: `frontend/src/api/auth.test.ts` (2) |
| Refresh expirado o revocado → login | Contratos backend anteriores; cliente: `frontend/src/stores/auth.store.test.ts::si el refresh anticipado falla limpia la sesión local`, `frontend/src/components/layout/ProtectedRoute.test.tsx::navega una sola vez a login cuando una sesión ya verificada queda sin token` |
| Renovación transparente | `frontend/src/api/client.test.ts::reintenta la petición original con el token rotado después de un 401`; además, ventana de gracia backend y single-flight cliente ya citados |
| Multi-key `JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS` (C8) | `backend/tests/test_jwt_key_rotation.py` (2): acepta CURRENT/PREVIOUS y rechaza una clave ajena; ejecutados individualmente contra PostgreSQL 18.3 efímero |

---

<a id="us-04"></a>
### 5.4 US-04: Métricas generales del dashboard — `completa`

| Criterio | Tests |
|---|---|
| Conteo de eventos por los 7 estados | `frontend/src/pages/Dashboard.test.tsx::Dashboard — US-04: metricas generales — muestra un contador para cada uno de los 7 estados canonicos, incluido superseded` |
| Léxico canónico en minúsculas (C1) | `frontend/src/pages/Dashboard.test.tsx::consulta al backend usando el lexico canonico en minusculas snake_case (C1)`; a nivel de enum: `backend/tests/test_domain_models.py::TestEventStatus::test_all_canonical_values`, `::TestEventStatus::test_rejects_uppercase` |
| Las métricas se cargan al entrar | `frontend/src/pages/Dashboard.test.tsx::carga las metricas al entrar al dashboard, sin interaccion del usuario` (verifica el estado de carga previo, su desaparición y las llamadas a `/events`, `/agents` y `/health/components`) |
| Indicadores numéricos claros | `frontend/src/pages/Dashboard.test.tsx::presenta cada metrica como un indicador numerico junto a su etiqueta` (busca el número dentro de la tarjeta de cada etiqueta, no suelto en la página) |

**Defecto encontrado por estos tests.** El primer criterio exige los 7 estados canónicos (RN-71) y
el dashboard enumeraba 6: faltaba `superseded` tanto en `EVENT_STATUSES` (`Dashboard.tsx:75-83`)
como en la lista `statuses` (`api/dashboard.ts:30`), de modo que los eventos `superseded` no
aparecían en ningún contador. Ambas listas fueron corregidas. Es el hallazgo que justifica el costo
de la infraestructura de tests de componente: era un defecto de producto invisible para toda la
suite de backend.

---

<a id="us-05"></a>
### 5.5 US-05: Estado general del sistema — `parcial`

| Criterio | Tests |
|---|---|
| Cantidad de `pending` sin resolver | `frontend/src/pages/Dashboard.test.tsx::Dashboard — US-05: estado general del sistema — indica cuantos eventos pending hay sin resolver` |
| Conectividad de agentes | `frontend/src/pages/Dashboard.test.tsx::muestra el estado de conectividad de los agentes registrados` (cuenta `online`, `offline`, `draining` y `dead` por separado); a nivel de enum: `backend/tests/test_domain_models.py::TestAgentStatus::test_all_canonical_values` |
| Realce de `pending` con severidad `critical`/`high` | `frontend/src/pages/Dashboard.test.tsx::destaca visualmente los pending critical/high cuando existen` y `::no destaca la tarjeta de pending critical/high cuando no hay ninguno` (par positivo/negativo: compara la clase de la tarjeta contra la de una tarjeta normal, de modo que un realce permanente fallaría) |
| Banner rojo de degradación | `frontend/src/components/layout/SystemBanner.test.tsx::no muestra ningun banner cuando todos los componentes estan ok`, `::muestra un banner rojo que nombra el componente degradado`, `::trata al subsistema de agentes como degradado cuando su status no es ok`, `::nombra todos los componentes caidos a la vez`; el estado de infraestructura en el dashboard: `frontend/src/pages/Dashboard.test.tsx::muestra el estado de la infraestructura monitoreada` |
| Banner amarillo de notificaciones fallidas | Parcial — `frontend/src/components/layout/AlertsBanner.test.tsx::muestra un banner amarillo con la cantidad de alertas fallidas en la DLQ`, `::no muestra ningun banner cuando no hay alertas fallidas`, `::ofrece un enlace para revisar las alertas fallidas`, `::consulta unicamente las alertas en estado failed`, `::usa el singular cuando hay una sola alerta fallida`. **El umbral `retry_count >= 3` que pide el criterio no está implementado ni asertado** |

Es la única historia que no cierra por la regla del caso limítrofe de §2: cuatro criterios están
plenamente asertados y el quinto lo está sólo en su forma implementada, más débil que la pedida.

---

<a id="us-06"></a>
### 5.6 US-06: Listado de eventos — `completa`

| Criterio | Tests |
|---|---|
| Tabla paginada, 50 por página por defecto | `backend/tests/test_event_listing_contract.py::test_list_events_default_page_size_is_50` (51 eventos: la primera página trae 50 y la segunda el restante, así que la paginación corta y no descarta); `backend/tests/test_c31_backend_event_correctness.py::test_fix04_pagination_sql`; `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío` |
| Fila con path, estado, acción, severidad, fecha y proceso causante | Cerrado por change `frontend-severity-triage`: `frontend/src/components/ui/EventsTable.test.tsx` — `EventsTable — contenido de fila (US-06)::una fila muestra path, estado, severidad y fecha juntos`, `EventsTable — severidad::la fila de un critical muestra el texto "critical", y la de un low muestra "low"`, `::la fila de un critical y la de un low no comparten la clase de banda de borde`, `EventsTable — proceso causante::una fila con contexto de proceso muestra el ejecutable, el pid y el uid`, `::un evento sin contexto de proceso no renderiza la sublínea ni el texto "null"`. "Tipo de acción" no es un campo nuevo: desde D35/RN-129 el `status` derivado *es* la acción ejecutada, y ese sub-criterio lo cierra la columna Estado, ya cubierta arriba |
| Orden por fecha de creación descendente | `backend/tests/test_event_listing_contract.py::test_list_events_orders_by_created_at_desc` (inserta fuera de orden cronológico a propósito, de modo que un `ORDER BY id` daría otra secuencia y el test lo detectaría) |
| El filtro default excluye `superseded` (W1) | `backend/tests/test_event_listing_contract.py::test_list_events_excludes_superseded_by_default`, `::test_superseded_filter_applies_to_total_not_only_to_the_page`; cliente: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — include_superseded=false queda como undefined` |

---

<a id="us-07"></a>
### 5.7 US-07: Filtrado de eventos por estado — `parcial`

| Criterio | Tests |
|---|---|
| Selector con los 7 estados | SIN TEST — `ALL_STATUSES` en `Events.tsx:10-17` enumera 6. El filtrado del backend sí: `backend/tests/test_event_listing_contract.py::test_pagination_total_respects_status_filter` |
| Selección múltiple simultánea | `backend/tests/test_event_listing_contract.py::test_status_filter_accepts_multiple_values` (el parámetro repetible es una unión, no una intersección vacía); `frontend/src/utils/eventFilters.test.ts::parseEventFilters — parsea multi-select status`, `::serializeEventFilters — serializa multi-select status como repeated params` |
| `superseded` excluido por defecto (W1) | `backend/tests/test_event_listing_contract.py::test_list_events_excludes_superseded_by_default`; cliente: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío` |
| Toggle "Mostrar superseded" | Backend: `backend/tests/test_event_listing_contract.py::test_list_events_includes_superseded_when_flag_is_true`. El checkbox: SIN TEST (ver US-31) |
| Actualización dinámica al filtrar | SIN TEST |

El test que antes se citaba aquí con reservas —`backend/tests/test_event_severity.py::test_list_events_filters_by_severity`, que enviaba `status=pending` sobre un fixture donde los cuatro eventos eran `pending`— queda superado: la selectividad hoy se prueba con eventos de estados distintos.

---

<a id="us-08"></a>
### 5.8 US-08: Detalle de un evento — `parcial`

| Criterio | Tests |
|---|---|
| Vista de detalle al seleccionar | `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` (200 con el detalle completo), `::test_get_event_by_id_unknown_returns_404`; rutas de error preexistentes: `backend/tests/test_event_router.py::test_get_event_by_id_no_auth_returns_401` |
| Campos: path, hash, estado, acción, severidad, fechas, resolución | `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` (id, `event_id`, `agent_id`, path, `hash_detected`, status, severity, version, `parent_event_id`, `resolved_at`/`resolved_by` en `None`, metadatos de symlink); serialización por campo: `backend/tests/test_event_severity.py::test_event_out_serializes_severity`, `backend/tests/test_event_symlink_metadata.py::test_event_out_serializes_symlink_metadata`, `::test_event_out_defaults_for_regular_file`, `backend/tests/test_event_status_derivation.py::test_event_out_serializes_action_failed_true`, `::test_event_out_defaults_action_failed_false`, `backend/tests/test_event_ack_status_field.py::test_event_with_confirmed_command_exposes_ack_status`, `::test_event_without_confirmable_command_has_no_ack_status`, `::test_event_uses_most_recent_published_command`. **"Tipo de acción": SIN TEST y sin campo en el modelo** |
| Timestamps dobles con clock skew de 5 min (W13) | Frontera exacta: `backend/tests/test_stream_ack_durability_consumer.py::test_sent_at_at_299s_is_accepted` (con `assert _CLOCK_SKEW_S == 300`), `::test_sent_at_at_301s_is_rejected`, `::test_detected_at_fallback_boundary_at_299s_and_301s`. Resto de la ventana: `::test_detected_at_old_sent_at_recent_is_accepted`, `::test_sent_at_out_of_range_rejected`, `::test_sent_at_in_future_rejected`, `::test_sent_at_unparseable_rejected`, `::test_sent_at_naive_interpreted_as_utc`, `::test_no_sent_at_within_window_accepted`, `::test_no_sent_at_old_detected_at_rejected`, `::test_response_matrix_clock_skew_terminal_nack`; `backend/tests/test_consumer.py::test_reject_clock_skew`; `backend/tests/test_c31_backend_event_correctness.py::test_fix08_unparseable_detected_at_rejected_as_clock_skew`, `::test_fix08_naive_datetime_within_range_accepted`; exposición en el detalle: `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` |
| Contexto forense del proceso (PID, UID, `exe`) | `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` (persistido y expuesto); captura en el agente: `agent/tests/test_detector_context.py::test_get_exe_returns_none_on_oserror`, `::test_get_exe_returns_path_on_success`, `::test_get_uid_returns_zero_on_oserror`, `::test_get_uid_parses_uid_from_proc_status` |
| Enlace al evento padre | El `parent_event_id` viaja en la respuesta: `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail`; se puebla al formarse la cadena: `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`. El render del link: SIN TEST |
| Posición en la cadena y navegación | SIN TEST — fuera de alcance según `EventTimeline.tsx:9-12` |

---

<a id="us-09"></a>
### 5.9 US-09: Visualización de diff — `sin cobertura`

Estado reverificado el 2026-08-19: sin cambios. El panel de diff sigue removido del detalle
(commit `9e566ed`); `frontend/src/pages/EventDetail.tsx:224-228` conserva sólo un comentario
explicando la remoción, y `DiffViewer.tsx` no se importa desde ningún módulo de la aplicación. El
modelo `Event` no tiene campo de contenido ni de diff, e `ingest_event` descarta el `diff_text` que
el agente sí emite.

La clasificación debe permanecer en `sin cobertura` aunque ahora exista infraestructura de tests de
componente: la función está ausente, no sin testear. Montar `DiffViewer` en un test para poder citar
una fila cubierta produciría cobertura de código muerto, que es exactamente el tipo de evidencia que
este anexo existe para descartar.

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
| UPDATE optimista `version = :expected_version` (C5) | `backend/tests/test_actions_router.py::test_approve_with_stale_version_returns_409`, `::test_approve_already_resolved_event_returns_409` (aprobar dos veces: la segunda es conflicto, no un no-op silencioso); `backend/tests/test_actions.py::test_approve_conflict`, `::test_approve_success` |
| `approved` + `resolved_at` + `resolved_by` | `backend/tests/test_actions_router.py::test_approve_returns_action_response_shape` (relee el evento de la base y verifica `version == 1`, `resolved_by == admin_id` y `resolved_at is not None`); `backend/tests/test_actions.py::test_approve_success` |
| Baseline con el hash **actual** del archivo | SIN TEST — y no implementado: `backend/tests/test_actions.py::test_no_get_file_hash_published` asserta la decisión contraria (D2) |
| Comando firmado con HMAC-SHA256 (C7) | `backend/tests/test_actions.py::test_baseline_update_hmac_valid`; `backend/tests/test_c31_backend_event_correctness.py::test_fix02_approve_publish_is_post_commit`; `backend/tests/test_stream_ack_durability_outbox.py::test_approve_pending_row_born_in_same_transaction`, `::test_approve_valkey_down_leaves_event_approved_and_command_pending`, `::test_approve_rollback_leaves_no_published_command_row`, `::test_approve_without_secret_reverts_and_raises` |
| `ruleset_version` monotónico (C11) | Indirecto: `backend/tests/test_ruleset_version_atomic.py::test_concurrent_increments_no_lost_update`, `::test_actions_and_rules_share_single_implementation`. El valor dentro del payload de approve no se asserta |
| El agente rechaza firma inválida | `agent/tests/test_commands.py::test_hmac_invalid_discards_command` |
| El agente descarta versión menor | `agent/tests/test_commands.py::test_baseline_update_older_version_ignored` |
| Baseline local re-cifrada AES-256-GCM (W10) | `agent/tests/test_commands.py::test_baseline_update_present_writes_encrypted`; motor: `agent/tests/test_baseline.py::test_encrypt_decrypt_roundtrip`, `::test_key_derivation_deterministic`, `::test_key_derivation_different_agents`, `::test_tampered_blob_raises`, `::test_unique_nonce_per_write`, `::test_gcm_detects_path_swap`, `::test_baseline_file_permissions` |
| Confirma con `event_ack` (C3) | Lado agente: SIN TEST para `baseline_update`. Lado backend: `backend/tests/test_command_ack_consumer.py::test_ack_ok_baseline_update_marks_acked`, `::test_ack_ok_baseline_update_reconciles_baseline_entries`, `::test_ack_ok_baseline_update_advances_ruleset_version_applied`, `::test_ack_ok_monotonic_does_not_regress`, `::test_ack_error_marks_failed_no_reconciliation`, `::test_ack_invalid_signature_rejected`, `::test_ack_repeated_is_idempotent`, `::test_ack_cross_agent_forge_rejected`, `::test_ack_spoofed_agent_id_wrong_secret_rejected`; firma del ack: `agent/tests/test_commands.py::test_publish_ack_signs_command_ack_with_hmac` |
| Warning de archivo ausente | Backend: `backend/tests/test_actions_router.py::test_approve_absent_file_without_confirmation_returns_422` (422 de dominio con `detail == {"code": "absent_confirmation_required"}`) y `::test_approve_missing_required_field_returns_validation_422` (el contraste con un 422 de Pydantic, que devuelve una lista). El texto del warning en la UI: SIN TEST |
| Confirmación explícita del admin | `backend/tests/test_actions_router.py::test_approve_absent_file_with_confirmation_succeeds`; `backend/tests/test_actions.py::test_approve_absent_no_confirm` |
| Baseline registra el path como `absent` (hash null) | `backend/tests/test_actions_router.py::test_approve_absent_file_with_confirmation_succeeds` (verifica la fila `BaselineEntry` con `status == absent`); `backend/tests/test_actions.py::test_approve_absent_confirmed`; `agent/tests/test_commands.py::test_baseline_update_absent_writes_null_hash` |
| Creación futura del path tratada como anomalía | SIN TEST |
| Registro en `audit_log` (W18) | `backend/tests/test_actions.py::test_audit_log_on_approve` |
| HTTP 409 + toast al perder la carrera | 409: `backend/tests/test_actions_router.py::test_approve_with_stale_version_returns_409` (con `detail.code == "conflict"` y el evento intacto en `pending`). El toast: SIN TEST |
| Autorización del endpoint | `backend/tests/test_actions_router.py::test_actions_endpoints_require_authentication[/actions/approve]`, `::test_actions_endpoints_reject_non_admin[/actions/approve]` |

---

<a id="us-12"></a>
### 5.12 US-12: Rechazo de un evento `pending` — `parcial`

| Criterio | Tests |
|---|---|
| Botón "Rechazar" | SIN TEST (UI) |
| Selección de `restore` o `quarantine` | `backend/tests/test_actions_router.py::test_reject_returns_action_response_shape`, `::test_reject_with_invalid_action_returns_422` (sólo se aceptan esas dos); `backend/tests/test_actions.py::test_reject_restore`, `::test_reject_quarantine` |
| Modal oculta acciones si el baseline está `absent` (C10) | SIN TEST — rama de UI eliminada en C38; el caso se resuelve del lado del servidor |
| Rechazo sobre baseline `absent` = no-op con warning | `backend/tests/test_actions_router.py::test_reject_with_absent_baseline_reports_the_noop` (el no-op es observable por HTTP vía `baseline_absent: true`); `backend/tests/test_actions.py::test_reject_absent_baseline_noop`; `backend/tests/test_stream_ack_durability_outbox.py::test_reject_baseline_absent_noop_enqueues_no_command` |
| UPDATE optimista (C5); 409 → toast | 409: `backend/tests/test_actions_router.py::test_reject_with_stale_version_returns_409`. Aislamiento por ítem: `backend/tests/test_actions.py::test_bulk_reject_partial`, `::test_bulk_reject_rollback_isolates_failed_item`. El toast: SIN TEST |
| `rejected` + `resolved_at` + `resolved_by` | `backend/tests/test_actions_router.py::test_reject_returns_action_response_shape` (relee de la base); `backend/tests/test_actions.py::test_reject_restore`, `::test_reject_quarantine`, `::test_reject_absent_baseline_noop` — las tres rutas assertan hoy `resolved_by` y `resolved_at`, incluida la del no-op |
| Comando firmado (C7) con `ruleset_version` (C11) | Firma: indirecto — `backend/tests/test_published_command_ack_tracking.py::test_enqueue_restore_file_requires_caller_commit`, `::test_enqueue_restore_file_persists_once_caller_commits`; `backend/tests/test_stream_ack_durability_outbox.py::test_reject_valkey_down_leaves_event_rejected_and_command_pending`, `::test_reject_without_secret_reverts_and_raises`; `backend/tests/test_c31_backend_event_correctness.py::test_fix02_reject_publish_is_post_commit`. `ruleset_version` no se incluye por diseño → criterio no implementado |
| Journal pre-acción (W2) | `agent/tests/test_commands.py::test_journal_written_before_filesystem_op` |
| Journal a `completed`/`failed` con detalle | Indirecto: `agent/tests/test_journal.py::test_journal_mark_completed`, `::test_journal_mark_failed`, `::test_journal_write_pending`, `::test_journal_load_pending`, `::test_journal_delete`, `::test_journal_hmac_valid_roundtrip`, `::test_journal_tampered_content_discarded`, `::test_journal_atomic_write_survives_and_rehydrates`, `::test_journal_missing_hmac_discarded`, `::test_journal_wiring_receives_correct_secret`. Ejecución y ack: `agent/tests/test_commands.py::test_restore_handler_success_publishes_ack`, `::test_restore_handler_no_baseline_publishes_error_ack`, `::test_quarantine_handler_success`, `::test_quarantine_handler_file_not_found_publishes_error_ack`; `agent/tests/test_baseline_restore.py::test_handle_restore_file_from_snapshot`, `::test_handle_restore_file_no_restorable_content` |
| Registro en `audit_log` (W18) | `backend/tests/test_actions.py::test_audit_log_on_reject` |
| Autorización del endpoint | `backend/tests/test_actions_router.py::test_actions_endpoints_require_authentication[/actions/reject]`, `::test_actions_endpoints_reject_non_admin[/actions/reject]` |

---

<a id="us-13"></a>
### 5.13 US-13: Superseded automático — `completa`

| Criterio | Tests |
|---|---|
| El evento anterior pasa a `superseded` | `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`, `::test_mark_superseded_success`, `::test_mark_superseded_wrong_version_returns_false`, `::test_get_pending_returns_most_recent`, `::test_get_pending_returns_none_when_no_pending`; `backend/tests/test_event_status_derivation.py::test_incoming_terminal_event_supersedes_active_pending`, `::test_persisted_terminal_event_is_never_superseded_afterward`; `backend/tests/test_c31_backend_event_correctness.py::test_fix03_race_no_pending_inserts_independent`, `::test_fix03_race_still_pending_returns_none` |
| Vínculo por `parent_event_id` | `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`, `::test_ingest_no_pending_creates_event_without_parent`; `backend/tests/test_event_status_derivation.py::test_incoming_terminal_event_supersedes_active_pending`; expuesto en el detalle: `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` |
| No aparece en la lista de pendientes | `backend/tests/test_event_listing_contract.py::test_list_events_excludes_superseded_by_default`, `::test_superseded_filter_applies_to_total_not_only_to_the_page` |
| Transición validada contra la máquina de estados (C2) | `backend/tests/test_event_service.py::test_validate_valid_pending_to_superseded`, `::test_validate_valid_pending_to_approved`, `::test_validate_valid_pending_to_rejected`, `::test_validate_invalid_terminal_to_pending`, `::test_validate_invalid_pending_to_alert_only`, `::test_validate_all_terminals_have_no_out_edges`; `backend/tests/test_event_consumer_c11.py::test_consumer_invalid_transition_xacks_and_does_not_persist`; `backend/tests/test_event_status_derivation.py::test_forged_status_cannot_induce_backend_exclusive_transitions`, `::test_explicit_status_key_is_ignored` |
| Accesibles para auditoría vía el toggle | `backend/tests/test_event_listing_contract.py::test_list_events_includes_superseded_when_flag_is_true`; serialización del parámetro: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — parsea include_superseded=true` |

Primera historia del anexo en alcanzar `completa`. Vale registrar por qué: sus criterios son todos
de dominio y ninguno describe una pantalla, de modo que el techo de la suite de backend le alcanza.

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
| Modificación de patrón, severidad y acción | `backend/tests/test_rules_service.py::TestWriteOperations::test_update_rule_persists_the_new_field_values`, `::TestWriteOperations::test_update_rule_partial_payload_keeps_untouched_fields` |
| Los cambios se persisten | `backend/tests/test_rules_service.py::TestWriteOperations::test_update_rule_persists_the_new_field_values` (relee la fila tras `expire_all()`, para no leer el objeto en memoria que el servicio ya mutó; verifica además que `updated_at` avanzó y que no se creó una fila nueva). Ruta de error: `backend/tests/test_rules_router.py::test_put_rule_not_found_returns_404` (aserción débil) |
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
| La regla se elimina | `backend/tests/test_rules_service.py::TestWriteOperations::test_delete_rule_removes_the_row` (la fila desaparece y las demás quedan intactas) |
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
| Identificador, estado, última actividad, `ruleset_version`, `queue_size` | Estados: `backend/tests/test_domain_models.py::TestAgentStatus::test_all_canonical_values`. Última actividad: `backend/tests/test_heartbeat_consumer.py::test_heartbeat_marks_online`, `backend/tests/test_agent_mgmt.py::test_dead_to_online_on_heartbeat`. Conteo por estado en la UI: `frontend/src/pages/Dashboard.test.tsx::muestra el estado de conectividad de los agentes registrados`. `ruleset_version` en la vista: SIN TEST. `queue_size`: SIN TEST y no persistido |
| Realce visual de los no-ok | SIN TEST en la vista de Agentes (el realce del dashboard sí: ver US-05) |
| Heartbeat cada 10 s | SIN TEST |
| Sin heartbeat 30 s → `offline` | `backend/tests/test_heartbeat_consumer.py::test_sweep_marks_offline_after_30s`, `::test_sweep_does_not_mark_offline_if_recent`, `::test_sweep_marks_draining_agent_offline_after_30s`, `::test_sweep_keeps_draining_agent_if_heartbeat_is_recent` |
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
| Botones bulk al seleccionar ≥ 1 | Ejercitado (no asertado como criterio aislado) por `frontend/src/components/ui/BulkActionBar.test.tsx`, que hace click en "Rechazar seleccionados" como parte del flujo de rechazo |
| Modal con cantidad y primeros 10 paths | SIN TEST (UI) |
| Elección de acción para el rechazo bulk | `backend/tests/test_actions_router.py::test_bulk_reject_uses_items_contract_with_per_item_action`; cliente: `frontend/src/components/ui/BulkActionBar.test.tsx::rechazar 3 eventos con "quarantine" produce 3 ítems con action:"quarantine" cada uno, sin action al nivel superior del cuerpo`. **Divergencia** (persiste, ver §6): la acción va por ítem en el wire, no una única aplicada a todos los seleccionados como pide la historia — pero la UI sí ofrece la elección única, y el mapeo por ítem ocurre en `BulkActionBar.handleBulkReject` |
| `POST /actions/bulk-approve` / `bulk-reject` | `backend/tests/test_actions_router.py::test_bulk_approve_uses_items_contract_and_partitions_results`, `::test_bulk_reject_uses_items_contract_with_per_item_action`, `::test_bulk_endpoints_accept_an_empty_batch` (el lote vacío devuelve la estructura vacía, no un 500), `::test_actions_endpoints_require_authentication[/actions/bulk-approve]`, `::test_actions_endpoints_require_authentication[/actions/bulk-reject]`, `::test_actions_endpoints_reject_non_admin[/actions/bulk-approve]`, `::test_actions_endpoints_reject_non_admin[/actions/bulk-reject]`, `::test_bulk_reject_request_fixture_matches_pydantic_schema`, `::test_bulk_reject_request_fixture_is_accepted_by_the_real_endpoint`, `::test_bulk_reject_superseded_shape_is_rejected_with_422_naming_the_missing_field` (contrato de wire compartido con el frontend, ver `contracts/actions.bulk-reject.request.json`) |
| Optimistic locking individual (C5) | `backend/tests/test_actions_router.py::test_bulk_approve_uses_items_contract_and_partitions_results` (el ítem en conflicto no arrastra a los demás, verificado releyendo los tres eventos); `backend/tests/test_actions.py::test_bulk_approve_partial`, `::test_bulk_reject_partial`, `::test_bulk_approve_rollback_isolates_failed_item`, `::test_bulk_reject_rollback_isolates_failed_item` |
| `succeeded[]` y `failed[]` con razón | `backend/tests/test_actions_router.py::test_bulk_approve_uses_items_contract_and_partitions_results` (`reason: "conflict"`), `::test_bulk_approve_reports_absent_confirmation_as_failed_item` (`reason: "absent_confirmation_required"`, sin cortar el lote); tests de servicio ya citados |
| Baseline firmado por cada aprobado (C7, C11) | Indirecto: `backend/tests/test_actions.py::test_baseline_update_hmac_valid`; `backend/tests/test_ruleset_version_atomic.py::test_concurrent_increments_no_lost_update` |
| `audit_log` por operación exitosa (W18) | Indirecto: `backend/tests/test_actions.py::test_audit_log_on_approve`, `::test_audit_log_on_reject` (ruta unitaria, no el camino bulk) |
| Resumen visual con detalle expandible | `frontend/src/components/ui/BulkActionBar.test.tsx::muestra un resumen expandible por evento y conserva seleccionados sólo los fallidos`: aserta `button`, `aria-expanded`, path, éxito y razón de fallo |
| Refresco automático de la tabla | El mismo caso aserta invalidación de `['events']`; la conciliación funcional quita sólo éxitos del lote sobre el estado actual, sin perder cambios concurrentes |

Nota de fidelidad del contrato, ahora confirmada por test: el cuerpo es `items[]` con
`{event_id, version, action}`, no `event_ids[]`; y `baseline_absent` no es un motivo de fallo sino un
mapa en la respuesta exitosa.

---

<a id="us-26"></a>
### 5.26 US-26: Paginación de eventos — `parcial`

| Criterio | Tests |
|---|---|
| 50 eventos por página por defecto | `backend/tests/test_event_listing_contract.py::test_list_events_default_page_size_is_50`; `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío` |
| Navegación numerada | SIN TEST y no implementado |
| Input "ir a página" con validación | SIN TEST y no implementado |
| `GET /events?page=N&page_size=50` | `backend/tests/test_event_listing_contract.py::test_list_events_default_page_size_is_50` (segunda página); `backend/tests/test_c31_backend_event_correctness.py::test_fix04_pagination_sql`; `backend/tests/test_event_router.py::test_list_events_returns_200_with_auth`; `frontend/src/utils/eventFilters.test.ts::serializeEventFilters — omite page cuando es 1 (default)`, `::incluye page cuando es mayor a 1` |
| La paginación respeta los filtros activos | `backend/tests/test_event_listing_contract.py::test_pagination_total_respects_status_filter`, `::test_pagination_total_respects_path_prefix_filter`, `::test_pagination_total_respects_date_range_filter`, `::test_superseded_filter_applies_to_total_not_only_to_the_page` — los cuatro usan `page_size=1` para que un `total` mal calculado no quede disimulado por una página que igual entra entera |

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
| Flag a `false` y tokens nuevos | Cubierto de forma incidental: el helper `_full_access_login` de `backend/tests/test_auth.py` completa el cambio y vuelve a loguear verificando `must_change_password is False`, y es precondición de `::test_logout_invalida_access_token` y `::test_logout_invalida_tambien_el_refresh_token`. El backend fuerza re-login en vez de emitir tokens nuevos |
| Bloqueo de otras rutas | `backend/tests/test_c22_scope_gate.py::test_get_events_scope_password_change_only_retorna_403`, `::test_get_event_by_id_scope_password_change_only_retorna_403`, `::test_get_rules_scope_password_change_only_retorna_403`, `::test_get_rule_by_id_scope_password_change_only_retorna_403`, `::test_get_events_full_access_token_no_recibe_403_por_scope`; `backend/tests/test_auth.py::test_change_password_con_scope_password_change_only` |
| Re-exigencia si cierra sin completar | SIN TEST |
| `audit_log` (W18) | SIN TEST — no hay aserciones sobre filas `login`, `logout` ni `change_password` |

---

<a id="us-28"></a>
### 5.28 US-28: Banner de degradación del sistema — `parcial`

| Criterio | Tests |
|---|---|
| Poll de `GET /health/components` cada 10 s | SIN TEST — `refetchInterval: 10_000` existe en `SystemBanner.tsx:23` y ningún test lo verifica |
| Estado de `postgres`, `valkey`, `n8n` y agentes | Backend: `backend/tests/test_notifications.py::test_health_all_ok`, `::test_health_valkey_down`, `::test_health_n8n_degraded_when_not_configured`; `backend/tests/test_health_n8n_check.py::test_n8n_ok_on_200_head`, `::test_n8n_down_on_500`, `::test_n8n_fallback_to_get_when_head_returns_404`, `::test_n8n_fallback_to_get_when_head_returns_405`, `::test_n8n_down_on_403_no_fallback`, `::test_n8n_fallback_to_get_still_fails`, `::test_n8n_fallback_to_get_on_connection_error`, `::test_n8n_degraded_when_not_configured`. **La porción `agents` del resultado del backend sigue sin asertarse**; el consumo de esa porción sí: `frontend/src/components/layout/SystemBanner.test.tsx::trata al subsistema de agentes como degradado cuando su status no es ok` |
| Banner rojo con componente y timestamp | Banner y componente: `frontend/src/components/layout/SystemBanner.test.tsx::muestra un banner rojo que nombra el componente degradado`, `::nombra todos los componentes caidos a la vez` (que además verifica que no nombra al que está sano), `::no muestra ningun banner cuando todos los componentes estan ok`. El timestamp del último check saludable: SIN TEST y no implementado |
| Cerrable y reaparece en el siguiente poll | SIN TEST y no implementado |
| No bloquea la UI | SIN TEST |
| Webhook n8n ante cambio de estado | `backend/tests/test_notifications.py::test_health_state_change_triggers_webhook`, `::test_health_no_webhook_on_first_call` |

`GET /health/components` como endpoint HTTP sigue sin invocarse en ningún test de backend: todos
llaman `check_components()` directamente. Los tests de `backend/tests/test_health.py` apuntan a
`GET /health` (liveness simple), no a `/health/components`.

---

<a id="us-29"></a>
### 5.29 US-29: Visualización y reintento de webhooks fallidos — `parcial`

| Criterio | Tests |
|---|---|
| Banner amarillo con `retry_count >= 3` | Banner: `frontend/src/components/layout/AlertsBanner.test.tsx::muestra un banner amarillo con la cantidad de alertas fallidas en la DLQ`, `::usa el singular cuando hay una sola alerta fallida`, `::consulta unicamente las alertas en estado failed`. **El umbral `retry_count >= 3` no está implementado ni asertado.** Endpoint que lo alimenta: `backend/tests/test_sse_alerts.py::test_get_alerts_filter_status_failed`, `::test_list_alerts_filter_status_failed` |
| Link a la vista de fallidas | `frontend/src/components/layout/AlertsBanner.test.tsx::ofrece un enlace para revisar las alertas fallidas` — el test asserta `href="/alerts"`, no `/notifications/failed` como pide la historia |
| Tabla con `event_id`, primer intento, error y `retry_count` | `backend/tests/test_notifications.py::test_get_failed_alerts_returns_only_failed`, `::test_get_failed_alerts_empty`; `backend/tests/test_sse_alerts.py::test_get_failed_alerts_serializa_status`. Los campos `last_error`, `retry_count` y `failed_at` en la respuesta HTTP: SIN TEST |
| Reintentar / Descartar por fila | Reintentar: `backend/tests/test_notifications.py::test_retry_alert_resets_dlq_state_and_reschedules` (resetea `failed_at`, `last_error` y `retry_count`, y verifica que la cascada se vuelve a disparar sobre la misma alerta y el mismo evento), `::test_retry_alert_delivers_and_leaves_the_dlq` (entrega por n8n, marca el canal y la fila desaparece de `list_failed_alerts`), más las rutas de error `::test_retry_alert_already_delivered`, `::test_retry_alert_not_found`, `::test_post_retry_alert_409_if_delivered`, `::test_post_retry_alert_404_if_not_found`. Descartar: `::test_delete_alert_204`, `::test_delete_alert_404_if_not_found`, `::test_delete_alert_service` |
| Bulk "Reintentar todos" | SIN TEST y sin endpoint (la UI itera reintentos individuales) |
| La fila se elimina tras un reintento exitoso | Cubierto en su efecto observable: `backend/tests/test_notifications.py::test_retry_alert_delivers_and_leaves_the_dlq` asserta `list_failed_alerts(session) == []`. La implementación no borra la fila sino que marca `delivered_at` |
| El banner desaparece con la tabla vacía | `frontend/src/components/layout/AlertsBanner.test.tsx::no muestra ningun banner cuando no hay alertas fallidas` |
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
| Pasa a `offline` o `dead` tras el drenaje | `draining → offline`: `backend/tests/test_heartbeat_consumer.py::test_sweep_marks_draining_agent_offline_after_30s`, con su caso negativo `::test_sweep_keeps_draining_agent_if_heartbeat_is_recent`. `offline → dead`: `backend/tests/test_agent_mgmt.py::test_dead_transition` |

---

<a id="us-31"></a>
### 5.31 US-31: Toggle para mostrar eventos superseded — `parcial`

| Criterio | Tests |
|---|---|
| El filtro oculta `superseded` por defecto | `backend/tests/test_event_listing_contract.py::test_list_events_excludes_superseded_by_default`, `::test_superseded_filter_applies_to_total_not_only_to_the_page`; cliente: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío`, `::include_superseded=false queda como undefined` |
| Checkbox "Mostrar superseded" | SIN TEST |
| Ícono de cadena rota y `parent_event_id` visible | SIN TEST |
| Persistencia en la URL | `frontend/src/utils/eventFilters.test.ts::parseEventFilters — parsea include_superseded=true`, `::serializeEventFilters — serializa include_superseded=true`, `::omite include_superseded cuando es false/undefined`, `::round-trip parse/serialize — preserva filtros complejos en ida y vuelta`, `::filtros vacíos round-trip produce URLSearchParams vacío` |
| `GET /events` respeta el parámetro | `backend/tests/test_event_listing_contract.py::test_list_events_includes_superseded_when_flag_is_true` (con eventos `superseded` reales: `total` pasa de 1 a 2 y el estado aparece en los ítems) |

Sigue vigente la advertencia de que `frontend/src/api/events.ts:88-97` **duplica** la serialización
de filtros en un `paramsSerializer` sin ningún test: el camino que realmente llega al backend no es
el que cubren los tests de `eventFilters.ts`.

---

## 6. Criterios sin test porque no están implementados

Distinguirlos importa: cerrarlos requiere desarrollo, no sólo escribir un test. La lista siguiente
salió del rastreo de código, no del texto de las historias, y se reverificó el 2026-08-19.

| Historia | Criterio | Estado real |
|---|---|---|
| US-01, US-02, US-03 | Cookie de refresh `SameSite=Strict` + `Path=/auth/refresh` | Implementado como `samesite="lax"`, `path="/"` |
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
| US-25 | Acción única aplicada a todo el lote | El contrato lleva acción **por ítem**. Actualizado 2026-08-21: la UI **sí** ofrece una elección única en el modal (`BulkActionBar.tsx`) y el mapeo sobre cada ítem ocurre en el cliente — la divergencia es de la historia respecto del contrato que el backend implementa, no del código respecto de la historia |
| US-25 | Detalle expandible del resumen bulk | Implementado en `BulkActionBar.tsx`; falta aceptación visual e integración contra backend real |
| US-26 | Navegación numerada e input "ir a página" | Sólo "Anterior"/"Siguiente" |
| US-27 | Reglas de complejidad de la contraseña | Sólo se valida longitud ≥ 12 |
| US-27 | `audit_log` de `login` / `logout` / `change_password` | La llamada existe para `change_password`; no hay filas verificadas para login/logout |
| US-05, US-29 | Umbral `retry_count >= 3` en el banner amarillo | `AlertsBanner` reacciona a cualquier alerta `failed` |
| US-29 | Vista `/notifications/failed` | El link del banner apunta a `/alerts` |
| US-28 | Timestamp del último check saludable y cierre manual del banner | No implementados |
| US-29 | Tabla `failed_notifications` con `payload_json` | Su rol lo cumple `alerts`, sin payload |
| US-29 | Bulk retry y `audit_log` de reintento/descarte | No implementados |
| US-30 | Cese de aceptación de eventos ante `SIGTERM`; "Drenando N eventos" | No implementados |

**Salió de esta lista**: el conteo del estado `superseded` en el dashboard (US-04). Faltaba en
`EVENT_STATUSES` y en `statuses`, y ambas listas fueron corregidas al escribirse el test que lo
detectó.

## 7. Brechas ordenadas por costo de cierre

Reordenado el 2026-08-19. De más barata a más cara, con el esfuerzo estimado de escritura de test
asumiendo la infraestructura existente, que hoy incluye tests de componente.

### Cerradas desde la primera versión del anexo

Los diez ítems del nivel 1 original —filtro de `superseded`, orden y `page_size` por defecto, `total`
respetando los filtros, `GET /events/{id}` camino feliz, efecto real de `update_rule` y
`delete_rule`, `resolved_at`/`resolved_by` en reject, camino feliz del reintento de notificación,
`draining → offline`, mensaje de error genérico en login y frontera del clock skew— más los ítems
11 (tests HTTP del router de acciones) y 15 (blacklist post-logout) del nivel 2, y el ítem 21
(infraestructura de tests de frontend) del nivel 3, que quedó instalada y aplicada a tres
componentes.

Vale registrar el saldo, porque es un dato para el Capítulo 5: de todo lo que la matriz marcaba como
"implementado pero sin test", **nada necesitó un `xfail`**. La brecha estaba en los tests. La única
excepción fue el dashboard, donde el test destapó un defecto real de producto (§6).

### Nivel 1 — un test cada una, infraestructura ya disponible

1. **Tests de componente de la tabla de Eventos.** `EventsTable` + `Events`: checkbox por fila y
   "seleccionar todo", aparición de los botones bulk, toggle "Mostrar superseded" y actualización
   dinámica al filtrar. Con `user-event` ya instalado, es la inversión que más criterios cierra de
   una vez: toca **US-06, US-07, US-25 y US-31**.
   **Cerrado parcialmente por `frontend-severity-triage` (2026-08-21)**: `EventsTable.test.tsx`
   cierra el contenido de fila completo de US-06 (§5.6), y `Events.test.tsx` + `BulkActionBar.test.tsx`
   cubren el filtro de severidad y la elección de acción del bulk reject. Siguen sin test el checkbox
   por fila / "seleccionar todo", la aparición de los botones bulk como criterio aislado, y el toggle
   "Mostrar superseded" — el resto de este ítem sigue abierto.
2. **Test de componente del detalle de evento.** `EventDetail`: campos en pantalla, contexto forense
   y link al evento padre. Cierra los criterios de render de **US-08** y **US-10**.
3. **Test de componente del login y del cambio forzado.** `Login` y `ForcePasswordChange`: el
   formulario, el mensaje de error genérico en pantalla y el redirect forzado. **US-01, US-02,
   US-27**.
4. **Porción `agents` de `check_components` del lado backend.** Hoy sólo se asserta desde el
   frontend, que consume un mock. **US-28**, con efecto sobre **US-05** y **US-21**.
5. **`GET /health/components` como endpoint HTTP.** Ningún test lo invoca; todos llaman
   `check_components()` directamente. **US-28**.
6. **`refetchInterval` de 10 s del `SystemBanner`.** Con timers falsos de vitest, un test corto.
   **US-28**.
7. **`ORDER BY created_at DESC` en el listado de alertas.** El equivalente del test de orden que ya
   existe para eventos. **US-19**.
8. **Camino positivo de `notify_if_applicable`.** Que un evento `critical`/`high` cree la `Alert`, la
   publique al broadcaster y dispare el envío. Cierra el criterio demostrado-sólo-por-exclusión de
   **US-23** y el eslabón faltante de **US-20**.
9. **Incremento efectivo de `ruleset_version` en `update_config`.** Hoy sólo se asserta que la fila
   de comando pendiente se crea. **US-24**.

### Nivel 2 — un archivo de tests nuevo, sin cambios de infraestructura

10. **Entrega efectiva por SMTP y por webhook directo.** La cascada sólo se prueba en sus ramas de
    "no configurado". **US-23**.
11. **Argon2id, atributos de la cookie y vida de los tokens.** Verificar el prefijo `$argon2id$` y
    los parámetros C9, el `Set-Cookie` emitido y el `exp` de los tokens. **US-01**. La cookie fallará
    contra el criterio tal como está escrito; hay que decidir antes si se corrige el código o el
    documento (ver nivel 4).
12. **Multi-key JWT (C8).** Requiere dejar de fijar `JWT_SECRET_PREVIOUS = ""` en `conftest.py` para
    un caso específico. **US-03**.
13. **Reconfiguración real de las marcas de `fanotify`.** Reemplazar los dos tests que reimplementan
    la aritmética de conjuntos por uno que invoque `reload_watch_paths` y verifique
    `FAN_MARK_ADD` / `FAN_MARK_REMOVE`. **US-24**.
14. **Ciclo de vida del journal integrado con los handlers.** Que `handle_restore_file` y
    `handle_quarantine_file` dejen el journal en `completed` o `failed`. **US-12**.
15. **`event_ack` de `baseline_update` del lado agente** y avance de `ruleset_version_applied` ante
    el ack de `update_config`. **US-11**, **US-24**.
16. **Timeout de 30 s del drenaje.** `_drain_then_stop(..., timeout=30.0)` no lo invoca ningún test.
    **US-30**.
17. **Tests de componente de Rules y Agents.** Formulario precargado, confirmación de borrado,
    botones deshabilitados en `draining` con su tooltip. **US-16, US-17, US-22, US-24, US-30**.
18. **Reemplazar las aserciones débiles.** Los tests de `test_rules_router.py` y
    `test_event_router.py` que aceptan `401` o `(404, 401)` como válidos deberían fijar el código
    esperado, ahora que el patrón de autenticación real de `test_actions_router.py` y
    `test_event_listing_contract.py` muestra cómo hacerlo sin sobreescribir `get_current_user`.

### Nivel 3 — requiere infraestructura o entorno adicional

19. **Verificar que los tests de Postgres no se saltean en la corrida oficial.**
    `test_event_listing_contract.py` y `test_actions_router.py` se saltean enteros si falta
    `psycopg`, y sostienen buena parte de esta matriz. Conviene que la Batería 2 falle en vez de
    reportarlos como `skipped`.
20. **Migrar los módulos "patrón A" a Postgres real.** Varios tests usan SQLite en memoria; las
    afirmaciones sobre persistencia son a nivel de ORM. Afecta la fuerza probatoria de varias
    historias, no su clasificación.
21. **Tests de routing y guardas de ruta en el frontend.** El redirect forzado de US-27, el bloqueo
    de navegación con `must_change_password` y la reconexión SSE de US-20 necesitan montar el árbol
    de rutas, no un componente suelto.

### Nivel 4 — requiere decidir antes de codificar

22. **Divergencias historia ↔ implementación.** Antes de escribir un test hay que resolver cuál de
    los dos textos manda, y asentarlo en el appendix de decisiones del documento canónico
    correspondiente. Los casos son: el hash del baseline en approve (US-11 vs. D2), los atributos de
    la cookie de refresh (US-01/W9), el `event_ack` de `rule_sync` (US-18 vs. la decisión de
    `ack_status` NULL), la re-emisión de tokens tras el cambio de password (US-27), la tabla
    `failed_notifications` y el umbral `retry_count >= 3` (US-05/US-29), la acción por ítem en bulk
    (US-25) y el `ruleset_version` en los comandos de acción correctiva (US-12) y de re-scan (US-22).

    Este grupo es hoy el techo real del anexo: **US-05 no puede alcanzar `completa`** sin resolver el
    umbral del banner amarillo, y varias `parcial` dependen de decisiones análogas.

---

## 8. Reproducción

Este anexo se construyó leyendo el código; no depende de una corrida. Para verificar cualquier fila:

```bash
# Backend — requiere Postgres y Valkey efímeros (ver backend/tests/conftest.py)
docker run --rm -d --name fim-test-db \
  -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fim_test \
  -p 5432:5432 postgres:18.3
docker run --rm -d --name fim-test-valkey -p 6379:6379 valkey/valkey:9.0.3

# Un test puntual del backend
pytest backend/tests/test_event_listing_contract.py::test_list_events_excludes_superseded_by_default -v

# Un test parametrizado del router de acciones
pytest "backend/tests/test_actions_router.py::test_actions_endpoints_reject_non_admin[/actions/approve]" -v

# Un test puntual del agente (no necesita servicios)
pytest agent/tests/test_commands.py::test_journal_written_before_filesystem_op -v

# Frontend — jsdom, sin servicios
cd frontend && pnpm test
cd frontend && pnpm test src/pages/Dashboard.test.tsx
```

Si en el futuro se adopta la opción (a) del plan de medición (`@pytest.mark.us("US-07")`), esta
matriz sirve como fuente para el marcado inicial y como control cruzado del resultado.
