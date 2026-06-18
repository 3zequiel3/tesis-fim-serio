## Context

El modelo `Rule` (pattern, severity, action) y el counter `RulesetVersion` ya existen en `backend/app/modules/rules/models.py` desde C03, pero no hay endpoints ni lógica de sincronización. El agente (C10) ya tiene un `commands_consumer` que filtra por `target_agent_id` y verifica firma HMAC + `ruleset_version` monotónico. C08 dejó el contrato compartido en `backend/app/core/streams.py` (`sign_payload`, `canonical_json`, `STREAM_COMMANDS`, `SCHEMA_VERSION`) y C11 estableció el patrón de publicación: construir el payload dict, firmar con `sign_payload`, serializar con `json.dumps(..., sort_keys=True, separators=(",",":"))` y `xadd(STREAM_COMMANDS, {"data": data})`.

Restricciones clave:
- Backend single-instance (RN-76): el counter `RulesetVersion` global no tiene contención multi-proceso.
- Los endpoints REST son síncronos (usan `Depends(get_session)` con `Session` de SQLModel), pero el cliente Valkey sync (`get_valkey_client`) expone `xadd` síncrono. No hay impedimento para publicar dentro del handler.
- Decisiones cerradas D5, D9, D10 (appendix arquitectura, Abril 2026) gobiernan el fan-out y el registro histórico. No hay suposiciones abiertas.

## Goals / Non-Goals

**Goals:**
- CRUD completo de reglas vía REST con control de acceso (admin para escrituras, autenticado para lecturas).
- Validación robusta de `pattern` (glob `fnmatch`), `severity`, `action`.
- En cada escritura: incrementar el counter global y hacer fan-out de `rule_sync` firmado por agente (D9), registrar en `published_commands` (D10) y en `audit_log` (RN-94), todo en una transacción coherente.
- Orden de severity canónico en `GET /rules` (RN-09: critical=0, high=1, medium=2, low=3).

**Non-Goals:**
- NO implementar el consumo de `rule_sync` en el agente (eso es C10, ya hecho) ni el cálculo de `is_up_to_date` / `ruleset_version_applied` en el endpoint de agents (eso es C14, usa la tabla `published_commands` que este change crea).
- NO implementar reglas dirigidas a un agente específico vía API (el modelo `Rule` actual es global; `target_agent_id` siempre lleva el ID explícito del agente destino en el fan-out, nunca null — D9).
- NO tocar el `commands_consumer` del agente ni el contrato `streams.py`.

## Decisions

### D-A: Fan-out de `rule_sync`, un mensaje firmado por agente (aplica D9)
En cada escritura, `publish_rule_sync(session, valkey_client, new_version)` itera todos los `Agent` con `shared_secret_hex IS NOT NULL` (agentes que completaron bootstrap), construye un payload por agente con `target_agent_id = agent.agent_id`, lo firma con el `shared_secret_hex` de ESE agente, y lo publica en `STREAM_COMMANDS`. Por cada mensaje publicado se inserta una fila en `published_commands`.

Payload del comando (snake_case, RN-71):
```json
{
  "type": "rule_sync",
  "target_agent_id": "<agent_id>",
  "ruleset_version": 47,
  "schema_version": 1,
  "signature": "<HMAC-SHA256 con shared_secret de ese agente>"
}
```

- **Por qué fan-out y no un único mensaje `target_agent_id: null`**: un único mensaje HMAC no puede ser verificado por N agentes con secrets distintos (cada uno generado en bootstrap). El fan-out preserva la garantía RN-79 sin introducir un secret de broadcast compartido. Alternativa descartada: un secret de broadcast global → rompe el modelo de seguridad per-agent y agrega gestión de un secret extra.
- **Por qué NO incluir las reglas en el payload**: D5/RN-58 ya establecen que el agente, al recibir `rule_sync`, hace pull o reemplaza su cache; el contrato actual del agente solo verifica firma + versión. Mantener el payload mínimo (sin las reglas inline) respeta el contrato existente del `commands_consumer` y evita payloads grandes en el stream. Esto se documenta como Open Question si el contrato del agente esperara las reglas inline.

### D-B: `published_commands` registra un row por mensaje físico (aplica D10)
La tabla `published_commands(id, command_type, target_agent_id, ruleset_version, published_at)` registra un row por cada mensaje publicado en el fan-out (N agentes → N rows con el mismo `ruleset_version` y `command_type='rule_sync'`, distinto `target_agent_id`). El check D5 de "agente al día" (`SELECT MAX(ruleset_version) FROM published_commands WHERE target_agent_id = :agent_id OR target_agent_id IS NULL`) funciona naturalmente: cada agente ve el max de los comandos dirigidos a él. Alternativa descartada: un row "lógico" con `target_agent_id=null` → contradice D9 (no hay mensajes broadcast físicos) y rompería el check por-agente.

