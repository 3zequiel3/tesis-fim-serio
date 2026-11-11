## MODIFIED Requirements

### Requirement: Página Login con manejo de rate limit

El sistema SHALL tener `frontend/src/pages/Login.tsx` con un formulario de username + password. Al enviar, llama `POST /auth/login`. Si la respuesta es 200, guarda el access token en el store y navega al destino original guardado en `location.state.from` por `ProtectedRoute` si existe y es una ruta interna de la consola, o al dashboard si no. Si la respuesta es 401, muestra el `detail.message` recibido o, si falta, un mensaje de credenciales incorrectas. Si la respuesta es 429, MUST mostrar un mensaje de bloqueo temporal indicando que se superaron los intentos fallidos permitidos y el tiempo de espera tomado de `Retry-After` (RN-88, D92/RN-186), y MUST deshabilitar el envío hasta que ese tiempo venza. Los mensajes se leen con el lector único de errores (D90/RN-184). Si llega con `location.state.notice` (cambio de contraseña o sesión vencida), MUST mostrar ese aviso sobre el formulario.

#### Scenario: Login exitoso redirige al dashboard
- **WHEN** el usuario ingresa credenciales válidas y envía el formulario sin un destino previo
- **THEN** el store tiene el access token y el usuario es redirigido a `/`

#### Scenario: Login exitoso vuelve al destino original
- **WHEN** el usuario fue redirigido a `/login` desde `/events/42` y luego ingresa credenciales válidas
- **THEN** el usuario llega a `/events/42`

#### Scenario: Un destino externo se ignora
- **WHEN** `location.state.from` no es una ruta interna (p. ej. `//evil.example`)
- **THEN** el usuario llega al dashboard

#### Scenario: Login con credenciales incorrectas muestra error
- **WHEN** el backend retorna 401 con `detail` `{code: "invalid_credentials", message: "Usuario o contraseña incorrectos."}`
- **THEN** se muestra «Usuario o contraseña incorrectos.»

#### Scenario: Rate limit (429) muestra mensaje de bloqueo
- **WHEN** el backend retorna 429 con `Retry-After: 120`
- **THEN** se muestra un mensaje de bloqueo temporal que menciona la espera (RN-88); el botón de envío queda deshabilitado hasta que vence

#### Scenario: Aviso recibido por navegación
- **WHEN** se llega a `/login` con `state.notice = "Contraseña actualizada. Ingresá con la contraseña nueva."`
- **THEN** el aviso se muestra sobre el formulario

#### Scenario: Usuario ya autenticado es redirigido
- **WHEN** se navega a `/login` con una sesión activa
- **THEN** el usuario es redirigido al dashboard sin ver el formulario

### Requirement: Página ForcePasswordChange con scope password_change_only

El sistema SHALL tener `frontend/src/pages/ForcePasswordChange.tsx`. Esta página MUST ser accesible solo cuando el JWT tiene scope `password_change_only` (RN-100). Cualquier ruta protegida que no sea `/change-password` con ese scope MUST redirigir a `/change-password` antes de montar la página destino, de modo que ninguna consulta de esa página llegue a enviarse (D93/RN-187). El formulario MUST incluir un campo de contraseña actual (`current_password`) además del nuevo password y su confirmación (D-2): el admin de seed conoce la contraseña con la que obtuvo ese scope. El formulario MUST mostrar los requisitos del nuevo password (mínimo 12 caracteres, al menos 1 mayúscula, 1 minúscula y 1 número) y MUST validarlos antes de enviar, con las clases de carácter Unicode equivalentes a las del backend (`\p{Lu}`, `\p{Ll}`, `\p{Nd}`). Si `current_password` está vacío, si algún requisito del nuevo password no se cumple, si el nuevo password es igual al actual, o la confirmación no coincide, MUST mostrar el error sin enviar la request. Con datos válidos, envía `POST /users/change-password` con `{current_password, new_password}`. En éxito, el backend ya revocó la sesión (D89/RN-183): el frontend MUST NOT llamar a `POST /auth/refresh`; MUST limpiar el store de auth, vaciar la caché de consultas y navegar a `/login` con el aviso «Contraseña actualizada. Ingresá con la contraseña nueva.». Un 401 o 422 del backend MUST mostrarse con el `detail.message` recibido (D90/RN-184), sin navegar. El formulario MUST deshabilitar el envío mientras la request está en curso.

