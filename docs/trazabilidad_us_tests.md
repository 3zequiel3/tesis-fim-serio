# Anexo — Matriz de trazabilidad: historias de usuario ↔ tests automatizados

> Elaborado el 2026-08-18 sobre la rama `devel`. **Reconciliado el 2026-09-16** sobre la rama `devel`,
> commit `2475de8` (25 `completa` + 6 `parcial`). **Cerrado el 2026-09-17**, commit `2d07cb2`
> (`backlog-full-stories-completion`, Change 57): las seis `parcial` pasan a `completa` — US-07 y
> US-21 por cambio de código, US-11 por la decisión D71/RN-165 que alinea el texto canónico, y
> US-22/US-27/US-29 con el test que faltaba por criterio. El resultado es **31/0/0, con conteo
> estricto de 24/31** (historias completas cuyo texto canónico no fue ajustado) — siete historias
> (US-01, US-05, US-11, US-12, US-23, US-27, US-29) llegan a `completa` con al menos un ajuste de
> criterio declarado, no sólo con test nuevo. Reemplaza la actualización del 2026-09-11 (base HEAD
> `6948aae`), que describía un árbol anterior al porte de los carriles V10 a `devel` (ver §3.1). El
> conteo y la reconciliación completa de los cortes históricos, incluida la tabla "Ajustes de
> criterio declarados", viven en
> [`docs/cierre/MATRIZ_TRAZABILIDAD.md`](cierre/MATRIZ_TRAZABILIDAD.md). La revisión inicial del
> 2026-08-19 siguió a los commits `faf7771` (backend, +45 tests) y `cff86fb` (frontend,
> infraestructura de componentes). Responde al punto "El requisito '31 de 31 historias' necesita
> trabajo aparte" de [`docs/plan_medicion_cap5.md`](plan_medicion_cap5.md) (Batería 2), opción
> **(b)**: matriz manual versionada como anexo.

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
| `completa` | **31** | US-01, US-02, US-03, US-04, US-05, US-06, US-07, US-08, US-09, US-10, US-11, US-12, US-13, US-14, US-15, US-16, US-17, US-18, US-19, US-20, US-21, US-22, US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31 |
| `parcial` | **0** | — |
| `sin cobertura` | **0** | — |

La aritmética de este corte es **31 `completa` + 0 `parcial` + 0 = 31**, sobre `devel`, commit
`2d07cb2`, al 2026-09-17 (Change 57, `backlog-full-stories-completion`, parte 1).

**Conteo estricto — historias completas cuyo texto canónico no fue ajustado: 24/31.** Siete historias
llegan a `completa` con al menos un ajuste de criterio declarado en
[`docs/cierre/MATRIZ_TRAZABILIDAD.md`](cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados):
US-01, US-05, US-11, US-12, US-23, US-27 y US-29. US-07 y US-21 no cuentan como ajuste: cerraron por
cambio de código sobre un texto que no cambió.

### 3.1 Por qué el corte del 2026-09-11 quedó desactualizado

Aquel corte declaraba 13 `completa` y 18 `parcial`. No fue un error de criterio sino de
sincronización. El 2026-09-15 se portaron a `devel` los carriles L1–L8 y L10 del candidato V10
(commits fechados 2026-09-12) junto con el backlog de historias parciales (Change 55, `6090b16`); el
commit de documentación `94fc455` sincronizó ese mismo día **solamente** las historias tocadas por el
Change 55. Desde entonces, trece filas de este anexo describían como inexistente funcionalidad que ya
estaba en el árbol: el endpoint de cadena (`b34aa11`, `f09e709`), el modo binario del diff
(`1c68e79`), la paginación numerada (`7f5685b`), `GET /rules/version`, el rechazo de patrón duplicado
y el `event_ack` de `rule_sync` (`1953209`), `path`/`action_taken` en alertas (`579b004`), el
timestamp y el cierre del banner (`0680783`) y el cese de `fanotify` en el drenaje (`8b3cab0`,
`1226ed9`).

Trece historias pasan de `parcial` a `completa` (US-01, US-08, US-09, US-10, US-14, US-15, US-18,
US-19, US-23, US-24, US-26, US-28, US-30) y una pasa de `completa` a `parcial` (US-21, ver §5.21).
Otras tres —US-22, US-27 y US-29— **conservan** el estado `parcial` pero **cambian de fundamento**:
las razones que el corte anterior daba son falsas contra este árbol, y el criterio que hoy las
sostiene es distinto y más angosto en los tres casos.

Situación anterior a la revisión (2026-08-18): 0 `completa`, 28 `parcial`, 3 `sin cobertura`.
Situación tras la change `frontend-severity-triage` (2026-08-21): US-06 cierra su cuarto y último
criterio (fila con severidad y proceso causante) y pasa de `parcial` a `completa`.

