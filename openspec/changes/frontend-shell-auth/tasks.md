## 1. Scaffold del proyecto

- [x] 1.1 Inicializar proyecto Vite en `frontend/` con template `react-ts` usando pnpm: `pnpm create vite@latest frontend --template react-ts` (ejecutar desde la raíz del repo)
- [x] 1.2 Instalar dependencias: `@tailwindcss/vite`, `tailwindcss`, `axios`, `react-router-dom`, `zustand`, `@tanstack/react-query`, `@tanstack/react-query-devtools`; devDependencies: `@types/node`
- [x] 1.3 Configurar Tailwind v4 en `frontend/vite.config.ts`: agregar `tailwindcss()` de `@tailwindcss/vite` al array `plugins`; renombrar `src/index.css` a `src/globals.css` con `@import "tailwindcss"` y bloque `@theme { --color-primary: ...; --color-danger: ...; }` (tokens mínimos)
- [x] 1.4 Configurar alias `@/` en `frontend/tsconfig.json` (`paths: {"@/*": ["./src/*"]}`) y en `frontend/vite.config.ts` (`resolve.alias: {"@": path.resolve(__dirname, "src")}`)
- [x] 1.5 Crear estructura de carpetas vacías: `src/api/`, `src/stores/`, `src/pages/`, `src/components/ui/`, `src/components/layout/`, `src/hooks/`

## 2. API client Axios

- [x] 2.1 Crear `frontend/src/api/client.ts`: instancia Axios con `baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000"` y `withCredentials: true` (para que la cookie de refresh se envíe automáticamente)
- [x] 2.2 Implementar interceptor request en `client.ts`: lee `useAuthStore.getState().accessToken`; si existe, agrega `Authorization: Bearer <token>`
- [x] 2.3 Implementar interceptor response en `client.ts`: detecta 401, encola requests pendientes en `pendingQueue: Array<{resolve, reject}>`, ejecuta `POST /auth/refresh` una sola vez (flag `isRefreshing`), resuelve/rechaza cola según resultado; si refresh falla → llama `useAuthStore.getState().logout()` y rechaza
- [x] 2.4 Crear `frontend/src/api/auth.ts` con funciones tipadas: `loginApi({ username, password })`, `refreshApi()`, `logoutApi()`, `changePasswordApi({ new_password })`

## 3. Auth store Zustand

- [x] 3.1 Crear `frontend/src/stores/auth.store.ts` con interfaz `AuthState`: `accessToken: string | null`, `user: { id: number; username: string; role: string } | null`, `isLoading: boolean`; NUNCA persistir en localStorage
- [x] 3.2 Implementar acciones en el store: `setToken(token, user)` (guarda en RAM), `login(credentials)` (llama `loginApi`, llama `setToken`), `logout()` (llama `logoutApi`, limpia estado), `refreshToken()` (llama `refreshApi`, llama `setToken`)

## 4. Routing y guards

- [x] 4.1 Configurar `frontend/src/App.tsx` con React Router `<BrowserRouter>`: rutas `<Route path="/login" element={<AuthLayout><Login /></AuthLayout>} />`, `<Route path="/change-password" element={<AuthLayout><ForcePasswordChange /></AuthLayout>} />`, `<Route element={<ProtectedRoute />}><Route element={<MainLayout />}><Route index element={<Navigate to="/events" />} /><Route path="*" element={<div>Página no encontrada</div>} /></Route></Route>`; envolver todo en `<QueryClientProvider>`
- [x] 4.2 Crear `frontend/src/components/layout/ProtectedRoute.tsx`: al montar, si no hay `accessToken` en store intenta `refreshToken()`; si falla redirige a `/login`; mientras espera muestra spinner; si pasa muestra `<Outlet />`
- [x] 4.3 Agregar en `ProtectedRoute` la verificación de scope: si el JWT decodificado (claim `scope`) es `password_change_only` y la ruta no es `/change-password`, redirigir a `/change-password`

## 5. Páginas de autenticación

