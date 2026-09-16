# Spec: backend-auth

## Purpose
Implementar autenticación JWT dual-key con rotación de refresh tokens, scope-gating, y rate-limiting de login.
## Requirements
### Requirement: core/security.py — Firma y validación JWT dual-key

El sistema SHALL implementar `backend/app/core/security.py` con las funciones:
- `create_access_token(user_id, username, must_change_password, jti) -> str`: firma un JWT con `JWT_SECRET_CURRENT`, `alg=HS256`, `exp=now+15min`, claims `sub=user_id`, `username`, `jti`, `type="access"`, y `scope="password_change_only"` si `must_change_password=True`. El claim `type="access"` MUST estar presente en todo access token (C6).
- `create_refresh_token(user_id, jti) -> str`: firma un JWT con `JWT_SECRET_CURRENT`, `exp=now+7days`, claims `sub=user_id`, `jti`, `type="refresh"`.
- `decode_token(token) -> dict`: intenta verificar con `JWT_SECRET_CURRENT`; si falla, intenta con `JWT_SECRET_PREVIOUS`; si ambas fallan, lanza `JWTError`. Retorna el payload. `decode_token` NO discrimina por `type` — la verificación de tipo es responsabilidad del consumidor del token.
- `hash_password(plain) -> str`: Argon2id vía `argon2-cffi`.
- `verify_password(plain, hashed) -> bool`: Argon2id verify.

#### Scenario: Token firmado con CURRENT es válido
- **WHEN** se llama `create_access_token(...)` y luego `decode_token(token)`
- **THEN** el payload contiene `sub`, `jti`, `username`, `exp`
- **AND** no se lanza excepción

#### Scenario: Access token lleva el claim type=access
- **WHEN** se llama `create_access_token(...)` y luego `decode_token(token)`
- **THEN** el payload contiene `type` igual a `"access"`

#### Scenario: Refresh token lleva el claim type=refresh
- **WHEN** se llama `create_refresh_token(...)` y luego `decode_token(token)`
- **THEN** el payload contiene `type` igual a `"refresh"`

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

### Requirement: POST /auth/login

El endpoint `POST /auth/login` SHALL aceptar JSON `{username: str, password: str}` y:
1. Verificar rate limit login: si el counter `fim:rl:login:<username>:<ip>` >= 5, responder 429 con `Retry-After: 900`.
2. Incrementar el counter con `INCR` y fijar el TTL de forma idempotente en cada incremento (`EXPIRE 900` en toda invocación, no solo cuando `count == 1`). El fallo o la ausencia del `EXPIRE` MUST NOT dejar la key sin TTL: la key de rate limit siempre MUST tener un TTL acotado tras un incremento exitoso, de modo que un incremento con `EXPIRE` fallido no produzca un lockout permanente del `(user+IP)`.
3. Buscar el usuario por username; si no existe o `verify_password` falla, responder 401 con `WWW-Authenticate: Bearer`.
4. Si `is_active=False`, responder 403.
5. Generar `jti_access` y `jti_refresh` como UUID v4.
6. Emitir access token (15 min) y refresh token (7 días).
7. Responder 200 con body `{access_token: str, token_type: "bearer", must_change_password: bool}` y `Set-Cookie: refresh_token=<refresh>; HttpOnly; Secure; SameSite=Strict; Path=/auth/refresh`.
8. Escribir `audit_log` con `action="login"`, `user_id`, `ip`.

El rate limit login es una ventana fija (fixed-window) de 900 s, no sliding-window: el docstring y la documentación del helper MUST describirlo correctamente como fixed-window.

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

#### Scenario: TTL siempre presente tras incrementar el counter
- **WHEN** el counter de rate limit se incrementa en un intento con `count > 1`
- **THEN** la key `fim:rl:login:<username>:<ip>` tiene un TTL acotado (> 0), no `-1` (sin expiración)
- **AND** el counter expira automáticamente al vencer la ventana, evitando un lockout permanente

#### Scenario: audit_log en login exitoso
- **WHEN** el login es exitoso
- **THEN** existe un registro en `audit_log` con `action="login"` y el `user_id` correspondiente

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

### Requirement: get_current_user dependency — validación y blacklist

