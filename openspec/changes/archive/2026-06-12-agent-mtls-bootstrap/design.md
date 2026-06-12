## Context

El agente FIM necesita autenticarse criptográficamente con el backend para que toda comunicación posterior sea mutuamente verificable. La autenticación por API key es vulnerable a replay y no provee identidad de host; mTLS sí. El problema del bootstrap es que el agente parte sin certificado: el canal mTLS no puede preexistir. Este change implementa el mecanismo de arranque seguro: un endpoint que acepta un CSR autenticado con un secreto de un solo uso (bootstrap_secret), emite un certificado firmado por la CA propia del backend, y entrega los secretos criptográficos que habilitan tanto los comandos firmados (shared_secret) como el baseline cifrado (master_secret).

## Goals / Non-Goals

**Goals:**
- `backend/app/core/pki.py` — CA Ed25519, emisión de certs TLS 1.3 (90 días), check de revocación
- `POST /agents/register` — admin pre-registra agente con bootstrap_secret; persiste hash Argon2id
- `POST /agents/bootstrap` — agente envía CSR + bootstrap_secret; backend verifica, emite cert + genera shared_secret/master_secret; invalida secret
- `agent/bootstrap.py` — genera par de claves Ed25519, construye CSR, llama bootstrap, persiste cert/secrets
- Servidor mTLS en puerto 8443 configurado y verificado como canal funcional
- CA cert/key persistidos en volumen Docker (`/certs/`)

**Non-Goals:**
- No Valkey Streams sobre mTLS (Change 08)
- No heartbeat ni sincronización de reglas (Change 08)
- No UI de pre-registro (Change 19)
- No cert rotation automática (fuera del MVP de esta tesis)
- No CA intermedia ni multi-CA

## Decisions

### D-PKI-01: Ed25519 para CA y certs de agentes

Ed25519 vs RSA 4096: claves 32× más pequeñas, generación 100× más rápida, y seguridad equivalente para TLS de 90 días. `cryptography` lo soporta nativamente. La CA raíz también usa Ed25519 (CA auto-firmada con validez 10 años). El CSR del agente usa Ed25519.

Alternativa descartada: RSA 4096 → sin ventaja de seguridad para este caso; solo overhead de tamaño y CPU.

### D-PKI-02: CA cert/key en volumen Docker `/certs/`

Las env vars `CA_CERT_PATH=/certs/ca.pem` y `CA_KEY_PATH=/certs/ca-key.pem` ya están declaradas en docker-compose (Change 01). `pki.py` genera la CA en `CA_KEY_PATH` al arrancar si no existe (idempotente). El volumen `backend_certs` persiste entre reinicios. El agente recibe `ca_cert` como parte de la respuesta del bootstrap y lo guarda en `/var/lib/fim-agent/certs/ca.pem`.

### D-PKI-03: Bootstrap en puerto 8000; mTLS en 8443

El endpoint `/agents/bootstrap` y `/agents/register` corren sobre el listener estándar (puerto 8000, sin client cert requerido) porque el agente no tiene cert aún. Después del bootstrap, el backend expone un segundo listener uvicorn en puerto 8443 configurado con `ssl_cert_reqs=CERT_REQUIRED` y `ssl_ca_certs=ca.pem`. Este listener arranca como tarea asyncio en el lifespan junto al app principal.

Alternativa descartada: un solo puerto con `ssl_verify_mode=CERT_OPTIONAL` y lógica por ruta → complejo, fácil de misconfigurар.

### D-PKI-04: Verificación Argon2id en lugar de HMAC del CSR

El campo `bootstrap_secret_hash` (Change 03) almacena el hash Argon2id del secreto, no el secreto en plaintext. Verificar HMAC requeriría el secreto original, imposible con solo el hash. **Decisión**: el agente envía `{agent_id, csr_pem, bootstrap_secret (plaintext)}` en el POST body (sobre HTTPS, en tránsito protegido por TLS). El backend verifica `Argon2id.verify(bootstrap_secret, stored_hash)`. Si válido, firma el CSR; invalida el hash (→ `None`). No hay HMAC separado del CSR — la verificación Argon2id + el single-use del secreto + TLS proveen garantías equivalentes.

La mención de "HMAC" en RN-78 y CHANGES.md era un diseño anterior que asumía almacenamiento en plaintext; la decisión de Change 03 de usar Argon2id es correcta y prevalece (los appendices prevalecen sobre el contenido previo per CLAUDE.md).

### D-PKI-05: shared_secret y master_secret generados en el backend

En el momento del bootstrap, el backend genera:
- `shared_secret`: 32 bytes random — para HMAC de comandos (RN-79)
- `master_secret`: 32 bytes random — para derivación de clave de baseline (RN-82)

Ambos se retornan en el response body (sobre HTTPS). El agente los persiste en `/var/lib/fim-agent/secrets/` con `0400`. El backend NO los almacena: son entregados una sola vez; si el agente los pierde, debe re-bootstrap.

### D-PKI-06: httpx para el bootstrap del agente (one-shot, pre-mTLS)

El agente usa `httpx` (cliente HTTP sync) para el bootstrap, que ocurre antes de que exista mTLS. Es el único caso en que el agente hace HTTP directo. Después del bootstrap, toda la comunicación pasa por Valkey Streams sobre el canal mTLS (Changes 07/08). `httpx` se agrega a `agent/requirements.txt`.

## Risks / Trade-offs

[CA key en volumen Docker es un punto único de falla] → Para el MVP de tesis (single-instance backend, RN-76) es aceptable. Un compromiso del volumen expone la CA. Mitigación: permisos `0400` en el container.

[bootstrap_secret enviado en plaintext en el body] → Protegido por TLS en tránsito. Single-use (se invalida post-uso). Ventana de exposición mínima.

[shared_secret y master_secret solo se entregan una vez] → Si el agente pierde el disco, debe re-bootstrap. Para MVP es aceptable. Mitigación: backup de `/var/lib/fim-agent/secrets/` en procedimiento operacional.

[Listener mTLS en 8443 como tarea asyncio] → uvicorn no expone API nativa para multi-port. Se usa `asyncio.start_server` con un handler que delega al app de FastAPI, o se lanza un segundo uvicorn config en background thread. Esto se documenta en el código con comentario.
