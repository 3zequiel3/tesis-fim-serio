## MODIFIED Requirements

### Requirement: mTLS listener on port 8443

El backend SHALL exponer un listener adicional en el puerto 8443 configurado con `ssl_cert_reqs=CERT_REQUIRED` y `ssl_ca_certs` apuntando al `ca.pem` de la CA propia. Este listener MUST servir exclusivamente la aplicación dedicada `mtls_app`, que monta sólo `POST /agents/renew`, requiriendo client certificate en todas las conexiones (D52/RN-146). La API de la consola y `POST /agents/bootstrap` MUST NOT servirse por este puerto. El certificado de servidor que presenta es el del backend, cuyo SAN se define en el requisito "SAN del certificado de servidor del backend desde `FIM_PUBLIC_HOSTS`".

El listener mTLS MUST ejecutarse sobre el event loop principal de la aplicación como una task de lifespan gestionada, NO sobre un thread secundario (C10). En concreto:
- `start_mtls_server(...)` SHALL construir el `uvicorn.Server` con `config.install_signal_handlers = False` y retornar el server configurado (o `None` cuando los certificados no están disponibles), sin lanzar ningún `threading.Thread` ni llamar `asyncio.run`.
- El lifespan de `main.py` SHALL arrancar el server mediante `asyncio.create_task(mtls_server.serve())`, registrando la task junto a las demás tasks de lifespan (`consumer_task`, `heartbeat_task`, `retention_task_handle`), y SHALL cancelarla en shutdown incluyéndola en el `asyncio.gather(..., return_exceptions=True)` existente.

De esta forma el puerto 8443 arranca de forma confiable; el bug previo (llamar `signal.signal()` desde un non-main thread, que lanzaba `ValueError` y dejaba el server silenciosamente caído) queda eliminado. Un fallo de arranque del listener MUST ser visible en los logs en lugar de quedar silenciado.

#### Scenario: Conexión mTLS exitosa
- **WHEN** un agente con certificado válido emitido por la CA se conecta al puerto 8443
- **THEN** el handshake mTLS completa y la solicitud HTTP llega al handler de FastAPI

#### Scenario: Conexión sin certificado rechazada
- **WHEN** un cliente intenta conectar al puerto 8443 sin presentar certificado de cliente
- **THEN** el handshake TLS falla con `SSL_ERROR_NO_CERTIFICATE`

#### Scenario: La API de la consola no se sirve por 8443
- **WHEN** un agente con certificado válido hace `GET /events` o `POST /agents/bootstrap` contra el puerto 8443
- **THEN** la respuesta es 404 o 405

#### Scenario: El listener 8443 arranca como task de lifespan en el loop principal
- **WHEN** el backend completa su startup con certificados disponibles
- **THEN** el puerto 8443 queda escuchando
- **AND** el servidor mTLS corre como una `asyncio` task sobre el event loop principal (sin thread secundario)
- **AND** no se lanza `ValueError` por `signal.signal()` en un non-main thread

#### Scenario: El listener 8443 se cancela limpiamente en shutdown
- **WHEN** el backend recibe la señal de shutdown
- **THEN** la task del servidor mTLS se cancela junto a las demás tasks de lifespan
- **AND** el shutdown completa sin excepciones no controladas (gather con `return_exceptions=True`)

#### Scenario: Fallo de arranque del listener es visible
- **WHEN** el servidor mTLS no puede arrancar (por ejemplo, el puerto 8443 ya está en uso)
- **THEN** el error queda registrado en los logs
- **AND** el fallo no se silencia

## ADDED Requirements

### Requirement: SAN del certificado de servidor del backend desde `FIM_PUBLIC_HOSTS` (D53/RN-147)

`Settings` SHALL exponer `fim_public_hosts: str` con default `""`, leído de `FIM_PUBLIC_HOSTS`: lista separada por comas, con espacios recortados y entradas vacías ignoradas. Cada entrada que parsea como dirección IP (IPv4 o IPv6) SHALL emitirse como `IPAddress`; cualquier otra SHALL ser un nombre DNS válido (etiquetas RFC 1123, sin comodines) y emitirse como `DNSName`. Una entrada que no es ninguna de las dos SHALL abortar el arranque con un mensaje que la nombre.

