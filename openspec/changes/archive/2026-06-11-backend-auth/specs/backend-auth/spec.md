# Spec: backend-auth

## ADDED Requirements

### Requirement: core/security.py — Firma y validación JWT dual-key

El sistema SHALL implementar `backend/app/core/security.py` con las funciones:
- `create_access_token(user_id, username, must_change_password, jti) -> str`: firma un JWT con `JWT_SECRET_CURRENT`, `alg=HS256`, `exp=now+15min`, claims `sub=user_id`, `username`, `jti`, `scope="password_change_only"` si `must_change_password=True`.
- `create_refresh_token(user_id, jti) -> str`: firma un JWT con `JWT_SECRET_CURRENT`, `exp=now+7days`, claims `sub=user_id`, `jti`, `type="refresh"`.
- `decode_token(token) -> dict`: intenta verificar con `JWT_SECRET_CURRENT`; si falla, intenta con `JWT_SECRET_PREVIOUS`; si ambas fallan, lanza `JWTError`. Retorna el payload.
- `hash_password(plain) -> str`: Argon2id vía `argon2-cffi`.
- `verify_password(plain, hashed) -> bool`: Argon2id verify.

#### Scenario: Token firmado con CURRENT es válido
- **WHEN** se llama `create_access_token(...)` y luego `decode_token(token)`
- **THEN** el payload contiene `sub`, `jti`, `username`, `exp`
- **AND** no se lanza excepción

#### Scenario: Token firmado con PREVIOUS es válido
- **WHEN** se firma un token manualmente con `JWT_SECRET_PREVIOUS`
- **AND** se llama `decode_token(token)`
- **THEN** el payload se decodifica correctamente sin excepción

#### Scenario: Token con secret desconocido es rechazado
- **WHEN** se firma un token con un secret arbitrario distinto de CURRENT y PREVIOUS
- **AND** se llama `decode_token(token)`
- **THEN** se lanza `jose.JWTError`

#### Scenario: Password hasheada con Argon2id
- **WHEN** se llama `hash_password("hunter2")`
- **THEN** el resultado empieza con `$argon2id$`
- **AND** `verify_password("hunter2", hashed)` retorna `True`
- **AND** `verify_password("wrong", hashed)` retorna `False`

---

### Requirement: seed_admin() con cuerpo completo (D3)

La función `seed_admin()` en `backend/app/modules/auth/service.py` SHALL tener el cuerpo completo de creación del admin. Si la tabla `users` no existe, retorna con log `seed_admin.skipped reason=users_table_not_yet_created`. Si la tabla existe y ya hay un usuario con `username=ADMIN_USERNAME`, retorna sin modificar. Si la tabla existe y está vacía, crea el usuario con `hash_password(ADMIN_PASSWORD)`, `role="admin"`, `must_change_password=True`, `is_active=True`, y emite log `seed_admin.created`.

#### Scenario: seed_admin crea admin cuando tabla vacía
- **WHEN** la tabla `users` existe y está vacía
- **AND** se llama `seed_admin()`
- **THEN** se crea exactamente un registro con `username=ADMIN_USERNAME`, `must_change_password=True`
- **AND** `verify_password(ADMIN_PASSWORD, user.password_hash)` retorna `True`

#### Scenario: seed_admin es idempotente
- **WHEN** el admin ya existe en la tabla
- **AND** se llama `seed_admin()` por segunda vez
- **THEN** la tabla sigue con exactamente un registro
- **AND** no se lanza excepción

---

### Requirement: POST /auth/login

El endpoint `POST /auth/login` SHALL aceptar JSON `{username: str, password: str}` y:
1. Verificar rate limit login: si el counter `fim:rl:login:<username>:<ip>` >= 5, responder 429 con `Retry-After: 900`.
2. Incrementar el counter con `INCR` y `EXPIRE 900` en Valkey.
3. Buscar el usuario por username; si no existe o `verify_password` falla, responder 401 con `WWW-Authenticate: Bearer`.
4. Si `is_active=False`, responder 403.
5. Generar `jti_access` y `jti_refresh` como UUID v4.
6. Emitir access token (15 min) y refresh token (7 días).
7. Responder 200 con body `{access_token: str, token_type: "bearer", must_change_password: bool}` y `Set-Cookie: refresh_token=<refresh>; HttpOnly; Secure; SameSite=Strict; Path=/auth/refresh`.
8. Escribir `audit_log` con `action="login"`, `user_id`, `ip`.

