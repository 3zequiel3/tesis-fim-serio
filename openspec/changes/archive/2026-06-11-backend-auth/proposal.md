## Why

El backend tiene tablas y scaffold operativos (Changes 01-03), pero aún no existe ninguna capa de autenticación: cualquier request puede acceder a cualquier endpoint. Este change implementa el módulo de auth completo — JWT dual-key con rotación de refresh token, blacklist en Valkey, cambio de password forzado al primer login, y los controles de rate limiting que D7 asigna al primer feature de auth.

## What Changes

- Nuevo módulo `backend/app/modules/auth/` con rutas `/auth/login`, `/auth/refresh`, `/auth/logout`.
- Nuevo `backend/app/core/security.py`: firma y validación JWT con `JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS` (dual-key), blacklist de `jti` en Valkey con TTL = `expires_in`.
- `get_current_user()` dependency con scope `password_change_only` para bloquear requests en sesiones de primer login.
- Nuevo endpoint `POST /users/change-password` (módulo `users`): forzado cuando `must_change_password=True`, mínimo 12 chars, Argon2id.
- **Cross-cutting rate limiting (D7)**: rate limit de login 5 intentos / 15 min por `(username + IP)` con counters Valkey + TTL; rate limit API autenticada 100 req/min por `user_id`; ambos inyectados como dependencies FastAPI.
- Middleware CORS con validación de `Origin` contra whitelist configurable (RN-95).
- `audit_log` en login exitoso, logout y cambio de password.

## Capabilities

### New Capabilities

- `backend-auth`: Endpoints de autenticación JWT (login, refresh, logout, change-password), lógica dual-key en `core/security.py`, blacklist `jti` en Valkey, scope `password_change_only`, rate limiting de login y API, validación de `Origin`.

### Modified Capabilities

- `backend-core`: Agrega middleware CORS con `Origin` whitelist al `main.py`; `core/security.py` es un módulo nuevo que se integra al core existente.

## Impact

- **Código nuevo**: `backend/app/core/security.py`, `backend/app/modules/auth/` (router, service, schemas), `backend/app/modules/users/router.py` (endpoint change-password).
- **Código modificado**: `backend/app/main.py` (agrega middleware CORS), `backend/app/core/database.py` o lifespan (conexión Valkey para blacklist y rate limiting).
- **Dependencias**: ya en `requirements.txt` — `python-jose`, `argon2-cffi`, `valkey-py`.
- **Reglas cubiertas**: RN-43, RN-44, RN-45, RN-46, RN-80, RN-81, RN-88, RN-95, RN-100.
- **Decisiones aplicadas**: D7.
- **DAG satisfecho**: Change 03 `domain-models` archivado ✅ — tabla `User` con `must_change_password` y `password_hash` (Argon2id) disponibles.
