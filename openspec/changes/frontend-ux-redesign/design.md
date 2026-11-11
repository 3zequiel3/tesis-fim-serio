## Context

La consola (`frontend/`, Vite + React 19 + TypeScript + Tailwind v4, TanStack Query + Zustand) es la superficie que se muestra en la presentación y demo técnica del proyecto. Tres revisiones del 2026-11-11 encontraron defectos funcionales y de presentación, verificados contra `devel` `30efcaf` (lista completa en `proposal.md`). Hechos de código que condicionan el diseño:

- `stores/auth.store.ts:105` `refreshToken()` hace `set({ isLoading: true })`; el temporizador proactivo (`:62`) lo invoca y `ProtectedRoute.tsx:56` reemplaza todo el árbol por la pantalla de carga mientras `isLoading` es verdadero.
- `ForcePasswordChange.tsx:66` llama a `refreshToken()` tras un `change-password` que ya revocó la sesión (`backend/app/modules/users/router.py:78-100`).
- Lecturas de error incoherentes: `useEventActions.ts:70` lee `data.code` aunque el mismo archivo tiene un lector correcto en `:34-41`; `useAgents.ts:55` lee `body.count`; `Rules.tsx`, `Agents.tsx` y `FailedAlerts.tsx` interpolan `detail` sin saber si es string.
- `EventDetail.tsx:72` `canApprove` incluye `alert_only`; el backend sólo resuelve `pending`.
- `api/dashboard.ts` cuenta cada estado con `page_size=1` sin `include_superseded`; el backend excluye `superseded` por defecto (`events/router.py:156`).
- `ack_status` existe en `EventOut`, pero el motivo (`PublishedCommand.error`, escrito en `agents/command_ack_consumer.py:265`) no se expone.
- `SystemBanner.tsx` ignora el error de su propia consulta.
- CSP de `nginx/common-headers.conf:6`: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'` — sin scripts inline ni fuentes externas.
- `globals.css` tiene un `@theme` mínimo (`--color-primary` y afines); los componentes usan colores literales `gray-*`, `red-950`, etc.
- Las decisiones normativas están cerradas en D93/RN-187 (consola) y consumen D89/RN-183, D90/RN-184 y D91/RN-185 (Change 71).

## Goals / Non-Goals

**Goals:**

- Una consola con identidad visual propia, coherente en tema claro y oscuro, legible en un proyector.
- Cada defecto funcional arreglado con un test que falla sin el arreglo, usando mocks con la forma real del backend.
- Estados explícitos (carga, vacío, error) en toda vista, modales accesibles y layout responsivo.
- Bundle dividido por ruta, ESLint limpio y auditoría de dependencias sin `high`/`critical`.

**Non-Goals:**

- Cambiar el modelo de datos, la máquina de estados de eventos o los endpoints de mutación.
- Introducir un rol nuevo (el modo lectura es defensivo; RN-44 sin cambio).
- Internacionalización: la interfaz sigue en español con el registro actual (voseo).
- Reescribir la suite E2E de Playwright; sólo se agrega un caso si es barato (D-14).
- Alterar la evidencia del Capítulo 5, atada a `v5.1-tesis`.

## Decisions

### D-1 · Dirección visual «Custodia»

**Tema.** Una consola FIM es, en el fondo, un registro de custodia: cada archivo tiene una huella aprobada y cada cambio exige una decisión documentada. La dirección toma ese vocabulario —sello, huella, expediente— y lo traduce con sobriedad: superficies frías y planas, una tinta de sello como único acento, y la ruta del archivo como protagonista tipográfica.

**Paleta (núcleo).**

| Token | Oscuro | Claro | Uso |
|---|---|---|---|
| `surface` | `#141C26` (grafito azulado) | `#F2F4F7` (gris papel frío) | fondo de página |
| `surface-raised` | `#1B2532` | `#FFFFFF` | paneles, tablas, modales |
| `line` | `#2B3949` | `#D5DCE4` | bordes y separadores |
| `text` | `#E4E9EF` | `#18222E` | texto principal |
| `text-muted` | `#93A1B1` | `#56636F` | texto secundario |
| `accent` | `#8F86F5` (tinta de sello) | `#4F3FCF` | foco, enlaces, acción primaria |

