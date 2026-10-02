# Lane L1 — US-14, US-15, US-18 — criterios de aceptación

Base: `v10-base` (7df4935 + privacy hardening) en `lane/l1-rules`.
Criterios citados verbatim de `docs/historias_de_usuario.md`. Fuente de verdad
de mapeo previo: `backlog_map.md` (secciones US-14/US-15/US-18), re-verificado
contra el código y los appendices de decisiones antes de implementar.

## US-14 — Listado de reglas de monitoreo

| # | Criterio (verbatim) | Implementación | Test | Resultado |
|---|---|---|---|---|
| 1 | "Se muestra una tabla con las reglas existentes." | Ya implementado — `frontend/src/pages/Rules.tsx:159-232` | `backend/tests/test_rules_service.py::TestListRules`, `backend/tests/test_rules_router.py` | PASS (preexistente) |
| 2 | "Cada fila muestra: patrón (`pattern`), severidad, acción configurada." | Ya implementado — `frontend/src/pages/Rules.tsx:173-181` | `frontend/src/pages/Rules.test.tsx::"Rules — US-14 listado" > "criterio 2..."` (nuevo) | PASS |
| 3 | "Se indica que la acción por defecto (sin regla que matchee) es `alert_only`." | Nuevo — leyenda estática `frontend/src/pages/Rules.tsx:136-140` | `frontend/src/pages/Rules.test.tsx::"criterio 3..."` (nuevo) | PASS |
| 4 | "Se muestra el `ruleset_version` actual del sistema para referencia de ordering (C11)." | Nuevo — endpoint `GET /rules/version` (`backend/app/modules/rules/router.py:99-108`, `RulesetVersionOut`), `get_ruleset_version()` (`backend/app/modules/rules/service.py:115-121`); frontend `getRulesetVersion()` (`frontend/src/api/rules.ts:38-41`), `useRulesetVersion()` (`frontend/src/hooks/useRules.ts:14-19`), display (`frontend/src/pages/Rules.tsx:120-125`) | `backend/tests/test_rules_service.py::TestGetRulesetVersion`, `backend/tests/test_rules_router.py::test_get_rules_version_returns_current_counter`, `test_get_rules_version_no_auth_returns_401`, `frontend/src/pages/Rules.test.tsx::"criterio 4..."` (todos nuevos) | PASS |

## US-15 — Creación de una regla de monitoreo

| # | Criterio (verbatim) | Implementación | Test | Resultado |
|---|---|---|---|---|
| 1 | "Existe un formulario para crear una regla con los campos: patrón (pattern con soporte de glob y negación `!`), severidad (...), acción (...)." | Ya implementado — `frontend/src/components/ui/RuleForm.tsx` (campo pattern es texto libre, acepta `!`) | `frontend/src/pages/Rules.test.tsx::"Rules — US-15 creación" > "criterio 1..."` (nuevo, cubre creación end-to-end con patrón negado) | PASS |
| 2 | "El patrón soporta glob estándar (`/etc/**`) y negación con prefijo `!` (`!/etc/motd`)." | `validate_pattern` ya aceptaba `!` sin cambios (fnmatch.translate no falla con `!` como literal) | `backend/tests/test_rules_service.py::TestValidatePattern::test_valid_negated_pattern`, `test_valid_negated_pattern_with_glob` (nuevos) | PASS |
| 3 | "Al evaluar, las reglas con prefijo `!` excluyen paths del match de reglas más amplias. Si un path matchea tanto una regla inclusiva como una exclusiva, la exclusiva gana." | Nuevo — `determine_severity_for_path` (`backend/app/modules/rules/service.py:59-90`): primera pasada descarta paths que matchean una regla exclusiva (retorna `low`, RN-65), segunda pasada evalúa sólo inclusivas | `backend/tests/test_rules_service.py::TestSeverityNegation::test_determine_severity_exclusive_pattern_wins_over_inclusive`, `test_determine_severity_exclusive_does_not_affect_other_paths` (nuevos) | PASS |
| 4 | "Al guardar, la regla se persiste en la base de datos." | Ya implementado | Cubierto indirectamente (preexistente) | PASS (preexistente) |
| 5 | "Se valida que el patrón no esté duplicado." | Nuevo — `create_rule` (`backend/app/modules/rules/service.py:311-316`) chequea `select(Rule).where(Rule.pattern == pattern)` antes de insertar, `ValueError` → 422 (router ya mapea) | `backend/tests/test_rules_service.py::TestWriteOperations::test_create_rule_duplicate_pattern_raises`, `backend/tests/test_rules_router.py::test_post_rules_duplicate_pattern_returns_422` (nuevos) | PASS |
| 6 | "Tras la creación, el backend incrementa `ruleset_version` (C11) y dispara sincronización automática al agente (US-18)." | Ya implementado | `test_rules_service.py::TestWriteOperations::test_create_rule_increments_counter` (preexistente) | PASS (preexistente) |
| 7 | "La operación se registra en `audit_log` (W18)." | Ya implementado | `test_rules_service.py::TestWriteOperations::test_create_rule_writes_audit_log` (preexistente) | PASS (preexistente) |

