# LANE L5 — Criterios de aceptación (US-21, US-22, US-30)

Fuente canónica: `docs/historias_de_usuario.md`. Base: v10-base (7df4935 + privacy hardening, 6790e40).

## US-21 — Visualización del estado de agentes (historias_de_usuario.md:392-406)

| # | Criterio (verbatim) | Archivo:línea | Test | Estado |
|---|---|---|---|---|
| 1 | Se muestra una lista de agentes registrados. | `backend/app/modules/agents/router.py:123-130`, `frontend/src/pages/Agents.tsx` | pre-existente | PASS (pre-existente) |
| 2 | Cada agente muestra: identificador, estado, última actividad, `ruleset_version` aplicado, `queue_size` local. | `backend/app/modules/agents/models.py` (`Agent.queue_size`, `AgentResponse.queue_size`), `backend/db/migrations/015_add_agent_queue_size.sql`, `frontend/src/components/ui/AgentCard.tsx:150-152` | `backend/tests/test_heartbeat_consumer.py::test_queue_size_persisted`, `::test_queue_size_never_reported_reads_as_null`; `backend/tests/test_agent_mgmt.py::test_get_agent_detail_exposes_queue_size`; `frontend/src/components/ui/AgentCard.test.tsx` (describe "queue_size local (US-21)") | PASS |
| 3 | Se destacan visualmente los agentes no-ok. | `frontend/src/components/ui/AgentCard.tsx` `STATUS_STYLES` | pre-existente | PASS (pre-existente) |
| 4a | offline a los 30s / dead a los 5min | `backend/app/modules/agents/heartbeat_consumer.py::_sweep_offline` | pre-existente (`test_heartbeat_consumer.py::test_sweep_marks_offline_after_30s`, etc.) | PASS (pre-existente) |
| 4b | dead → dispara webhook n8n | `backend/app/modules/agents/heartbeat_consumer.py::_notify_agent_dead`, `_sweep_offline` (retorna `newly_dead`), `backend/app/modules/alerts/contract.py::NOTIFICATION_TYPE_AGENT_DEAD` | `test_heartbeat_consumer.py::test_sweep_offline_returns_newly_dead_agent_ids`, `::test_sweep_offline_does_not_report_agent_already_dead`, `::test_notify_agent_dead_skips_without_webhook_url`, `::test_notify_agent_dead_sends_n8n_payload` | PASS |
| 4c | heartbeat con `shutdown:true` → `draining` | pre-existente | pre-existente | PASS (pre-existente) |
| 5 | `queue_pressure` > 80% → banner de alerta específico del agente (W3) | `frontend/src/components/ui/AgentCard.tsx` (`showQueuePressureBanner`, `role="alert"`) | `AgentCard.test.tsx` (describe "banner de presión de cola alta (US-21/W3)") | PASS |

**US-21: 8/8 sub-criterios demostrados** (3 pre-existentes de la baseline, 5 nuevos de este lane).

## US-22 — Disparo de re-scan de baseline (historias_de_usuario.md:410-426)

