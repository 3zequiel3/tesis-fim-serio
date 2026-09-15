## MODIFIED Requirements

### Requirement: POST /users/change-password

El endpoint `POST /users/change-password` SHALL requerir autenticación (acepta tanto scope normal como `password_change_only`) y aceptar `{current_password: str, new_password: str}`:
1. Si el token tiene scope `password_change_only`, omitir la verificación de `current_password` (primer login forzado — el admin no tiene password "anterior" que valide el flujo normal).
2. Si el scope es normal, verificar `current_password` contra el hash actual; si falla, 401 sin modificar `password_hash`.
3. Validar `new_password` contra la política de RN-100: mínimo 12 caracteres y al menos una letra mayúscula, una letra minúscula y un dígito decimal. Si no cumple, MUST responder 422 con `detail` string que nombra el requisito incumplido, sin modificar `password_hash` ni `must_change_password`. El largo se evalúa antes que la complejidad.
4. Actualizar `password_hash` con `hash_password(new_password)` (Argon2id con parámetros C9: `time_cost=3`, `memory_cost=65536`, `parallelism=4`) y `must_change_password=False`.
5. Revocar el access token actual en la blacklist (forzar nuevo login).
6. Limpiar la cookie `refresh_token` con `Max-Age=0`.
7. Escribir `audit_log` con `action="change_password"`, `user_id`.
8. Responder 200 con `{message: "password_changed"}`.

La política de complejidad MUST evaluarse por carácter con clases Unicode: mayúscula (`str.isupper`), minúscula (`str.islower`) y dígito decimal (`str.isdecimal`), de modo que letras como `Ñ` o `á` cuenten en su clase.

#### Scenario: Primer login — cambio forzado con scope password_change_only
- **WHEN** el admin recién creado hace `POST /users/change-password` con un token de scope `password_change_only`
- **AND** provee un `new_password` que cumple la política (≥ 12 caracteres, con mayúscula, minúscula y dígito)
- **THEN** responde 200
- **AND** un login posterior con la nueva password es exitoso
- **AND** el access token anterior ya no es válido (401)

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
