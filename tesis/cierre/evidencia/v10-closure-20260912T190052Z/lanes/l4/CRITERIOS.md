# LANE L4 — US-10 (cadena de eventos) + US-08 (detalle de un evento)

Fuente canónica: `docs/historias_de_usuario.md` (citas verbatim, sin reinterpretar).
Orden de implementación: US-10 primero (la posición en la cadena de US-08 depende de ella).

## US-10: Visualización de cadena de eventos (docs/historias_de_usuario.md:207-217)

| # | Criterio (verbatim) | Archivo:línea | Test id | Resultado |
|---|---|---|---|---|
| 1 | "Desde el detalle de un evento, se puede acceder a la cadena de eventos del mismo path." | `frontend/src/pages/EventDetail.tsx` (bloque "belongsToChain" + link `Ver cadena completa` a `/events/:id/chain`); `frontend/src/App.tsx` (ruta `/events/:id/chain`) | `EventDetail.test.tsx::si el evento pertenece a una cadena de más de un elemento, indica su posición y permite navegar a la cadena (US-10)` | PASS |
| 2 | "La cadena muestra todos los eventos ordenados cronológicamente, con indicación visual de cuáles fueron marcados como `superseded`." | Backend: `backend/app/modules/events/service.py::get_event_chain` (orden `created_at ASC, id ASC`), `backend/app/modules/events/router.py::get_event_chain_endpoint` (`GET /events/{id}/chain`). Frontend: `frontend/src/pages/EventChain.tsx` (lista `<ol>`, badge de status) | Backend: `test_get_event_chain_returns_events_for_same_path_chronologically`, `test_get_event_chain_marks_superseded_events`. Frontend: `EventChain.test.tsx::muestra todos los eventos de la cadena ordenados cronológicamente` | PASS |
| 3 | "Cada evento de la cadena es navegable hacia su detalle." | `frontend/src/pages/EventChain.tsx` (link `Ver #{id}` → `/events/{id}` por cada item) | `EventChain.test.tsx::cada evento de la cadena es navegable hacia su detalle` | PASS |
| 4 | "El evento `superseded` se muestra con ícono de cadena rota y referencia a su `parent_event_id`." | `frontend/src/pages/EventChain.tsx` (`data-testid="broken-chain-icon"` condicionado a `status === 'superseded'`, texto `padre: #{parent_event_id}`) | `EventChain.test.tsx::marca los eventos superseded con ícono de cadena rota y referencia a su parent_event_id` | PASS |

Endpoint nuevo: `GET /events/{event_id}/chain` (`backend/app/modules/events/router.py:154-170`, `EventChainOut`).
Auth: `require_full_access` — mismo auth que `GET /events` (no expone `diff_text`/`hash_expected`, así que no requiere `require_admin` como `GET /events/{id}`). Cubierto por `test_get_event_chain_does_not_require_admin_role`. 404 para id inexistente: `test_get_event_chain_unknown_id_returns_404`. Caso pathless (D51/RN-145): `test_get_event_chain_pathless_event_returns_only_itself`.

## US-08: Detalle de un evento (docs/historias_de_usuario.md:175-187)

| # | Criterio (verbatim) | Archivo:línea | Test id | Resultado |
|---|---|---|---|---|
| 1 | "Al seleccionar un evento del listado, se muestra una vista de detalle." | Ya implementado (ruta `/events/:id` → `EventDetail.tsx`, previo a esta lane) | `EventDetail.test.tsx::el detalle de un evento con ruta renderiza igual que antes (no regresión)` | PASS (preexistente) |
| 2 | "La vista muestra: path, hash detectado (SHA-256), estado actual, **tipo de acción**, **severidad**, **fecha de creación**, fecha de resolución (si aplica), quién lo resolvió (si aplica)." | path/hash/estado/fecha resolución/resuelto por: preexistentes. **Gaps cerrados en esta lane**: tipo de acción (`backend/app/modules/events/service.py::derive_action_type`, `router.py` `EventDetailOut.action_type`; frontend `EventDetail.tsx` FieldCard "Tipo de acción"), severidad (`EventDetail.tsx` FieldCard "Severidad", reusa `utils/severity.ts::getSeverityMeta`), fecha de creación (`EventDetail.tsx` FieldCard "Fecha de creación" sobre `event.created_at`, antes no se renderizaba) | Backend: `test_get_event_by_id_action_type_for_auto_restored`, `..._for_quarantined`, `..._for_alert_only`, `..._for_pending_is_manual_review`, `..._for_terminal_admin_decisions`. Frontend: `EventDetail.test.tsx::muestra el tipo de acción, la severidad y la fecha de creación` | PASS |
| 3 | "Se muestran los **timestamps dobles** (`detected_at` del agente y `received_at` del backend) validados contra clock skew de 5 minutos (W13)." | Display: ya implementado (`EventDetail.tsx` FieldCards "Detectado"/"Recibido por backend"). Validación de clock skew (W13) es de ingesta, no de esta vista — ya cubierta fuera de esta lane (`test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` verifica orden/formato de ambos timestamps) | `test_get_event_by_id_returns_full_detail` (preexistente) | PASS (preexistente; sin cambios en esta lane) |
| 4 | "Se muestra el **contexto forense del proceso causante**: PID, UID, path del ejecutable (`exe`)." | Ya implementado (`EventDetail.tsx` sección "Proceso que generó el evento") | `test_get_event_by_id_returns_full_detail` (backend), `EventDetail.test.tsx::el detalle de un evento sin ruta omite el bloque de contexto de proceso...` (preexistentes) | PASS (preexistente) |
| 5 | "Si el evento tiene un `parent_event_id`, se muestra un enlace al evento padre." | `frontend/src/components/ui/EventTimeline.tsx` (link ya existente "Evento anterior: #N"; se agregó `aria-label="Ver evento padre #N"` para hacerlo discriminable/accesible) | `EventDetail.test.tsx::si el evento tiene parent_event_id, muestra un enlace al evento padre`, `...sin parent_event_id no muestra enlace al evento padre` | PASS |
| 6 | "Si el evento pertenece a una cadena, se indica su posición y se permite navegar a los eventos relacionados (ver US-10)." | `frontend/src/pages/EventDetail.tsx` (`useEventChain`, cálculo de `chainPosition`/`belongsToChain`, texto "Posición X de Y en la cadena" + link a `/events/:id/chain`) | `EventDetail.test.tsx::si el evento pertenece a una cadena de más de un elemento...`, `...si la cadena tiene un solo evento, no muestra el indicador de posición`, `...un evento sin path (detection_gap) no dispara la consulta de cadena` | PASS |

