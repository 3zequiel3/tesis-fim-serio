# CHANGES.md — Roadmap de implementación FIM Platform

Este documento define la **secuencia ordenada de changes** (en sentido OpenSpec) para construir el sistema FIM Platform desde cero. Cada change representa una slice coherente con proposal/spec/tasks que entrega capacidad verificable y depende explícitamente de changes anteriores.

**Fuentes canónicas** (leídas para producir este roadmap):
- [docs/arquitectura_stack.md](docs/arquitectura_stack.md) — stack técnico, modelo de eventos, decision engine, baseline
- [docs/flujo_de_usuario.md](docs/flujo_de_usuario.md) — flujos UI/UX
- [docs/historias_de_usuario.md](docs/historias_de_usuario.md) — historias priorizadas
- [docs/reglas_de_negocio.md](docs/reglas_de_negocio.md) — 16 dominios, ~103 reglas

**Estado actual**: backend/, agent/, frontend/ vacíos. Documentación 100% terminada y validada (33 decisiones de auditoría + 10 decisiones de diseño + **28 decisiones de implementación** aplicadas en D1–D28).

**Decisiones de implementación cerradas (2026-04-24)**: las 8 suposiciones que estaban abiertas en una versión anterior de este roadmap fueron resueltas y documentadas en los appendices "Decisiones de implementación — Abril 2026" de [docs/reglas_de_negocio.md](docs/reglas_de_negocio.md) y [docs/arquitectura_stack.md](docs/arquitectura_stack.md). Este roadmap ya las incorpora.

**Principio de orden**: domain contracts + core integration loop (agent + backend + persistencia) PRIMERO; frontend al final, sobre API estable.

**Cross-cutting distribuido**: logging sanitizado, rate limiting y `trace_id` se introducen en el primer change que los necesita (D7), no se centralizan al final.

---

## TL;DR — Tabla resumen

