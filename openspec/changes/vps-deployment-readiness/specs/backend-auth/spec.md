## MODIFIED Requirements

### Requirement: POST /auth/login

El endpoint `POST /auth/login` SHALL aceptar JSON `{username: str, password: str}` y:
1. Verificar rate limit login: si el counter `fim:rl:login:<username>:<ip>` >= 5, responder 429 con `Retry-After: 900`.
2. Incrementar el counter con `INCR` y `EXPIRE 900` en Valkey.
3. Buscar el usuario por username; si no existe o `verify_password` falla, responder 401 con `WWW-Authenticate: Bearer`.
4. Si `is_active=False`, responder 403.
5. Generar `jti_access` y `jti_refresh` como UUID v4.
6. Emitir access token (15 min) y refresh token (7 días).
7. Responder 200 con body `{access_token: str, token_type: "bearer", must_change_password: bool}` y `Set-Cookie: refresh_token=<refresh>; HttpOnly; SameSite=Strict; Path=/auth/refresh`, con el atributo `Secure` presente si y sólo si `CONSOLE_TLS_MODE` es distinto de `off` (ver requisito "Atributo `Secure` de la cookie de refresh derivado del modo TLS de la consola").
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

## ADDED Requirements

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