El SAN requerido del certificado de servidor del backend (listeners 8443 y 8444) SHALL ser `{backend, fim-backend, localhost}` ∪ `FIM_PUBLIC_HOSTS`. Si el certificado existente carece de `AuthorityKeyIdentifier`, si su SAN no cubre el conjunto requerido —nombres DNS comparados sin distinguir mayúsculas, IPs comparadas en forma normalizada— o si le quedan menos de `_CERT_RENEWAL_THRESHOLD_DAYS` (15) días de vigencia (D61/RN-155), SHALL reemitirse con la misma CA, conservando la clave privada existente. Si nada de eso ocurre, SHALL NOT tocarse. La reemisión sólo ocurre al arrancar; la CA no se rota. El cálculo SHALL ser una función pura compartida por `certs-init` y por el lifespan del backend, de modo que ninguno de los dos pueda emitir un SAN menor que el otro. SHALL NOT existir una configuración que desactive la verificación de hostname en ningún cliente (RN-114).

#### Scenario: Sin hosts públicos
- **WHEN** `FIM_PUBLIC_HOSTS` está vacía
- **THEN** el SAN del certificado del backend contiene exactamente `backend`, `fim-backend` y `localhost` como `DNSName`

#### Scenario: IP y nombre DNS
- **WHEN** `FIM_PUBLIC_HOSTS=203.0.113.10, fim.example.org`
- **THEN** el SAN contiene `IPAddress(203.0.113.10)` y `DNSName(fim.example.org)` además de los nombres internos
- **AND** `203.0.113.10` no aparece como `DNSName`

#### Scenario: Certificado que ya cubre el conjunto
- **WHEN** el certificado existente cubre el SAN requerido
- **THEN** el archivo no se reescribe y su número de serie no cambia

#### Scenario: Host nuevo agregado
- **WHEN** se agrega una entrada a `FIM_PUBLIC_HOSTS` y se reinicia el stack
- **THEN** el certificado se reemite firmado por la misma CA, con la misma clave pública y con el SAN ampliado

#### Scenario: Certificado próximo a vencer
- **WHEN** el certificado del backend cubre el SAN requerido pero le quedan 10 días de vigencia y el stack arranca
- **THEN** se reemite firmado por la misma CA, con la misma clave pública y una vigencia nueva

#### Scenario: Entrada inválida
- **WHEN** `FIM_PUBLIC_HOSTS` contiene `bad_host!`
- **THEN** el cálculo falla con un error que nombra `bad_host!` y no se escribe ningún certificado

#### Scenario: Verificación de hostname contra una IP
- **WHEN** un cliente TLS con `ca.pem` como ancla y verificación de hostname activa conecta a `https://203.0.113.10:8444` con `FIM_PUBLIC_HOSTS=203.0.113.10`
- **THEN** el handshake completa sin mapear nombres en `/etc/hosts`

### Requirement: Certificado de servidor de Valkey emitido automáticamente (D53/RN-147)

`certs-init` SHALL emitir el certificado de servidor de Valkey firmado por la CA propia, con `CN=valkey`, SAN `{valkey, localhost}` ∪ `FIM_PUBLIC_HOSTS` (misma regla IP/DNS), `BasicConstraints(ca=False)` crítica, `AuthorityKeyIdentifier` y EKU `serverAuth` y `clientAuth` (el segundo lo usa el healthcheck de Valkey para autenticarse ante sí mismo). SHALL aplicar el mismo criterio idempotente que el certificado del backend. SHALL escribirlo, junto con su clave y una copia de `ca.pem`, en el volumen de material TLS de Valkey, que SHALL NOT contener la clave privada de la CA. La emisión manual con `scripts/emitir_cert_valkey.py` deja de ser un paso del despliegue.

#### Scenario: Emisión en arranque limpio
- **WHEN** `certs-init` corre sin certificado de Valkey previo
- **THEN** existen el certificado y la clave de Valkey en su volumen, con el SAN requerido

#### Scenario: Verificación estricta de Python 3.13
- **WHEN** un cliente creado con `ssl.create_default_context()` de Python 3.13 verifica el certificado de Valkey contra `ca.pem`
- **THEN** la verificación no falla por ausencia de `AuthorityKeyIdentifier`

#### Scenario: Idempotencia
- **WHEN** `certs-init` corre con un certificado de Valkey que ya cubre el SAN requerido
- **THEN** el certificado no se reescribe

### Requirement: Certificado de cliente del backend ante Valkey (D53/RN-147)

`certs-init` SHALL emitir un certificado de cliente propio del backend ante Valkey, firmado por la CA propia, con `CN=fim-backend-valkey`, EKU únicamente `clientAuth`, `AuthorityKeyIdentifier` y sin SAN. SHALL escribirlo en el volumen de certificados del backend con la clave privada en modo `0400`, legible sólo por el usuario del backend. SHALL reemitirse si falta, si su perfil no cumple lo anterior o si le quedan menos de `_CERT_RENEWAL_THRESHOLD_DAYS` (15) días de vigencia (D61/RN-155). El backend SHALL NOT autenticarse ante Valkey con `backend.pem` (sólo `serverAuth`) ni con el certificado del servidor Valkey.

