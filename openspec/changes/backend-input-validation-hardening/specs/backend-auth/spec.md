## MODIFIED Requirements

### Requirement: POST /auth/login

El endpoint `POST /auth/login` SHALL aceptar JSON `{username: str, password: str}` y:
1. Resolver la `ip` del cliente según el requisito «Resolución de la IP real del cliente detrás del proxy de confianza».
2. Verificar el rate limit login **antes** de verificar la contraseña: si el counter `fim:rl:login:<username>:<ip>` es mayor o igual a `rate_limit_login_attempts` (5), responder 429 con `Retry-After` igual al TTL restante de la key (en segundos, mínimo 1) y `detail` `{"code": "login_rate_limited", "message": <texto en español>}`, sin evaluar la contraseña.
3. Buscar el usuario por username; si no existe o `verify_password` falla, incrementar el counter con `INCR` y fijar el TTL con `EXPIRE <rate_limit_login_window_seconds> NX` en cada incremento, y responder 401 con `WWW-Authenticate: Bearer` y `detail` `{"code": "invalid_credentials", "message": <texto en español>}`. El fallo o la ausencia del `EXPIRE` MUST NOT dejar la key sin TTL: la key de rate limit siempre MUST tener un TTL acotado tras un incremento exitoso, de modo que un incremento con `EXPIRE` fallido no produzca un lockout permanente del `(user+IP)`.
4. Si `is_active=False`, responder 403 con `detail` `{"code": "account_disabled", "message": <texto en español>}`.
5. Con credenciales correctas, borrar la key del counter (`DEL`): un login exitoso MUST NOT incrementar el counter.
6. Generar `jti_access` y `jti_refresh` como UUID v4.
7. Emitir access token (15 min) y refresh token (7 días).
8. Responder 200 con body `{access_token: str, token_type: "bearer", must_change_password: bool}` y `Set-Cookie: refresh_token=<refresh>; HttpOnly; Secure; SameSite=Strict; Path=/auth/refresh`.
9. Escribir `audit_log` con `action="login"`, `user_id`, `ip`.

El rate limit login es una ventana fija (fixed-window) de `rate_limit_login_window_seconds` (900 s por defecto), no sliding-window: el docstring y la documentación del helper MUST describirlo correctamente como fixed-window y MUST decir que cuenta sólo intentos fallidos (D92/RN-186). Pedidos simultáneos pueden superar el umbral en a lo sumo la cantidad de pedidos en vuelo; se acepta.

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
- **THEN** responde 401 con `detail.code == "invalid_credentials"` y un `detail.message` en español

#### Scenario: Rate limit login — 6to intento bloqueado
- **WHEN** se hacen 5 intentos de login fallidos (usuario + IP)
- **AND** se hace un 6to intento, aun con la contraseña correcta
- **THEN** el 6to intento responde 429 con `detail.code == "login_rate_limited"`
- **AND** el header `Retry-After` está presente y es igual al TTL restante de la key

#### Scenario: Los logins exitosos no cuentan
- **WHEN** se hacen 10 logins exitosos seguidos con el mismo usuario e IP
- **THEN** los 10 responden 200
- **AND** la key `fim:rl:login:<username>:<ip>` no existe

#### Scenario: Un login exitoso reinicia el contador
- **WHEN** se hacen 4 intentos fallidos y luego un login exitoso (usuario + IP)
- **AND** se hacen 4 intentos fallidos más
- **THEN** ninguno de esos pedidos responde 429

#### Scenario: Otra IP no queda bloqueada
- **WHEN** se hacen 5 intentos fallidos para `admin` desde la IP `203.0.113.7`
- **AND** se hace un login correcto de `admin` desde la IP `198.51.100.9`
- **THEN** el segundo responde 200

#### Scenario: TTL siempre presente tras incrementar el counter
- **WHEN** el counter de rate limit se incrementa en un intento fallido con `count > 1`
- **THEN** la key `fim:rl:login:<username>:<ip>` tiene un TTL acotado (> 0), no `-1` (sin expiración)
- **AND** el counter expira automáticamente al vencer la ventana, evitando un lockout permanente

