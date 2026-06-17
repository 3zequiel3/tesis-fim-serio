## 1. RulesCache — cache local de reglas con evaluación glob

- [x] 1.1 Crear `agent/rules.py` con dataclass `Rule(pattern: str, action: str | None, negated: bool)` y clase `RulesCache`
- [x] 1.2 Implementar `RulesCache.load(state: dict)` — lee clave `"rules"` de state.json parseado y popula la lista interna
- [x] 1.3 Implementar `RulesCache.evaluate(path: str) -> str` — itera reglas en orden, `!` exclusiva gana, default `"alert_only"` (RN-05, RN-06, RN-65)
- [x] 1.4 Implementar `RulesCache.update(rules_payload: list[dict], ruleset_version: int) -> bool` — reemplaza reglas solo si la versión es mayor (RN-75); retorna True si actualizó
- [x] 1.5 Implementar persistencia: `RulesCache` lee/escribe clave `"rules"` en `state.json` junto al `ruleset_version` existente (escritura atómica `.tmp` + `os.replace()`)

## 2. JournalManager — journal transaccional por event_id

- [x] 2.1 Crear `agent/journal.py` con dataclass `JournalEntry(event_id, path, action, state, created_at, updated_at, error=None)` y clase `JournalManager`
- [x] 2.2 Implementar `JournalManager.write_pending(event_id, path, action) -> JournalEntry` — escribe `{state: "pending"}` en `/var/lib/fim-agent/journal/{event_id}.json` (RN-83)
- [x] 2.3 Implementar `JournalManager.mark_completed(event_id)` — actualiza `state` a `"completed"` y `updated_at`
- [x] 2.4 Implementar `JournalManager.mark_failed(event_id, error: str)` — actualiza `state` a `"failed"`, `error`, y `updated_at`
- [x] 2.5 Implementar `JournalManager.load_pending() -> list[JournalEntry]` — escanea `journal/` y retorna todas las entradas con `state: "pending"`
- [x] 2.6 Implementar `JournalManager.delete(event_id)` — elimina `journal/{event_id}.json` tras completar rehidratación

## 3. DecisionEngine — orquestación evaluación + acción

- [x] 3.1 Crear `agent/decision.py` con clase `DecisionEngine(rules: RulesCache, journal: JournalManager, baseline: BaselineEngine, quarantine_dir: str)`
- [x] 3.2 Implementar `DecisionEngine.evaluate_and_act(change: DetectedChange) -> dict` — evalúa acción, escribe journal pending, ejecuta, actualiza journal, retorna payload enriquecido con `action` y `action_failed`
- [x] 3.3 Implementar acción `_auto_restore(change, entry) -> None` — lee `entry.content_b64`, escribe via `.tmp` + `os.replace()`, verifica SHA-256 vs `entry.hash` (RN-30–33)
- [x] 3.4 Manejar fallo de `_auto_restore` cuando `content_b64 is None` — `mark_failed("no_baseline_content")`, `action_failed: True` en payload
- [x] 3.5 Manejar fallo de `_auto_restore` cuando SHA-256 no coincide — `mark_failed("hash_mismatch_after_restore")`, `action_failed: True` en payload
- [x] 3.6 Implementar acción `_quarantine(change) -> str` — `shutil.move(path, quarantine_path)`, retorna `quarantine_path` (RN-34–37)
- [x] 3.7 Manejar `FileNotFoundError` en `_quarantine` — `mark_failed("file_not_found")`, `action_failed: True` en payload
- [x] 3.8 Para `manual_review` y `alert_only` — solo escribir journal `completed` sin acción física; no modificar el payload con `action_failed`

## 4. Rehidratación de journal en bootstrap

- [x] 4.1 Implementar `DecisionEngine.rehydrate(publisher) -> None` — llama `journal.load_pending()` y procesa cada entrada
- [x] 4.2 Para pendientes `auto_restore`/`quarantine` — reintenta la acción con `evaluate_and_act` reconstruido desde journal entry
- [x] 4.3 Para pendientes `manual_review`/`alert_only` — `mark_failed("rehydrated_without_action")` y re-publica como `alert_only` via publisher
- [x] 4.4 Después de procesar cada entrada, eliminar el archivo de journal con `journal.delete(event_id)` si quedó `completed`

## 5. Integración en detector.py

