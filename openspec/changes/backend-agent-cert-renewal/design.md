## Context

El lado del agente está completo y es robusto. `_cert_renewal_loop` (`agent/__main__.py:40-120`):

1. Duerme `cert_renewal_check_interval_h`, interrumpible por `stop_event`.
2. Lee el certificado, calcula `days_left` contra `not_valid_after_utc`.
3. Si `days_left > 15`, loguea `cert_renewal.skipped` y sigue.
4. Si no, `POST {backend_url}/agents/renew` con cliente mTLS y body `{"agent_id": ...}`.
5. Ante status ≠ 200, loguea `cert_renewal.backend_error` y **continúa el loop** (RN-111/D13: degrada, no interrumpe).
6. Con 200: lee `data["cert_pem"]` y `data.get("ca_cert_pem", <ca local>)`, carga su **clave privada existente** y llama `bootstrap.verify_cert(new_cert_pem, ca_cert_pem, agent_id, private_key=agent_key)`.
7. Escribe atómicamente con `O_CREAT|O_WRONLY|O_TRUNC`, modo `0600`, `fsync` y `os.replace`.

Falta la contraparte. El backend tiene la maquinaria de PKI (`core/pki.py`: `ensure_ca`, `issue_certificate`, `start_mtls_server` con `CERT_REQUIRED`) y el modelo `RevokedCertificate`, pero ninguna ruta de renovación.

## Goals / Non-Goals

**Goals:**

- Que un agente con certificado próximo a vencer obtenga uno nuevo sin intervención.
- Que la renovación sea imposible sin poseer la clave privada del certificado vigente.
- Que un agente revocado no pueda renovar.
- Que el contrato existente del agente funcione **sin desplegar agentes nuevos**.

**Non-Goals:**

- Cambiar el contrato que el agente ya implementa.
- Revocación automática del certificado saliente.
- Rotación proactiva iniciada por el backend, CRL, OCSP.

## Decisions

### D-1. La autenticación es el handshake mTLS, no un token en el cuerpo

**Decisión**: la identidad del solicitante se toma del **certificado cliente presentado**, no del `agent_id` del body.

El `agent_id` del cuerpo se usa sólo para **contrastar** contra el CN del certificado presentado; si no coinciden, se rechaza. Tratarlo como identidad sería un IDOR directo: cualquier agente con un certificado válido podría renovar el de otro.

**Alternativa descartada**: firmar el pedido con el `shared_secret` HMAC. Redundante — el handshake mTLS ya prueba posesión de la clave privada, que es una garantía más fuerte, y agregaría un segundo mecanismo de autenticación que mantener.

### D-2. Se emite sobre la clave pública presentada, no sobre un CSR

**Decisión**: el backend extrae la clave pública del certificado cliente del handshake y emite el nuevo certificado para **esa misma clave**.

Es forzado por el agente, y correctamente: `verify_cert(..., private_key=agent_key)` valida que el certificado recibido corresponda a la clave privada que el agente **ya tiene en disco**. Emitir para otra clave haría que el agente descarte el certificado y siga sin renovar — el mismo resultado que hoy, con más pasos.

Consecuencia: `issue_certificate(csr_pem, ...)` no sirve tal cual, porque toma un CSR. Hace falta una variante que acepte una clave pública y un subject. **No se cambia la firma existente**: `issue_certificate` la usa el bootstrap y funciona.

**Riesgo asumido**: la clave del agente no rota nunca, sólo el certificado. Es una limitación real y merece registrarse como `[open-q]` — rotar la clave exigiría que el agente genere un par nuevo y mande CSR, lo que cambia el contrato de los dos lados.

### D-3. El certificado saliente NO se revoca

**Decisión**: `POST /agents/renew` no escribe en `revoked_certificates`.

Entre que el backend responde y que el agente escribe el archivo hay E/S que puede fallar: disco lleno, permisos, un `verify_cert` que rechaza. Si el saliente ya estuviera revocado, el agente quedaría **sin ningún certificado válido** y sin canal para pedir otro — el único que tenía es el que se acaba de invalidar. La ventana de solapamiento es deliberada.

El saliente expira solo por vencimiento. Revocar de verdad es una acción administrativa distinta (agente comprometido), y ya tiene su propio camino.

### D-4. Un agente revocado no renueva, y se verifica explícitamente

**Decisión**: antes de emitir, verificar que el `agent_id` no esté `revoked` y que el número de serie presentado no esté en `revoked_certificates`.

El handshake mTLS **no alcanza**: valida la cadena contra la CA, no consulta la base. Sin este chequeo, un certificado robado sigue renovándose indefinidamente y la revocación del agente se vuelve decorativa. Es la razón por la que este endpoint es sensible: **emite credenciales**.

### D-5. La ruta vive en el listener mTLS (8443), no en la API HTTP (8000)

**Decisión**: alcanzable sólo por el puerto con `CERT_REQUIRED`.

Expuesta en 8000 no habría certificado cliente que inspeccionar, y la autenticación de D-1 sería imposible. El agente ya apunta a `cfg.backend_url`, que en su configuración es el endpoint mTLS.

## Risks / Trade-offs

**[Riesgo] Es un endpoint que emite credenciales.** Un fallo de autenticación permite renovación indefinida de un certificado comprometido.
→ D-1 (identidad del handshake, no del body) y D-4 (chequeo de revocación) son criterio de aceptación, no extras.

**[Riesgo] La clave privada del agente nunca rota.** Sólo rota el certificado.
→ Limitación declarada. Cambiarlo exige tocar el contrato de los dos lados; ver `[open-q]` 1.

**[Riesgo] Ventana de solapamiento**: dos certificados válidos para el mismo agente hasta que el saliente expire.
→ Aceptado a propósito (D-3). El costo de la alternativa es un agente que se desconecta solo y no puede volver.

**[Trade-off] El `agent_id` del body es redundante** una vez que la identidad sale del certificado.
→ Se conserva porque el agente ya lo envía, y contrastarlo contra el CN es una verificación barata que atrapa configuración cruzada.

## Migration Plan

1. Variante de emisión sobre clave pública en `core/pki.py`, sin tocar `issue_certificate`.
2. Ruta en el router de agents, montada en el listener mTLS.
3. Verificación de revocación y auditoría.
4. Test de contrato contra el cuerpo real que emite el agente.

**Rollback**: revertir el commit. El agente vuelve al comportamiento actual — 404, log, seguir —, que es exactamente donde está hoy. Ningún agente desplegado necesita cambios.

**Despliegue**: sólo backend. Un agente viejo funciona con el backend nuevo desde el primer chequeo.

## Open Questions

1. **¿Debería el agente rotar también su clave privada?** Hoy sólo rota el certificado. Rotar la clave da mejor higiene criptográfica pero exige que el agente genere un par nuevo y envíe CSR — cambio de contrato en los dos lados y despliegue coordinado.
2. **¿Qué pasa si el certificado ya venció** antes de que el loop lo renueve (agente apagado meses)? El handshake mTLS falla y el agente no puede autenticarse para renovar. Probablemente deba volver al bootstrap, pero el `bootstrap_secret` es de un solo uso y ya se consumió. **Es un camino sin salida y conviene resolverlo antes de la defensa** — es exactamente el escenario de un agente que estuvo apagado.
3. **¿El período de validez del renovado es el mismo que el del bootstrap?** `_CERT_VALIDITY_DAYS` se reutiliza; conviene confirmarlo contra RN-78.