| # | Criterio (verbatim) | Archivo:línea | Test | Estado |
|---|---|---|---|---|
| 1 | Botón para disparar el re-scan, con opción de seleccionar paths específicos. | `frontend/src/components/ui/AgentCard.tsx` (checkboxes "Paths a re-escanear") | `AgentCard.test.tsx` (describe "selección de paths para rescan (US-22)") | PASS |
| 2 | Diálogo de confirmación listando los eventos `pending` que serán `superseded` para los paths seleccionados. | `frontend/src/components/ui/RescanConfirmModal.tsx` (lista de paths), `backend/app/modules/agents/service.py::rescan_agent` (conteo acotado por path) | `frontend/src/components/ui/RescanConfirmModal.test.tsx`; `backend/tests/test_agent_mgmt.py::test_rescan_with_paths_scopes_pending_count` | PASS |
| 3 | Admin debe confirmar explícitamente. | `frontend/src/pages/Agents.tsx` (`RescanConfirmModal` + `handleForceRescan`) | pre-existente, extendido | PASS |
| 4 | Al confirmar: `pending`→`superseded` para esos paths; comando `rescan_baseline` firmado HMAC + `ruleset_version++` (C11). | `backend/app/modules/agents/service.py::rescan_agent`, `backend/app/modules/agents/streams.py::enqueue_rescan_baseline` | `test_rescan_with_paths_supersedes_only_selected_paths`, `test_rescan_increments_ruleset_version`, `test_rescan_with_paths_publishes_paths_in_command`, `test_rescan_without_paths_publishes_empty_list` | PASS |
| 5 | Agente verifica firma HMAC y versión antes de ejecutar. | `agent/commands.py::dispatch` (HMAC, pre-existente), `agent/commands.py::handle_rescan_baseline` (guard de versión, nuevo) | `agent/tests/test_agent_config.py::test_rescan_baseline_handler_ignores_stale_version` | PASS |
| 6 | Agente regenera baseline completo para los paths indicados, re-cifrado AES-256-GCM (W10). | `agent/commands.py::handle_rescan_baseline` (`scan_paths` acotado + `_path_is_within_watch_paths`); cifrado AES-GCM pre-existente en `agent/baseline.py` (no tocado) | `test_rescan_baseline_handler_scans_only_specified_paths`, `test_rescan_baseline_handler_rejects_paths_outside_watch_roots`, `test_rescan_baseline_handler_calls_run_scan` (regresión: sin paths = todos) | PASS |
| 7 | Agente confirma mediante `event_ack` (C3). | `agent/commands.py::handle_rescan_baseline` (`_publish_ack`, pre-existente); `backend/app/modules/agents/command_ack_consumer.py` (`rescan_baseline` agregado a `_RECONCILE_ROOT_VERSION_TYPES`) | `test_rescan_baseline_handler_publishes_ack` (pre-existente); `backend/tests/test_command_ack_consumer.py::test_ack_ok_rescan_baseline_advances_ruleset_version_applied` | PASS |
| 8 | Se muestra confirmación de que la solicitud fue enviada. | `frontend/src/pages/Agents.tsx` (`toast.success`) | pre-existente | PASS (pre-existente) |
| 9 | La operación se registra en `audit_log` (W18). | `backend/app/modules/agents/service.py::rescan_agent` (incluye `paths` en el detail) | `test_audit_log_on_rescan_includes_paths` | PASS |
| 10 | Si el agente está `draining`, botón deshabilitado con tooltip (ver US-30). | `frontend/src/components/ui/AgentCard.tsx` (`DRAINING_TOOLTIP` en botón Rescan) | `AgentCard.test.tsx::"el botón de rescan tiene el tooltip canónico exacto durante el drenaje"` | PASS |

**US-22: 10/10 sub-criterios demostrados** (3 pre-existentes extendidos, 7 nuevos de este lane).

## US-30 — Indicador de agente en shutdown graceful (historias_de_usuario.md:567-578, W17)

| # | Criterio (verbatim) | Archivo:línea | Test | Estado |
|---|---|---|---|---|
| 1a | SIGTERM → deja de aceptar nuevos eventos de fanotify | `agent/detector.py::set_draining`, `_try_enqueue` (gate); `agent/__main__.py::_shutdown` (llama `detector.set_draining(True)`) | `agent/tests/test_detector_draining.py` (4 tests); `agent/tests/test_shutdown_heartbeat.py` (2 tests de wiring del shutdown handler) | PASS |
| 1b | drena la cola local publicando al stream (timeout 30 s) | `agent/__main__.py::_drain_then_stop` (pre-existente, `timeout: float = 30.0`) | `agent/tests/test_drain_then_stop.py` (4 tests, incluye `test_drain_then_stop_default_timeout_is_30_seconds` contra la firma real) | PASS |
| 1c | emite heartbeats con flag `shutdown: true` | `agent/heartbeat.py` (pre-existente) | `agent/tests/test_shutdown_heartbeat.py::test_shutdown_flag_set_on_sigterm` (pre-existente) | PASS (pre-existente) |
| 2 | Backend marca a ese agente `draining` mientras el flag esté activo. | `backend/app/modules/agents/heartbeat_consumer.py` (pre-existente) | `backend/tests/test_heartbeat_consumer.py::test_heartbeat_shutdown_marks_draining` (pre-existente) | PASS (pre-existente) |
| 3 | Indicador visual distintivo (ícono + texto "Drenando N eventos"). | `frontend/src/components/ui/AgentCard.tsx` (bloque `isDraining`, ⏳ + "Drenando {queue_size} eventos") | `AgentCard.test.tsx` (describe "indicador de drenaje graceful (US-30)") | PASS |
| 4 | Botones de re-scan/update config deshabilitados con tooltip exacto "No disponible durante shutdown graceful". | `frontend/src/components/ui/AgentCard.tsx` (`DRAINING_TOOLTIP` constante, aplicada a "Editar" y "Rescan") | `AgentCard.test.tsx` (2 tests de tooltip exacto) | PASS |
| 5 | Tras drenar: `offline` (si vuelve pronto) o `dead` (>5 min sin heartbeat). | `backend/app/modules/agents/heartbeat_consumer.py::_sweep_offline` (pre-existente) | `test_sweep_marks_draining_agent_offline_after_30s`, sweep a `dead` (pre-existentes) | PASS (pre-existente) |

