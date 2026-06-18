## 1. Modelo PublishedCommand (D10)

- [x] 1.1 Agregar `class PublishedCommand(SQLModel, table=True)` a `backend/app/modules/rules/models.py` con columnas `id: int | None` (PK), `command_type: str`, `target_agent_id: str | None`, `ruleset_version: int`, `published_at: datetime` (default_factory utcnow)
- [x] 1.2 Verificar que `app.modules` importa el módulo `rules.models` para que `PublishedCommand` quede en `SQLModel.metadata` (revisar `backend/app/modules/__init__.py`); si no, agregar el import

## 2. Service layer (backend/app/modules/rules/service.py)

- [x] 2.1 Crear `service.py` con docstring y constante `SEVERITY_ORDER = {critical:0, high:1, medium:2, low:3}` (RN-09)
- [x] 2.2 Implementar `validate_pattern(pattern: str) -> None` que rechace pattern vacío y use `fnmatch.translate` + `re.compile`; lanzar `ValueError` (mapeado a 422 en router) si inválido (RN-08, RN-58)
- [x] 2.3 Implementar `increment_ruleset_version(session) -> int`: lee la fila única de `RulesetVersion` (crea con version=0 si no existe), incrementa, actualiza `updated_at`, flush, retorna nuevo valor (RN-75, D-C)
- [x] 2.4 Implementar `publish_rule_sync(session, valkey_client, new_version) -> int`: itera `Agent` con `shared_secret_hex` no nulo, construye payload `{type, target_agent_id, ruleset_version, schema_version}`, firma con `sign_payload(bytes.fromhex(secret), payload)`, serializa con `json.dumps(sort_keys=True, separators=(",",":"))`, `xadd(STREAM_COMMANDS, {"data": data})`, inserta un `PublishedCommand` por agente; retorna nº de agentes (D9, D10, RN-79)
- [x] 2.5 Implementar `write_audit(session, user_id, action, rule_id)`: inserta `AuditLog` con `target_type='rule'` (RN-94)
- [x] 2.6 Implementar `create_rule(session, valkey_client, user_id, data) -> Rule`: valida, persiste Rule, increment_ruleset_version, audit (action='rule_created'), commit, luego publish_rule_sync (orden D-F)
- [x] 2.7 Implementar `update_rule(...)`: 404 si no existe, valida, actualiza campos + `updated_at`, increment, audit (rule_updated), commit, publish
- [x] 2.8 Implementar `delete_rule(...)`: 404 si no existe, captura id, elimina, increment, audit (rule_deleted), commit, publish
- [x] 2.9 Implementar `list_rules(session) -> list[Rule]`: SELECT y orden en memoria por `SEVERITY_ORDER[severity]` luego `id` (RN-09)
- [x] 2.10 Implementar `get_rule(session, rule_id) -> Rule | None`

## 3. Router layer (backend/app/modules/rules/router.py)

- [x] 3.1 Crear `router.py` con `APIRouter(prefix="/rules", tags=["rules"])`, modelos Pydantic `RuleCreate`, `RuleUpdate`, `RuleOut` (from_attributes)
- [x] 3.2 `POST /rules` con `Depends(require_admin)` + `Depends(get_session)` + `Depends(get_valkey_client)`; mapea `ValueError` de validación a HTTP 422; retorna 201 con `RuleOut`
- [x] 3.3 `GET /rules` con `Depends(get_current_user)`; retorna lista ordenada de `RuleOut`
- [x] 3.4 `GET /rules/{id}` con `Depends(get_current_user)`; 404 si no existe
- [x] 3.5 `PUT /rules/{id}` con `Depends(require_admin)`; 404 / 422 según corresponda; retorna `RuleOut`
- [x] 3.6 `DELETE /rules/{id}` con `Depends(require_admin)`; 404 si no existe; retorna 204
- [x] 3.7 Extraer `user_id` del `User` inyectado por `require_admin` para los audit logs

## 4. Wiring en main.py

- [x] 4.1 Importar `from app.modules.rules.router import router as rules_router` y registrar con `app.include_router(rules_router)` en `backend/app/main.py`
- [x] 4.2 Confirmar que `PublishedCommand` se incluye en `create_all()` (vía import de `app.modules`); no agregar import redundante si ya está cubierto por 1.2

## 5. Tests

- [x] 5.1 Crear `backend/tests/test_rules_service.py` (patrón skip psycopg + SQLite in-memory, como `test_event_consumer_c11.py`): increment_ruleset_version idempotente y monotónico; validate_pattern acepta globs válidos y rechaza inválidos/vacíos
- [x] 5.2 En `test_rules_service.py`: publish_rule_sync con mock valkey client (`xadd = MagicMock`) hace fan-out de N mensajes con firma verificable por `verify_payload` y `target_agent_id` correcto; inserta N rows en `published_commands`; con 0 agentes no publica ni inserta (D9)
- [x] 5.3 En `test_rules_service.py`: create/update/delete escriben `audit_log` con action correcta y `target_type='rule'`; incrementan el counter; list_rules respeta orden critical→high→medium→low (RN-09)
- [x] 5.4 Crear `backend/tests/test_rules_router.py` (patrón httpx ASGI + `_auth_headers` como `test_event_router.py`): 401 sin token en todos los endpoints; 403 para no-admin en POST/PUT/DELETE; 422 para pattern/severity/action inválidos; 404 en GET/PUT/DELETE de id inexistente
- [x] 5.5 En `test_rules_router.py`: happy path POST crea regla y retorna 201; GET lista ordenada por severity; flujo crear→listar→actualizar→eliminar coherente
- [x] 5.6 Actualizar `backend/tests/test_domain_models.py` si aplica: smoke test de `PublishedCommand` (instancia + columnas)

## 6. Validación final

- [x] 6.1 Correr `pytest backend/tests/test_rules_service.py backend/tests/test_rules_router.py -v` y verificar verde (o skip limpio si no hay psycopg)
- [x] 6.2 Verificar léxico snake_case en payloads y logs (RN-71); sin `Co-Authored-By` en commits
- [x] 6.3 `openspec validate backend-rules-crud` sin errores
