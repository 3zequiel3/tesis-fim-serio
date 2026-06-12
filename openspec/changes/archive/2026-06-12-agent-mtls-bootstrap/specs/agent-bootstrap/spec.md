## ADDED Requirements

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