La función `get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)) -> User` SHALL:
1. Llamar `decode_token(token)`; si falla, 401.
2. Verificar que `payload.get("type") == "access"`; si el token tiene cualquier otro `type` (o no tiene `type`), responder 401 (`token_type_invalid`). Esta verificación MUST ocurrir antes de cualquier otra validación y cubre todos los endpoints que dependen de `get_current_user`, cerrando el uso de un refresh token como access token (C6).
3. Verificar `EXISTS fim:blacklist:<jti>` en Valkey; si está, 401.
4. Verificar rate limit API: `fim:rl:api:<user_id>` con límite 100/min; si supera, 429.
5. Cargar el `User` de la DB; si no existe o `is_active=False`, 401.
6. Retornar el `User`.

#### Scenario: Token válido retorna el usuario
- **WHEN** se llama `get_current_user` con un access token válido (`type=access`) y no revocado
- **THEN** retorna el `User` correspondiente sin excepción

#### Scenario: Refresh token usado como access token — 401
- **WHEN** se presenta un refresh token (`type=refresh`) como Bearer credential a `get_current_user`
- **THEN** lanza HTTPException 401 con detalle `token_type_invalid`
- **AND** la verificación falla aunque el refresh token tenga firma válida y no esté en la blacklist

#### Scenario: Token sin claim type — 401
- **WHEN** se presenta a `get_current_user` un token con firma válida pero sin claim `type`
- **THEN** lanza HTTPException 401 con detalle `token_type_invalid`

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

### Requirement: scope password_change_only — bloqueo de acceso general

La dependency `require_full_access(user: User = Depends(get_current_user)) -> User` SHALL verificar que el token no tiene `scope="password_change_only"`. Si lo tiene, responde 403 con `{detail: "password_change_required"}`. Todos los endpoints protegidos normales SHALL usar `Depends(require_full_access)` en vez de `Depends(get_current_user)` directamente.

#### Scenario: Token con scope password_change_only bloqueado en endpoints normales
- **WHEN** se usa un access token con `scope="password_change_only"` en cualquier endpoint normal (ej. `GET /events`)
- **THEN** responde 403 con `detail="password_change_required"`

#### Scenario: Token normal no está bloqueado
- **WHEN** se usa un access token sin scope especial
- **THEN** el endpoint procede normalmente

### Requirement: POST /users/change-password

El endpoint `POST /users/change-password` SHALL requerir autenticación (acepta tanto scope normal como `password_change_only`) y aceptar `{current_password: str, new_password: str}`:
1. Independientemente del scope del token (normal o `password_change_only`), verificar `current_password` contra el hash actual; si falla o está ausente, 401 sin modificar `password_hash`. El admin de seed conoce su contraseña actual: es la que usó para obtener el token, incluido el de scope `password_change_only` del primer login (D-2).
2. Validar `new_password` contra la política de RN-100: mínimo 12 caracteres y al menos una letra mayúscula, una letra minúscula y un dígito decimal. Si no cumple, MUST responder 422 con `detail` string que nombra el requisito incumplido, sin modificar `password_hash` ni `must_change_password`. El largo se evalúa antes que la complejidad.
3. Actualizar `password_hash` con `hash_password(new_password)` (Argon2id con parámetros C9: `time_cost=3`, `memory_cost=65536`, `parallelism=4`) y `must_change_password=False`.
4. Revocar el access token actual en la blacklist (forzar nuevo login).
5. Limpiar la cookie `refresh_token` con `Max-Age=0`.
6. Escribir `audit_log` con `action="change_password"`, `user_id`.
7. Responder 200 con `{message: "password_changed"}`.

La política de complejidad MUST evaluarse por carácter con clases Unicode: mayúscula (`str.isupper`), minúscula (`str.islower`) y dígito decimal (`str.isdecimal`), de modo que letras como `Ñ` o `á` cuenten en su clase.

#### Scenario: Primer login — cambio forzado con scope password_change_only
- **WHEN** el admin recién creado hace `POST /users/change-password` con un token de scope `password_change_only`, provee `current_password` correcto (la password de seed)
- **AND** provee un `new_password` que cumple la política (≥ 12 caracteres, con mayúscula, minúscula y dígito)
- **THEN** responde 200
- **AND** un login posterior con la nueva password es exitoso
- **AND** el access token anterior ya no es válido (401)

