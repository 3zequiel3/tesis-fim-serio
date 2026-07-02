## ADDED Requirements

### Requirement: AgentStatus incluye el valor revoked

El enum `AgentStatus` en `agents/models.py` MUST incluir el valor `revoked`. La columna `status` en la tabla `agents` de PostgreSQL MUST aceptar el valor `'revoked'`. La migración SQL MUST usar `ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'revoked'` para ser idempotente.

#### Scenario: Agente revocado registrado en DB
- **WHEN** el estado de un agente se actualiza a `revoked` en DB
- **THEN** la fila en la tabla `agents` refleja `status = 'revoked'` sin error de constraint

#### Scenario: Migración idempotente
- **WHEN** el script SQL de migración se ejecuta dos veces
- **THEN** no produce error en la segunda ejecución (IF NOT EXISTS garantiza idempotencia)

---

### Requirement: Consumers rechazan mensajes de agentes revocados

El consumer de eventos (`events/consumer.py`) MUST consultar el estado del agente en DB al inicio del procesamiento de cada mensaje. Si `agent.status == revoked`, el mensaje MUST ser descartado sin procesamiento y MUST registrarse un log de nivel INFO con el `agent_id`. El mismo comportamiento MUST aplicar en el consumer de heartbeats (`agents/heartbeat_consumer.py`).

#### Scenario: Mensaje de agente revocado descartado en event consumer
- **WHEN** `events/consumer.py` recibe un mensaje de un agente cuyo `status == revoked`
- **THEN** el mensaje se descarta sin procesamiento, no se actualiza ningún estado en DB, y se emite un log INFO con el agent_id

#### Scenario: Heartbeat de agente revocado descartado
- **WHEN** `agents/heartbeat_consumer.py` recibe un heartbeat de un agente cuyo `status == revoked`
- **THEN** el heartbeat se descarta sin actualizar `last_seen` ni el estado del agente, y se emite un log INFO con el agent_id

#### Scenario: Agente con status online procesado normalmente
- **WHEN** el consumer recibe un mensaje de un agente con `status == online`
- **THEN** el mensaje se procesa normalmente sin descarte