| # | Change ID | Capa | Hito | Depende de |
|---|-----------|------|------|------------|
| 01 | [`infra-docker-compose`](#change-01--infra-docker-compose) | infra | M1 | — |
| 02 | [`backend-core-scaffold`](#change-02--backend-core-scaffold) | backend | M1 | 01 |
| 03 | [`domain-models`](#change-03--domain-models) | backend | M1 | 02 |
| 04 | [`backend-auth`](#change-04--backend-auth) | backend | M1 | 03 |
| 05 | [`agent-core-scaffold`](#change-05--agent-core-scaffold) | agent | M2 | — (paralelo) |
| 06 | [`agent-mtls-bootstrap`](#change-06--agent-mtls-bootstrap) | cross | M2 | 02, 05 |
| 07 | [`agent-baseline-engine`](#change-07--agent-baseline-engine) | agent | M2 | 06 |
| 08 | [`valkey-streams-transport`](#change-08--valkey-streams-transport) | cross | M2 | 06, 03 |
| 09 | [`agent-fanotify-detector`](#change-09--agent-fanotify-detector) | agent | M2 | 07, 08 |
| 10 | [`agent-decision-engine`](#change-10--agent-decision-engine) | agent | M3 | 09, 07 |
| 11 | [`backend-event-ingestion`](#change-11--backend-event-ingestion) | backend | M3 | 08, 03 |
| 12 | [`backend-rules-crud`](#change-12--backend-rules-crud) | backend | M3 | 04, 08 |
| 13 | [`backend-approve-reject`](#change-13--backend-approve-reject) | backend | M3 | 11, 12, 10 |
| 14 | [`backend-agent-config`](#change-14--backend-agent-config) | cross | M3 | 13, 09 |
| 15 | [`backend-notifications`](#change-15--backend-notifications) | backend | M3 | 11 |
| 16 | [`backend-sse-alerts`](#change-16--backend-sse-alerts) | backend | M3 | 15, 04 |
| 17 | [`frontend-shell-auth`](#change-17--frontend-shell-auth) | frontend | M4 | 04, 16 |
| 18 | [`frontend-events`](#change-18--frontend-events) | frontend | M4 | 17, 13 |
| 19 | [`frontend-rules-agents-dashboard`](#change-19--frontend-rules-agents-dashboard) | frontend | M4 | 18, 14, 12 |
| 20 | [`backend-observability-hardening`](#change-20--backend-observability-hardening) | cross | M4 | 13, 15 |
| 21 | [`agent-critical-fixes`](#change-21--agent-critical-fixes) | agente | — (remediación) | 05, 13, 14 |
| 22 | [`backend-critical-fixes`](#change-22--backend-critical-fixes) | backend | — (remediación) | 02, 04, 13 |
| 23 | [`agent-high-fixes`](#change-23--agent-high-fixes) | agente | — (remediación) ✓ | 21 |
| 24 | [`agent-valkey-mtls`](#change-24--agent-valkey-mtls) | agente | — (tesis) ✓ | 23 |
| 25 | [`agent-reconnect-order`](#change-25--agent-reconnect-order) | agente | — (tesis) ✓ | 24 |
| 26 | [`agent-fanotify-and-lifecycle`](#change-26--agent-fanotify-and-lifecycle) | agente | — (tesis) ✓ | 25 |
| 27 | [`agent-stability-fixes`](#change-27--agent-stability-fixes) | agente | — (remediación) ✓ | 26 |
| 28 | [`agent-audit-fixes`](#change-28--agent-audit-fixes) | agente | — (auditoría 2026-06-26) ✓ | 27 |
| 29 | [`agent-resilience-fixes`](#change-29--agent-resilience-fixes) | agente | — (auditoría 2026-06-26) | 28 |
| 30 | [`backend-async-io-fixes`](#change-30--backend-async-io-fixes) | backend | — (auditoría 2026-06-26) | 22, 29 |
| 31 | [`backend-event-correctness`](#change-31--backend-event-correctness) | backend | — (auditoría 2026-06-26) | 30 |
| 32 | [`backend-sse-security-fixes`](#change-32--backend-sse-security-fixes) | backend | — (auditoría 2026-06-26) | 31 |
| 33 | [`backend-test-harness`](#change-33--backend-test-harness) | backend | — (remediación 2026-06-29) | 30 |
| 34 | [`backend-residual-fixes`](#change-34--backend-residual-fixes) | backend | — (auditoría 2026-06-23, residual) | 32 |
| 35 | [`e2e-contract-fixes`](#change-35--e2e-contract-fixes) | cross | — (auditoría dual-judge 2026-07-02) | 34 |
| 36 | [`backend-command-ack-consumer`](#change-36--backend-command-ack-consumer) | backend + agente | — (auditoría dual-judge 2026-07-02) | 34, 35 |
| 37 | [`agent-fanotify-scope-filter`](#change-37--agent-fanotify-scope-filter) | agente | — (auditoría dual-judge 2026-07-02) | 34, 35 |
| 38 | [`frontend-contract-fixes`](#change-38--frontend-contract-fixes) | frontend + backend | — (auditorías 2026-07-02) ✓ | 35 |
| 39 | [`agent-scope-filter-symlink-hardening`](#change-39--agent-scope-filter-symlink-hardening) | agente + backend + frontend | — (dual-review C37, 2026-07-02) | 37 |
| 40 | [`event-status-contract`](#change-40--event-status-contract) | backend + agente + frontend | — (auditoría 2026-08-13) | 38, 39 |
| 41 | [`agent-deployment-caps`](#change-41--agent-deployment-caps) | agente + backend + frontend | — (auditoría 2026-08-14) | 40 |
| 42 | [`stream-ack-durability`](#change-42--stream-ack-durability) | agente + backend + frontend | — (auditoría 2026-08-16) | 40, 41 |

---

## Mapa dominios → capacidades

| # | Dominio (RN) | Capacidades clave | Layer |
|---|--------------|-------------------|-------|
| 1 | Detección y monitoreo (RN-01–04) | fanotify; contexto de proceso; paths configurados | Agent |
| 2 | Motor de decisión (RN-05–09) | reglas glob cacheadas; 4 acciones; default `alert_only` | Agent |
| 3 | Ciclo de vida del evento (RN-10–14, 71–72) | máquina de 7 estados; transiciones validadas | Backend |
| 4 | Baseline (RN-15–20, 50, 82) | init scan; AES-256-GCM con HKDF; estado `absent` | Agent + Backend |
| 5 | Cadena de eventos (RN-21–24) | `superseded`; `parent_event_id`; solo el último accionable | Backend |
| 6 | Aprobación y rechazo (RN-25–29, 77) | optimistic locking; baseline_update; restore/quarantine | Backend |
| 7 | Restauración automática (RN-30–33) | descifrado + escritura + verificación hash; journal | Agent |
| 8 | Cuarentena (RN-34–37) | mover a `/var/lib/fim-agent/quarantine/`; `0400`; journal | Agent |
| 9 | Resiliencia offline (RN-38–42, 83–85) | cola JSON atómica; 100MB drop-oldest; FIFO; journal | Agent |
| 10 | Auth (RN-43–46, 80–81, 100) | JWT rotación; blacklist; Argon2id; must_change_password | Backend |
| 11 | Almacenamiento (RN-47–51) | máx 3 snapshots; gzip; deduplicación por hash | Agent |
| 12 | Notificaciones (RN-52–54, 86–87, 102) | webhook n8n + retry 3x; cascada fallbacks; DLQ | Backend |
| 13 | Sincronización (RN-55–59, 73–75) | 3 streams Valkey; ACK end-to-end; `ruleset_version` | Cross |
| 14 | Seguridad avanzada (RN-60–67, 78–79) | mTLS bootstrap; HMAC; baseline `absent`; rotación cert 90d | Cross |
| 15 | Configuración del agente (RN-68–70) | `config.yaml`; `update_config` firmado; re-scan | Cross |
| 16 | Observabilidad y degradación (RN-87, 92–93, 101–103) | `/health/components` 10s; heartbeat; draining; banners | Backend + Frontend |

---

## Hito 1 (M1) — Dominio, persistencia e infraestructura

**Criterio de aceptación**: el servidor central arranca con `docker compose up`; todas las tablas existen en PostgreSQL; el primer admin puede hacer login, obtiene tokens JWT, y es forzado a cambiar su password; el logout invalida el refresh token; rate limiting de login funcional.

### Change 01 — `infra-docker-compose`

**Capa**: infra · **Depende de**: ninguno

Capacidades:
- `docker-compose.yml` con servicios: `db` (PostgreSQL 18.3), `valkey` (Valkey 9.0.3), `backend` (placeholder), `frontend` (placeholder), `n8n` (2.16.1). **Sin** `db-init` (D3: el lifespan de FastAPI hace `create_all` + `seed_admin`).
- Script SQL de init: bases `fim` y `fim_n8n` con permisos restringidos (ejecutado por la imagen oficial de PostgreSQL via `/docker-entrypoint-initdb.d/`).
- `.env.example` con variables documentadas (DB_PASSWORD, JWT_SECRET_CURRENT/PREVIOUS, ADMIN_USERNAME, ADMIN_PASSWORD, paths CA).
- Red interna Docker; backend único expuesto (`8443` mTLS agentes, `8000` API).

Reglas: RN-67, RN-76, RN-78. Decisiones aplicadas: D3.

**Done**: `docker compose up db valkey n8n` arranca limpio; `psql -c "\l"` muestra `fim` y `fim_n8n`.

---

### Change 02 — `backend-core-scaffold`

**Capa**: backend · **Depende de**: 01

Capacidades:
- Estructura `backend/app/{core,modules}/` según [docs/arquitectura_stack.md](docs/arquitectura_stack.md).
- `core/config.py` (pydantic-settings), `core/database.py` (engine SQLModel + Session).
- **Cross-cutting desde el día 1 (D7)**:
  - `core/logging.py` con structlog JSON.
  - Middleware `sanitize_logs` que filtra password/tokens/secrets de cualquier log structlog.
  - Middleware `trace_id`: genera UUID por request, lo inyecta en context vars de structlog.
- `main.py` con lifespan FastAPI: `SQLModel.metadata.create_all(engine)` + `seed_admin()` (idempotentes, single-instance backend RN-76).
- `requirements.txt` versiones fijadas (FastAPI 0.136, SQLModel, psycopg, python-jose, argon2-cffi, structlog, valkey-py, cryptography).

Reglas: RN-45, RN-62, RN-81, RN-89. Decisiones aplicadas: D3, D7.

**Done**: `docker compose up backend` arranca; `GET /health` → 200; tabla `users` con seed admin; logs son JSON con `trace_id` y sin secrets aún si una request los pasa.

---

### Change 03 — `domain-models`

**Capa**: backend · **Depende de**: 02

Capacidades:
- `Event` (con `version: int`, `parent_event_id`, `process_pid/uid/exe`, `detected_at`, `received_at`, enum `EventStatus` 7 valores en minúsculas; campo `hash` que el approve usará directamente — D2).
- `Rule` (`pattern`, `severity`, `action` enum 4 valores), `RulesetVersion` (contador monotónico global; los comandos llevarán `target_agent_id` — D5).
- `Agent` (`status`, `last_heartbeat`, `ruleset_version_applied` con semántica D5, `queue_pressure`, `bootstrap_secret_hash`), `revoked_certificates`.
- `BaselineEntry` (D1) en backend con: `path`, `agent_id`, `hash: str | null`, `status: 'present' | 'absent'`, `last_updated`, `ruleset_version`. **Sin contenido cifrado** (eso vive en el agente).
- `RejectedEventAudit` (D4) con enum `RejectionReason` (`clock_skew | invalid_schema | invalid_signature | unknown_agent | duplicate_event`) + `payload_dump` truncado a 4 KB.
- `Alert` (D6) tabla **unificada** con lifecycle completo: `event_id`, `severity` enum, `channel` enum nullable, `delivered_at`, `failed_at`, `last_error`, `retry_count`, `created_at`. **Reemplaza** la tabla `failed_notifications` mencionada en RN-86 original.
- `audit_log`, `User` (con `must_change_password`).

Reglas: RN-08, RN-10, RN-44, RN-66, RN-71, RN-72, RN-77, RN-94. Decisiones aplicadas: D1, D4, D5, D6.

**Done**: `create_all()` crea todas las tablas; enums rechazan valores fuera del léxico canónico; `baseline_entries` y `alerts` existen con los shapes definidos en los appendices de docs.

---

### Change 04 — `backend-auth`

**Capa**: backend · **Depende de**: 03

Capacidades:
- `POST /auth/login`, `POST /auth/refresh` (rotación), `POST /auth/logout` (blacklist `jti` en Valkey).
- `core/security.py`: JWT con dual-key (`JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS`).
- `get_current_user()` con scope `password_change_only`.
- `POST /users/change-password` (forzado primer login, ≥12 chars).
- **Cross-cutting (D7)**:
  - Rate limit login 5/15min por `(user+IP)` con counters Valkey + TTL.
  - Rate limit API autenticada 100 req/min por user (en `get_current_user`).
  - Validación de `Origin` contra whitelist (RN-95) en middleware CORS.

Reglas: RN-43, RN-44, RN-45, RN-46, RN-80, RN-81, RN-88, RN-95, RN-100. Decisiones aplicadas: D7.

**Done**: login → access+refresh; refresh rota; logout invalida; segundo uso del refresh revocado → 401; primer admin forzado a cambiar password; 6° intento de login en 15 min → 429.

---

## Hito 2 (M2) — Loop core agent ↔ backend

**Criterio de aceptación**: agente arranca como servicio systemd; bootstrap mTLS completo; baseline cifrado AES-256-GCM generado; cambio real detectado por fanotify (con PID/UID/exe) → publicado en Valkey → consumido por backend → persistido en PostgreSQL → `event_ack` publicado → agente elimina de cola local. Canal mTLS verificado, HMAC obligatorio.

### Change 05 — `agent-core-scaffold`

**Capa**: agent · **Depende de**: ninguno (paralelizable con M1)

Capacidades:
- Estructura `agent/` con `config.py` (lectura `/etc/fim-agent/config.yaml`), `logging.py` (structlog JSON sanitizado), `state.py` (`state.json` con `ruleset_version`).
- Unidad systemd `fim-agent.service` con `AmbientCapabilities=CAP_SYS_ADMIN`, `ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`.
- Setup directorios: `/var/lib/fim-agent/{baseline,quarantine,queue,journal,secrets,certs}/` con `0700`; secrets `0400`.
- `install.sh`: usuario `fim-agent`, dirs, habilitar servicio.

Reglas: RN-51, RN-68, RN-89.

**Done**: `systemctl start fim-agent` ok; corre como `fim-agent` con capabilities correctas; permisos verificados.

---

### Change 06 — `agent-mtls-bootstrap`

**Capa**: cross · **Depende de**: 02, 05

Capacidades:
- `backend/app/core/pki.py`: CA propia (RSA 4096 o Ed25519), emisión TLS 1.3 (90 días), verificación contra `revoked_certificates`, rotación 15 días antes.
- `POST /agents/bootstrap`: recibe `{agent_id, csr, hmac_signature}`, verifica HMAC contra `bootstrap_secret`, emite cert, genera `shared_secret` y `master_secret`, invalida `bootstrap_secret`.
- `POST /agents/register`: admin pre-registra `{agent_id, bootstrap_secret}`.
- Agente: `bootstrap.py` genera par claves, CSR, firma HMAC, llama `/agents/bootstrap`; persiste en `/var/lib/fim-agent/{certs,secrets}/` (`0600`/`0400`).
- Canal mTLS habilitado para toda comunicación posterior.

Reglas: RN-63, RN-64, RN-78, RN-79, RN-82.

**Done**: bootstrap exitoso; cert firmado por CA; canal mTLS funcional; `bootstrap_secret` invalidado.

---

### Change 07 — `agent-baseline-engine`

**Capa**: agent · **Depende de**: 06

Capacidades:
- Derivación clave `HKDF-SHA256(master_secret, AGENT_ID, "baseline-v1")`.
- AES-256-GCM con nonce 96 bits único por archivo.
- Init scan: SHA-256 + cifrado + metadata; deduplicación por hash.
- Snapshots: máx 3/archivo FIFO; gzip del no-activo.
- Baseline con `status: present | absent`.
- Verificación al leer: descifrado falla → reportar incidente.
- Permisos `0600` archivos, `0700` directorio.

Reglas: RN-15, RN-19, RN-20, RN-47, RN-48, RN-49, RN-50, RN-66, RN-82.

**Done**: scan inicial genera archivos cifrados; descifrado produce mismo hash; alteración del cifrado falla.

---

### Change 08 — `valkey-streams-transport`

**Capa**: cross · **Depende de**: 06, 03

Capacidades:
- Agente `publisher.py`: stream `events` con `event_id` UUID v4, `detected_at`, `schema_version`, payload, HMAC-SHA256.
- Agente `heartbeat.py`: stream `agent_heartbeat` cada 10s con `queue_size`, `ruleset_version`, `queue_pressure`, `shutdown`.
- Backend `consumer.py`: consumer group `fim-backend`; `XACK` tras persistir; publica `event_ack` en `commands`; valida timestamps dobles (tolerancia 5min); valida `schema_version`; rechaza con `clock_skew` → `rejected_events_audit`.
- Backend `heartbeat_consumer.py`: actualiza `Agent.last_heartbeat`, `queue_pressure`; `online → offline` 30s sin heartbeat.
- Agente `queue.py`: cola JSON write+rename atómico; 100MB drop-oldest; `queue_pressure` >80%.

Reglas: RN-38, RN-39, RN-40, RN-41, RN-55, RN-56, RN-73, RN-84, RN-90, RN-91, RN-92.

**Done**: evento publicado → consumido → `XACK` → `event_ack` → agente elimina de cola local; heartbeat visible con `online`.

---

### Change 09 — `agent-fanotify-detector`

**Capa**: agent · **Depende de**: 07, 08

Capacidades:
- pyfanotify 0.3.0; `FAN_MARK_FILESYSTEM` sobre paths configurados; exclusión obligatoria de `/var/lib/fim-agent/**`.
- Captura PID, UID, path del ejecutable; modo notificación pura (post-write).
- SHA-256 actual vs baseline cifrado: si igual → ignorar.
- Diff textual para texto; detección texto/binario.
- Recarga de paths en caliente al recibir `update_config`.
- Graceful shutdown SIGTERM: deja de aceptar, drena cola (30s), heartbeat con `shutdown: true`, exit 0.

Reglas: RN-01, RN-02, RN-03, RN-04, RN-93.

**Done**: modificar archivo monitoreado → evento con path, hash, PID, UID, exe; archivo excluido → sin evento; misma modificación dos veces → un solo evento.

---

## Hito 3 (M3) — Decision engine, aprobación humana y sincronización completa

**Criterio de aceptación**: archivo que matchea `auto_restore` → restaurado automáticamente; admin aprueba evento pending → baseline del agente actualizado verificable por hash; rechazo con restore o quarantine ejecutado por agente; CRUD de reglas sincroniza al agente en caliente; re-scan con pending requiere confirmación; notificaciones críticas llegan a n8n (o `failed_notifications` si está caído); `GET /health/components` reporta estado real.

### Change 10 — `agent-decision-engine`

**Capa**: agent · **Depende de**: 09, 07

Capacidades:
- Cache local de reglas; evaluación glob con negación `!`; exclusiva gana sobre inclusiva; default `alert_only`.
- 4 acciones: `auto_restore`, `quarantine`, `manual_review`, `alert_only` con journal pre-acción y post-acción.
- Rehidratación journal al arrancar: `state: pending` → reintento o reporte.
- Comportamiento offline: ejecuta automáticas con reglas cacheadas; encola evento.

Reglas: RN-05, RN-06, RN-07, RN-30, RN-31, RN-32, RN-33, RN-34, RN-35, RN-36, RN-37, RN-42, RN-65, RN-83.

**Done**: regla `auto_restore` → archivo restaurado y evento `auto_restored`; regla `quarantine` → archivo en `/var/lib/fim-agent/quarantine/`; sin regla → `alert_only`; journal coherente.

---

### Change 11 — `backend-event-ingestion`

**Capa**: backend · **Depende de**: 08, 03

Capacidades:
- Validación `schema_version` y clock skew; deduplicación por `event_id`.
- Validación de transiciones contra máquina canónica → 409 si inválida.
- Cadena: si existe `pending` mismo path → marca anterior `superseded`, nuevo con `parent_event_id`; compactación >10/path.
- `GET /events` paginado 50/pág con filtros multi-select estado/fecha/path; excluye `superseded` por defecto.
- `GET /events/{id}` con timestamps dobles y contexto proceso.
- `rejected_events_audit` con enum `RejectionReason` (D4): rechazos por clock skew, schema inválido, signature inválida, agente desconocido o evento duplicado; payload truncado a 4 KB.
- **Rate limit (D7)**: eventos del agente 100/min por `agent_id`; excedentes descartados con alerta interna y registro en `rejected_events_audit` con razón distinta.
- Retention 30 días terminales (excepto referenciados en audit_log).

Reglas: RN-10, RN-11, RN-12, RN-13, RN-14, RN-21, RN-22, RN-23, RN-24, RN-71, RN-72, RN-88, RN-90, RN-91, RN-98, RN-105. Decisiones aplicadas: D4, D7.

**Done**: evento publicado → aparece en `GET /events`; dos cambios consecutivos con pending → cadena (primero `superseded`, segundo activo); fuera de skew → rechazado y persistido en `rejected_events_audit` con `reason='clock_skew'`.

---

### Change 12 — `backend-rules-crud`

**Capa**: backend · **Depende de**: 04, 08

Capacidades:
- `GET/POST/PUT/DELETE /rules` (admin auth).
- Validación `pattern` (glob con `!`), `severity`, `action`.
- En cada cambio: `ruleset_version++` (counter global), comando `rule_sync` firmado HMAC + `target_agent_id` (D5) — typically `null` (broadcast) para reglas globales, opcional para reglas dirigidas a un agente específico.
- Agente filtra por `target_agent_id IN (self.agent_id, NULL)`, verifica firma+versión, reemplaza cache, persiste `ruleset_version`, confirma vía `event_ack`.
- Backend actualiza `Agent.ruleset_version_applied` con la semántica D5: max version de comandos cuyo target era el agente o broadcast.
- `audit_log` para CRUD.

Reglas: RN-08, RN-09, RN-29, RN-57, RN-58, RN-75, RN-79, RN-94, RN-106. Decisiones aplicadas: D5.

**Done**: crear regla via API → `rule_sync` en Valkey → agente aplica sin reiniciar; eliminar regla → paths fallan a `alert_only` default; dashboard muestra `Agent.ruleset_version_applied` correctamente sin falsos "desactualizados" cuando el comando fue targeted a otro agente.

---

### Change 13 — `backend-approve-reject`

**Capa**: backend · **Depende de**: 11, 12, 10

Capacidades:
- `POST /actions/{approve,reject,bulk-approve,bulk-reject}`.
- Approve (D2): UPDATE optimista `WHERE id=X AND version=V AND status='pending'` → 409 si 0 filas; **usa `event.hash` directamente** (NO consulta al agente — la cadena de eventos garantiza que el pending activo refleja el estado más reciente); upsert en `baseline_entries` del backend (D1); publica `baseline_update` firmado HMAC + `ruleset_version++` + `target_agent_id` (D5); `audit_log`.
- Approve con `absent` (RN-60): warning UI; si confirmado, `BaselineEntry` con `hash: null, status: 'absent'`.
- Reject: UPDATE optimista; si `baseline_entries.status='absent'` → no-op log; publica `restore_file` o `quarantine_file` firmado HMAC + `target_agent_id`; baseline NO se actualiza.
- Bulk: optimistic locking individual; respuesta `{succeeded[], failed[]}`.
- Agente al recibir `baseline_update`: filtra `target_agent_id`, verifica firma+versión, actualiza baseline local re-cifrado AES-GCM, confirma vía `event_ack` → backend actualiza `baseline_entries` y `Agent.ruleset_version_applied`.
- Agente al recibir `restore_file/quarantine_file`: filtra `target_agent_id`, journal pre-acción, ejecuta, confirma.
- **NO se publica ningún comando `get_file_hash`** (D2 + D8). El backend no realiza request síncrono al agente.

Reglas: RN-14, RN-16, RN-17 (reescrita por D2), RN-25, RN-26, RN-27, RN-28, RN-29, RN-59, RN-60, RN-66, RN-74, RN-77, RN-94, RN-99, RN-104, RN-106. Decisiones aplicadas: D1, D2, D5, D8.

**Done**: approve → `baseline_entries` (backend) y baseline local del agente actualizados con `event.hash` (verificable por hash); approve de archivo eliminado → `absent` en ambos; reject → comando ejecutado; segundo approve concurrente → 409; bulk mixto → respuesta parcial correcta; **no se observa ningún tráfico síncrono backend → agente** (todo va por streams).

---

### Change 14 — `backend-agent-config`

**Capa**: cross · **Depende de**: 13, 09

Capacidades:
- `GET /agents`, `GET /agents/{id}`, `POST /agents/{id}/config`, `POST /agents/{id}/rescan`.
- `config`: persiste paths en PostgreSQL (autoritativa); `update_config` firmado + `ruleset_version++`; agente recarga fanotify en caliente, scan baseline para paths nuevos.
- `rescan`: si hay pending → confirmación; marca pending `superseded`; publica `rescan_baseline` firmado.
- `GET /agents/{id}` con `status` (online/offline/draining/dead), `last_heartbeat`, `queue_pressure`, `ruleset_version_applied`.
- Transición `dead` 5 min sin heartbeat.
- `audit_log`.

Reglas: RN-18, RN-55, RN-57, RN-68, RN-69, RN-70, RN-75, RN-92, RN-94.

**Done**: agregar path → agente lo monitorea sin reiniciar; re-scan con pending → confirmación + supersede.

---

### Change 15 — `backend-notifications`

**Capa**: backend · **Depende de**: 11

Capacidades:
- Webhook `POST http://n8n:5678/webhook/fim-alert` con retry 3x exponencial (5s/30s/120s).
- Cascada fallbacks: SMTP directo → webhook directo → log crítico. Cada intento (exitoso o fallido) registra/actualiza una fila en la tabla **unificada** `alerts` (D6, RN-107) con `channel`, `delivered_at` o `failed_at`/`last_error`/`retry_count`. **No existe** tabla `failed_notifications` separada.
- Trigger: severidad `critical` o `high`; `superseded` no notifica; asincrónico no bloqueante.
- `GET /alerts/failed`, `POST /alerts/{id}/retry`, `DELETE /alerts/{id}` para gestión del DLQ (filtro `WHERE delivered_at IS NULL AND failed_at IS NOT NULL`).
- `GET /health/components` con `{postgres, valkey, n8n, agents[]}` → `ok|degraded|down`; cambios disparan webhook n8n.

Reglas: RN-52, RN-53, RN-54, RN-86 (reescrita por D6), RN-87, RN-101, RN-102 (reescrita por D6), RN-103, RN-107. Decisiones aplicadas: D6.

**Done**: evento crítico → llega a n8n y queda con `delivered_at` en `alerts`; n8n offline tras 3 retries → fila en `alerts` con `failed_at NOT NULL`; banner amarillo aparece basado en query `WHERE delivered_at IS NULL AND failed_at IS NOT NULL`; `/health/components` refleja estado real.

---

### Change 16 — `backend-sse-alerts`

**Capa**: backend · **Depende de**: 15, 04

Capacidades:
- `GET /alerts/stream` SSE con auth JWT; emite filas nuevas de la tabla `alerts` (D6) al llegar del consumer.
- `GET /alerts` listado paginado (incluye delivered, failed, pending).
- El modelo `Alert` (D6 / RN-107) ya está definido en change 03 con lifecycle completo. Este change solo agrega el endpoint SSE y la query de listado.

Reglas: RN-53, RN-54, RN-107.

**Done**: frontend conectado al SSE recibe alertas sin polling; reconexión no pierde alertas posteriores.

---

## Hito 4 (M4) — Frontend completo y hardening

**Criterio de aceptación**: el admin opera el sistema completamente desde el navegador (login con cambio forzado de password, ver eventos paginados con filtros, aprobar/rechazar individual y bulk con manejo de 409, ver diff, gestionar reglas con sincronización al agente, gestionar paths del agente, dashboard con métricas, alertas en tiempo real SSE, notificaciones fallidas con reintento, banner de degradación del sistema). Headers de seguridad nginx, rate limiting funcional en endpoints sensibles.

### Change 17 — `frontend-shell-auth`

**Capa**: frontend · **Depende de**: 04, 16

Capacidades:
- Vite + React 19 + TypeScript + Tailwind v4 (`@tailwindcss/vite`, sin PostCSS, sin `tailwind.config.js`, solo `@import "tailwindcss"` + `@theme`) + pnpm.
- `api/client.ts`: Axios con interceptors JWT (attach + 401 refresh).
- `stores/auth.store.ts`: Zustand, access token en memoria, NUNCA localStorage.
- `Login.tsx` (rate limit visible), `ForcePasswordChange.tsx` (redirect scope `password_change_only`).
- Layout: `MainLayout`, `AuthLayout`, `Sidebar`, `Navbar`, `SystemBanner` (polling `/health/components` 10s), `AlertsBanner` (yellow si hay filas en `alerts WHERE delivered_at IS NULL AND failed_at IS NOT NULL` — D6).
- `nginx.conf`: CSP, HSTS, X-Frame-Options, SameSite=Strict.
- Cookie refresh: `httpOnly + Secure + SameSite=Strict + Path=/auth/refresh`.

Reglas: RN-43, RN-46, RN-88, RN-95, RN-96, RN-97, RN-100, RN-101, RN-102, RN-103.

**Done**: login funcional; refresh transparente; logout invalida; banner rojo si componente `down`; primer login → change-password.

---

### Change 18 — `frontend-events`

**Capa**: frontend · **Depende de**: 17, 13

Capacidades:
- `pages/Events.tsx`: tabla 50/pág con TanStack Query; filtros multi-select; toggle "Mostrar superseded" persistente en URL; selección múltiple + bulk action bar.
- `EventsTable.tsx`: checkbox por fila + "seleccionar página".
- `BulkActionBar.tsx`: aprobar/rechazar selección con confirmación.
- Detalle: path, hash, timestamps dobles, contexto (PID/UID/exe), estado.
- `DiffViewer.tsx`: `react-diff-viewer-continued` con escapado activo; PROHIBIDO `dangerouslySetInnerHTML`; texto/binario auto; binario → hash + hex dump parcial.
- `RejectModal.tsx`: branch `baseline_absent` oculta restore/quarantine; mensaje especial; manejo HTTP 409 con toast + refresh.
- `EventTimeline.tsx`: cadena por `parent_event_id`.
- Alertas vía SSE: aparecen automáticamente.

Reglas: RN-03, RN-22, RN-23, RN-71, RN-74, RN-77, RN-96, RN-97, RN-98, RN-99.

**Done**: ver eventos paginados; filtrar; ver diff texto; aprobar pending (baseline verificable); rechazar restore/quarantine; 409 → toast + refresh; bulk de 10 → resultado parcial correcto.

---

### Change 19 — `frontend-rules-agents-dashboard`

**Capa**: frontend · **Depende de**: 18, 14, 12

Capacidades:
- `pages/Rules.tsx`: listado, formulario crear/editar (pattern glob con `!`, severity, action), eliminar con confirmación; sincronización visible.
- `pages/Agents.tsx`: lista con `online/offline/draining/dead`; indicador `queue_pressure`; lista editable de paths; botón re-scan con confirmación listando pending a supersede; `AgentCard.tsx` con `draining` visible y botones deshabilitados en ese estado.
- `pages/Dashboard.tsx`: contadores por estado; agentes registrados; pending crítico/alto.
- `pages/Alerts.tsx`: lista histórica desde tabla unificada `alerts` (D6) con filtros por estado (pending/delivered/failed) y severidad.
- `pages/FailedAlerts.tsx`: vista filtrada (`delivered_at IS NULL AND failed_at IS NOT NULL`); reintento individual/bulk vía `POST /alerts/{id}/retry`; descarte vía `DELETE /alerts/{id}`.

Reglas: RN-70, RN-87, RN-92, RN-93, RN-101, RN-102, RN-103.

**Done**: crear regla → agente sin reiniciar; agregar path → agente monitorea; re-scan con pending → diálogo correcto; `draining` deshabilita acciones.

---

### Change 20 — `backend-observability-hardening`

**Capa**: cross · **Depende de**: 13, 15

> **Nota (D7)**: la mayor parte del cross-cutting (sanitize_logs, trace_id, rate limit login/API/eventos, validación Origin) ya vive en los changes 02, 04, 11. Este change consolida lo que NO tenía un primer feature obvio que lo requiriera.

Capacidades:
- `GET /users`, `POST /users` para creación de admins adicionales por admin existente (RN-45).
- Tuning de parámetros de rate limiting para producción (ajuste de buckets si aparece carga real).
- Tests de carga del rate limiter.
- Retención de eventos (30d terminales — RN-98) y compactación de cadenas >10 implementadas como tareas programadas (job de housekeeping).
- Workflows de ejemplo de n8n (`n8n/workflows/*.json`) con casos comunes (Slack, email, ticketing).
- Documentación operativa: variables de entorno requeridas, formato de logs estructurados, paths de retención, instalación del agente como systemd unit.

Reglas: RN-45, RN-94, RN-98.

**Done**: admin puede crear segundo admin; jobs de retención borran eventos terminales >30d (excepto referenciados en `audit_log`); workflows de n8n importables y funcionales; documentación de instalación del agente probada en VM limpia.

---

### Change 21 — `agent-critical-fixes`

**Capa**: agente · **Depende de**: 05, 13, 14 (código ya existente) · **Origen**: auditoría de bugs ([docs/audit_bugs.md](docs/audit_bugs.md), 2026-06-23)

> **Nota**: change de remediación, no de feature nueva. Resuelve los 5 críticos del agente FIM (C1–C5 del audit). No introduce suposiciones nuevas — cada fix hace cumplir una regla ya cerrada (RN-79, RN-75, RN-83, RN-01, RN-93).

Capacidades:
- **C1**: llamar `register_command_handlers()` en `__main__.py` — restaura `restore_file`/`quarantine_file`/`rescan_baseline`/`baseline_update` de no-op silencioso a funcional.
- **C2**: punto de entrada único `_verify_and_parse` que verifica HMAC de todo comando antes de cualquier side effect (cierra el bypass de RN-79 en `event_ack`/`update_config`/`rule_sync`).
- **C3**: eliminar branch duplicado de `update_config` que esquivaba el chequeo de `ruleset_version` (RN-75). Depende de C1.
- **C4**: índice inverso `_event_to_path` para `on_ack` O(1) sin riesgo de mutate-during-iterate.
- **C5**: `_hash_file_async` con retry exponencial (3×, ≤150 ms) para evitar `file_absent` falso por race fanotify/hash (write-tmp+rename de editores).

Reglas: RN-01, RN-40, RN-73, RN-75, RN-79, RN-83, RN-93. Decisiones: D5, D8.

**Done**: comandos destructivos ejecutan; comando con HMAC inválido se descarta; `update_config` viejo se rechaza por versión; baseline sobrevive acks concurrentes y editores con escritura atómica; tests de regresión para invalid-HMAC, mutación concurrente de `_pending` y race fanotify/hash pasan.

---

### Change 22 — `backend-critical-fixes`

**Capa**: backend · **Depende de**: 02, 04, 13 (código ya existente) · **Origen**: auditoría de bugs ([docs/audit_bugs.md](docs/audit_bugs.md), 2026-06-23)

> **Nota**: change de remediación, no de feature nueva. Resuelve los 5 críticos del backend (C6–C10 del audit). No introduce suposiciones nuevas — cada fix hace cumplir una regla/decisión ya cerrada. C9 respeta D3 (sin Alembic): modelo SQLModel + script SQL idempotente versionado en `db/migrations/`.

Capacidades:
- **C6**: marcar `"type": "access"` en `create_access_token` y rechazar tokens no-access en `get_current_user` — un único punto de control cierra el bypass de TTL (refresh usado como access).
- **C7**: cambiar `Depends(get_current_user)` por `Depends(require_full_access)` en `GET /events`, `GET /events/{id}`, `GET /rules`, `GET /rules/{id}` — cierra el bypass de `must_change_password`. Convención: `get_current_user` solo para endpoints de usuario propio.
- **C8**: taxonomía explícita de resultados en el consumer (éxito/skip/error-de-datos → xack; error transitorio de DB → NO xack, dejar en PEL para retry del consumer group). Elimina la pérdida silenciosa de eventos de integridad.
- **C9**: `ondelete="SET NULL"` en FK `parent_event_id` + `order_by DESC` en `compact_chain` + script SQL idempotente `db/migrations/001_fix_parent_event_id_ondelete.sql` para ambientes ya levantados (D3, sin Alembic).
- **C10**: unificar el servidor mTLS 8443 en el event loop principal (`asyncio.create_task(mtls_server.serve())` con `install_signal_handlers=False`), mismo patrón que `consumer_task`/`heartbeat_task`/`retention_task_handle`. Elimina el thread secundario que rompía con `ValueError`.

Reglas: RN-76, RN-79. Decisiones: D3, D7, D8.

**Done**: refresh token rechazado como Bearer access; usuario con `must_change_password` no lee events/rules; evento de integridad con error transitorio de DB se reintenta (queda en PEL); `compact_chain` con cadena larga no lanza `IntegrityError`; puerto 8443 arranca y los agentes conectan por mTLS; tests de regresión para token-type, scope-gate, no-ack-on-db-error, compact-chain-FK y mTLS-startup pasan.

---

### Change 23 — `agent-high-fixes`

**Capa**: agente · **Depende de**: 21 (código ya existente, críticos del agente resueltos) · **Origen**: auditoría de bugs ([docs/audit_bugs.md](docs/audit_bugs.md), 2026-06-23)

> **Nota**: change de remediación, no de feature nueva. Resuelve los 4 ALTOS del agente FIM que conviven con los archivos parcheados por C21 (H1–H4 del audit). No introduce suposiciones nuevas — cada fix hace cumplir una regla ya cerrada (RN-39, RN-84, RN-83, RN-78, RN-79, RN-16, RN-17, RN-30). La verificación de cert en H3 usa Ed25519 (no RSA/PKCS1v15), consistente con el `bootstrap.py` real.

Capacidades:
- **H1**: zero-pad del timestamp a 16 dígitos en el nombre de archivo de cola (`f"{detected_at_ms:016d}_{event_id}.json"`) — el sort lexicográfico de `_json_files` queda cronológicamente correcto, `drop-oldest` borra el evento más viejo (RN-39 FIFO, RN-84). Migración tolerante de nombres legacy sin pad ya en disco.
- **H2**: journal con escritura atómica (tmp → fsync → `os.replace`, mismo patrón que `queue.py`) y HMAC-SHA256 sobre el JSON con `shared_secret`. Entradas truncadas o con HMAC inválido se descartan como corruptas; rehidratación de pendientes al reiniciar deja de perder acciones (RN-83).
- **H3**: verificación criptográfica del material de bootstrap antes de persistir — cadena cert→CA (firma Ed25519 vía `ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes)`), CN del cert == `agent_id`, y clave pública del cert == clave pública local. Cualquier fallo → `RuntimeError`, no se escribe el cert. Cierra el MITM en bootstrap pre-mTLS (RN-78, RN-79).
- **H4**: `update_from_command` lee el entry existente vía `read_entry` y mergea — preserva `snapshots` y `content_b64`, actualiza solo `hash`/`status`/metadata. `restore_file` posterior a un `baseline_update` deja de fallar con `no_baseline_content` (RN-16, RN-17, RN-30).

Reglas: RN-16, RN-17, RN-30, RN-39, RN-78, RN-79, RN-83, RN-84. Decisiones: D8.

**Done**: cola con timestamps de distinta longitud ordena cronológicamente y `drop-oldest` borra el más viejo; entrada de journal truncada o con HMAC inválido se descarta y no se rehidrata; cert de bootstrap con CN incorrecto o no firmado por la CA levanta error y no se persiste; `update_from_command` preserva `snapshots` y `content_b64` existentes; tests de regresión para sort-FIFO, journal-truncado, journal-HMAC-inválido, cert-CN-inválido, cert-CA-inválida y baseline-merge pasan.

---

### Change 28 — `agent-audit-fixes`

**Capa**: agente · **Depende de**: 27 (`agent-stability-fixes`) · **Origen**: auditoría 2026-06-26 · **Decisiones**: D14 (RN-112), D15 (RN-113), D16 (RN-114), D17 (RN-115)

> **Nota**: change de remediación pura. Corrige 14 defectos encontrados en la segunda pasada de auditoría del agente FIM. No introduce features nuevas ni nuevas suposiciones — todas las decisiones (D14–D17) fueron cerradas en los appendices canónicos el 2026-06-26.

Bugs corregidos:
- **BUG-01/02/03 (CRITICAL, D14)** — `detector.py`: reordenamiento en los tres branches de eventos para que `evaluate_and_act` corra ANTES de mutar el baseline. `auto_restore` puede leer `content_b64`. El branch non-restore de `file_modified` solo llama `add_snapshot` (sin `write_entry`) para mantener el baseline activo apuntando al estado known-good.
- **BUG-04 (CRITICAL)** — `decision.py` `rehydrate()`: `publisher.publish()` envuelto en `try/except`; Valkey caído al restart ya no aborta el ciclo de rehidratación.
- **BUG-05 (CRITICAL)** — `decision.py` `_quarantine()`: `mkdir(parents=True, exist_ok=True)` antes de `shutil.move()`; auto-quarantine ya no falla siempre con `move_failed`.
- **BUG-06 (HIGH)** — `__main__.py` `_cert_renewal_loop`: carga `agent-key.pem` y lo pasa como `private_key=` a `verify_cert`; el binding cert↔clave se verifica en renovaciones.
- **BUG-07 (HIGH, D16)** — `bootstrap.py`: `verify=False` reemplazado por `verify=str(config.ca_cert_path)`; validación de existencia del CA cert al inicio de `run()` con `sys.exit(1)` si falta. **BREAKING operacional**: el operador debe pre-provisionar `ca_cert_path` antes del primer bootstrap.
- **BUG-08 (HIGH, D17)** — `transport.py`: `ssl_check_hostname=True` en el cliente `valkeys://`; cierra la posibilidad de MITM por CN incorrecto.
- **BUG-09 (HIGH)** — `publisher.py` `_ack_listener`: cursor guardado DESPUÉS del dispatch (at-least-once).
- **BUG-10 (MEDIUM, D15)** — `decision.py` commit path + `journal.py`: `commit_fn` llama `delete(event_id)` tras `mark_completed`; el journal no crece indefinidamente.
- **BUG-11 (MEDIUM)** — `state.py`: `state.json` corrupto → renombrar a `.bak`, reiniciar con defaults, warn; elimina el crash-restart loop.
- **BUG-12 (MEDIUM)** — `commands.py` `handle_update_config`: guard monotónico de `ruleset_version` (igual que `handle_baseline_update`).
- **BUG-13 (MEDIUM)** — `publisher.py` `_flush_commands`: `save_state` envuelto en `try/except`; disco lleno ya no impide el startup.
- **BUG-14 (MEDIUM)** — `__main__.py`: excepción inesperada de `asyncio.gather` → `sys.exit(1)` para que systemd `Restart=on-failure` active.

Reglas: RN-30, RN-36, RN-79, RN-83, RN-85, RN-112–RN-115. Decisiones aplicadas: D14, D15, D16, D17.

**Done**: 14 bugs corregidos con 247/247 tests pasando (20 regresiones nuevas + 227 existentes).

---

### Change 29 — `agent-resilience-fixes`

**Capa**: agente · **Depende de**: 28 (`agent-audit-fixes`) · **Origen**: auditoría 2026-06-26 · **Decisiones**: D18 (RN-116), D19 (RN-117), D20 (RN-118)

> **Nota**: change de remediación (9 fixes, MEDIUM/LOW/HIGH). No introduce features nuevas. Todas las decisiones (D18–D20) fueron cerradas en los appendices canónicos el 2026-06-26.

Bugs corregidos:
- **FIX-01 (HIGH)** — `detector.py` `_process_event`: guard `path.endswith(".fim_restore_tmp")` al inicio — previene eventos espurios del mecanismo de restauración atómica y el loop infinito de `auto_restore` (D19 / RN-117).
- **FIX-02 (MEDIUM)** — `__main__.py`: `rehydrate()` movido dentro del `try:` principal — el `finally:` con `detector.close()` y `valkey_client.aclose()` se garantiza incluso si `rehydrate` falla por OSError de journal.
- **FIX-03 (MEDIUM)** — `publisher.py` `publish()`: `_pending[event_id]` asignado ANTES de `_xadd()`; XADD envuelto en `try/except pass` — un fallo de Valkey en publish ya no descarta el evento del ciclo de retry.
- **FIX-04 (MEDIUM)** — `commands.py` `handle_quarantine_file` y `handle_restore_file`: validación `os.path.realpath(path)` contra `config.watch_paths` al inicio; rechaza y publica error-ack si el path está fuera o si `watch_paths` está vacío (D18 / RN-116).
- **FIX-05 (MEDIUM)** — `config.py` + `transport.py` + `config.yaml.example`: `AgentConfig.allow_plaintext_valkey: bool = False`; warning prominente en `create_valkey_client` cuando el esquema es `valkey://`/`redis://` y el flag es False — hace visible un `valkeys://` mal escrito que desactivaría mTLS en silencio (D20 / RN-118).
- **FIX-06 (LOW)** — `state.py` `load_state()`: bak renombrado con timestamp (`state.{ts}.json.bak`) — múltiples corrupciones no sobrescriben el mismo `.bak`.
- **FIX-07 (LOW)** — `decision.py` `rehydrate()`: `except Exception` agregado después de `except _ActionFailed` en el loop interno — OSError de `mark_completed()` o `delete()` hace `continue` sin crashear la rehidratación de entradas restantes.
- **FIX-08 (LOW)** — `bootstrap.py` `verify_cert()`: check `not_valid_before_utc <= now <= not_valid_after_utc` después de verificar firma CA y CN — certs expirados o no-aún-válidos son rechazados.
- **FIX-09 (LOW)** — `state.py` `save_state()`: `f.flush(); os.fsync(f.fileno())` antes de cerrar el tmp — consistente con journal, queue y baseline; previene escrituras truncadas en crash.

Reglas: RN-116, RN-117, RN-118. Decisiones aplicadas: D18, D19, D20.

**Done**: 9 fixes implementados; 267/267 tests pasando (20 nuevos en `test_resilience_fixes.py`).

---

### Change 30 — `backend-async-io-fixes`

**Capa**: backend · **Depende de**: 22 (`backend-critical-fixes`), 29 (`agent-resilience-fixes`) · **Origen**: auditoría 2026-06-26 · **Decisiones**: D21, D22 (RN-119)

> **Nota**: change de remediación. Corrige el I/O bloqueante sistémico de consumers y dependencias FastAPI, agrega HMAC al heartbeat consumer, y resuelve bugs de resiliencia en los loops de consumer. Todas las decisiones (D21–D22) están cerradas en los appendices canónicos el 2026-06-26.

Fixes:
- **FIX-01 (CRÍTICO)** — `events/consumer.py` + `heartbeat_consumer.py`: wrap de funciones DB síncronas (`_get_shared_secret`, `_event_exists`, `_reject`, `_handle_heartbeat`, `_sweep_offline`) con `run_in_executor` en sus call sites (D21).
- **FIX-02 (CRÍTICO)** — `core/valkey.py` + `core/deps.py` + `core/rate_limit.py`: agregar cliente Valkey async (`valkey.asyncio.Valkey`) y convertir blacklist check + rate limit a async en las dependencias FastAPI (D21).
- **FIX-03 (CRÍTICO)** — `agents/heartbeat_consumer.py`: agregar verificación HMAC-SHA256 en `_handle_heartbeat` antes de actualizar estado del agente (D22 / RN-119).
- **FIX-04 (ALTO)** — `events/consumer.py:221`, `alerts/service.py:272`, `core/health.py:155`: guardar referencias de `asyncio.create_task()` en un `_background_tasks: set` module-level con callback `discard` para evitar GC prematuro.
- **FIX-05 (ALTO)** — `events/consumer.py:93-95`: envolver `_ensure_group` y `_process_batch("0")` en try/except antes del loop — Valkey no disponible al startup no mata el consumer permanentemente.
- **FIX-06 (MEDIO)** — `agents/heartbeat_consumer.py:88-97`: envolver `_sweep_offline()` en try/except dentro de `_sweep_loop` — errores de DB no colapsan el heartbeat consumer completo.

Reglas: RN-119. Decisiones aplicadas: D21, D22.

---

### Change 31 — `backend-event-correctness`

**Capa**: backend · **Depende de**: 30 (`backend-async-io-fixes`) · **Origen**: auditoría 2026-06-26 · **Decisiones**: D23 (RN-120), D25 (RN-121)

> **Nota**: change de remediación. Corrige lógica de negocio de eventos, notificaciones y acciones. No introduce features nuevas. Todas las decisiones (D23, D25) están cerradas en los appendices canónicos el 2026-06-26.

Fixes:
- **FIX-01 (CRÍTICO)** — `alerts/service.py`: `_try_cascade` retorna `(False, None)` cuando canales primarios configurados fallan — activa retry loop, `failed_at` y DLQ (D23 / RN-120).
- **FIX-02 (ALTO)** — `actions/service.py:204,273-276`: `publish_baseline_update`, `publish_restore_file`, `publish_quarantine_file` movidos a DESPUÉS de `db.commit()` en `_approve_single` y `_reject_single`.
- **FIX-03 (ALTO)** — `events/service.py`: en `ingest_event`, cuando `mark_superseded` retorna `False`, re-consultar pending antes de descartar el nuevo evento (D25 / RN-121).
- **FIX-04 (ALTO)** — `events/router.py:82-86`: paginación SQL real con `LIMIT/OFFSET/ORDER BY` en `list_events` — elimina full table scan.
- **FIX-05 (MEDIO)** — `events/service.py:97-124`: `compact_chain` corregido de `.desc()` a `.asc()` — retiene eventos más viejos, descarta los recientes (correcto).
- **FIX-06 (MEDIO)** — `events/consumer.py:171-184`: check de rate limit movido DESPUÉS del dedup — re-deliveries no gastan presupuesto.
- **FIX-07 (MEDIO)** — `events/consumer.py:178`: validar que `event_id` sea no-vacío antes del dedup; rechazar con `invalid_schema` si ausente.
- **FIX-08 (MEDIO)** — `events/consumer.py:167`: normalizar `detected_at` a UTC-aware antes de la resta; si no parseable → rechazar con `clock_skew` explícito.
- **FIX-09 (INFO)** — `events/service.py`, `rules/service.py`, `actions/service.py`: reemplazar `datetime.utcnow()` por `datetime.now(timezone.utc)` en 5+ lugares.

Reglas: RN-120, RN-121. Decisiones aplicadas: D23, D25.

---

### Change 32 — `backend-sse-security-fixes`

**Capa**: backend · **Depende de**: 31 (`backend-event-correctness`) · **Origen**: auditoría 2026-06-26 · **Decisiones**: D24, D26 (RN-122), D27 (sin código), D28 (sin código)

> **Nota**: change de remediación. Resuelve la fuga de conexiones DB en SSE, la queue ilimitada, y la soft revocation de agentes. D27 y D28 se documentan como limitaciones aceptadas sin cambio de código. Todas las decisiones (D24–D28) están cerradas en los appendices canónicos el 2026-06-26.

Fixes:
- **FIX-01 (ALTO)** — `alerts/stream.py` + `alerts/router.py`: sesión DB liberada tras replay inicial; `asyncio.Queue(maxsize=100)` con drop-newest + log WARNING en `QueueFull` (D24).
- **FIX-02 (ALTO)** — `agents/models.py` + `events/consumer.py` + `agents/heartbeat_consumer.py`: agregar `AgentStatus.revoked`; consumers verifican `agent.status != revoked` antes de procesar mensajes (D26 / RN-122).
- **FIX-03 (BAJO)** — `actions/streams.py`: insertar `PublishedCommand` para todos los tipos de comando de acción (no solo `rule_sync`), completando la trazabilidad de D10.
- **D27 (limitación documentada)** — `shared_secret_hex` en plaintext en DB. Sin cambio de código. Documentar en tesis como trabajo futuro.
- **D28 (tradeoff documentado)** — Heartbeat consumer con `last_id="$"` pierde heartbeats en restart del backend. Sin cambio de código. Impacto: falso positivo de `offline` por <30 s.

Reglas: RN-122. Decisiones aplicadas: D24, D26, D27, D28.

---

### Change 33 — `backend-test-harness`

**Capa**: backend · **Depende de**: 30 (`backend-async-io-fixes`) · **Origen**: remediación 2026-06-29 · **Decisiones**: D3 (lifespan seed/create_all, espejado en el harness)

> **Nota**: change de remediación de infraestructura de tests. La suite del backend no era reproducible: solo pasaba contra la base `fim` del compose de desarrollo (que ya tenía schema + admin sembrado por el lifespan real). Contra una base limpia fallan 38 tests (`relation "users" does not exist`); sin base, 49 (`connection refused`). No introduce features ni nuevas reglas; corrige dos defectos que el harness roto enmascaraba. No requiere delta specs (precedente C28 `agent-audit-fixes`).

Fixes:
- **FIX-01 (CRÍTICO)** — `backend/tests/conftest.py` (root): owner único del schema (`create_all` session-scoped), del seed del admin, y del aislamiento por test vía `TRUNCATE ... RESTART IDENTITY CASCADE` + reseed (function-scoped autouse) sobre el engine real de Postgres. Elimina la dependencia de orden/estado y la falsa premisa de que `httpx.AsyncClient + ASGITransport` ejecuta el lifespan de FastAPI (no lo hace).
- **FIX-02 (ALTO)** — `auth/service.py::seed_admin`: corregir `must_change_password=False` → `True`. Bug de producción que viola RN-62 y RN-100/W20 y el spec `backend-auth` vigente. Agregar helper de test para el flujo de cambio forzado (scope `password_change_only` → 403 hasta completar el cambio).
- **FIX-03 (ALTO)** — resolver el conflicto de `ADMIN_USERNAME` entre `test_auth.py` (`admin`) y `test_user_management.py` (`admin@fim.local`): `Settings()` se instancia una vez al import, first-writer-wins. Fijar un admin de test canónico (`admin`) en el conftest root antes de cualquier import de la app.
- **FIX-04 (ALTO)** — consolidar los patrones B (schema sin aislamiento) y C (sin nada, depende de DB pre-sembrada) sobre el harness canónico. El patrón A (in-memory + `dependency_overrides`) se deja como está (ya aísla). Muchos tests usan `Session(engine)` directo (consumers/services), por eso se elige truncate-reseed sobre el engine real en vez de rollback transaccional (que no los aislaría).
- **FIX-05 (MEDIO)** — `test_logging_sanitize.py`: reescribir los tests. Usaban `structlog.testing.capture_logs()`, que reemplaza la cadena de processors y nunca ejecuta `sanitize_secrets` (por eso fallaban 6 tests, no solo el case-insensitive). El sanitizer de producción ya es correcto (match case-insensitive con `k.lower()`, recursivo) — el defecto está en los tests, NO en `app/core/logging.py`.
- **FIX-06 (MEDIO)** — `test_sse_alerts.py`: acotar el test de stream SSE (consumir N eventos / read-timeout) para que termine deterministicamente; agregar `pytest-timeout` a `requirements-dev.txt` con timeout global como red de seguridad (la suite colgaba indefinidamente).
- **FIX-07 (BAJO)** — corregir docs obsoletas: `backend/README.md` ("Los tests montan la app en memoria — no necesitan DB ni Valkey") y el docstring del conftest. Documentar el run canónico: Postgres+Valkey efímeros, `uv run pytest` desde `backend/`.

Reglas: RN-62, RN-100, RN-89. Decisiones aplicadas: D3.

**Done**: con Postgres+Valkey efímeros y base `fim_test` limpia, `uv run pytest` desde `backend/` queda 100% verde e independiente del orden; ningún test cuelga.

---

### Change 34 — `backend-residual-fixes`

**Capa**: backend · **Depende de**: 32 (`backend-sse-security-fixes`) · **Origen**: auditoría 2026-06-23 ([docs/audit_bugs.md](docs/audit_bugs.md)), bugs residuales · **Decisiones**: D29 (User.email — cerrada 2026-07-01)

> **Nota**: change de remediación. Captura los 8 bugs **backend** de la auditoría 2026-06-23 que nunca tuvieron change asignada: el 1 ALTO y 7 MEDIOS que no entraron en C22 (solo críticos C6–C10) ni fueron rescatados por C30/C31/C32 (que solo levantaron H5, H7, H8, M2). Verificados como STILL-PRESENT contra el código actual el 2026-06-30. No es feature nueva.

Fixes:
- **H6 (ALTO)** — `rules/service.py`: `publish_rule_sync` commitea `Rule` + `RulesetVersion` a Postgres ANTES de publicar a Valkey. Si Valkey está caído, la versión avanza pero los agentes nunca reciben las reglas. Implementar outbox: persistir el mensaje pendiente en la misma transacción y publicar en un background task con retry.
- **M1 (MEDIO)** — `core/rate_limit.py`: el `expire` solo se setea cuando `count == 1`; si `incr` tiene éxito pero `expire` falla, la key queda sin TTL → lockout permanente del `(user+IP)`. Setear el TTL de forma atómica/idempotente en cada incremento. Corregir el docstring que dice "sliding-window" siendo fixed-window. (C30 portó esto a async pero mantuvo el defecto.)
- **M3 (MEDIO)** — `users/models.py` + `users/schemas.py` + `users/router.py`: agregar el campo `email` a `User` (**NOT NULL + UNIQUE**, validado con `EmailStr`). Hoy `UserItem` devuelve `username` en el campo `email` y `CreateUserRequest.email` acepta cualquier string. Script SQL idempotente `db/migrations/` para la columna (D3, sin Alembic). Seed admin con email vía env `ADMIN_EMAIL` (default `admin@fim.local`). **Decisión D29.**
- **M4 (MEDIO)** — ✅ **D32/RN-126 cerrada el 2026-07-02** — `agents/heartbeat_consumer.py` `_sweep_offline`: `Agent.last_heartbeat < threshold` excluye filas `NULL` (en SQL `NULL < x` es NULL) → agentes que nunca latieron nunca pasan a `offline`/`dead`. Estuvo bloqueado en el apply de C34 (2026-07-02) porque el modelo `Agent` no tenía `created_at` ni `registered_at`, sin referencia temporal para decidir cuándo un agente que nunca latió pasa a `dead`. **D32/RN-126** cierra el gap: se agrega `Agent.registered_at` (seteado en `register_agent`) y el barrido marca `dead` cuando `now - registered_at` supera el mismo umbral de `offline → dead` (300 s / 5 min). M4 queda desbloqueado.
- **M5 (MEDIO)** — `agents/service.py` `update_agent_config`: el `detail` del audit log se arma con f-string sobre `str(list)` → JSON inválido (comillas simples) y rompe si un path contiene `"` o `\`. Usar `json.dumps(...)`.
- **M6 (MEDIO)** — `rules/service.py` + `actions/service.py`: `RulesetVersion.increment` hace `SELECT` + `version += 1` + `flush` sin `SELECT FOR UPDATE` → race entre requests concurrentes. Dos implementaciones duplicadas. Unificar en un único `UPDATE ruleset_versions SET version = version + 1 RETURNING version` atómico.
- **M8 (MEDIO)** — `actions/service.py` `_reject_single`: el no-op sobre baseline `absent` es **correcto** por RN-74 (no publica `restore_file` ni `quarantine_file`, "Excepciones: Ninguna"), pero el código no devuelve `baseline_absent: true` en la respuesta. Hacer cumplir RN-74: retornar el flag para que el frontend avise al admin. **No cambia el comportamiento de no-op.**
- **M9 (MEDIO)** — `core/health.py` `_check_n8n`: `client.head()` sin `raise_for_status()` → el `except httpx.HTTPStatusError` es dead code (un 500 de n8n se reporta como OK). Chequear el status code e implementar el fallback GET documentado.

Reglas: RN-44, RN-45, RN-74, RN-75, RN-79, RN-92, RN-94, RN-123. Decisiones aplicadas: D3, D29.

**Done**: regla creada con Valkey caído se reentrega al recuperarse (outbox); `expire` que falla no bloquea permanentemente; `User.email` real, único y validado, con admin sembrado vía `ADMIN_EMAIL`; agente sin heartbeat inicial pasa a `dead`; audit log de config es JSON válido; `ruleset_version` no se pisa bajo concurrencia; reject sobre baseline absent retorna `baseline_absent: true`; `/health` reporta n8n caído como `down`. Tests de regresión por cada fix.

---

### Change 35 — `e2e-contract-fixes`

**Capa**: cross (agente · backend · frontend) · **Depende de**: 34 (`backend-residual-fixes`) · **Origen**: auditoría dual-judge 2026-07-02 (6 subagentes, 2 jueces × componente) · **Decisiones**: ninguna nueva — cada fix hace cumplir un contrato/léxico ya cerrado.

> **Nota**: change de remediación, no de feature nueva. Captura los **4 bugs de contrato cross-proceso** de la auditoría 2026-07-02 que NO requieren decisión de diseño nueva — son mismatches entre lo que un lado emite y lo que el otro espera, verificados a mano contra el código actual. Los tests unitarios de cada lado no los detectan porque construyen los payloads a mano con las claves correctas, nunca cruzando el límite de proceso con el payload real (`to_event_data()`, `EventSource` real). Los otros 2 hallazgos de la misma auditoría (#3 event_ack loop, #6 fanotify over-collection) requieren cerrar decisiones en los appendices y se tratan aparte (exploración → change posterior). Precedente de change de remediación cross-capa sin delta specs: C28/C33.

Fixes:
- **FIX-01 (CRÍTICO)** — `agent/detector.py`: `DetectedChange.to_event_data()` emite `current_hash`/`previous_hash` (via `dataclasses.asdict`), pero el backend lee `event_data.get("hash_detected", "")` (`events/service.py:172`) → **todo evento real persiste con `hash_detected == ""`** y el frontend lo muestra como "archivo ausente". Alinear el payload del agente al léxico canónico que backend y frontend ya usan (`hash_detected`/`hash_expected`), NO cambiar el backend. Agregar test de integración que use el `to_event_data()` real contra el consumer (hoy inexistente — los tests arman el dict a mano).
- **FIX-02 (CRÍTICO)** — `backend/app/modules/alerts/router.py:150,174`: el generador SSE yield-ea `{"id","data"}` sin la clave `event` → el navegador recibe tipo default `message`, pero el frontend escucha `addEventListener('alert', ...)` (`useAlertsSSE.ts:21`) → el listener nunca dispara y el único push del sistema está muerto. Emitir `event: "alert"` en cada yield de alerta (contrato C16). Complementario: `useAlertsSSE` solo está montado en `/events` (`Events.tsx:32`) — evaluar montarlo en el layout global para que las alertas lleguen en toda la app.
- **FIX-03 (ALTO)** — contrato de Agent front↔backend: `AgentResponse` (`agents/models.py:65+`) expone `agent_id`/`last_heartbeat`/`ruleset_version_applied` y **no tiene `hostname` ni `id` ni `last_seen`**, pero el front (`api/agents.ts:8-13`) tipa `id`/`hostname`/`last_seen` → `key={agent.id}` es `undefined` para todos (colisión de keys React), "Visto hace NaNd", y config/rescan pegan a `/agents/undefined` → 404. Alinear el front al schema real del backend (`agent_id`/`last_heartbeat`). `hostname` no existe en el backend: si se lo quiere mostrar hay que verificar si el agente lo reporta en registro/heartbeat; si no, el front deja de referenciarlo. **Si mostrar `hostname` exige una columna nueva en `Agent`, es una decisión → detener y cerrarla en appendix antes de codear.** Además `triggerRescan` (`api/agents.ts:49-53`) manda `force` como query param con body `null`, pero el backend exige `AgentRescanRequest` como JSON body → 422; enviar el body correcto.
- **FIX-04 (MEDIO)** — `backend/app/modules/actions/service.py:337,373`: `approve_bulk`/`reject_bulk` capturan `except Exception` por ítem reusando una única `Session` en loop **sin `session.rollback()`** → en Postgres un error en el ítem N deja la transacción abortada y todos los N+1 fallan en cascada como `internal_error` falsos. Hacer `session.rollback()` tras cada fallo de ítem (patrón ya usado en `users/router.py:130`) o aislar cada ítem en su propia transacción. Test de regresión con un ítem que falla en medio del batch.

Reglas: RN-71 (léxico canónico), RN-17/D2 (hash del evento). Decisiones aplicadas: ninguna nueva.

---

### Change 36 — `backend-command-ack-consumer`

**Capa**: backend + agente · **Depende de**: 34 (`backend-residual-fixes`), 35 (`e2e-contract-fixes`) · **Origen**: auditoría dual-judge 2026-07-02, hallazgo #3 · **Decisiones**: D30 (RN-124)

> **Nota**: cierra el hallazgo #3 de la auditoría dual-judge 2026-07-02 (loop de confirmación de ejecución de comandos), diferido en C35 por requerir una decisión de diseño nueva. D30/RN-124 se cerró el 2026-07-02.

Capacidades:
- Consumer dedicado del stream `event_ack` para el concepto renombrado **`command_ack`** (confirmación de ejecución de comandos, distinto del ack de ingesta homónimo de RN-40/RN-54).
- `PublishedCommand` gana tracking de estado de ejecución: `command_id` (persistido, ya se genera en `actions/streams.py` pero hoy se descarta), estado (`pending | acked | failed | timeout`), `acked_at`, `error`. Migración SQL idempotente (D3, sin Alembic).
- Sweep periódico que marca `timeout` los comandos `pending` que superan el umbral configurado.
- Badge/indicador secundario por evento en el frontend (no un nuevo `EventStatus`).
- Corrige la violación viva de D5/RN-106 en `agents/service.py::update_agent_config` (`ruleset_version_applied` se actualizaba al publicar, no al confirmar) y cierra D1/RN-104 (`baseline_entries` no se actualizaba vía ack de `baseline_update`).

Reglas: RN-104, RN-106, RN-124. Decisiones aplicadas: D30.

**Done**: todo comando publicado queda rastreado en `PublishedCommand` con su `command_id`; un `command_ack` exitoso de `baseline_update` actualiza `baseline_entries`; `Agent.ruleset_version_applied` solo avanza al confirmarse el comando; comandos sin ack tras el umbral configurado quedan en `timeout`; UI muestra el badge de estado de ejecución por evento.

---

### Change 37 — `agent-fanotify-scope-filter`

**Capa**: agente · **Depende de**: 34 (`backend-residual-fixes`), 35 (`e2e-contract-fixes`) · **Origen**: auditoría dual-judge 2026-07-02, hallazgo #6 · **Decisiones**: D31 (RN-125)

> **Nota**: cierra el hallazgo #6 de la auditoría dual-judge 2026-07-02 (over-collection de `FAN_MARK_FILESYSTEM`), diferido en C35 por requerir una decisión de diseño nueva. D31/RN-125 se cerró el 2026-07-02.

Capacidades:
- Filtro de alcance por containment `realpath` en `agent/detector.py::_read_loop`, antes de encolar el evento en `_raw_queue`.
- `watch_paths` canonicalizados una única vez, en `start()`, `reload_paths()` y `reload_watch_paths()`.
- Fix de symlinks que escapan del scope en `agent/baseline.py::init_scan` (y rescan): se omiten con log warning en vez de cifrarse.
- Reutiliza el patrón de containment de D18/RN-116 (`agent/commands.py`) para consistencia entre módulos.
- Contador `out_of_scope_drops` surfaceado en el heartbeat, análogo a `event_drops` ya existente.

Reglas: RN-04, RN-125. Decisiones aplicadas: D31.

**Done**: un cambio fuera de `watch_paths` en un host de un solo mount ya no genera evento; un symlink dentro de `watch_paths` que apunta afuera se omite del baseline con warning (no se cifra); el heartbeat reporta `out_of_scope_drops` > 0 cuando `FAN_MARK_FILESYSTEM` descarta tráfico fuera de alcance.

---

### Change 38 — `frontend-contract-fixes`

**Capa**: frontend + backend · **Depende de**: 35 (`e2e-contract-fixes`) · **Origen**: auditoría dual-judge 2026-07-02 (Juez A) + auditoría de calidad del frontend 2026-07-02 · **Decisiones**: D34 (RN-128)

> **Nota**: change de remediación de contrato frontend↔backend, **ampliada** tras la auditoría de calidad del frontend del 2026-07-02 (la primera auditoría había sido solo de comunicación/contratos). El scope final cubre los 2 bugs de contrato originales, el bug del KPI de severidad (que requirió cerrar la decisión D34/RN-128), la capa visual rota y los gaps de UX/robustez/accesibilidad. Implementada el 2026-07-02.

Fixes de contrato (backend + frontend):
- **FIX-01** — `LoginResponse`/`RefreshResponse` (`auth/schemas.py`) ganan el objeto `user` (`AuthUserOut`: id, username, role, must_change_password). Resuelto backend-side (de las dos opciones planteadas): el front lo tipaba pero el backend nunca lo enviaba → el Navbar no mostraba el usuario logueado.
- **FIX-02** — `AlertResponse` (`alerts/router.py`) serializa `status` (`pending | delivered | failed`) derivado de `delivered_at`/`failed_at` (misma semántica que el filtro `filter_status`); el frame SSE y el replay también lo incluyen. La columna "Estado" de Alertas quedaba siempre vacía.
- **D34/RN-128 (severidad)** — el KPI "pending critical + high" del dashboard enviaba `severity` a `GET /events`, que lo ignoraba → mostraba 2× el total de pendings. Se cerró D34: `Event.severity` (RuleSeverity) persistida al ingerir con la lógica compartida de D-C15-01 (helper único en `rules/service.py`, alerts delega); `/events` acepta `severity` como filtro repetible; `EventOut` la expone; migración idempotente `006_add_event_severity.sql` (backfill `low`). El KPI usa una única request con el filtro real.
- **Limpieza** — se elimina la request `GET /events?page_size=100` del dashboard cuyo resultado se descartaba; `hash_detected` pasa a `string` no-nullable en el front (el backend nunca envía null) y se elimina la rama muerta "archivo ausente" del `RejectModal` (el flujo `confirm_absent`/`baseline_absent` no cambia: va por el 422 y el no-op server-side).

Visual (frontend):
- Tema oscuro unificado: el shell (`MainLayout` bg-gray-50 claro + Navbar blanco) hacía ilegibles los `h1 text-white` de las 6 páginas; shell y vistas auth pasan al tema oscuro de las tarjetas (`bg-gray-950/900/800`).
- Token `gray-750` definido en `globals.css` (`@theme`): los `hover:bg-gray-750` de las 4 tablas eran inertes en Tailwind v4.
- Botones de acción unificados hacia los tokens `@theme` (`primary`/`danger`) en lugar de paleta cruda (`blue-600`/`red-700`).

UX/robustez (frontend):
- `QueryErrorState` compartido: las 6 páginas de listado manejan `isError` con mensaje + retry (antes, pantalla muda ante una request fallida).
- `useAlertsSSE`: además del toast, invalida las queries de `alerts`/`dashboard`/`alerts-failed-count`; ante cierre definitivo de la conexión (respuesta no-200, p. ej. 401 por token vencido en el query param) cierra limpio e intenta refresh — el token nuevo recrea la conexión, sin loop de 401.
- `ModalDialog` compartido (`role="dialog"`, `aria-modal`, `aria-labelledby`, focus trap, Esc, restauración de foco) aplicado a `RejectModal`, `RescanConfirmModal`, el modal de Rules y los dos modales de `BulkActionBar`, sin cambiar su lógica.

No incluido (consciente): endpoint agregado de dashboard (sigue haciendo 1 request por status — 9 por refresco, antes 11); refactor de `AlertsBanner` para reusar `api/alerts.ts`; tests de componentes/hooks del frontend (la cobertura sigue siendo solo de utils puros).

Reglas: RN-128. Decisiones aplicadas: D34.

**Done**: el Navbar muestra el usuario logueado tras login/refresh; la columna Estado de Alertas renderiza `pending|delivered|failed`; el KPI "pending critical + high" refleja el conteo real filtrado por severidad persistida; los encabezados de todas las páginas son legibles sobre el shell oscuro; el hover de las tablas funciona; las páginas de listado muestran error + retry ante fallas; una alerta SSE refresca las vistas y el feed sobrevive al vencimiento del access token; los modales son navegables por teclado y anunciables por lectores de pantalla; el flujo aprobar/rechazar (restore/cuarentena) queda intacto y verificado.

---

### Change 39 — `agent-scope-filter-symlink-hardening`

**Capa**: agente + backend + frontend · **Depende de**: 37 (`agent-fanotify-scope-filter`) · **Origen**: dual-review de C37 (hallazgo MEDIUM-2), 2026-07-02 · **Decisiones**: D33 (RN-127)

> **Nota**: change de hardening que cierra el hallazgo MEDIUM-2 de la revisión dual-judge de C37 (un symlink de escape creado dentro de un `watch_path` es invisible porque el containment por `realpath` completo de D31 dereferencia el destino final antes de comparar contra `watch_paths`). D33/RN-127 se cerró el 2026-07-02 y refina la cláusula de symlinks de D31/RN-125 sin reescribirla. Scope completo cross-capa (agente + backend + frontend) — el metadato del symlink se persiste y se expone en la UI, no queda como slice opcional.

Capacidades:
- Containment por ubicación del link: `_path_location_in_scope` (nueva en `agent/detector.py`) canonicaliza el directorio padre del path y compara el basename literal, sin seguir el componente final; reemplaza al containment por `realpath` completo en el punto de descarte de `_read_loop`.
- Symlink-as-object: todo symlink en scope se reporta con el léxico canónico de RN-71 (`file_created`/`file_deleted`/`file_modified`, sin `event_type` nuevo); `hash_detected = sha256(os.readlink(path))`; el agente nunca abre, hashea ni cifra el contenido del destino, esté dentro o fuera de scope.
- Baseline: nueva función `write_symlink_entry` (`os.lstat`/`os.readlink`); `BaselineEntry` gana `symlink_target: str | None`; `init_scan`/`run_scan` chequean `is_symlink()` antes de `is_file()`.
- Persistencia del metadato en `Event` (`is_symlink`, `symlink_target`) + migración SQL idempotente en `backend/db/migrations/` (convención D3, sin Alembic).
- `EventOut` expone `is_symlink`/`symlink_target`; el frontend agrega un badge/indicador que distingue un evento de symlink de un evento de archivo regular, mostrando el `symlink_target`.
- Resuelve como efecto colateral el hallazgo LOW-1 de la misma revisión (`file_deleted` espurio al borrar un symlink que antes no se registraba en baseline).
- Hardlinks quedan documentados como limitación conocida (no resuelta) más un contador detective opcional `hardlink_suspected` en el heartbeat (`st_nlink >= 2`), sin cambio de comportamiento.

Reglas: RN-04, RN-125, RN-127. Decisiones aplicadas: D33.

**Done**: la creación de un symlink de escape dentro de un `watch_path` ya no es invisible — se reporta como `file_created` con hash de la cadena del destino; el contenido del destino out-of-scope nunca se lee ni se cifra; el re-pointing de un symlink existente se detecta como `file_modified`; la UI muestra que el evento corresponde a un symlink y su `symlink_target`; el hardlink queda documentado como limitación conocida en los appendices canónicos.

---

### Change 40 — `event-status-contract`

**Capa**: backend + agente + frontend · **Depende de**: 38 (`frontend-contract-fixes`), 39 (`agent-scope-filter-symlink-hardening`) · **Origen**: auditoría 2026-08-13 (RN-13 inoperante en producción) · **Decisiones**: D35 (RN-129)

> **Nota**: RN-13 —el evento sobre el que el agente ya actuó nace terminal y no pasa por `pending`— nunca funcionó. El agente no emite `status` y `ingest_event` defaultea a `pending`, así que `auto_restored`, `quarantined` y `alert_only` son miembros inalcanzables del enum `EventStatus` y todo el relato del decision engine es indemostrable. El agente ya publica `action` y `action_failed`, firmados y sin allowlist en el camino; el backend simplemente los descarta. D35/RN-129 se cerró el 2026-08-13 y define la derivación en el backend. Scope acotado al contrato de estado: persistir `diff_text`/`operation_type`/`hash_expected` y arreglar las capabilities de la unit systemd son changes separadas.

Capacidades:
- Derivación del estado en la ingesta: nueva función pura `derive_event_status(action, action_failed)` en `backend/app/modules/events/service.py` implementando la tabla de D35/RN-129; se elimina la lectura de `event_data["status"]` — el backend es la única autoridad sobre `EventStatus`, para que un agente comprometido no pueda inyectar eventos ya `approved`/`rejected`.
- Acción fallida ⇒ `pending`, nunca terminal: el archivo sigue adulterado y el incidente vuelve a la cola del operador con aprobar/rechazar disponibles (los estados terminales no tienen out-edges en `VALID_TRANSITIONS`).
- Nueva columna `Event.action_failed: bool` (default `false`) + migración SQL idempotente `007_add_event_action_failed.sql` (convención D3, sin Alembic), backfill por `DEFAULT FALSE`; `EventOut` la expone.
- `resolved_at = received_at` y `resolved_by = NULL` para los terminales de origen agente: la combinación identifica una resolución automática sin operador humano.
- Limpieza del léxico RN-71: se elimina la sobrescritura `payload["event_type"] = "auto_restored"` de `_auto_restore` (`agent/decision.py`), que contaminaba un campo de vocabulario cerrado y que `_quarantine` nunca hizo de forma simétrica — esa asimetría es justamente por qué el estado se deriva de `action`, no de `event_type`.
- Frontend: indicador que distingue un `pending` con `action_failed = true` (fallo de remediación, prioridad operativa) de un `pending` normal, vía un mapper puro compartido según el patrón de `utils/ackStatus.ts`.
- Tests que cruzan el límite real agente→backend: la suite existente no detectó el bug porque construye payloads a mano con las claves correctas. El test central alimenta `ingest_event` con un payload producido por `DetectedChange.to_event_data()` + `DecisionEngine.evaluate_and_act` reales, para cada fila de la tabla de derivación.

Reglas: RN-06, RN-13, RN-71, RN-72, RN-77, RN-129. Decisiones aplicadas: D35 (D3 para la migración, D33 como precedente de tolerancia hacia adelante).

**Done**: los tres estados terminales de origen agente son alcanzables y verificables en la base; un `auto_restore` exitoso nace `auto_restored` con `resolved_at` seteado y `resolved_by` nulo, y ya no se le pide al operador que decida sobre un archivo ya resuelto; un `auto_restore` fallido nace `pending` con `action_failed = true` y la UI lo distingue de un pendiente ordinario; `event_type` conserva su vocabulario declarado; un payload con `status` explícito lo tiene ignorado y no puede inducir `approved` ni `rejected`; un agente de versión anterior sigue ingiriendo sin error como `pending`.

> **Contexto de riesgo**: por el `ProtectSystem=strict` de la unit systemd (fuera de scope, change separada), `action_failed = true` es hoy la ruta común en un host real, no un caso de borde. La rama `pending + action_failed` es la que se va a ejercitar en la demo hasta que esa change aterrice; la demostración end-to-end de `auto_restored` queda bloqueada hasta entonces. Esa change es la 41.

---

### Change 41 — `agent-deployment-caps`

**Capa**: agente + backend + frontend · **Depende de**: 40 (`event-status-contract`) · **Origen**: auditoría 2026-08-14 (remediación automática inejecutable en el despliegue entregado) · **Decisiones**: D36 (RN-130)

> **Nota**: las acciones automáticas `auto_restore` y `quarantine` (RN-30 a RN-37) son **físicamente inejecutables** en el despliegue que el repo entrega, el 100% de las veces sobre los `watch_paths` por defecto. Dos barreras independientes: `ProtectSystem=strict` con `ReadWritePaths` limitado a los directorios propios del agente remonta la jerarquía del sistema en solo-lectura — y **ninguna capability atraviesa un mount de solo-lectura**, la escritura falla con `EROFS` con independencia del privilegio —; y `CAP_SYS_ADMIN` **no exime de los chequeos DAC**, así que reemplazar un archivo de `root` requiere `CAP_DAC_OVERRIDE` y restaurar su propiedad requiere `CAP_FOWNER` + `CAP_CHOWN`. El unit entregado tampoco puede arrancar en una instalación limpia: exige `FIM_BOOTSTRAP_SECRET` y no declara `EnvironmentFile`, así que gira en el loop de `Restart=on-failure`. D36/RN-130 se cerró el 2026-08-14 y fija el contrato, incluido el rechazo explícito de `ProtectSystem=full`. Esta change desbloquea la demostración end-to-end de `auto_restored` que la 40 dejó declarada como bloqueada.

Capacidades:
- Capabilities: `AmbientCapabilities` y `CapabilityBoundingSet` incorporan `CAP_DAC_OVERRIDE`, `CAP_FOWNER` y `CAP_CHOWN` — en ambas directivas, porque una ambient capability ausente del bounding set se descarta en silencio.
- `ProtectSystem=strict` se conserva con `ReadWritePaths` **derivado**: `install.sh` lo emite como drop-in (`/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf`) a partir de los `watch_paths` del `config.yaml`, dejando el unit base sin editar. El drop-in es aditivo (no repite los directorios del agente ni resetea la lista) e incluye siempre `/etc/fim-agent`, porque `update_config` persiste ahí. El generador es un módulo Python testeable que **rechaza** paths no absolutos, con `..` o con caracteres que romperían la sintaxis de systemd: `config.yaml` lo reescribe `update_config` con paths que vienen del backend.
- Preflight de escritura por `watch_path` al arrancar y en cada `update_config`, con vocabulario cerrado (`writable`, `read_only_mount`, `permission_denied`, `missing`). No invasivo — `statvfs` para la barrera de mount, `access` para la DAC — porque una sonda de escritura real generaría eventos fanotify del propio agente dentro de un path monitoreado. Un path no escribible **no detiene al agente ni interrumpe el monitoreo**: se marca solo-detección, se loguea y viaja en el heartbeat hasta la tarjeta del agente. La detección es la función primaria; la remediación es una capacidad adicional que puede faltar.
- La restauración preserva modo, uid y gid del baseline — que ya se guardan y que **nadie leía jamás**. Sin esto, habilitar las capabilities convertiría un feature roto en una vulnerabilidad: un `auto_restore` "exitoso" dejaría un binario del sistema con dueño `fim-agent`. `fchown` **antes** de `fchmod` (invertirlo limpia los bits setuid/setgid) y ambos sobre el descriptor antes del `os.replace`, así el archivo nunca existe en su path final con propiedad equivocada. Metadata incompleta ⇒ la restauración falla (`no_baseline_metadata`) y el archivo original queda intacto.
- Causa de fallo distinguible: vocabulario cerrado de razones que separa barrera de despliegue (`read_only_mount`, `permission_denied`) de problema de datos (`no_baseline_content`, `no_restorable_content`), publicada en el evento, persistida en `Event.action_error` y explicada en prosa en la UI. Compone con `Event.action_failed` (D35/RN-129) sin alterarlo.
- `install.sh` deja de darle al usuario del servicio la propiedad de su propio código: `/opt/fim-agent` y `/etc/fim-agent` pasan a `root`. Hoy el `chown -R fim-agent` sobre ambos permite que quien obtenga ese uid reescriba el agente y reciba `CAP_SYS_ADMIN` en el siguiente reinicio — las capabilities viven en el proceso, no en el uid.
- `EnvironmentFile=-/etc/fim-agent/env` (opcional, el secreto de bootstrap es de un solo uso) y código de salida `78` (`EX_CONFIG`) con `RestartPreventExitStatus=78`: una instalación mal configurada falla una vez con un mensaje legible en vez de repetirlo cada 5 s.
- Corrección de la documentación canónica: RN-51, el unit de ejemplo de `arquitectura_stack.md`, las limitaciones técnicas de `flujo_de_usuario.md` y la sección de despliegue de `operations.md`, que además está desfasada por documentar `pyfanotify`, `User=root`, `ProtectSystem=full` y un entrypoint inexistente.

Reglas: RN-30 a RN-37, RN-51, RN-71, RN-92, RN-93, RN-108, RN-116, RN-130. Decisiones aplicadas: D36 (D3 para las migraciones, D35 como base sobre la que compone, D18 como límite de containment que no se amplía).

**Done**: un `auto_restore` sobre un `watch_path` cubierto por el drop-in completa en un host real y devuelve el archivo a su contenido, modo, dueño y grupo originales, con el bit setuid intacto si lo tenía; un `watch_path` no remediable aparece como solo-detección en la tarjeta del agente en lugar de fallar en silencio, y el agente sigue detectando; un fallo de remediación por permisos se distingue en la UI de uno por baseline ausente; el usuario del servicio ya no es dueño del código que systemd ejecuta con `CAP_SYS_ADMIN`; y una instalación limpia arranca, o falla una sola vez con un exit code que dice que el problema es de configuración.

> **Limitación conocida (D36)**: `ReadWritePaths` se materializa en la instalación, mientras que `update_config` cambia los `watch_paths` en caliente. Un path agregado desde la interfaz queda **monitoreado pero no remediable** hasta regenerar el drop-in y hacer `daemon-reload` en el anfitrión. Es inherente a que el aislamiento de systemd se resuelve en el namespace de montaje al arrancar el servicio. El preflight la hace visible en vez de silenciosa.


### Change 42 — `stream-ack-durability`

**Capa**: agente + backend + frontend · **Depende de**: 40 (`event-status-contract`), 41 (`agent-deployment-caps`) · **Origen**: auditoría 2026-08-16 (transporte sin contrato de durabilidad) · **Decisiones**: D37 (RN-131)

> **Nota**: tres defectos con una raíz común — el transporte agente↔backend tenía camino feliz y nada más. **(1)** RN-90 y RN-38/RN-41 se anulaban entre sí: la cola offline de 100 MB existe para sobrevivir una caída del backend, y la ventana de skew de 5 minutos sobre `detected_at` convertía el contenido íntegro de esa cola en eventos irrecibibles ante cualquier corte mayor a cinco minutos. La cola de resiliencia sólo funcionaba mientras no hiciera falta. **(2)** El rechazo no se comunicaba: `_reject` hacía `XACK` sin publicar `event_ack`, y el agente sólo borra de la cola al recibir ack, así que cada evento rechazado entraba en un ciclo permanente de republicación cada 60 s, agregando una fila a `rejected_events_audit` por vuelta — tabla que ninguna retención toca. **(3)** Los comandos de decisión no tenían outbox: `baseline_update`, `restore_file` y `quarantine_file` se publicaban post-commit, con pérdida silenciosa (`200 OK` sin comando emitido) si fallaba la obtención del secreto, y pérdida con `500` si fallaba el `XADD` — en ambos casos con el evento ya terminal y el operador creyendo haber restaurado un archivo que nadie tocó. D37/RN-131 se cerró el 2026-08-16 y **enmienda RN-90 y RN-88**.

Capacidades:
- `sent_at` en el payload de evento, **dentro del JSON canónico firmado**, sellado antes de cada `XADD` y re-sellado en cada republicación. La ventana de skew se evalúa sobre él; `detected_at` conserva su validación de parseabilidad y pierde la ventana, quedando como verdad forense. Que esté cubierto por el HMAC es lo que impide que un tercero re-selle un mensaje capturado — el único ataque que RN-90 realmente cubría. Consecuencia estructural: la firma pasa de ser propiedad del evento almacenado a propiedad del envío, y el archivo de cola guarda el payload sin firma. Efecto lateral deseable: rotar el `shared_secret` deja de invalidar la cola en disco, cosa que antes ocurría en silencio.
- Respuesta tipada a todo evento, con `event_nack` como tipo nuevo firmado en el stream `commands`. La presencia de `retry_after` es lo que distingue retenible de terminal — no hay un booleano aparte que pueda desincronizarse del motivo. `invalid_signature` y `unknown_agent` **no reciben respuesta**: no se puede firmar una respuesta verificable para un emisor que no autenticó, y responder convertiría al backend en un oráculo que confirma qué `agent_id` existen.
- Un evento excedido por rate limit **nunca se destruye**: el backend responde `retry_after` derivado del rate limiter y el agente frena la publicación conservándolo en cola. Un evento de integridad descartado es una detección perdida, y una tormenta de cambios es precisamente cuando un atacante se mueve. Los nacks retenibles **no incrementan** el contador de intentos: señalan una condición del backend, no un fallo de entrega, y contarlos haría que el propio backpressure quemara el presupuesto de reintentos.
- `invalid_schema` se parte en dos: payload ilegible (terminal) frente a `schema_version` adelantado (retenible, `schema_version_unsupported`). Sin esa distinción, todo bump futuro de esquema habría exigido despliegue backend-primero **bajo pena de que los agentes borraran sus propios eventos**.
- Techo de intentos y directorio local de descarte con el motivo, acotado a 1000 archivos con drop-oldest, contabilizado en el heartbeat como `discarded_events` y expuesto en la tarjeta del agente. El contador durable vive en el sobre del archivo de cola, no en memoria: `_drain_queue` republica todo al arrancar, así que un techo en RAM no acota nada — un evento sobreviviría indefinidamente a base de reinicios.
- Contención del `event_nack` no autenticado: el agente **ignora todo ack o nack cuyo `event_id` no esté en su cola local**. Sin eso, un tercero puede provocar que el backend emita un nack correctamente firmado con un `event_id` elegido por él, y borrarle eventos pendientes a un agente sano. La firma prueba origen, no legitimidad del contenido. El agente además acota el `retry_after` que acepta, para que un backend con un bug o comprometido no pueda silenciarlo durante horas.
- Los cinco comandos hacia agentes pasan por el outbox transaccional que ya existía para `rule_sync`: la fila nace `pending` en la misma transacción que la mutación del evento y el despachador la publica después. Invierte deliberadamente la norma FIX-02 de publicar post-commit, y la inversión es correcta — con outbox la protección la da la atomicidad, que es más fuerte.

Reglas: RN-25, RN-26, RN-38 a RN-41, RN-71, RN-73, RN-88 (enmendada), RN-90 (enmendada), RN-91, RN-105, RN-131. Decisiones aplicadas: D37 (D3 para la migración `010`, D4/RN-105 ampliada, H6 como mecanismo de outbox reutilizado sin duplicar).

**Done**: una cola que sobrevivió un corte largo drena completa en lugar de ser rechazada en bloque por skew; un evento rechazado deja de republicarse para siempre y queda archivado localmente con su motivo; una tormenta que excede el rate limit no pierde un solo evento; y un approve ejecutado con Valkey caído entrega su comando al recuperarse, en vez de dejar el evento terminal sin comando emitido.

> **Follow-ups declarados fuera de scope**: `event-payload-persistence` (el backend sigue descartando `diff_text`, `operation_type` y `hash_expected` en la ingesta) y la retención de `rejected_events_audit`, `published_commands`, `alerts` y `baseline_entries`, todas sin cota — la política de RN-98 sólo alcanza a `events`.

> **Nota de despliegue**: el formato del archivo de cola es compatible hacia adelante (el agente nuevo lee los archivos del formato anterior y los envuelve), pero **no hacia atrás**. Un rollback a la versión previa con la cola no vacía requiere vaciar el directorio a mano.

---

## Decisiones de implementación cerradas — Abril 2026

Las 8 suposiciones que estaban abiertas en una versión anterior de este roadmap se cerraron el 2026-04-24 y se documentaron formalmente en los appendices "Decisiones de implementación — Abril 2026" de:

- [docs/reglas_de_negocio.md](docs/reglas_de_negocio.md#appendix-decisiones-de-implementación--abril-2026) — contraparte normativa (nuevas reglas RN-104 a RN-108 + reescrituras de RN-17, RN-86, RN-102, RN-75).
- [docs/arquitectura_stack.md](docs/arquitectura_stack.md#appendix-decisiones-de-implementación--abril-2026) — contraparte técnica (schemas SQLModel, decisiones de despliegue, semánticas de protocolo).

Resumen del impacto en este roadmap:

| Decisión | Resolución | Aplicada en change(s) |
|----------|------------|------------------------|
| **D1** — `BaselineEntry` en backend | Tabla con metadata (sin contenido cifrado); el agente sigue siendo único custodio del contenido | 03, 13 |
| **D2** — Hash en approve | Usa el hash del evento; cadena de eventos garantiza consistencia (RN-17 reescrita) | 13 |
| **D3** — Seed admin | Lifespan FastAPI ejecuta `create_all` + `seed_admin` (no init-container); `db-init` eliminado | 01, 02 |
| **D4** — `rejected_events_audit` | Schema con enum `RejectionReason` + payload truncado a 4 KB | 03, 11 |
| **D5** — `ruleset_version` | Counter global + `target_agent_id` por comando + semántica precisa de `ruleset_version_applied` | 03, 12, 13 |
| **D6** — `alerts` unificada | Una sola tabla con lifecycle completo; `failed_notifications` eliminada (RN-86 y RN-102 reescritas) | 03, 15, 16, 17, 19 |
| **D7** — Cross-cutting | Distribuido: cada control viaja con el primer feature que lo necesita; change 20 solo consolida docs | 02, 04, 11, 20 |
| **D8** — NO HTTP en agente | Streams + heartbeat enriquecido cubren todo; futuro Unix socket via systemd activation si surge necesidad | 13 |

**Importante**: si surge una nueva suposición durante la implementación, NO seguir adelante hasta validarla y agregar la decisión correspondiente al appendix de implementación.

---

## Cómo usar este roadmap

1. Cada change debería convertirse en un OpenSpec change (`/sdd-new <change-id>`) cuando llegue su turno en la secuencia.
2. Validar las suposiciones del bloque anterior ANTES de empezar el change que las tiene como bloqueante.
3. Los hitos M1–M4 son puntos de demo/validación. Cerrar un hito implica que todo lo del hito está implementado, probado y verificable end-to-end.
4. Los changes 05 (`agent-core-scaffold`) puede arrancarse en paralelo a M1 si hay capacidad. El resto respeta el DAG.
5. Si surgen nuevas reglas o cambios en docs canónicos, actualizar este roadmap y los changes afectados.
