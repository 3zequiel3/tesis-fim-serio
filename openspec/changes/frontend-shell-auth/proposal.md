## Why

El backend está completo (M1–M3). El M4 comienza con el shell del frontend: scaffolding del proyecto, flujo de autenticación (login + cambio forzado de password) y la estructura de layout persistente con banners de estado del sistema. Sin esto el admin no puede operar el sistema desde el navegador.

## What Changes

- Nuevo proyecto frontend en `frontend/` con Vite + React 19 + TypeScript + Tailwind v4 (CSS-first, `@tailwindcss/vite`, sin PostCSS, sin `tailwind.config.js`) + pnpm.
- `api/client.ts`: Axios con interceptores JWT (attach access token en header, 401 → refresh automático; refresh fallido → logout).
- `stores/auth.store.ts`: Zustand, access token en **memoria** (NUNCA localStorage); refresh token en cookie `httpOnly + Secure + SameSite=Strict + Path=/auth/refresh`.
- `pages/Login.tsx`: formulario login con indicador de rate limit (429 → mensaje de bloqueo temporal).
- `pages/ForcePasswordChange.tsx`: redirige automáticamente si el scope del token es `password_change_only`.
- Layout: `MainLayout` (autenticado), `AuthLayout` (sin auth), `Sidebar`, `Navbar`.
- `components/layout/SystemBanner.tsx`: polling `/health/components` cada 10s; banner rojo si algún componente está `down`.
- `components/layout/AlertsBanner.tsx`: banner amarillo si hay alertas con `delivered_at IS NULL AND failed_at IS NOT NULL` (DLQ no vacía — D6).
- `nginx.conf`: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, SameSite=Strict; sirve el build estático.

## Capabilities

### New Capabilities

- `frontend-scaffold`: Setup del proyecto Vite + React 19 + TypeScript + Tailwind v4 + pnpm; Axios client con interceptores JWT; React Router; estructura de carpetas.
- `frontend-auth`: Flujo de autenticación completo — Zustand auth store, Login, ForcePasswordChange, refresh automático, logout.
- `frontend-shell`: Layout shell persistente — MainLayout, AuthLayout, Sidebar, Navbar, SystemBanner (health polling), AlertsBanner (DLQ banner), nginx config con headers de seguridad.

### Modified Capabilities

*(ninguna — primer change de frontend, sin specs previas)*

## Impact

- **Código nuevo**: todo `frontend/` (proyecto vacío hasta ahora).
- **Dependencias del backend**: `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /users/change-password` (C04), `GET /health/components` (C15), `GET /alerts?status=failed` (C16).
- **Reglas cubiertas**: RN-43, RN-46, RN-88, RN-95, RN-96, RN-97, RN-100, RN-101, RN-102, RN-103.
- **Sin cambios al backend**.
