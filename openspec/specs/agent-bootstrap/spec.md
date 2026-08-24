# agent-bootstrap Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Agent generates Ed25519 key pair and CSR
El módulo `agent/bootstrap.py` SHALL generar un par de claves Ed25519 y construir un CSR con CN igual al `agent_id` del config al ejecutar el bootstrap. La clave privada MUST persistirse en `/var/lib/fim-agent/certs/agent-key.pem` con permisos `0600`. El CSR es efímero (no se persiste).

#### Scenario: Generación de par de claves
- **WHEN** `bootstrap.run()` es invocado y no existe `/var/lib/fim-agent/certs/agent-key.pem`
- **THEN** se genera un par de claves Ed25519 y la clave privada se escribe en `0600`

#### Scenario: Par de claves ya existe
- **WHEN** `/var/lib/fim-agent/certs/agent-key.pem` ya existe
- **THEN** se reutiliza el par de claves existente (no se regenera)

### Requirement: Agent calls bootstrap endpoint and persists secrets
El módulo SHALL enviar `POST /agents/bootstrap` con `{agent_id, csr_pem, bootstrap_secret}` al backend (usando la URL del config más el path `/agents/bootstrap`). Si el response es 200, MUST persistir: `cert_pem` → `/var/lib/fim-agent/certs/agent-cert.pem` (`0600`), `ca_cert_pem` → `/var/lib/fim-agent/certs/ca.pem` (`0600`), `shared_secret_hex` (decoded) → `/var/lib/fim-agent/secrets/shared_secret` (`0400`), `master_secret_hex` (decoded) → `/var/lib/fim-agent/secrets/master_secret` (`0400`). Si el response no es 200, MUST terminar con `SystemExit(1)` y mensaje de error.

#### Scenario: Bootstrap exitoso
- **WHEN** el backend responde 200 al `POST /agents/bootstrap`
- **THEN** existen los 4 archivos en los paths correctos con los permisos especificados

#### Scenario: Bootstrap falla (401)
- **WHEN** el backend responde 401 (bootstrap_secret inválido)
- **THEN** el agente termina con `SystemExit(1)` y loguea el error

#### Scenario: Backend inalcanzable
- **WHEN** la conexión al backend falla (timeout / connection refused)
- **THEN** el agente termina con `SystemExit(1)` y loguea el error de conexión

### Requirement: Agent startup checks for valid certificate before bootstrapping
El `agent/__main__.py` SHALL verificar al arrancar si existe un certificado válido en `/var/lib/fim-agent/certs/agent-cert.pem`. Si no existe o es inválido/expirado, MUST ejecutar `bootstrap.run()` antes de iniciar el loop principal. Si el certificado es válido, el bootstrap se omite.

#### Scenario: Primer arranque sin certificado
- **WHEN** el agente arranca y `/var/lib/fim-agent/certs/agent-cert.pem` no existe
- **THEN** se ejecuta el bootstrap completo antes del loop principal

#### Scenario: Arranque con certificado válido
- **WHEN** existe un certificado válido y no expirado
- **THEN** el bootstrap se omite y el agente continúa directamente al loop principal

#### Scenario: Arranque con certificado expirado
- **WHEN** el certificado existe pero su `not_valid_after` ya pasó
- **THEN** se ejecuta el bootstrap para obtener un cert nuevo

### Requirement: bootstrap_secret read from environment variable
El `bootstrap_secret` necesario para el bootstrap SHALL leerse de la variable de entorno `FIM_BOOTSTRAP_SECRET`. Si la variable no está seteada y el bootstrap es necesario, MUST terminar con `SystemExit(1)` y mensaje indicando que `FIM_BOOTSTRAP_SECRET` no está definida. Una vez completado el bootstrap exitosamente, la variable de entorno es irrelevante (los secrets ya están en disco).

#### Scenario: Bootstrap con variable de entorno seteada
- **WHEN** `FIM_BOOTSTRAP_SECRET` está definida y es el secreto correcto
- **THEN** el bootstrap completa exitosamente

#### Scenario: Bootstrap sin variable de entorno
- **WHEN** se requiere bootstrap y `FIM_BOOTSTRAP_SECRET` no está definida
- **THEN** el agente termina con `SystemExit(1)` y mensaje claro

### Requirement: Bootstrap certificate chain is verified before trust

Before persisting the certificate received during bootstrap, the agent SHALL verify that the certificate is signed by the received CA certificate. The verification MUST use the CA public key with the algorithm-appropriate method (Ed25519: `ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes)`, with no RSA padding or hash algorithm). If signature verification fails, the agent MUST raise `RuntimeError` and persist nothing (RN-78, RN-79).

#### Scenario: Certificate not signed by the received CA is rejected
- **WHEN** the bootstrap response contains a certificate not signed by the accompanying CA certificate
- **THEN** verification fails, a `RuntimeError` is raised, and no cert, CA, or secret is written to disk

#### Scenario: Certificate signed by the received CA passes the chain check
- **WHEN** the certificate is correctly signed by the accompanying CA certificate
- **THEN** the chain check passes and verification proceeds to the next checks

### Requirement: Bootstrap certificate CN matches the agent identity

The agent SHALL verify that the certificate's Common Name equals the configured `agent_id`. If it does not match, the agent MUST raise `RuntimeError` and persist nothing.

#### Scenario: Certificate with wrong CN is rejected
- **WHEN** the received certificate's CN is not equal to the agent's `agent_id`
- **THEN** a `RuntimeError` is raised and nothing is persisted

### Requirement: Bootstrap certificate public key matches the local private key

The agent SHALL verify that the public key embedded in the received certificate matches the public key of the locally generated private key (proving the backend signed the agent's own CSR). The comparison MUST be done over the serialized public key bytes. If they do not match, the agent MUST raise `RuntimeError` and persist nothing.

#### Scenario: Certificate whose public key does not match the local key is rejected
- **WHEN** the received certificate's public key differs from the local private key's public key
- **THEN** a `RuntimeError` is raised and nothing is persisted

#### Scenario: All checks pass and material is persisted
- **WHEN** the certificate chains to the CA, the CN matches `agent_id`, and the public key matches the local key
- **THEN** the cert, CA, `shared_secret`, and `master_secret` are written to disk with their existing permissions
