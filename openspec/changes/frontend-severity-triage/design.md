## Context

Dos defectos de frontend, verificados contra el sistema vivo (ver [proposal](proposal.md)): la tabla de eventos no muestra severidad ni contexto de proceso, y `POST /actions/bulk-reject` se emite con una forma que el backend rechaza con 422 en el 100% de las llamadas. El backend no se toca: severidad persistida, filtro repetible y contrato de bulk-reject ya existen y responden correctamente.

El estado del laboratorio al diseñar acota el problema con precisión: **142 eventos `pending`, de los cuales 140 son `low`, 1 es `critical` y 1 es `high`**. La cola de triage tiene 142 filas y 2 que importan. Esa proporción es la que gobierna las decisiones de abajo: no se está diseñando una vista para leer con calma, se está diseñando una para encontrar dos agujas en tres páginas.

Restricciones que no se negocian:

- **El backend pagina en SQL y no expone parámetro de orden** (`backend/app/modules/events/router.py:105`, `ORDER BY created_at DESC` fijo). Cualquier cosa que el frontend haga con el orden actúa sobre 50 filas de 142.
- **US-06 fija el orden por defecto** (`docs/historias_de_usuario.md:152`) y `test_list_events_orders_by_created_at_desc` lo asserta.
- **C1/RN-71 obliga al léxico canónico en toda la UI** (`docs/flujo_de_usuario.md:1074`), con excepción única para botones de acción.
- **La fila ya lleva tres badges** (`EventsTable.tsx:124-154`) y una columna de fecha tabular. El presupuesto visual está gastado.
- **El proyecto no tiene msw ni ninguna librería de intercepción HTTP** (`frontend/package.json`), y la convención vigente de tests mockea `@/api/client` (`Dashboard.test.tsx:15`, `api/events.test.ts:11`).
- **Vitest fija `TZ` en la configuración** (`frontend/vitest.config.ts`), precedente de la change 44 para que un test no pueda vaciarse en silencio por el entorno.

## Goals / Non-Goals

**Goals:**

- Que el operador vea la severidad de un evento sin leer la fila, y llegue desde el KPI a la lista prefiltrada en un click.
- Cerrar el criterio de contenido de fila de US-06 completo, no a medias.
- Que el rechazo en lote funcione, y que **no pueda volver a romperse en silencio**: cualquier divergencia entre la forma que emite el cliente y la que acepta el backend debe poner algo en rojo.
- Corregir la spec `frontend-events`, que hoy prescribe el contrato equivocado.
- Eliminar la triplicación de la paleta de severidad en vez de agregarle una cuarta copia.

**Non-Goals:**

- Cambiar el orden por defecto del listado (ver D-3).
- Tocar código de producción del backend.
- Introducir dependencias nuevas en el frontend (ver D-6).
- Resolver los demás criterios abiertos de US-06/07/08/25 enumerados como fuera de scope en el proposal.

## Decisions

### D-1 — La severidad se codifica dos veces: banda de borde para escanear, texto canónico para leer

La fila lleva **una banda de color de 4px en el borde izquierdo** (`border-l-4`) y **una celda de texto** con el valor canónico en minúsculas, con tratamiento tipográfico deliberadamente bajo (mono, `text-xs`, color del nivel, sin fondo ni borde).

*Por qué no un cuarto badge.* La celda Estado ya puede mostrar dos chips simultáneos (`status` + `action_failed`) y la de Ejecución un tercero. Un cuarto badge no agrega un eje: agrega un competidor en el mismo eje, y en la fila más cargada —un `pending` con `action_failed` y `ack_status: failed`— habría cuatro rectángulos de colores saturados disputando la atención. La banda de borde ocupa un canal visual **que hoy está vacío** y que se lee en diagonal sobre una lista larga sin fijar la vista en ninguna fila: es la codificación correcta para "encontrar dos entre ciento cuarenta".

