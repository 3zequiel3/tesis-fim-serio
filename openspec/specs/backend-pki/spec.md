# Spec: backend-pki

Capability: PKI interna del backend FIM — CA Ed25519 auto-firmada, emisión de certificados para agentes, revocación, y listener mTLS en puerto 8443.

---

### Requirement: CA generation on first startup
El backend SHALL generar una CA raíz auto-firmada Ed25519 con validez 10 años al arrancar si `CA_KEY_PATH` no existe. La CA MUST persistirse en los paths indicados por las variables de entorno `CA_CERT_PATH` y `CA_KEY_PATH`. La generación MUST ser idempotente: si los archivos ya existen, no se regenera.

#### Scenario: Primera inicialización sin CA
- **WHEN** el backend arranca y `CA_KEY_PATH` no existe en el filesystem
- **THEN** se generan `ca.pem` y `ca-key.pem` en los paths configurados y el backend continúa

#### Scenario: Reinicio con CA existente
- **WHEN** el backend arranca y `CA_KEY_PATH` ya existe
- **THEN** la CA existente se carga sin regenerar; los fingerprints de los certs emitidos previamente siguen siendo válidos

### Requirement: Agent certificate issuance
El backend SHALL emitir certificados TLS 1.3 para agentes firmados por la CA propia. Cada certificado MUST tener validez de 90 días, CN igual al `agent_id`, y extensiones de uso de clave para autenticación de cliente TLS. Los certificados MUST ser verificables contra el `ca.pem` del backend.

#### Scenario: Emisión de certificado para agente
- **WHEN** se presenta un CSR válido con CN=`agent_id` a `pki.issue_certificate(csr)`
- **THEN** se retorna un certificado firmado por la CA, con validez 90 días y CN igual al `agent_id`

#### Scenario: Certificado verificable contra CA
- **WHEN** se verifica el certificado emitido contra el `ca.pem`
- **THEN** la verificación pasa sin errores

### Requirement: Certificate revocation check
El backend SHALL rechazar conexiones mTLS de agentes cuyo número de serie de certificado esté en la tabla `revoked_certificates`. La verificación MUST ocurrir en cada handshake mTLS, consultando la DB.

#### Scenario: Agente con certificado no revocado
- **WHEN** un agente conecta al puerto mTLS 8443 con un certificado válido no revocado
- **THEN** el handshake TLS completa y la conexión se establece

#### Scenario: Agente con certificado revocado
- **WHEN** un agente conecta con un certificado cuyo serial está en `revoked_certificates`
- **THEN** el handshake TLS se rechaza con error de certificado

### Requirement: mTLS listener on port 8443
El backend SHALL exponer un listener adicional en el puerto 8443 configurado con `ssl_cert_reqs=CERT_REQUIRED` y `ssl_ca_certs` apuntando al `ca.pem` de la CA propia. Este listener MUST servir las mismas rutas de la app FastAPI pero requiriendo client certificate en todas las conexiones.

#### Scenario: Conexión mTLS exitosa
- **WHEN** un agente con certificado válido emitido por la CA se conecta al puerto 8443
- **THEN** el handshake mTLS completa y la solicitud HTTP llega al handler de FastAPI

#### Scenario: Conexión sin certificado rechazada
- **WHEN** un cliente intenta conectar al puerto 8443 sin presentar certificado de cliente
- **THEN** el handshake TLS falla con `SSL_ERROR_NO_CERTIFICATE`
