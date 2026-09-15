## MODIFIED Requirements

### Requirement: Página ForcePasswordChange con scope password_change_only

El sistema SHALL tener `frontend/src/pages/ForcePasswordChange.tsx`. Esta página MUST ser accesible solo cuando el JWT tiene scope `password_change_only` (RN-100). Cualquier ruta protegida que no sea `/change-password` con ese scope MUST redirigir a `/change-password`. El formulario MUST incluir un campo de contraseña actual (`current_password`) además del nuevo password y su confirmación (D-2): el admin de seed conoce la contraseña con la que obtuvo ese scope. El formulario MUST mostrar los requisitos del nuevo password (mínimo 12 caracteres, al menos 1 mayúscula, 1 minúscula y 1 número) y MUST validarlos antes de enviar, con las clases de carácter Unicode equivalentes a las del backend (`\p{Lu}`, `\p{Ll}`, `\p{Nd}`). Si `current_password` está vacío, si algún requisito del nuevo password no se cumple, o la confirmación no coincide, MUST mostrar el error sin enviar la request. Con datos válidos, envía `POST /users/change-password` con `{current_password, new_password}`. En éxito, refresca el token (scope limpio) y redirige al dashboard. Un 401 o 422 del backend MUST mostrarse con el `detail` recibido.

#### Scenario: Token con scope password_change_only redirige desde rutas protegidas
- **WHEN** el usuario tiene un token con `scope=password_change_only` y navega a `/events`
- **THEN** es redirigido automáticamente a `/change-password`

#### Scenario: Cambio exitoso de password navega al dashboard
- **WHEN** el usuario ingresa su contraseña actual, un nuevo password que cumple la política (≥12 chars, mayúscula, minúscula y número) y lo confirma
- **THEN** se envía `POST /users/change-password` con `{current_password, new_password}`
- **AND** el token se refresca (sin scope restrictivo) y el usuario llega al dashboard

#### Scenario: Contraseña actual vacía muestra error de validación
- **WHEN** el usuario deja el campo de contraseña actual vacío
- **THEN** se muestra un error sin enviar la request

#### Scenario: Contraseña actual incorrecta muestra el error del backend
- **WHEN** el backend responde 401 a `POST /users/change-password`
- **THEN** se muestra el `detail` recibido sin navegar

#### Scenario: Password corto muestra error de validación
- **WHEN** el usuario ingresa un password de menos de 12 caracteres
- **THEN** se muestra error de validación sin enviar la request (RN-100)

#### Scenario: Password sin mayúscula, minúscula o número muestra error de validación
- **WHEN** el usuario ingresa un password de 12 o más caracteres al que le falta una mayúscula, una minúscula o un número
- **THEN** se muestra un error que nombra el requisito incumplido
- **AND** no se envía `POST /users/change-password`

#### Scenario: Requisitos visibles en el formulario
- **WHEN** el usuario abre `/change-password`
- **THEN** el formulario lista los requisitos: mínimo 12 caracteres, al menos 1 mayúscula, al menos 1 minúscula y al menos 1 número
