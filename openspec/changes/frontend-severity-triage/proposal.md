## Why

**La consola de triage no muestra la severidad, y la acción masiva de rechazo nunca funcionó.** Los dos defectos son independientes en el código y tienen el mismo origen: en ambos casos la especificación escrita se apartó de lo que el requisito pedía o de lo que el backend implementa, y el código siguió fielmente a la especificación equivocada. No son errores de programación; son roturas de trazabilidad que quedaron en verde.

### Defecto 1 — la cola de pendientes no distingue lo urgente de lo trivial

`frontend/src/components/ui/EventsTable.tsx:74-79` renderiza cuatro columnas: Path, Estado, Ejecución, Detectado. **No hay columna de severidad**, y `EventFilters` (`frontend/src/api/events.ts:66-74`) no tiene campo `severity`, de modo que la pantalla de eventos no ofrece filtro por severidad. La severidad no se renderiza en ningún punto del flujo de eventos: `rg severity frontend/src` la encuentra declarada en el tipo (`api/events.ts:34`), usada en el dashboard, en alertas y en reglas — y en ninguna parte de `EventsTable.tsx` ni de `EventDetail.tsx`.

El dato existe entero del otro lado. Verificado contra la API viva del laboratorio, no deducido:

| Consulta | `total` |
|---|---|
| `GET /events?severity=critical` | 41 |
| `GET /events?severity=high` | 7245 |
| `GET /events?severity=medium` | 0 |
| `GET /events?severity=low` | 376 |
| `GET /events?status=pending` | **142** |
| `GET /events?status=pending&severity=critical` | **1** |
| `GET /events?status=pending&severity=high` | **1** |
| `GET /events?status=pending&severity=low` | **140** |

Ese último bloque es el defecto entero en cuatro números. **La cola de triage tiene 142 eventos y exactamente 2 de ellos importan.** El dashboard lo sabe y lo anuncia — "Pending critical + high: 2" — y después manda al operador a una lista de 142 filas, repartidas en tres páginas, ordenadas por fecha, visualmente idénticas entre sí. Sabe cuántas agujas hay y no dice dónde están. **Una consola de triage que no muestra severidad no es una consola de triage**, y la asimetría entre las dos pantallas es la forma más nítida del problema: el sistema ya calculó la respuesta y la pantalla siguiente la descarta.

**Esto no abre una suposición: la cierra D34 / RN-128** (`docs/reglas_de_negocio.md:1124`, `docs/arquitectura_stack.md:2388`), que persiste `Event.severity`, expone el filtro repetible en `GET /events` y publica el campo en `EventOut`. El "problema base" que D34 documenta era *exactamente* este KPI del dashboard devolviendo basura; la decisión arregló el backend y el KPI, y dejó sin consumir el resto de lo que habilitó. Y **US-06** (`docs/historias_de_usuario.md:151`) exige el campo en la fila desde antes que existiera la columna en la base.

### Defecto 2 — el rechazo en lote devuelve 422 el 100% de las veces

`frontend/src/api/actions.ts:64-66` publica `{ items: [{event_id, version}], action }`, con la acción **al nivel superior**. El backend la exige **por ítem**: `BulkRejectItem` (`backend/app/modules/actions/schemas.py:57-61`) declara `action: RejectAction` obligatoria, sin default, dentro de cada elemento de `items`. Pydantic ignora la clave sobrante de arriba y falla por la que falta abajo.

Verificado contra la API viva:

```
POST /actions/bulk-reject  {"items":[{"event_id":…,"version":1}],"action":"restore"}
→ HTTP 422  {"detail":[{"type":"missing","loc":["body","items",0,"action"],…}]}

POST /actions/bulk-reject  {"items":[{"event_id":…,"version":1,"action":"restore"}]}
→ HTTP 200  {"succeeded":[],"failed":[…],"baseline_absent":{}}
```

El operador ve `toast.error('Error al rechazar en lote')` (`frontend/src/hooks/useEventActions.ts:94`) y nada más: el manejador descarta el status y el cuerpo del error, así que el 422 estructural se presenta igual que una caída de red. El tipo `BulkRejectItem` del frontend (`api/actions.ts:20-23`) ni siquiera declara el campo. La mitad de US-25 es código muerto desde que se escribió.

### Por qué sobrevivió: hay un test del backend que afirma lo contrario, y está en verde

`backend/tests/test_actions_router.py:405` se llama `test_bulk_reject_uses_items_contract_with_per_item_action` — literalmente "cada ítem lleva su propia acción" — y pasa. Del otro lado, `frontend/src/api/actions.ts` manda la acción arriba, y su suite también pasa. **Las dos suites verifican la creencia de su propio lado y ninguna observa la del otro.** El contrato tiene dos implementaciones y cero aserciones compartidas; el 422 solo es observable en el punto de encuentro, que ningún test ejecuta.

