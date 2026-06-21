## ADDED Requirements

### Requirement: Proyecto frontend inicializado con Vite + React 19 + TypeScript + Tailwind v4 + pnpm

El sistema SHALL tener un proyecto frontend en `frontend/` inicializado con Vite, React 19, TypeScript strict, Tailwind v4 (plugin `@tailwindcss/vite`, sin PostCSS, sin `tailwind.config.js`) y pnpm como package manager. El CSS global SHALL contener `@import "tailwindcss"` y un bloque `@theme {}` para tokens de diseño del proyecto. El `tsconfig.json` MUST tener `strict: true` y `paths` configurados para alias `@/` apuntando a `src/`.

#### Scenario: Dev server arranca
- **WHEN** se ejecuta `pnpm dev` en `frontend/`
- **THEN** el servidor de desarrollo arranca en `http://localhost:5173` sin errores

#### Scenario: Build de producción es exitoso
- **WHEN** se ejecuta `pnpm build` en `frontend/`
- **THEN** genera `dist/` sin errores de TypeScript ni de build

---

### Requirement: Estructura de carpetas canónica del frontend

El proyecto SHALL tener la estructura `frontend/src/{api,stores,pages,components/{ui,layout},hooks}/` según las convenciones del proyecto. Los archivos de entrada SHALL ser `src/main.tsx` y `src/App.tsx`.

#### Scenario: Estructura de directorios correcta
- **WHEN** se inspecciona `frontend/src/`
- **THEN** existen los directorios `api/`, `stores/`, `pages/`, `components/ui/`, `components/layout/`, `hooks/`

---

### Requirement: Axios client con interceptores JWT

El sistema SHALL tener `frontend/src/api/client.ts` con una instancia Axios con `baseURL` apuntando al backend. El interceptor de request MUST adjuntar el access token del store Zustand en el header `Authorization: Bearer <token>` si existe. El interceptor de response MUST detectar 401, pausar requests pendientes, ejecutar `POST /auth/refresh` una sola vez (D-FE-3), y reintentar o hacer logout según el resultado.

#### Scenario: Request autenticada adjunta Bearer token
- **WHEN** el store tiene un access token y se hace una request con el client
- **THEN** el header `Authorization: Bearer <token>` está presente en la request

#### Scenario: 401 dispara refresh automático
- **WHEN** una request recibe 401 y hay una cookie de refresh válida
- **THEN** el client ejecuta `POST /auth/refresh`, obtiene nuevo access token, y reintenta la request original

#### Scenario: Refresh fallido hace logout
- **WHEN** `POST /auth/refresh` retorna 401 (cookie expirada)
- **THEN** el store llama `logout()` y el usuario es redirigido a `/login`

#### Scenario: Múltiples 401 simultáneos disparan un solo refresh
- **WHEN** 3 requests simultáneas reciben 401
- **THEN** solo se ejecuta un `POST /auth/refresh`; las 3 requests se reintentamos tras el refresh exitoso

---

### Requirement: React Router con rutas definidas

El sistema SHALL configurar React Router v7 en `App.tsx` con las siguientes rutas mínimas: `/login` (pública), `/change-password` (requiere scope `password_change_only`), `/*` (rutas protegidas bajo `MainLayout`). Las rutas protegidas MUST verificar autenticación y redirigir a `/login` si no hay sesión. La ruta raíz `/` MUST redirigir a `/events` (preparando C18).

#### Scenario: Ruta protegida sin sesión redirige a login
- **WHEN** se navega a `/` sin access token ni cookie de refresh válida
- **THEN** el usuario es redirigido a `/login`

#### Scenario: Ruta pública accesible sin auth
- **WHEN** se navega a `/login` sin autenticación
- **THEN** se muestra la página de login sin redirección
