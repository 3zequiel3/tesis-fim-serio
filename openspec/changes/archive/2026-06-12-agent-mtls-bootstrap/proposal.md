## Why

El agente FIM no puede autenticarse con API keys: requiere identidad criptográfica para resistir replay attacks e identificación unívoca por host. Este change implementa el bootstrap mTLS completo — el mecanismo por el cual un agente sin certificado previo obtiene uno firmado por la CA propia del backend, y a partir de ese momento todo el canal agente↔backend corre sobre TLS 1.3 mutuo. Sin este change, ningún módulo de comunicación (Valkey Streams, heartbeat, comandos) puede establecerse de forma segura.

## What Changes

- **Backend — PKI propia**: `backend/app/core/pki.py` — CA (Ed25519), emisión TLS 1.3 con validez 90 días, revocación contra tabla `revoked_certificates`, rotación 15 días antes de expirar
- **Backend — Endpoints de agentes**: `backend/app/modules/agents/` — `POST /agents/register` (admin pre-registra `{agent_id, bootstrap_secret}`), `POST /agents/bootstrap` (agente envía CSR + HMAC, recibe cert + `shared_secret` + `master_secret`; invalida `bootstrap_secret`)
- **Agente — Bootstrap**: `agent/bootstrap.py` — genera par de claves Ed25519, construye CSR, firma HMAC-SHA256 con `bootstrap_secret`, llama `POST /agents/bootstrap`, persiste cert/secrets con permisos `0600`/`0400`
- **Agente — Arranque condicional**: `agent/__main__.py` comprueba si ya existe cert válido antes de arrancar el loop principal; si no, ejecuta bootstrap

## Capabilities

### New Capabilities

- `backend-pki`: CA propia del backend — generación de CA raíz Ed25519, emisión de certificados TLS 1.3 para agentes, consulta de revocación, rotación automática
- `backend-agents`: Endpoints de registro y bootstrap de agentes — `POST /agents/register` y `POST /agents/bootstrap`, incluyendo validación HMAC, emisión de cert, generación de `shared_secret`/`master_secret`, invalidación de `bootstrap_secret`
- `agent-bootstrap`: Bootstrap del agente FIM — generación de par de claves, CSR, firma HMAC, obtención de cert desde backend, persistencia en `/var/lib/fim-agent/{certs,secrets}/`

### Modified Capabilities

*(ninguna — las requirements existentes no cambian; el arranque condicional es implementación)*

## Impact

- **Nuevos archivos backend**: `backend/app/core/pki.py`, `backend/app/modules/agents/__init__.py`, `backend/app/modules/agents/router.py`, `backend/app/modules/agents/models.py`, `backend/app/modules/agents/service.py`
- **Nuevo archivo agente**: `agent/bootstrap.py`
- **Modificado**: `agent/__main__.py` (comprueba cert antes de iniciar loop), `backend/app/main.py` (incluye router de agents)
- **Modelo DB existente**: tabla `agents` (campo `bootstrap_secret_hash`, `revoked_certificates`) ya provisionada en Change 03 — no requiere migraciones
- **Dependencias**: `cryptography==44.0.2` (ya en requirements de backend y agente); `httpx` se agrega al agente para el bootstrap HTTP antes de que exista mTLS
- **Puerto**: `8443` expuesto en Docker Compose (ya declarado en Change 01) para canal mTLS; el bootstrap usa `8000` (HTTP plain) porque aún no hay cert
- **Reglas cubiertas**: RN-63, RN-64, RN-78, RN-79, RN-82