#### Scenario: Login exitoso sin must_change_password
- **WHEN** se hace `POST /auth/login` con credenciales correctas de un usuario con `must_change_password=False`
- **THEN** responde 200
- **AND** el body contiene `access_token` (JWT válido) y `must_change_password: false`
- **AND** el header `Set-Cookie` incluye `refresh_token` con flags `HttpOnly`, `SameSite=Strict`

#### Scenario: Login exitoso con must_change_password
- **WHEN** se hace `POST /auth/login` con credenciales del primer admin
- **THEN** responde 200 con `must_change_password: true`
- **AND** el access token decodificado contiene `scope: "password_change_only"`

#### Scenario: Login con password incorrecta
- **WHEN** se hace `POST /auth/login` con username válido y password incorrecta
- **THEN** responde 401

#### Scenario: Rate limit login — 6to intento bloqueado
- **WHEN** se hacen 5 intentos de login fallidos (usuario + IP)
- **AND** se hace un 6to intento
- **THEN** el 6to intento responde 429
- **AND** el header `Retry-After` está presente

#### Scenario: audit_log en login exitoso
- **WHEN** el login es exitoso
- **THEN** existe un registro en `audit_log` con `action="login"` y el `user_id` correspondiente

---

### Requirement: POST /auth/refresh — rotación de refresh token

El endpoint `POST /auth/refresh` SHALL leer el refresh token de la cookie `refresh_token` y:
1. Decodificarlo con `decode_token`; si falla, 401.
2. Verificar que `type=="refresh"`; si no, 401.
3. Verificar que `jti` NO está en la blacklist Valkey; si está, 401.
4. Agregar el `jti` viejo a la blacklist con `SETEX fim:blacklist:<jti> <ttl_restante> "1"`.
5. Emitir nuevo par access + refresh con nuevos `jti`s.
6. Responder 200 con `{access_token: str, token_type: "bearer"}` y nuevo `Set-Cookie` con el nuevo refresh token.

#### Scenario: Refresh válido rota el token
- **WHEN** se hace `POST /auth/refresh` con una cookie refresh token válida
- **THEN** responde 200 con un nuevo `access_token`
- **AND** el `Set-Cookie` contiene un nuevo `refresh_token` diferente al anterior

#### Scenario: Refresh con token revocado — 401
- **WHEN** se usa el mismo refresh token por segunda vez (ya rotado)
- **THEN** responde 401

#### Scenario: Refresh con cookie ausente — 401
- **WHEN** se hace `POST /auth/refresh` sin cookie `refresh_token`
- **THEN** responde 401

---

### Requirement: POST /auth/logout — blacklist de ambos tokens

El endpoint `POST /auth/logout` SHALL requerir autenticación (access token válido en `Authorization: Bearer`) y:
1. Extraer el `jti` del access token y agregarlo a la blacklist con TTL = tiempo restante.
2. Leer la cookie `refresh_token`; si existe, extraer su `jti` y agregarlo a la blacklist con TTL = tiempo restante.
3. Limpiar la cookie `refresh_token` con `Set-Cookie: refresh_token=; Max-Age=0`.
4. Escribir `audit_log` con `action="logout"`, `user_id`.
5. Responder 200 con `{message: "logged_out"}`.

#### Scenario: Logout invalida el access token
- **WHEN** se hace `POST /auth/logout` con un access token válido
- **THEN** responde 200
- **AND** una llamada subsiguiente con el mismo access token a cualquier endpoint protegido responde 401

#### Scenario: Logout invalida el refresh token
- **WHEN** se hace `POST /auth/logout` con access + refresh cookie
- **THEN** un `POST /auth/refresh` posterior con la misma cookie responde 401

#### Scenario: audit_log en logout
- **WHEN** el logout es exitoso
- **THEN** existe un registro en `audit_log` con `action="logout"` y el `user_id`

---

### Requirement: get_current_user dependency — validación y blacklist

La función `get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)) -> User` SHALL:
1. Llamar `decode_token(token)`; si falla, 401.
2. Verificar `EXISTS fim:blacklist:<jti>` en Valkey; si está, 401.
3. Verificar rate limit API: `fim:rl:api:<user_id>` con límite 100/min; si supera, 429.
4. Cargar el `User` de la DB; si no existe o `is_active=False`, 401.
5. Retornar el `User`.