#### Scenario: Cambio forzado con current_password incorrecto — 401
- **WHEN** el admin recién creado hace `POST /users/change-password` con un token de scope `password_change_only` y `current_password` incorrecto o ausente
- **THEN** responde 401
- **AND** `password_hash` no cambia
- **AND** `must_change_password` sigue en `True`

#### Scenario: Cambio normal con current_password correcto
- **WHEN** un usuario autenticado (scope normal) hace `POST /users/change-password` con `current_password` correcto y un `new_password` que cumple la política
- **THEN** responde 200
- **AND** `must_change_password` queda en `False`

#### Scenario: new_password < 12 caracteres — 422
- **WHEN** se envía `new_password` con 11 caracteres o menos
- **THEN** responde 422

#### Scenario: new_password sin mayúscula — 422
- **WHEN** se envía un `new_password` de 12 o más caracteres con minúsculas y dígitos pero sin ninguna mayúscula
- **THEN** responde 422 con un `detail` string que menciona la complejidad
- **AND** `password_hash` no cambia

#### Scenario: new_password sin minúscula — 422
- **WHEN** se envía un `new_password` de 12 o más caracteres con mayúsculas y dígitos pero sin ninguna minúscula
- **THEN** responde 422
- **AND** `password_hash` no cambia

#### Scenario: new_password sin dígito — 422
- **WHEN** se envía un `new_password` de 12 o más caracteres con mayúsculas y minúsculas pero sin ningún dígito
- **THEN** responde 422
- **AND** `password_hash` no cambia

#### Scenario: Mayúscula no ASCII cuenta para la complejidad
- **WHEN** se envía un `new_password` de 12 o más caracteres cuya única mayúscula es `Ñ`, con minúsculas y dígitos
- **THEN** responde 200

#### Scenario: current_password incorrecto (scope normal) — 401
- **WHEN** el usuario envía `current_password` incorrecto
- **THEN** responde 401
- **AND** `password_hash` no cambia

#### Scenario: La nueva contraseña queda hasheada con Argon2id C9
- **WHEN** el cambio de password es exitoso
- **THEN** el `password_hash` persistido comienza con `$argon2id$` y codifica `m=65536,t=3,p=4`
- **AND** verifica contra el nuevo password y no contra el anterior

#### Scenario: audit_log en change_password
- **WHEN** el cambio de password es exitoso
- **THEN** existe un registro en `audit_log` con `action="change_password"` y el `user_id`

#### Scenario: Cambio no completado se vuelve a exigir
- **WHEN** el admin seed hace login, no completa el cambio y vuelve a hacer login
- **THEN** la segunda respuesta de login incluye `must_change_password: true`
- **AND** el access token emitido tiene scope `password_change_only`

### Requirement: Done criterion del Change 04 — verificación end-to-end

El sistema SHALL satisfacer todos los criterios de aceptación de `CHANGES.md §Change 04`: login retorna access+refresh; refresh rota el token viejo; logout invalida ambos tokens; segundo uso del refresh revocado → 401; primer admin es forzado a cambiar password en el primer login; el 6to intento de login en 15 min → 429.

#### Scenario: Flujo completo de primer admin
- **WHEN** se ejecuta el flujo: login → refresh → logout → login (con credenciales iniciales)
- **THEN** login inicial retorna 200 con `must_change_password: true`
- **AND** refresh retorna 200 con nuevo access token
- **AND** logout retorna 200
- **AND** login con el access token del logout (revocado) responde 401

### Requirement: Atributo `Secure` de la cookie de refresh derivado del modo TLS de la consola (D55/RN-149)

`Settings` SHALL exponer `console_tls_mode` con dominio cerrado `off` | `self_signed` | `provided` y default `off`, leído de `CONSOLE_TLS_MODE`; un valor fuera del dominio SHALL abortar el arranque con `ValidationError`. Toda emisión de la cookie `refresh_token` con valor (login, rotación en `/auth/refresh`) SHALL llevar el atributo `Secure` si y sólo si `console_tls_mode` es distinto de `off`. El atributo SHALL NOT derivarse de `ENVIRONMENT`, que queda sin efecto sobre la seguridad de la cookie. Al arrancar, el backend SHALL registrar el modo en un log estructurado; con `off`, ese log SHALL tener nivel `warning` e indicar que credenciales y tokens viajan en claro.