*Por qué además el texto.* El color solo no es una codificación accesible (WCAG 1.4.1, *Use of Color*), y `critical` contra `high` son rojo contra naranja: adyacentes en el espectro y el par exacto que un deuteranope no separa. Pero la razón principal no es la accesibilidad: **US-06 pide que la fila "muestre" la severidad**, y una banda de color no muestra un valor, lo sugiere. El texto es el criterio; la banda es la ergonomía.

*Por qué bajo cromatismo en el texto.* Si la celda fuera un badge con fondo, volveríamos al problema que la banda resuelve. El texto plano en el color del nivel es legible cuando se lo mira y silencioso cuando no.

*Alternativas descartadas.* Un ícono por nivel (agrega un vocabulario nuevo que el operador tiene que aprender, y el proyecto ya usa texto canónico para status, ack y severidad en Alerts/Rules). Teñir el fondo entero de la fila (colisiona con los estados de selección y de `superseded`, que ya usan el fondo: `EventsTable.tsx:84-88`). Ordenar por severidad en vez de codificarla (ver D-3).

### D-2 — La paleta se extrae a `utils/severity.ts` y los tres consumidores actuales migran

`SEVERITY_COLORS` está copiada literal, con los mismos cuatro valores, en `Alerts.tsx:28-33`, `Rules.tsx:12-17` y `FailedAlerts.tsx:11-16`. La opción barata era una cuarta copia en `EventsTable`; la correcta es un helper con contrato, siguiendo la convención que el proyecto ya tiene para exactamente este problema (`utils/ackStatus.ts`, `utils/actionFailed.ts`, `utils/timeDisplay.ts`), y migrar las tres copias.

El helper expone la clase de texto (lo que los tres consumidores actuales necesitan), la clase de banda (lo que `EventsTable` necesita) y un **rango numérico de precedencia** — `critical > high > medium > low` —, porque "cuál severidad es mayor" es conocimiento del dominio que hoy no está escrito en ninguna parte del frontend y que cualquier comparación futura (un resumen de selección, un follow-up de ordenamiento) va a necesitar. Escribirlo ahora cuesta una línea; deducirlo después de un `Record` de clases de Tailwind es cómo nacen las terceras copias.

Migrar los tres consumidores es parte del change y no un extra: dejar el helper conviviendo con las copias produce cuatro fuentes en vez de tres, que es peor que el estado actual.

*Riesgo asumido*: el diff toca tres pantallas que este change no arregla. Se mitiga porque la migración es puramente mecánica (mismo mapa, mismos valores) y porque las clases resultantes deben ser idénticas — un test lo asserta.

### D-3 — El orden por defecto no cambia, y el filtro es el instrumento correcto

Ordenar por severidad haría subir los 2 pendientes que importan por encima de los 140 que no. Se descarta, y no por conservadurismo:

1. **Contradice un requisito documentado.** US-06:152 fija el orden descendente por fecha y un test del backend lo asserta. Cambiarlo requeriría abrir una decisión de appendix, y este change no abre ninguna.
2. **No funcionaría.** El backend pagina en SQL sin parámetro de orden. Un `sort` del lado del cliente reordena las 50 filas que ya llegaron, no las 142 que existen: un `critical` en la página 3 sigue en la página 3. **Ordenar una ventana paginada por el servidor no es ordenar, es reacomodar una ventana** — y es estrictamente peor que no ordenar, porque entrega la garantía visual de una lista ordenada sin la propiedad. El operador que ve `critical` arriba concluye, razonablemente, que no hay otro más arriba.

El instrumento que sí reduce 142 a 2 es el filtro por severidad, y el deep-link es lo que lo pone a un click. Por eso las dos piezas son un solo change: la columna sin el filtro deja al operador escaneando tres páginas, y el filtro sin la columna lo deja sin saber qué está mirando cuando saca el filtro.

Un `ORDER BY severity` del lado del servidor es un follow-up legítimo. Necesita parámetro de orden en la API, índice compuesto, y su propia decisión sobre si el default cambia. Nada de eso pertenece a un change de frontend.

### D-4 — El `severity` del filtro viaja por la URL como parámetro repetible, igual que `status`