#### Scenario: Token válido retorna el usuario
- **WHEN** se llama `get_current_user` con un access token válido y no revocado
- **THEN** retorna el `User` correspondiente sin excepción

#### Scenario: Token expirado — 401
- **WHEN** se llama `get_current_user` con un token con `exp` en el pasado
- **THEN** lanza HTTPException 401

#### Scenario: Token en blacklist — 401
- **WHEN** el `jti` del token está en `fim:blacklist:*` en Valkey
- **THEN** lanza HTTPException 401

#### Scenario: Rate limit API — 101a request bloqueada
- **WHEN** un usuario autenticado hace 100 requests en menos de 60 segundos
- **AND** hace la request 101
- **THEN** la request 101 responde 429

---

### Requirement: scope password_change_only — bloqueo de acceso general

La dependency `require_full_access(user: User = Depends(get_current_user)) -> User` SHALL verificar que el token no tiene `scope="password_change_only"`. Si lo tiene, responde 403 con `{detail: "password_change_required"}`. Todos los endpoints protegidos normales SHALL usar `Depends(require_full_access)` en vez de `Depends(get_current_user)` directamente.

#### Scenario: Token con scope password_change_only bloqueado en endpoints normales
- **WHEN** se usa un access token con `scope="password_change_only"` en cualquier endpoint normal (ej. `GET /events`)
- **THEN** responde 403 con `detail="password_change_required"`

#### Scenario: Token normal no está bloqueado
- **WHEN** se usa un access token sin scope especial
- **THEN** el endpoint procede normalmente

---

### Requirement: POST /users/change-password

El endpoint `POST /users/change-password` SHALL requerir autenticación (acepta tanto scope normal como `password_change_only`) y aceptar `{current_password: str, new_password: str}`:
1. Si el token tiene scope `password_change_only`, omitir la verificación de `current_password` (primer login forzado — el admin no tiene password "anterior" que valide el flujo normal).
2. Si el scope es normal, verificar `current_password` contra el hash actual; si falla, 401.
3. Validar `new_password`: mínimo 12 caracteres; si no cumple, 422.
4. Actualizar `password_hash` con `hash_password(new_password)` y `must_change_password=False`.
5. Revocar el access token actual en la blacklist (forzar nuevo login).
6. Limpiar la cookie `refresh_token` con `Max-Age=0`.
7. Escribir `audit_log` con `action="change_password"`, `user_id`.
8. Responder 200 con `{message: "password_changed"}`.

#### Scenario: Primer login — cambio forzado con scope password_change_only
- **WHEN** el admin recién creado hace `POST /users/change-password` con un token de scope `password_change_only`
- **AND** provee un `new_password` de al menos 12 caracteres
- **THEN** responde 200
- **AND** un login posterior con la nueva password es exitoso
- **AND** el access token anterior ya no es válido (401)

#### Scenario: Cambio normal con current_password correcto
- **WHEN** un usuario autenticado (scope normal) hace `POST /users/change-password` con `current_password` correcto y `new_password` ≥ 12 chars
- **THEN** responde 200
- **AND** `must_change_password` queda en `False`

#### Scenario: new_password < 12 caracteres — 422
- **WHEN** se envía `new_password` con 11 caracteres o menos
- **THEN** responde 422

#### Scenario: current_password incorrecto (scope normal) — 401
- **WHEN** el usuario envía `current_password` incorrecto
- **THEN** responde 401

#### Scenario: audit_log en change_password
- **WHEN** el cambio de password es exitoso
- **THEN** existe un registro en `audit_log` con `action="change_password"` y el `user_id`

---

### Requirement: Done criterion del Change 04 — verificación end-to-end

El sistema SHALL satisfacer todos los criterios de aceptación de `CHANGES.md §Change 04`: login retorna access+refresh; refresh rota el token viejo; logout invalida ambos tokens; segundo uso del refresh revocado → 401; primer admin es forzado a cambiar password en el primer login; el 6to intento de login en 15 min → 429.

#### Scenario: Flujo completo de primer admin
- **WHEN** se ejecuta el flujo: login → refresh → logout → login (con credenciales iniciales)
- **THEN** login inicial retorna 200 con `must_change_password: true`
- **AND** refresh retorna 200 con nuevo access token
- **AND** logout retorna 200
- **AND** login con el access token del logout (revocado) responde 401
