## ADDED Requirements

### Requirement: Layout shell con MainLayout y AuthLayout

El sistema SHALL tener `frontend/src/components/layout/MainLayout.tsx` (con Sidebar + Navbar, para rutas autenticadas) y `frontend/src/components/layout/AuthLayout.tsx` (centrado, para login y change-password). `MainLayout` MUST incluir `SystemBanner` y `AlertsBanner` en la parte superior. `Sidebar` MUST incluir navegación a las secciones principales: Eventos, Reglas, Agentes, Dashboard, Alertas.

#### Scenario: Rutas autenticadas usan MainLayout
- **WHEN** el usuario navega a cualquier ruta protegida
- **THEN** se muestra el layout con Sidebar y Navbar visibles

#### Scenario: Rutas de auth usan AuthLayout
- **WHEN** el usuario navega a `/login` o `/change-password`
- **THEN** se muestra el layout centrado sin Sidebar ni Navbar

---

### Requirement: SystemBanner con polling de /health/components

El sistema SHALL tener `frontend/src/components/layout/SystemBanner.tsx` que hace polling a `GET /health/components` cada 10 segundos (RN-101). Si algún componente devuelve `"down"`, MUST mostrar un banner rojo visible en la parte superior del layout con un mensaje indicando degradación. Si todos están `"ok"` o `"degraded"`, no se muestra el banner rojo (solo se muestra para `"down"`).

#### Scenario: Componente down muestra banner rojo
- **WHEN** `GET /health/components` retorna algún componente con `"down"`
- **THEN** aparece un banner rojo en la parte superior con mensaje de alerta del sistema

#### Scenario: Todos los componentes ok — sin banner
- **WHEN** todos los componentes retornan `"ok"` o `"degraded"`
- **THEN** no se muestra el banner rojo (puede mostrarse amarillo por degraded según criterio de implementación)

#### Scenario: Polling actualiza el estado cada 10 segundos
- **WHEN** un componente pasa de `"ok"` a `"down"` entre polls
- **THEN** el banner aparece en el próximo ciclo de 10 segundos sin recargar la página

---

### Requirement: AlertsBanner con conteo de alertas fallidas

El sistema SHALL tener `frontend/src/components/layout/AlertsBanner.tsx` que consulta `GET /alerts?status=failed&size=1` para verificar si hay alertas fallidas en la DLQ (RN-102, D6). Si `total > 0`, MUST mostrar un banner amarillo con el conteo de alertas fallidas y un enlace a la página de alertas fallidas. El banner MUST desaparecer automáticamente cuando no hay alertas fallidas.

#### Scenario: DLQ no vacía muestra banner amarillo
- **WHEN** `GET /alerts?status=failed` retorna `total > 0`
- **THEN** aparece un banner amarillo con el número de alertas fallidas

#### Scenario: DLQ vacía — sin banner amarillo
- **WHEN** `GET /alerts?status=failed` retorna `total = 0`
- **THEN** no se muestra el banner amarillo

#### Scenario: Banner desaparece tras resolver alertas
- **WHEN** todas las alertas fallidas son reintentadas exitosamente y el siguiente poll retorna `total = 0`
- **THEN** el banner amarillo desaparece sin recargar la página

---

### Requirement: nginx.conf con headers de seguridad y SPA fallback

El sistema SHALL tener `frontend/nginx.conf` que sirve el build estático de Vite con `try_files $uri /index.html` para SPA routing. MUST incluir headers de seguridad: `Content-Security-Policy` (script-src self), `Strict-Transport-Security` (HSTS), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`. El `Dockerfile` del frontend MUST usar nginx para servir el build en producción.

#### Scenario: SPA routing funciona en rutas anidadas
- **WHEN** el usuario navega directamente a `/events` en el browser
- **THEN** nginx sirve `index.html` y React Router maneja la ruta

#### Scenario: Headers de seguridad presentes en respuestas
- **WHEN** se hace cualquier request al frontend en producción
- **THEN** los headers `X-Frame-Options`, `X-Content-Type-Options`, y `Strict-Transport-Security` están presentes en la respuesta