- [x] 5.1 Crear `frontend/src/pages/Login.tsx`: formulario controlado con campos `username` y `password`; botón submit que llama `login()` del store; en 200 → `navigate("/")`, en 401 → mensaje "Credenciales incorrectas", en 429 → mensaje "Demasiados intentos. Esperá unos minutos antes de reintentar." (RN-88); mostrar spinner mientras carga; si ya hay sesión activa → `<Navigate to="/" />`
- [x] 5.2 Crear `frontend/src/pages/ForcePasswordChange.tsx`: formulario con campos `new_password` y `confirm_password`; validación cliente: ≥12 chars y que coincidan; en submit llama `changePasswordApi`; en 200 → llama `refreshToken()` y `navigate("/")`; en error → muestra mensaje

## 6. Componentes de layout

- [x] 6.1 Crear `frontend/src/components/layout/Sidebar.tsx`: lista de links `NavLink` a `/events`, `/rules`, `/agents`, `/dashboard`, `/alerts`; aplica clase activa con `isActive` de React Router
- [x] 6.2 Crear `frontend/src/components/layout/Navbar.tsx`: muestra `user.username` del store; botón "Cerrar sesión" que llama `logout()` y redirige a `/login`
- [x] 6.3 Crear `frontend/src/components/layout/MainLayout.tsx`: `<div class="flex">` con `<Sidebar />` + `<div class="flex-1 flex-col">` con `<SystemBanner />` + `<AlertsBanner />` + `<Navbar />` + `<main><Outlet /></main>`
- [x] 6.4 Crear `frontend/src/components/layout/AuthLayout.tsx`: `<div class="min-h-screen flex items-center justify-center">` con `<div class="w-full max-w-md">{children}</div>`

## 7. Banners de estado

- [x] 7.1 Crear `frontend/src/components/layout/SystemBanner.tsx`: usa `useQuery` con `queryKey: ["health"]`, `queryFn: () => apiClient.get("/health/components").then(r => r.data)`, `refetchInterval: 10_000`; si algún componente tiene `status === "down"` → muestra `<div class="bg-red-600 text-white text-center p-2">⚠ Sistema degradado — componente X no disponible</div>`
- [x] 7.2 Crear `frontend/src/components/layout/AlertsBanner.tsx`: usa `useQuery` con `queryKey: ["alerts-failed-count"]`, `queryFn: () => apiClient.get("/alerts?status=failed&size=1").then(r => r.data)`, `refetchInterval: 30_000`; si `data.total > 0` → muestra `<div class="bg-yellow-400 text-yellow-900 text-center p-2">⚠ {data.total} alerta(s) fallidas en la DLQ — <a href="/alerts">revisar</a></div>`

## 8. Entrypoint y providers

- [x] 8.1 Actualizar `frontend/src/main.tsx`: `<QueryClientProvider client={new QueryClient()}>` envuelve `<App />`; importar `globals.css` en lugar de `index.css`; en desarrollo agregar `<ReactQueryDevtools />`

## 9. nginx y Docker

- [x] 9.1 Crear `frontend/nginx.conf`: `server { listen 80; root /usr/share/nginx/html; index index.html; location / { try_files $uri /index.html; } add_header X-Frame-Options DENY; add_header X-Content-Type-Options nosniff; add_header Strict-Transport-Security "max-age=63072000; includeSubDomains"; add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' http://localhost:8000"; }`
- [x] 9.2 Crear `frontend/Dockerfile`: multi-stage — stage `build` usa `node:22-alpine` con `pnpm install && pnpm build`; stage `serve` usa `nginx:alpine`, copia `dist/` a `/usr/share/nginx/html/` y `nginx.conf` a `/etc/nginx/conf.d/default.conf`

## 10. Variables de entorno

- [x] 10.1 Crear `frontend/.env.example` con `VITE_API_URL=http://localhost:8000`
- [x] 10.2 Crear `frontend/.env.development` con `VITE_API_URL=http://localhost:8000` (dev local)

## 11. docker-compose

- [x] 11.1 Actualizar `docker-compose.yml`: agregar `ports: ["80:80"]` al servicio `frontend` y actualizar comentario de placeholder a real

## 12. Commit

- [ ] 12.1 Commit `feat(frontend): add scaffold, auth flows and layout shell (C17)`
