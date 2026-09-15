# frontend-auth Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: Zustand auth store con access token en memoria

El sistema SHALL tener `frontend/src/stores/auth.store.ts` con un store Zustand que mantiene: `accessToken: string | null`, `user: { id, username, role } | null`, `isLoading: boolean`. El access token MUST almacenarse SOLO en memoria (RAM); NUNCA en localStorage ni sessionStorage (RN-96). El store SHALL exponer: `login(credentials)`, `logout()`, `refreshToken()`, `setToken(token, user)`.

#### Scenario: Access token nunca persiste en storage
- **WHEN** el usuario hace login exitoso
- **THEN** `localStorage` y `sessionStorage` no contienen ningún token

#### Scenario: logout() limpia el store completamente
- **WHEN** se llama `logout()`
- **THEN** `accessToken` es `null`, `user` es `null`, y se llama `POST /auth/logout`

### Requirement: Página Login con manejo de rate limit

El sistema SHALL tener `frontend/src/pages/Login.tsx` con un formulario de username + password. Al enviar, llama `POST /auth/login`. Si la respuesta es 200, guarda el access token en el store y navega al dashboard. Si la respuesta es 401, muestra mensaje de credenciales incorrectas. Si la respuesta es 429, MUST mostrar mensaje de bloqueo temporal indicando que se superaron los intentos permitidos (RN-88).

#### Scenario: Login exitoso redirige al dashboard
- **WHEN** el usuario ingresa credenciales válidas y envía el formulario
- **THEN** el store tiene el access token y el usuario es redirigido a `/`

#### Scenario: Login con credenciales incorrectas muestra error
- **WHEN** el backend retorna 401
- **THEN** se muestra un mensaje de error de credenciales

#### Scenario: Rate limit (429) muestra mensaje de bloqueo
- **WHEN** el backend retorna 429
- **THEN** se muestra un mensaje indicando bloqueo temporal (RN-88); el formulario no permite envío inmediato

#### Scenario: Usuario ya autenticado es redirigido
- **WHEN** se navega a `/login` con una sesión activa
- **THEN** el usuario es redirigido al dashboard sin ver el formulario

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

### Requirement: ProtectedRoute con verificación de sesión y refresh silencioso

El sistema SHALL tener un componente `ProtectedRoute` que, al montar, verifica si hay access token en el store. Si no hay token, intenta un refresh silencioso (`POST /auth/refresh`). Si el refresh es exitoso, continúa. Si falla, redirige a `/login`. El componente MUST mostrar un estado de carga durante el refresh silencioso para evitar flicker (RN-97).

#### Scenario: Recarga de página con cookie válida mantiene sesión
- **WHEN** el usuario recarga la página y la cookie de refresh es válida
- **THEN** el refresh silencioso restaura el access token y el usuario no es redirigido a login

#### Scenario: Recarga sin cookie válida redirige a login
- **WHEN** el usuario recarga la página y no hay cookie de refresh válida
- **THEN** el usuario es redirigido a `/login`

