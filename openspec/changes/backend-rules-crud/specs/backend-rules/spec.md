## ADDED Requirements

### Requirement: Crear una regla de decisión

El sistema SHALL exponer `POST /rules` para crear una regla. La operación MUST estar restringida al rol admin (RN-29 análogo a escrituras administrativas). El cuerpo del request MUST contener `pattern` (string), `severity` (enum `RuleSeverity`) y `action` (enum `RuleAction`) (RN-08). Tras crear la regla, el sistema MUST incrementar el counter global `RulesetVersion` (RN-75), hacer fan-out del comando `rule_sync` (ver capability de sincronización), registrar en `published_commands` y escribir una fila en `audit_log` (RN-94).

#### Scenario: Admin crea una regla válida
- **WHEN** un admin autenticado hace `POST /rules` con `{"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"}`
- **THEN** el sistema persiste la regla, retorna 201 con la regla creada (incluido su `id`)
- **AND** incrementa `RulesetVersion.version` en 1
- **AND** escribe una fila en `audit_log` con `action='rule_created'`, `target_type='rule'`, `target_id` = id de la regla

#### Scenario: Usuario no-admin no puede crear regla
- **WHEN** un usuario autenticado con rol distinto de admin hace `POST /rules`
- **THEN** el sistema retorna 403 y no crea ninguna regla

#### Scenario: Request sin autenticación
- **WHEN** se hace `POST /rules` sin token JWT válido
- **THEN** el sistema retorna 401

### Requirement: Validación de pattern, severity y action

El sistema SHALL validar todo `pattern` recibido como un glob compatible con `fnmatch` de Python (RN-08, RN-58); un `pattern` vacío o no compilable MUST ser rechazado con 422. El `severity` MUST pertenecer al enum `RuleSeverity` (critical, high, medium, low) y el `action` al enum `RuleAction` (auto_restore, quarantine, manual_review, alert_only); valores fuera del enum MUST ser rechazados con 422. La validación MUST ocurrir antes de cualquier escritura en base de datos.

#### Scenario: Pattern inválido
- **WHEN** un admin hace `POST /rules` con `pattern` vacío o un glob no compilable
- **THEN** el sistema retorna 422 y no persiste nada ni incrementa el counter

#### Scenario: Severity fuera del enum
- **WHEN** un admin hace `POST /rules` con `severity` que no está en {critical, high, medium, low}
- **THEN** el sistema retorna 422

#### Scenario: Action fuera del enum
- **WHEN** un admin hace `POST /rules` con `action` que no está en {auto_restore, quarantine, manual_review, alert_only}
- **THEN** el sistema retorna 422

### Requirement: Listar reglas ordenadas por severity

El sistema SHALL exponer `GET /rules` para cualquier usuario autenticado. La respuesta MUST listar las reglas ordenadas por severity en el orden canónico critical → high → medium → low (RN-09), y dentro de cada severity por `id` ascendente.

#### Scenario: Listado ordenado por severity
- **WHEN** existen reglas con severities mezcladas y un usuario autenticado hace `GET /rules`
- **THEN** el sistema retorna 200 con las reglas ordenadas critical primero, luego high, medium y low
- **AND** dentro de la misma severity las ordena por `id` ascendente

#### Scenario: Listado sin autenticación
- **WHEN** se hace `GET /rules` sin token JWT válido
- **THEN** el sistema retorna 401

### Requirement: Obtener una regla por id

El sistema SHALL exponer `GET /rules/{id}` para cualquier usuario autenticado, retornando la regla solicitada.

#### Scenario: Regla existente
- **WHEN** un usuario autenticado hace `GET /rules/{id}` de una regla existente
- **THEN** el sistema retorna 200 con la regla

#### Scenario: Regla inexistente
- **WHEN** un usuario autenticado hace `GET /rules/{id}` de un id que no existe
- **THEN** el sistema retorna 404

### Requirement: Actualizar una regla

El sistema SHALL exponer `PUT /rules/{id}` restringido al rol admin. La actualización MUST re-validar `pattern`, `severity` y `action`. Tras actualizar, el sistema MUST incrementar `RulesetVersion`, hacer fan-out de `rule_sync`, registrar en `published_commands` y escribir en `audit_log` con `action='rule_updated'`.

