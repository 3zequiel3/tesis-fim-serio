# Spec: backend-agents

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Admin pre-registers agent with bootstrap secret
El backend SHALL proveer `POST /agents/register` (requiere JWT de admin) que recibe `{agent_id: str, bootstrap_secret: str}` y persiste el agente en DB con `bootstrap_secret_hash = Argon2id(bootstrap_secret)`. Si ya existe un agente con ese `agent_id`, el endpoint MUST retornar 409. `bootstrap_secret` MUST tener al menos 16 caracteres.

#### Scenario: Registro exitoso
- **WHEN** un admin autentico hace `POST /agents/register` con `agent_id` nuevo y `bootstrap_secret` válido
- **THEN** responde 201, crea una fila en `agents` con `status=offline` y `bootstrap_secret_hash` poblado

#### Scenario: agent_id duplicado
- **WHEN** se intenta registrar un `agent_id` que ya existe en DB
- **THEN** responde 409 con mensaje de error

#### Scenario: bootstrap_secret demasiado corto
- **WHEN** `bootstrap_secret` tiene menos de 16 caracteres
- **THEN** responde 422 con detalle de validación

### Requirement: Agent bootstrap with CSR exchange
El backend SHALL proveer `POST /agents/bootstrap` (sin autenticación JWT) que recibe `{agent_id: str, csr_pem: str, bootstrap_secret: str}`. MUST verificar que el `agent_id` existe, que `Argon2id.verify(bootstrap_secret, stored_hash)` pasa, y que el CSR es válido (Ed25519, CN coincide con agent_id). Si todo es válido MUST: emitir certificado (90 días), generar `shared_secret` (32 bytes random) y `master_secret` (32 bytes random), retornar `{cert_pem, ca_cert_pem, shared_secret_hex, master_secret_hex}`, y nullear `bootstrap_secret_hash` en DB. El `bootstrap_secret` es de un solo uso: un segundo intento con el mismo secreto MUST fallar.

#### Scenario: Bootstrap exitoso
- **WHEN** un agente envía CSR válido con el bootstrap_secret correcto
- **THEN** responde 200 con `{cert_pem, ca_cert_pem, shared_secret_hex, master_secret_hex}` y `bootstrap_secret_hash` queda NULL en DB

#### Scenario: bootstrap_secret inválido
- **WHEN** el bootstrap_secret no coincide con el hash almacenado
- **THEN** responde 401

#### Scenario: Segundo intento de bootstrap (bootstrap_secret ya invalidado)
- **WHEN** el agente reintenta el bootstrap después de uno exitoso (hash ya NULL)
- **THEN** responde 401

#### Scenario: agent_id no registrado
- **WHEN** el bootstrap usa un `agent_id` que no existe en DB
- **THEN** responde 404

#### Scenario: CSR con CN incorrecto
- **WHEN** el CSR tiene CN distinto al `agent_id` del request
- **THEN** responde 422

### Requirement: Bootstrap secret is single-use
El campo `bootstrap_secret_hash` en la tabla `agents` MUST ser nulleado atómicamente en la misma transacción DB en que se emite el certificado. Si la transacción falla, el secreto no se invalida y el agente puede reintentar.

#### Scenario: Invalidación atómica
- **WHEN** el bootstrap completa exitosamente
- **THEN** `agents.bootstrap_secret_hash` es NULL en DB inmediatamente; cualquier segundo intento retorna 401

### Requirement: Endpoints GET /agents y GET /agents/{id} son parte del recurso agents

Los endpoints `GET /agents` y `GET /agents/{id}` (definidos en la spec `backend-agent-management`) MUST ser registrados bajo el mismo router de agents con prefix `/agents` y tag `agents`. El recurso `/agents` incluye tanto los endpoints de ciclo de vida (register, bootstrap — C06) como los de consulta y configuración (C14).

#### Scenario: GET /agents accesible bajo el mismo prefix que POST /register
- **WHEN** el backend arranca
- **THEN** tanto `GET /agents` como `POST /agents/register` son accesibles bajo el prefix `/agents`

### Requirement: AgentStatus incluye el valor revoked

El enum `AgentStatus` en `agents/models.py` MUST incluir el valor `revoked`. La columna `status` en la tabla `agents` de PostgreSQL MUST aceptar el valor `'revoked'`. La migración SQL MUST usar `ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'revoked'` para ser idempotente.

#### Scenario: Agente revocado registrado en DB
- **WHEN** el estado de un agente se actualiza a `revoked` en DB
- **THEN** la fila en la tabla `agents` refleja `status = 'revoked'` sin error de constraint

#### Scenario: Migración idempotente
- **WHEN** el script SQL de migración se ejecuta dos veces
- **THEN** no produce error en la segunda ejecución (IF NOT EXISTS garantiza idempotencia)

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
