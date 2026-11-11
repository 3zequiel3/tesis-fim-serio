## 0. Precondiciones

- [ ] 0.1 Verificar con `openspec list --json` y `eza openspec/changes/archive` que `backend-input-validation-hardening` (Change 71) está archivada, o que su rama está integrada en `devel`; si no, detenerse.
- [ ] 0.2 En `frontend/`, correr `pnpm test --run`, `pnpm typecheck` y `pnpm build`; registrar la línea base (298 tests, tamaño del chunk de entrada ~515 kB) y `pnpm audit --prod` (11 `high`). Correr `python3 scripts/check_spec_integrity.py` y registrar que pasa.
- [ ] 0.3 Releer D93/RN-187 y D89–D91 en `docs/reglas_de_negocio.md` y las filas en `docs/arquitectura_stack.md`; cualquier suposición nueva se cierra ahí antes de seguir.

## 1. Calidad base: dependencias y ESLint

- [ ] 1.1 Actualizar `axios` a `^1.21` y `react-router-dom` a `^7.18.5` (arrastra `react-router` y `follow-redirects` corregidos); correr la suite y arreglar regresiones.
- [ ] 1.2 `pnpm audit --prod --audit-level high` termina en 0; si queda un residual, `pnpm.overrides` documentado en `package.json` o justificación en `design.md` (spec «Dependencias de producción sin vulnerabilidades altas»).
- [ ] 1.3 Agregar `eslint`, `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh` y `globals`; crear `frontend/eslint.config.js` (design D-13) con la regla `no-restricted-syntax` de D-4 y el script `"lint": "eslint ."`.
- [ ] 1.4 Corregir los hallazgos de `pnpm lint` hasta 0 errores; cada `eslint-disable-next-line` lleva el motivo.

## 2. Sistema de diseño (D93/RN-187, design D-1 a D-3)

- [ ] 2.1 Agregar `@fontsource-variable/atkinson-hyperlegible-next`, `@fontsource-variable/atkinson-hyperlegible-mono` y `lucide-react`; importar sólo los subconjuntos `latin` y `latin-ext`.
- [ ] 2.2 Reescribir `frontend/src/globals.css`: tokens semánticos y de estado en `@theme` (tema oscuro), bloque `[data-theme="light"]`, escala tipográfica y espaciado. Test puro `src/theme/contrast.test.ts` que calcula el contraste WCAG de cada par texto/fondo de ambos temas y exige ≥ 4,5:1; ajustar tonos hasta que pase.
- [ ] 2.3 Crear `frontend/public/theme-init.js` y cargarlo en `<head>` de `frontend/index.html`; hook `useTheme` y `ThemeToggle` con persistencia en `localStorage['fim.theme']`. Tests: sin elección guardada respeta `prefers-color-scheme`; la elección persiste.
- [ ] 2.4 Componentes base en `src/components/ui/`: `Button`, `StatusBadge`, `PathLabel`, `HashChip`, `DataState`, `EmptyState`, `ResponsiveTable`, `Modal`. Tests: `StatusBadge` para los siete estados y uno desconocido (texto, ícono, nunca sólo color); `Modal` con `role="dialog"`, foco atrapado, devolución del foco y bloqueo de cierre con mutación en curso; `DataState` con carga, vacío, error con «Reintentar» y `403`.
- [ ] 2.5 Layout: `MainLayout`, `Sidebar` (agrupada, colapsable, panel con foco atrapado a ≤ 768 px), barra superior con estado del sistema, `ThemeToggle`, usuario y leyenda de modo lectura. Tests: a 375 px el menú tiene nombre accesible y abre el panel; `Escape` lo cierra.
- [ ] 2.6 Hook `useCan()` y componente `<Can>`; test con `role = "viewer"` y `role = "admin"`.

## 3. Errores y sesión

