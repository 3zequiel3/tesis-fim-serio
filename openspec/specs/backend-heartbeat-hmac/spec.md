# Spec: backend-heartbeat-hmac

## Purpose
Define los requisitos de verificación HMAC para el consumer del stream `agent_heartbeat`. Simétrico con el protocolo de verificación del events consumer (RN-79, D22).

## Requirements

### Requirement: Verificación HMAC-SHA256 en el consumer de heartbeat (D22 / RN-119)

El consumer del stream `agent_heartbeat` MUST verificar la firma `HMAC-SHA256(shared_secret, canonical_json(payload))` de cada payload antes de actualizar el estado del agente. La verificación SHALL realizarse después de obtener el agente de DB (el `shared_secret` proviene de ese lookup), usando `hmac.compare_digest` para evitar timing attacks. Un payload con firma inválida MUST ser descartado sin actualizar estado. Un `agent_id` desconocido (no en DB) MUST ser descartado con log de warning.

#### Scenario: Heartbeat con HMAC válido actualiza estado del agente

- **WHEN** llega un mensaje en `agent_heartbeat` con `agent_id` de un agente registrado y `signature` válida
- **THEN** el consumer actualiza `agent.last_heartbeat`, `agent.queue_pressure`, y `agent.status` en DB

#### Scenario: Heartbeat con HMAC inválido es descartado

- **WHEN** llega un mensaje en `agent_heartbeat` con `agent_id` registrado pero `signature` inválida o ausente
- **THEN** el consumer descarta el mensaje sin modificar el agente en DB
- **AND** emite log de warning con `agent_id` y motivo

#### Scenario: Heartbeat de agente desconocido es descartado

- **WHEN** llega un mensaje en `agent_heartbeat` con un `agent_id` que no existe en la tabla `agents`
- **THEN** el consumer descarta el mensaje sin modificar ningún agente
- **AND** emite log de warning con el `agent_id` desconocido

#### Scenario: Agente con shared_secret_hex vacío es descartado

- **WHEN** llega un heartbeat de un agente que existe en DB pero tiene `shared_secret_hex` vacío o nulo
- **THEN** el consumer descarta el mensaje con log de error
- **AND** no actualiza el estado del agente