#### Scenario: Token con scope password_change_only redirige desde rutas protegidas
- **WHEN** el usuario tiene un token con `scope=password_change_only` y navega a `/events`
- **THEN** es redirigido automáticamente a `/change-password`
- **AND** no se envía ningún `GET /events` ni `GET /health/components` durante la redirección

#### Scenario: Cambio exitoso lleva al login con aviso
- **WHEN** el usuario ingresa su contraseña actual, un nuevo password distinto que cumple la política y lo confirma, y el backend responde 200
- **THEN** se envía `POST /users/change-password` con `{current_password, new_password}`
- **AND** no se envía `POST /auth/refresh`
- **AND** el store de auth queda vacío y el usuario llega a `/login` con el aviso de contraseña actualizada

#### Scenario: Contraseña actual vacía muestra error de validación
- **WHEN** el usuario deja el campo de contraseña actual vacío
- **THEN** se muestra un error sin enviar la request

#### Scenario: Nueva contraseña igual a la actual
- **WHEN** el usuario ingresa como nueva la misma contraseña que la actual
- **THEN** se muestra un error sin enviar la request

#### Scenario: Contraseña actual incorrecta muestra el error del backend
- **WHEN** el backend responde 401 con `detail` `{code: "current_password_invalid", message: "La contraseña actual es incorrecta."}`
- **THEN** se muestra «La contraseña actual es incorrecta.» sin navegar

#### Scenario: Reutilización rechazada por el backend
- **WHEN** el backend responde 422 con `detail.code == "password_reuse"`
- **THEN** se muestra el `detail.message` recibido sin navegar

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

El sistema SHALL tener un componente `ProtectedRoute` que, al montar, verifica si hay access token en el store. Si no hay token, intenta un refresh silencioso (`POST /auth/refresh`). Si el refresh es exitoso, continúa. Si falla, redirige a `/login` guardando la ruta pedida en `state.from`. El componente MUST mostrar un estado de carga sólo durante esa verificación inicial para evitar flicker (RN-97). La renovación proactiva del token previa a su vencimiento MUST ejecutarse en segundo plano sin modificar el indicador de carga que observa `ProtectedRoute`, de modo que nunca desmonte las rutas hijas ni pierda el estado de la página (modales abiertos, selección, filtros) (D93/RN-187). Si una renovación en segundo plano o un `401` posterior determinan que la sesión venció, el store y la caché de TanStack Query MUST vaciarse y el usuario MUST llegar a `/login` con `state.from` y el aviso «Tu sesión venció. Ingresá de nuevo.». Con un token de scope `password_change_only`, MUST redirigir a `/change-password` antes de renderizar las rutas hijas.

#### Scenario: Recarga de página con cookie válida mantiene sesión
- **WHEN** el usuario recarga la página y la cookie de refresh es válida
- **THEN** el refresh silencioso restaura el access token y el usuario no es redirigido a login

#### Scenario: Recarga sin cookie válida redirige a login
- **WHEN** el usuario recarga la página y no hay cookie de refresh válida
- **THEN** el usuario es redirigido a `/login`

#### Scenario: La renovación proactiva no desmonta la página
- **WHEN** hay un modal abierto en `/events/7` y se dispara la renovación proactiva del token
- **THEN** la renovación termina con éxito y el modal sigue abierto con su contenido
- **AND** el indicador de carga de `ProtectedRoute` nunca se muestra

#### Scenario: Sesión vencida lleva al login con aviso
- **WHEN** la renovación en segundo plano falla con 401
- **THEN** el store queda vacío, la caché de consultas queda vacía y el usuario llega a `/login` con el aviso «Tu sesión venció. Ingresá de nuevo.»

## ADDED Requirements

### Requirement: El logout vacía la caché de consultas

El logout SHALL vaciar la caché de TanStack Query (`queryClient.clear()`) además del store de auth, de modo que un login posterior —del mismo u otro usuario— nunca muestre datos de la sesión anterior (D93/RN-187).

#### Scenario: Datos de la sesión anterior no reaparecen
- **WHEN** el usuario ve la lista de eventos, hace logout y vuelve a ingresar
- **THEN** la caché estaba vacía tras el logout y la lista se consulta de nuevo antes de mostrarse