#### Scenario: Admin actualiza una regla
- **WHEN** un admin hace `PUT /rules/{id}` con datos válidos sobre una regla existente
- **THEN** el sistema persiste los cambios, retorna 200 con la regla actualizada
- **AND** incrementa `RulesetVersion.version`
- **AND** escribe `audit_log` con `action='rule_updated'`, `target_type='rule'`, `target_id={id}`

#### Scenario: Actualizar regla inexistente
- **WHEN** un admin hace `PUT /rules/{id}` de un id que no existe
- **THEN** el sistema retorna 404 y no incrementa el counter

#### Scenario: No-admin no puede actualizar
- **WHEN** un usuario no-admin hace `PUT /rules/{id}`
- **THEN** el sistema retorna 403

### Requirement: Eliminar una regla

El sistema SHALL exponer `DELETE /rules/{id}` restringido al rol admin. Tras eliminar, el sistema MUST incrementar `RulesetVersion`, hacer fan-out de `rule_sync`, registrar en `published_commands` y escribir en `audit_log` con `action='rule_deleted'`.

#### Scenario: Admin elimina una regla
- **WHEN** un admin hace `DELETE /rules/{id}` de una regla existente
- **THEN** el sistema elimina la regla, retorna 204 (o 200 con confirmación)
- **AND** incrementa `RulesetVersion.version`
- **AND** escribe `audit_log` con `action='rule_deleted'`, `target_type='rule'`, `target_id={id}`

#### Scenario: Eliminar regla inexistente
- **WHEN** un admin hace `DELETE /rules/{id}` de un id que no existe
- **THEN** el sistema retorna 404 y no incrementa el counter

#### Scenario: No-admin no puede eliminar
- **WHEN** un usuario no-admin hace `DELETE /rules/{id}`
- **THEN** el sistema retorna 403

### Requirement: Fan-out de rule_sync firmado por agente

En cada escritura exitosa (crear, actualizar, eliminar) el sistema SHALL publicar el comando `rule_sync` al stream Valkey `commands` mediante fan-out: un mensaje físico por cada agente registrado con `shared_secret_hex` no nulo (D9, RN-58, RN-79). Cada mensaje MUST llevar `target_agent_id = agent.agent_id`, el `ruleset_version` recién incrementado, `schema_version`, y MUST estar firmado HMAC-SHA256 con el `shared_secret_hex` específico de ese agente. El léxico del payload MUST ser snake_case (RN-71). El `target_agent_id` MUST llevar siempre el id explícito del agente (nunca null para `rule_sync`).

#### Scenario: Fan-out a varios agentes
- **WHEN** hay dos agentes registrados con secret y un admin crea una regla
- **THEN** el sistema publica dos mensajes `rule_sync` en el stream `commands`, uno por agente
- **AND** cada mensaje lleva `target_agent_id` del agente correspondiente y firma válida con su `shared_secret_hex`
- **AND** ambos mensajes llevan el mismo `ruleset_version`

#### Scenario: Firma verificable por el agente
- **WHEN** se publica un `rule_sync` para un agente
- **THEN** la firma `signature` del payload es válida bajo `verify_payload` con el `shared_secret_hex` de ese agente

#### Scenario: Sin agentes registrados
- **WHEN** no hay agentes con `shared_secret_hex` y un admin crea una regla
- **THEN** el sistema incrementa el counter pero no publica ningún mensaje ni inserta en `published_commands`
- **AND** la operación retorna éxito

### Requirement: Registro de comandos publicados

Por cada mensaje `rule_sync` publicado, el sistema SHALL insertar una fila en `published_commands` (D10) con `command_type='rule_sync'`, `target_agent_id` del agente destino, `ruleset_version` publicado y `published_at`. Este registro es la base del check D5 de "agente al día".

#### Scenario: Un row por mensaje publicado
- **WHEN** se hace fan-out de `rule_sync` a tres agentes
- **THEN** se insertan tres filas en `published_commands`, una por agente, todas con el mismo `ruleset_version` y `command_type='rule_sync'`

#### Scenario: Check de agente al día
- **WHEN** se consulta `SELECT MAX(ruleset_version) FROM published_commands WHERE target_agent_id = :agent_id OR target_agent_id IS NULL`
- **THEN** el resultado es la máxima versión de comando dirigida a ese agente, comparable con `Agent.ruleset_version_applied`