**Regresión obligatoria** (`determine_severity_for_path` es compartida con severidad/alertas, D34/RN-128):
`backend/tests/test_event_severity.py` (9 tests) y `backend/tests/test_notifications.py` (39 tests) — 48/48 PASS, ver `GREEN-us15-regression-severity-notifications.log`.

## US-18 — Sincronización automática de reglas al agente

| # | Criterio (verbatim) | Implementación | Test | Resultado |
|---|---|---|---|---|
| 1 | "Tras cualquier operación CRUD sobre reglas, el backend publica el set actualizado en el stream `commands`... con tipo `rule_sync`." | Ya implementado (create/update/delete llaman `enqueue_rule_sync`) | `test_rule_sync_outbox.py` (create, preexistente) + nuevos `test_rules_service.py::TestWriteOperations::test_update_rule_enqueues_rule_sync_command`, `test_delete_rule_enqueues_rule_sync_command` | PASS |
| 2 | "Cada comando incluye `signature` HMAC-SHA256 (C7) y `ruleset_version` monotónico (C11)." | Ya implementado | `TestPublishRuleSync::test_signature_is_verifiable` (preexistente) | PASS (preexistente) |
| 3 | "El agente verifica firma HMAC; rechaza con error si es inválida." | Ya implementado — gate único `agent/publisher.py::_verify_and_parse` | `agent/tests/test_reconnect_order.py` (preexistente) | PASS (preexistente) |
| 4 | "El agente verifica que `ruleset_version` sea mayor o igual al último aplicado; descarta mensajes con versión menor." | Ya implementado — `agent/rules.py::RulesCache.update` | `agent/tests/test_stability_fixes.py::test_rule_sync_idempotent_same_version`, `test_rule_sync_rejects_older_version` (preexistente) | PASS (preexistente) |
| 5 | "El agente reemplaza su caché local de reglas con las recibidas sin reiniciar el proceso." | Ya implementado (swap de caché); nuevo test de integración real publisher→RulesCache | `agent/tests/test_rules.py::test_rules_update_applies_newer_version` (preexistente) + nuevo `agent/tests/test_publisher_dispatch_integration.py::test_rule_sync_dispatched_via_publisher_updates_real_rules_cache` | PASS |
| 6 | "El agente persiste el nuevo `ruleset_version` aplicado en `/var/lib/fim-agent/state.json`." | Ya implementado — `agent/rules.py::RulesCache._persist` | `agent/tests/test_rules.py::test_save_state_preserves_rules` (preexistente); verificado de punta a punta en el nuevo test de integración (`persisted["ruleset_version"] == 9`) | PASS |
| 7 | "Si el agente está desconectado, al reconectar procesa primero los comandos pendientes del stream antes de enviar los eventos encolados (W4)." | Ya implementado | `agent/tests/test_reconnect_order.py:114-146` (preexistente) | PASS (preexistente) |
| 8 | "El agente confirma aplicación mediante `event_ack` (C3)." | **Gap real cerrado** (no una decisión revertida — ver nota abajo). Backend: `enqueue_rule_sync` genera `command_id`, lo firma en el payload y setea `PublishedCommand(command_id=..., ack_status="pending")` (`backend/app/modules/rules/service.py:154-193`). Agente: `agent/__main__.py::_on_rule_sync` (líneas 325-329) retorna el bool de `rules_cache.update(...)`; `agent/publisher.py::_handle_command_async` rama `rule_sync` (líneas 547-573) publica `commands._publish_ack(...)` con ese resultado | `backend/tests/test_published_command_ack_tracking.py::test_rule_sync_persists_with_command_id_and_pending_ack_status` (invertido, antes assertaba `ack_status is None`); `agent/tests/test_publisher_dispatch_integration.py::test_rule_sync_dispatches_event_ack` (nuevo) | PASS |

