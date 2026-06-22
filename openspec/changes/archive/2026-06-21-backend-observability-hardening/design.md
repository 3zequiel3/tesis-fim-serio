## Context

C20 cierra los últimos gaps operativos de M4. El módulo `users` hoy solo expone `POST /users/change-password`. Los buckets de rate limit están hardcodeados como constantes en `core/rate_limit.py`. No existen workflows de n8n ni documentación operativa. La retención de eventos (RN-98) y compactación de cadenas ya están implementadas en C11 (`retention_task()`, `compact_chain()` en `backend/app/modules/events/service.py`, registradas en `main.py` lifespan) pero sin tests dedicados.

## Goals / Non-Goals

**Goals:**
- `GET /users` + `POST /users` (RN-45): admin crea admins adicionales
- Rate limit buckets movidos a `config.py` settings con env vars
- Tests de carga del rate limiter
- Workflows n8n ejemplo (Slack, email, ticketing)
- Documentación operativa completa
- Tests de verificación de retention/compaction de C11

**Non-Goals:**
- Eliminación o desactivación de usuarios (no en RN-45)
- Expansión de roles más allá de admin (plataforma single-role)
- Reimplementar retención (ya existe en C11)
- Automatización de setup de n8n vía API (requiere config manual de credenciales)

## Decisions

### D1: Reutilizar infraestructura auth existente para GET/POST /users
`require_admin` dependency, modelo `User` SQLModel, `hash_password` (Argon2id via passlib), y `write_audit_log` ya existen y se reutilizan sin modificación. Ningún patrón auth nuevo.

**Alternativa descartada**: nuevo rol `superadmin` — rechazado, RN-45 solo requiere autorización de admin existente.

### D2: Rate limit buckets → settings en config.py
`core/rate_limit.py` tiene constantes como `MAX_REQUESTS_PER_MINUTE = 60`. Se convierten en `settings.RATE_LIMIT_LOGIN_PER_MINUTE`, `settings.RATE_LIMIT_API_PER_MINUTE`, `settings.RATE_LIMIT_EVENTS_PER_MINUTE` en `config.py` con overrides por env var. `rate_limit.py` lee de settings al inicio. Los defaults son idénticos a los valores hardcodeados actuales para evitar breaking changes.

**Alternativa descartada**: archivo YAML/TOML de config — rechazado, el patrón env var es consistente con el resto del stack.

### D3: Workflows n8n como JSON importables
Los workflows se almacenan en `n8n/workflows/*.json` en el formato de export de n8n. Usan triggers webhook para recibir payloads de alertas del FIM y hacer fan-out a Slack/email/Jira. No hay automatización vía n8n API — el admin los importa manualmente por la UI de n8n. Intencional: la configuración de credenciales de n8n requiere setup manual de todas formas.

### D4: Tests de retención con fixtures explícitos (no sleep)
`retention_task()` y `compact_chain()` no tienen tests dedicados. C20 agrega `backend/tests/modules/events/test_retention.py` con fixtures que sobreescriben `created_at` a fechas >30d en el pasado, evitando dependencia en tiempo real. Requiere conexión PostgreSQL real (consistent con el patrón C08+: skip en Windows sin psycopg).

### D5: Docs operativos en docs/operations.md
Un único archivo markdown consolidado cubre: variables de entorno requeridas (con valores default), formato de logs estructurados (JSON, campos fijos), paths y política de retención, y guía de instalación del agente como systemd unit (con unit file ejemplo). Referenciado desde el README principal.

## Risks / Trade-offs

- **[Risk] Formato JSON de n8n cambia entre versiones** → Mitigation: documentar la versión n8n (2.16.1) en el header de cada workflow; el formato de export es estable en 2.x.
- **[Risk] Tests de retención frágiles por timing** → Mitigation: usar override explícito de `created_at` en fixtures, no `sleep`.
- **[Risk] Cambio de buckets de rate limit rompe comportamiento existente** → Mitigation: defaults en `config.py` son los mismos valores numéricos que las constantes actuales.