**US-30: 7/7 sub-criterios demostrados** (3 pre-existentes, 4 nuevos de este lane).

## Resumen

- US-21: 8/8 · US-22: 10/10 · US-30: 7/7 — **ningún criterio BLOCKED-BY-DECISION.**
- No se encontró conflicto entre los criterios canónicos y los appendices de decisión de `reglas_de_negocio.md`/`arquitectura_stack.md` (ver `mem_search` / investigación previa: W16/RN-92, W17/RN-93, W3/RN-84, C11/RN-75 confirman, no descartan, estos criterios).
- Divergencia de nomenclatura preexistente (no introducida por este lane): el texto canónico de US-21 describe `queue_pressure` como flag booleano ("`queue_pressure: true`"); el sistema (agente + backend + frontend, desde antes de este lane) lo modela como float 0.0–1.0 con umbral de 80%. Mismo criterio semántico, distinta representación de wire — no se tocó por estar fuera del alcance de esta lane y no divergir del comportamiento observable pedido (banner cuando la cola supera 80%).

## Verificación final (suites completas)

| Suite | Resultado | Baseline | Nuevos |
|---|---|---|---|
| Backend (`backend/tests`, Postgres 18.3 + Valkey 9.0.3 dedicados, contenedor recién creado) | **618 passed, 0 failed, 0 errors** (67.64s) — `.v10-evidence/l5/green/backend_full_final_GREEN.log`, `junit/backend_full_final.xml` | 602 | +16 |
| Agent (`agent/tests`) | **527 passed, 1 skipped** (20.08s) — `green/agent_full_final_GREEN.log`, `junit/agent_full_final.xml` | 513 + 1 skipped | +14 |
| Frontend (`pnpm exec vitest run`) | **141 passed** — `green/frontend_full_final_GREEN.log` | 128 | +13 |
| Frontend typecheck (`tsc --noEmit`) | limpio | — | — |
| Frontend build (`vite build`) | limpio, 205 módulos | — | — |
| `python3 scripts/check_spec_integrity.py` | `OK — 44 main specs, 249 requisitos, sin problemas` | — | — |

**Nota sobre flakiness observada durante la verificación**: los primeros 4-5 intentos de correr la suite backend completa contra el contenedor `fim-l5-db` mostraron fallas no determinísticas (10-70 tests distintos cada vez, nunca los mismos, nunca en archivos tocados por esta lane) con `psycopg.errors.UniqueViolation`/`DeadlockDetected` sobre el admin sembrado por el fixture `_db_isolation` (`backend/tests/conftest.py`). Diagnóstico: `docker stats`/`uptime` mostraban carga de host 6-13 con 6-8 contenedores `fim-l*` de otras lanes corriendo en paralelo, y el log de Postgres mostró un checkpoint con `write=119s, sync=16s` — evidencia de contención de I/O de disco compartido, no un bug de este lane (confirmado: el mismo patrón de error aparecía en archivos de test sin ninguna relación con agentes, e incluso en un archivo no tocado por este lane corriendo completamente solo). Recrear el contenedor desde cero (`docker rm -f` + `docker run`) y correr una única vez produjo el resultado limpio de la tabla de arriba, que es la evidencia de referencia.
