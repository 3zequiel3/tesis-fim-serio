## ADDED Requirements

### Requirement: Tokens de diseño CSS-first con tema claro y oscuro

La consola SHALL definir sus tokens de color, tipografía, espaciado y radios en el bloque `@theme` de `frontend/src/globals.css` (Tailwind v4, sin `tailwind.config.js`), con valores semánticos (`--color-surface`, `--color-surface-raised`, `--color-text`, `--color-text-muted`, `--color-line`, `--color-accent`, y un par fondo/texto por cada estado de RN-71) que cambian según `[data-theme="light"]` o `[data-theme="dark"]` en `<html>`. Los componentes MUST usar sólo esos tokens, no colores literales de la paleta de Tailwind. El tema inicial SHALL seguir `prefers-color-scheme` cuando no hay elección guardada; un conmutador accesible en la barra superior SHALL alternar el tema y la elección SHALL persistirse en `localStorage` (`fim.theme`). El atributo `data-theme` SHALL fijarse antes del primer pintado por `frontend/public/theme-init.js`, cargado desde `index.html` (la CSP prohíbe scripts inline). Todo par texto/fondo MUST cumplir contraste WCAG AA (4,5:1 para texto normal) en ambos temas (D93/RN-187).

#### Scenario: Primer ingreso respeta el sistema operativo
- **WHEN** no hay `fim.theme` guardado y el sistema prefiere el esquema claro
- **THEN** `<html>` tiene `data-theme="light"` antes de que React monte

#### Scenario: La elección persiste
- **WHEN** el usuario activa el conmutador para pasar a tema oscuro y recarga la página
- **THEN** la consola carga en tema oscuro aunque el sistema prefiera el claro

#### Scenario: Contraste suficiente
- **WHEN** se verifica cada par de tokens texto/fondo de ambos temas con la fórmula de contraste WCAG
- **THEN** todos alcanzan al menos 4,5:1

### Requirement: Tipografías empaquetadas

La consola SHALL usar Atkinson Hyperlegible Next para la interfaz y Atkinson Hyperlegible Mono para rutas, hashes e identificadores, servidas desde el propio bundle mediante paquetes `@fontsource-variable` (sin pedidos a dominios externos, compatible con `default-src 'self'`). Los textos SHALL seguir una escala tipográfica fija definida en `@theme`.

#### Scenario: Sin pedidos externos de fuentes
- **WHEN** se carga la consola compilada
- **THEN** todas las fuentes se piden al mismo origen

### Requirement: Badge único para los estados de RN-71

Un único componente `StatusBadge` SHALL representar los siete estados (`pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`) en toda la consola (tabla, tarjetas, detalle, cadena, Dashboard). Cada estado MUST combinar un color de estado, un ícono propio y el texto canónico en minúsculas snake_case (RN-71); el estado nunca se comunica sólo por color. Un valor desconocido MUST mostrarse literal con el estilo neutro.

#### Scenario: El mismo estado se ve igual en todas las vistas
- **WHEN** un evento `quarantined` aparece en la lista, en su detalle y en la cadena
- **THEN** las tres vistas renderizan el mismo `StatusBadge` con el texto `quarantined` y el mismo ícono

#### Scenario: Valor desconocido
- **WHEN** el backend devuelve un estado que el frontend no conoce
- **THEN** el badge muestra el valor literal con estilo neutro

### Requirement: Estados de carga, vacío y error en toda vista de datos

Toda vista o panel que consulta datos SHALL renderizar con un componente común `DataState` tres estados además del contenido: carga (esqueleto o indicador con texto accesible), vacío (frase que explica qué falta y, si corresponde, qué hacer) y error (mensaje de `readApiError` y botón «Reintentar»). Un `403` MUST mostrar «No tenés permiso para ver esta sección.» y MUST NOT reintentar automáticamente. Ninguna vista MUST quedar indefinidamente en carga ante un error.

#### Scenario: Error con reintento en una vista cualquiera
- **WHEN** `GET /rules` responde `500`
- **THEN** la página de reglas muestra el error y «Reintentar»

#### Scenario: Prohibido
- **WHEN** una consulta responde `403`
- **THEN** la vista muestra «No tenés permiso para ver esta sección.» sin carga eterna

### Requirement: Modales accesibles que no se cierran a mitad de una mutación

Todo modal SHALL usar un componente común `Modal` con `role="dialog"`, `aria-modal="true"`, `aria-labelledby` apuntando a su título, foco inicial en el primer control, foco atrapado mientras está abierto y devuelto al control que lo abrió al cerrarse. `Escape`, el clic fuera y el botón de cerrar MUST cerrarlo, salvo mientras su mutación está en curso, en cuyo caso los tres MUST ignorarse y los botones de acción quedar deshabilitados.

#### Scenario: Foco atrapado
- **WHEN** el modal de rechazo está abierto y el usuario presiona `Tab` desde el último control
- **THEN** el foco vuelve al primer control del modal

#### Scenario: No se cierra con la mutación en curso
- **WHEN** el admin confirma un rechazo y, antes de la respuesta, presiona `Escape`
- **THEN** el modal sigue abierto hasta que la mutación termina

### Requirement: Layout responsivo sin desborde horizontal

El layout SHALL tener una barra lateral con la navegación agrupada (Supervisión: Dashboard, Eventos, Alertas; Configuración: Reglas, Agentes) que en pantallas de más de 768 px puede colapsarse a un riel de íconos con etiquetas accesibles, y que a 768 px o menos se reemplaza por un botón de menú que abre un panel lateral con foco atrapado y cierre con `Escape`. A 375 px de ancho ninguna página MUST producir desplazamiento horizontal del documento: las tablas de eventos, reglas, agentes y alertas SHALL pasar a tarjetas por fila por debajo de 640 px o desplazarse dentro de su propio contenedor. Las rutas largas MUST cortarse sin desbordar.

#### Scenario: Menú en móvil
- **WHEN** el ancho es 375 px
- **THEN** la barra lateral no está visible y un botón de menú con nombre accesible la abre

#### Scenario: Sin desborde a 375 px
- **WHEN** cada página principal se renderiza a 375 px con datos reales de ejemplo, incluidas rutas de 200 caracteres
- **THEN** `document.documentElement.scrollWidth` no supera `clientWidth`

### Requirement: Modo lectura para roles que no son admin

La consola SHALL derivar del `role` del usuario autenticado si puede mutar: sólo `role = admin` ve controles de mutación (aprobar, rechazar, acciones masivas, liberar cuarentena, crear/editar/eliminar reglas, editar rutas, rescan, reintentar o descartar alertas). Cualquier otro `role` MUST ver las mismas vistas en modo lectura, sin esos controles, con la leyenda «Modo lectura: tu usuario no puede modificar la configuración.» en la barra superior. Hoy sólo existe el rol `admin` (RN-29, RN-44); este requisito es defensivo y no introduce un rol nuevo (D93/RN-187).

#### Scenario: Usuario que no es admin
- **WHEN** el usuario autenticado tiene `role = "viewer"` y abre el detalle de un evento `pending`
- **THEN** no se muestran Aprobar ni Rechazar y la barra superior muestra la leyenda de modo lectura

#### Scenario: Admin
- **WHEN** el usuario autenticado tiene `role = "admin"`
- **THEN** los controles de mutación se muestran según el estado de cada recurso