- [x] 5.1 Modificar `FanotifyDetector._process_event` — en lugar de armar el payload directamente, delegar a `self._decision_engine.evaluate_and_act(detected_change)` y obtener el payload enriquecido
- [x] 5.2 Agregar parámetro `decision_engine: DecisionEngine` al constructor de `FanotifyDetector`
- [x] 5.3 Asegurarse de que el campo `event_type` en el payload siga siendo `"auto_restored"` cuando la acción fue `auto_restore` exitosa (reemplaza `"file_modified"`)

## 6. Integración en __main__.py

- [x] 6.1 Importar `RulesCache`, `JournalManager`, `DecisionEngine` en `agent/__main__.py`
- [x] 6.2 Inicializar `RulesCache` al arrancar (carga rules de `state.json` si existen)
- [x] 6.3 Inicializar `JournalManager` con `journal_dir` de la config
- [x] 6.4 Inicializar `DecisionEngine` con `RulesCache`, `JournalManager`, `BaselineEngine`, `quarantine_dir`
- [x] 6.5 Llamar `decision_engine.rehydrate(publisher)` antes de arrancar el detector (rehidratación en bootstrap)
- [x] 6.6 Agregar callback `on_rule_sync` en publisher: recibe el payload del comando `rule_sync` y llama `rules_cache.update(rules, ruleset_version)`
- [x] 6.7 Registrar el callback via `publisher.register_callbacks(on_ack=..., on_update_config=..., on_rule_sync=...)`
- [x] 6.8 Pasar `decision_engine` al constructor de `FanotifyDetector`

## 7. Modificación en publisher.py — callback on_rule_sync

- [x] 7.1 Agregar atributo `_on_rule_sync_cb: Callable[[list, int], None] | None = None` en `Publisher`
- [x] 7.2 Extender `register_callbacks` para aceptar `on_rule_sync` opcional
- [x] 7.3 En `_handle_command`, agregar rama `elif cmd_type == "rule_sync":` que parsea `payload["rules"]` y `payload["ruleset_version"]` y llama al callback

## 8. Tests — RulesCache

- [x] 8.1 `test_rules_evaluate_inclusive_match` — regla glob inclusiva matchea path → acción correcta
- [x] 8.2 `test_rules_evaluate_exclusive_wins` — regla `!` exclusiva + regla inclusiva → `alert_only`
- [x] 8.3 `test_rules_evaluate_no_match_default` — sin regla que matchee → `alert_only`
- [x] 8.4 `test_rules_update_rejects_older_version` — `update()` con versión menor no actualiza reglas
- [x] 8.5 `test_rules_update_applies_newer_version` — `update()` con versión mayor reemplaza reglas y persiste

## 9. Tests — JournalManager

- [x] 9.1 `test_journal_write_pending` — crea archivo JSON con `state: "pending"` en el dir correcto
- [x] 9.2 `test_journal_mark_completed` — actualiza `state` a `"completed"` y `updated_at`
- [x] 9.3 `test_journal_mark_failed` — actualiza `state` a `"failed"` con campo `error`
- [x] 9.4 `test_journal_load_pending` — retorna solo las entradas con `state: "pending"`
- [x] 9.5 `test_journal_delete` — elimina el archivo correspondiente

## 10. Tests — DecisionEngine acciones

- [x] 10.1 `test_decision_auto_restore_success` — archivo restaurado, hash verificado, journal `completed`, payload con `event_type: "auto_restored"`
- [x] 10.2 `test_decision_auto_restore_no_content` — `content_b64 is None` → journal `failed`, `action_failed: True`
- [x] 10.3 `test_decision_auto_restore_hash_mismatch` — hash post-restore no coincide → journal `failed`, `action_failed: True`
- [x] 10.4 `test_decision_quarantine_success` — archivo movido a quarantine_dir, journal `completed`, `quarantine_path` en payload
- [x] 10.5 `test_decision_quarantine_file_gone` — `FileNotFoundError` → journal `failed`, `action_failed: True`
- [x] 10.6 `test_decision_alert_only` — sin acción física, journal `completed`, payload sin `action_failed`
- [x] 10.7 `test_decision_manual_review` — sin acción física, journal `completed`

## 11. Tests — Rehidratación

- [x] 11.1 `test_rehydrate_auto_restore_pending` — entry pending `auto_restore` → acción reintentada
- [x] 11.2 `test_rehydrate_manual_review_pending` — entry pending `manual_review` → journal `failed`, evento publicado `alert_only`
- [x] 11.3 `test_rehydrate_no_pending` — sin entries pending → ningún evento publicado