Tres puntos, tres cambios simétricos con los que ya existen para `status`: `parseEventFilters` lo lee con `sp.getAll('severity')`, `serializeEventFilters` lo escribe con `append`, y el `paramsSerializer` de `getEvents` lo emite repetido. El backend lo acepta exactamente así (`router.py:73` — `Annotated[list[RuleSeverity], Query(alias="severity")]`), verificado en vivo con `?severity=critical&severity=high`.

Que viva en la URL no es simetría por prolijidad: **es la precondición del deep-link**. `/events?status=pending&severity=critical&severity=high` tiene que ser un estado reconstruible desde una URL pegada en un ticket, igual que el resto de los filtros (W1, y el escenario "Deep-link reconstruye el estado de la vista" que la spec ya exige). Sin el round-trip por URL, la tarjeta del dashboard no tendría a dónde apuntar.

`EventFilters.severity` es `string[]`, no `EventSeverity[]`, por consistencia deliberada con `status?: string[]`: la URL es entrada no confiable y el tipado estricto acá daría una falsa garantía sobre un valor que viene de una query string. El backend valida contra su enum y devuelve 422 ante un valor inválido — que es donde corresponde validarlo.

### D-5 — El contrato de wire se afirma desde los dos lados, sobre un único fixture versionado

Este es el corazón del change, porque es lo único que impide que el defecto 2 vuelva.

**El diagnóstico completo.** Es tentador decir "el problema fue mockear el módulo de API en vez del cliente HTTP". Es cierto pero **no es suficiente**, y conviene decirlo con precisión: `bulkReject` llama `apiClient.post(url, body)`, así que incluso el mock de módulo vigente en el proyecto (`vi.mock('@/api/client')`) captura el objeto del cuerpo. Un test escrito en su momento habría afirmado `{items:[…], action:'restore'}` — **la creencia equivocada, escrita por la misma persona con el mismo modelo mental que produjo el código** — y habría pasado. La profundidad del mock no era el problema. El problema es que **ningún artefacto del lado del frontend sabía qué acepta el backend**, y ninguno del lado del backend sabía qué emite el frontend. Del otro lado hay un test llamado `test_bulk_reject_uses_items_contract_with_per_item_action`, en verde, sobre la forma correcta. Dos suites verdes, dos contratos incompatibles, cero aserciones compartidas.

**La solución: un solo artefacto que los dos lados asertan.**

```
contracts/actions.bulk-reject.request.json
```

- **Frontend**: instala un adaptador de captura sobre el cliente axios **real** (`apiClient.defaults.adapter`), llama `bulkReject(...)` sin mockear `@/api/client`, y compara `JSON.parse(config.data)` contra el fixture. La captura ocurre después de `transformRequest`, así que lo comparado es el cuerpo **serializado** que saldría al cable, no el objeto de JavaScript que lo precede.
- **Backend**: lee el mismo archivo y afirma (a) que `BulkRejectRequest.model_validate(fixture)` no levanta, y (b) que `POST /actions/bulk-reject` con ese cuerpo no devuelve 422.
- **Caso negativo, obligatorio en los dos lados**: la forma vieja —acción arriba, ausente por ítem— debe ser **rechazada**. Un guard que nunca se probó contra su propio caso negativo es cómo la change 44 descubrió que `test_fix09_no_utcnow_in_production_modules` afirmaba lo contrario de la verdad. No se repite ese error acá.

**Por qué el fixture y no un literal en cada test.** Un literal en el test del frontend es la misma creencia unilateral, escrita dos veces. El fixture solo tiene valor porque **el backend lo valida**: es el único punto donde las dos creencias se encuentran y pueden discrepar. Si el schema del backend cambia, su test se pone rojo sobre el fixture; si el cliente del frontend cambia, su test se pone rojo sobre el mismo fixture. Ninguno de los dos lados puede moverse solo.

**Por qué la captura tiene que ser del cuerpo serializado.** El fixture es JSON, y tiene que serlo para que Python lo lea. Comparar un objeto de JavaScript contra JSON parseado esconde justamente la clase de diferencias que solo aparecen al serializar (claves `undefined` que desaparecen, enums que se estrechan a string, instancias que se colapsan). Capturar en el adaptador es lo que hace que la comparación sea honesta.

