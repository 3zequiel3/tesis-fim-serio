## 1. Actualizar dependencias

- [x] 1.1 Agregar `httpx` a `agent/requirements.txt` (cliente HTTP para bootstrap pre-mTLS)
- [x] 1.2 Verificar que `cryptography==44.0.2` ya está en `backend/requirements.txt` (ya presente desde Change 02 — confirmar)

## 2. Backend — PKI core (`backend/app/core/pki.py`)

- [x] 2.1 Crear `backend/app/core/pki.py` con función `ensure_ca(cert_path, key_path)`: genera CA Ed25519 auto-firmada (validez 10 años) si no existe; idempotente
- [x] 2.2 Implementar `issue_certificate(csr_pem: str, ca_cert_path, ca_key_path) -> str`: carga CSR, firma con CA Ed25519, validez 90 días, extensiones `digitalSignature` + `clientAuth`, retorna PEM
- [x] 2.3 Implementar `is_revoked(serial: int, session: Session) -> bool`: consulta tabla `revoked_certificates` por serial
- [x] 2.4 Agregar llamada a `ensure_ca()` en el lifespan de `backend/app/main.py` (antes de `create_all` + `seed_admin`)

## 3. Backend — Servidor mTLS en 8443

- [x] 3.1 Crear función `start_mtls_server(app, ca_cert_path, cert_path, key_path)` en `backend/app/core/pki.py`: arranca un servidor uvicorn en puerto 8443 con `ssl_certfile`, `ssl_keyfile`, `ssl_ca_certs`, `ssl_cert_reqs=CERT_REQUIRED`
- [x] 3.2 Lanzar `start_mtls_server` como tarea asyncio en el lifespan del backend (después de `ensure_ca`)
- [x] 3.3 Agregar a `.env.example`: `BACKEND_CERT_PATH`, `BACKEND_KEY_PATH` (cert/key del propio backend para el listener mTLS)
- [x] 3.4 Generar cert del backend firmado por la CA (auto-bootstrap) en `ensure_ca()` si no existe `BACKEND_CERT_PATH`

## 4. Backend — Módulo agents (`backend/app/modules/agents/`)

- [x] 4.1 Crear `backend/app/modules/agents/__init__.py` vacío
- [x] 4.2 Crear `backend/app/modules/agents/models.py` con schema Pydantic `AgentRegisterRequest(agent_id, bootstrap_secret)` y `AgentBootstrapRequest(agent_id, csr_pem, bootstrap_secret)` y `AgentBootstrapResponse(cert_pem, ca_cert_pem, shared_secret_hex, master_secret_hex)`
- [x] 4.3 Crear `backend/app/modules/agents/service.py` con `register_agent(req, session)` y `bootstrap_agent(req, session, pki_config) -> AgentBootstrapResponse`
  - `register_agent`: valida longitud de `bootstrap_secret` (≥ 16 chars), hashea Argon2id, persiste Agent con status=offline
  - `bootstrap_agent`: verifica Argon2id hash, valida CSR (Ed25519, CN == agent_id), emite cert, genera secrets aleatorios, nulifica hash en misma transacción
- [x] 4.4 Crear `backend/app/modules/agents/router.py` con `POST /agents/register` (requiere `get_current_user` admin) y `POST /agents/bootstrap` (sin auth JWT)
- [x] 4.5 Registrar el router en `backend/app/main.py`: `app.include_router(agents_router, prefix="/agents")`

## 5. Agente — Módulo bootstrap (`agent/bootstrap.py`)

- [x] 5.1 Crear `agent/bootstrap.py` con función `is_bootstrapped(certs_dir: Path) -> bool`: retorna True si existe `agent-cert.pem` válido y no expirado
- [x] 5.2 Implementar `generate_keypair(key_path: Path) -> tuple[PrivateKey, PublicKey]`: genera Ed25519 si no existe `key_path`; persiste PEM con `0600`
- [x] 5.3 Implementar `build_csr(private_key, agent_id: str) -> str`: construye CSR PEM con CN=agent_id
- [x] 5.4 Implementar `run(config: AgentConfig, bootstrap_secret: str) -> None`:
  - llama `generate_keypair` + `build_csr`
  - POST a `{valkey_url_base}/agents/bootstrap` (derivar URL del backend desde config)
  - si 200: persiste cert/ca_cert/shared_secret/master_secret con permisos correctos
  - si error: `SystemExit(1)` con mensaje descriptivo
- [x] 5.5 Persistir archivos de secrets con permisos explícitos: `agent-cert.pem` y `ca.pem` → `0600`; `shared_secret` y `master_secret` → `0400`

## 6. Agente — Integrar bootstrap en `__main__.py`

- [x] 6.1 Agregar campo `backend_url: str` a `AgentConfig` en `agent/config.py` y al `config.yaml.example`
- [x] 6.2 En `agent/__main__.py`: antes de iniciar el loop, llamar `bootstrap.is_bootstrapped(certs_dir)` — si False, leer `FIM_BOOTSTRAP_SECRET` del entorno (SystemExit si no definida) y ejecutar `bootstrap.run(cfg, secret)`
- [x] 6.3 Verificar que el certificado no está expirado en `is_bootstrapped()` usando `cryptography.x509.load_pem_x509_certificate`

## 7. Actualizar `docker-compose.yml` (Change 01)

- [x] 7.1 Agregar variable de entorno `BACKEND_CERT_PATH=/certs/backend.pem` y `BACKEND_KEY_PATH=/certs/backend-key.pem` al servicio `backend` en `docker-compose.yml`
- [x] 7.2 Confirmar que el puerto `8443` ya está mapeado en el servicio `backend` (presente desde Change 01)

## 8. Smoke test

- [x] 8.1 `docker compose up backend` — verificar que `ensure_ca()` genera `ca.pem` y `ca-key.pem` en el volumen y el log muestra `"CA initialized"`
- [x] 8.2 `POST /agents/register` con credenciales de admin → 201; verificar que `agents` tiene la fila con `bootstrap_secret_hash` no nulo
- [x] 8.3 En un host Linux con el agente instalado (Change 05): `FIM_BOOTSTRAP_SECRET=<secret> systemctl start fim-agent` → verificar que `bootstrap.run()` completa y los 4 archivos existen con los permisos correctos
- [x] 8.4 Segundo arranque del agente → verificar que `is_bootstrapped()` retorna True y el bootstrap se omite
- [x] 8.5 Verificar canal mTLS: `openssl s_client -connect backend:8443 -cert agent-cert.pem -key agent-key.pem -CAfile ca.pem` → handshake completa sin errores
- [x] 8.6 Segundo intento de bootstrap con el mismo `bootstrap_secret` → verificar 401 del backend
- [x] 8.7 `POST /agents/bootstrap` sin `bootstrap_secret` correcto → 401