Estados de RN-71 (par fondo/texto por tema, contraste AA verificado en la tarea 2.2): `pending` ámbar `#C98A12`, `approved` verde `#2E9E6A`, `rejected` rojo `#D2483E`, `superseded` neutro `#7D8896`, `auto_restored` cian `#1F98A6`, `quarantined` ciruela `#B0479A`, `alert_only` azul `#3B7DD8`; cada uno con ícono propio (reloj, tilde, cruz, flecha de reemplazo, flecha circular, candado, campana) de `lucide-react`.

**Tipografía.** Atkinson Hyperlegible Next (interfaz) y Atkinson Hyperlegible Mono (rutas, hashes, ids). Es una familia diseñada para distinguir glifos ambiguos (`l`/`1`/`I`, `0`/`O`), que es exactamente el problema de leer hashes y rutas en una pantalla compartida; usar su variante mono para los datos da coherencia sin una segunda familia ajena. Escala de razón 1,2 sobre 15 px: 12,5 / 15 / 18 / 21,6 / 26 / 31 px; pesos 400 y 600 (700 sólo en el título de la ruta del detalle). Sin mayúsculas sostenidas en etiquetas; los estados van en minúsculas por RN-71.

**Lo memorable: la ruta como espécimen.** `PathLabel` muestra el directorio atenuado y el nombre de archivo en peso 600; en el encabezado del detalle de evento la ruta se compone grande (26 px, mono), es el título de la página y el único gesto tipográfico audaz de la consola. `HashChip` muestra los primeros 8 hex en dos grupos de 4 (`a3f9 1c02`) con el hash completo en `title` y copia al portapapeles. Todo lo demás es silencioso.

**Layout.**

```
≥ 769 px                                  ≤ 768 px
┌────────┬───────────────────────────┐    ┌──────────────────────────┐
│ FIM    │ estado del sistema · tema │    │ ☰  FIM          tema  ⏻ │
│        ├───────────────────────────┤    ├──────────────────────────┤
│Supervi-│ /etc/ssh/sshd_config      │    │ /etc/ssh/                │
│sión    │ ─────────────────────────│    │ sshd_config              │
│ Dashb. │ [pending] agente-01 …     │    │ [pending]                │
│ Eventos│                           │    │ ┌ tarjeta por fila ────┐ │
│ Alertas│  tabla (sticky header)    │    │ │ ruta / estado / hora │ │
│Config. │                           │    │ └──────────────────────┘ │
│ Reglas │                           │    └──────────────────────────┘
│ Agentes│                           │
└────────┴───────────────────────────┘
```

Contenido alineado a la izquierda, ancho máximo 1.280 px; barra lateral de 232 px colapsable a riel de 64 px. Espaciado en base 4 (4, 8, 12, 16, 24, 32, 48). Radios con jerarquía: 6 px en controles y badges, 10 px en paneles, 14 px en modales; sin sombras salvo el modal. El Dashboard abandona la grilla de tarjetas con números grandes: una barra proporcional de eventos por estado (cada segmento es enlace al filtro) más la lista de pendientes críticos y altos, que es lo que el operador tiene que mirar.

**Movimiento.** Sólo en respuesta a acciones: apertura de modal y panel lateral (120 ms, opacidad y desplazamiento de 4 px), y el cambio de tema sin transición de color (evita destellos). Todo desactivado con `prefers-reduced-motion`.

**Revisión contra los defaults.** El primer borrador era un fondo casi negro con un acento verde «terminal»: es el default de cualquier herramienta de seguridad y se descartó por la tinta de sello violeta, que no compite con los colores de estado. También se descartó una grilla de tarjetas KPI idénticas en el Dashboard (el kit SaaS) a favor de la barra proporcional, y se evitaron etiquetas en mayúsculas sostenidas y metadatos unidos por puntos medios.

### D-2 · Tokens y temas en `@theme` con `[data-theme]`

