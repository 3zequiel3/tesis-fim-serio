## MODIFIED Requirements

### Requirement: Agent calls bootstrap endpoint and persists secrets
El módulo SHALL enviar `POST /agents/bootstrap` con `{agent_id, csr_pem, bootstrap_secret}` al backend (usando la URL del config más el path `/agents/bootstrap`). `backend_url` MUST apuntar al listener TLS dedicado al bootstrap (puerto 8444, D52/RN-146) y MUST usar el esquema `https`: con cualquier otro esquema el agente MUST terminar con `SystemExit(1)` y un mensaje explícito **antes** de generar el CSR o abrir cualquier conexión de red (RN-114). La conexión MUST verificar el certificado del servidor contra `ca_cert_path` —el ancla de confianza inicial, provisionada con huella verificada por el instalador— y MUST verificar que su SAN cubre el host de `backend_url` (nombre como `DNSName`, IP como `IPAddress`, D53/RN-147). Si `ca_cert_path` no existe, MUST terminar con `SystemExit(1)` sin enviar la solicitud.

Si el response es 200, MUST persistir: `cert_pem` → `/var/lib/fim-agent/certs/agent-cert.pem` (`0600`), `ca_cert_pem` → `/var/lib/fim-agent/certs/ca.pem` (`0600`), `shared_secret_hex` (decoded) → `/var/lib/fim-agent/secrets/shared_secret` (`0400`), `master_secret_hex` (decoded) → `/var/lib/fim-agent/secrets/master_secret` (`0400`). Si el response no es 200, MUST terminar con `SystemExit(1)` y mensaje de error.

#### Scenario: Bootstrap exitoso
- **WHEN** el backend responde 200 al `POST /agents/bootstrap`
- **THEN** existen los 4 archivos en los paths correctos con los permisos especificados

#### Scenario: Bootstrap falla (401)
- **WHEN** el backend responde 401 (bootstrap_secret inválido)
- **THEN** el agente termina con `SystemExit(1)` y loguea el error

#### Scenario: Backend inalcanzable
- **WHEN** la conexión al backend falla (timeout / connection refused)
- **THEN** el agente termina con `SystemExit(1)` y loguea el error de conexión

#### Scenario: `backend_url` sin `https`
- **WHEN** `backend_url` es `http://203.0.113.10:8000`
- **THEN** el agente termina con `SystemExit(1)` y un mensaje que exige `https`
- **AND** no se genera CSR ni se abre ninguna conexión de red

#### Scenario: El SAN del servidor no cubre el host configurado
- **WHEN** `backend_url` es `https://203.0.113.10:8444` y el certificado del backend encadena a `ca_cert_path` pero su SAN no incluye `IPAddress(203.0.113.10)`
- **THEN** el agente termina con `SystemExit(1)` informando el error de verificación
- **AND** no se persiste ningún certificado ni secreto

#### Scenario: Bootstrap contra una IP pública cubierta por el SAN
- **WHEN** `backend_url` es `https://203.0.113.10:8444` y el servidor tiene `FIM_PUBLIC_HOSTS=203.0.113.10`
- **THEN** el bootstrap completa sin mapear nombres en `/etc/hosts`