### Nota de verificación — US-18 criterio 8 (no bloqueado por decisión)

Antes de implementar se verificó si algún appendix de decisiones revertía RN-58. Hallazgo:
- `docs/reglas_de_negocio.md:436-439` (RN-58, regla base, nunca superseded): "...confirma vía `event_ack`".
- `docs/arquitectura_stack.md:2152`: tabla de comandos, fila "Rule sync → Async vía `rule_sync` + `event_ack`".
- El appendix `D30/RN-124` (`docs/reglas_de_negocio.md:1077-1090`) lista 5 comandos (`baseline_update`, `restore_file`, `quarantine_file`, `update_config`, `rescan_baseline`) que migran al tracking `PublishedCommand.ack_status` — **no menciona `rule_sync` porque ese comando ya usaba el mismo outbox desde antes (H6/C12)**, no porque lo excluya del ack. `backend/app/modules/rules/models.py` (`D37/RN-131`, docstring) confirma que `rule_sync` comparte el mismo outbox transaccional desde antes de D30.
- La única fuente de la exclusión era un comentario de código (`PublishedCommand.__doc__`, pre-existente) que documentaba el estado *actual* del código, no una decisión de negocio en ninguno de los dos docs canónicos — y contradecía RN-58/arquitectura_stack.md:2152 sin ningún appendix que lo respalde. Se corrigió el comentario junto con el código (ver `models.py`, `command_ack_consumer.py`).
- Conclusión: **no hay conflicto con ningún appendix de decisiones** — es el mismo gap de implementación que ya había identificado la verificación previa (`backlog_map.md` §"Conflictos resueltos" #2). Implementado sin reservas.

## Regresión completa (evidencia en este directorio)

| Suite | Baseline v10-base | Resultado esta lane | Log |
|---|---|---|---|
| Backend (`pytest backend/tests`) | 602 passed | **614 passed** (+12 tests nuevos, 0 fallos, 0 regresiones) | `GREEN-backend-full-suite-final.log`, `backend-full-junit-final.xml` |
| Agente (`pytest agent/tests`) | 513 passed + 1 skipped | **515 passed + 1 skipped** (+2 tests nuevos) | `GREEN-agent-full-suite-2.log`, `agent-full-junit.xml` |
| Frontend (`vitest run`) | 128 passed | **132 passed** (+4 tests nuevos) | `GREEN-frontend-full-suite-junit.log`, `frontend-junit.xml` |
| Frontend typecheck | — | OK | `typecheck.log` |
| Frontend build | — | OK | `build.log` |
| `check_spec_integrity.py` | — | OK — 44 main specs, 249 requisitos | `spec_integrity.log` |

Ningún criterio quedó BLOCKED-BY-DECISION. No se requirió migración de base de datos
(el modelo `PublishedCommand.command_id`/`ack_status` ya existía; sólo se empezaron a
poblar para `rule_sync`).
