## Context

Change 04 del roadmap M1. El backend ya tiene scaffold (core, logging, trace_id, DB engine) y todos los modelos de dominio (`User`, `Event`, `Alert`, etc.) definidos y migrados. Este change cierra el hito 1: implementa la capa de autenticación completa incluyendo los controles de rate limiting que D7 asignó al primer feature que los necesita.

**Estado previo**: ningún endpoint requiere auth. `User.must_change_password` existe pero nadie lo verifica. `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`JWT_SECRET_CURRENT`/`JWT_SECRET_PREVIOUS` están en `settings` pero sin consumir.

**Constraints**:
- Single-instance backend (RN-76): no hay sesiones distribuidas entre réplicas. Los counters de rate limit y la blacklist de tokens van en Valkey (compartido y sobrevive reinicios).
- Valkey ya corre como servicio en el compose. La conexión se crea en el lifespan.
- FastAPI 0.136 + python-jose + argon2-cffi ya en `requirements.txt`.

## Goals / Non-Goals

**Goals:**
- Login con access token (15 min) + refresh token (7 días, httpOnly cookie).
- Refresh con rotación: el token viejo queda revocado inmediatamente.
- Logout: blacklist del `jti` del access token + del refresh token en Valkey.
- Segundo uso de refresh token revocado → 401.
- `POST /users/change-password` con guard `must_change_password`.
- Scope `password_change_only` que bloquea todos los endpoints excepto change-password.
- Rate limit login: 5 intentos / 15 min por `(username + IP)`.
- Rate limit API autenticada: 100 req/min por `user_id`.
- Validación `Origin` en CORS contra whitelist configurable.
- `audit_log` en login exitoso, logout y change-password.

**Non-Goals:**
- Multi-factor authentication.
- Creación de usuarios adicionales (eso es Change 20).
- OAuth / SSO.
- Rate limit por endpoint individual (solo global autenticado + login).
- Lógica de `GET /users` (Change 20).

## Decisions

### D-A: Tokens en body + refresh en cookie httpOnly

Access token viaja en el body del response de login/refresh (el frontend lo guarda en memoria, nunca en localStorage — requisito de la HU frontend). Refresh token viaja en `Set-Cookie: refresh_token; HttpOnly; Secure; SameSite=Strict; Path=/auth/refresh`. El backend lee el refresh token de la cookie, no del body, para blindarlo contra XSS.

**Alternativa considerada**: ambos tokens en body. Descartada: requeriría que el frontend almacene el refresh en localStorage, lo que viola RN-96.

### D-B: Blacklist `jti` en Valkey con TTL

Cada access token y refresh token tiene un `jti` (UUID v4). Al logout, ambos `jti`s se insertan en Valkey con `SETEX fim:blacklist:<jti> <ttl_restante_segundos> "1"`. `get_current_user` verifica `EXISTS fim:blacklist:<jti>` antes de aceptar el token. El TTL es el tiempo restante hasta expiración del token, evitando que Valkey acumule entradas viejas.

**Alternativa considerada**: set de jti válidos (allowlist). Descartada: requiere escribir en Valkey en cada login y limpiar activamente; la blacklist solo escribe en logout (evento raro) y se auto-limpia.

### D-C: Refresh token rotation + detección de re-uso

Cada `POST /auth/refresh` emite un nuevo par access/refresh. El refresh viejo se agrega a la blacklist inmediatamente. Si el mismo refresh se usa dos veces (re-use attack), la segunda llamada encuentra el `jti` en la blacklist y responde 401 — sin necesidad de revocar todos los tokens del usuario.

**Alternativa considerada**: invalidar todos los tokens del usuario al detectar re-uso. Descartada: excesiva para el threat model actual y rompe sesiones legítimas concurrentes.

### D-D: Rate limiting con Sliding Window en Valkey

Para login: clave `fim:rl:login:<username>:<ip>` con pipeline `INCR` + `EXPIRE` (TTL 900s). Si el counter supera 5, el handler devuelve 429 antes de verificar password (evita timing oracle). Para API autenticada: clave `fim:rl:api:<user_id>` con TTL 60s, límite 100. La verificación va en `get_current_user` después de validar el JWT — aplica solo a usuarios autenticados.

**Alternativa considerada**: Token bucket con sorted set. Descartada: más compleja de implementar correctamente y la diferencia de precisión no es relevante para este threat model.

### D-E: `get_current_user` como dependency con scope

`get_current_user` valida el JWT, verifica blacklist, y devuelve el `User`. Cuando `must_change_password=True`, agrega el claim `scope: password_change_only` al token en el login (no en todos los tokens). Los endpoints protegidos usan `Depends(get_current_user)` sin scope. El endpoint `POST /users/change-password` verifica que `must_change_password=True` o que se llame con un token de scope normal (ambos caminos válidos — el usuario puede cambiar su password libremente).

Para bloquear el acceso a endpoints normales cuando hay scope `password_change_only`, se define una dependency `require_full_access` que lanza 403 si el scope es `password_change_only`. Los endpoints normales usan `Depends(require_full_access)` encadenado a `Depends(get_current_user)`.

### D-F: Dual-key JWT

`JWT_SECRET_CURRENT` firma los nuevos tokens. `JWT_SECRET_PREVIOUS` permite validar tokens firmados con la clave anterior (para rotación de clave sin invalidar sesiones activas). `get_current_user` intenta verificar primero con `CURRENT`, si falla con `PREVIOUS`. Si ambas fallan, 401. Si el token fue firmado con `PREVIOUS`, el próximo refresh emite uno nuevo firmado con `CURRENT`.

## Risks / Trade-offs

- **Counter de rate limit no atomic** → Mitigación: usar pipeline Valkey `INCR` + `EXPIRE` en una sola transacción; race condition teórica en creación de la key es aceptable (puede dejar pasar 1-2 requests extra).
- **Blacklist consulta Valkey en cada request** → Trade-off aceptado: agrega ~1ms de latencia. No hay alternativa sin perder la capacidad de revocar tokens inmediatamente. Con single-instance backend (RN-76) no se puede usar una variable en memoria de forma segura ante reinicios.
- **Cookie SameSite=Strict rompe flows OAuth futuros** → No-goal en este change; si en el futuro se agrega OAuth, el cookie handling se revisará.
- **Refresh token en cookie no accesible por JS** → Correcto por diseño (XSS mitigation). El frontend nunca lee la cookie; solo el browser la envía automáticamente a `/auth/refresh`.

## Migration Plan

1. Sin datos previos que migrar: Change 03 creó la tabla `users` vacía.
2. `seed_admin()` (definida aquí, ya con el cuerpo completo) corre en el lifespan y crea el primer admin si la tabla está vacía.
3. Variables requeridas en `.env`: `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`. Ya están en `.env.example` desde Change 01.
4. Rollback: revertir el merge. La tabla `users` queda vacía o con el admin creado; no hay datos de usuario que perder.

## Open Questions

Ninguna. Las decisiones de auth estaban cerradas en el appendix "Decisiones de implementación — Abril 2026" y en RN-43 a RN-46, RN-80, RN-81, RN-88, RN-95, RN-100.
