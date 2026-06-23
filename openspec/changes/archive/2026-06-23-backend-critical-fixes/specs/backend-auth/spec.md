## MODIFIED Requirements

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
