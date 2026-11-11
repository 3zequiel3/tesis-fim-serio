## Why

La consola web es la cara del proyecto en la presentación y demo técnica, y hoy no está lista para eso. Tres revisiones del 2026-11-11 (estática, automática y E2E en navegador real sobre una pila aislada), verificadas contra `devel` `30efcaf`, encontraron defectos que rompen flujos completos frente a una audiencia —el cambio de contraseña del primer login deja al usuario atascado, la confirmación de US-11 es inalcanzable, la app se desmonta sola cada ~14 minutos— y una interfaz sin sistema visual: tema oscuro sin alternativa clara, sin estados de error ni vacío en varias vistas, sin layout responsivo y un único bundle de 515 kB. Además `pnpm audit --prod` reporta 11 hallazgos `high`.

La memoria de la tesis (Capítulo 5) sigue atada a `v5.1-tesis`; esta change rige la demo y no altera la evaluación.

## What Changes

**Sistema visual (D93/RN-187)**

- Dirección visual «Custodia» (ver `design.md` D-1): tokens de color, tipografía, espaciado y radios en `@theme` de Tailwind v4, tema oscuro y claro con conmutador que respeta `prefers-color-scheme` y persiste la elección; tipografías Atkinson Hyperlegible Next y Mono empaquetadas (sin CDN).
- Componentes base: `StatusBadge` único para los siete estados de RN-71 (color + ícono + texto canónico), `PathLabel` (directorio atenuado, nombre destacado), `HashChip`, `Button`, `Modal` accesible, `DataState` (carga, vacío, error con reintento), tabla que pasa a tarjetas en pantallas angostas.
- Layout: barra lateral agrupada y colapsable; menú hamburguesa a ≤ 768 px; sin desborde horizontal a 375 px.
- Diff legible por palabras; proceso con pid 0 o sin dato se muestra como «desconocido».

**Arreglos funcionales (cada uno con un test que falla sin el arreglo, con mocks de la forma real `{"detail": ...}`)**

- B1/D1: tras el cambio de contraseña, cerrar la sesión local y llevar a `/login` con aviso (D89/RN-183); mensajes del backend en español.
- B2, B3/D4, A7: un único lector de errores `readApiError` (D90/RN-184); la confirmación de archivo ausente (US-11) y el conteo del rescan vuelven a funcionar; ningún toast muestra `[object Object]`.
- B4: la renovación proactiva del token no usa el indicador de carga global.
- B5/D2: `EventDetail`/`EventChain` con estado de error y reintento; id no numérico → «Evento no encontrado».
- B6/D8: Aprobar/Rechazar sólo para `pending`.
- B7/D6: el contador `superseded` del Dashboard consulta con `include_superseded=true`.
- B8/D13: `FailedAlerts` con enlace al evento, `last_error`, `retry_count`, canal legible y «Reintentar todas».
- D3/M3/D11: el detalle se reconsulta mientras el comando está `pending` (cada 3 s, hasta 60 s) y muestra el motivo de un fallo en español; el rechazo con restauración informa «solicitada», no un éxito prematuro.
- D12b/M4: el editor de rutas no guarda una lista vacía y toma la entrada escrita sin «Agregar»; el rescan no re-escanea todo con la selección vacía y su selección no queda obsoleta.
- M1 (logout vacía la caché), M5 (la lista de eventos se refresca), M6/D16 (redirección de scope antes de montar páginas), M7 (parámetros de página saneados), M8 (`RejectModal` se reinicia), M9 (carrera del debounce de ruta, `SystemBanner` cuando `/health` falla, «seleccionar todo» con ids obsoletos, `Login` respeta `location.state.from`).
- D15: controles de mutación ocultos para un `role` distinto de `admin`, con mensajes en vez de carga eterna.
- «Sesión vencida»: aviso explícito al volver a `/login`.

**Backend (un campo de lectura)**

- `EventOut.ack_error`: el `error` del mismo `PublishedCommand` que da `ack_status`, truncado a 200 caracteres.

**Calidad**

- División del bundle por ruta (`React.lazy`).
- ESLint de configuración plana con `typescript-eslint` y `react-hooks`, script `lint`, sin errores.
- `axios` ≥ 1.20.0 y `react-router(-dom)` ≥ 7.18.2; `pnpm audit --prod` sin `high`/`critical`.

## Capabilities

### New Capabilities

- `frontend-design-system`: tokens, temas, tipografías y componentes base (badge de estado, ruta, hash, modal, estados de datos), layout responsivo y modo lectura por rol.

### Modified Capabilities

- `frontend-auth`: el cambio de contraseña termina en `/login` con aviso; la renovación proactiva no desmonta rutas; logout y sesión vencida vacían la caché; redirección de scope antes de montar; `Login` respeta el destino original.
- `frontend-events`: Aprobar/Rechazar sólo para `pending`; error codes leídos de `detail`; estados de error en detalle y cadena; reconsulta del comando y motivo del fallo; diff por palabras; proceso desconocido; refresco de la lista; saneo de parámetros; `RejectModal` y selección.
- `frontend-agents`: editor de rutas seguro; rescan con conteo real y selección explícita.
- `frontend-alerts`: vista de alertas fallidas con datos completos y «Reintentar todas».
- `frontend-dashboard`: contador `superseded` correcto.
- `frontend-shell`: `SystemBanner` ante falla de `/health/components`.
- `frontend-scaffold`: división por ruta, ESLint, lector único de errores y auditoría de dependencias.
- `backend-events-api`: `EventOut.ack_error`.

## Impact

- **Código**: casi todo `frontend/src/` (páginas, componentes, hooks, store de auth, `globals.css`, `App.tsx`), `frontend/index.html`, `frontend/public/theme-init.js` (nuevo), `frontend/eslint.config.js` (nuevo), `frontend/package.json` y `pnpm-lock.yaml`; `backend/app/modules/events/router.py` (`ack_error`).
- **Dependencias nuevas**: `@fontsource-variable/atkinson-hyperlegible-next`, `@fontsource-variable/atkinson-hyperlegible-mono`, `lucide-react`; de desarrollo: `eslint`, `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals`.
- **Tests**: los 298 existentes siguen pasando; sólo se adaptan los que mockeaban una forma de error que el backend no emite, con nota. Tests nuevos por cada arreglo.
- **Decisiones**: D93/RN-187 (nueva); consume D89/RN-183, D90/RN-184, D91/RN-185. Preserva RN-71, RN-29, RN-44, D30/RN-124, D64/RN-158, D70/RN-164.
- **DAG**: depende de la Change 71 (`backend-input-validation-hardening`), que fija los códigos de error que esta change lee.