La causa raíz está un nivel más arriba, y es la parte incómoda: **la especificación del proyecto también está equivocada.** `openspec/specs/frontend-events/spec.md:167` dice, textualmente, que el bulk reject «SHALL llamar `POST /actions/bulk-reject` con `{items:[{event_id, version}], action}`», y el escenario de la línea 183 lo repite. El frontend no se desvió de su spec: la cumplió. Arreglar solo el código dejaría el defecto vivo en el artefacto que gobierna al código.

El mismo patrón explica el defecto 1. `openspec/specs/frontend-events/spec.md:55` fija el contenido de la fila en «al menos `path`, `status`, `detected_at`» — la spec dejó caer la severidad, el tipo de acción y el contexto de proceso que US-06 enumera. El código implementó la spec, no la historia. `docs/trazabilidad_us_tests.md:298` ya lo tiene registrado como criterio abierto: *"SIN TEST — y sin implementación: `EventsTable.tsx` no renderiza severidad, acción ni contexto de proceso"*.

### Sobre el alcance de la fila: el criterio de US-06 es indivisible

US-06 (`docs/historias_de_usuario.md:151`) pide un solo criterio: *"Cada fila muestra: path del archivo, estado, tipo de acción, severidad, fecha de creación y **proceso causante** (PID, UID, `exe`…)"*. Y `docs/trazabilidad_us_tests.md:49-53` fija una regla explícita para este caso: cuando la implementación es más angosta que el texto del criterio, el test de lo implementado **no cierra el criterio**. Agregar solo la severidad dejaría US-06 exactamente donde está: `parcial`, con el mismo criterio abierto.

De los tres campos que faltan, dos se cierran acá y uno ya está cerrado por otra vía:

- **Severidad** — el dato viaja en `EventListItem.severity`. Se renderiza.
- **Proceso causante** — `process_pid`, `process_uid` y `process_exe` ya viajan en el payload del listado y no se muestran. Se renderizan.
- **Tipo de acción** — `EventOut` no expone un campo `action`, y **no hace falta que lo exponga**: desde D35/RN-129 (`docs/reglas_de_negocio.md:1139`) el backend *deriva* el `status` del evento a partir de la acción y de si falló, de modo que `auto_restored`, `quarantined` y `alert_only` **son** el tipo de acción ejecutado, y `pending` es "ninguna acción automática, requiere decisión". La columna Estado ya lo lleva. Esto no requiere tocar el backend y no requiere decisión nueva: es la lectura directa de D35.

Por eso el alcance de la fila es severidad **y** proceso causante. Es una ampliación deliberada respecto de "agregar la columna de severidad", y su justificación es que sin ella el change no cierra nada en términos de trazabilidad.

## What Changes