- [ ] 3.1 Crear `src/api/errors.ts` (`readApiError`, `apiErrorMessage`) y `src/test/mockApiError.ts`; tests de las tres formas de `detail`, campo extra (`count`, `index`) y error de red (spec «Un único lector de errores de la API»).
- [ ] 3.2 B2: en `hooks/useEventActions.ts`, leer el código con `readApiError`; borrar el lector local. Test que monta el detalle, mockea `422 {"detail": {"code": "absent_confirmation_required"}}` y espera el aviso de US-11 (falla sin el arreglo). Corregir con nota los tests existentes que mockeaban `{code}` en la raíz.
- [ ] 3.3 B3/D4: en `hooks/useAgents.ts`, leer `data.count` con `readApiError`; test del modal de rescan con `409 {"detail": {"code": "pending_events_exist", "count": 3}}` que espera «3» (falla sin el arreglo).
- [ ] 3.4 A7: reemplazar toda interpolación de `detail` en `Rules.tsx`, `Agents.tsx`, `FailedAlerts.tsx`, `BulkActionBar` y toasts por `apiErrorMessage`; test que mockea `detail` objeto y lista y verifica que ningún texto contiene `[object Object]`.
- [ ] 3.5 Crear el módulo `src/api/queryClient.ts` y usarlo en `main.tsx` y en el store.
- [ ] 3.6 B4: separar `status` de la renovación en `stores/auth.store.ts` (design D-5); `ProtectedRoute` sólo muestra carga en `checking`. Test con temporizadores falsos: modal abierto, disparo de la renovación proactiva, el modal sigue montado (falla sin el arreglo).
- [ ] 3.7 `endSession(reason)` y uso en logout (M1), en el interceptor de 401 cuando el refresh falla («Tu sesión venció. Ingresá de nuevo.») y en el cambio de contraseña. Tests: tras logout `queryClient.getQueryCache().getAll()` está vacío; sesión vencida llega a `/login` con el aviso.
- [ ] 3.8 B1/D1: `ForcePasswordChange` sin `refreshToken()`, con `endSession('password_changed')`, validación de nueva ≠ actual, mensajes del backend por `readApiError` y envío deshabilitado en curso. Test que verifica que no se envía `POST /auth/refresh` y que se llega a `/login` con el aviso (falla sin el arreglo); tests de `current_password_invalid` y `password_reuse` con la forma real.
- [ ] 3.9 M6/D16: gate de scope en render de `ProtectedRoute` (design D-6). Test: con scope `password_change_only` en `/events`, ninguna request a `/events` ni a `/health/components` se envía.
- [ ] 3.10 M9: `Login` respeta `location.state.from` sólo para rutas internas, muestra `state.notice` y el `Retry-After` del 429 con envío deshabilitado. Tests de los escenarios del spec `frontend-auth`.

## 4. Eventos

- [ ] 4.1 Backend (design D-8): `_get_ack_status_map` devuelve estado y error; `EventOut.ack_error` truncado a 200 en lista, detalle y cadena. Tests en la suite de backend: fallido con motivo, confirmado sin motivo, truncado, y conteo de consultas constante en una página de 50.
- [ ] 4.2 Agregar `ack_error` a `src/api/events.ts` y al contrato de fixtures si existe (`events.contract.test.ts`).
- [ ] 4.3 B5/D2: `useEventId()` y estados de error con «Reintentar» en `EventDetail` y `EventChain`. Tests: `/events/abc` no envía requests y muestra «Evento no encontrado»; `500` en detalle y `503` en cadena muestran error con reintento (fallan sin el arreglo).
- [ ] 4.4 B6/D8: Aprobar/Rechazar sólo para `pending` y dentro de `<Can>`. Test con `alert_only` (falla sin el arreglo) y con `role = "viewer"`.
- [ ] 4.5 D3/M3/D11: reconsulta acotada (design D-7), motivo legible de `ack_error` y toast «Rechazo registrado; restauración solicitada». Tests con temporizadores falsos: `pending` → `acked` a los 4 s se refleja sin interacción; a los 60 s se detiene y aparece «Actualizar»; `failed` + `no_restorable_content` muestra el motivo en español.
- [ ] 4.6 Diff por palabras y `utils/process.ts` (design D-11). Tests: `PermitRootLogin no` → `yes` no se fragmenta en letras; pid `0` y exe `null` muestran «desconocido»; uid `0` se muestra como `0`.
- [ ] 4.7 M5: invalidación de `['events']` desde `useAlertsSSE` y `refetchInterval` de 15 s en `useEvents`. Test del SSE que espera una nueva consulta de `GET /events`.
- [ ] 4.8 M7: `parsePageParams` y test con `page=abc` y `page=-3`.
- [ ] 4.9 M9: carrera del filtro de ruta con debounce (key con el valor debounced) y selección depurada tras refresco; tests de ambos escenarios del spec.
- [ ] 4.10 M8: `RejectModal` reiniciado en cada apertura y tolerante a `path` nulo; tests.
- [ ] 4.11 Reescribir `Events`, `EventsTable`, `EventDetail`, `EventChain`, `EventTimeline` y `BulkActionBar` sobre los componentes base: `PathLabel` como título del detalle, `HashChip`, `StatusBadge`, `ResponsiveTable` con tarjetas por debajo de 640 px.