`@theme` declara los tokens semánticos con los valores del tema oscuro; un bloque `[data-theme="light"] { --color-…: … }` los redefine. Tailwind v4 genera las utilidades (`bg-surface`, `text-muted`, `border-line`, `bg-status-pending`) a partir de las variables, así que el cambio de tema es sólo un atributo. `frontend/public/theme-init.js` (síncrono en `<head>`) lee `localStorage['fim.theme']` o `matchMedia('(prefers-color-scheme: light)')` y fija `data-theme` antes del primer pintado; un hook `useTheme` lo cambia y persiste. *Alternativa descartada*: la variante `dark:` de Tailwind por clase — duplica cada utilidad en cada componente y deja colores literales dispersos. *Alternativa descartada*: script inline — lo bloquea la CSP.

### D-3 · Componentes base en `components/ui/`

`Button` (primario, secundario, peligro, fantasma; estado `loading`), `StatusBadge`, `PathLabel`, `HashChip`, `Modal`, `DataState`, `ResponsiveTable` (tabla en ≥ 640 px, lista de tarjetas por debajo, con la misma definición de columnas), `EmptyState`, `ThemeToggle`. Los componentes existentes (`EventsTable`, `AgentCard`, modales) se reescriben sobre éstos sin cambiar sus contratos de props salvo lo que exigen los arreglos. `Modal` implementa el atrapado de foco sin dependencia nueva (lista de focuseables + `keydown`), con `inert` sobre el resto del documento.

### D-4 · Lector único de errores

`frontend/src/api/errors.ts` exporta `readApiError(err: unknown): ApiError` y `apiErrorMessage(err, fallback)`. Se borra el lector local de `useEventActions.ts:34-41` y toda lectura directa de `err.response.data`. Una regla de ESLint `no-restricted-syntax` prohíbe `response.data.detail` fuera de `api/errors.ts` para que el defecto no vuelva.

### D-5 · Sesión: renovación en segundo plano y salida limpia

El store separa `status: 'checking' | 'authenticated' | 'anonymous'` (sólo la verificación inicial pasa por `checking`) de la renovación: `refreshToken({ background: true })` no toca `status`. Una función `endSession(reason: 'logout' | 'expired' | 'password_changed')` limpia el store, llama a `queryClient.clear()` (el `QueryClient` se exporta desde un módulo propio para usarlo fuera de React) y navega a `/login` con el aviso correspondiente. El interceptor de Axios que hoy reintenta tras un 401 usa `endSession('expired')` cuando el refresh falla. *Alternativa descartada* para B1: que el backend emita tokens nuevos tras el cambio — descartada en D89/RN-183.

### D-6 · Gate de scope y rol antes de montar

`ProtectedRoute` decide en render, no en `useEffect`: con `scope = password_change_only` devuelve `<Navigate to="/change-password">` antes de renderizar `<Outlet>`, así ninguna página llega a disparar consultas (D16). El rol se expone con `useCan()` (`role === 'admin'`) y los controles de mutación se envuelven en `<Can>`; el resto de la vista se muestra igual.

### D-7 · Detalle, cadena y reconsulta del comando

`useEventId()` valida `:id` (`/^[1-9]\d*$/`) y devuelve `null` si no lo es; `useEvent` queda `enabled: id !== null`. La reconsulta usa `refetchInterval` de TanStack Query como función: `ack_status === 'pending' && Date.now() - pendingSince < 60_000 ? 3_000 : false`, donde `pendingSince` se guarda al observar la transición a `pending`. El motivo usa `getActionErrorMeta` ampliado con los códigos de comando conocidos (`no_restorable_content`, `artifact_not_found`, `path_occupied`, `path_outside_watch_paths`, entre otros, tomados de los specs de cuarentena y restauración).

### D-8 · `ack_error` en el backend

`_get_ack_status_map` (`events/router.py:300`) pasa a devolver `{event_id: (ack_status, error)}` con la misma consulta; `EventOut.ack_error` se llena con `error[:200]` sólo si `ack_status == 'failed'`. Es el único cambio de backend; se elige sobre un endpoint nuevo de comandos porque el dato ya viaja en la misma fila y la UI lo necesita junto al estado.

### D-9 · Lista de eventos al día

