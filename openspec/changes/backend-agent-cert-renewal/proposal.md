## Why

**`POST /agents/renew` no existe en el backend, y el agente lo llama.**

No es un desalineamiento documental: es una funcionalidad implementada de un solo lado.

`agent/__main__.py:40-120` corre `_cert_renewal_loop`. Cada `cert_renewal_check_interval_h` horas lee su certificado, calcula `days_left`, y si faltan **≤ 15 días** arma un cliente httpx con `cert=(cert_path, key_path)` y `verify=ca_path` y hace `POST {backend_url}/agents/renew` con `{"agent_id": ...}`.

Del otro lado no hay ruta. El router de agents expone `register`, `bootstrap`, `GET /agents`, `GET /agents/{agent_id}`, `POST /agents/{agent_id}/config` y `POST /agents/{agent_id}/rescan`. Una búsqueda literal de `renew` en `backend/` no devuelve una sola ocurrencia real.

El agente recibe 404, loguea `cert_renewal.backend_error` y continúa el loop. **Los certificados de los agentes nunca se renuevan.** Pasada la vigencia que fija RN-78, el agente pierde el canal mTLS y deja de poder publicar eventos. Hasta ese momento la falla es silenciosa: un warning periódico en un log que nadie mira, y después un agente que se cae solo.

**Por qué no se detectó antes**: `agent-cert-renewal` era una de las 29 specs truncadas por archives defectuosos. Sus requisitos —incluido el que define este endpoint— eran **invisibles** para `validate`, `list` y `archive`. Nadie podía contrastarlos contra el código aunque hubiera querido. Apareció al recuperarlas y barrer los 244 requisitos.

## What Changes

- **`POST /agents/renew`**, autenticado por **mTLS con el certificado del propio agente** — vigente, o vencido dentro de una ventana de gracia de 30 días (D48/RN-142). La prueba de identidad es el handshake: quien presenta un certificado válido emitido por la CA propia y no revocado, es el agente.
- **Emisión para la MISMA clave pública.** El agente **no envía CSR** — envía sólo `{"agent_id": ...}` — y después verifica el certificado recibido contra su **clave privada existente** (`bootstrap.verify_cert(..., private_key=agent_key)`). El backend SHALL tomar la clave pública del certificado cliente presentado en el handshake. Emitir para otra clave rompería esa verificación y el agente descartaría el certificado.
- **`bootstrap_secret` NO sirve para renovar.** Es de un solo uso y ya fue consumido en el bootstrap (prohibición explícita de la spec `agent-cert-renewal`).
- **El certificado anterior NO se revoca automáticamente.** El agente necesita seguir operando hasta escribir y recargar el nuevo. Revocar antes abre una ventana en la que el agente no puede hablar con nadie — y su único canal para pedir ayuda es justamente el que se acaba de cerrar.
- **Auditoría** en `audit_log` (RN-94) con `agent_id` y los números de serie saliente y entrante.
- **Test de contrato agente↔backend**: el cuerpo que emite `_cert_renewal_loop` y la forma que consume (`data["cert_pem"]`, `data.get("ca_cert_pem")`) verificados contra el schema real del endpoint, con caso negativo obligatorio.

- **Ventana de gracia de 30 días** sobre `not_valid_after` (D48/RN-142). Sin ella un agente apagado el tiempo suficiente queda **sin camino de vuelta**: no renueva (handshake), no re-bootstrapea (`bootstrap_secret_hash = None`, `401`), no se re-registra (`409`). Y forzar un re-bootstrap emitiría un `master_secret` nuevo — que el backend **no persiste**, por D1 — destruyendo el baseline cifrado del agente y su historial de integridad.

**Fuera de alcance**: cambiar el contrato que el agente ya implementa; rotación proactiva iniciada por el backend; revocación automática del certificado saliente; CRL o OCSP; rotación de la clave privada del agente.

## Capabilities

### New Capabilities
- `backend-cert-renewal`: el endpoint de renovación, su autenticación por mTLS, la regla de emisión sobre la clave presentada y la política de no-revocación del certificado saliente.

### Modified Capabilities
Ninguna. `agent-cert-renewal` ya especifica el lado del agente y **no cambia**: este change implementa la contraparte que esa spec siempre asumió existente.

## Impact

**Código**: `backend/app/modules/agents/router.py` (ruta nueva), `backend/app/core/pki.py` (emisión sobre clave pública en lugar de CSR — hoy `issue_certificate` sólo acepta CSR), `backend/app/modules/agents/service.py`.

**Tests**: contrato agente↔backend, más los casos de autenticación.

**Sin impacto en el agente**: su lado está completo. Tocarlo obligaría a desplegar agentes nuevos para arreglar un defecto del backend.

**Riesgo principal**: es un endpoint que **emite credenciales**. Un fallo de autenticación acá permite a un atacante con un certificado de agente comprometido renovarlo indefinidamente, incluso después de que el agente sea revocado. Por eso la verificación contra `revoked_certificates` es parte del criterio de aceptación, no un extra.

**Riesgo secundario**: el listener baja de `CERT_REQUIRED` a `CERT_OPTIONAL` para poder aplicar la ventana de gracia (D-6), y ese puerto es **compartido** por todos los endpoints mTLS. Se mitiga invirtiendo el default: una dependencia de validación que **falla cerrada** pasa a ser obligatoria para todos, y `/agents/renew` es la única excepción, sólo sobre el vencimiento. **El criterio de aceptación incluye un test de no-regresión**: los demás endpoints mTLS siguen rechazando un certificado vencido.

**Reglas cubiertas**: RN-78 (rotación de certificados), RN-111 y D13 (la falla de renovación degrada, no interrumpe — ya cumplido del lado del agente), RN-94 (auditoría).