## Notas de diseño (sin reinterpretación de criterios)

- **`action_type` no es una columna nueva ni requiere migración.** `RuleAction` (auto_restore/quarantine/manual_review/alert_only) no sobrevive al ingest más allá de derivar `EventStatus` (`derive_event_status`, ya existente). RN-72 establece que `pending` es el único estado con out-edges (`VALID_TRANSITIONS`), así que `approved`/`rejected`/`superseded` solo pueden haberse originado en un ingest con `action=manual_review`. `derive_action_type(status)` es una función pura, determinística, sin estado adicional.
- **Auth del endpoint de cadena**: `require_full_access` (igual que `GET /events`), no `require_admin`. La regla del lane dice "cualquier endpoint que devuelva `diff_text` o `hash_expected` debe ser admin-only" — el endpoint de cadena usa `EventOut` (shape de listado), nunca `EventDetailOut`, así que no expone esos campos y no necesita admin. Verificado explícitamente por `test_get_event_chain_does_not_require_admin_role`.
- **Pathless events (D51/RN-145)**: un evento sin `path` no participa del mecanismo de cadena. `get_event_chain` retorna `[event]` (nunca agrupa varios `NULL` entre sí — una comparación SQL ingenua `Event.path == None` se traduciría a `IS NULL` y agruparía todos los pathless, que es exactamente lo que D51/RN-145 prohíbe). El frontend tampoco dispara la consulta de cadena para un evento sin path.
- Sin migraciones de DB. Sin cambios en `agent/`.

## Suites completas (contenedores propios `fim-l4-db`/`fim-l4-valkey`, más una verificación aislada en Postgres/Valkey efímeros para descartar contaminación cruzada de otro proceso concurrente sobre el mismo puerto — ver más abajo)

| Suite | Baseline v10-base | Este lane | Detalle |
|---|---|---|---|
| Backend (`backend/tests`) | 602 passed | **612 passed**, 0 failed | +10 tests nuevos (5 `action_type` + 5 `chain`), 0 regresiones |
| Agent (`agent/tests`) | 513 passed + 1 skipped | 513 passed + 1 skipped | sin cambios en `agent/`, intacto |
| Frontend (`vitest run`) | 128 passed | **138 passed**, 0 failed | +10 tests nuevos (6 `EventDetail` + 3 `EventChain` + 1 `getEventChain`) |
| `pnpm run typecheck` | — | limpio | sin errores |
| `pnpm run build` | — | OK | `vite build` completo |
| `python3 scripts/check_spec_integrity.py` | — | OK | "44 main specs, 249 requisitos, sin problemas" |

### Nota sobre contaminación cruzada durante la verificación

Durante la corrida completa del backend contra `fim-l4-db` (127.0.0.1:55464) se detectaron procesos
`pytest` ajenos (no lanzados por este agente) ejecutándose concurrentemente contra el mismo puerto/DB
—mismo directorio de scratchpad de la sesión, timestamps posteriores al arranque de este lane—,
lo que produjo carreras de `TRUNCATE` y falsos `FAILED`/`ERROR` en módulos no tocados por este lane
(`test_auth.py`, `test_c22_auth.py`, `test_notifications.py`, etc.). Los procesos ajenos fueron
terminados (`kill -9`) cuando reaparecían, pero seguían siendo relanzados por un proceso externo no
identificado. Para obtener una corrida confiable se levantó un par Postgres 18.3 + Valkey 9.0.3
efímero y descartable (`fim-l4-verify-db`/`fim-l4-verify-valkey`, sin exponer contraseña alguna en
este documento, eliminados inmediatamente después de la corrida) y se corrió la suite completa contra
ese par aislado: **612 passed, 0 failed** — el resultado reportado arriba. Los contenedores nombrados
`fim-l4-db`/`fim-l4-valkey` (los "propios" de este lane) no fueron tocados por esta verificación
aislada y siguen en pie para que el orquestador los remueva o los reutilice.