#### Scenario: Modo sin TLS con ENVIRONMENT de producción
- **WHEN** `CONSOLE_TLS_MODE=off` y `ENVIRONMENT=prod`, y se hace login exitoso
- **THEN** la cookie `refresh_token` no lleva `Secure`

#### Scenario: Modo autofirmado con ENVIRONMENT de desarrollo
- **WHEN** `CONSOLE_TLS_MODE=self_signed` y `ENVIRONMENT=dev`, y se hace login exitoso
- **THEN** la cookie `refresh_token` lleva `Secure`

#### Scenario: Rotación en modo con certificado provisto
- **WHEN** `CONSOLE_TLS_MODE=provided` y se hace `POST /auth/refresh` con una cookie válida
- **THEN** la cookie rotada lleva `Secure`

#### Scenario: Valor inválido
- **WHEN** `CONSOLE_TLS_MODE=https`
- **THEN** la importación de `app.core.config` lanza `ValidationError` que nombra `console_tls_mode`

#### Scenario: Advertencia en modo sin TLS
- **WHEN** el backend arranca con `CONSOLE_TLS_MODE=off`
- **THEN** se emite un log de nivel `warning` con el modo y la advertencia de tráfico en claro

### Requirement: Advertencia y CLI de reset cuando `ADMIN_PASSWORD` no verifica contra el admin existente (D56/RN-150, hallazgo 14.4)

`seed_admin()` SHALL crear el admin sólo si la tabla `users` está vacía (sin cambios). Si ya existe un usuario con `username=settings.admin_username` y `ADMIN_PASSWORD` no está vacío y no verifica contra su `password_hash` almacenado, `seed_admin()` SHALL registrar un log de nivel `warning` con evento `seed_admin.env_password_ignored` y el `username`, SHALL NOT modificar la contraseña almacenada, y SHALL continuar el arranque sin abortar. Con `ADMIN_PASSWORD` vacío, o si verifica contra el hash existente, SHALL NOT emitirse el warning.

El sistema SHALL exponer un CLI soportado, `python -m app.modules.auth.cli reset-admin-password`, que aplica el `ADMIN_PASSWORD` vigente al usuario `settings.admin_username` (mismo hashing Argon2id que `seed_admin()`), fuerza `must_change_password=True` (RN-62, RN-100/W20) y escribe un registro en `audit_log` (RN-94) con `action="reset_admin_password_cli"`, `user_id` del propio admin y `detail` con el username. Con `ADMIN_PASSWORD` vacío o sin un usuario `settings.admin_username`, SHALL terminar con exit distinto de 0 sin escribir nada, nombrando la causa.

#### Scenario: Warning sin modificar la contraseña
- **WHEN** el backend arranca con un admin ya existente cuyo `password_hash` no verifica contra `ADMIN_PASSWORD`
- **THEN** se emite un log `warning` `seed_admin.env_password_ignored` con el `username`
- **AND** el `password_hash` almacenado no cambia

#### Scenario: Sin warning cuando la contraseña coincide
- **WHEN** el backend arranca con un admin ya existente cuyo `password_hash` sí verifica contra `ADMIN_PASSWORD`
- **THEN** no se emite el warning `seed_admin.env_password_ignored`

#### Scenario: CLI aplica la contraseña y fuerza el cambio
- **WHEN** se ejecuta `python -m app.modules.auth.cli reset-admin-password` con `ADMIN_PASSWORD` configurado y el usuario admin existente
- **THEN** el CLI termina con exit 0
- **AND** el login con la nueva `ADMIN_PASSWORD` es exitoso y `must_change_password` es `true`
- **AND** existe un registro en `audit_log` con `action="reset_admin_password_cli"` y el `user_id` del admin

#### Scenario: CLI sin `ADMIN_PASSWORD`
- **WHEN** se ejecuta el CLI sin `ADMIN_PASSWORD` configurado
- **THEN** termina con exit distinto de 0 sin escribir nada, nombrando `ADMIN_PASSWORD`

