## Context

El backend expone todos los endpoints necesarios (auth, health, alerts). El frontend `frontend/` está vacío. Este change bootstrapea el proyecto desde cero y entrega el shell completo: scaffolding, auth flows y layout con banners de estado. Es la base sobre la que C18 y C19 agregan las páginas de contenido.

Stack decidido en CLAUDE.md y docs canónicos:
- Vite 6 + React 19 + TypeScript
- Tailwind v4 CSS-first (`@tailwindcss/vite`, sin PostCSS, sin `tailwind.config.js`)
- pnpm como package manager
- TanStack Query v5 + Zustand v5 (gestión de estado server/client)
- Axios para HTTP
- React Router v7

## Goals / Non-Goals

**Goals:**
- Proyecto frontend funcional con build y dev server operativos.
- Flujo de auth completo (login → dashboard; login → force-change-password → dashboard).
- Refresh automático transparente al usuario; logout limpia todo.
- Layout shell con banners de estado en tiempo real.
- nginx sirve el SPA con headers de seguridad correctos.

**Non-Goals:**
- Páginas de contenido (events, rules, agents, dashboard) — son C18 y C19.
- Internacionalización.
- Tests E2E o de componentes con Playwright/Vitest (se añaden en C20 si hay tiempo).

## Decisions

### D-FE-1: Tailwind v4 CSS-first (sin `tailwind.config.js`)

**Decisión**: Usar el plugin `@tailwindcss/vite` directamente; el único punto de entrada es `@import "tailwindcss"` + `@theme { ... }` en el CSS global. Sin `tailwind.config.js`, sin PostCSS.

**Razón**: Es el modo canónico de Tailwind v4. Reduce archivos de configuración y mantiene coherencia con CLAUDE.md.

### D-FE-2: Access token en memoria, refresh en cookie httpOnly

**Decisión**: El access token (15min) vive solo en el store Zustand (RAM). La cookie `fim_refresh` es `httpOnly + Secure + SameSite=Strict + Path=/auth/refresh` — el backend la setea en `POST /auth/login` y la usa en `POST /auth/refresh`.

**Razón**: Tokens en localStorage son vulnerables a XSS (RN-96). La cookie httpOnly es inaccesible desde JS. SameSite=Strict previene CSRF en el endpoint de refresh (RN-97).

**Alternativa descartada**: Token en localStorage — vulnerable a XSS.

### D-FE-3: Interceptor Axios con cola de retry durante refresh

**Decisión**: El interceptor de respuesta 401 pausa todas las requests en una cola (`pendingQueue`), ejecuta el refresh una sola vez, y resuelve o rechaza la cola. Si el refresh falla (cookie expirada/inválida), llama `logout()`.

**Razón**: Evita condición de carrera donde múltiples requests concurrentes disparan N refreshes simultáneos.

### D-FE-4: SystemBanner — polling activo vs SSE

**Decisión**: `SystemBanner` hace `GET /health/components` cada 10 segundos vía TanStack Query `refetchInterval`. No SSE.

**Razón**: El endpoint `/health/components` es síncrono y barato. SSE añade complejidad sin beneficio para datos que cambian raramente. El polling 10s es el intervalo canónico (RN-101).

### D-FE-5: AlertsBanner — query paginada vs conteo

**Decisión**: `AlertsBanner` hace `GET /alerts?status=failed&size=1` y muestra banner amarillo si `total > 0` (D6 — `delivered_at IS NULL AND failed_at IS NOT NULL`).

**Razón**: El endpoint ya existe (C16). No necesita endpoint extra de conteo. `size=1` minimiza el payload.

### D-FE-6: Rutas protegidas con React Router loader + Zustand

**Decisión**: Un componente `ProtectedRoute` lee el access token del store Zustand; si no existe, intenta sillar refresh antes de redirigir a `/login`. El scope `password_change_only` redirige a `/change-password` desde cualquier ruta protegida.

**Razón**: Patrón estándar para SPAs con auth basada en tokens en memoria.

## Risks / Trade-offs

- **[Risk] Pérdida del access token al recargar** → El token vive en RAM; una recarga de página lo pierde. Mitigación: `ProtectedRoute` hace un refresh silencioso al montar — si la cookie sigue válida, el usuario no nota la recarga.
- **[Trade-off] pnpm en lugar de npm** → Más rápido y con lockfile más predecible, pero requiere `pnpm` instalado. Es el PM estándar del proyecto según CLAUDE.md.
- **[Risk] Tailwind v4 aún relativamente nuevo** → Algunos plugins de terceros pueden no ser compatibles. Mitigación: este change no usa plugins, solo el core + `@tailwindcss/vite`.