#### Scenario: audit_log en login exitoso
- **WHEN** el login es exitoso
- **THEN** existe un registro en `audit_log` con `action="login"` y el `user_id` correspondiente

### Requirement: POST /users/change-password

El endpoint `POST /users/change-password` SHALL requerir autenticación (acepta tanto scope normal como `password_change_only`) y aceptar `{current_password: str, new_password: str}`:
1. Independientemente del scope del token (normal o `password_change_only`), verificar `current_password` contra el hash actual; si falla o está ausente, MUST responder 401 con `detail` `{"code": "current_password_invalid", "message": <texto en español>}` sin modificar `password_hash`. El admin de seed conoce su contraseña actual: es la que usó para obtener el token, incluido el de scope `password_change_only` del primer login (D-2).
2. Validar `new_password` contra la política de RN-100: mínimo 12 caracteres y al menos una letra mayúscula, una letra minúscula y un dígito decimal. Si no cumple, MUST responder 422 con `detail` `{"code": "password_policy", "message": <texto en español que nombra el requisito incumplido>}`, sin modificar `password_hash` ni `must_change_password`. El largo se evalúa antes que la complejidad.
3. Si `new_password` verifica contra el hash vigente, MUST responder 422 con `detail` `{"code": "password_reuse", "message": <texto en español>}`, sin modificar `password_hash` ni `must_change_password` (D89/RN-183).
4. Actualizar `password_hash` con `hash_password(new_password)` (Argon2id con parámetros C9: `time_cost=3`, `memory_cost=65536`, `parallelism=4`) y `must_change_password=False`.
5. Revocar el access token actual y el refresh token en la blacklist (forzar nuevo login). La respuesta MUST NOT emitir tokens nuevos (D89/RN-183).
6. Limpiar la cookie `refresh_token` con `Max-Age=0`.
7. Escribir `audit_log` con `action="change_password"`, `user_id`.
8. Responder 200 con `{message: "password_changed"}`.

La política de complejidad MUST evaluarse por carácter con clases Unicode: mayúscula (`str.isupper`), minúscula (`str.islower`) y dígito decimal (`str.isdecimal`), de modo que letras como `Ñ` o `á` cuenten en su clase. La creación de admins adicionales (C20) usa la misma función de política y MUST recibir los mismos mensajes en español.

#### Scenario: Primer login — cambio forzado con scope password_change_only
- **WHEN** el admin recién creado hace `POST /users/change-password` con un token de scope `password_change_only`, provee `current_password` correcto (la password de seed)
- **AND** provee un `new_password` distinto que cumple la política (≥ 12 caracteres, con mayúscula, minúscula y dígito)
- **THEN** responde 200 sin `access_token` en el body
- **AND** un login posterior con la nueva password es exitoso
- **AND** el access token anterior ya no es válido (401)
- **AND** un `POST /auth/refresh` con el refresh token anterior responde 401

#### Scenario: Cambio forzado con current_password incorrecto — 401
- **WHEN** el admin recién creado hace `POST /users/change-password` con un token de scope `password_change_only` y `current_password` incorrecto o ausente
- **THEN** responde 401 con `detail.code == "current_password_invalid"` y un `detail.message` en español
- **AND** `password_hash` no cambia
- **AND** `must_change_password` sigue en `True`

#### Scenario: Nueva contraseña igual a la actual — 422
- **WHEN** el admin envía `new_password` igual a `current_password` y ésta cumple la política
- **THEN** responde 422 con `detail.code == "password_reuse"`
- **AND** `password_hash` no cambia y `must_change_password` conserva su valor
- **AND** el access token sigue siendo válido

#### Scenario: Cambio normal con current_password correcto
- **WHEN** un usuario autenticado (scope normal) hace `POST /users/change-password` con `current_password` correcto y un `new_password` distinto que cumple la política
- **THEN** responde 200
- **AND** `must_change_password` queda en `False`

#### Scenario: new_password < 12 caracteres — 422
- **WHEN** se envía `new_password` con 11 caracteres o menos
- **THEN** responde 422 con `detail.code == "password_policy"` y un `detail.message` en español que menciona los 12 caracteres