### D-C: Incremento del counter como upsert de fila única (RN-75)
`RulesetVersion` tiene a lo sumo 1 fila (counter global, RN-76 single-instance). `increment_ruleset_version(session)`: lee la fila única (o la crea con version=0 si no existe), incrementa `version`, actualiza `updated_at`, hace flush y devuelve el nuevo valor. No requiere locking distribuido por ser single-instance. Alternativa descartada: tabla append-only de versiones → innecesaria, `published_commands` ya da el historial.

### D-D: Validación de `pattern` con `fnmatch.translate` (RN-08, RN-58)
El `pattern` es un glob estilo `fnmatch` (soporta `*`, `?`, `[seq]`, y `!` para negación según RN-58/CHANGES.md C12). Se valida intentando `fnmatch.translate(pattern)` y compilando el regex resultante con `re.compile`; si lanza excepción o el pattern está vacío → HTTP 422. `severity` y `action` se validan vía coerción al enum SQLModel (FastAPI/Pydantic lo hace automáticamente en el request body; un valor fuera del enum → 422).

### D-E: Orden de severity canónico en GET /rules (RN-09)
El orden critical→high→medium→low NO es el orden alfabético ni el del enum string. Se implementa con un `CASE`/mapa de orden: `{critical:0, high:1, medium:2, low:3}`, ordenando luego por `id` ascendente como desempate. Dado el volumen pequeño esperado de reglas, se ordena en memoria tras el `SELECT` (consistente con el patrón de `list_events`), o vía `order_by(case(...))` si se prefiere SQL. Se elige el mapa en memoria por simplicidad y portabilidad SQLite/Postgres en tests.

### D-F: Transaccionalidad y orden de operaciones por escritura
Orden dentro del handler (una sola `Session`):
1. Validar input (pattern/severity/action) → 422 si inválido, antes de tocar la DB.
2. Crear/actualizar/eliminar el `Rule` (`session.add`/`session.delete`, `flush`).
3. `increment_ruleset_version(session)` → `new_version`.
4. `audit_log` insert (user_id del `require_admin`, action ∈ {rule_created, rule_updated, rule_deleted}, target_type='rule', target_id=rule.id).
5. `session.commit()` — persiste Rule + RulesetVersion + audit_log atómicamente.
6. `publish_rule_sync(...)` + inserts en `published_commands` **después** del commit del Rule. Trade-off documentado abajo.

## Risks / Trade-offs

- **[Publicar `rule_sync` después del commit del Rule no es atómico con el commit]** → Si el proceso muere entre el commit y el `xadd`, la regla queda persistida pero el agente no recibe el sync hasta la próxima escritura. Mitigación: el counter `RulesetVersion` quedó incrementado y `published_commands` (que se inserta junto al fan-out) sería la fuente de verdad del check D5; ante inconsistencia, una escritura posterior re-sincroniza. Para una tesis single-instance el riesgo es aceptable; se documenta como límite conocido. Alternativa (outbox pattern) se considera over-engineering para el alcance.
- **[Fan-out a 0 agentes]** → Si no hay agentes con `shared_secret_hex`, el counter igual se incrementa pero no se publica ningún mensaje ni se inserta en `published_commands`. Comportamiento correcto: las reglas quedan listas y el primer agente que haga bootstrap recibirá el ruleset al sincronizar. Sin error.
- **[`pattern` con `!` de negación]** → `fnmatch` no interpreta `!` como negación a nivel de pattern completo (solo dentro de `[!seq]`). RN-58/C12 menciona glob "con `!`". Se valida que el pattern sea compilable; la semántica de negación a nivel-pattern (si el agente la soporta) es responsabilidad del motor de decisión del agente (C10), no de la validación del backend. Mitigación: la validación acepta `!` prefijo sin romper; documentado como Open Question si el agente requiere una semántica específica.
- **[DELETE de la última regla de un path]** → Done criterion C12: al eliminar reglas, los paths caen al default `alert_only`. Eso es comportamiento del motor del agente (C10), no del backend; el backend solo elimina y sincroniza. Sin riesgo de integridad.
- **[Orden de severity en memoria]** → Si el número de reglas creciera mucho, ordenar en memoria sería ineficiente. Para el alcance de la tesis (decenas de reglas) es irrelevante; se documenta para revisión futura.

## Open Questions

- ¿El contrato del `commands_consumer` del agente (C10) espera las reglas inline en el payload `rule_sync`, o hace pull tras recibir el comando? El diseño asume payload mínimo (solo `type`, `target_agent_id`, `ruleset_version`, `schema_version`, `signature`) coherente con el resto de comandos del stream. Verificar contra `agent/.../commands_consumer` antes de apply; si requiere reglas inline, agregar campo `rules: [...]` al payload.
- ¿La negación `!` a nivel pattern tiene semántica en el motor del agente, o solo se usa `[!seq]` de fnmatch? No bloquea este change (validación solo verifica compilabilidad).
