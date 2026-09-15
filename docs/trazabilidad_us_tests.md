# Anexo — Matriz de trazabilidad: historias de usuario ↔ tests automatizados

> Elaborado el 2026-08-18 sobre la rama `devel`. **Actualizado el 2026-09-11** con las verificaciones
> posteriores identificadas en cada historia, sobre candidatos congelados con base HEAD `6948aae`.
> La revisión inicial del 2026-08-19 siguió a los commits
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
| `completa` | **13** | US-02, US-03, US-04, US-05, US-06, US-12, US-13, US-16, US-17, US-20, US-21, US-25, US-31 |
| `parcial` | **18** | US-01, US-07, US-08, US-09, US-10, US-11, US-14, US-15, US-18, US-19, US-22, US-23, US-24, US-26, US-27, US-28, US-29, US-30 |
| `sin cobertura` | **0** | — |

Situación anterior a la revisión (2026-08-18): 0 `completa`, 28 `parcial`, 3 `sin cobertura`.
Situación tras la change `frontend-severity-triage` (2026-08-21): US-06 cierra su cuarto y último
criterio (fila con severidad y proceso causante) y pasa de `parcial` a `completa`.

El corte inmediatamente anterior a la implementación posterior de US-09 tenía **10 completas,
20 parciales y 1 sin cobertura**. Tras esa implementación, US-09 pasa a parcial, no a completa:
el flujo textual está integrado y probado, pero la historia canónica también exige comparación de
hashes y hex dump para binarios, detección de modo en el visor y `react-diff-viewer-continued`.

**Lo que el Capítulo 5 puede afirmar con esta evidencia:** que las 31 historias tienen al menos una
cobertura automatizada y que 10 tienen todos sus criterios funcionales asertados — pero **no** que
las 31 historias estén completas.

Tres matices que conviene declarar junto al número, porque explican la forma del resultado:

1. **El sesgo era estructural y se corrigió en parte.** La suite era densa donde el sistema es
   riesgoso (máquina de estados de eventos, HMAC, outbox transaccional, cola offline, cifrado de
   baseline) y nula donde el sistema es visual, porque `vitest` corría sin DOM. Con `jsdom` y
   Testing Library ya instalados, la brecha dejó de ser infraestructural y pasó a ser de alcance:
   hay tres componentes con tests y el resto sin ellos.
