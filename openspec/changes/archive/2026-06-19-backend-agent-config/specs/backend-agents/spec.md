# Spec: backend-agents (delta)

Capability: Delta sobre registro y bootstrap de agentes — documenta que los endpoints GET /agents y GET /agents/{id} son parte del mismo recurso `/agents` definido en C14.

---

## ADDED Requirements

### Requirement: Endpoints GET /agents y GET /agents/{id} son parte del recurso agents

Los endpoints `GET /agents` y `GET /agents/{id}` (definidos en la spec `backend-agent-management`) MUST ser registrados bajo el mismo router de agents con prefix `/agents` y tag `agents`. El recurso `/agents` incluye tanto los endpoints de ciclo de vida (register, bootstrap — C06) como los de consulta y configuración (C14).

#### Scenario: GET /agents accesible bajo el mismo prefix que POST /register
- **WHEN** el backend arranca
- **THEN** tanto `GET /agents` como `POST /agents/register` son accesibles bajo el prefix `/agents`