#### Scenario: new_password sin mayúscula — 422
- **WHEN** se envía un `new_password` de 12 o más caracteres con minúsculas y dígitos pero sin ninguna mayúscula
- **THEN** responde 422 con `detail.code == "password_policy"` y un `detail.message` que menciona la mayúscula
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

## ADDED Requirements

### Requirement: Resolución de la IP real del cliente detrás del proxy de confianza

El backend SHALL resolver la IP del cliente con un único helper (`backend/app/core/client_ip.py`) usado por el login y por su registro en `audit_log` (D92/RN-186). Si el par TCP (`request.client.host`) pertenece a alguna red de `trusted_proxy_cidrs`, la IP SHALL ser la entrada más a la derecha de `X-Forwarded-For` que no pertenezca a esas redes; si el header falta, no tiene entradas válidas o todas son de confianza, SHALL usarse el par TCP. Si el par TCP no es de confianza, `X-Forwarded-For` MUST ignorarse. El setting `trusted_proxy_cidrs` (variable `TRUSTED_PROXY_CIDRS`, lista separada por comas) SHALL tener default `127.0.0.1/32,::1/128`; un valor que no sea una red IP válida MUST impedir el arranque con un mensaje que nombra la entrada. Los compose del producto y de laboratorio SHALL fijarlo a `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`.

#### Scenario: Detrás del nginx de confianza se usa la IP del cliente
- **WHEN** el par TCP es `172.18.0.5`, `trusted_proxy_cidrs` incluye `172.16.0.0/12` y `X-Forwarded-For` es `203.0.113.7`
- **THEN** la IP resuelta es `203.0.113.7`

#### Scenario: Una entrada falsificada a la izquierda se ignora
- **WHEN** el par TCP es de confianza y `X-Forwarded-For` es `1.2.3.4, 203.0.113.7`
- **THEN** la IP resuelta es `203.0.113.7`

#### Scenario: Un par que no es de confianza no puede falsear la IP
- **WHEN** el par TCP es `198.51.100.9`, fuera de `trusted_proxy_cidrs`, y envía `X-Forwarded-For: 203.0.113.7`
- **THEN** la IP resuelta es `198.51.100.9`

#### Scenario: Header ausente o inválido
- **WHEN** el par TCP es de confianza y `X-Forwarded-For` falta o contiene sólo valores que no son IP
- **THEN** la IP resuelta es el par TCP

#### Scenario: Setting inválido impide el arranque
- **WHEN** `TRUSTED_PROXY_CIDRS=10.0.0.0/8,no-es-una-red`
- **THEN** la carga de settings falla con un mensaje que nombra `no-es-una-red`

### Requirement: Contrato del cuerpo de error de la API

Toda respuesta de error del backend SHALL tener la forma de FastAPI `{"detail": ...}` (D90/RN-184), con `detail` igual a: un string (forma heredada); un objeto `{"code": <snake_case>, "message": <texto en español>, ...campos adicionales}`; o la lista de errores de validación de Pydantic de un `422` automático. Los errores introducidos o modificados por esta change (reglas, `watch_paths`, login y cambio de contraseña) MUST usar la forma de objeto con `code` y `message`. Los errores existentes que ya emiten un objeto con `code` (`absent_confirmation_required`, `pending_events_exist` con `count`, `release_in_progress`, `quarantine_not_releasable`) MUST conservar su `code` y sus campos. Un test de contrato SHALL fijar esa forma para cada uno de los códigos nuevos.

#### Scenario: Un error nuevo trae código y mensaje
- **WHEN** un endpoint de esta change rechaza una entrada
- **THEN** el body es `{"detail": {"code": <str>, "message": <str>}}` con `code` en minúsculas snake_case
- **AND** el body no tiene `code` en el nivel raíz

#### Scenario: Los códigos existentes no cambian
- **WHEN** un `POST /agents/{id}/rescan` sin `force` encuentra eventos pending
- **THEN** responde 409 con `detail == {"code": "pending_events_exist", "count": <int>}`