`useAlertsSSE` invalida además `['events']` (y `['event']` del detalle abierto) en cada mensaje. `useEvents` agrega `refetchInterval: 15_000` y `refetchIntervalInBackground: false`. Las query keys incluyen el valor del filtro ya debounced, de modo que una respuesta tardía de un valor anterior cae en otra entrada de caché y no reemplaza la vigente (M9). `parsePageParams` sanea `page`/`page_size` antes de construir la key.

### D-10 · Editor de rutas y rescan

El editor normaliza con las mismas reglas del backend en `utils/watchPaths.ts` (función pura con tests), toma el valor escrito al guardar y deshabilita el guardado con lista vacía. El modal de rescan recibe `watchPaths` como prop y reinicia su selección en cada apertura (`key` por apertura), y su confirmación queda deshabilitada sin selección.

### D-11 · Diff por palabras y proceso desconocido

`compareMethod={DiffMethod.WORDS_WITH_SPACE}` y `styles` derivados de los tokens del tema activo (el componente recibe `useDarkTheme` según `data-theme`). `formatProcess` en `utils/process.ts` centraliza «desconocido» para pid `null`/`0` y exe `null`/`"?"`.

### D-12 · División por ruta

`React.lazy` para todas las páginas salvo `Login` y `ForcePasswordChange`; `Suspense` con `DataState` de carga dentro de `MainLayout` para que la barra lateral no parpadee. `vite.config.ts` agrega `build.rollupOptions.output.manualChunks` sólo para aislar `react-diff-viewer-continued` (la dependencia más pesada, usada sólo en el detalle) si el chunk de la página de detalle supera los 250 kB.

### D-13 · ESLint y dependencias

ESLint 9 de configuración plana con `typescript-eslint` `recommendedTypeChecked` sobre `src/`, `react-hooks` y `react-refresh`; los tests usan `globals.vitest`. Se arreglan los hallazgos en vez de desactivarlos. Dependencias: `axios` a `^1.21`, `react-router-dom` a `^7.18.5`; se corre `pnpm audit --prod` y se resuelve cualquier residual alto con la versión corregida o un `overrides` documentado.

### D-14 · Tests

Vitest + Testing Library para cada arreglo, con mocks en la forma real (`{"detail": {...}}`); se agrega un helper `mockApiError(status, detail)` en `src/test/` para que los mocks no puedan inventar otra forma. Los tests existentes que mockeaban `{code}` en la raíz o `{count}` sin `detail` se corrigen con un comentario que cita esta change. Playwright sólo agrega, si es barato, un caso de desborde a 375 px y el cambio de tema; la suite E2E existente no se reescribe.

## Risks / Trade-offs

- [Reescritura amplia de componentes rompe tests por selectores de texto o clases] → los tests consultan por rol y nombre accesible; se mantienen los textos funcionales (toasts y avisos citados por specs) y se cambia sólo la presentación.
- [`exhaustive-deps` como error obliga a tocar efectos que hoy funcionan] → se corrigen uno por uno con test; un efecto que deba omitir una dependencia lleva comentario y `eslint-disable-next-line` justificado.
- [Reconsulta del detalle carga el backend] → acotada a 3 s durante 60 s y sólo con `ack_status = pending` y la pestaña visible.
- [La Change 71 no está desplegada al probar] → los tests mockean las formas nuevas; `readApiError` también acepta los string heredados, así que la consola degrada a mensajes legibles con un backend anterior.
- [Fuentes empaquetadas suman peso] → se cargan sólo los ejes y subconjuntos latinos necesarios (`latin` y `latin-ext`), con `font-display: swap`.
- [Contraste de los colores de estado en tema claro] → la tarea 2.2 verifica cada par con la fórmula WCAG y ajusta el tono antes de usarlo.

## Migration Plan

Sin migración de datos. Desplegar después de la Change 71 (o junto con ella). Rollback: volver a la imagen anterior del frontend; el campo `ack_error` es aditivo y un frontend anterior lo ignora.

## Open Questions

Ninguna. Las suposiciones nuevas quedaron cerradas en D93/RN-187, y las del contrato con el backend en D89–D91.