**Por qué el adaptador y no msw.** msw es la herramienta canónica y sería una dependencia nueva, un service worker en jsdom y una capa de configuración para obtener exactamente un dato: el cuerpo que emite axios. `apiClient.defaults.adapter = fn` es API pública de axios, son cinco líneas, no agrega dependencias y captura el mismo objeto. Si el proyecto llega a necesitar respuestas dinámicas por ruta, msw se justificará por sí solo; hoy no.

**Por qué `contracts/` en la raíz y no dentro de `frontend/` o de `backend/`.** El artefacto no pertenece a ninguno de los dos: ponerlo bajo uno lo convierte en "la creencia de ese lado, que el otro consume", que es el problema original con un archivo compartido encima. En la raíz es lo que es — el contrato — y ninguno de los dos lados es su dueño.

**Límite honesto de la garantía.** El fixture es una instantánea: prueba que el cuerpo que el cliente emite es aceptado por el schema **que corre en la suite del backend**, no por un backend desplegado con otra versión. Es la garantía correcta para un monorepo donde las dos suites corren juntas, y no pretende ser un test de integración. Y no cubre la forma de la **respuesta** — solo la de la petición; extenderlo a respuestas es un follow-up natural, no un requisito de este change.

### D-6 — El alcance de `api-contract-fixtures` en este change es bulk-reject, no todas las llamadas

La capacidad se introduce con un solo fixture. Es tentador cubrir de entrada las nueve llamadas del cliente; se descarta porque el valor de esta técnica está en los contratos donde los dos lados pudieron divergir, y aplicarla en masa ahora produciría ocho fixtures escritos leyendo el código del backend —es decir, ocho copias de la creencia del backend, sin la tensión que hace útil al mecanismo.

El filtro `severity` de `GET /events` **sí** entra, con la misma técnica, por dos razones concretas: cruza la misma frontera que acaba de fallar, y la forma repetible de un array en una query string es exactamente la clase de detalle que un mock de módulo no observa (`{severity: ['critical','high']}` es un objeto plausible que serializa de tres maneras distintas y solo una es la que el backend acepta).

El test existente de conversión de fechas (`api/events.test.ts`) queda como está: usa el mock de módulo, cubre una propiedad de transformación —no de contrato— y reescribirlo sería churn. La regla que se establece es sobre lo nuevo: **una aserción sobre la forma del cuerpo o de la query se hace contra el fixture compartido; una aserción sobre lógica de transformación puede seguir mockeando el módulo.**

### D-7 — Los tests de componente afirman lo que el operador ve, no cómo está implementado

`EventsTable` no tiene tests hoy y `docs/trazabilidad_us_tests.md:799-802` señala precisamente esta inversión como la de mayor rendimiento del proyecto: cierra criterios de US-06, US-07, US-25 y US-31 de una vez, con `user-event` ya instalado.

Los tests van contra la conducta observable, con dos reglas:

- **Nada de aserciones sobre clases de Tailwind como fin en sí mismo.** Un test que afirma `border-l-red-500` se rompe con un retoque de paleta y no dice nada sobre si el operador puede distinguir un `critical`. Las aserciones son: la fila **contiene el texto** de su severidad; la fila de un `critical` y la de un `low` **no tienen la misma clase de banda** (par positivo/negativo, el mismo patrón que `Dashboard.test.tsx` ya usa para el realce del KPI, que es lo que hace que un realce permanente falle en vez de pasar).
- **Los deep-links se asertan como destino, no como render.** El test afirma que la tarjeta del dashboard es un enlace **a** `/events?status=pending&severity=critical&severity=high`, con los dos `severity` presentes. Un `href` con un solo parámetro es exactamente el error plausible acá y tiene que fallar.

Y un test de léxico que recorre las etiquetas de estado del dashboard y afirma que ninguna difiere de su valor canónico. Es la clase de propiedad que se degrada sola cuando alguien agrega un estado nuevo, y escribirla cuesta tres líneas.

## Risks / Trade-offs

