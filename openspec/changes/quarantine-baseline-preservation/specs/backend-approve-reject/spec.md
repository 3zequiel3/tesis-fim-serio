## MODIFIED Requirements

### Requirement: Comandos restore_file / quarantine_file publicados en Valkey al rechazar

Al rechazar exitosamente, el sistema SHALL publicar en el stream `commands` un mensaje con: `type="restore_file"` o `type="quarantine_file"`, `command_id` (UUID v4), `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`. No incluye `hash` ni `ruleset_version`. El comando `quarantine_file` SHALL incluir además `agent_event_id`, igual a `Event.event_id` (el UUID que el agente emitió para el evento rechazado), cubierto por la `signature`: el agente lo usa como identidad del artefacto de cuarentena y como clave de journal (D82/RN-176). `event_id` conserva su significado (identificador del evento en el backend) y la correlación `command_ack` → evento sigue leyéndose de la fila `PublishedCommand`, no del payload.

**La emisión del comando SHALL pasar por el outbox transaccional (D37 / RN-131, prevalece sobre FIX-02)**, con el mismo criterio que `baseline_update`: la fila `PublishedCommand` con el payload firmado se inserta con `status="pending"` dentro de la transacción del evento, y el despachador hace el `XADD` después del commit. El orden en `_reject_single` SHALL ser: (1) UPDATE optimista; (2) flush + refresh; (3) consultar `baseline_entry`; (4) `_write_audit`; (5) **encolar el comando en el outbox** según corresponda, salvo en el no-op de baseline `absent` (RN-74); (6) `db.commit()`; (7) `db.refresh(event)`; (8) intento inmediato best-effort de publicación del outbox.

El no-op de baseline `absent` (RN-74) conserva su comportamiento: no se encola comando alguno.

El rechazo con cuarentena SHALL dejar el evento en `rejected`, como cualquier rechazo (RN-11, RN-12, RN-72 sin enmienda); el resultado físico de la cuarentena se expone como `quarantine_state` derivado en lectura (`backend-events-api`).

Si el `shared_secret` del agente destino no puede obtenerse, la excepción SHALL propagarse y revertir la transacción; el endpoint SHALL responder un error en lugar de dejar el evento `rejected` sin comando emitido.

#### Scenario: Comando restore_file contiene campos requeridos
- **WHEN** se rechaza con `action="restore"`
- **THEN** el mensaje en el stream contiene `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`
- **AND** la `signature` verifica con el `shared_secret` del agente

#### Scenario: Comando quarantine_file lleva la identidad del evento del agente
- **WHEN** se rechaza con `action="quarantine"` un evento cuyo `event_id` del agente es `<uuid>`
- **THEN** el mensaje contiene `type`, `command_id`, `event_id`, `agent_event_id`, `target_agent_id`, `path`, `issued_at`, `signature`
- **AND** `agent_event_id` es `<uuid>`
- **AND** la `signature` verifica con el `shared_secret` del agente sobre el payload que incluye `agent_event_id`

#### Scenario: La fila del comando nace pending en la transacción del rechazo
- **WHEN** se rechaza un evento exitosamente con `action="quarantine"`
- **THEN** existe una fila `PublishedCommand` con `command_type="quarantine_file"`, `status="pending"` y `published_at` nulo, comiteada junto con la mutación del evento
- **AND** el evento queda en `rejected`

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
