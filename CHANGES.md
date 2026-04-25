# CHANGES.md — Roadmap de implementación FIM Platform

Este documento define la **secuencia ordenada de changes** (en sentido OpenSpec) para construir el sistema FIM Platform desde cero. Cada change representa una slice coherente con proposal/spec/tasks que entrega capacidad verificable y depende explícitamente de changes anteriores.

**Fuentes canónicas** (leídas para producir este roadmap):
- [docs/arquitectura_stack.md](docs/arquitectura_stack.md) — stack técnico, modelo de eventos, decision engine, baseline
- [docs/flujo_de_usuario.md](docs/flujo_de_usuario.md) — flujos UI/UX
- [docs/historias_de_usuario.md](docs/historias_de_usuario.md) — historias priorizadas
- [docs/reglas_de_negocio.md](docs/reglas_de_negocio.md) — 16 dominios, ~103 reglas

**Estado actual**: backend/, agent/, frontend/ vacíos. Documentación 100% terminada y validada (33 decisiones de auditoría + 10 decisiones de diseño + **8 decisiones de implementación** aplicadas en Abril 2026).

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