- **La severidad pasa a ser el eje visual primario de la fila, no un cuarto badge.** La fila ya carga tres badges (`EventsTable.tsx:124-154`: status, action_failed, ack_status) y un cuarto competiría con ellos en vez de ordenarlos. La señal de escaneo va en el **borde izquierdo** de la fila — una banda de color, fuera del flujo de badges, legible en diagonal sobre una lista de 50 filas — acompañada de una celda de texto de bajo cromatismo con el valor canónico. El color solo no es una codificación accesible (WCAG 1.4.1); el texto no es redundancia decorativa, es el criterio de US-06.
- **La paleta de severidad deja de estar triplicada.** `SEVERITY_COLORS` está copiada literal en `Alerts.tsx:28-33`, `Rules.tsx:12-17` y `FailedAlerts.tsx:11-16`. Agregar una cuarta copia en `EventsTable` sería consolidar el error. Se extrae un helper compartido con contrato propio, siguiendo la convención ya establecida del proyecto (`utils/ackStatus.ts`, `utils/actionFailed.ts`, `utils/timeDisplay.ts`), y los tres consumidores actuales pasan a usarlo.
- **La fila muestra el proceso causante** (`process_exe` con `pid`/`uid`), como sublínea del path — el mismo tratamiento tipográfico que ya recibe `symlink_target` (`EventsTable.tsx:130-134`), que es el precedente del proyecto para contexto secundario sin gastar una columna.
- **`EventFilters` gana `severity`, y el filtro vive en la URL** como parámetro repetible, exactamente igual que `status`: `parseEventFilters` lo lee con `getAll`, `serializeEventFilters` lo escribe con `append`, el `paramsSerializer` de `getEvents` lo emite repetido. El backend ya lo acepta así (`backend/app/modules/events/router.py:73,97-98`), verificado en vivo.
- **Los KPI del dashboard pasan a ser navegación.** "Pending (todos)" enlaza a `/events?status=pending`; "Pending critical + high" a `/events?status=pending&severity=critical&severity=high`; cada tarjeta de "Eventos por estado" a su estado. Hoy son texto inerte: el dashboard sabe la respuesta y obliga al operador a reconstruir la consulta a mano.
- **El dashboard pasa a usar el léxico canónico.** `Dashboard.tsx:8-16` rotula `Pending`, `Auto-restored`, `Alert only` mientras la tabla de eventos renderiza `pending`, `auto_restored`, `alert_only`: el mismo estado con dos nombres en pantallas contiguas. C1/RN-71 (`docs/flujo_de_usuario.md:1074`) es explícito — minúsculas snake_case **en toda la UI**, con excepción única para los botones de acción (`APPROVE`, `REJECT`) como énfasis. Una etiqueta de tarjeta no es un botón de acción. Y el deep-link vuelve la divergencia funcional además de cosmética: el operador haría click en `Auto-restored` para aterrizar en una URL que dice `auto_restored` sobre filas que dicen `auto_restored`.
- **El rechazo en lote empieza a funcionar.** `BulkRejectItem` del frontend pasa a declarar `action`, espejando el schema del backend, y `bulkReject(items)` deja de recibir la acción por separado: la elección única del modal (que es lo que pide US-25) se mapea sobre cada ítem en `BulkActionBar`, donde vive la decisión de UX. Con el campo en el tipo, TypeScript impide volver a omitirlo.
- **El error del lote deja de ser opaco.** Un 422 en una acción masiva es una violación de contrato, no una falla operativa, y presentarlo con el mismo texto genérico que un timeout es lo que mantuvo el defecto invisible durante toda la vida del proyecto. El manejador distingue el 422 y lo rotula como tal.
- **La spec del proyecto se corrige junto con el código.** `frontend-events` lleva dos requisitos con el contrato equivocado o incompleto; arreglar el código sin arreglarlos dejaría el defecto vivo en el artefacto que gobierna al código.
- **Un contrato de wire verificado por los dos lados.** Un fixture JSON único, versionado fuera de `frontend/` y de `backend/`, que el test del frontend compara contra el cuerpo **serializado** que emite el cliente HTTP real, y que el test del backend valida contra el schema Pydantic real y contra el endpoint real. Cada lado afirma sobre el mismo artefacto; ninguno puede derivar sin poner algo en rojo. Ver D-5 del [design](design.md) para por qué bajar una capa en el mock es necesario pero **no suficiente**, y por qué la parte que importa es que la aserción sea de dos lados.

**Fuera de scope** (declarado, no omitido):

- **Cambiar el orden por defecto del listado.** Es tentador —ordenar por severidad pondría los 2 pendientes que importan arriba de los 140 que no— y está **mal por dos razones independientes**. Primero, US-06 lo fija como criterio (`historias_de_usuario.md:152`, "ordenado por fecha de creación descendente por defecto") y `test_list_events_orders_by_created_at_desc` lo asserta: cambiarlo contradice un requisito documentado y requeriría decisión de appendix. Segundo, y más grave, **no funcionaría**: el backend pagina en SQL (`router.py:105`) y no expone parámetro de orden, así que un ordenamiento del lado del cliente reordena las 50 filas que ya llegaron, no las 142 que existen. Un `critical` en la página 3 seguiría en la página 3, ahora con la apariencia tranquilizadora de una lista ordenada. **Ordenar una ventana paginada por el servidor no es ordenar; es reacomodar una ventana**, y es peor que no ordenar porque miente sobre su alcance. El instrumento correcto para "llevame a lo que importa" es el filtro, y el deep-link es lo que lo hace un solo click. Un `ORDER BY severity` del lado del servidor es un follow-up legítimo, con su propia change y su propio índice.
- **Tocar el backend.** No hace falta: severidad, filtro repetible y contrato de bulk-reject ya están implementados y verificados en vivo. Lo único que se agrega del lado del backend es un test que lee el fixture compartido.
- **`ALL_STATUSES` enumera 6 de los 7 estados** (`Events.tsx:10-17`; `superseded` solo aparece condicionalmente). Es un criterio abierto de US-07 (`trazabilidad_us_tests.md:307`) y una pregunta de UX real —un checkbox para un estado que el toggle excluye es contradictorio—, no un descuido. Merece resolverse a propósito, no de arrastre.
- **Detalle expandible del resumen bulk** (US-25, hoy solo un toast agregado) y **severidad en `EventDetail.tsx`** (US-08, `historias_de_usuario.md:180`). Ambos son criterios abiertos reales; ninguno es este defecto.
- **El appendix de `arquitectura_stack.md` quedó rezagado**: su párrafo introductorio (`:1928`) y su tabla de cierre (hasta `:2469`) siguen deteniéndose en D34, mientras `reglas_de_negocio.md` va por D39/RN-133. Es higiene documental que conviene registrar, no arreglar de paso acá.