#### Scenario: Emisión en arranque limpio
- **WHEN** `certs-init` corre sin certificado de cliente previo
- **THEN** existe un certificado con `CN=fim-backend-valkey` y EKU `clientAuth`, sin `serverAuth`

#### Scenario: Valkey acepta al backend
- **WHEN** el backend conecta a Valkey TLS con `--tls-auth-clients yes` usando ese certificado
- **THEN** la conexión se establece y `PING` responde

### Requirement: Listener de bootstrap TLS en el puerto 8444 (D52/RN-146)

El backend SHALL exponer un listener en el puerto 8444 que presenta el certificado de servidor del backend, con TLS 1.3 como versión mínima y sin exigir certificado de cliente (`ssl.CERT_NONE`), que sirve exclusivamente la aplicación de bootstrap (`POST /agents/bootstrap`). `start_bootstrap_server(...)` SHALL seguir el mismo contrato que `start_mtls_server`: retornar `None` si los certificados no están disponibles, sin signal handlers propios, arrancado y cancelado como task de lifespan. La aplicación principal servida en 8000 SHALL NOT montar `POST /agents/bootstrap`.

#### Scenario: Handshake sin certificado de cliente
- **WHEN** un cliente sin certificado propio conecta al puerto 8444 verificando contra `ca.pem`
- **THEN** el handshake TLS 1.3 completa y el servidor presenta `CN=fim-backend`

#### Scenario: Versión de TLS inferior rechazada
- **WHEN** un cliente intenta negociar TLS 1.2 contra el puerto 8444
- **THEN** el handshake falla

#### Scenario: Bootstrap ausente del puerto 8000
- **WHEN** se hace `POST http://backend:8000/agents/bootstrap`
- **THEN** la respuesta es 404 o 405

### Requirement: Certificado autofirmado de la consola (D55/RN-149, D61/RN-155, D62/RN-156)

Sólo con `CONSOLE_TLS_MODE=self_signed`, `certs-init` SHALL emitir el certificado de servidor de la consola como certificado **autofirmado** con clave ECDSA P-256 y firma ECDSA-SHA256, con SAN `{localhost}` ∪ `FIM_PUBLIC_HOSTS` (misma regla IP/DNS que el certificado del backend), `BasicConstraints(ca=False)` crítica y EKU únicamente `serverAuth`. SHALL NOT firmarse con la CA propia ni usar Ed25519, porque los navegadores no aceptan Ed25519 en TLS (D62/RN-156). `certs-init` SHALL registrar su huella SHA-256. SHALL escribirlo, junto con su clave, en el volumen del certificado generado de la consola, que SHALL NOT contener la clave privada de la CA. SHALL reemitirse si falta, si su SAN no cubre el conjunto requerido o si le quedan menos de `_CERT_RENEWAL_THRESHOLD_DAYS` (15) días de vigencia; en otro caso SHALL NOT tocarse. En los modos `off` y `provided` SHALL NOT emitirse.

#### Scenario: Emisión en modo autofirmado
- **WHEN** `certs-init` corre con `CONSOLE_TLS_MODE=self_signed` y `FIM_PUBLIC_HOSTS=203.0.113.10`
- **THEN** el volumen de la consola contiene un certificado autofirmado con clave ECDSA P-256, emisor igual al sujeto, `IPAddress(203.0.113.10)` y `DNSName(localhost)` en el SAN y EKU `serverAuth`
- **AND** un navegador Chromium completa la navegación a `https://203.0.113.10/` tras aceptar el certificado no confiable, sin `ERR_SSL_VERSION_OR_CIPHER_MISMATCH`
- **AND** ese volumen no contiene `ca-key.pem`

#### Scenario: Sin emisión fuera del modo autofirmado
- **WHEN** `certs-init` corre con `CONSOLE_TLS_MODE=off` o `CONSOLE_TLS_MODE=provided`
- **THEN** no se emite ningún certificado de consola

#### Scenario: Idempotencia y vencimiento
- **WHEN** `certs-init` corre con un certificado de consola que cubre el SAN y vence en 60 días
- **THEN** el archivo no se reescribe y su número de serie no cambia
- **AND** si el mismo certificado vence en 10 días, se reemite
