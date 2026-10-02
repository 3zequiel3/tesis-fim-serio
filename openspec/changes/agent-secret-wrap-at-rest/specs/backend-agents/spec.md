## MODIFIED Requirements

### Requirement: Agent bootstrap with CSR exchange
El backend SHALL proveer `POST /agents/bootstrap` (sin autenticación JWT) que recibe `{agent_id: str, csr_pem: str, bootstrap_secret: str}`. El endpoint MUST servirse exclusivamente por el listener TLS dedicado al bootstrap en el puerto 8444 (D52/RN-146; ver spec `backend-pki`); la aplicación principal servida en el puerto 8000 MUST NOT montarlo, de modo que el `bootstrap_secret` y los secretos de la respuesta nunca viajen en claro. MUST verificar que el `agent_id` existe, que `Argon2id.verify(bootstrap_secret, stored_hash)` pasa, y que el CSR es válido (Ed25519, CN coincide con agent_id). Si todo es válido MUST: emitir certificado (90 días), generar `shared_secret` (32 bytes random) y `master_secret` (32 bytes random), retornar `{cert_pem, ca_cert_pem, shared_secret_hex, master_secret_hex}`, y nullear `bootstrap_secret_hash` en DB. El `bootstrap_secret` es de un solo uso: un segundo intento con el mismo secreto MUST fallar.

El `shared_secret` SHALL persistirse en `agents.shared_secret_hex` **envuelto** con el formato `v1:` de la spec `agent-secret-at-rest` (AES-256-GCM, AAD = `agent_id`, D86/RN-180), en la misma transacción que nullea `bootstrap_secret_hash`; MUST NOT persistirse en claro. La respuesta al agente no cambia: `shared_secret_hex` sigue siendo el hex en claro de los 32 bytes, transportado por el listener TLS del puerto 8444.

#### Scenario: Bootstrap exitoso
- **WHEN** un agente envía CSR válido con el bootstrap_secret correcto
- **THEN** responde 200 con `{cert_pem, ca_cert_pem, shared_secret_hex, master_secret_hex}` y `bootstrap_secret_hash` queda NULL en DB

#### Scenario: El secreto se persiste envuelto
- **WHEN** un agente completa el bootstrap
- **THEN** `agents.shared_secret_hex` empieza con `v1:` y es distinto del `shared_secret_hex` de la respuesta
- **AND** `unwrap_agent_secret(agent_id, agents.shared_secret_hex)` devuelve los mismos 32 bytes que la respuesta codifica en hex

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

#### Scenario: El puerto 8000 no sirve el bootstrap
- **WHEN** se hace `POST /agents/bootstrap` contra la aplicación principal en el puerto 8000
- **THEN** responde 404 o 405 y no se consulta ni modifica ningún agente
