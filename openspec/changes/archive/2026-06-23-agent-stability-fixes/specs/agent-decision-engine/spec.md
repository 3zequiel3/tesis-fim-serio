## MODIFIED Requirements

### Requirement: Cache local de reglas con evaluación glob y negación

El agente SHALL mantener una cache local de reglas de decisión (`RulesCache`) que se actualiza al recibir un comando `rule_sync` firmado con HMAC y `ruleset_version` monotónico mayor o igual al aplicado actualmente; una versión igual a la aplicada es un replay seguro e idempotente y MUST reaplicarse sin error. Solo se descartan comandos con `ruleset_version` estrictamente menor al aplicado (RN-75: «descarta mensajes con versión menor»). Esto alinea la cache de reglas con la ruta de comandos (`agent/commands.py`, que ya usa `<`) y garantiza idempotencia ante re-entregas (RN-75, RN-79). La cache MUST persistirse bajo la clave `"rules"` en `/var/lib/fim-agent/state.json` (escritura atómica via `.tmp` + `os.replace()`). Al evaluar un evento, el sistema SHALL iterar las reglas en orden de declaración usando `fnmatch.fnmatch`: si alguna regla con prefijo `!` matchea el path, el resultado es `alert_only` sin importar las reglas inclusivas previas (exclusiva gana, RN-65). Si solo reglas inclusivas matchean, la primera en orden determina la acción. Si ninguna matchea, el resultado es `alert_only` (RN-06). La cache MUST ser thread-safe para lecturas concurrentes.

#### Scenario: Regla inclusiva matchea — acción aplicada

- **WHEN** el path `/etc/hosts` se evalúa contra la regla `{"pattern": "/etc/**", "action": "auto_restore"}`
- **THEN** la evaluación retorna `action: "auto_restore"`

#### Scenario: Regla exclusiva matchea — alert_only

- **WHEN** el path `/etc/mtab` se evalúa contra reglas `[{"pattern": "/etc/**", "action": "auto_restore"}, {"pattern": "!/etc/mtab", "negated": true}]`
- **THEN** la evaluación retorna `action: "alert_only"` porque la regla exclusiva gana

#### Scenario: Sin regla que matchee — default alert_only

- **WHEN** el path `/tmp/foo.txt` se evalúa y no hay regla que lo cubra
- **THEN** la evaluación retorna `action: "alert_only"` (RN-06)

#### Scenario: rule_sync con versión menor descartado

- **WHEN** el agente tiene `ruleset_version: 5` y recibe un `rule_sync` con `ruleset_version: 3`
- **THEN** el comando es descartado sin actualizar la cache y sin confirmar vía `event_ack`

#### Scenario: rule_sync con versión igual reaplicado idempotentemente

- **WHEN** el agente tiene `ruleset_version: 5` y recibe un `rule_sync` re-entregado con `ruleset_version: 5` y HMAC válido
- **THEN** el comando NO es rechazado: la cache se reaplica con las mismas reglas, `ruleset_version` permanece en 5, y el agente confirma vía `event_ack` (replay idempotente, RN-75)

#### Scenario: rule_sync válido — cache actualizada y persistida

- **WHEN** el agente recibe un `rule_sync` con `ruleset_version: 6` (mayor al actual) y HMAC válido
- **THEN** la cache se reemplaza con las nuevas reglas, `ruleset_version` en `state.json` se actualiza a 6, y el agente publica `event_ack`

#### Scenario: Cache vacía al arrancar — alert_only por defecto

- **WHEN** el agente arranca sin `rules` en `state.json`
- **THEN** todos los eventos se evalúan como `alert_only` hasta recibir el primer `rule_sync`

### Requirement: Motor de decisión con journal transaccional pre/post-acción

El `DecisionEngine` SHALL evaluar cada `DetectedChange` contra la `RulesCache`, ejecutar la acción correspondiente y registrar el resultado en el journal. Antes de ejecutar cualquier acción (incluido `alert_only`), MUST escribirse una entrada de journal con `state: "pending"` en `/var/lib/fim-agent/journal/{event_id}.json`. Tras ejecutar la acción física, `evaluate_and_act` MUST NOT marcar el estado terminal del journal de forma inmediata: en su lugar retorna, junto al payload del evento, un callable `commit_fn` que aplica la transición terminal (`completed` o `failed`). El caller (detector) MUST invocar `commit_fn()` únicamente después de que `await publisher.publish(...)` retorne sin excepción. Si el publish falla, la entrada permanece `pending` y se rehidrata al reiniciar (FA3, RN-75). El evento MUST publicarse al stream (vía publisher) independientemente del resultado de la acción. Si la acción falla, el payload del evento MUST incluir `action_failed: true`.

#### Scenario: Evaluación y acción completan exitosamente

- **WHEN** un evento con path `/etc/hosts` (acción `auto_restore`) es procesado por el motor
- **THEN** se escribe journal `{state: "pending"}`, se ejecuta la restauración, se retorna `commit_fn`, el detector publica el evento con `action: "auto_restore"`, y solo tras un publish exitoso `commit_fn()` marca journal `{state: "completed"}`

#### Scenario: Publish falla — la entrada permanece pending y se rehidrata

- **WHEN** la acción física completa pero `publisher.publish(...)` lanza excepción antes de invocar `commit_fn`
- **THEN** la entrada de journal permanece `{state: "pending"}` y es devuelta por `load_pending` al reiniciar para re-publicación

#### Scenario: Acción falla — journal failed tras publish, evento publicado igual

- **WHEN** la restauración de `/etc/passwd` falla porque `content_b64` es `None` en baseline
- **THEN** el evento se publica con `action_failed: true` y, tras el publish exitoso, `commit_fn()` marca el journal `{state: "failed", error: "no_baseline_content"}`

#### Scenario: alert_only — journal y publicación sin acción física

- **WHEN** un evento para `/var/log/app.log` es evaluado y no hay regla (default `alert_only`)
- **THEN** se escribe journal `{state: "pending"}` sin ejecutar acción física, el evento se publica normalmente, y tras el publish exitoso `commit_fn()` marca el journal `{state: "completed"}`
