## MODIFIED Requirements

### Requirement: Comando baseline_update publicado en Valkey al aprobar

Al aprobar exitosamente un evento, el sistema SHALL publicar en el stream `commands` de Valkey un mensaje con los campos: `type="baseline_update"`, `command_id` (UUID v4), `event_id`, `target_agent_id` (igual a `event.agent_id`), `path` (igual a `event.path`), `hash` (igual a `event.hash`, puede ser null), `baseline_status` ("present" | "absent"), `ruleset_version` (counter global incrementado, D5), `issued_at` (ISO8601 UTC), `signature` (HMAC-SHA256 hex del payload canónico con la clave `shared_secret` del agente). NO se publica ningún comando `get_file_hash` (D2, D8).

**La emisión del comando SHALL pasar por el outbox transaccional (D37 / RN-131, prevalece sobre FIX-02).** La fila `PublishedCommand` con el payload ya firmado SHALL insertarse con `status="pending"` y `published_at=None` **dentro de la misma transacción** que la mutación del evento, y el `XADD` SHALL ejecutarlo el despachador del outbox después del commit. El orden en `_approve_single` SHALL ser: (1) verificar hash/confirm_absent; (2) UPDATE optimista; (3) flush + refresh; (4) `_increment_ruleset_version`; (5) `_upsert_baseline_entry`; (6) `_write_audit`; (7) **encolar el comando en el outbox**; (8) `db.commit()`; (9) `db.refresh(event)`; (10) intento inmediato best-effort de publicación del outbox.

La inversión respecto de FIX-02 es deliberada. FIX-02 protegía contra que el agente recibiera un comando de una transacción que después se revirtiera; con el outbox esa protección la da la **atomicidad**, y de forma más fuerte: la fila del comando vive o muere con el evento. Si la transacción se revierte, no queda nada que publicar. Si comitea, el comando está garantizado y el despachador lo entrega con reintento. Deja de existir el estado en que un evento es terminal y su comando no se emitió.

Si el `shared_secret` del agente destino no puede obtenerse, la excepción SHALL propagarse y revertir la transacción. El endpoint SHALL responder un error. NO se permite loguear y retornar dejando el evento terminal y ningún comando emitido.

Las columnas `command_id`, `event_id` y `ack_status` de `PublishedCommand` conservan su semántica de D30/RN-124 sin cambios: `status` es el estado de outbox y `ack_status` el de ejecución confirmada por el agente, y no se fusionan.

#### Scenario: Comando baseline_update contiene los campos requeridos
- **WHEN** se aprueba un evento exitosamente
- **THEN** el mensaje en el stream `commands` contiene exactamente los campos `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `hash`, `baseline_status`, `ruleset_version`, `issued_at`, `signature`
- **AND** `signature` verifica correctamente con HMAC-SHA256 y el `shared_secret` del agente objetivo

#### Scenario: La fila del comando nace pending en la transacción del evento
- **WHEN** se aprueba un evento exitosamente
- **THEN** existe una fila `PublishedCommand` con `command_type="baseline_update"`, `status="pending"` y `published_at` nulo, comiteada junto con la mutación del evento

#### Scenario: Valkey caído deja el evento aprobado y el comando pendiente
- **WHEN** se aprueba un evento y el `XADD` falla porque Valkey no responde
- **THEN** el endpoint responde exitosamente, el evento queda `approved` y la fila del comando queda `pending`
- **AND** el despachador del outbox publica el comando en una corrida posterior y la marca `published`

#### Scenario: Una transacción revertida no deja comando encolado
- **WHEN** la aprobación falla después de encolar el comando y la transacción se revierte
- **THEN** no queda ninguna fila `PublishedCommand` para ese evento y el evento conserva su estado anterior

#### Scenario: Un agente sin shared_secret hace fallar la aprobación
- **WHEN** se aprueba un evento cuyo agente no tiene `shared_secret_hex`
- **THEN** la transacción se revierte, el evento NO queda `approved` y el endpoint responde un error

#### Scenario: No se publica get_file_hash
- **WHEN** se procesa cualquier approve o reject
- **THEN** no aparece ningún mensaje de tipo `get_file_hash` en el stream `commands`

### Requirement: Comandos restore_file / quarantine_file publicados en Valkey al rechazar

Al rechazar exitosamente, el sistema SHALL publicar en el stream `commands` un mensaje con: `type="restore_file"` o `type="quarantine_file"`, `command_id` (UUID v4), `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`. No incluye `hash` ni `ruleset_version`.

**La emisión del comando SHALL pasar por el outbox transaccional (D37 / RN-131, prevalece sobre FIX-02)**, con el mismo criterio que `baseline_update`: la fila `PublishedCommand` con el payload firmado se inserta con `status="pending"` dentro de la transacción del evento, y el despachador hace el `XADD` después del commit. El orden en `_reject_single` SHALL ser: (1) UPDATE optimista; (2) flush + refresh; (3) consultar `baseline_entry`; (4) `_write_audit`; (5) **encolar el comando en el outbox** según corresponda, salvo en el no-op de baseline `absent` (RN-74); (6) `db.commit()`; (7) `db.refresh(event)`; (8) intento inmediato best-effort de publicación del outbox.

El no-op de baseline `absent` (RN-74) conserva su comportamiento: no se encola comando alguno.

Si el `shared_secret` del agente destino no puede obtenerse, la excepción SHALL propagarse y revertir la transacción; el endpoint SHALL responder un error en lugar de dejar el evento `rejected` sin comando emitido.

#### Scenario: Comando restore_file contiene campos requeridos
- **WHEN** se rechaza con `action="restore"`
- **THEN** el mensaje en el stream contiene `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`
- **AND** la `signature` verifica con el `shared_secret` del agente

#### Scenario: La fila del comando nace pending en la transacción del rechazo
- **WHEN** se rechaza un evento exitosamente con `action="quarantine"`
- **THEN** existe una fila `PublishedCommand` con `command_type="quarantine_file"`, `status="pending"` y `published_at` nulo, comiteada junto con la mutación del evento

#### Scenario: Valkey caído deja el evento rechazado y el comando pendiente
- **WHEN** se rechaza un evento y el `XADD` falla porque Valkey no responde
- **THEN** el endpoint responde exitosamente, el evento queda `rejected` y la fila del comando queda `pending`
- **AND** el despachador del outbox lo publica en una corrida posterior

#### Scenario: El no-op de baseline absent no encola comando
- **WHEN** se rechaza un evento cuyo `baseline_entry` tiene `status=absent`
- **THEN** no se inserta ninguna fila `PublishedCommand` y el evento queda `rejected`

#### Scenario: Un agente sin shared_secret hace fallar el rechazo
- **WHEN** se rechaza un evento cuyo agente no tiene `shared_secret_hex`
- **THEN** la transacción se revierte, el evento NO queda `rejected` y el endpoint responde un error