- **La banda de borde no sobrevive a un cambio de layout de tabla** (colapso a tarjetas en viewport chico, por ejemplo) → el helper expone la clase, no la incrusta; un layout alternativo consume el mismo contrato. Y la severidad sigue presente como texto, que es lo que cierra US-06: el peor caso es perder ergonomía, nunca información.
- **Migrar las tres pantallas a `utils/severity.ts` amplía el diff a código que este change no arregla** → la migración es un reemplazo mecánico del mismo mapa por el mismo mapa, y un test afirma que las clases resultantes son idénticas a las actuales. La alternativa —dejar las copias— produce cuatro fuentes de verdad, que es peor que las tres de hoy.
- **El adaptador de captura toca `apiClient.defaults`, que es estado global del módulo** → se instala y se restaura en `beforeEach`/`afterEach` del archivo que lo usa, y el helper vive en `src/test/` para que el patrón no se copie mal. Si se filtrara, el síntoma sería ruidoso (todas las requests capturadas), no silencioso.
- **El fixture puede quedar desactualizado si alguien lo edita para "que pase el test"** → editarlo pone en rojo el otro lado inmediatamente. Ese es el mecanismo entero, y es la razón por la que el caso negativo también se testea: sin él, alguien podría vaciar el fixture y las dos aserciones seguirían pasando sobre nada.
- **Con 140 de 142 pendientes en `low`, la columna de severidad discrimina poco dentro del filtro `pending`** → es exactamente al revés: 140 iguales y 2 distintos es el caso donde una banda de color rinde más, no menos. Lo que sí es cierto es que la utilidad depende de que el ruleset asigne severidades con criterio; con 5 reglas en el laboratorio (3 `critical`, 2 `high`) y `medium` sin usar en ningún evento, la paleta define cuatro niveles de los que hoy se ven tres. Se definen los cuatro igual: el nivel faltante aparece en cuanto alguien cree una regla `medium`, y descubrirlo entonces sería un defecto.
- **`bulkReject` cambia de firma** (`(items, action)` → `(items)`) → es un cambio interno al frontend con un único llamador (`useEventActions.ts:88`); TypeScript localiza el resto. Se hace así a propósito: con `action` dentro del tipo del ítem, omitirla deja de compilar, que es la garantía más barata disponible contra la reincidencia.

## Migration Plan

No hay migración: sin cambios de base de datos, sin cambios de API, sin cambios de contrato de respuesta. El despliegue es un build de frontend.

**Rollback**: revertir el commit. El único artefacto compartido nuevo es `contracts/`, que solo consumen tests. Un rollback parcial que revirtiera el frontend dejando el test del backend sería inofensivo: ese test valida el fixture contra el schema del backend y seguiría pasando.

**Verificación post-despliegue**, en este orden:

1. `/events?status=pending` muestra severidad y proceso causante en cada fila.
2. La tarjeta "Pending critical + high" navega a la lista prefiltrada, y el total que muestra la lista coincide con el número de la tarjeta. **Si difieren, el filtro está mal construido** — es la comprobación más barata de que el deep-link y el KPI hacen la misma consulta.
3. Un rechazo en lote de dos eventos `pending` devuelve 200 y el toast de éxito con los conteos.
4. Ninguna etiqueta de estado del dashboard difiere de la que muestra la tabla para el mismo estado.

## Open Questions

Ninguna que bloquee. Dos que este change deja registradas a propósito, para que se resuelvan a propósito:

- **El selector de estados enumera 6 de 7** (`Events.tsx:10-17`; `superseded` aparece solo con el toggle activo). Es criterio abierto de US-07 y una pregunta de UX real: un checkbox para un estado que el toggle excluye es contradictorio, y la respuesta correcta puede ser corregir la historia en vez del código. No se resuelve de arrastre acá.
- **`ORDER BY severity` del lado del servidor**, con parámetro de orden en `GET /events` e índice compuesto sobre `(severity, created_at)`. Es la forma correcta del impulso que D-3 rechaza, y necesita decisión sobre si el default de US-06 cambia — es decir, appendix.
