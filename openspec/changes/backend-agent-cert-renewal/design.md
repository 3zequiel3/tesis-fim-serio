## Context

El lado del agente está completo y es robusto. `_cert_renewal_loop` (`agent/__main__.py:40-120`):

1. Duerme `cert_renewal_check_interval_h`, interrumpible por `stop_event`.
2. Lee el certificado, calcula `days_left` contra `not_valid_after_utc`.
3. Si `days_left > 15`, loguea `cert_renewal.skipped` y sigue.
4. Si no, `POST {backend_url}/agents/renew` con cliente mTLS y body `{"agent_id": ...}`.
5. Ante status ≠ 200, loguea `cert_renewal.backend_error` y **continúa el loop** (RN-111/D13: degrada, no interrumpe).
6. Con 200: lee `data["cert_pem"]` y `data.get("ca_cert_pem", <ca local>)`, carga su **clave privada existente** y llama `bootstrap.verify_cert(new_cert_pem, ca_cert_pem, agent_id, private_key=agent_key)`.
7. Escribe atómicamente con `O_CREAT|O_WRONLY|O_TRUNC`, modo `0600`, `fsync` y `os.replace`.

Falta la contraparte. El backend tiene la maquinaria de PKI (`core/pki.py`: `ensure_ca`, `issue_certificate`, `start_mtls_server`) y el modelo `RevokedCertificate`, pero ninguna ruta de renovación.

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

**Decisión**: alcanzable sólo por el puerto mTLS, nunca por la API HTTP de 8000.

Expuesta en 8000 no habría certificado cliente que inspeccionar, y la autenticación de D-1 sería imposible. El agente ya apunta a `cfg.backend_url`, que en su configuración es el endpoint mTLS.

### D-6. Ventana de gracia para certificados vencidos — y por qué relajar TLS no relaja la autenticación

**El problema que resuelve.** Un agente apagado el tiempo suficiente pierde el certificado por vencimiento, y entonces queda **sin ningún camino de vuelta**, verificado contra el código:

| Camino | Resultado |
|---|---|
| Renovar | El handshake mTLS rechaza el certificado vencido |
| Re-bootstrapear | `bootstrap_secret_hash` es `None` — `bootstrap_agent` lo destruye al consumirlo (`service.py:80`) → `401` |
| Re-registrar | `register_agent` devuelve `409` si el agente existe (`service.py:35-39`) |

La única recuperación hoy es escribir a mano en la base. Y peor: **cualquier re-bootstrap emite un `master_secret` nuevo**, del que sale por HKDF la clave AES-256-GCM del baseline. El backend no lo persiste —está sólo en `AgentBootstrapResponse`, nunca en la tabla `Agent`, porque D1 hace al agente custodio único—, así que no puede devolver el anterior. Recuperar un agente así **le destruye la línea base y su historial de integridad**.

**Decisión**: `POST /agents/renew` SHALL aceptar un certificado **vencido pero por lo demás válido**, dentro de una ventana acotada a partir de `not_valid_after`.

Un certificado vencido sigue siendo **prueba de posesión de la clave privada** — que es lo que la autenticación necesita. Lo que el vencimiento expresa es «esta credencial ya cumplió su plazo», no «quien la presenta no es quien dice ser». Lo que acota el riesgo no es la fecha sino la **verificación de revocación** (D-4), que es donde vive la decisión real sobre si esa identidad sigue siendo legítima.

**Cómo se implementa sin abrir el listener.** El riesgo que esta decisión introduce es concreto: el puerto 8443 es **compartido** por todos los endpoints mTLS, y relajarlo los relajaría a todos. La mitigación invierte el default:

1. El listener baja a `CERT_OPTIONAL` — entrega el certificado a la aplicación en lugar de rechazarlo en el handshake.
2. Una dependencia de validación **falla cerrada**: exige certificado presente, cadena válida contra la CA propia, CN coherente, **no vencido** y no revocado. Es el default de **todos** los endpoints mTLS.
3. `POST /agents/renew` es la **única** excepción, y sólo sobre el vencimiento: sigue exigiendo cadena, CN y no-revocación, y agrega el chequeo de ventana.

La relajación queda así en un solo punto explícito y auditable, en vez de repartida por omisión. Un endpoint nuevo que olvide declarar su validación queda **protegido**, no expuesto.

**Alternativa descartada**: un listener aparte en otro puerto para la renovación. Aísla mejor, pero el agente apunta a un único `cfg.backend_url` y habría que cambiar su configuración — o sea, desplegar agentes nuevos para arreglar un defecto del backend, que es justo lo que este change evita.

**Ventana propuesta: 30 días.** Con certificados de la vigencia que fija RN-78 y un umbral de renovación de 15 días antes del vencimiento, 30 días de gracia cubren un agente apagado alrededor de mes y medio. Más allá de eso la recuperación vuelve a ser una acción administrativa deliberada, que para un agente ausente meses es lo correcto: conviene que un humano se entere.

## Risks / Trade-offs

**[Riesgo] Es un endpoint que emite credenciales.** Un fallo de autenticación permite renovación indefinida de un certificado comprometido.
→ D-1 (identidad del handshake, no del body) y D-4 (chequeo de revocación) son criterio de aceptación, no extras.

**[Riesgo] La clave privada del agente nunca rota.** Sólo rota el certificado.
→ Limitación declarada. Cambiarlo exige tocar el contrato de los dos lados; ver `[open-q]` 1.

**[Riesgo] Bajar el listener a `CERT_OPTIONAL` afecta a los demás endpoints mTLS del puerto 8443.**
→ Mitigado invirtiendo el default (D-6): la dependencia de validación falla cerrada y es obligatoria para todos; `/agents/renew` es la única excepción y sólo sobre el vencimiento. Un endpoint que olvide declararla queda protegido, no expuesto. **El criterio de aceptación SHALL incluir un test que verifique que los demás endpoints mTLS siguen rechazando un certificado vencido.**

**[Riesgo] Un certificado comprometido hace tiempo puede renovarse dentro de la ventana de gracia.**
→ Lo acota la verificación de revocación (D-4), no la fecha. Si el agente fue revocado, no renueva ni dentro ni fuera de la ventana. La ventana bounded limita la exposición de un compromiso no detectado.

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
2. ~~**¿Qué pasa si el certificado ya venció?**~~ **RESUELTO por D-6**: ventana de gracia de 30 días sobre `not_valid_after`, con la relajación confinada a este endpoint mediante una dependencia que falla cerrada. Preserva el `master_secret` y por lo tanto el baseline, que es lo que un re-bootstrap habría destruido.
3. **¿El período de validez del renovado es el mismo que el del bootstrap?** `_CERT_VALIDITY_DAYS` se reutiliza; conviene confirmarlo contra RN-78.