Seis conteos circulan por el corpus del cierre: **3/27/1** (línea base histórica de este anexo,
agosto 2026), **10/21/0** (corte intermedio citado por `RESULTADOS_VERIFICADOS.md`), **23/8/0**
(Tabla 22 del candidato V10, recompuesta por la auditoría externa sobre `7a7ee50`, 2026-09-12 —
antes del Change 55), **12/19/0** (resumen del corte del 2026-09-11 de `MATRIZ_TRAZABILIDAD.md`,
que además no coincidía con sus propias 13/18 filas), **25/6/0** (corte reconciliado del 2026-09-16)
y **31/0/0** (este corte, con conteo estricto de 24/31). Miden objetos distintos — cortes de código
diferentes, en momentos diferentes — y no son intercambiables entre sí; la tabla completa con qué
midió cada uno y por qué difieren vive en
[`docs/cierre/MATRIZ_TRAZABILIDAD.md`](cierre/MATRIZ_TRAZABILIDAD.md#reconciliación-de-los-conteos-históricos).

**Lo que el Capítulo 5 puede afirmar con esta evidencia:** que las 31 historias tienen al menos una
cobertura automatizada y que las 31 tienen todos sus criterios funcionales asertados o alineados por
decisión — **con el matiz del conteo estricto**: 24 de esas 31 llegan a `completa` sin que su texto
canónico haya sido ajustado; las siete restantes (US-01, US-05, US-11, US-12, US-23, US-27, US-29)
cierran con al menos un ajuste de criterio declarado (`docs/cierre/MATRIZ_TRAZABILIDAD.md`, sección
"Ajustes de criterio declarados"), no con una implementación más angosta encubierta.

Tres matices que conviene declarar junto al número, porque explican la forma del resultado:

1. **El sesgo era estructural y se corrigió en parte.** La suite era densa donde el sistema es
   riesgoso (máquina de estados de eventos, HMAC, outbox transaccional, cola offline, cifrado de
   baseline) y nula donde el sistema es visual, porque `vitest` corría sin DOM. Con `jsdom` y
   Testing Library ya instalados, la brecha dejó de ser infraestructural y pasó a ser de alcance:
   hoy hay tests de componente en todo el frontend relevante.
2. **Dos historias divergían del texto canónico y se cerraron por código, no por decisión.**
   US-07 (el selector ahora enumera los siete estados) y US-21 (el agente ahora publica el flag
   booleano `queue_pressure_high`, D72/RN-166) cerraron cambiando el código para cumplir el texto
   vigente — no ajustando el texto. La tercera divergencia histórica, US-11 (D2 sobre el hash del
   approve), sí se cerró con una decisión (D71/RN-165) que alinea el texto canónico al comportamiento
   ya vigente desde `8d37075`.
3. **Las otras tres historias que quedaban `parcial` eran criterios implementados sin aserción**: la
   confirmación visual del rescan (US-22), el `audit_log` de login/logout (US-27) y los valores de
   `last_error`/`retry_count`/`failed_at` en la respuesta HTTP (US-29). Un test cada una las cerró
   (Change 57, grupo 6, commit `2d07cb2`).

## 4. Matriz

Convención de la columna **Tests**: se nombran los archivos principales y la cantidad de tests
relevantes; los identificadores `archivo::nombre_del_test` completos están en el detalle por
historia (§5), al que remite cada fila.

| US | Criterios (resumidos) | Tests | Cobertura | Observaciones |
|---|---|---|---|---|
| **US-01** Inicio de sesión | Formulario; tokens JWT 15 min / 7 días con rotación; error genérico; token en memoria; cookie `httpOnly`/`Secure`/`SameSite=Strict`; Argon2id C9; rate limit 5/15 min; scope `password_change_only` | `test_auth.py` (+Argon2id, vida de tokens, cookie), `auth.store.test.ts`, `Login.test.tsx`, `ProtectedRoute.test.tsx`, `core/test_rate_limit_load.py` (4) — [§5.1](#us-01) | **completa** | Cerrado por `f87230a`. **La divergencia de cookie que este anexo denunciaba no existe en el árbol actual**: `auth/router.py:65-73` emite `samesite="strict"` y `path="/auth/refresh"`; el `path="/"` sólo aparece en el `delete_cookie` que purga la cookie legacy. Argon2id C9, vida de 15 min / 7 días, ausencia de `localStorage`/`sessionStorage`, formulario y redirect forzado tienen hoy test dedicado; la ruta `/change-password` coincide con la historia porque `cc73c2d` corrigió el texto canónico |
| **US-02** Cierre de sesión | Botón; limpieza de token; blacklist del `jti` en Valkey con TTL; redirección; 401 posterior | `test_auth.py` (2), `auth.test.ts`, `Navbar.test.tsx`, `auth.store.test.ts`, `us02-logout.spec.ts` — [§5.2](#us-02) | **completa** | La corrección posterior envía el Bearer al endpoint autenticado de logout. Unitarias y Playwright real verifican botón, limpieza local, revocación de access/refresh, cookie eliminada, redirección, Back seguro y comunicación explícita cuando la revocación remota no puede confirmarse. |
| **US-03** Renovación de sesión | Refresh anticipado; rotación single-use; blacklist → login; transparencia; multi-key JWT | Unitarios; `us03-session-refresh.spec.ts`; cookie/ruta/logout/reuso y rotación live en `us-isolated-lab.spec.ts`/runner — [§5.3](#us-03) | completa | Cookie `Strict`+`/auth/refresh`, migración legacy, revocación por `refresh_jti` y CURRENT/PREVIOUS ejecutados. |
| **US-04** Métricas del dashboard | Conteo por los 7 estados; léxico en minúsculas C1; carga al entrar; indicadores numéricos | `Dashboard.test.tsx` (4) — [§5.4](#us-04) | **completa** | Los cuatro criterios asertados sobre el componente real. El test mockea `@/api/client` y no `@/api/dashboard`, así que ejercita la agregación real del cliente (N requests a `/events`, una por estado). **Encontró un defecto real**: el dashboard enumeraba 6 de los 7 estados canónicos — faltaba `superseded` en `EVENT_STATUSES` (`Dashboard.tsx`) y en `statuses` (`api/dashboard.ts`) —, de modo que los eventos `superseded` no aparecían en ningún contador. Corregido en ambas listas |
| **US-05** Estado general del sistema | Pendientes sin resolver; conectividad de agentes; realce de críticos; banner rojo; banner amarillo | `Dashboard.test.tsx` (5), `SystemBanner.test.tsx` (4), `AlertsBanner.test.tsx` (7) — [§5.5](#us-05) | **completa** | El quinto criterio cierra por decisión, no por regresión de exigencia: `docs/historias_de_usuario.md` fue corregida en paralelo al change `backlog-partial-stories-completion` (Change 55) a la definición D6/RN-102 (fallo terminal, sin umbral `retry_count`), que es también la que `AlertsBanner` implementa hoy (`GET /alerts/failed/count`, D-3). El test asserta exactamente lo que la historia vigente pide |
| **US-06** Listado de eventos | Tabla paginada 50/página; fila con path, estado, acción, severidad, fecha y proceso causante; orden desc; excluye `superseded` | `test_event_listing_contract.py` (4), `test_c31_backend_event_correctness.py` (1), `eventFilters.test.ts` (2), `EventsTable.test.tsx` (5) — [§5.6](#us-06) | **completa** | Change `frontend-severity-triage` (2026-08-21) cerró el cuarto criterio: `EventsTable.tsx` ahora renderiza severidad (banda de borde + texto canónico) y proceso causante como sublínea del path, con caso negativo para el evento sin contexto de proceso. El "tipo de acción" del criterio se satisface por la columna Estado (D35/RN-129: el `status` derivado *es* la acción ejecutada), sin campo nuevo. Los cuatro criterios quedan asertados sobre el componente real |
| **US-07** Filtrado por estado | Selector de los 7 estados; multi-selección; `superseded` excluido; toggle; actualización dinámica | `Events.test.tsx::Events — filtro por estado (US-07)` (C1-C5 + 3 escenarios ADDED), `eventFilters.test.ts` (2 nuevos + round-trip), `test_event_listing_contract.py` (3) — [§5.7](#us-07) | **completa** | Cerrada por cambio de código (Change 57, grupo 5, commit `2d07cb2`): `ALL_STATUSES` (`Events.tsx`) enumera los 7 estados sin depender del toggle; marcar/desmarcar `superseded` y encender/apagar el toggle mantienen la coherencia con `include_superseded`; `parseEventFilters` normaliza el deep-link |
| **US-08** Detalle de un evento | Vista de detalle; campos; timestamps dobles con clock skew W13; contexto forense del proceso; enlace al padre; posición en la cadena | `test_event_listing_contract.py` (2), `test_stream_ack_durability_consumer.py` (11), `test_consumer.py` (1), `test_c31_backend_event_correctness.py` (2), `test_event_severity.py` (1), `test_event_symlink_metadata.py` (2), `test_event_ack_status_field.py` (3), `test_detector_context.py` (4) — [§5.8](#us-08) | **completa** | **Reclasificada** por el carril L4 (`b34aa11`, `f09e709`): "tipo de acción" existe como campo derivado (`derive_action_type`, `events/service.py:188-196`; `EventDetailOut.action_type`, `router.py:79`) con 5 tests en `test_event_listing_contract.py:535-590`, y la posición en la cadena se muestra y se testea (`EventDetail.tsx:35-38,186-201`; `EventDetail.test.tsx:221-235`). Dos huecos grandes ya estaban cerrados. `test_get_event_by_id_returns_full_detail` es el primer test de camino feliz del detalle: 200 y el conjunto de campos, con el contexto forense (`process_pid`/`uid`/`exe`) verificado ya persistido y expuesto, no sólo capturado en el agente. Y la frontera del clock skew quedó fijada a 299 s / 301 s en las **dos** ramas (con `sent_at` y por fallback sobre `detected_at`), incluida una aserción de que `_CLOCK_SKEW_S == 300`. Falta "tipo de acción", que no existe como campo, y la posición en la cadena |
| **US-09** Diff de un evento | Diff lado a lado/unificado; sólo texto; binarios con hashes y hex dump; detección automática; escapado W8; nunca loguear el diff W6 | `test_detector_binary_diff.py` (7), `DiffViewer.test.ts`, `EventDetail.test.tsx`, `test_detector_diff.py`, `test_log_inspection.py` (2) — [§5.9](#us-09) | **completa** | **Reclasificada** por el carril L6 (`1c68e79`): el modo binario existe (`_hex_dump`/`_binary_diff_info`, `agent/detector.py:235-285`, renderizados por `BinaryComparison`), la detección de modo es automática (`DiffViewer.tsx:170-196`) y la biblioteca en uso **es** `react-diff-viewer-continued@3.4.0` (`package.json:22`), sin un solo `dangerouslySetInnerHTML`. W6 verificado capturando structlog real. Límite declarado: no hay E2E de archivo real → diff renderizado, y el diff es acumulativo contra la baseline aprobada |
| **US-10** Cadena de eventos | Acceso a la cadena del path; orden cronológico con marca de `superseded`; navegación; ícono de cadena rota y `parent_event_id` | `test_event_service.py` (5), `test_event_status_derivation.py` (2), `test_c31_backend_event_correctness.py` (3), `test_event_listing_contract.py` (chain, 3), `EventChain.test.tsx` (3), `test_event_service.py` (5), `test_c22_fk_chain.py` (3) — [§5.10](#us-10) | **completa** | **Reclasificada.** La funcionalidad de usuario existe, al contrario de lo que afirmaba el corte anterior: `GET /events/{id}/chain` (`events/router.py:180-197`, orden `created_at ASC, id ASC`) y `frontend/src/pages/EventChain.tsx` con ícono de cadena rota y "padre: #N", ruta cableada en `App.tsx:54` y acceso desde el detalle. `EventTimeline.tsx` ya no declara la cadena fuera de alcance: su docstring remite a `EventChain`. El modelo de datos subyacente sigue siendo de lo mejor cubierto del repositorio |
| **US-11** Aprobación de un evento | Botón; UPDATE optimista C5; `approved` + `resolved_at`/`resolved_by`; baseline con el hash del evento aprobado (D71/RN-165, ratifica D2); comando firmado C7 + C11; agente rechaza firma/versión; re-cifrado W10; `event_ack` C3; warning de archivo ausente; `audit_log`; 409 + toast | `test_actions_router.py` (11), `test_actions.py` (7), `test_c31_backend_event_correctness.py` (1), `test_stream_ack_durability_outbox.py` (4), `test_command_ack_consumer.py` (9), `test_commands.py` (5), `test_baseline.py` (7), `EventDetail.test.tsx` (5) — [§5.11](#us-11) | **completa** | Cerrada por alineación de texto canónico: D71/RN-165 (2026-09-17) ratifica D2 y alinea el criterio 4 al comportamiento vigente desde `8d37075` — el baseline adopta el hash del evento aprobado, no uno releído del filesystem. `test_no_get_file_hash_published` asserta el criterio vigente. Ajuste de criterio declarado — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados` |
| **US-12** Rechazo de un evento | Botón; elección `restore`/`quarantine`; modal ante baseline `absent` C10; no-op con warning; UPDATE optimista; `rejected` + campos; comando firmado C7 + C11; journal pre-acción W2; `audit_log` | `test_actions_router.py` (8), `test_actions.py` (5), `test_stream_ack_durability_outbox.py` (3), `test_published_command_ack_tracking.py` (2), `test_commands.py` (5), `test_journal.py` (9), `test_baseline_restore.py` (2), `test_event_router.py` (4), `RejectModal.test.tsx` (3), `test_journal_state_after_action_handlers.py` (4), `EventDetail.test.tsx` (1) — [§5.12](#us-12) | **completa** | Cerrado por el change `backlog-partial-stories-completion` (Change 55): C10 ya no es un no-op invisible para el admin — `GET /events/{id}.baseline_status` (D-8) alimenta a `RejectModal`, que oculta las opciones correctivas y muestra el texto literal del criterio. Los handlers `restore_file`/`quarantine_file` ahora tienen test del estado final del journal (`completed`/`failed` con `error`). `ruleset_version` en estos comandos queda excluido por D66/RN-160 — decisión cerrada, no brecha |
| **US-13** Superseded automático | Nuevo evento supersede al `pending`; vínculo `parent_event_id`; no aparece en pendientes; transición validada C2; accesible por el toggle | `test_event_listing_contract.py` (3), `test_event_service.py` (7), `test_event_status_derivation.py` (5), `test_c31_backend_event_correctness.py` (2), `test_event_consumer_c11.py` (1), `test_c22_consumer.py` (1) — [§5.13](#us-13) | **completa** | Era la más cerca de cerrarse y se cerró. `test_list_events_excludes_superseded_by_default` cubre el único criterio que faltaba, y `test_superseded_filter_applies_to_total_not_only_to_the_page` agrega el matiz que hacía falta para que la exclusión sea coherente con la paginación: el `superseded` excluido tampoco cuenta en `total`. El acceso para auditoría queda cubierto por `test_list_events_includes_superseded_when_flag_is_true` |
| **US-14** Listado de reglas | Tabla; fila con patrón, severidad y acción; leyenda del default `alert_only`; `ruleset_version` del sistema | `test_rules_router.py` (version, 2), `Rules.test.tsx` (3), `test_rules_service.py::TestListRules` (3) — [§5.14](#us-14) | **completa** | **Reclasificada** (`1953209`, carril L1). El `ruleset_version` global **sí lo expone un endpoint**: `GET /rules/version` (`rules/router.py:103-109`) devuelve `RulesetVersionOut(version=get_ruleset_version(session))`, con `test_get_rules_version_returns_current_counter` y su caso 401. La fila con patrón/severidad/acción y la leyenda del default `alert_only` se renderizan en `Rules.tsx:120-133,169-172` y se assertan en `Rules.test.tsx` |
| **US-15** Creación de regla | Formulario; glob y negación `!`; la exclusiva gana; persistencia; patrón no duplicado; `ruleset_version++` C11 + sync; `audit_log` | `test_rules_service.py` (10), `test_rules_router.py` (3), `test_ruleset_version_atomic.py` (2), `test_rules.py` (3) — [§5.15](#us-15) | **completa** | **Reclasificada** (`1953209`, carril L1). Las dos afirmaciones anteriores son falsas en este árbol: el rechazo de patrón duplicado existe (`rules/service.py:313-316`, `test_create_rule_duplicate_pattern_raises` + `test_post_rules_duplicate_pattern_returns_422`), y la precedencia de la negación `!` está implementada **también en el backend** (`determine_severity_for_path`, `rules/service.py:59-89`), que es la función usada por el camino real de ingesta (`events/service.py:399`), con `TestSeverityNegation` (2) |
| **US-16** Edición de regla | Formulario precargado; modificar patrón/severidad/acción; persistencia; `ruleset_version++` + sync; `audit_log` | Unitarios previos + `us-isolated-lab.spec.ts` — [§5.16](#us-16) | **completa** | Playwright real verifica precarga/edición y el laboratorio verifica persistencia, auditoría, incremento exacto +1 y convergencia DB/agente. Pendiente separado: asociación accesible de labels, no criterio funcional de esta historia. |
| **US-17** Eliminación de regla | Opción de borrar; confirmación; eliminación de la fila; `ruleset_version++` + sync; caída al default `alert_only`; `audit_log` | Unitarios previos + `us-isolated-lab.spec.ts` — [§5.17](#us-17) | **completa** | Cancelar no emite DELETE; confirmar elimina, incrementa exactamente +1, converge con el agente y el siguiente cambio propio cae a `alert_only`. Pendiente separado: labels accesibles de RuleForm. |
| **US-18** Sync automática de reglas | Publica `rule_sync`; firma C7 + `ruleset_version` C11; el agente verifica firma; descarta versiones menores; reemplaza caché sin reiniciar; persiste en `state.json`; comandos antes que eventos W4; `event_ack` C3 | `test_rules_service.py` (8), `test_rule_sync_outbox.py` (4), `test_c32_sse_security_fixes.py` (1), `test_rules.py` (5), `test_stability_fixes.py` (2), `test_reconnect_order.py` (7), `test_publisher_dispatch_integration.py` — [§5.18](#us-18) | **completa** | **Reclasificada** (`1953209`, carril L1). El octavo criterio quedó implementado: la rama `rule_sync` de `agent/publisher.py:547-573` publica `_publish_ack(...)` con el `command_id` tras aplicar el ruleset (cableado en `agent/__main__.py:333-343`), asertado por `test_rule_sync_dispatches_event_ack` (docstring "US-18 criterio 8 / RN-58"). El test que documentaba la decisión contraria (`test_rule_sync_persists_with_null_ack_status`) **ya no existe** en el repositorio |
| **US-19** Listado de alertas | Lista ordenada por fecha desc; fila con path, severidad, acción, fecha y canal; navegación al evento | `test_sse_alerts.py` (10 + orden y campos), `Alerts.test.tsx` (3) — [§5.19](#us-19) | **completa** | **Reclasificada** (`579b004`, carril L3). Los tres criterios de la historia están hoy implementados y asertados: `AlertResponse` expone `path` y `action_taken` por join a `events` (`alerts/router.py:58-77`), el `ORDER BY created_at DESC` (`alerts/service.py:415`) tiene test en las dos capas, y la navegación al detalle existe (`Alerts.tsx:140-145`, asertada con `href="/events/99"`) |
| **US-20** Alertas en tiempo real | Conexión SSE; alerta ante nuevo evento; notificación visual; reconexión automática | Unitarios previos + `us20-realtime-alerts.spec.ts` — [§5.20](#us-20) | completa | Un proxy exclusivo del laboratorio permitió cortar físicamente sólo la ruta SSE. Dos corridas individuales y dos combinadas probaron cierre, API y refresh 200 durante el corte, segunda respuesta SSE establecida antes de publicar y toast para un evento real posterior. |
| **US-21** Estado de agentes | Lista; identificador, estado, última actividad, `ruleset_version`, `queue_size`; realce de no-ok; heartbeat 10 s / 30 s → offline / 5 min → dead + webhook / `shutdown` → draining; banner de `queue_pressure` (D72/RN-166) | `agent/tests/test_heartbeat_queue_pressure_high.py`, `test_heartbeat_consumer.py::test_queue_pressure_high_*` (4), `test_agent_mgmt.py::test_agents_expose_queue_pressure_high`, `AgentCard.test.tsx::AgentCard — banner de presión de cola alta (US-21/W3, D72/RN-166)` (4); resto: `test_agent_mgmt.py` (5), `test_heartbeat_consumer.py` (6), `test_agent_watch_path_status.py` (2), `test_domain_models.py` (1), `test_queue.py` (4), `test_heartbeat_interval.py` (2) — [§5.21](#us-21) | **completa** | Cerrada por cambio de código (D72/RN-166, Change 57, grupos 2 a 4, commit `2d07cb2`): el agente publica el flag booleano `queue_pressure_high` que el texto canónico y W3 piden, calculado de una sola lectura de `queue_pressure` (que se conserva sin cambios); el banner de `AgentCard` se deriva sólo del flag, sin umbral en el cliente |
| **US-22** Re-scan de baseline | Botón con selección de paths; diálogo con los `pending` afectados; confirmación explícita; supersesión + comando firmado C7 con `ruleset_version++` C11; el agente verifica firma y versión; regenera baseline cifrado W10; `event_ack` C3; confirmación visual; `audit_log`; deshabilitado si `draining` | `Agents.test.tsx::Agents — confirmación visual del rescan (US-22)` (2); resto: `test_agent_mgmt.py` (4), `test_published_command_ack_tracking.py` (1), `test_stream_ack_durability_outbox.py` (1), `test_agent_config.py` (5), `test_commands.py` (3), `test_baseline.py` (7), `AgentCard.test.tsx`, `RescanConfirmModal.test.tsx` — [§5.22](#us-22) | **completa** | Cerrada con el test que faltaba (Change 57, grupo 6, commit `2d07cb2`): `Agents.test.tsx`, nuevo, cubre el toast de confirmación del rescan sin conflicto y con 409 → modal → forzar. El resto (selección de paths, `ruleset_version++`, guard de versión, supersesión acotada) ya estaba cerrado desde el carril L5 |
| **US-23** Notificación externa | Webhook n8n ante `critical`/`high`; payload con contexto de proceso y timestamps; n8n como enrutador; retry 5/30/120 s; cascada SMTP → webhook → log; fila en DLQ; n8n caído no compromete la operación | `test_notification_payload_contract.py` (7), `test_notifications.py` (16), `test_health_n8n_check.py` (8) — [§5.23](#us-23) | **completa** | **Reclasificada.** La afirmación central anterior es falsa: `_build_payload` (`alerts/service.py:144-177`) **sí** emite `process_pid`, `process_uid`, `process_exe`, `received_at`, `detected_at`, `action_taken`, `path` y `severity` — implementado en `670f3c3` (2026-08-24) y asertado por `test_payload_satisfies_rn53` y el resto del contrato. La entrega real está acreditada en tres canales (email vía n8n, fallback SMTP con Mailpit, webhook directo del carril L7). Límite declarado: el rol de enrutador se sostiene en evidencia estática de arquitectura (carril L7, fila 3), no en una lista blanca de tipos de nodo |
| **US-24** Paths monitoreados | Lista de paths por agente; agregar; quitar; persistencia; `update_config` firmado C7 + `ruleset_version++` C11; el agente verifica y recarga en caliente; baseline scan de paths nuevos W10; `event_ack` C3; bootstrap desde YAML → autoridad en PostgreSQL; `audit_log`; deshabilitado si `draining` | `test_agent_mgmt.py` (5), `test_agent_watch_path_status.py` (3), `test_published_command_ack_tracking.py` (2), `test_agent_config.py` (6), `test_commands.py` (5), `test_stability_fixes.py` (2), `test_audit_fixes.py` (1), `AgentCard.test.tsx` — [§5.24](#us-24) | **completa** | **Reclasificada.** La advertencia metodológica **caducó**: `test_reload_watch_paths_marks_new` y `::test_reload_watch_paths_unmarks_removed` (`test_agent_config.py:211-256`) hoy invocan el método real `FanotifyDetector.reload_watch_paths` y assertan `FAN_MARK_ADD`/`FAN_MARK_REMOVE` (`0051e45`). El botón "Guardar paths" **sí** se deshabilita en `draining` (`AgentCard.tsx:243-249`, `fca97b5`). Los criterios de infraestructura 4-10 tienen artefactos capturados en el carril L7. Límites declarados: el incremento efectivo del contador se acredita por artefacto, no por test unitario, y la reconciliación al arrancar por construcción del lab |
| **US-25** Bulk approve/reject | Checkbox por fila y "todo en la página"; botones bulk; modal; acción compartida; `event_ids[]`; locking C5; resultados; baseline; auditoría; resumen/refresco | Unitarios + `us25-bulk-actions.spec.ts` + `us-isolated-lab.spec.ts` — [§5.25](#us-25) | completa | Wire canónico, rechazo 422 de legacy, UX/parcialidad y cadena approve→comando→agente→ACK→baseline pasaron. |
| **US-26** Paginación | 50 por página; navegación numerada; input "ir a página"; `?page=N&page_size=50`; respeta los filtros activos | `test_event_listing_contract.py` (5), `test_c31_backend_event_correctness.py` (1), `Pagination.test.tsx` (9), `test_event_listing_contract.py` (5), `eventFilters.test.ts` (3) — [§5.26](#us-26) | **completa** | **Reclasificada** (`7f5685b`, carril L2). Los criterios 2 y 3 dejaron de ser "no implementados": `Pagination.tsx:14-126` tiene navegación numerada completa (Primera / Anterior / ventana de números con `aria-current` / Siguiente / Última) e input "ir a página" con validación `1..totalPages`, cableado en `Events.tsx:216` y cubierto por 9 casos. El `total` que respeta cada filtro ya estaba asertado con `page_size=1` |
| **US-27** Cambio obligatorio de password | Seed con el flag; scope `password_change_only`; redirect forzado a `/change-password` (D70/RN-164); formulario con complejidad; validación de la actual; Argon2id C9; flag a `false` + tokens nuevos; bloqueo de otras rutas; re-exigencia; `audit_log` | `test_auth.py::test_login_deja_fila_en_audit_log`, `::test_logout_deja_fila_en_audit_log`; resto: `test_auth.py` (24), `test_c22_auth.py` (1), `test_c22_scope_gate.py` (5), `modules/users/test_user_management.py` (3), `ForcePasswordChange.test.tsx` (8), `ProtectedRoute.test.tsx` (2) — [§5.27](#us-27) | **completa** | Cerrada con el test que faltaba (Change 57, grupo 6, commit `2d07cb2`): el `audit_log` de `login`/`logout` ahora tiene aserción, junto a `test_change_password_deja_fila_en_audit_log`. El resto ya estaba cerrado por el Change 55; la ruta del redirect forzado es un ajuste de criterio declarado (D70/RN-164) — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados` |
| **US-28** Banner de degradación | Poll cada 10 s; estado de `postgres`, `valkey`, `n8n` y agentes; banner rojo con componente y timestamp; cerrable y reaparece; no bloquea; webhook ante cambio de estado | `SystemBanner.test.tsx` (9), `test_health.py` (2), `test_notifications.py` (5), `test_health_n8n_check.py` (8) — [§5.28](#us-28) | **completa** | **Reclasificada** (`0680783`, carril L2). Los dos criterios de UI que este anexo daba por no implementados existen: timestamp del último check saludable (`lastHealthyAtRef`, `SystemBanner.tsx:33,41-50,72-73`) y botón de cierre que reaparece en el siguiente poll (`dismissedFor` ligado a `checked_at`, `:39,60-61,78-85`), ambos asertados. El poll de 10 s tiene test con fake timers, y `GET /health/components` **sí** se invoca por HTTP (`test_health.py`). Límite declarado: `_check_agents` (`core/health.py:119-133`) no tiene test propio, así que la rama `has_online` nunca se ejercita con filas `Agent` reales |
| **US-29** Webhooks fallidos | Banner amarillo sin umbral (D6/RN-107, reescritura de RN-102); link a `/alerts/failed` (D70/RN-164); tabla con `event_id`, primer intento, error y `retry_count`; reintentar/descartar por fila; bulk; eliminación tras reintento exitoso; el banner desaparece; `audit_log` | `test_notifications.py::test_get_failed_alerts_expone_last_error_retry_count_failed_at`; resto: `test_notifications.py` (19), `AlertsBanner.test.tsx` (7), `test_sse_alerts.py` (3), `FailedAlerts.test.tsx` (3) — [§5.29](#us-29) | **completa** | Cerrada con el test que faltaba (Change 57, grupo 6, commit `2d07cb2`): `last_error`/`retry_count`/`failed_at` ahora tienen aserción HTTP, que además corrigió la normalización de zona horaria de esos campos bajo SQLite. El banner sin umbral y la ruta del link son ajustes de criterio declarados (D6/RN-107, D70/RN-164) — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados` |
| **US-30** Agente en shutdown graceful | Deja de aceptar eventos; drena con timeout 30 s; heartbeat con `shutdown: true`; backend marca `draining`; indicador "Drenando N eventos"; botones deshabilitados con tooltip; pasa a `offline`/`dead` | `test_shutdown_heartbeat.py` (5), `test_heartbeat_consumer.py` (3), `test_stability_fixes.py` (1), `test_agent_mgmt.py` (1), `test_detector_draining.py`, `test_drain_then_stop.py` (4), `AgentCard.test.tsx` (4), `test_shutdown_heartbeat.py` (5), `test_heartbeat_consumer.py` (3) — [§5.30](#us-30) | **completa** | **Reclasificada** (carril L5, `8b3cab0`/`1226ed9`). Los cuatro criterios que este anexo daba por no implementados existen y tienen test: el cese de aceptación de `fanotify` (`set_draining()`, `test_set_draining_stops_accepting_new_events`), el timeout de 30 s (`test_drain_then_stop_default_timeout_is_30_seconds`, contra la firma viva), el indicador "Drenando N eventos" (`AgentCard.tsx:137`) y los botones deshabilitados con el tooltip literal (`DRAINING_TOOLTIP`, `AgentCard.tsx:19`) |
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
### 5.1 US-01: Inicio de sesión — `completa`

| Criterio | Tests |
|---|---|
| Formulario con usuario y contraseña | **Actualización 2026-09-16**: `frontend/src/pages/Login.test.tsx` — describe `US-01 criterio 1 (formulario)`, `::presenta campos de usuario y contraseña con sus labels`, `::el botón de ingresar está deshabilitado hasta completar ambos campos` |
| Credenciales válidas → par de tokens y redirección | `backend/tests/test_auth.py::test_login_exitoso_retorna_200`, `::test_login_incluye_objeto_user`. **Actualización 2026-09-16**: la vida de 15 min / 7 días tiene test directo — `test_auth.py::test_access_15min_refresh_7d`. La redirección al dashboard se acredita por E2E contra el stack real, no por unitario: `us-isolated-lab.spec.ts` asserta `toHaveURL(/\/dashboard/)` tras un login 200 real |
| Credenciales inválidas → error genérico | `backend/tests/test_auth.py::test_login_error_es_identico_para_password_mala_y_usuario_inexistente` (compara los cuerpos completos, el `detail` literal y que ninguna respuesta nombra al usuario probado), `::test_login_password_incorrecta_retorna_401`, `::test_login_usuario_inexistente_retorna_401` |
| Access token en memoria, nunca en `localStorage` (W9) | **Actualización 2026-09-16**: `frontend/src/stores/auth.store.test.ts::login() nunca escribe en localStorage ni sessionStorage (spy en Storage.prototype.setItem)` |
| Refresh token como cookie `httpOnly`/`Secure`/`SameSite=Strict`/`Path=/auth/refresh` (W9) | **Actualización 2026-09-16.** La divergencia denunciada aquí era falsa: `backend/app/modules/auth/router.py:65-73` emite `httponly=True`, `samesite="strict"`, `path="/auth/refresh"` y `secure` atado a `console_tls_mode`; el `path="/"` sólo aparece en el `delete_cookie` que purga la cookie legacy. `test_auth.py::test_cookie_refresh_secure_fuera_de_modo_off`, `::test_login_migra_cookie_legacy_y_emite_cookie_canonica` |
| Argon2id `time_cost=3, memory_cost=65536, parallelism=4` (C9) | **Actualización 2026-09-16**: `test_auth.py::test_hash_password_usa_argon2id_c9` (asserta el prefijo `$argon2id$v=19$m=65536,t=3,p=4$`) |
| Rate limit 5 intentos / 15 min por `(username + IP)` (W5) | `backend/tests/test_auth.py::test_rate_limit_login_6to_intento_retorna_429`, `::test_rate_limit_login_5_intentos_pasan`, `backend/tests/core/test_rate_limit_load.py::test_login_n_requests_dentro_del_bucket_no_rechazados`, `::test_login_n_mas_1_request_retorna_429`, `::test_login_ventana_se_resetea_en_primer_request`, `::test_login_ttl_siempre_presente_tras_incrementos_count_mayor_a_1` |
| `must_change_password` → scope `password_change_only`, redirige a `/change-password` (D70/RN-164) | Scope: `backend/tests/test_auth.py::test_login_primer_admin_must_change_password_true`, `::test_scope_password_change_only_en_access_token`, `backend/tests/test_c22_auth.py::test_create_access_token_scope_password_change_only_sigue_teniendo_type_access`. **Ajuste de criterio declarado**: la ruta era `/account/change-password`, alineada a `/change-password` en `cc73c2d` y respaldada por D70/RN-164 — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`. **Actualización 2026-09-16**: el redirect en sí ahora tiene test — `ProtectedRoute.tsx:44-54` implementa el gate y `ProtectedRoute.test.tsx` lo asserta en sus dos ramas (ver §5.27) |

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
D6/RN-107 (reescritura de RN-102, fallo terminal sin umbral) y `AlertsBanner` implementa exactamente
eso (`GET /alerts/failed/count`, sin `retry_count >= 3`, D-3 del design). **Ajuste de criterio
declarado**: el texto original pedía `failed_notifications` con `retry_count >= 3` — ver
`docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`.

| Criterio | Tests |
|---|---|
| Cantidad de `pending` sin resolver | `frontend/src/pages/Dashboard.test.tsx::Dashboard — US-05: estado general del sistema — indica cuantos eventos pending hay sin resolver` |
| Conectividad de agentes | `frontend/src/pages/Dashboard.test.tsx::muestra el estado de conectividad de los agentes registrados` (cuenta `online`, `offline`, `draining` y `dead` por separado); a nivel de enum: `backend/tests/test_domain_models.py::TestAgentStatus::test_all_canonical_values` |
| Realce de `pending` con severidad `critical`/`high` | `frontend/src/pages/Dashboard.test.tsx::destaca visualmente los pending critical/high cuando existen` y `::no destaca la tarjeta de pending critical/high cuando no hay ninguno` (par positivo/negativo: compara la clase de la tarjeta contra la de una tarjeta normal, de modo que un realce permanente fallaría) |
| Banner rojo de degradación | `frontend/src/components/layout/SystemBanner.test.tsx::no muestra ningun banner cuando todos los componentes estan ok`, `::muestra un banner rojo que nombra el componente degradado`, `::trata al subsistema de agentes como degradado cuando su status no es ok`, `::nombra todos los componentes caidos a la vez`; el estado de infraestructura en el dashboard: `frontend/src/pages/Dashboard.test.tsx::muestra el estado de la infraestructura monitoreada` |
| Banner amarillo de notificaciones fallidas (D6/RN-107, reescritura de RN-102, sin umbral) | `frontend/src/components/layout/AlertsBanner.test.tsx::muestra un banner amarillo con el texto literal de US-29 cuando count=4`, `::no muestra ningun banner cuando count=0`, `::el enlace apunta a /alerts/failed`, `::consulta GET /alerts/failed/count`, `::usa el singular cuando count=1`, `::una alerta con retry_count=0 (n8n sin configurar) igual cuenta — sin umbral`, `::el banner desaparece cuando un refetch devuelve count=0`; endpoint: `backend/tests/test_notifications.py::test_get_failed_alerts_count_ignores_retry_count_threshold`, `::test_get_failed_alerts_count_empty_dlq`, `::test_get_failed_alerts_count_requires_admin` |

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
### 5.7 US-07: Filtrado de eventos por estado — `completa`

**Cerrada por cambio de código (Change 57, grupo 5, commit `2d07cb2`).** `ALL_STATUSES`
(`frontend/src/pages/Events.tsx`) enumera los 7 estados canónicos en orden, con `superseded` siempre
visible y desmarcado por defecto — ya no depende del checkbox condicionado al toggle. Marcar
`superseded` activa `include_superseded`; apagar el toggle lo quita del filtro sin apagarse a sí
mismo al revés; `parseEventFilters` normaliza un deep-link `status=superseded` sin el toggle.

| Criterio | Tests |
|---|---|
| Selector con los 7 estados | `frontend/src/pages/Events.test.tsx::Events — filtro por estado (US-07) — C1: los siete checkboxes existen sin activar el toggle y en el orden canónico`; backend: `backend/tests/test_event_listing_contract.py::test_pagination_total_respects_status_filter` |
| Selección múltiple simultánea | `Events.test.tsx::...C2: marcar pending y approved emite ambos status en la petición`; `backend/tests/test_event_listing_contract.py::test_status_filter_accepts_multiple_values` (el parámetro repetible es una unión, no una intersección vacía); `frontend/src/utils/eventFilters.test.ts::parseEventFilters — parsea multi-select status`, `::serializeEventFilters — serializa multi-select status como repeated params` |
| `superseded` excluido por defecto (W1) | `Events.test.tsx::...C3: sin parámetros ningún estado está marcado y la petición no lleva include_superseded`; `backend/tests/test_event_listing_contract.py::test_list_events_excludes_superseded_by_default`; cliente: `eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío` |
| Toggle "Mostrar superseded" coherente con el filtro | `Events.test.tsx::...C4: encender el toggle emite include_superseded=true y apagarlo con superseded marcado lo desmarca y lo quita de la petición`, `::marcar superseded en el selector activa include_superseded=true`, `::desmarcar superseded conserva el toggle activo`, `::un deep-link con status=superseded arranca con el checkbox y el toggle activos`; backend: `backend/tests/test_event_listing_contract.py::test_list_events_includes_superseded_when_flag_is_true`; parser: `eventFilters.test.ts::status=superseded sin el toggle en la URL se parsea con include_superseded: true`, `::sin superseded en status, include_superseded sigue undefined por default`, `::round-trip conserva superseded en status e include_superseded juntos` |
| Actualización dinámica al filtrar | `Events.test.tsx::...C5: desmarcar el último estado emite una petición nueva sin status` |

El test que antes se citaba aquí con reservas —`backend/tests/test_event_severity.py::test_list_events_filters_by_severity`, que enviaba `status=pending` sobre un fixture donde los cuatro eventos eran `pending`— queda superado: la selectividad hoy se prueba con eventos de estados distintos.

---

<a id="us-08"></a>
### 5.8 US-08: Detalle de un evento — `completa`

| Criterio | Tests |
|---|---|
| Vista de detalle al seleccionar | `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` (200 con el detalle completo), `::test_get_event_by_id_unknown_returns_404`; rutas de error preexistentes: `backend/tests/test_event_router.py::test_get_event_by_id_no_auth_returns_401` |
| Campos: path, hash, estado, acción, severidad, fechas, resolución | `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` (id, `event_id`, `agent_id`, path, `hash_detected`, status, severity, version, `parent_event_id`, `resolved_at`/`resolved_by` en `None`, metadatos de symlink); serialización por campo: `backend/tests/test_event_severity.py::test_event_out_serializes_severity`, `backend/tests/test_event_symlink_metadata.py::test_event_out_serializes_symlink_metadata`, `::test_event_out_defaults_for_regular_file`, `backend/tests/test_event_status_derivation.py::test_event_out_serializes_action_failed_true`, `::test_event_out_defaults_action_failed_false`, `backend/tests/test_event_ack_status_field.py::test_event_with_confirmed_command_exposes_ack_status`, `::test_event_without_confirmable_command_has_no_ack_status`, `::test_event_uses_most_recent_published_command`. **"Tipo de acción" — actualización 2026-09-16 (carril L4, `b34aa11`/`f09e709`)**: existe como campo derivado, `derive_action_type` (`backend/app/modules/events/service.py:188-196`) y `EventDetailOut.action_type` (`router.py:79`), con 5 tests en `test_event_listing_contract.py:535-590` |
| Timestamps dobles con clock skew de 5 min (W13) | Frontera exacta: `backend/tests/test_stream_ack_durability_consumer.py::test_sent_at_at_299s_is_accepted` (con `assert _CLOCK_SKEW_S == 300`), `::test_sent_at_at_301s_is_rejected`, `::test_detected_at_fallback_boundary_at_299s_and_301s`. Resto de la ventana: `::test_detected_at_old_sent_at_recent_is_accepted`, `::test_sent_at_out_of_range_rejected`, `::test_sent_at_in_future_rejected`, `::test_sent_at_unparseable_rejected`, `::test_sent_at_naive_interpreted_as_utc`, `::test_no_sent_at_within_window_accepted`, `::test_no_sent_at_old_detected_at_rejected`, `::test_response_matrix_clock_skew_terminal_nack`; `backend/tests/test_consumer.py::test_reject_clock_skew`; `backend/tests/test_c31_backend_event_correctness.py::test_fix08_unparseable_detected_at_rejected_as_clock_skew`, `::test_fix08_naive_datetime_within_range_accepted`; exposición en el detalle: `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` |
| Contexto forense del proceso (PID, UID, `exe`) | `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` (persistido y expuesto); captura en el agente: `agent/tests/test_detector_context.py::test_get_exe_returns_none_on_oserror`, `::test_get_exe_returns_path_on_success`, `::test_get_uid_returns_zero_on_oserror`, `::test_get_uid_parses_uid_from_proc_status` |
| Enlace al evento padre | El `parent_event_id` viaja en la respuesta: `backend/tests/test_event_listing_contract.py::test_get_event_by_id_returns_full_detail`; se puebla al formarse la cadena: `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`. **Actualización 2026-09-16**: `EventDetail.test.tsx::si el evento tiene parent_event_id, muestra un enlace al evento padre` (con caso negativo `::sin parent_event_id no muestra enlace al evento padre`) |
| Posición en la cadena y navegación | **Actualización 2026-09-16 (carril L4)**: `EventDetail.tsx:35-38,186-201` muestra "Posición N de M en la cadena" y enlaza a `/events/{id}/chain`, con 3 casos en `EventDetail.test.tsx:221-235` (incluido el caso negativo de cadena de un solo elemento). `EventTimeline.tsx` ya no declara la cadena fuera de alcance |

---

<a id="us-09"></a>
### 5.9 US-09: Visualización de diff — `completa`

En el corte histórico del 2026-08-19 esta historia estaba `sin cobertura`: el panel había sido
removido y el backend descartaba `diff_text`. La implementación posterior `8039624`, corregida por
`f08626a`, integró un patch unificado textual en el detalle autenticado. El agente lo genera sólo
para texto UTF-8 admisible de hasta 1 MiB; el backend revalida, limita y persiste; la lista no expone
el contenido y `DiffViewer` lo renderiza como texto React sin HTML inyectado.

**Actualización 2026-09-16 (carril L6, `1c68e79`).** Los tres pendientes que dejaban esta historia en
`parcial` quedaron cerrados: el modo binario existe de punta a punta (`_hex_dump`/`_binary_diff_info`
en `agent/detector.py:235-285`, persistidos en `events/models.py:53-62`, renderizados por
`BinaryComparison`), el visor detecta automáticamente texto/binario según `diffText`/`isBinary`
(`DiffViewer.tsx:170-196`), y la biblioteca en uso **es** `react-diff-viewer-continued@3.4.0`
(`frontend/package.json:22`, con `splitView`), sin un solo `dangerouslySetInnerHTML` en el código.
Límites declarados que persisten sin bloquear la clasificación (mismo estándar con que US-04, US-06 y
US-13 alcanzan `completa`): no hay un E2E de archivo real del filesystem al diff renderizado en el
navegador, y el diff es acumulativo contra la baseline aprobada, no contra la versión inmediatamente
anterior.

| Criterio | Tests |
|---|---|
| Diff lado a lado o unificado en el detalle | `frontend/src/pages/EventDetail.test.tsx`; `frontend/src/components/ui/DiffViewer.test.ts`; render integrado y patch multi-hunk verificados. |
| Diff textual sólo para archivos de texto | `agent/tests/test_detector_diff.py`; binario, UTF-8 inválido, controles y tamaño excesivo producen `diff_text=None`. |
| Binarios: hashes + hex dump | **Actualización 2026-09-16 (`1c68e79`)**: `agent/tests/test_detector_binary_diff.py` (7 casos) cubre `_hex_dump`/`_binary_diff_info`; `BinaryComparison` renderiza la comparación de hashes con indicador visual y el hex dump parcial lado a lado. |
| Detección automática texto/binario | **Actualización 2026-09-16**: `DiffViewer.test.ts::detecta modo binario automáticamente` cubre el cambio de modo en el visor según `diffText`/`isBinary`. |
| `react-diff-viewer-continued` con escapado; prohibido `dangerouslySetInnerHTML` (W8) | **Actualización 2026-09-16**: la biblioteca exigida está en uso (`package.json:22`); `DiffViewer.test.ts::nunca usa dangerouslySetInnerHTML (W8)`; `rg` no encuentra `dangerouslySetInnerHTML` en `frontend/src`. |
| El diff nunca se loguea (W6) | `agent/tests/test_log_inspection.py::test_binary_modification_never_logs_diff_or_hexdump_content`, `::test_text_modification_never_logs_diff_content` (capturan structlog real y assertan el conjunto exacto de campos permitidos); `test_logging_sanitize.py::test_hex_dump_keys_redacted`. |

---

<a id="us-10"></a>
### 5.10 US-10: Cadena de eventos — `completa`

| Criterio | Tests |
|---|---|
| Acceso a la cadena del path desde el detalle | **Actualización 2026-09-16 (carril L4, `b34aa11`/`f09e709`)**: `GET /events/{event_id}/chain` (`backend/app/modules/events/router.py:180-197`) existe; accesible desde el detalle vía "Ver cadena completa" (`EventDetail.tsx`). Backend: `backend/tests/test_event_listing_contract.py::test_get_event_chain_returns_events_for_same_path_chronologically`, `::test_get_event_chain_does_not_require_admin_role`, 404 cubierto |
| Cadena ordenada con marca de `superseded` | **Actualización 2026-09-16**: orden `created_at ASC, id ASC` (`events/service.py:204-214`), marca de `superseded` visible; `test_get_event_chain_returns_events_for_same_path_chronologically`, `test_get_event_chain_marks_superseded_events`; frontend: `frontend/src/pages/EventChain.tsx`, `EventChain.test.tsx::muestra todos los eventos de la cadena ordenados cronologicamente` |
| Cada evento navegable a su detalle | **Actualización 2026-09-16**: ruta cableada en `App.tsx:54`; `EventChain.test.tsx::cada evento de la cadena es navegable hacia su detalle` |
| Ícono de cadena rota y referencia al `parent_event_id` | **Actualización 2026-09-16**: `EventChain.tsx` renderiza el ícono de cadena rota (`data-testid="broken-chain-icon"`) y "padre: #N"; `EventChain.test.tsx::marca los eventos superseded`. Formación del vínculo subyacente: `backend/tests/test_event_service.py::test_ingest_with_pending_creates_chain`, `::test_mark_superseded_success`, `::test_mark_superseded_wrong_version_returns_false`, `::test_get_pending_returns_most_recent`, `::test_get_pending_returns_none_when_no_pending`; `backend/tests/test_event_status_derivation.py::test_incoming_terminal_event_supersedes_active_pending`, `::test_persisted_terminal_event_is_never_superseded_afterward`; `backend/tests/test_c31_backend_event_correctness.py::test_fix03_race_no_pending_inserts_independent`, `::test_fix03_race_still_pending_returns_none`, `::test_fix05_compact_chain_retains_newest`; `backend/tests/test_c22_fk_chain.py::test_delete_parent_nulls_child_parent_event_id`, `::test_compact_chain_long_chain_no_integrity_error`, `::test_ingest_event_keeps_new_event_after_compaction`; `backend/tests/modules/events/test_retention.py::test_compact_chain_compacta_cadena_mayor_10`, `::test_compact_chain_no_elimina_si_10_o_menos`, `::test_compact_chain_preserva_protegidos_por_audit_log` |

Hasta el 2026-09-15 sólo el modelo de datos subyacente estaba cubierto; el endpoint de cadena y
`EventChain.tsx` (carril L4) cerraron la funcionalidad de usuario que faltaba.

---

<a id="us-11"></a>
### 5.11 US-11: Aprobación de un evento `pending` — `completa`

| Criterio | Tests |
|---|---|
| Botón "Aprobar" | `frontend/src/pages/EventDetail.test.tsx::EventDetail — US-11 (toast 409 y aviso de archivo ausente) — el detalle de un evento pending muestra los botones Aprobar y Rechazar` |
| UPDATE optimista `version = :expected_version` (C5) | `backend/tests/test_actions_router.py::test_approve_with_stale_version_returns_409`, `::test_approve_already_resolved_event_returns_409` (aprobar dos veces: la segunda es conflicto, no un no-op silencioso); `backend/tests/test_actions.py::test_approve_conflict`, `::test_approve_success` |
| `approved` + `resolved_at` + `resolved_by` | `backend/tests/test_actions_router.py::test_approve_returns_action_response_shape` (relee el evento de la base y verifica `version == 1`, `resolved_by == admin_id` y `resolved_at is not None`); `backend/tests/test_actions.py::test_approve_success` |
| Baseline con el hash reportado por el evento aprobado (D71/RN-165, ratifica D2) | **Ajuste de criterio declarado** — el texto pedía el hash **actual** del filesystem; D71/RN-165 (2026-09-17) alinea el criterio al comportamiento vigente desde `8d37075`, ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`. `backend/tests/test_actions.py::test_no_get_file_hash_published` asserta el criterio vigente: el baseline usa `event.hash_detected`, sin releer el filesystem |
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
| Comando firmado (C7); `ruleset_version` superado por decisión (D66/RN-160) | Firma: indirecto — `backend/tests/test_published_command_ack_tracking.py::test_enqueue_restore_file_requires_caller_commit`, `::test_enqueue_restore_file_persists_once_caller_commits`; `backend/tests/test_stream_ack_durability_outbox.py::test_reject_valkey_down_leaves_event_rejected_and_command_pending`, `::test_reject_without_secret_reverts_and_raises`; `backend/tests/test_c31_backend_event_correctness.py::test_fix02_reject_publish_is_post_commit`. **Ajuste de criterio declarado** (sin cambio de texto): `ruleset_version` no se incluye por diseño → superado por D66/RN-160 (2026-09-15, `docs/reglas_de_negocio.md:2124`), ese contador queda reservado a `update_config`, no a los comandos de acción correctiva — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados` y `openspec/changes/backlog-partial-stories-completion/design.md` → D-7 |
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
### 5.14 US-14: Listado de reglas — `completa`

| Criterio | Tests |
|---|---|
| Tabla con las reglas existentes | `backend/tests/test_rules_service.py::TestListRules::test_empty_returns_empty_list`, `::TestListRules::test_order_critical_before_high_before_medium_before_low`, `::TestListRules::test_same_severity_ordered_by_id`; `backend/tests/test_rules_router.py::test_get_rules_returns_200_with_auth`, `::test_get_rules_list_is_sorted_by_severity` |
| Fila con patrón, severidad y acción | **Actualización 2026-09-16 (carril L1, `1953209`)**: renderizado en `frontend/src/pages/Rules.tsx:120-133`, con `Rules.test.tsx` |
| Indicación del default `alert_only` | **Actualización 2026-09-16**: leyenda renderizada en `Rules.tsx:169-172`, con `Rules.test.tsx`. Comportamiento en el agente: `agent/tests/test_rules.py::test_rules_evaluate_no_match_default` |
| `ruleset_version` actual del sistema (C11) | **Actualización 2026-09-16 (`1953209`)**: `GET /rules/version` (`backend/app/modules/rules/router.py:103-109`) devuelve `RulesetVersionOut(version=get_ruleset_version(session))`; `test_rules_router.py::test_get_rules_version_returns_current_counter` (200, entero, incrementa tras crear), `::test_get_rules_version_no_auth_returns_401` |

---

<a id="us-15"></a>
### 5.15 US-15: Creación de una regla — `completa`

| Criterio | Tests |
|---|---|
| Formulario con patrón, severidad y acción | **Actualización 2026-09-16**: `frontend/src/pages/Rules.test.tsx::criterio 1: existe un formulario para crear una regla con pattern (glob+negación), severidad y acción`. Validación de enums: `backend/tests/test_rules_router.py::test_post_rules_invalid_severity_returns_422`, `::test_post_rules_invalid_action_returns_422` |
| Glob estándar y negación `!` | Glob: `backend/tests/test_rules_service.py::TestValidatePattern::test_valid_glob_star`, `::test_valid_glob_question`, `::test_valid_literal_path`, `::test_valid_bracket`, `::test_empty_string_raises`, `::test_whitespace_only_raises`; `backend/tests/test_rules_router.py::test_post_rules_empty_pattern_returns_422`. **Actualización 2026-09-16 (carril L1, `1953209`)**: la negación en el backend también está implementada — ver fila siguiente |
| La regla exclusiva gana sobre la inclusiva | `agent/tests/test_rules.py::test_rules_evaluate_exclusive_wins` (agente). **Actualización 2026-09-16 (`1953209`)**: también en el backend — `determine_severity_for_path` (`rules/service.py:59-89`) descarta primero los paths que matchean una regla exclusiva, y es la función usada por el camino real de ingesta (`events/service.py:399`); `test_rules_service.py::TestSeverityNegation::test_determine_severity_exclusive_pattern_wins_over_inclusive`, `::test_determine_severity_exclusive_does_not_affect_other_paths` |
| La regla se persiste | Indirecto: `backend/tests/test_rule_sync_outbox.py::test_create_rule_with_valkey_down_persists_pending_command` |
| Patrón no duplicado | **Actualización 2026-09-16 (`1953209`)**: `create_rule` rechaza el duplicado — `select(Rule).where(Rule.pattern == pattern)` seguido de `ValueError` → 422 (`rules/service.py:313-316`); `test_rules_service.py::TestWriteOperations::test_create_rule_duplicate_pattern_raises` (asserta que persiste exactamente 1 fila), `test_rules_router.py::test_post_rules_duplicate_pattern_returns_422` |
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
### 5.18 US-18: Sincronización automática de reglas — `completa`

| Criterio | Tests |
|---|---|
| Publica el set actualizado como `rule_sync` en `commands` | `backend/tests/test_rules_service.py::TestPublishRuleSync::test_one_agent_publishes_one_message`, `::test_no_agents_returns_zero`, `::test_two_agents_two_messages`, `::test_agent_without_secret_is_skipped`, `::test_target_agent_id_is_correct`, `::test_rules_included_in_payload`, `::test_inserts_published_command_row`; `backend/tests/test_rule_sync_outbox.py::test_create_rule_with_valkey_down_persists_pending_command`, `::test_pending_command_redelivered_when_valkey_recovers`, `::test_transient_failure_stops_batch_without_losing_pending_rows`, `::test_outbox_poller_survives_unexpected_exception`; `backend/tests/test_c32_sse_security_fixes.py::test_published_command_inserted_for_rule_sync` |
| Firma HMAC-SHA256 (C7) y `ruleset_version` (C11) | `backend/tests/test_rules_service.py::TestPublishRuleSync::test_signature_is_verifiable`; `backend/tests/test_rule_sync_outbox.py::test_pending_command_redelivered_when_valkey_recovers`. El campo `ruleset_version` dentro del JSON no se asserta directamente |
| El agente verifica firma y rechaza si es inválida | `agent/tests/test_reconnect_order.py::test_invalid_hmac_cursor_still_advances`; adyacente: `agent/tests/test_commands.py::test_hmac_invalid_discards_command` |
| Descarta versiones menores | `agent/tests/test_rules.py::test_rules_update_rejects_older_version`; `agent/tests/test_stability_fixes.py::test_rule_sync_rejects_older_version`, `::test_rule_sync_idempotent_same_version` |
| Reemplaza la caché sin reiniciar | `agent/tests/test_rules.py::test_rules_update_applies_newer_version`, `::test_rules_evaluate_inclusive_match` |
| Persiste el `ruleset_version` en `state.json` | `agent/tests/test_rules.py::test_rules_update_applies_newer_version`, `::test_rules_persist_via_state_not_direct`, `::test_save_state_preserves_rules`, `::test_cursor_persist_does_not_erase_rules` |
| Comandos pendientes antes que eventos encolados (W4) | `agent/tests/test_reconnect_order.py::test_drain_runs_after_command_flush`, `::test_cursor_loaded_on_restart`, `::test_first_start_uses_zero_cursor`, `::test_first_start_xread_from_origin`, `::test_cursor_persisted_on_each_message`, `::test_flush_timeout_continues_to_drain`, `::test_ack_listener_uses_persisted_cursor` |
| Confirma con `event_ack` (C3) | **Actualización 2026-09-16 (carril L1, `1953209`)**: la rama `rule_sync` de `agent/publisher.py:547-573` llama a `_commands._publish_ack(...)` con el `command_id` tras aplicar el ruleset, igual que `baseline_update` (cableado de producción en `agent/__main__.py:333-343`); `agent/tests/test_publisher_dispatch_integration.py::test_rule_sync_dispatches_event_ack` (docstring "US-18 criterio 8 / RN-58"; asserta `xadd` al stream `event_ack` con `command_type == rule_sync` y `status == ok`); `backend/tests/test_published_command_ack_tracking.py::test_rule_sync_persists_with_command_id_and_pending_ack_status`. El test `test_rule_sync_persists_with_null_ack_status`, que documentaba la decisión contraria, ya no existe en el repositorio |

---

<a id="us-19"></a>
### 5.19 US-19: Listado de alertas — `completa`

| Criterio | Tests |
|---|---|
| Lista ordenada por fecha descendente | Existencia del listado: `backend/tests/test_sse_alerts.py::test_list_alerts_no_filters`, `::test_get_alerts_returns_all`, `::test_get_alerts_pagination`, `::test_list_alerts_pagination`, `::test_list_alerts_empty`, `::test_get_alerts_no_auth_returns_401`. **Actualización 2026-09-16 (carril L3, `579b004`)**: el `ORDER BY created_at DESC` (`alerts/service.py:415`) ahora tiene test — `test_list_alerts_order_desc_by_created_at`, `::test_get_alerts_order_desc_by_created_at` |
| Fila con path, severidad, acción, fecha y canal | **Actualización 2026-09-16 (carril L3, `579b004`)**: `AlertResponse` expone `path` y `action_taken` por join a `events`, sin migración de esquema (`alerts/router.py:58-77`, comentado `# US-19`); `test_get_alerts_includes_path_and_action_taken`, `::test_get_alerts_action_taken_null_when_pending`, `::test_get_failed_alerts_includes_path_and_action_taken`. Severidad y estado ya estaban cubiertos: `backend/tests/test_sse_alerts.py::test_list_alerts_filter_severity_critical`, `::test_get_alerts_filter_severity_high`, `::test_get_alerts_serializa_status_derivado`, `::test_get_alerts_status_delivered_gana_sobre_failed` |
| Navegación al detalle del evento | **Actualización 2026-09-16 (carril L3, `579b004`)**: implementada en `frontend/src/pages/Alerts.tsx:140-145`; `Alerts.test.tsx::cada alerta es navegable hacia el detalle del evento asociado` (asserta `href="/events/99"`) |

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
| Banner del flag `queue_pressure_high` (D72/RN-166) | **Cerrada por cambio de código (Change 57, grupos 2 a 4, commit `2d07cb2`)**: el agente calcula el flag de una sola lectura del ratio (`agent/queue.py::QUEUE_PRESSURE_HIGH_THRESHOLD = 0.8`) y lo publica junto al float sin cambios. Agente: `agent/tests/test_heartbeat_queue_pressure_high.py` (ratio 0.85→true, 0.5→false, exactamente 0.8→false, tipo bool, firma HMAC, una sola lectura). Backend: `backend/tests/test_heartbeat_consumer.py::test_queue_pressure_high_persisted`, `::test_queue_pressure_high_absent_does_not_reset`, `::test_queue_pressure_high_non_bool_ignored`, `::test_queue_pressure_high_never_reported_reads_as_null`; `test_agent_mgmt.py::test_agents_expose_queue_pressure_high`. Frontend: `frontend/src/components/ui/AgentCard.test.tsx::AgentCard — banner de presión de cola alta (US-21/W3, D72/RN-166)` (flag true, ratio alto con flag false, ratio bajo con flag true, flag nulo/ausente). Persistencia del ratio (sin cambios): `agent/tests/test_queue.py::test_queue_pressure_zero_when_empty`, `::test_queue_pressure_positive_after_enqueue`, `::test_drop_oldest_on_limit`, `::test_drop_oldest_removes_chronologically_oldest` |

---

<a id="us-22"></a>
### 5.22 US-22: Re-scan de baseline — `completa`

| Criterio | Tests |
|---|---|
| Botón con selección de paths específicos | **Actualización 2026-09-16 (carril L5, `7f62348`/`8b3cab0`)**: `AgentRescanRequest.paths` (`backend/app/modules/agents/models.py:131-137`), con checkboxes en `AgentCard.tsx` y `RescanConfirmModal.tsx`; `RescanConfirmModal.test.tsx` cubre la lista de paths |
| Diálogo con los `pending` que serán superseded | `backend/tests/test_agent_mgmt.py::test_rescan_with_pending_no_force` (asserta el conteo y que no se publica nada); `RescanConfirmModal.test.tsx` |
| Confirmación explícita | `backend/tests/test_agent_mgmt.py::test_rescan_with_pending_no_force`; `RescanConfirmModal.test.tsx::onConfirm` |
| Supersesión + comando firmado (C7) con `ruleset_version++` (C11) | `backend/tests/test_agent_mgmt.py::test_rescan_with_pending_force`, `::test_rescan_no_pending_succeeds`, `::test_rescan_with_paths_supersedes_only_selected_paths`, `::test_rescan_with_paths_scopes_pending_count`; `backend/tests/test_published_command_ack_tracking.py::test_enqueue_rescan_baseline_creates_pending_command`; `backend/tests/test_stream_ack_durability_outbox.py::test_rescan_without_secret_reverts_and_raises`. **Actualización 2026-09-16**: `ruleset_version++` implementado (`agents/service.py:256-259`) y la supersesión ya se acota a los paths seleccionados (`service.py:229-254`), no a todos los pending del agente. Verificación de la firma del payload: SIN TEST |
| El agente verifica firma y versión | Firma: `agent/tests/test_commands.py::test_hmac_invalid_discards_command`; ruteo: `agent/tests/test_agent_config.py::test_dispatch_routes_rescan_baseline`. **Actualización 2026-09-16**: guard de versión implementado — `agent/commands.py:679-688`; `agent/tests/test_agent_config.py::test_rescan_baseline_handler_ignores_stale_version` |
| Regenera el baseline cifrado (W10) | `agent/tests/test_agent_config.py::test_rescan_baseline_handler_calls_run_scan`, `::test_run_scan_creates_baseline_entries`, `::test_run_scan_skips_nonexistent_path`, `::test_rescan_baseline_handler_scans_only_specified_paths`, `::test_rescan_baseline_handler_rejects_paths_outside_watch_roots`; cifrado: `agent/tests/test_baseline.py::test_encrypt_decrypt_roundtrip`, `::test_key_derivation_deterministic`, `::test_key_derivation_different_agents`, `::test_unique_nonce_per_write`, `::test_tampered_blob_raises`, `::test_gcm_detects_path_swap`, `::test_baseline_file_permissions` |
| Confirma con `event_ack` (C3) | `agent/tests/test_agent_config.py::test_rescan_baseline_handler_publishes_ack`; `agent/tests/test_commands.py::test_publish_ack_signs_command_ack_with_hmac`, `::test_publish_ack_logs_error_without_shared_secret` |
| Confirmación visual del envío | **Cerrada con el test que faltaba (Change 57, grupo 6, commit `2d07cb2`)**: `frontend/src/pages/Agents.test.tsx`, nuevo, mockea `@/api/client` y `sonner` y cubre `toast.success('Rescan iniciado')` (sin conflicto) y `toast.success('Rescan forzado iniciado')` (con 409 → modal → confirmar) |
| `audit_log` (W18) | `backend/tests/test_agent_mgmt.py::test_audit_log_on_rescan`, `::test_audit_log_on_rescan_includes_paths` |
| Botón deshabilitado si el agente está `draining` | **Actualización 2026-09-16 (carril L5)**: `AgentCard.test.tsx::el botón de rescan tiene el tooltip canónico exacto durante el drenaje` |

---

<a id="us-23"></a>
### 5.23 US-23: Notificación externa ante eventos críticos — `completa`

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): la historia
ya coincide con el código en la tabla `alerts` unificada (D6/RN-107). Se agrega evidencia de entrega
real de email vía n8n; el fallback SMTP directo del backend (segundo escalón de la cascada) sigue sin
evidencia de entrega real, sólo de código (ver fila "Cascada SMTP...").

| Criterio | Tests |
|---|---|
| Webhook ante `critical`/`high` | Por exclusión: `backend/tests/test_notifications.py::test_notify_skip_low_severity`, `::test_notify_skip_medium_severity`, `::test_notify_skip_superseded`. Severidad: `::test_determine_severity_critical`, `::test_determine_severity_high_over_low`, `::test_determine_severity_no_match`, `::test_determine_severity_no_rules`. Envío dado un `Alert`: `::test_notify_event_delivers_on_first_attempt`. El disparo positivo de `notify_if_applicable`: SIN TEST |
| Payload con `event_id`, path, severidad, acción, contexto de proceso y timestamps | **Actualización 2026-09-16.** La afirmación anterior era falsa contra este árbol: `_build_payload` (`backend/app/modules/alerts/service.py:144-177`) sí emite `event_id`, `path`, `severity`, `action_taken`, `process_pid`, `process_uid`, `process_exe`, `detected_at` y `received_at` — implementado en `670f3c3` (2026-08-24). `test_notification_payload_contract.py::test_payload_satisfies_rn53` (asserta cada uno de esos campos), `::test_absent_process_context_is_null_not_omitted`, `::test_action_taken_is_not_a_second_copy_of_status`, `::test_payload_carries_every_contract_field`, `::test_envelope_is_flat_not_nested` |
| n8n limitado a enrutador | Procedimiento reproducible declarado (carril L7, fila 3): `rg -n "n8n" backend/app/modules/*/router.py` no devuelve ningún endpoint inbound iniciado por n8n — el backend sólo emite webhooks salientes. Es evidencia estática de arquitectura, no una aserción automatizada dedicada |
| n8n reencamina por el canal configurado | Fuera del sistema. **Evidencia de entrega real (laboratorio VPS, aceptación 2026-09-15):** `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/a4-12.6-webhook-email.txt` registra una respuesta `202` del router n8n con `{"channel":"email","delivered":true,"error":null}` sobre Gmail SMTP configurado como canal de salida. Cubre el canal de email de n8n — **no** el fallback SMTP directo del backend (el segundo escalón de la cascada, fila siguiente) |
| Retry con delays 5 s / 30 s / 120 s (W11) | `backend/tests/test_notifications.py::test_notify_event_retry_3x_then_dlq` (compara la secuencia real contra `RETRY_DELAYS`) |
| Cascada SMTP → webhook directo → log crítico | Parcial: `backend/tests/test_notifications.py::test_send_smtp_skipped_when_no_host`, `::test_send_webhook_fallback_skipped_when_no_url`, `::test_send_n8n_skipped_when_no_url`, `::test_send_n8n_success`, `::test_send_n8n_failure`, `::test_send_log_only_always_succeeds`, `::test_log_only_no_entrega_si_hay_primarios_configurados`; `backend/tests/test_c31_backend_event_correctness.py::test_fix01_no_primaries_log_only_delivers`. **Entrega real del fallback SMTP directo del backend, verificada el 2026-09-15 (task 8.5 del change `backlog-partial-stories-completion`):** `send_smtp` (`app/modules/alerts/notifier.py`) contra un SMTP de captura desechable (`axllent/mailpit`, `docker compose -p fim-c55`, sin STARTTLS/SSL, puerto 1025), sin `N8N_WEBHOOK_URL` configurada (n8n agotado/ausente, forzando el segundo escalón de la cascada) — `send_smtp` retornó `True` y el mensaje llegó al capturador: `Mailpit message ID 1NQ73pW1kKvdeH7iLt9vAO`, `Date: 2026-09-15T18:43:41.266Z`, `Subject: [FIM Alert] severity=critical`, `From: fim-alerts@fim.local`, `To: admin@fim.local`, cuerpo = el payload JSON de `_build_payload` con `notification_id="c55-smtp-evidence-0001"`. El compose se levantó y se destruyó dentro de la misma sesión (`docker compose -p fim-c55 down`); no queda infraestructura residual. Esta corrida es evidencia unitaria del canal (`send_smtp` invocado directamente, no la cascada completa `notify_event` contra Postgres real) — confirma que el canal SMTP directo entrega, no reemplaza una corrida end-to-end sobre el laboratorio |
| Fila en fallo terminal con `last_error`, `failed_at`, `retry_count` (W11, D6/RN-107) | **Ajuste de criterio declarado**: el texto original exigía una fila en `failed_notifications(event_id, payload_json, last_error, failed_at, retry_count)`; hoy es la fila de `alerts` en fallo terminal, sin `payload_json` — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`. `backend/tests/test_notifications.py::test_notify_event_retry_3x_then_dlq`; `backend/tests/test_c31_backend_event_correctness.py::test_fix01_primary_fails_dlq_activated` |
| La caída de n8n no compromete la operación | Indirecto: `::test_send_n8n_failure`, `::test_notify_event_retry_3x_then_dlq`, `::test_log_only_no_entrega_si_hay_primarios_configurados` |

---

<a id="us-24"></a>
### 5.24 US-24: Gestión de paths monitoreados — `completa`

| Criterio | Tests |
|---|---|
| Lista de paths por agente | `backend/tests/test_agent_mgmt.py::test_get_agents_list`, `::test_get_agent_detail`; `backend/tests/test_agent_watch_path_status.py::test_list_agents_exposes_watch_path_status`, `::test_get_agent_exposes_watch_path_status`, `::test_agent_that_never_reported_has_null_status_map`. **Actualización 2026-09-16**: render en `AgentCard.test.tsx` — describe `AgentCard — lista de paths monitoreados (US-24/C1)`, `::muestra todos los watch_paths actualmente monitoreados por el agente` |
| Agregar un path | **Actualización 2026-09-16**: `AgentCard.test.tsx` — describe `AgentCard — agregar un nuevo path (US-24/C2)`, `::agrega el path escrito al listado y lo envía en onConfigSave al guardar`; efecto backend: `backend/tests/test_agent_mgmt.py::test_agent_config_updates_watch_paths` |
| Quitar un path | **Actualización 2026-09-16**: `AgentCard.test.tsx` — describe `AgentCard — quitar un path existente (US-24/C3)`, `::quita el path seleccionado del listado y lo envía sin él en onConfigSave al guardar`; efecto backend: mismo test (replace-all) |
| Persistencia de la configuración | `backend/tests/test_agent_mgmt.py::test_agent_config_updates_watch_paths`, `::test_agent_config_not_found` |
| `update_config` firmado (C7) con `ruleset_version++` (C11) | `backend/tests/test_agent_mgmt.py::test_agent_config_updates_watch_paths`, `::test_agent_config_hmac_valid`; `backend/tests/test_published_command_ack_tracking.py::test_enqueue_update_config_creates_pending_command_without_advancing_version`; `backend/tests/test_stream_ack_durability_outbox.py::test_update_config_without_secret_reverts_and_raises`. El incremento efectivo del contador: SIN TEST |
| El agente verifica firma y versión y recarga en caliente | `agent/tests/test_agent_config.py::test_dispatch_routes_update_config`, `::test_update_config_handler_reloads_detector`; `agent/tests/test_commands.py::test_hmac_invalid_discards_command`, `::test_update_config_preflight_rerun_does_not_block_reload`; `agent/tests/test_audit_fixes.py::test_update_config_stale_version_ignored` |
| Baseline scan de paths nuevos cifrado (W10) | `agent/tests/test_agent_config.py::test_update_config_handler_reloads_detector` (asserta `run_scan` sólo con el path nuevo), `::test_run_scan_creates_baseline_entries`; cifrado: `agent/tests/test_baseline.py::test_encrypt_decrypt_roundtrip`, `::test_unique_nonce_per_write`, `::test_tampered_blob_raises`, `::test_key_derivation_deterministic`, `::test_gcm_detects_path_swap` |
| Confirma con `event_ack` (C3) | `agent/tests/test_agent_config.py::test_update_config_handler_publishes_ack`, `::test_update_config_updates_state_ruleset_version`; `agent/tests/test_commands.py::test_update_config_without_registry_still_works`, `::test_update_config_write_failure_marks_registry_and_logs_error`. El avance de `ruleset_version_applied` en el backend ante este ack: SIN TEST |
| Bootstrap desde YAML; autoridad en PostgreSQL | `agent/tests/test_stability_fixes.py::test_update_config_writes_to_loaded_path`, `::test_update_config_falls_back_to_default_path`; `agent/tests/test_commands.py::test_update_config_missing_file_is_logged_and_marks_registry_false`, `::test_update_config_successful_write_clears_degraded_persistence_state`, `::test_update_config_reruns_preflight_and_updates_registry`. La reconciliación al arrancar: SIN TEST |
| `audit_log` (W18) | `backend/tests/test_agent_mgmt.py::test_audit_log_on_config`, `::test_audit_log_detail_is_valid_json_with_quotes_and_backslashes` |
| Botones deshabilitados si el agente está `draining` | **Actualización 2026-09-16 (carril L7, `fca97b5`)**: el botón "Guardar paths" sí se deshabilita durante el drenaje (`AgentCard.tsx:243-249`, más "Editar" en `:199-207`); `AgentCard.test.tsx::el botón "Guardar paths" está deshabilitado con el tooltip canónico cuando el agente está draining` |

**Advertencia metodológica — caducada el 2026-09-16 (`0051e45`).** Hasta el corte del 2026-09-11,
`agent/tests/test_agent_config.py::test_reload_watch_paths_marks_new` y
`::test_reload_watch_paths_unmarks_removed` no invocaban el método que decían probar: reimplementaban
la aritmética de conjuntos dentro del propio test. Hoy (`agent/tests/test_agent_config.py:211-256`)
invocan el método real `FanotifyDetector.reload_watch_paths` y assertan `FAN_MARK_ADD`/`FAN_MARK_REMOVE`
sobre `_fan_mod.mark`, cerrando la reconfiguración real de las marcas de `fanotify`.

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
### 5.26 US-26: Paginación de eventos — `completa`

| Criterio | Tests |
|---|---|
| 50 eventos por página por defecto | `backend/tests/test_event_listing_contract.py::test_list_events_default_page_size_is_50`; `frontend/src/utils/eventFilters.test.ts::parseEventFilters — retorna defaults cuando el URLSearchParams está vacío` |
| Navegación numerada | **Actualización 2026-09-16 (carril L2, `7f5685b`)**: `frontend/src/components/ui/Pagination.tsx:14-126` implementa Primera / Anterior / ventana de números con `aria-current` / Siguiente / Última, cableado en `Events.tsx:216`; `Pagination.test.tsx` (9 casos) |
| Input "ir a página" con validación | **Actualización 2026-09-16 (`7f5685b`)**: validación de rango `1..totalPages` en `Pagination.tsx`; `Pagination.test.tsx` cubre válido, fuera de rango y no numérico |
| `GET /events?page=N&page_size=50` | `backend/tests/test_event_listing_contract.py::test_list_events_default_page_size_is_50` (segunda página); `backend/tests/test_c31_backend_event_correctness.py::test_fix04_pagination_sql`; `backend/tests/test_event_router.py::test_list_events_returns_200_with_auth`; `frontend/src/utils/eventFilters.test.ts::serializeEventFilters — omite page cuando es 1 (default)`, `::incluye page cuando es mayor a 1` |
| La paginación respeta los filtros activos | `backend/tests/test_event_listing_contract.py::test_pagination_total_respects_status_filter`, `::test_pagination_total_respects_path_prefix_filter`, `::test_pagination_total_respects_date_range_filter`, `::test_superseded_filter_applies_to_total_not_only_to_the_page` — los cuatro usan `page_size=1` para que un `total` mal calculado no quede disimulado por una página que igual entra entera |

---

<a id="us-27"></a>
### 5.27 US-27: Primer login con cambio obligatorio de password — `completa`

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): la política
de complejidad (mayúscula, minúscula, dígito) y la exigencia de `current_password` también con scope
`password_change_only` (D-2) se implementaron y testearon en ambos lados (backend + frontend), con
los mismos casos de prueba (ASCII, `Ñ`, dígitos) para verificar paridad de clases de carácter.

| Criterio | Tests |
|---|---|
| El seed crea el admin con `must_change_password: true` | Indirecto: `backend/tests/test_auth.py::test_login_primer_admin_must_change_password_true`, `::test_login_incluye_objeto_user`. Los tests de seed (`backend/tests/modules/users/test_user_management.py::test_seed_admin_usa_admin_email_configurado`, `::test_seed_admin_usa_default_cuando_no_hay_admin_email`, `::test_seed_admin_idempotente_con_admin_existente`) sólo assertan email e idempotencia |
| Tokens con scope `password_change_only` | `backend/tests/test_auth.py::test_scope_password_change_only_en_access_token`, `::test_login_primer_admin_must_change_password_true`; `backend/tests/test_c22_auth.py::test_create_access_token_scope_password_change_only_sigue_teniendo_type_access` |
| Redirect forzado al formulario en `/change-password` (D70/RN-164) | **Actualización 2026-09-16.** La afirmación anterior era falsa: `ProtectedRoute.tsx:44-54` implementa el gate y `ProtectedRoute.test.tsx` lo asserta en sus dos ramas — redirige a `/change-password` con scope forzado, y no redirige si ya está ahí (evitando el loop). **Ajuste de criterio declarado**: la ruta era `/account/change-password` — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados` |
| Formulario con password actual, complejidad y confirmación | Cerrado por el change `backlog-partial-stories-completion`: `frontend/src/pages/ForcePasswordChange.test.tsx::ForcePasswordChange — US-27 (D-2, complejidad y contraseña actual) — lista los requisitos del password en el formulario`, `::contraseña actual vacía muestra error y no llama a changePasswordApi`, `::password nuevo sin mayúscula muestra error y no llama a changePasswordApi`, `::password nuevo sin minúscula muestra error y no llama a changePasswordApi`, `::password nuevo sin número muestra error y no llama a changePasswordApi`, `::password corto muestra error y no llama a changePasswordApi`, `::password válido con Ñ como única mayúscula llama a changePasswordApi con current_password`, `::un 401 del backend (contraseña actual incorrecta) muestra el detail recibido` |
| El backend valida la actual y la complejidad | `backend/tests/test_auth.py::test_password_policy_error_password_valida`, `::test_password_policy_error_corta`, `::test_password_policy_error_sin_mayuscula`, `::test_password_policy_error_sin_minuscula`, `::test_password_policy_error_sin_digito`, `::test_password_policy_error_mayuscula_ene_con_tilde_es_valida` (unitarios de `password_policy_error`); HTTP: `::test_change_password_short_retorna_422`, `::test_change_password_sin_complejidad_retorna_422[sin_mayuscula/sin_minuscula/sin_digito]`, `::test_change_password_mayuscula_no_ascii_cuenta`. `current_password` exigido en ambos scopes (D-2): `::test_change_password_current_password_incorrecto_scope_forzado_retorna_401`, `::test_change_password_current_password_ausente_scope_forzado_retorna_401`, `::test_change_password_current_password_correcto_scope_normal`, `::test_change_password_current_password_incorrecto_scope_normal_retorna_401` |
| Argon2id (C9) | `backend/tests/test_auth.py::test_change_password_hashea_con_argon2id_c9_y_no_verifica_contra_anterior` (prefijo `$argon2id$v=19$m=65536,t=3,p=4$`, verifica contra el nuevo y no contra el anterior) |
| Flag a `false` y tokens nuevos | `backend/tests/test_auth.py::test_change_password_current_password_correcto_scope_normal` (`must_change_password is False` releído de la base). Cubierto también de forma incidental por el helper `_full_access_login`, precondición de `::test_logout_invalida_access_token` y `::test_logout_invalida_tambien_el_refresh_token`. El backend fuerza re-login en vez de emitir tokens nuevos |
| Bloqueo de otras rutas | `backend/tests/test_c22_scope_gate.py::test_get_events_scope_password_change_only_retorna_403`, `::test_get_event_by_id_scope_password_change_only_retorna_403`, `::test_get_rules_scope_password_change_only_retorna_403`, `::test_get_rule_by_id_scope_password_change_only_retorna_403`, `::test_get_events_full_access_token_no_recibe_403_por_scope`; `backend/tests/test_auth.py::test_change_password_con_scope_password_change_only` |
| Re-exigencia si cierra sin completar | `backend/tests/test_auth.py::test_change_password_no_completado_se_vuelve_a_exigir` (segundo login sin completar el cambio → `must_change_password: true` y scope `password_change_only`) |
| `audit_log` (W18) | `change_password`: `backend/tests/test_auth.py::test_change_password_deja_fila_en_audit_log`. **Cerrado con el test que faltaba (Change 57, grupo 6, commit `2d07cb2`)**: `login`/`logout` ahora tienen aserción — `::test_login_deja_fila_en_audit_log`, `::test_logout_deja_fila_en_audit_log` |

---

<a id="us-28"></a>
### 5.28 US-28: Banner de degradación del sistema — `completa`

| Criterio | Tests |
|---|---|
| Poll de `GET /health/components` cada 10 s | **Actualización 2026-09-16 (carril L2, `0680783`)**: `SystemBanner.test.tsx::consulta GET /health/components cada 10 segundos` asserta 3 llamadas tras dos avances de 10 s con fake timers |
| Estado de `postgres`, `valkey`, `n8n` y agentes | Backend: `backend/tests/test_notifications.py::test_health_all_ok`, `::test_health_valkey_down`, `::test_health_n8n_degraded_when_not_configured`; `backend/tests/test_health_n8n_check.py::test_n8n_ok_on_200_head`, `::test_n8n_down_on_500`, `::test_n8n_fallback_to_get_when_head_returns_404`, `::test_n8n_fallback_to_get_when_head_returns_405`, `::test_n8n_down_on_403_no_fallback`, `::test_n8n_fallback_to_get_still_fails`, `::test_n8n_fallback_to_get_on_connection_error`, `::test_n8n_degraded_when_not_configured`. **La porción `agents` del resultado del backend sigue sin asertarse**; el consumo de esa porción sí: `frontend/src/components/layout/SystemBanner.test.tsx::trata al subsistema de agentes como degradado cuando su status no es ok` |
| Banner rojo con componente y timestamp | Banner y componente: `frontend/src/components/layout/SystemBanner.test.tsx::muestra un banner rojo que nombra el componente degradado`, `::nombra todos los componentes caidos a la vez` (que además verifica que no nombra al que está sano), `::no muestra ningun banner cuando todos los componentes estan ok`. **Actualización 2026-09-16 (carril L2, `0680783`)**: el timestamp del último check saludable por componente está implementado (`lastHealthyAtRef`, `SystemBanner.tsx:33,41-50,72-73`) y testeado (`::muestra el timestamp del ultimo check saludable del componente afectado`) |
| Cerrable y reaparece en el siguiente poll | **Actualización 2026-09-16 (`0680783`)**: botón de cierre implementado (`dismissedFor` ligado a `checked_at`, `SystemBanner.tsx:39,60-61,78-85`); `::es cerrable manualmente y reaparece en el siguiente poll si la condicion persiste` |
| No bloquea la UI | **Actualización 2026-09-16**: `SystemBanner.test.tsx::no bloquea el uso normal de la UI` (verifica ausencia de `fixed`/`absolute`/`aria-modal`) |
| Webhook n8n ante cambio de estado | `backend/tests/test_notifications.py::test_health_state_change_triggers_webhook`, `::test_health_no_webhook_on_first_call` |

`GET /health/components` como endpoint HTTP sigue sin invocarse en ningún test de backend: todos
llaman `check_components()` directamente. Los tests de `backend/tests/test_health.py` apuntan a
`GET /health` (liveness simple), no a `/health/components`.

---

<a id="us-29"></a>
### 5.29 US-29: Visualización y reintento de webhooks fallidos — `completa`

Actualizado por el change `backlog-partial-stories-completion` (Change 55, 2026-09-15): el banner
pasó a `GET /alerts/failed/count` (D-3, D-4) con el texto y el link literales de la historia, y
`POST /alerts/{id}/retry` / `DELETE /alerts/{id}` ahora registran `audit_log` (D-5). **Cerrada con el
test que faltaba (Change 57, grupo 6, commit `2d07cb2`)**: `last_error`/`retry_count`/`failed_at` en
la respuesta HTTP ahora tienen aserción. El banner sin umbral (D6/RN-107, reescritura de RN-102) y la
ruta `/alerts/failed` (D70/RN-164) son ajustes de criterio declarados — ver
`docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`.

| Criterio | Tests |
|---|---|
| Banner amarillo sin umbral (D6/RN-107, reescritura de RN-102) | **Ajuste de criterio declarado**: el texto original exigía `retry_count >= 3`. Cerrado sin umbral por D6/RN-107 (D-3 del design de Change 55) — fallo terminal puro, `retry_count=0` cuenta igual que `retry_count=3`: `backend/tests/test_notifications.py::test_get_failed_alerts_count_ignores_retry_count_threshold`, `::test_get_failed_alerts_count_empty_dlq`, `::test_get_failed_alerts_count_requires_admin`. Banner: `frontend/src/components/layout/AlertsBanner.test.tsx::muestra un banner amarillo con el texto literal de US-29 cuando count=4`, `::usa el singular cuando count=1`, `::una alerta con retry_count=0 (n8n sin configurar) igual cuenta — sin umbral`, `::consulta GET /alerts/failed/count` |
| Link a la vista de fallidas en `/alerts/failed` (D70/RN-164) | **Ajuste de criterio declarado**: el texto original decía `/notifications/failed`. `frontend/src/components/layout/AlertsBanner.test.tsx::el enlace apunta a /alerts/failed` — ya coincide con la ruta real (`App.tsx`), corregida en la historia |
| Tabla con `event_id`, primer intento, error y `retry_count` | `backend/tests/test_notifications.py::test_get_failed_alerts_returns_only_failed`, `::test_get_failed_alerts_empty`; `backend/tests/test_sse_alerts.py::test_get_failed_alerts_serializa_status`. **Cerrado con el test que faltaba (Change 57, grupo 6, commit `2d07cb2`)**: `test_notifications.py::test_get_failed_alerts_expone_last_error_retry_count_failed_at` asserta `last_error`, `retry_count` y `failed_at` (ISO-8601 con zona) en la respuesta HTTP — el fix incluyó normalizar esos tres campos a UTC en `_to_alert_response` (`_as_utc`), porque bajo SQLite el JSON perdía la zona horaria |
| Reintentar / Descartar por fila | Reintentar: `backend/tests/test_notifications.py::test_retry_alert_resets_dlq_state_and_reschedules` (resetea `failed_at`, `last_error` y `retry_count`, y verifica que la cascada se vuelve a disparar sobre la misma alerta y el mismo evento), `::test_retry_alert_delivers_and_leaves_the_dlq` (entrega por n8n, marca el canal y la fila desaparece de `list_failed_alerts`), más las rutas de error `::test_retry_alert_already_delivered`, `::test_retry_alert_not_found`, `::test_post_retry_alert_409_if_delivered`, `::test_post_retry_alert_404_if_not_found`. Descartar: `::test_delete_alert_204`, `::test_delete_alert_404_if_not_found`, `::test_delete_alert_service`. UI (fila y bulk): `frontend/src/pages/FailedAlerts.test.tsx::"Reintentar" por fila llama POST /alerts/{id}/retry`, `::seleccionar tres filas y usar el bulk llama POST /alerts/{id}/retry una vez por id`, `::"Descartar" confirmado llama DELETE /alerts/{id}` |
| Bulk "Reintentar todos" | El contrato vigente es N llamadas individuales del frontend (no hay endpoint de bulk), verificado end-to-end: `frontend/src/pages/FailedAlerts.test.tsx::seleccionar tres filas y usar el bulk llama POST /alerts/{id}/retry una vez por id`; cada llamada deja su propia fila `audit_log`: `backend/tests/test_notifications.py::test_post_retry_alert_masivo_deja_una_fila_por_alerta` |
| La fila se elimina tras un reintento exitoso | Cubierto en su efecto observable: `backend/tests/test_notifications.py::test_retry_alert_delivers_and_leaves_the_dlq` asserta `list_failed_alerts(session) == []`. La implementación no borra la fila sino que marca `delivered_at` |
| El banner desaparece con la tabla vacía | `frontend/src/components/layout/AlertsBanner.test.tsx::no muestra ningun banner cuando count=0`, `::el banner desaparece cuando un refetch devuelve count=0` |
| `audit_log` (W18) | Cerrado por el change `backlog-partial-stories-completion` (D-5): `backend/tests/test_notifications.py::test_post_retry_alert_deja_fila_en_audit_log` (`action="alert_retry"`, `user_id` del admin, `target_type="alert"`, `target_id`, `detail` con `event_id`), `::test_post_retry_alert_masivo_deja_una_fila_por_alerta`, `::test_post_retry_alert_409_no_deja_fila_en_audit_log`, `::test_post_retry_alert_404_no_deja_fila_en_audit_log`, `::test_delete_alert_deja_fila_en_audit_log` (`action="alert_discard"`), `::test_delete_alert_404_no_deja_fila_en_audit_log` |

La tabla `failed_notifications` no existe: su rol lo cumple `alerts` con `failed_at NOT NULL` y
`delivered_at IS NULL`, sin columna de payload.

---

<a id="us-30"></a>
### 5.30 US-30: Indicador de agente en shutdown graceful — `completa`

| Criterio | Tests |
|---|---|
| Ante `SIGTERM` deja de aceptar eventos de `fanotify` | **Actualización 2026-09-16 (carril L5, `8b3cab0`)**: `set_draining()` / `_try_enqueue` en `agent/detector.py:392-395`; `agent/tests/test_detector_draining.py::test_set_draining_stops_accepting_new_events` (la cola queda en 0 tras `set_draining(True)`) |
| Drena la cola con timeout de 30 s | **Actualización 2026-09-16 (`8b3cab0`)**: `_drain_then_stop` (`agent/__main__.py:144`) tiene timeout por defecto 30 s; `agent/tests/test_drain_then_stop.py::test_drain_then_stop_default_timeout_is_30_seconds` (contra la firma viva), `::test_drain_then_stop_times_out_if_queue_never_empties`. Mecánica genérica preexistente: `agent/tests/test_publisher.py::test_drain_queue_publishes_in_fifo_order`; `agent/tests/test_reconnect_order.py::test_drain_runs_after_command_flush`, `::test_flush_timeout_continues_to_drain` |
| Heartbeats con `shutdown: true` | `agent/tests/test_shutdown_heartbeat.py::test_shutdown_flag_set_on_sigterm`, `::test_publisher_set_shutdown_changes_property`, `::test_heartbeat_reads_publisher_shutdown`, `::test_heartbeat_fallback_to_shutdown_flag_when_no_publisher`, `::test_heartbeat_publisher_beats_shutdown_flag`; `agent/tests/test_stability_fixes.py::test_shutdown_handler_safe_before_queue_created` |
| El backend marca `draining` | `backend/tests/test_heartbeat_consumer.py::test_heartbeat_shutdown_marks_draining` |
| Indicador "Drenando N eventos" | **Actualización 2026-09-16 (carril L5, `1226ed9`)**: `AgentCard.tsx:137` muestra "Drenando {queue_size} eventos"; `AgentCard.test.tsx::un agente draining muestra "Drenando N eventos" con el queue_size actual` y su caso negativo |
| Botones deshabilitados con tooltip | **Actualización 2026-09-16.** La afirmación anterior era falsa: el tooltip literal de la historia está implementado — `DRAINING_TOOLTIP = 'No disponible durante shutdown graceful'` (`AgentCard.tsx:19`); 3 tests de tooltip en `AgentCard.test.tsx` |
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
salió del rastreo de código, no del texto de las historias.

> **Reverificada el 2026-09-16 sobre `2475de8`.** La mayoría de estas filas **caducó**: el porte de
> los carriles V10 a `devel` (2026-09-15) implementó el endpoint de cadena, el modo binario del diff,
> la paginación numerada, `GET /rules/version`, el rechazo de patrón duplicado, la negación `!` en el
> backend, el `event_ack` de `rule_sync`, `path`/`action_taken` en alertas, el timestamp y el cierre
> del banner, la selección de paths del rescan con su guard de versión, y el cese de aceptación de
> `fanotify` en el drenaje. Cada fila afectada queda anotada abajo con su estado real actual, en vez
> de borrarse, para que el lector pueda contrastar contra el corte anterior.
>
> **Cerrada el 2026-09-17 (commit `2d07cb2`, `backlog-full-stories-completion`, Change 57).** Las
> filas restantes de US-07, US-11, US-22, US-27 y US-29 caducaron o quedaron declaradas como ajuste de
> criterio; ninguna sigue siendo una brecha abierta. Esta sección se conserva completa como historia
> de qué estaba pendiente en cada corte, no porque queden ítems sin cerrar.

| Historia | Criterio | Estado real |
|---|---|---|
| US-07 | Selector con los 7 estados | **Caducada el 2026-09-17** (Change 57, grupo 5, commit `2d07cb2`): `ALL_STATUSES` enumera los 7, sin depender del toggle — ver §5.7 |
| US-08 | "Tipo de acción" del evento | **Caducada el 2026-09-16**: existe como campo derivado — `derive_action_type` (`events/service.py:188-196`) y `EventDetailOut.action_type` (`router.py:79`), con 5 tests |
| US-08, US-10 | Posición en la cadena y navegación | **Caducada el 2026-09-16**: `EventDetail.tsx:35-38,186-201` muestra "Posición N de M" y enlaza a la cadena; testeado en `EventDetail.test.tsx:221-235` |
| US-09 | Modo binario con hashes y hex dump | **Caducada el 2026-09-16** (`1c68e79`): `_hex_dump` y `_binary_diff_info` en `agent/detector.py:235-285`, persistidos y renderizados por `BinaryComparison`; 7 tests |
| US-09 | `react-diff-viewer-continued` | **Caducada el 2026-09-16**: es la biblioteca en uso (`package.json:22`, `^3.4.0`) con `splitView`; sin `dangerouslySetInnerHTML` en el código |
| US-10 | Endpoint de cadena de eventos por path | **Caducada el 2026-09-16**: `GET /events/{id}/chain` (`events/router.py:180-197`) + `EventChain.tsx` + ruta en `App.tsx:54` |
| US-11 | Baseline con el hash actual del filesystem | **Ajuste de criterio declarado el 2026-09-17** (D71/RN-165, ratifica D2): el texto canónico se alineó a `event.hash_detected`, el comportamiento vigente desde `8d37075` — ver §5.11 y `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados` |
| US-12 | `ruleset_version` en `restore_file` / `quarantine_file` | **Ajuste de criterio declarado** (sin cambio de texto): superado por D66/RN-160 (2026-09-15) — excluido por diseño, no es una brecha abierta — ver `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados` |
| US-14 | `ruleset_version` global del sistema expuesto | **Caducada el 2026-09-16** (`1953209`): `GET /rules/version` (`rules/router.py:103-109`), con `test_get_rules_version_returns_current_counter` |
| US-15 | Validación de patrón duplicado | **Caducada el 2026-09-16** (`1953209`): `create_rule` rechaza el duplicado (`rules/service.py:313-316`) → 422, con test en servicio y router |
| US-15 | Precedencia de la negación `!` en el backend | **Caducada el 2026-09-16** (`1953209`): `determine_severity_for_path` (`rules/service.py:59-89`) trata el prefijo `!` con exclusiva-gana, y es la función del camino real de ingesta (`events/service.py:399`) |
| US-18 | `event_ack` tras `rule_sync` | **Caducada el 2026-09-16** (`1953209`): `agent/publisher.py:547-573` publica el ack; el test que documentaba lo contrario ya no existe |
| US-19 | `path` y tipo de acción en `AlertResponse`; link al evento | **Caducada el 2026-09-16** (`579b004`): `AlertResponse` expone `path` y `action_taken` (`alerts/router.py:58-77`) y `Alerts.tsx:140-145` enlaza al evento |
| US-21 | `queue_size` del agente | Cerrado el 2026-09-12 (`7f62348`, `1226ed9`): persistido desde el heartbeat y mostrado en la tarjeta — ver §5.21 |
| US-21 | Webhook n8n al pasar un agente a `dead` | Cerrado el 2026-09-12 (`7f62348`): `_notify_agent_dead` por agente. Pendiente fuera de US-21: cascada, DLQ y rama `agent_dead` en el enrutador (Change 48) |
| US-21 | Umbral del 80% para `queue_pressure` (W3) | Cerrado el 2026-09-12 (`1226ed9`): banner por encima del 80 % en `AgentCard.tsx:80-83` |
| US-22 | Selección de paths para el re-scan | **Caducada el 2026-09-16** (`7f62348`, `8b3cab0`): `AgentRescanRequest.paths` (`agents/models.py:131-137`) + checkboxes en `AgentCard.tsx`, con la supersesión acotada a los paths elegidos |
| US-22 | `ruleset_version++` en `rescan_baseline` y guard en el agente | **Caducada el 2026-09-16**: `agents/service.py:256-259` incrementa el contador y `agent/commands.py:679-688` descarta versiones obsoletas, ambos con test |
| US-22 | Confirmación visual de que la solicitud fue enviada | **Caducada el 2026-09-17** (Change 57, grupo 6, commit `2d07cb2`): `Agents.test.tsx` cubre el toast sin y con conflicto 409 — ver §5.22 |
| US-23 | Contexto de proceso, `received_at` y acción en el payload del webhook | **Caducada el 2026-09-16**: `_build_payload` (`alerts/service.py:144-177`) sí los emite desde `670f3c3` (2026-08-24), asertado por `test_payload_satisfies_rn53` |
| US-26 | Navegación numerada e input "ir a página" | **Caducada el 2026-09-16** (`7f5685b`): `Pagination.tsx:14-126` implementa ambos, cableado en `Events.tsx:216`, con 9 tests |
| US-27 | Reglas de complejidad de la contraseña | Cerrado por el change `backlog-partial-stories-completion` (Change 55): `password_policy_error` en `backend/app/core/security.py`, exigido también con scope `password_change_only` (D-2) — ver §5.27 |
| US-27 | `audit_log` de `login` / `logout` / `change_password` | **Caducada el 2026-09-17** (Change 57, grupo 6, commit `2d07cb2`): las tres acciones tienen aserción — `test_login_deja_fila_en_audit_log`, `test_logout_deja_fila_en_audit_log`, `test_change_password_deja_fila_en_audit_log` |
| US-05, US-29 | Umbral `retry_count >= 3` en el banner amarillo | **Ajuste de criterio declarado**: D6/RN-107 (reescritura de RN-102) reemplazó la base del banner por fallo terminal sin umbral — ver D-3 del design de Change 55 y `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`. `test_get_failed_alerts_count_ignores_retry_count_threshold` asserta explícitamente que una alerta con `retry_count=0` cuenta igual que una con `retry_count=3` |
| US-29 | Vista `/notifications/failed` | **Ajuste de criterio declarado** (D70/RN-164): la ruta real siempre fue `/alerts/failed` y la historia fue corregida para nombrarla — sin redirect desde `/notifications/failed` (ver Resolved #2 del design de Change 55 y `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`) |
| US-28 | Timestamp del último check saludable y cierre manual del banner | **Caducada el 2026-09-16** (`0680783`): `lastHealthyAtRef` (`SystemBanner.tsx:33,41-50,72-73`) y `dismissedFor` ligado a `checked_at` (`:39,60-61,78-85`), ambos con test |
| US-28 | Porción `agents` de `check_components` del lado backend | **Vigente**: `_check_agents` (`core/health.py:119-133`) no tiene test propio; la rama `has_online` nunca se ejercita con filas `Agent` reales. El contrato del endpoint sí está asertado por `test_health.py` |
| US-29 | Tabla `failed_notifications` con `payload_json` | Su rol lo cumple `alerts`, sin payload |
| US-29 | Bulk retry y `audit_log` de reintento/descarte | Cerrado por el change `backlog-partial-stories-completion` (Change 55): el bulk sigue siendo N llamadas individuales del frontend (contrato ya vigente), y cada una deja fila `alert_retry`/`alert_discard` en `audit_log` — ver §5.29 |
| US-30 | Cese de aceptación de eventos ante `SIGTERM`; "Drenando N eventos" | **Caducada el 2026-09-16** (`8b3cab0`, `1226ed9`): `set_draining()` en `agent/detector.py` con `test_set_draining_stops_accepting_new_events`; indicador en `AgentCard.tsx:137` y tooltip canónico en `:19`, ambos con test |
| US-21 | Flag booleano `queue_pressure_high` emitido por el agente | **Caducada el 2026-09-17** (D72/RN-166, Change 57, grupos 2 a 4, commit `2d07cb2`): el agente ahora publica `queue_pressure_high` (booleano) calculado de una sola lectura del ratio, junto al float `queue_pressure` sin cambios; el banner de `AgentCard` se deriva sólo del flag. Ver `agent/tests/test_heartbeat_queue_pressure_high.py` y `AgentCard.test.tsx::AgentCard — banner de presión de cola alta (US-21/W3, D72/RN-166)` |

**Salió de esta lista**: el conteo del estado `superseded` en el dashboard (US-04). Faltaba en
`EVENT_STATUSES` y en `statuses`, y ambas listas fueron corregidas al escribirse el test que lo
detectó.

## 7. Brechas ordenadas por costo de cierre

Reordenado el 2026-08-19. De más barata a más cara, con el esfuerzo estimado de escritura de test
asumiendo la infraestructura existente, que hoy incluye tests de componente.

> **Estado al 2026-09-16 (`2475de8`).** El porte de los carriles V10 cerró buena parte de esta lista:
> los ítems **4** (parcialmente: sólo queda `_check_agents` sin test propio), **5** (`GET
> /health/components` ya tiene test HTTP), **6** (el `refetchInterval` de 10 s ya tiene test con fake
> timers), **7** (el `ORDER BY created_at DESC` de alertas ya está asertado), **13** (los tests de
> `reload_watch_paths` ya invocan el método real, `0051e45`) y **16** (el timeout de 30 s del drenaje
> ya tiene test contra la firma viva) están **cerrados**. Los ítems 1, 2 y 3 quedaron cubiertos por
> los tests de componente de `Events`, `EventDetail`, `Login` y `Rules`. Quedaban abiertos, y eran
> exactamente los que sostenían las seis historias `parcial`: la confirmación visual del rescan
> (US-22), el `audit_log` de login/logout (US-27), los valores de `last_error`/`retry_count`/
> `failed_at` en la respuesta HTTP (US-29) y las tres divergencias del ítem 22 (US-07, US-11, US-21).
>
> **Cerrados el 2026-09-17 (commit `2d07cb2`, `backlog-full-stories-completion`, Change 57).** Los
> cuatro puntos que quedaban abiertos se cerraron: US-22, US-27 y US-29 con el test que faltaba cada
> una (grupo 6), y las tres divergencias del ítem 22 — US-07 y US-21 por cambio de código, US-11 con
> D71/RN-165. No queda ninguna brecha abierta de las que sostenían una historia `parcial`.

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
    correspondiente.

    **Actualizado el 2026-09-16.** Varias de las divergencias que listaba este ítem quedaron
    resueltas: `cc73c2d` corrigió el texto canónico de la ruta `/change-password` (US-01/US-27), de
    la tabla `failed_notifications` y del umbral `retry_count >= 3` (US-05/US-29), y de la ruta
    `/alerts/failed`; D66/RN-160 cerró el `ruleset_version` de los comandos de acción correctiva
    (US-12); el `event_ack` de `rule_sync` dejó de ser divergencia porque se implementó (US-18); y la
    afirmación de que la cookie de refresh divergía era **falsa** (US-01: el código siempre emitió
    `samesite="strict"` y `path="/auth/refresh"`).

    **Cerrado el 2026-09-17 (commit `2d07cb2`, `backlog-full-stories-completion`, Change 57).** Las
    tres divergencias que quedaban abiertas se cerraron; no queda ninguna vigente:

    - **US-07** — cerrada por cambio de código: `ALL_STATUSES` (`frontend/src/pages/Events.tsx`)
      enumera hoy los 7 estados, con `superseded` siempre visible y coherente con
      `include_superseded`. No es un ajuste de criterio: el texto no cambió, el selector se adaptó a
      él.
    - **US-11** — cerrada por decisión: D71/RN-165 (2026-09-17) ratifica D2 y alinea el criterio 4 al
      comportamiento vigente desde `8d37075` (`event.hash_detected`, no el hash actual del
      filesystem). Es un ajuste de criterio declarado — ver
      `docs/cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados`.
    - **US-21** — cerrada por cambio de código: el agente publica `queue_pressure_high` (booleano,
      D72/RN-166), calculado de una sola lectura de `queue_pressure`, que se conserva sin cambios. No
      es un ajuste de criterio: el texto de W3 no cambió, el agente se adaptó a él.

    Las siete historias con al menos un ajuste de criterio declarado (US-01, US-05, US-11, US-12,
    US-23, US-27, US-29) están en la tabla dedicada de
    [`docs/cierre/MATRIZ_TRAZABILIDAD.md`](cierre/MATRIZ_TRAZABILIDAD.md#ajustes-de-criterio-declarados),
    con texto original, texto vigente, decisión, fecha y commit por fila.

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