2. **En muchas de las 22 `parcial`, el criterio que falta no es un test sino una función.** Se listan en
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
| **US-02** Cierre de sesión | Botón; limpieza de token; blacklist del `jti` en Valkey con TTL; redirección; 401 posterior | `test_auth.py` (2), `auth.test.ts`, `Navbar.test.tsx`, `auth.store.test.ts`, `us02-logout.spec.ts` — [§5.2](#us-02) | **completa** | La corrección posterior envía el Bearer al endpoint autenticado de logout. Unitarias y Playwright real verifican botón, limpieza local, revocación de access/refresh, cookie eliminada, redirección, Back seguro y comunicación explícita cuando la revocación remota no puede confirmarse. |
| **US-03** Renovación de sesión | Refresh anticipado; rotación single-use; blacklist → login; transparencia; multi-key JWT | Unitarios; `us03-session-refresh.spec.ts`; cookie/ruta/logout/reuso y rotación live en `us-isolated-lab.spec.ts`/runner — [§5.3](#us-03) | completa | Cookie `Strict`+`/auth/refresh`, migración legacy, revocación por `refresh_jti` y CURRENT/PREVIOUS ejecutados. |
| **US-04** Métricas del dashboard | Conteo por los 7 estados; léxico en minúsculas C1; carga al entrar; indicadores numéricos | `Dashboard.test.tsx` (4) — [§5.4](#us-04) | **completa** | Los cuatro criterios asertados sobre el componente real. El test mockea `@/api/client` y no `@/api/dashboard`, así que ejercita la agregación real del cliente (N requests a `/events`, una por estado). **Encontró un defecto real**: el dashboard enumeraba 6 de los 7 estados canónicos — faltaba `superseded` en `EVENT_STATUSES` (`Dashboard.tsx`) y en `statuses` (`api/dashboard.ts`) —, de modo que los eventos `superseded` no aparecían en ningún contador. Corregido en ambas listas |
| **US-05** Estado general del sistema | Pendientes sin resolver; conectividad de agentes; realce de críticos; banner rojo; banner amarillo | `Dashboard.test.tsx` (5), `SystemBanner.test.tsx` (4), `AlertsBanner.test.tsx` (7) — [§5.5](#us-05) | **completa** | El quinto criterio cierra por decisión, no por regresión de exigencia: `docs/historias_de_usuario.md` fue corregida en paralelo al change `backlog-partial-stories-completion` (Change 55) a la definición D6/RN-102 (fallo terminal, sin umbral `retry_count`), que es también la que `AlertsBanner` implementa hoy (`GET /alerts/failed/count`, D-3). El test asserta exactamente lo que la historia vigente pide |
| **US-06** Listado de eventos | Tabla paginada 50/página; fila con path, estado, acción, severidad, fecha y proceso causante; orden desc; excluye `superseded` | `test_event_listing_contract.py` (4), `test_c31_backend_event_correctness.py` (1), `eventFilters.test.ts` (2), `EventsTable.test.tsx` (5) — [§5.6](#us-06) | **completa** | Change `frontend-severity-triage` (2026-08-21) cerró el cuarto criterio: `EventsTable.tsx` ahora renderiza severidad (banda de borde + texto canónico) y proceso causante como sublínea del path, con caso negativo para el evento sin contexto de proceso. El "tipo de acción" del criterio se satisface por la columna Estado (D35/RN-129: el `status` derivado *es* la acción ejecutada), sin campo nuevo. Los cuatro criterios quedan asertados sobre el componente real |
| **US-07** Filtrado por estado | Selector de los 7 estados; multi-selección; `superseded` excluido; toggle; actualización dinámica | `test_event_listing_contract.py` (3), `eventFilters.test.ts` (4) — [§5.7](#us-07) | parcial | La selectividad real del filtro quedó probada: `test_pagination_total_respects_status_filter` verifica que `total` cuenta sólo el estado pedido y que el ítem devuelto es de ese estado, y `test_status_filter_accepts_multiple_values` que el parámetro repetible es una unión. Siguen sin test los tres criterios de interfaz, y el selector **enumera 6 estados**, no 7 |
| **US-08** Detalle de un evento | Vista de detalle; campos; timestamps dobles con clock skew W13; contexto forense del proceso; enlace al padre; posición en la cadena | `test_event_listing_contract.py` (2), `test_stream_ack_durability_consumer.py` (11), `test_consumer.py` (1), `test_c31_backend_event_correctness.py` (2), `test_event_severity.py` (1), `test_event_symlink_metadata.py` (2), `test_event_ack_status_field.py` (3), `test_detector_context.py` (4) — [§5.8](#us-08) | parcial | Dos huecos grandes cerrados. `test_get_event_by_id_returns_full_detail` es el primer test de camino feliz del detalle: 200 y el conjunto de campos, con el contexto forense (`process_pid`/`uid`/`exe`) verificado ya persistido y expuesto, no sólo capturado en el agente. Y la frontera del clock skew quedó fijada a 299 s / 301 s en las **dos** ramas (con `sent_at` y por fallback sobre `detected_at`), incluida una aserción de que `_CLOCK_SKEW_S == 300`. Falta "tipo de acción", que no existe como campo, y la posición en la cadena |
| **US-09** Diff de un evento | Diff lado a lado/unificado; sólo texto; binarios con hashes y hex dump; detección automática; escapado W8; nunca loguear el diff W6 | Pruebas dirigidas de agente/backend/frontend sobre `8039624` + `f08626a` — [§5.9](#us-09) | **parcial** | El patch textual está integrado en el detalle autenticado, limitado a UTF-8 y 1 MiB y verificado. Los binarios se descartan: no hay comparación de hashes ni hex dump; el visor tampoco usa `react-diff-viewer-continued`. |
| **US-10** Cadena de eventos | Acceso a la cadena del path; orden cronológico con marca de `superseded`; navegación; ícono de cadena rota y `parent_event_id` | `test_event_service.py` (5), `test_event_status_derivation.py` (2), `test_c31_backend_event_correctness.py` (3), `test_c22_fk_chain.py` (3), `modules/events/test_retention.py` (3) — [§5.10](#us-10) | parcial | Sin cambios. El **modelo de datos** de la cadena está entre lo mejor cubierto del repositorio (supersesión optimista, `parent_event_id`, compactación a 10, protección por `audit_log`, carreras). La **funcionalidad de usuario** no existe: no hay endpoint que devuelva la cadena de un path, y `EventTimeline.tsx` documenta que quedó fuera de alcance |
| **US-11** Aprobación de un evento | Botón; UPDATE optimista C5; `approved` + `resolved_at`/`resolved_by`; baseline con hash actual; comando firmado C7 + C11; agente rechaza firma/versión; re-cifrado W10; `event_ack` C3; warning de archivo ausente; `audit_log`; 409 + toast | `test_actions_router.py` (11), `test_actions.py` (7), `test_c31_backend_event_correctness.py` (1), `test_stream_ack_durability_outbox.py` (4), `test_command_ack_consumer.py` (9), `test_commands.py` (5), `test_baseline.py` (7), `EventDetail.test.tsx` (5) — [§5.11](#us-11) | parcial | El hueco transversal del router quedó cerrado: `ConflictError → 409` con `detail.code`, `AbsentConfirmationRequired → 422` **contrastado contra un 422 de validación de Pydantic**, `require_admin` parametrizado sobre los cuatro endpoints, y la forma exacta de `ActionResponse` con el evento releído de la base. El change `backlog-partial-stories-completion` (Change 55) cerró el toast del 409 y el warning de archivo ausente en la UI, con el texto literal de la historia (D-6). El criterio "baseline con el **hash actual**" sigue sin test y sin implementación por decisión: `test_no_get_file_hash_published` asserta la decisión contraria (D2, registrada como divergencia cerrada, no como huella abierta) |
| **US-12** Rechazo de un evento | Botón; elección `restore`/`quarantine`; modal ante baseline `absent` C10; no-op con warning; UPDATE optimista; `rejected` + campos; comando firmado C7 + C11; journal pre-acción W2; `audit_log` | `test_actions_router.py` (8), `test_actions.py` (5), `test_stream_ack_durability_outbox.py` (3), `test_published_command_ack_tracking.py` (2), `test_commands.py` (5), `test_journal.py` (9), `test_baseline_restore.py` (2), `test_event_router.py` (4), `RejectModal.test.tsx` (3), `test_journal_state_after_action_handlers.py` (4), `EventDetail.test.tsx` (1) — [§5.12](#us-12) | **completa** | Cerrado por el change `backlog-partial-stories-completion` (Change 55): C10 ya no es un no-op invisible para el admin — `GET /events/{id}.baseline_status` (D-8) alimenta a `RejectModal`, que oculta las opciones correctivas y muestra el texto literal del criterio. Los handlers `restore_file`/`quarantine_file` ahora tienen test del estado final del journal (`completed`/`failed` con `error`). `ruleset_version` en estos comandos queda excluido por D66/RN-160 — decisión cerrada, no brecha |
| **US-13** Superseded automático | Nuevo evento supersede al `pending`; vínculo `parent_event_id`; no aparece en pendientes; transición validada C2; accesible por el toggle | `test_event_listing_contract.py` (3), `test_event_service.py` (7), `test_event_status_derivation.py` (5), `test_c31_backend_event_correctness.py` (2), `test_event_consumer_c11.py` (1), `test_c22_consumer.py` (1) — [§5.13](#us-13) | **completa** | Era la más cerca de cerrarse y se cerró. `test_list_events_excludes_superseded_by_default` cubre el único criterio que faltaba, y `test_superseded_filter_applies_to_total_not_only_to_the_page` agrega el matiz que hacía falta para que la exclusión sea coherente con la paginación: el `superseded` excluido tampoco cuenta en `total`. El acceso para auditoría queda cubierto por `test_list_events_includes_superseded_when_flag_is_true` |
| **US-14** Listado de reglas | Tabla; fila con patrón, severidad y acción; leyenda del default `alert_only`; `ruleset_version` del sistema | `test_rules_service.py` (3), `test_rules_router.py` (2), `test_rules.py` (1) — [§5.14](#us-14) | parcial | Sin cambios. Sólo el listado y su orden canónico por severidad están asertados. El `ruleset_version` global del sistema **no lo expone ningún endpoint**: lo que la UI muestra es `ruleset_version_applied` por agente, que es otra cosa |
| **US-15** Creación de regla | Formulario; glob y negación `!`; la exclusiva gana; persistencia; patrón no duplicado; `ruleset_version++` C11 + sync; `audit_log` | `test_rules_service.py` (10), `test_rules_router.py` (3), `test_ruleset_version_atomic.py` (2), `test_rules.py` (3) — [§5.15](#us-15) | parcial | Sin cambios. La precedencia de reglas exclusivas está probada **sólo en el agente**: `rules/service.py::determine_severity_for_path` hace `fnmatch` sin tratar el prefijo `!`. La validación de patrón duplicado no está implementada |
| **US-16** Edición de regla | Formulario precargado; modificar patrón/severidad/acción; persistencia; `ruleset_version++` + sync; `audit_log` | Unitarios previos + `us-isolated-lab.spec.ts` — [§5.16](#us-16) | **completa** | Playwright real verifica precarga/edición y el laboratorio verifica persistencia, auditoría, incremento exacto +1 y convergencia DB/agente. Pendiente separado: asociación accesible de labels, no criterio funcional de esta historia. |
| **US-17** Eliminación de regla | Opción de borrar; confirmación; eliminación de la fila; `ruleset_version++` + sync; caída al default `alert_only`; `audit_log` | Unitarios previos + `us-isolated-lab.spec.ts` — [§5.17](#us-17) | **completa** | Cancelar no emite DELETE; confirmar elimina, incrementa exactamente +1, converge con el agente y el siguiente cambio propio cae a `alert_only`. Pendiente separado: labels accesibles de RuleForm. |
| **US-18** Sync automática de reglas | Publica `rule_sync`; firma C7 + `ruleset_version` C11; el agente verifica firma; descarta versiones menores; reemplaza caché sin reiniciar; persiste en `state.json`; comandos antes que eventos W4; `event_ack` C3 | `test_rules_service.py` (8), `test_rule_sync_outbox.py` (4), `test_c32_sse_security_fixes.py` (1), `test_rules.py` (5), `test_stability_fixes.py` (2), `test_reconnect_order.py` (7) — [§5.18](#us-18) | parcial | Sin cambios. Siete de ocho criterios asertados, incluido el orden de reconexión W4 y la persistencia del `ruleset_version` en `state.json`. El único que falla —`event_ack` tras `rule_sync`— no está implementado, y los tests **documentan la decisión contraria** (`test_rule_sync_persists_with_null_ack_status`) |
| **US-19** Listado de alertas | Lista ordenada por fecha desc; fila con path, severidad, acción, fecha y canal; navegación al evento | `test_sse_alerts.py` (10) — [§5.19](#us-19) | parcial | Sin cambios. El endpoint, sus filtros y la paginación están bien cubiertos; los tres criterios *de la historia*, no. `AlertResponse` no expone `path` ni tipo de acción, la navegación al evento no está implementada, y el `ORDER BY created_at DESC` no lo asserta ningún test |
| **US-20** Alertas en tiempo real | Conexión SSE; alerta ante nuevo evento; notificación visual; reconexión automática | Unitarios previos + `us20-realtime-alerts.spec.ts` — [§5.20](#us-20) | completa | Un proxy exclusivo del laboratorio permitió cortar físicamente sólo la ruta SSE. Dos corridas individuales y dos combinadas probaron cierre, API y refresh 200 durante el corte, segunda respuesta SSE establecida antes de publicar y toast para un evento real posterior. |
| **US-21** Estado de agentes | Lista; identificador, estado, última actividad, `ruleset_version`, `queue_size`; realce de no-ok; heartbeat 10 s / 30 s → offline / 5 min → dead + webhook / `shutdown` → draining; banner de `queue_pressure` W3 | `test_agent_mgmt.py` (5), `test_heartbeat_consumer.py` (6), `test_agent_watch_path_status.py` (2), `test_domain_models.py` (1), `test_queue.py` (4) — [§5.21](#us-21) | parcial | La máquina de estados del heartbeat quedó completa en sus transiciones (online → draining → offline@30s → dead@5min → vuelta a online, y ahora también draining → offline). Sin cobertura: el intervalo de 10 s, el webhook n8n al pasar a `dead` (no implementado), `queue_size` en la vista (no se persiste) y el umbral del 80% de W3, que no existe en el código |
| **US-22** Re-scan de baseline | Botón con selección de paths; diálogo con los `pending` afectados; confirmación explícita; supersesión + comando firmado C7 con `ruleset_version++` C11; el agente verifica firma y versión; regenera baseline cifrado W10; `event_ack` C3; confirmación visual; `audit_log`; deshabilitado si `draining` | `test_agent_mgmt.py` (4), `test_published_command_ack_tracking.py` (1), `test_stream_ack_durability_outbox.py` (1), `test_agent_config.py` (5), `test_commands.py` (3), `test_baseline.py` (7) — [§5.22](#us-22) | parcial | Sin cambios. El flujo existe de punta a punta y ese eje está bien cubierto. Tres criterios fallan por implementación: no hay selección de paths, el comando no lleva `ruleset_version++`, y `handle_rescan_baseline` no tiene guard de versión. La supersesión alcanza a **todos** los pending del agente, no a los paths seleccionados |
| **US-23** Notificación externa | Webhook n8n ante `critical`/`high`; payload con contexto de proceso y timestamps; n8n como enrutador; retry 5/30/120 s; cascada SMTP → webhook → log; fila en DLQ; n8n caído no compromete la operación | `test_notifications.py` (16), `test_c31_backend_event_correctness.py` (2), `test_health_n8n_check.py` (8) — [§5.23](#us-23) | parcial | Sin cambios. El retry con los delays exactos y la caída a DLQ son el núcleo mejor asertado. El criterio "sólo `critical`/`high`" se demuestra **por exclusión**, nunca por inclusión. El payload no incluye `process_pid`/`uid`/`exe`, `received_at` ni la acción tomada → criterio incumplido en el código. La entrega efectiva por SMTP y por webhook directo nunca se asserta con éxito |
| **US-24** Paths monitoreados | Lista de paths por agente; agregar; quitar; persistencia; `update_config` firmado C7 + `ruleset_version++` C11; el agente verifica y recarga en caliente; baseline scan de paths nuevos W10; `event_ack` C3; bootstrap desde YAML → autoridad en PostgreSQL; `audit_log`; deshabilitado si `draining` | `test_agent_mgmt.py` (5), `test_agent_watch_path_status.py` (3), `test_published_command_ack_tracking.py` (2), `test_agent_config.py` (6), `test_commands.py` (5), `test_stability_fixes.py` (2), `test_audit_fixes.py` (1) — [§5.24](#us-24) | parcial | Sin cambios. La historia mejor cubierta del lado backend + agente. Se mantiene la advertencia metodológica: `test_reload_watch_paths_marks_new` y `::test_reload_watch_paths_unmarks_removed` **no invocan el método que dicen probar** — reimplementan la aritmética de conjuntos dentro del propio test. La reconfiguración real de las marcas de `fanotify` no está verificada por ningún test |
| **US-25** Bulk approve/reject | Checkbox por fila y "todo en la página"; botones bulk; modal; acción compartida; `event_ids[]`; locking C5; resultados; baseline; auditoría; resumen/refresco | Unitarios + `us25-bulk-actions.spec.ts` + `us-isolated-lab.spec.ts` — [§5.25](#us-25) | completa | Wire canónico, rechazo 422 de legacy, UX/parcialidad y cadena approve→comando→agente→ACK→baseline pasaron. |
| **US-26** Paginación | 50 por página; navegación numerada; input "ir a página"; `?page=N&page_size=50`; respeta los filtros activos | `test_event_listing_contract.py` (5), `test_c31_backend_event_correctness.py` (1), `test_event_router.py` (1), `eventFilters.test.ts` (3) — [§5.26](#us-26) | parcial | El riesgo silencioso más grande quedó cubierto con tres tests: `total` respeta el filtro de estado, el `path_prefix` y el rango de fechas — cada uno con `page_size=1` para que un `total` mal calculado no se disimule. Los criterios 2 y 3 siguen sin test porque **no están implementados**: sólo hay "Anterior"/"Siguiente" |
| **US-27** Cambio obligatorio de password | Seed con el flag; scope `password_change_only`; redirect forzado; formulario con complejidad; validación de la actual; Argon2id C9; flag a `false` + tokens nuevos; bloqueo de otras rutas; re-exigencia; `audit_log` | `test_auth.py` (24), `test_c22_auth.py` (1), `test_c22_scope_gate.py` (5), `modules/users/test_user_management.py` (3), `ForcePasswordChange.test.tsx` (8) — [§5.27](#us-27) | parcial | El change `backlog-partial-stories-completion` (Change 55) cerró siete de los diez criterios: complejidad (mayúscula/minúscula/dígito, con paridad ASCII/`Ñ` entre backend y frontend), `current_password` exigido también con scope `password_change_only` (D-2), Argon2id C9, flag a `false`, re-exigencia tras no completar el cambio, y el `audit_log` de `change_password`. Persisten sin test: el redirect forzado (ver §5.1) y el `audit_log` de `login`/`logout` |
| **US-28** Banner de degradación | Poll cada 10 s; estado de `postgres`, `valkey`, `n8n` y agentes; banner rojo con componente y timestamp; cerrable y reaparece; no bloquea; webhook ante cambio de estado | `SystemBanner.test.tsx` (4), `test_notifications.py` (5), `test_health_n8n_check.py` (8) — [§5.28](#us-28) | parcial | El banner dejó de estar sin test: se asserta que no aparece con todo `ok`, que nombra el componente caído, que trata el subsistema `agents` como degradado y que nombra varios caídos a la vez sin inventar uno sano. Quedan tres huecos: el poll de 10 s (`refetchInterval: 10_000` existe en `SystemBanner.tsx` y ningún test lo verifica), la porción `agents` de `check_components` **del lado backend**, y `GET /health/components` como endpoint HTTP, que ningún test invoca. Dos criterios de UI no están implementados: timestamp del último check saludable y botón de cierre |
| **US-29** Webhooks fallidos | Banner amarillo con `retry_count >= 3`; link a la vista; tabla con `event_id`, primer intento, error y `retry_count`; reintentar/descartar por fila; bulk; eliminación tras reintento exitoso; el banner desaparece; `audit_log` | `test_notifications.py` (19), `AlertsBanner.test.tsx` (7), `test_sse_alerts.py` (3), `FailedAlerts.test.tsx` (3) — [§5.29](#us-29) | parcial | El change `backlog-partial-stories-completion` (Change 55) cerró el banner (`GET /alerts/failed/count`, D-3/D-4, sin umbral por D6/RN-102, texto y link literales a `/alerts/failed`), el `audit_log` de reintento y descarte (D-5, con fila por cada llamada del bulk) y la UI de reintentar/descartar por fila y en bloque. Persisten sin cerrar: los campos `last_error`/`retry_count`/`failed_at` en la respuesta HTTP sin test dedicado, y la tabla `failed_notifications` que no existe (su rol lo cumple `alerts`) |
| **US-30** Agente en shutdown graceful | Deja de aceptar eventos; drena con timeout 30 s; heartbeat con `shutdown: true`; backend marca `draining`; indicador "Drenando N eventos"; botones deshabilitados con tooltip; pasa a `offline`/`dead` | `test_shutdown_heartbeat.py` (5), `test_heartbeat_consumer.py` (3), `test_stability_fixes.py` (1), `test_agent_mgmt.py` (1), `test_publisher.py` (1), `test_reconnect_order.py` (2) — [§5.30](#us-30) | parcial | La transición `draining → offline` quedó cubierta con su caso negativo (un agente drenando que sigue latiendo no se marca offline): era la rama del `status.in_([online, draining])` que nunca se ejercitaba. Siguen sin test o sin implementación el cese de aceptación de eventos de `fanotify`, el timeout de 30 s del drenaje (`_drain_then_stop(..., timeout=30.0)` no lo invoca ningún test) y los dos criterios de interfaz |
| **US-31** Toggle de superseded | Oculto por defecto; checkbox; ícono de cadena rota y `parent_event_id`; persistencia en la URL; `GET /events` respeta el parámetro | Unitarios previos + `EventsTable.test.tsx` + `us31-superseded-toggle.spec.ts` — [§5.31](#us-31) | **completa** | Toggle, URL, request real y reload pasaron; el vínculo conserva su semántica accesible y muestra `parent_event_id` como texto visible. |

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
| `must_change_password` → scope `password_change_only`, redirige a `/change-password` (W20) | Scope: `backend/tests/test_auth.py::test_login_primer_admin_must_change_password_true`, `::test_scope_password_change_only_en_access_token`, `backend/tests/test_c22_auth.py::test_create_access_token_scope_password_change_only_sigue_teniendo_type_access`. La ruta `/change-password` del criterio ya coincide con la implementada (`frontend/src/App.tsx`) — divergencia de nomenclatura cerrada por trazabilidad pura (D-9 del design de `backlog-partial-stories-completion`, Change 55), sin cambio de comportamiento; el redirect en sí sigue SIN TEST (ver §5.27) |

Los tests de rate limit leen `settings.rate_limit_login_attempts` en vez de fijar 5 y 900, de modo
que los valores del criterio quedan verificados sólo en tanto se respeten los defaults de
`backend/app/core/config.py:51-52`.

---

<a id="us-02"></a>
### 5.2 US-02: Cierre de sesión — `completa`

| Criterio | Tests |
|---|---|
| Botón de logout visible | `frontend/src/components/layout/Navbar.test.tsx`; `frontend/e2e/us02-logout.spec.ts`. |
| Limpieza del access token e invalidación de la cookie | Lado servidor: `backend/tests/test_auth.py::test_logout_invalida_tambien_el_refresh_token`. Cliente y navegador real: `Navbar.test.tsx`, `auth.store.test.ts` y `us02-logout.spec.ts`. |
| `jti` del refresh en blacklist con TTL restante (C8) | `backend/tests/test_auth.py::test_logout_invalida_access_token` (TTL del access acotado a `ACCESS_TOKEN_EXPIRE_MINUTES * 60` y verificado como recién emitido), `::test_logout_invalida_tambien_el_refresh_token` (TTL del refresh dentro de la ventana de `REFRESH_TOKEN_EXPIRE_DAYS`) |
| Redirección al login | `frontend/src/components/layout/Navbar.test.tsx`; Playwright verifica `/login` y que Back no reabra la vista protegida. |
| Solicitudes posteriores con token invalidado → 401 | `backend/tests/test_auth.py::test_logout_invalida_access_token` y `::test_logout_invalida_tambien_el_refresh_token`; Playwright repite ambos probes contra el stack real. |

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
### 5.3 US-03: Renovación automática de sesión — `completa`

| Criterio | Tests |
|---|---|
| El frontend pide un token nuevo antes de que expire | `frontend/src/stores/auth.store.test.ts::renueva una vez sesenta segundos antes de expirar y reemplaza el token en memoria`; `::un token ilegible no dispara refresh basado en claims no verificadas` |
| El refresh rota en cada uso (C8) | `backend/tests/test_auth.py::test_refresh_valido_rota_token`, `::test_refresh_con_token_revocado_retorna_401`; single-flight cliente: `frontend/src/api/auth.test.ts` (2) |
| Refresh expirado o revocado → login | Contratos backend anteriores; cliente: `frontend/src/stores/auth.store.test.ts::si el refresh anticipado falla limpia la sesión local`, `frontend/src/components/layout/ProtectedRoute.test.tsx::navega una sola vez a login cuando una sesión ya verificada queda sin token` |
| Renovación transparente | `frontend/src/api/client.test.ts::reintenta la petición original con el token rotado después de un 401`; además, ventana de gracia backend y single-flight cliente ya citados |
| Multi-key `JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS` (C8) | Unitarios y rotación live en `scripts/run-isolated-acceptance-lab.sh`: access/refresh previos 200, clave ajena 401 y nuevo CURRENT 200 |
| Cookie canónica y revocación | `backend/tests/test_auth.py::test_login_migra_cookie_legacy_y_emite_cookie_canonica`, `::test_logout_revoca_refresh_jti_sin_recibir_cookie_canonica`, `::test_gracia_no_resucita_refresh_ganador_revocado_por_logout`, `::test_gracia_no_resucita_refresh_ganador_revocado_por_change_password_sin_cookie`; `us-isolated-lab.spec.ts::US-03...` observa URL exacta, atributos, rotación, logout y reuso 401 |

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
### 5.5 US-05: Estado general del sistema — `completa`

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): el quinto
criterio ya no diverge del texto de la historia — `docs/historias_de_usuario.md` fue alineada a
D6/RN-102 (fallo terminal sin umbral) por el equipo de documentación, y `AlertsBanner` implementa
exactamente eso (`GET /alerts/failed/count`, sin `retry_count >= 3`, D-3 del design).

| Criterio | Tests |
|---|---|
| Cantidad de `pending` sin resolver | `frontend/src/pages/Dashboard.test.tsx::Dashboard — US-05: estado general del sistema — indica cuantos eventos pending hay sin resolver` |
| Conectividad de agentes | `frontend/src/pages/Dashboard.test.tsx::muestra el estado de conectividad de los agentes registrados` (cuenta `online`, `offline`, `draining` y `dead` por separado); a nivel de enum: `backend/tests/test_domain_models.py::TestAgentStatus::test_all_canonical_values` |
| Realce de `pending` con severidad `critical`/`high` | `frontend/src/pages/Dashboard.test.tsx::destaca visualmente los pending critical/high cuando existen` y `::no destaca la tarjeta de pending critical/high cuando no hay ninguno` (par positivo/negativo: compara la clase de la tarjeta contra la de una tarjeta normal, de modo que un realce permanente fallaría) |
| Banner rojo de degradación | `frontend/src/components/layout/SystemBanner.test.tsx::no muestra ningun banner cuando todos los componentes estan ok`, `::muestra un banner rojo que nombra el componente degradado`, `::trata al subsistema de agentes como degradado cuando su status no es ok`, `::nombra todos los componentes caidos a la vez`; el estado de infraestructura en el dashboard: `frontend/src/pages/Dashboard.test.tsx::muestra el estado de la infraestructura monitoreada` |
| Banner amarillo de notificaciones fallidas (D6/RN-102, sin umbral) | `frontend/src/components/layout/AlertsBanner.test.tsx::muestra un banner amarillo con el texto literal de US-29 cuando count=4`, `::no muestra ningun banner cuando count=0`, `::el enlace apunta a /alerts/failed`, `::consulta GET /alerts/failed/count`, `::usa el singular cuando count=1`, `::una alerta con retry_count=0 (n8n sin configurar) igual cuenta — sin umbral`, `::el banner desaparece cuando un refetch devuelve count=0`; endpoint: `backend/tests/test_notifications.py::test_get_failed_alerts_count_ignores_retry_count_threshold`, `::test_get_failed_alerts_count_empty_dlq`, `::test_get_failed_alerts_count_requires_admin` |

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
### 5.9 US-09: Visualización de diff — `parcial`

En el corte histórico del 2026-08-19 esta historia estaba `sin cobertura`: el panel había sido
removido y el backend descartaba `diff_text`. La implementación posterior `8039624`, corregida por
`f08626a`, integró un patch unificado textual en el detalle autenticado. El agente lo genera sólo
para texto UTF-8 admisible de hasta 1 MiB; el backend revalida, limita y persiste; la lista no expone
el contenido y `DiffViewer` lo renderiza como texto React sin HTML inyectado.

La historia no queda completa. `docs/historias_de_usuario.md` exige además que los binarios muestren
hashes y hex dump parcial, que el visor cambie de modo automáticamente y que utilice
`react-diff-viewer-continued`. La implementación vigente descarta el contenido binario y el visor es
un `<pre>` propio. Mantener esos pendientes evita convertir una implementación textual verificada en
cumplimiento retrospectivo de criterios que no fueron modificados.

| Criterio | Tests |
|---|---|
| Diff lado a lado o unificado en el detalle | `frontend/src/pages/EventDetail.test.tsx`; `frontend/src/components/ui/DiffViewer.test.ts`; render integrado y patch multi-hunk verificados. |
| Diff textual sólo para archivos de texto | `agent/tests/test_detector_diff.py`; binario, UTF-8 inválido, controles y tamaño excesivo producen `diff_text=None`. |
| Binarios: hashes + hex dump | **Pendiente de implementación y prueba.** El contrato vigente descarta el contenido binario. |
| Detección automática texto/binario | Detección en el agente probada; **pendiente en el visor**, que sólo recibe `diffText`. |
| `react-diff-viewer-continued` con escapado; prohibido `dangerouslySetInnerHTML` (W8) | El render React como texto y la ausencia de `dangerouslySetInnerHTML` reducen el riesgo de inyección; **no se usa la biblioteca exigida por el criterio**. |
| El diff nunca se loguea (W6) | La inspección del camino implementado no muestra logging directo de `diff_text`, pero no hay una prueba automatizada específica que inspeccione todos los logs; la nomenclatura canónica completa de hashes/tamaño tampoco queda acreditada. |

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
| Botón "Aprobar" | `frontend/src/pages/EventDetail.test.tsx::EventDetail — US-11 (toast 409 y aviso de archivo ausente) — el detalle de un evento pending muestra los botones Aprobar y Rechazar` |
| UPDATE optimista `version = :expected_version` (C5) | `backend/tests/test_actions_router.py::test_approve_with_stale_version_returns_409`, `::test_approve_already_resolved_event_returns_409` (aprobar dos veces: la segunda es conflicto, no un no-op silencioso); `backend/tests/test_actions.py::test_approve_conflict`, `::test_approve_success` |
| `approved` + `resolved_at` + `resolved_by` | `backend/tests/test_actions_router.py::test_approve_returns_action_response_shape` (relee el evento de la base y verifica `version == 1`, `resolved_by == admin_id` y `resolved_at is not None`); `backend/tests/test_actions.py::test_approve_success` |
| Baseline con el hash **actual** del archivo | SIN TEST — y no implementado: `backend/tests/test_actions.py::test_no_get_file_hash_published` asserta la decisión contraria (D2) |
| Comando firmado con HMAC-SHA256 (C7) | `backend/tests/test_actions.py::test_baseline_update_hmac_valid`; `backend/tests/test_c31_backend_event_correctness.py::test_fix02_approve_publish_is_post_commit`; `backend/tests/test_stream_ack_durability_outbox.py::test_approve_pending_row_born_in_same_transaction`, `::test_approve_valkey_down_leaves_event_approved_and_command_pending`, `::test_approve_rollback_leaves_no_published_command_row`, `::test_approve_without_secret_reverts_and_raises` |
| `ruleset_version` monotónico (C11) | Indirecto: `backend/tests/test_ruleset_version_atomic.py::test_concurrent_increments_no_lost_update`, `::test_actions_and_rules_share_single_implementation`. El valor dentro del payload de approve no se asserta |
| El agente rechaza firma inválida | `agent/tests/test_commands.py::test_hmac_invalid_discards_command` |
| El agente descarta versión menor | `agent/tests/test_commands.py::test_baseline_update_older_version_ignored` |
| Baseline local re-cifrada AES-256-GCM (W10) | `agent/tests/test_commands.py::test_baseline_update_present_writes_encrypted`; motor: `agent/tests/test_baseline.py::test_encrypt_decrypt_roundtrip`, `::test_key_derivation_deterministic`, `::test_key_derivation_different_agents`, `::test_tampered_blob_raises`, `::test_unique_nonce_per_write`, `::test_gcm_detects_path_swap`, `::test_baseline_file_permissions` |
| Confirma con `event_ack` (C3) | Lado agente: SIN TEST para `baseline_update`. Lado backend: `backend/tests/test_command_ack_consumer.py::test_ack_ok_baseline_update_marks_acked`, `::test_ack_ok_baseline_update_reconciles_baseline_entries`, `::test_ack_ok_baseline_update_advances_ruleset_version_applied`, `::test_ack_ok_monotonic_does_not_regress`, `::test_ack_error_marks_failed_no_reconciliation`, `::test_ack_invalid_signature_rejected`, `::test_ack_repeated_is_idempotent`, `::test_ack_cross_agent_forge_rejected`, `::test_ack_spoofed_agent_id_wrong_secret_rejected`; firma del ack: `agent/tests/test_commands.py::test_publish_ack_signs_command_ack_with_hmac` |
| Warning de archivo ausente | Backend: `backend/tests/test_actions_router.py::test_approve_absent_file_without_confirmation_returns_422` (422 de dominio con `detail == {"code": "absent_confirmation_required"}`) y `::test_approve_missing_required_field_returns_validation_422` (el contraste con un 422 de Pydantic, que devuelve una lista). Texto literal en la UI, cerrado por el change `backlog-partial-stories-completion` (D-6): `frontend/src/pages/EventDetail.test.tsx::EventDetail — US-11 (toast 409 y aviso de archivo ausente) — approve con 422 absent_confirmation_required muestra el aviso literal; Confirmar reenvía con confirm_absent:true`, `::Cancelar oculta el aviso de archivo ausente sin enviar una nueva request` |
| Confirmación explícita del admin | `backend/tests/test_actions_router.py::test_approve_absent_file_with_confirmation_succeeds`; `backend/tests/test_actions.py::test_approve_absent_no_confirm` |
| Baseline registra el path como `absent` (hash null) | `backend/tests/test_actions_router.py::test_approve_absent_file_with_confirmation_succeeds` (verifica la fila `BaselineEntry` con `status == absent`); `backend/tests/test_actions.py::test_approve_absent_confirmed`; `agent/tests/test_commands.py::test_baseline_update_absent_writes_null_hash` |
| Creación futura del path tratada como anomalía | SIN TEST |
| Registro en `audit_log` (W18) | `backend/tests/test_actions.py::test_audit_log_on_approve` |
| HTTP 409 + toast al perder la carrera | 409: `backend/tests/test_actions_router.py::test_approve_with_stale_version_returns_409` (con `detail.code == "conflict"` y el evento intacto en `pending`). El toast, con el texto literal de la historia y la invalidación de queries (D-6): `frontend/src/pages/EventDetail.test.tsx::EventDetail — US-11 (toast 409 y aviso de archivo ausente) — approve con 409 muestra el toast literal e invalida las queries del evento y la lista` |
| Autorización del endpoint | `backend/tests/test_actions_router.py::test_actions_endpoints_require_authentication[/actions/approve]`, `::test_actions_endpoints_reject_non_admin[/actions/approve]` |

---

<a id="us-12"></a>
### 5.12 US-12: Rechazo de un evento `pending` — `completa`

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): C10 del modal
de rechazo estaba implementado como no-op server-side pero sin la rama de UI (el frontend no conocía
`baseline_status` antes de enviar), y los handlers `restore_file`/`quarantine_file` no tenían test del
estado final del journal. Ambos gaps se cerraron; `ruleset_version` en estos comandos queda excluido
por D66/RN-160, una decisión, no una brecha. Con eso, los once criterios sustantivos de la historia
tienen al menos un test.

| Criterio | Tests |
|---|---|
| Botón "Rechazar" | `frontend/src/pages/EventDetail.test.tsx::EventDetail — US-11 (toast 409 y aviso de archivo ausente) — el detalle de un evento pending muestra los botones Aprobar y Rechazar` |
| Selección de `restore` o `quarantine` | `backend/tests/test_actions_router.py::test_reject_returns_action_response_shape`, `::test_reject_with_invalid_action_returns_422` (sólo se aceptan esas dos); `backend/tests/test_actions.py::test_reject_restore`, `::test_reject_quarantine` |
| Modal oculta acciones si el baseline está `absent` (C10) | Cerrado por el change `backlog-partial-stories-completion` (D-8): `GET /events/{id}` expone `baseline_status` (`backend/tests/test_event_router.py::test_get_event_baseline_status_absent`, `::test_get_event_baseline_status_present`, `::test_get_event_baseline_status_null_sin_fila`, `::test_get_event_baseline_status_null_sin_path`); `RejectModal` lo consume: `frontend/src/components/ui/RejectModal.test.tsx::RejectModal — US-12 C10 (baseline_status) — con baseline_status=absent no renderiza los radios y muestra el texto literal de C10`, `::con baseline_status=present renderiza los radios de acción correctiva`, `::con baseline_status=null (evento sin path baselineado) renderiza los radios como hoy` |
| Rechazo sobre baseline `absent` = no-op con warning | `backend/tests/test_actions_router.py::test_reject_with_absent_baseline_reports_the_noop` (el no-op es observable por HTTP vía `baseline_absent: true`); `backend/tests/test_actions.py::test_reject_absent_baseline_noop`; `backend/tests/test_stream_ack_durability_outbox.py::test_reject_baseline_absent_noop_enqueues_no_command` |
| UPDATE optimista (C5); 409 → toast | 409: `backend/tests/test_actions_router.py::test_reject_with_stale_version_returns_409`. Aislamiento por ítem: `backend/tests/test_actions.py::test_bulk_reject_partial`, `::test_bulk_reject_rollback_isolates_failed_item`. El toast, mismo literal que approve (D-6): `frontend/src/pages/EventDetail.test.tsx::EventDetail — US-11 (toast 409 y aviso de archivo ausente) — reject con 409 muestra el mismo toast e invalida las queries` |
| `rejected` + `resolved_at` + `resolved_by` | `backend/tests/test_actions_router.py::test_reject_returns_action_response_shape` (relee de la base); `backend/tests/test_actions.py::test_reject_restore`, `::test_reject_quarantine`, `::test_reject_absent_baseline_noop` — las tres rutas assertan hoy `resolved_by` y `resolved_at`, incluida la del no-op |
| Comando firmado (C7) con `ruleset_version` (C11) | Firma: indirecto — `backend/tests/test_published_command_ack_tracking.py::test_enqueue_restore_file_requires_caller_commit`, `::test_enqueue_restore_file_persists_once_caller_commits`; `backend/tests/test_stream_ack_durability_outbox.py::test_reject_valkey_down_leaves_event_rejected_and_command_pending`, `::test_reject_without_secret_reverts_and_raises`; `backend/tests/test_c31_backend_event_correctness.py::test_fix02_reject_publish_is_post_commit`. `ruleset_version` no se incluye por diseño → **superado por D66/RN-160 (2026-09-15, `docs/reglas_de_negocio.md:2123`)**: ese contador queda reservado a `update_config`, no a los comandos de acción correctiva. No es una brecha abierta, es una divergencia cerrada por decisión — ver `openspec/changes/backlog-partial-stories-completion/design.md` → D-7 |
| Journal pre-acción (W2) | `agent/tests/test_commands.py::test_journal_written_before_filesystem_op` |
| Journal a `completed`/`failed` con detalle | Cerrado por el change `backlog-partial-stories-completion` sobre los handlers reales (D-7): `agent/tests/test_journal_state_after_action_handlers.py::test_handle_restore_file_success_leaves_journal_completed`, `::test_handle_restore_file_no_baseline_leaves_journal_failed` (`state=="failed"`, `error=="no_baseline_content"`), `::test_handle_quarantine_file_success_leaves_journal_completed`, `::test_handle_quarantine_file_store_failure_leaves_journal_failed` (el `error` persistido coincide con el del ack publicado). Journal aislado: `agent/tests/test_journal.py::test_journal_mark_completed`, `::test_journal_mark_failed`, `::test_journal_write_pending`, `::test_journal_load_pending`, `::test_journal_delete`, `::test_journal_hmac_valid_roundtrip`, `::test_journal_tampered_content_discarded`, `::test_journal_atomic_write_survives_and_rehydrates`, `::test_journal_missing_hmac_discarded`, `::test_journal_wiring_receives_correct_secret`. Ejecución y ack: `agent/tests/test_commands.py::test_restore_handler_success_publishes_ack`, `::test_restore_handler_no_baseline_publishes_error_ack`, `::test_quarantine_handler_success`, `::test_quarantine_handler_file_not_found_publishes_error_ack`; `agent/tests/test_baseline_restore.py::test_handle_restore_file_from_snapshot`, `::test_handle_restore_file_no_restorable_content` |
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
### 5.16 US-16: Edición de una regla — `completa`

| Criterio | Tests |
|---|---|
| Formulario precargado | `frontend/e2e/us-isolated-lab.spec.ts::US-16 and US-17...` verifica los valores reales de patrón, severidad y acción antes de editar. |
| Modificación de patrón, severidad y acción | `backend/tests/test_rules_service.py::TestWriteOperations::test_update_rule_persists_the_new_field_values`, `::TestWriteOperations::test_update_rule_partial_payload_keeps_untouched_fields` |
| Los cambios se persisten | `backend/tests/test_rules_service.py::TestWriteOperations::test_update_rule_persists_the_new_field_values` (relee la fila tras `expire_all()`, para no leer el objeto en memoria que el servicio ya mutó; verifica además que `updated_at` avanzó y que no se creó una fila nueva). Ruta de error: `backend/tests/test_rules_router.py::test_put_rule_not_found_returns_404` (aserción débil) |
| `ruleset_version++` (C11) + sync | Unitario previo y Playwright aislado: versión posterior = versión anterior + 1, seguida de convergencia exacta del `state.json` del agente con DB. |
| `audit_log` (W18) | `backend/tests/test_rules_service.py::TestWriteOperations::test_update_rule_writes_audit_log` |

Autorización sí cubierta: `backend/tests/test_rules_router.py::test_put_rule_non_admin_returns_403`,
`::test_put_rule_no_auth_returns_401`.

Pendiente de accesibilidad separado de los criterios funcionales: los labels visibles de
`RuleForm` no tienen asociación programática con sus controles. El E2E acota selectores al diálogo
y no presenta ese defecto como corregido.

---

<a id="us-17"></a>
### 5.17 US-17: Eliminación de una regla — `completa`

| Criterio | Tests |
|---|---|
| Opción de eliminar | `frontend/e2e/us-isolated-lab.spec.ts::US-16 and US-17...` acciona el control real de la fila. |
| Confirmación previa | El caso cancela y verifica cero estado de confirmación/DELETE antes de confirmar; luego observa DELETE 204. |
| La regla se elimina | `backend/tests/test_rules_service.py::TestWriteOperations::test_delete_rule_removes_the_row` (la fila desaparece y las demás quedan intactas) |
| `ruleset_version++` (C11) + sync | Unitario previo y Playwright aislado: delete incrementa exactamente +1 y DB/agente convergen en la misma versión sin la regla. |
| Los paths pasan al default `alert_only` | El E2E modifica un archivo propio después de borrar y espera el evento real `alert_only` producido por agente→Valkey→backend. |
| `audit_log` (W18) | `backend/tests/test_rules_service.py::TestWriteOperations::test_delete_rule_writes_audit_log` |

Autorización sí cubierta: `backend/tests/test_rules_router.py::test_delete_rule_non_admin_returns_403`,
`::test_delete_rule_no_auth_returns_401`.

El pendiente de asociación accesible de labels pertenece a `RuleForm` y se registra por separado;
no se lo ocultó ni se modificó producción durante esta validación.

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
### 5.20 US-20: Alertas en tiempo real — `completa`

| Criterio | Tests |
|---|---|
| Conexión SSE | Unitarios previos y `frontend/e2e/us20-realtime-alerts.spec.ts` contra backend real. |
| Alerta ante nuevo evento | El E2E recorrió Valkey HMAC → consumer → Event/Alert PostgreSQL → broadcaster SSE; PASS. |
| Notificación visual sin recargar | El mismo caso observó el toast sin reload; PASS. |
| Reconexión automática | `us02-us20-us31-fixed-us20isolated20260911T0220Z/` corta sólo un proxy SSE del laboratorio: el stream inicial cierra, API y refresh permanecen 200, el proxy vuelve, se observa la segunda respuesta SSE antes de publicar y llega el toast del evento real posterior. Dos corridas individuales 2/2 y dos combinadas 5/5 PASS. Los paquetes anteriores se conservan como evidencia histórica insuficiente. |
| Robustez de la conexión (C32) | `backend/tests/test_c32_sse_security_fixes.py::test_session_closed_after_replay_before_sse_loop`, `::test_session_closed_when_no_replay`, `::test_broadcaster_queue_bounded_at_100`, `::test_broadcaster_queue_full_logs_warning` |

De las ramas de `_require_admin_from_token` sólo están asertadas el JWT inválido y el token ausente;
el `jti` en blacklist, el scope `password_change_only` y el 403 `admin_required` no tienen test.

---

<a id="us-21"></a>
### 5.21 US-21: Estado de agentes — `completa`

| Criterio | Tests |
|---|---|
| Lista de agentes registrados | `backend/tests/test_agent_mgmt.py::test_get_agents_list`, `::test_get_agent_detail`, `::test_get_agent_not_found`; `backend/tests/test_agent_watch_path_status.py::test_list_agents_exposes_watch_path_status`, `::test_get_agent_exposes_watch_path_status` |
| Identificador, estado, última actividad, `ruleset_version`, `queue_size` | Estados: `backend/tests/test_domain_models.py::TestAgentStatus::test_all_canonical_values`. Última actividad: `backend/tests/test_heartbeat_consumer.py::test_heartbeat_marks_online`, `backend/tests/test_agent_mgmt.py::test_dead_to_online_on_heartbeat`. Conteo por estado en la UI: `frontend/src/pages/Dashboard.test.tsx::muestra el estado de conectividad de los agentes registrados`. `ruleset_version` en la vista: `frontend/src/components/ui/AgentCard.test.tsx::muestra el ruleset_version aplicado por el agente`, `::no inventa un ruleset cuando el agente todavía no aplicó ninguno`. `queue_size` persistido: `backend/tests/test_heartbeat_consumer.py::test_queue_size_persisted`, `::test_queue_size_absent_does_not_reset`, `::test_queue_size_non_numeric_ignored`, `::test_queue_size_never_reported_reads_as_null` (commit `7f62348`) |
| Realce visual de los no-ok | `frontend/src/components/ui/AgentCard.test.tsx::realza el estado no-ok %s con su color propio` (dead, draining, offline), `::un agente online no usa los colores de alerta` |
| Heartbeat cada 10 s | `agent/tests/test_heartbeat_interval.py::test_heartbeat_interval_is_ten_seconds`, `::test_run_waits_the_interval_between_publications` |
| Sin heartbeat 30 s → `offline` | `backend/tests/test_heartbeat_consumer.py::test_sweep_marks_offline_after_30s`, `::test_sweep_does_not_mark_offline_if_recent`, `::test_sweep_marks_draining_agent_offline_after_30s`, `::test_sweep_keeps_draining_agent_if_heartbeat_is_recent` |
| Sin heartbeat 5 min → `dead` + webhook | `backend/tests/test_agent_mgmt.py::test_dead_transition`, `::test_dead_to_online_on_heartbeat`. Webhook por agente: `backend/tests/test_heartbeat_consumer.py::test_sweep_offline_returns_newly_dead_agent_ids`, `::test_sweep_offline_does_not_report_agent_already_dead`, `::test_notify_agent_dead_skips_without_webhook_url`, `::test_notify_agent_dead_sends_n8n_payload` (commit `7f62348`). Observación fuera del criterio: sale directo a n8n, sin cascada ni DLQ, y el enrutador lo procesa por la rama de alerta (Change 48) |
| Flag `shutdown` → `draining` | `backend/tests/test_heartbeat_consumer.py::test_heartbeat_shutdown_marks_draining` |
| Banner de `queue_pressure` (W3) | Banner: `frontend/src/components/ui/AgentCard.test.tsx::queue_pressure > 80% muestra un banner de alerta específico del agente`, `::queue_pressure <= 80% no muestra el banner` (commit `1226ed9`). Persistencia y cálculo: `backend/tests/test_heartbeat_consumer.py::test_heartbeat_marks_online`; `agent/tests/test_queue.py::test_queue_pressure_zero_when_empty`, `::test_queue_pressure_positive_after_enqueue`, `::test_drop_oldest_on_limit`, `::test_drop_oldest_removes_chronologically_oldest`. Umbral del 80 % en `frontend/src/components/ui/AgentCard.tsx:80-83` |

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

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): la historia
ya coincide con el código en la tabla `alerts` unificada (D6/RN-107). Se agrega evidencia de entrega
real de email vía n8n; el fallback SMTP directo del backend (segundo escalón de la cascada) sigue sin
evidencia de entrega real, sólo de código (ver fila "Cascada SMTP...").

| Criterio | Tests |
|---|---|
| Webhook ante `critical`/`high` | Por exclusión: `backend/tests/test_notifications.py::test_notify_skip_low_severity`, `::test_notify_skip_medium_severity`, `::test_notify_skip_superseded`. Severidad: `::test_determine_severity_critical`, `::test_determine_severity_high_over_low`, `::test_determine_severity_no_match`, `::test_determine_severity_no_rules`. Envío dado un `Alert`: `::test_notify_event_delivers_on_first_attempt`. El disparo positivo de `notify_if_applicable`: SIN TEST |
| Payload con `event_id`, path, severidad, acción, contexto de proceso y timestamps | SIN TEST y no implementado: `_build_payload` no incluye `process_pid`/`uid`/`exe`, `received_at` ni la acción tomada |
| n8n limitado a enrutador | SIN TEST dedicado (sostenido por construcción) |
| n8n reencamina por el canal configurado | Fuera del sistema. **Evidencia de entrega real (laboratorio VPS, aceptación 2026-09-15):** `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/a4-12.6-webhook-email.txt` registra una respuesta `202` del router n8n con `{"channel":"email","delivered":true,"error":null}` sobre Gmail SMTP configurado como canal de salida. Cubre el canal de email de n8n — **no** el fallback SMTP directo del backend (el segundo escalón de la cascada, fila siguiente) |
| Retry con delays 5 s / 30 s / 120 s (W11) | `backend/tests/test_notifications.py::test_notify_event_retry_3x_then_dlq` (compara la secuencia real contra `RETRY_DELAYS`) |
| Cascada SMTP → webhook directo → log crítico | Parcial: `backend/tests/test_notifications.py::test_send_smtp_skipped_when_no_host`, `::test_send_webhook_fallback_skipped_when_no_url`, `::test_send_n8n_skipped_when_no_url`, `::test_send_n8n_success`, `::test_send_n8n_failure`, `::test_send_log_only_always_succeeds`, `::test_log_only_no_entrega_si_hay_primarios_configurados`; `backend/tests/test_c31_backend_event_correctness.py::test_fix01_no_primaries_log_only_delivers`. **Entrega real del fallback SMTP directo del backend, verificada el 2026-09-15 (task 8.5 del change `backlog-partial-stories-completion`):** `send_smtp` (`app/modules/alerts/notifier.py`) contra un SMTP de captura desechable (`axllent/mailpit`, `docker compose -p fim-c55`, sin STARTTLS/SSL, puerto 1025), sin `N8N_WEBHOOK_URL` configurada (n8n agotado/ausente, forzando el segundo escalón de la cascada) — `send_smtp` retornó `True` y el mensaje llegó al capturador: `Mailpit message ID 1NQ73pW1kKvdeH7iLt9vAO`, `Date: 2026-09-15T18:43:41.266Z`, `Subject: [FIM Alert] severity=critical`, `From: fim-alerts@fim.local`, `To: admin@fim.local`, cuerpo = el payload JSON de `_build_payload` con `notification_id="c55-smtp-evidence-0001"`. El compose se levantó y se destruyó dentro de la misma sesión (`docker compose -p fim-c55 down`); no queda infraestructura residual. Esta corrida es evidencia unitaria del canal (`send_smtp` invocado directamente, no la cascada completa `notify_event` contra Postgres real) — confirma que el canal SMTP directo entrega, no reemplaza una corrida end-to-end sobre el laboratorio |
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
### 5.25 US-25: Bulk approve/reject — `completa`

| Criterio | Tests |
|---|---|
| Selección, botones y modal 10+N | `frontend/e2e/us25-bulk-actions.spec.ts`; `frontend/src/components/ui/BulkActionBar.test.tsx` |
| Wire canónico | `frontend/src/api/actions.test.ts` compara el JSON serializado con `contracts/actions.bulk-reject.request.json`; `backend/tests/test_actions_router.py` valida schema/endpoint y exige 422 para `items[]` legacy |
| Acción compartida y carga server-side | `test_bulk_reject_uses_event_ids_contract_with_shared_action`; `test_bulk_approve_uses_event_ids_contract_and_partitions_results` cubre `not_found`/`not_pending`; `test_bulk_approve_reports_absent_confirmation_as_failed_item` cubre `baseline_absent` |
| Locking y aislamiento parcial | `backend/tests/test_actions.py::test_bulk_approve_partial`, `::test_bulk_reject_partial`, y los dos casos rollback; `_approve_single`/`_reject_single` conservan UPDATE condicional por versión capturada |
| Resultado y conciliación visual | `BulkActionBar.test.tsx::muestra un resumen expandible...` y `::aplica el resultado sobre la selección actual...` |
| Firma, entrega, ACK, auditoría y efecto | `us-isolated-lab.spec.ts::US-25...` contra backend, DB, Valkey y agente reales; baseline cifrada termina ligada al UUID/hash aprobado |

El wire bulk no mantiene alias: approve usa `{event_ids:[...]}` y reject `{event_ids:[...], action:"restore|quarantine"}`. `baseline_absent` queda sólo en la acción individual; approve bulk informa el motivo y reject bulk lo trata como éxito sin comando (RN-74).

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

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): la política
de complejidad (mayúscula, minúscula, dígito) y la exigencia de `current_password` también con scope
`password_change_only` (D-2) se implementaron y testearon en ambos lados (backend + frontend), con
los mismos casos de prueba (ASCII, `Ñ`, dígitos) para verificar paridad de clases de carácter.

| Criterio | Tests |
|---|---|
| El seed crea el admin con `must_change_password: true` | Indirecto: `backend/tests/test_auth.py::test_login_primer_admin_must_change_password_true`, `::test_login_incluye_objeto_user`. Los tests de seed (`backend/tests/modules/users/test_user_management.py::test_seed_admin_usa_admin_email_configurado`, `::test_seed_admin_usa_default_cuando_no_hay_admin_email`, `::test_seed_admin_idempotente_con_admin_existente`) sólo assertan email e idempotencia |
| Tokens con scope `password_change_only` | `backend/tests/test_auth.py::test_scope_password_change_only_en_access_token`, `::test_login_primer_admin_must_change_password_true`; `backend/tests/test_c22_auth.py::test_create_access_token_scope_password_change_only_sigue_teniendo_type_access` |
| Redirect forzado al formulario | SIN TEST (la ruta real es `/change-password`, ver §5.1) |
| Formulario con password actual, complejidad y confirmación | Cerrado por el change `backlog-partial-stories-completion`: `frontend/src/pages/ForcePasswordChange.test.tsx::ForcePasswordChange — US-27 (D-2, complejidad y contraseña actual) — lista los requisitos del password en el formulario`, `::contraseña actual vacía muestra error y no llama a changePasswordApi`, `::password nuevo sin mayúscula muestra error y no llama a changePasswordApi`, `::password nuevo sin minúscula muestra error y no llama a changePasswordApi`, `::password nuevo sin número muestra error y no llama a changePasswordApi`, `::password corto muestra error y no llama a changePasswordApi`, `::password válido con Ñ como única mayúscula llama a changePasswordApi con current_password`, `::un 401 del backend (contraseña actual incorrecta) muestra el detail recibido` |
| El backend valida la actual y la complejidad | `backend/tests/test_auth.py::test_password_policy_error_password_valida`, `::test_password_policy_error_corta`, `::test_password_policy_error_sin_mayuscula`, `::test_password_policy_error_sin_minuscula`, `::test_password_policy_error_sin_digito`, `::test_password_policy_error_mayuscula_ene_con_tilde_es_valida` (unitarios de `password_policy_error`); HTTP: `::test_change_password_short_retorna_422`, `::test_change_password_sin_complejidad_retorna_422[sin_mayuscula/sin_minuscula/sin_digito]`, `::test_change_password_mayuscula_no_ascii_cuenta`. `current_password` exigido en ambos scopes (D-2): `::test_change_password_current_password_incorrecto_scope_forzado_retorna_401`, `::test_change_password_current_password_ausente_scope_forzado_retorna_401`, `::test_change_password_current_password_correcto_scope_normal`, `::test_change_password_current_password_incorrecto_scope_normal_retorna_401` |
| Argon2id (C9) | `backend/tests/test_auth.py::test_change_password_hashea_con_argon2id_c9_y_no_verifica_contra_anterior` (prefijo `$argon2id$v=19$m=65536,t=3,p=4$`, verifica contra el nuevo y no contra el anterior) |
| Flag a `false` y tokens nuevos | `backend/tests/test_auth.py::test_change_password_current_password_correcto_scope_normal` (`must_change_password is False` releído de la base). Cubierto también de forma incidental por el helper `_full_access_login`, precondición de `::test_logout_invalida_access_token` y `::test_logout_invalida_tambien_el_refresh_token`. El backend fuerza re-login en vez de emitir tokens nuevos |
| Bloqueo de otras rutas | `backend/tests/test_c22_scope_gate.py::test_get_events_scope_password_change_only_retorna_403`, `::test_get_event_by_id_scope_password_change_only_retorna_403`, `::test_get_rules_scope_password_change_only_retorna_403`, `::test_get_rule_by_id_scope_password_change_only_retorna_403`, `::test_get_events_full_access_token_no_recibe_403_por_scope`; `backend/tests/test_auth.py::test_change_password_con_scope_password_change_only` |
| Re-exigencia si cierra sin completar | `backend/tests/test_auth.py::test_change_password_no_completado_se_vuelve_a_exigir` (segundo login sin completar el cambio → `must_change_password: true` y scope `password_change_only`) |
| `audit_log` (W18) | `change_password`: `backend/tests/test_auth.py::test_change_password_deja_fila_en_audit_log`. `login`/`logout`: SIN TEST — sigue sin aserciones dedicadas |

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

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): el banner
pasó a `GET /alerts/failed/count` (D-3, D-4) con el texto y el link literales de la historia, y
`POST /alerts/{id}/retry` / `DELETE /alerts/{id}` ahora registran `audit_log` (D-5). El umbral
`retry_count >= 3` queda cerrado por decisión (D6/RN-102 prevalece sobre el literal original), no
implementado — ver §6.

| Criterio | Tests |
|---|---|
| Banner amarillo con `retry_count >= 3` | Cerrado sin umbral por D6/RN-102 (D-3 del design de Change 55) — fallo terminal puro, `retry_count=0` cuenta igual que `retry_count=3`: `backend/tests/test_notifications.py::test_get_failed_alerts_count_ignores_retry_count_threshold`, `::test_get_failed_alerts_count_empty_dlq`, `::test_get_failed_alerts_count_requires_admin`. Banner: `frontend/src/components/layout/AlertsBanner.test.tsx::muestra un banner amarillo con el texto literal de US-29 cuando count=4`, `::usa el singular cuando count=1`, `::una alerta con retry_count=0 (n8n sin configurar) igual cuenta — sin umbral`, `::consulta GET /alerts/failed/count` |
| Link a la vista de fallidas | `frontend/src/components/layout/AlertsBanner.test.tsx::el enlace apunta a /alerts/failed` — ya coincide con la ruta real (`App.tsx`), corregida en la historia |
| Tabla con `event_id`, primer intento, error y `retry_count` | `backend/tests/test_notifications.py::test_get_failed_alerts_returns_only_failed`, `::test_get_failed_alerts_empty`; `backend/tests/test_sse_alerts.py::test_get_failed_alerts_serializa_status`. Los campos `last_error`, `retry_count` y `failed_at` en la respuesta HTTP: SIN TEST |
| Reintentar / Descartar por fila | Reintentar: `backend/tests/test_notifications.py::test_retry_alert_resets_dlq_state_and_reschedules` (resetea `failed_at`, `last_error` y `retry_count`, y verifica que la cascada se vuelve a disparar sobre la misma alerta y el mismo evento), `::test_retry_alert_delivers_and_leaves_the_dlq` (entrega por n8n, marca el canal y la fila desaparece de `list_failed_alerts`), más las rutas de error `::test_retry_alert_already_delivered`, `::test_retry_alert_not_found`, `::test_post_retry_alert_409_if_delivered`, `::test_post_retry_alert_404_if_not_found`. Descartar: `::test_delete_alert_204`, `::test_delete_alert_404_if_not_found`, `::test_delete_alert_service`. UI (fila y bulk): `frontend/src/pages/FailedAlerts.test.tsx::"Reintentar" por fila llama POST /alerts/{id}/retry`, `::seleccionar tres filas y usar el bulk llama POST /alerts/{id}/retry una vez por id`, `::"Descartar" confirmado llama DELETE /alerts/{id}` |
| Bulk "Reintentar todos" | El contrato vigente es N llamadas individuales del frontend (no hay endpoint de bulk), verificado end-to-end: `frontend/src/pages/FailedAlerts.test.tsx::seleccionar tres filas y usar el bulk llama POST /alerts/{id}/retry una vez por id`; cada llamada deja su propia fila `audit_log`: `backend/tests/test_notifications.py::test_post_retry_alert_masivo_deja_una_fila_por_alerta` |
| La fila se elimina tras un reintento exitoso | Cubierto en su efecto observable: `backend/tests/test_notifications.py::test_retry_alert_delivers_and_leaves_the_dlq` asserta `list_failed_alerts(session) == []`. La implementación no borra la fila sino que marca `delivered_at` |
| El banner desaparece con la tabla vacía | `frontend/src/components/layout/AlertsBanner.test.tsx::no muestra ningun banner cuando count=0`, `::el banner desaparece cuando un refetch devuelve count=0` |
| `audit_log` (W18) | Cerrado por el change `backlog-partial-stories-completion` (D-5): `backend/tests/test_notifications.py::test_post_retry_alert_deja_fila_en_audit_log` (`action="alert_retry"`, `user_id` del admin, `target_type="alert"`, `target_id`, `detail` con `event_id`), `::test_post_retry_alert_masivo_deja_una_fila_por_alerta`, `::test_post_retry_alert_409_no_deja_fila_en_audit_log`, `::test_post_retry_alert_404_no_deja_fila_en_audit_log`, `::test_delete_alert_deja_fila_en_audit_log` (`action="alert_discard"`), `::test_delete_alert_404_no_deja_fila_en_audit_log` |

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
### 5.31 US-31: Toggle para mostrar eventos superseded — `completa`

| Criterio | Tests |
|---|---|
| El filtro oculta `superseded` por defecto | `backend/tests/test_event_listing_contract.py::test_list_events_excludes_superseded_by_default`, `::test_superseded_filter_applies_to_total_not_only_to_the_page`; cliente: `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío`, `::include_superseded=false queda como undefined` |
| Checkbox "Mostrar superseded" | `frontend/e2e/us31-superseded-toggle.spec.ts`: oculto por defecto y toggle real PASS. |
| Ícono de cadena rota y `parent_event_id` visible | `frontend/src/components/ui/EventsTable.test.tsx` y E2E posterior: link/ícono presentes, semántica accesible conservada y `#<parent_event_id>` visible. PASS. |
| Persistencia en la URL | `frontend/src/utils/eventFilters.test.ts::parseEventFilters — parsea include_superseded=true`, `::serializeEventFilters — serializa include_superseded=true`, `::omite include_superseded cuando es false/undefined`, `::round-trip parse/serialize — preserva filtros complejos en ida y vuelta`, `::filtros vacíos round-trip produce URLSearchParams vacío` |
| `GET /events` respeta el parámetro | Unitario previo y E2E: request real `include_superseded=true`, URL y persistencia tras reload PASS. |

Sigue vigente la advertencia de que `frontend/src/api/events.ts:88-97` **duplica** la serialización
de filtros en un `paramsSerializer` sin ningún test: el camino que realmente llega al backend no es
el que cubren los tests de `eventFilters.ts`.

---

## 6. Criterios sin test porque no están implementados

Distinguirlos importa: cerrarlos requiere desarrollo, no sólo escribir un test. La lista siguiente
salió del rastreo de código, no del texto de las historias, y se reverificó el 2026-08-19.

| Historia | Criterio | Estado real |
|---|---|---|
| US-07 | Selector con los 7 estados | `ALL_STATUSES` enumera 6 |
| US-08 | "Tipo de acción" del evento | No existe el campo en `Event` ni en `EventOut` |
| US-08, US-10 | Posición en la cadena y navegación | Fuera de alcance declarado; sólo se muestra el padre inmediato |
| US-09 | Modo binario con hashes y hex dump | No implementado; el contenido binario se descarta por el contrato vigente. |
| US-09 | `react-diff-viewer-continued` | No se usa; el visor vigente renderiza el patch en un `<pre>`. |
| US-10 | Endpoint de cadena de eventos por path | No existe |
| US-11 | Baseline con el hash actual del filesystem | Decisión D2 en contra: se usa `event.hash_detected` |
| US-12 | `ruleset_version` en `restore_file` / `quarantine_file` | Superado por D66/RN-160 (2026-09-15) — excluido por diseño, no es una brecha abierta |
| US-14 | `ruleset_version` global del sistema expuesto | Ningún endpoint lo expone |
| US-15 | Validación de patrón duplicado | Sin `unique=True` ni constraint |
| US-15 | Precedencia de la negación `!` en el backend | `determine_severity_for_path` usa `fnmatch` sin tratar `!` |
| US-18 | `event_ack` tras `rule_sync` | No implementado; `ack_status` queda NULL a propósito |
| US-19 | `path` y tipo de acción en `AlertResponse`; link al evento | No implementados |
| US-21 | `queue_size` del agente | Cerrado el 2026-09-12 (`7f62348`, `1226ed9`): persistido desde el heartbeat y mostrado en la tarjeta — ver §5.21 |
| US-21 | Webhook n8n al pasar un agente a `dead` | Cerrado el 2026-09-12 (`7f62348`): `_notify_agent_dead` por agente. Pendiente fuera de US-21: cascada, DLQ y rama `agent_dead` en el enrutador (Change 48) |
| US-21 | Umbral del 80% para `queue_pressure` (W3) | Cerrado el 2026-09-12 (`1226ed9`): banner por encima del 80 % en `AgentCard.tsx:80-83` |
| US-22 | Selección de paths para el re-scan | `AgentRescanRequest` sólo tiene `force` |
| US-22 | `ruleset_version++` en `rescan_baseline` y guard en el agente | No implementados |
| US-23 | Contexto de proceso, `received_at` y acción en el payload del webhook | `_build_payload` no los incluye |
| US-26 | Navegación numerada e input "ir a página" | Sólo "Anterior"/"Siguiente" |
| US-27 | Reglas de complejidad de la contraseña | Cerrado por el change `backlog-partial-stories-completion` (Change 55): `password_policy_error` en `backend/app/core/security.py`, exigido también con scope `password_change_only` (D-2) — ver §5.27 |
| US-27 | `audit_log` de `login` / `logout` / `change_password` | `change_password` verificado (`test_change_password_deja_fila_en_audit_log`); no hay filas verificadas para login/logout — sigue pendiente |
| US-05, US-29 | Umbral `retry_count >= 3` en el banner amarillo | Cerrado por decisión, no por implementación del umbral: D6/RN-102 (`docs/arquitectura_stack.md:2088-2091`) reemplazó la base del banner por fallo terminal sin umbral — ver D-3 del design de Change 55. `test_get_failed_alerts_count_ignores_retry_count_threshold` asserta explícitamente que una alerta con `retry_count=0` cuenta igual que una con `retry_count=3` |
| US-29 | Vista `/notifications/failed` | Cerrado como divergencia de trazabilidad: la ruta real siempre fue `/alerts/failed` y la historia fue corregida para nombrarla — sin redirect desde `/notifications/failed` (ver Resolved #2 del design de Change 55) |
| US-28 | Timestamp del último check saludable y cierre manual del banner | No implementados |
| US-29 | Tabla `failed_notifications` con `payload_json` | Su rol lo cumple `alerts`, sin payload |
| US-29 | Bulk retry y `audit_log` de reintento/descarte | Cerrado por el change `backlog-partial-stories-completion` (Change 55): el bulk sigue siendo N llamadas individuales del frontend (contrato ya vigente), y cada una deja fila `alert_retry`/`alert_discard` en `audit_log` — ver §5.29 |
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
