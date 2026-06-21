### Requirement: Zustand auth store con access token en memoria

El sistema SHALL tener `frontend/src/stores/auth.store.ts` con un store Zustand que mantiene: `accessToken: string | null`, `user: { id, username, role } | null`, `isLoading: boolean`. El access token MUST almacenarse SOLO en memoria (RAM); NUNCA en localStorage ni sessionStorage (RN-96). El store SHALL exponer: `login(credentials)`, `logout()`, `refreshToken()`, `setToken(token, user)`.

#### Scenario: Access token nunca persiste en storage
- **WHEN** el usuario hace login exitoso
- **THEN** `localStorage` y `sessionStorage` no contienen ningún token

#### Scenario: logout() limpia el store completamente
- **WHEN** se llama `logout()`
- **THEN** `accessToken` es `null`, `user` es `null`, y se llama `POST /auth/logout`

---

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

---

### Requirement: Página ForcePasswordChange con scope password_change_only

El sistema SHALL tener `frontend/src/pages/ForcePasswordChange.tsx`. Esta página MUST ser accesible solo cuando el JWT tiene scope `password_change_only` (RN-100). Cualquier ruta protegida que no sea `/change-password` con ese scope MUST redirigir a `/change-password`. El formulario envía `POST /users/change-password` con el nuevo password (≥12 chars). En éxito, refresca el token (scope limpio) y redirige al dashboard.

#### Scenario: Token con scope password_change_only redirige desde rutas protegidas
- **WHEN** el usuario tiene un token con `scope=password_change_only` y navega a `/events`
- **THEN** es redirigido automáticamente a `/change-password`

#### Scenario: Cambio exitoso de password navega al dashboard
- **WHEN** el usuario ingresa un nuevo password válido (≥12 chars) y confirma
- **THEN** el token se refresca (sin scope restrictivo) y el usuario llega al dashboard

#### Scenario: Password corto muestra error de validación
- **WHEN** el usuario ingresa un password de menos de 12 caracteres
- **THEN** se muestra error de validación sin enviar la request (RN-100)

---

### Requirement: ProtectedRoute con verificación de sesión y refresh silencioso

El sistema SHALL tener un componente `ProtectedRoute` que, al montar, verifica si hay access token en el store. Si no hay token, intenta un refresh silencioso (`POST /auth/refresh`). Si el refresh es exitoso, continúa. Si falla, redirige a `/login`. El componente MUST mostrar un estado de carga durante el refresh silencioso para evitar flicker (RN-97).

#### Scenario: Recarga de página con cookie válida mantiene sesión
- **WHEN** el usuario recarga la página y la cookie de refresh es válida
- **THEN** el refresh silencioso restaura el access token y el usuario no es redirigido a login

#### Scenario: Recarga sin cookie válida redirige a login
- **WHEN** el usuario recarga la página y no hay cookie de refresh válida
- **THEN** el usuario es redirigido a `/login`
