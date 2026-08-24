## ADDED Requirements

### Requirement: POST /agents/renew emite un certificado nuevo autenticando por mTLS

El backend SHALL exponer `POST /agents/renew` en el listener mTLS (puerto 8443, `CERT_REQUIRED`). La ruta SHALL NOT ser alcanzable por la API HTTP sin certificado cliente.

La identidad del solicitante SHALL derivarse del **certificado cliente presentado en el handshake**, no del cuerpo del pedido. El `agent_id` del cuerpo SHALL contrastarse contra el CN del certificado presentado; si difieren, el pedido SHALL rechazarse con `403`.

El `bootstrap_secret` SHALL NOT aceptarse como credencial de renovación: es de un solo uso y fue consumido en el bootstrap.

El contrato SHALL respetar lo que el agente ya implementa (`agent/__main__.py`):
- Petición: `{"agent_id": "<id>"}`
- Respuesta `200`: `{"cert_pem": "<PEM>", "ca_cert_pem": "<PEM>"}` — `ca_cert_pem` es opcional para el agente, que cae a su CA local si falta.

#### Scenario: Renovación exitosa
- **WHEN** un agente presenta un certificado válido emitido por la CA propia, no vencido y no revocado
- **AND** el `agent_id` del cuerpo coincide con el CN del certificado
- **THEN** la respuesta es `200` con `cert_pem` de un certificado firmado por la CA
- **AND** el certificado emitido tiene un número de serie distinto al presentado

#### Scenario: Sin certificado cliente
- **WHEN** se invoca el endpoint sin presentar certificado cliente
- **THEN** el handshake TLS falla y no se emite ningún certificado

#### Scenario: agent_id del cuerpo no coincide con el certificado
- **WHEN** un agente presenta el certificado de `agent-a` y envía `{"agent_id": "agent-b"}`
- **THEN** la respuesta es `403` y no se emite ningún certificado
- **AND** queda registro del intento

#### Scenario: bootstrap_secret rechazado
- **WHEN** se intenta renovar presentando `bootstrap_secret` en lugar de un certificado cliente
- **THEN** no se emite ningún certificado

---

### Requirement: El certificado se emite sobre la clave pública presentada

El backend SHALL extraer la clave pública del certificado cliente del handshake y emitir el nuevo certificado **para esa misma clave**. SHALL NOT generar un par de claves nuevo ni exigir un CSR.

El motivo es un contrato ya implementado: el agente verifica el certificado recibido contra su **clave privada existente** (`bootstrap.verify_cert(..., private_key=agent_key)`). Un certificado emitido para otra clave sería descartado por el agente, que seguiría sin renovar.

Consecuencia declarada: la **clave privada del agente no rota** — sólo rota el certificado.

#### Scenario: La clave pública se preserva
- **WHEN** se renueva el certificado de un agente
- **THEN** la clave pública del certificado emitido es idéntica a la del certificado presentado
- **AND** el agente puede verificar el binding contra su clave privada existente sin regenerarla

#### Scenario: No se exige CSR
- **WHEN** el agente envía únicamente `{"agent_id": "<id>"}` sin CSR
- **THEN** la renovación procede normalmente

---

### Requirement: Un agente revocado no puede renovar

Antes de emitir, el backend SHALL verificar que el agente no esté en estado `revoked` y que el número de serie del certificado presentado no figure en `revoked_certificates`. Si alguna condición se cumple, SHALL responder `403` sin emitir.

El handshake mTLS **no alcanza** para esto: valida la cadena contra la CA, no consulta la base. Sin esta verificación un certificado robado se renueva indefinidamente y la revocación del agente queda sin efecto práctico.

#### Scenario: Agente en estado revoked
- **WHEN** un agente cuyo `status == revoked` presenta un certificado aún válido y pide renovar
- **THEN** la respuesta es `403` y no se emite certificado

#### Scenario: Número de serie revocado
- **WHEN** el certificado presentado tiene un serial que figura en `revoked_certificates`
- **THEN** la respuesta es `403` y no se emite certificado

---

### Requirement: El certificado saliente no se revoca en la renovación

La renovación SHALL NOT escribir en `revoked_certificates` ni invalidar el certificado presentado. El saliente SHALL quedar válido hasta su vencimiento natural.

Entre la respuesta del backend y la escritura del archivo por parte del agente hay E/S que puede fallar — disco lleno, permisos, un `verify_cert` que rechaza. Si el saliente ya estuviera revocado, el agente quedaría sin ningún certificado válido **y sin canal para pedir otro**, porque el único que tenía es el que se acaba de invalidar. La ventana de solapamiento es deliberada.

Revocar un certificado sigue siendo una acción administrativa por su propio camino (agente comprometido).

#### Scenario: El saliente sigue sirviendo tras la renovación
- **WHEN** un agente renueva su certificado exitosamente
- **AND** falla al escribir el nuevo en disco
- **THEN** el certificado anterior sigue autenticando contra el backend
- **AND** el agente puede reintentar en el siguiente ciclo

#### Scenario: La renovación no escribe en revoked_certificates
- **WHEN** se completa una renovación
- **THEN** la tabla `revoked_certificates` no tiene filas nuevas

---

### Requirement: Toda renovación queda auditada

Cada renovación exitosa SHALL registrarse en `audit_log` (RN-94) con el `agent_id`, el número de serie del certificado saliente y el del entrante. Los intentos rechazados SHALL registrarse con el motivo.

Un endpoint que emite credenciales sin dejar rastro impide reconstruir qué certificados existen y por qué.

#### Scenario: Renovación exitosa auditada
- **WHEN** un agente renueva su certificado
- **THEN** existe una entrada en `audit_log` con el `agent_id` y ambos números de serie

#### Scenario: Rechazo auditado
- **WHEN** una solicitud de renovación es rechazada por revocación o por CN discordante
- **THEN** existe una entrada en `audit_log` con el motivo del rechazo

---

### Requirement: Test de contrato entre el loop del agente y el endpoint

La suite SHALL incluir un test que verifique que el cuerpo que emite `_cert_renewal_loop` es aceptado por el schema del endpoint, y que la respuesta del endpoint contiene las claves que el agente consume (`cert_pem`, y `ca_cert_pem` cuando esté presente).

El test SHALL incluir un caso negativo: una respuesta sin `cert_pem` SHALL hacerlo fallar. Sin eso, vaciar el contrato dejaría el test en verde verificando nada.

Este endpoint es precisamente el caso de un contrato con **dos implementaciones y cero aserciones compartidas** — que es cómo llegó a existir de un solo lado.

#### Scenario: El cuerpo del agente es aceptado
- **WHEN** se envía al endpoint el cuerpo exacto que construye `_cert_renewal_loop`
- **THEN** el schema lo acepta sin error de validación

#### Scenario: La respuesta contiene lo que el agente consume
- **WHEN** el endpoint responde `200`
- **THEN** el cuerpo contiene `cert_pem`
- **AND** el acceso `data["cert_pem"]` que hace el agente no levanta `KeyError`

#### Scenario: Caso negativo — respuesta sin cert_pem
- **WHEN** el endpoint devuelve un cuerpo sin la clave `cert_pem`
- **THEN** el test de contrato falla