## 5. Agentes, reglas, alertas, Dashboard y banner

- [ ] 5.1 D12b: `utils/watchPaths.ts` (función pura con las reglas de D91/RN-185 y tests) y editor que toma la entrada escrita, bloquea la lista vacía y ubica el error por `detail.index`. Test: escribir `/var/www` sin «Agregar» y guardar envía ambas rutas; quitar la última deshabilita guardar (fallan sin el arreglo).
- [ ] 5.2 M4: selección del rescan reconstruida en cada apertura, confirmación deshabilitada sin selección, modal sin cierre en curso; tests de los escenarios del spec `frontend-agents`.
- [ ] 5.3 Reescribir `Agents` y `AgentCard` sobre los componentes base, con `<Can>` en las mutaciones.
- [ ] 5.4 Reescribir `Rules` y `RuleForm` sobre los componentes base; mostrar los `pattern_*` del backend por `readApiError` junto al campo; `<Can>` en las mutaciones; test con `422 pattern_not_absolute`.
- [ ] 5.5 B8/D13: `FailedAlerts` con enlace al evento, `last_error`, `retry_count`, «sin canal entregado» y «Reintentar todas» con resumen; estado vacío. Tests de los escenarios del spec `frontend-alerts` (el de «Reintentar todas» falla sin el arreglo).
- [ ] 5.6 Reescribir `Alerts` y `AlertsBanner` sobre los componentes base.
- [ ] 5.7 B7/D6: `api/dashboard.ts` con `include_superseded=true` para `superseded` y su enlace. Test que verifica el parámetro y muestra el conteo (falla sin el arreglo).
- [ ] 5.8 Rediseñar `Dashboard` (barra proporcional por estado con enlaces y lista de pendientes críticos y altos, design D-1).
- [ ] 5.9 M9: `SystemBanner` muestra «No se puede consultar el estado del sistema.» cuando su consulta falla; test con `502` y recuperación.
- [ ] 5.10 Rediseñar `Login`, `ForcePasswordChange` y `AuthLayout` sobre los componentes base.

## 6. Responsivo y división por ruta

- [ ] 6.1 `React.lazy` + `Suspense` en `App.tsx` (design D-12); `pnpm build` con chunk de entrada < 250 kB; aislar `react-diff-viewer-continued` si hace falta.
- [ ] 6.2 Revisar a 375 px, 768 px y 1.280 px cada página con rutas de 200 caracteres; corregir todo desborde horizontal del documento.
- [ ] 6.3 Verificación visual en navegador real (servidor de desarrollo con mocks o pila aislada) en ambos temas: capturas de Dashboard, Eventos, detalle, Agentes y Reglas; ajustar lo que no siga la dirección de D-1 y anotar en la change lo revisado.
- [ ] 6.4 Si es barato: un caso de Playwright que verifica `scrollWidth <= clientWidth` a 375 px en `/events` y el cambio de tema.

## 7. Cierre

- [ ] 7.1 `pnpm test --run`: los 298 tests previos pasan (sólo los de forma de error adaptados, cada uno con nota) y los nuevos pasan; registrar el conteo final.
- [ ] 7.2 `pnpm lint`, `pnpm typecheck`, `pnpm build` y `pnpm audit --prod --audit-level high` terminan en 0; registrar el tamaño del chunk de entrada.
- [ ] 7.3 Suite de backend completa con el cambio de `ack_error`.
- [ ] 7.4 `openspec validate frontend-ux-redesign --strict` y `python3 scripts/check_spec_integrity.py`.
- [ ] 7.5 Commits convencionales por grupo (`build(frontend): ...`, `feat(frontend): ...`, `fix(frontend): ...`, `feat(events): ack_error ...`, `test(frontend): ...`), sin atribución a IA.