## Capabilities

### New Capabilities

- `frontend-severity-display`: contrato único de presentación de severidad en la interfaz — la paleta de los cuatro niveles, la codificación de escaneo (banda de borde) separada de la codificación accesible (texto canónico), y el orden de precedencia entre niveles. Hoy la responsabilidad está copiada literal en tres archivos y ausente del cuarto lugar donde más importa; que sea capacidad propia es lo que permite afirmarla con un test en vez de revisarla a ojo — el mismo motivo por el que `frontend-time-display` se separó en la change 44.
- `api-contract-fixtures`: contrato de wire entre el cliente del frontend y la API del backend, materializado en fixtures JSON versionados que **ambos** lados asertan. El frontend afirma que el cuerpo serializado que emite es igual al fixture; el backend afirma que el fixture es aceptado por el schema y por el endpoint. Es la capacidad que hoy no existe y cuya ausencia es la causa directa de que el defecto 2 haya sobrevivido con las dos suites en verde.

### Modified Capabilities

- `frontend-events`: el contenido mínimo de la fila pasa a incluir severidad y contexto de proceso (hoy la spec fija `path`, `status`, `detected_at` y omite lo que US-06 pide); el listado gana filtro por severidad sincronizado en URL; y **el requisito de bulk reject se corrige**, porque hoy la spec prescribe el cuerpo `{items:[{event_id, version}], action}` que el backend rechaza con 422 — el requisito describe un contrato que no existe.
- `frontend-dashboard`: los contadores dejan de ser texto inerte y pasan a enlazar a la lista prefiltrada equivalente, y las etiquetas de estado pasan al léxico canónico de C1/RN-71.

## Impact

**Frontend** — `components/ui/EventsTable.tsx` (columna y banda de severidad, contexto de proceso), `pages/Events.tsx` (control de filtro por severidad), `api/events.ts` (`EventFilters.severity` + serialización repetible), `utils/eventFilters.ts` (parse/serialize de `severity`), `pages/Dashboard.tsx` (tarjetas navegables, léxico canónico), `api/actions.ts` (`BulkRejectItem.action`, firma de `bulkReject`), `components/ui/BulkActionBar.tsx` (mapeo de la acción única sobre los ítems), `hooks/useEventActions.ts` (422 distinguible), y un `utils/severity.ts` nuevo que absorbe las tres copias de `SEVERITY_COLORS` en `pages/Alerts.tsx`, `pages/Rules.tsx` y `pages/FailedAlerts.tsx`.

**Backend** — **sin cambios de producción.** Se agrega un test que lee el fixture compartido y lo valida contra `BulkRejectRequest` y contra `POST /actions/bulk-reject`.

**Compartido** — un directorio `contracts/` nuevo en la raíz del repositorio, que no pertenece a ninguno de los dos lados por diseño (ver D-5 del design).

**Agente** — sin cambios.

**Base de datos** — sin cambios. `Event.severity` ya existe y está indexada (`backend/app/modules/events/models.py:37`).

**Reglas cubiertas**: RN-128/D34 (severidad persistida y filtrable — se consume del lado de la consola lo que la decisión habilitó), RN-129/D35 (el `status` derivado es el tipo de acción — se aplica su lectura, sin alterarla), C1/RN-71 (léxico canónico — se corrige la divergencia del dashboard). **Decisiones aplicadas**: D34, D35, D3 (sin migraciones nuevas: no hay ninguna). **Ninguna decisión nueva de appendix**, y la afirmación es verificable punto por punto: la severidad en la fila la pide US-06:151; el filtro por severidad lo habilita D34 explícitamente; el proceso causante lo pide US-06:151 y ya viaja en el payload; el `event_ids[]` de US-25 ya fue superado por el contrato `items[]` implementado y registrado en `trazabilidad_us_tests.md:626`; y el léxico del dashboard es aplicación literal de C1. Lo único genuinamente nuevo —la codificación visual de la severidad y la forma del fixture de contrato— son decisiones de diseño, no de política, y viven en `design.md`.

**Historias afectadas**: US-06 (cierra el criterio de contenido de fila), US-07 (agrega filtro por severidad; el criterio de los 7 estados sigue abierto), US-25 (el rechazo en lote pasa a existir), US-05 (el realce del dashboard pasa a ser accionable).
