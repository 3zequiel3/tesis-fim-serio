## MODIFIED Requirements

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
