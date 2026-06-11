## 1. Settings y conexión Valkey

- [x] 1.1 Agregar `JWT_SECRET_CURRENT: str`, `JWT_SECRET_PREVIOUS: str` como campos obligatorios en `Settings` (`core/config.py`)
- [x] 1.2 Agregar `CORS_ALLOWED_ORIGINS: str = ""` en `Settings` con método helper `get_allowed_origins() -> list[str]` que parsea la cadena separada por comas
- [x] 1.3 Agregar `VALKEY_URL: str` como campo obligatorio en `Settings` si no estaba ya presente
- [x] 1.4 Agregar cliente Valkey singleton en el lifespan de `main.py`: `valkey.Valkey.from_url(settings.VALKEY_URL)`, almacenado en variable de módulo
- [x] 1.5 Implementar `get_valkey_client() -> valkey.Valkey` como dependency de FastAPI que retorna el cliente singleton
- [x] 1.6 Cerrar el cliente Valkey en el bloque `finally` del lifespan

## 2. core/security.py — JWT y Argon2id

- [x] 2.1 Crear `backend/app/core/security.py` con `create_access_token(user_id, username, must_change_password, jti) -> str`
- [x] 2.2 Implementar `create_refresh_token(user_id, jti) -> str` en `security.py`
- [x] 2.3 Implementar `decode_token(token: str) -> dict` con fallback a `JWT_SECRET_PREVIOUS`
- [x] 2.4 Implementar `hash_password(plain: str) -> str` con Argon2id (`argon2.PasswordHasher`)
- [x] 2.5 Implementar `verify_password(plain: str, hashed: str) -> bool` con Argon2id verify

## 3. Middleware CORS con validación de Origin

- [x] 3.1 Crear `backend/app/core/middleware/cors.py` con `CORSOriginMiddleware` (ASGI middleware o `BaseHTTPMiddleware`)
- [x] 3.2 El middleware valida `Origin` header: si está presente y no está en `settings.get_allowed_origins()`, responde 403
- [x] 3.3 Si `Origin` no está presente, la request pasa sin restricción
- [x] 3.4 Registrar `CORSOriginMiddleware` en `main.py` antes del router

## 4. Módulo auth — estructura, schemas y service

- [x] 4.1 Crear `backend/app/modules/auth/__init__.py`
- [x] 4.2 Crear `backend/app/modules/auth/schemas.py` con `LoginRequest`, `LoginResponse`, `RefreshResponse`, `LogoutResponse`
- [x] 4.3 Implementar `seed_admin()` en `backend/app/modules/auth/service.py`: check tabla existe → check admin ya existe → crear con `hash_password` + `must_change_password=True` → log
- [x] 4.4 Actualizar el lifespan en `main.py` para importar `seed_admin` desde `modules.auth.service` y llamarla después de `create_all`

## 5. Módulo auth — router (login, refresh, logout)

- [x] 5.1 Crear `backend/app/modules/auth/router.py` con `APIRouter(prefix="/auth")`
- [x] 5.2 Implementar `POST /auth/login`: rate limit check → verify password → generate tokens → set cookie → audit_log → response
- [x] 5.3 Implementar `POST /auth/refresh`: read cookie → decode → blacklist check → rotate → set new cookie → response
- [x] 5.4 Implementar `POST /auth/logout`: blacklist access jti → blacklist refresh jti si existe → clear cookie → audit_log → response
- [x] 5.5 Registrar `auth_router` en `main.py` con `app.include_router(auth_router)`

## 6. Dependencies — get_current_user y require_full_access

- [x] 6.1 Crear `backend/app/core/deps.py` con `get_current_user(token, session, valkey_client) -> User`: decode → blacklist check → rate limit API → load User
- [x] 6.2 Implementar `require_full_access(user: User = Depends(get_current_user)) -> User`: verifica que el JWT no tiene `scope="password_change_only"`, lanza 403 si tiene

## 7. Módulo users — change-password

- [x] 7.1 Crear `backend/app/modules/users/__init__.py` y `backend/app/modules/users/schemas.py` con `ChangePasswordRequest`
- [x] 7.2 Crear `backend/app/modules/users/router.py` con `POST /users/change-password`: aceptar ambos scopes → validar current_password si scope normal → validar longitud ≥ 12 → update hash → `must_change_password=False` → revocar tokens → audit_log → response
- [x] 7.3 Registrar `users_router` en `main.py`

## 8. Rate limiting helpers

- [x] 8.1 Crear `backend/app/core/rate_limit.py` con `check_login_rate_limit(username, ip, valkey) -> None` que lanza 429 si supera 5/15min
- [x] 8.2 Implementar `check_api_rate_limit(user_id, valkey) -> None` con límite 100/min por user_id
- [x] 8.3 Integrar `check_login_rate_limit` en el handler de login (antes de verificar password)
- [x] 8.4 Integrar `check_api_rate_limit` en `get_current_user` (después de validar JWT y blacklist)

## 9. audit_log helper

- [x] 9.1 Crear o completar `backend/app/core/audit.py` con función `write_audit_log(session, action, user_id, extra=None)` que inserta en la tabla `audit_log`
- [x] 9.2 Llamar `write_audit_log` en: login exitoso (`action="login"`), logout (`action="logout"`), change-password (`action="change_password"`)

## 10. Tests

- [x] 10.1 Crear `backend/tests/test_auth.py` con test de login exitoso (sin must_change_password)
- [x] 10.2 Test de login con primer admin: `must_change_password=True` en response y scope en token
- [x] 10.3 Test de login con password incorrecta → 401
- [x] 10.4 Test de rate limit login: 5 intentos fallidos → 6to retorna 429
- [x] 10.5 Test de refresh válido → rota el token; refresh con token viejo → 401
- [x] 10.6 Test de logout → access token revocado → 401 en request siguiente
- [x] 10.7 Test de `POST /users/change-password` con scope `password_change_only` (primer login)
- [x] 10.8 Test de change-password con new_password < 12 chars → 422
- [x] 10.9 Test de CORS: Origin en whitelist → OK; Origin fuera → 403; sin Origin → OK
- [x] 10.10 Test de `require_full_access`: token con scope `password_change_only` en endpoint normal → 403

## 11. Smoke test end-to-end

- [x] 11.1 Actualizar `.env` con `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `CORS_ALLOWED_ORIGINS=http://localhost:5173`
- [x] 11.2 Ejecutar `docker compose up --build backend db valkey` y verificar que el backend arranca sin errores
- [x] 11.3 Verificar `GET /health` → 200
- [x] 11.4 Verificar que `seed_admin` creó el admin: `POST /auth/login` con credenciales del `.env` → 200 con `must_change_password: true`
- [x] 11.5 Verificar `POST /users/change-password` con el token de scope `password_change_only` → 200
- [x] 11.6 Verificar `POST /auth/login` con la nueva password → 200 sin `must_change_password`
- [x] 11.7 Verificar `POST /auth/refresh` → nuevo access token
- [x] 11.8 Verificar `POST /auth/logout` → 200; llamada siguiente con access token revocado → 401
- [x] 11.9 Verificar rate limit: 6 intentos de login fallidos → 429 en el 6to
