## Current authority and supersession

The canonical bulk work is complete as a breaking migration: approve `{event_ids:[...]}`, reject `{event_ids:[...], action:"restore"|"quarantine"}`, no `items` alias, and legacy requests receive 422. Checked `items[]` work from the original execution is preserved only as the historical supersession record in section 6; the tasks below describe the authoritative final state.

## 1. El helper compartido de severidad (`frontend/src/utils/severity.ts`)

- [x] 1.1 Crear `frontend/src/utils/severity.ts` con su test al lado, siguiendo la convención que ya establecen `ackStatus.ts`, `actionFailed.ts` y `timeDisplay.ts`: un `Record` privado por nivel y una función de acceso que tolera lo desconocido. No exportar el `Record` — lo que se exporta es la función, para que el fallback no sea opcional en el sitio de uso.
- [x] 1.2 Definir los **cuatro** niveles (`critical`, `high`, `medium`, `low`) aunque el ruleset del laboratorio hoy produzca solo tres (`GET /events?severity=medium` devuelve 0). Un nivel que aparece por primera vez cuando alguien crea la primera regla `medium` es un nivel que se descubre como defecto.
- [x] 1.3 Cada nivel expone tres cosas: la clase de **texto** (la que consumen las tres pantallas existentes), la clase de **banda de borde** (la que consume `EventsTable`), y un **rango numérico** de precedencia con `critical > high > medium > low`. El rango es conocimiento de dominio que hoy no está escrito en ninguna parte del frontend; escribirlo ahora cuesta una línea, deducirlo después de un mapa de clases de Tailwind es cómo nacen las terceras copias.
- [x] 1.4 Las clases de texto deben ser **idénticas** a las actuales (`text-red-400`, `text-orange-400`, `text-yellow-400`, `text-blue-400`), verbatim de `Alerts.tsx:29-32`. La migración de la tarea 2 tiene que ser un no-op observable en esas pantallas; si el color cambia, deja de ser una extracción y pasa a ser un rediseño no pedido de tres pantallas que este change no arregla.
- [x] 1.5 Elegir las clases de banda de modo que **ningún par de niveles comparta una**, y que la banda de `critical` se distinga de la de `high` también en luminancia y no solo en tono: rojo contra naranja son adyacentes en el espectro y son exactamente el par que un deuteranope no separa. El texto de 1.3 es lo que cierra la accesibilidad formalmente; esto es para que la banda sirva de verdad al escanear.
- [x] 1.6 Un valor fuera de los cuatro niveles devuelve un tratamiento neutro y **no lanza**. El listado ya recibe `status` desconocidos con este mismo patrón (`EventsTable.tsx:127`, `?? 'bg-gray-700 text-gray-300'`).

## 2. Migrar las tres copias existentes de `SEVERITY_COLORS`

- [x] 2.1 Reemplazar la copia local en `frontend/src/pages/Alerts.tsx:28-33` por el helper, y borrar la constante. Dejar el helper conviviendo con las copias produce **cuatro** fuentes de verdad en vez de las tres de hoy, que es estrictamente peor que el estado actual.
- [x] 2.2 Ídem en `frontend/src/pages/Rules.tsx:12-17`.
- [x] 2.3 Ídem en `frontend/src/pages/FailedAlerts.tsx:11-16`.
- [x] 2.4 Confirmar con `rg SEVERITY_COLORS frontend/src` que no queda ninguna definición local. Si aparece una cuarta que el diseño no vio, es información: registrarla antes de borrarla.
- [x] 2.5 Test que afirma que la clase de texto que devuelve el helper para cada nivel es la que las tres pantallas producían antes. Es la aserción que vuelve la migración verificable en vez de confiable.

## 3. La fila de eventos (`frontend/src/components/ui/EventsTable.tsx`)

- [x] 3.1 Agregar una columna **Severidad** entre Estado y Ejecución, renderizando el valor canónico en minúsculas con la clase de texto del helper, en `text-xs` mono y **sin fondo ni borde**. Un chip la devolvería a competir con los tres badges que la fila ya carga (`:124-154`), que es exactamente lo que la banda existe para evitar. Ver D-1 del design.
- [x] 3.2 Agregar la **banda de borde izquierdo** al `<tr>` (`border-l-4` con la clase del helper), sin tocar las clases de fondo que ya usan `selected` y `superseded` (`:84-88`). Teñir el fondo colisionaría con los dos estados que ya lo usan.
- [x] 3.3 Verificar que la banda sobrevive a las tres combinaciones de fondo que la fila ya tiene: normal (`bg-gray-900`), seleccionada (`bg-gray-700`) y superseded (`opacity-60`). Una banda que se pierde bajo `opacity-60` deja sin señal justo a las filas que el operador está por descartar.
- [x] 3.4 Renderizar el **proceso causante** como sublínea del path, en el mismo registro tipográfico que ya usa `symlink_target` (`:130-134`): `text-[11px] text-gray-500 font-mono`. Es el precedente del proyecto para contexto secundario sin gastar una columna.
- [x] 3.5 Tratar los tres campos de proceso como opcionales de verdad: `process_pid`, `process_uid` y `process_exe` son `| null` en el tipo (`api/events.ts:31-33`). Si los tres son nulos, **no** renderizar la sublínea — ni vacía, ni con guiones, ni con `null`. Un evento sin contexto de proceso es un caso normal, no un error de datos.
- [x] 3.6 Confirmar que el ancho total sigue cabiendo: la tabla ya está dentro de un `overflow-x-auto` (`:59`), así que el peor caso es scroll horizontal y no desborde. Revisar que la columna nueva no empuje la fecha fuera del viewport en un ancho de laptop, porque la fecha es la segunda señal de triage.
- [x] 3.7 **NO** agregar una columna "tipo de acción". US-06 la pide y ya está: desde D35/RN-129 el `status` **es** la acción ejecutada (`auto_restored`, `quarantined`, `alert_only`) o su ausencia (`pending`). `EventOut` no expone un campo `action` y no hace falta que lo exponga. Si durante la implementación parece que sí hace falta, detenerse: eso contradice al design y la discrepancia es información.

## 4. El filtro por severidad (URL → petición)

- [x] 4.1 Agregar `severity?: string[]` a `EventFilters` (`frontend/src/api/events.ts:66-74`), tipado como `string[]` y **no** como `EventSeverity[]`, por simetría deliberada con `status?: string[]`: la URL es entrada no confiable y el tipo estricto acá daría una garantía falsa sobre un valor que viene de una query string. El backend valida contra su enum y responde 422. Ver D-4 del design.
- [x] 4.2 En `parseEventFilters` (`frontend/src/utils/eventFilters.ts:11`), leer `sp.getAll('severity')` con el mismo patrón que `status`: array si hay valores, `undefined` si está vacío. El `undefined` importa — es lo que mantiene la URL limpia y lo que hace que el query key de TanStack no cambie por un array vacío.
- [x] 4.3 En `serializeEventFilters` (`:26`), escribirlo con `append` por valor, igual que `status` (`:29-31`).
- [x] 4.4 En el `paramsSerializer` de `getEvents` (`api/events.ts:99-104`), emitir un `severity` por valor con `sp.append`. **No** unir con comas ni usar notación de corchetes: el backend declara `Annotated[list[RuleSeverity], Query(alias="severity")]` (`router.py:73`) y solo acepta la forma repetible. Verificado en vivo con `?severity=critical&severity=high`.
- [x] 4.5 Agregar el control de filtro en `frontend/src/pages/Events.tsx`, con la misma forma de checkboxes que el filtro de estado (`:82-105`) y un `handleSeverityToggle` simétrico a `handleStatusToggle` (`:48-55`). Los cuatro niveles, en orden de precedencia descendente — que es el orden en que el operador los busca, no el alfabético.
- [x] 4.6 Confirmar que el query key de `useEvents` (`hooks/useEvents.ts:6`) incorpora la severidad sin cambios: deriva de `['events', filters]` y el campo nuevo entra solo. Verificar que cambiar la severidad dispara refetch y no sirve una respuesta cacheada de otro filtro.
- [x] 4.7 Comprobar el caso de quitar el último nivel seleccionado: el parámetro debe desaparecer de la URL **y** de la petición, no quedar como `severity=`.

## 5. Los KPI del dashboard (`frontend/src/pages/Dashboard.tsx`)

- [x] 5.1 Convertir `StatCard` (`:47-72`) en un componente que acepta un destino opcional y, cuando lo tiene, se renderiza como `<Link>` de `react-router-dom` conservando el tratamiento visual actual (incluido el `emphasis`). Destino opcional y no obligatorio: las tarjetas de agentes y de infraestructura no tienen lista prefiltrada a la que ir, y forzarles un enlace muerto sería peor que dejarlas inertes.
- [x] 5.2 Enlazar "Pending (todos)" a `/events?status=pending`.
- [x] 5.3 Enlazar "Pending critical + high" a `/events?status=pending&severity=critical&severity=high`, con los **dos** `severity` presentes. Un `href` con uno solo es el error plausible acá y el test de 8.4 tiene que rechazarlo.
- [x] 5.4 Enlazar cada tarjeta de "Eventos por estado" a `/events?status=<estado>`. Para `superseded`, agregar además `include_superseded=true`: sin eso el enlace lleva a una lista que filtra por un estado que el default excluye, es decir, siempre vacía. Es el único destino que no es una traducción directa y es el que más fácil se rompe.
- [x] 5.5 Reemplazar `EVENT_STATUS_LABELS` (`:8-16`) por el valor canónico. C1/RN-71 (`docs/flujo_de_usuario.md:1074`) es explícito: minúsculas snake_case en **toda la UI**, con excepción única para botones de acción. Una etiqueta de tarjeta no es un botón de acción. Con el enlace de 5.4 la divergencia además deja de ser cosmética: el operador haría click en `Auto-restored` para aterrizar en una URL que dice `auto_restored` sobre filas que dicen `auto_restored`.
- [x] 5.6 Dejar `AGENT_STATUS_LABELS` (`:32-38`) **como está**. C1/RN-71 gobierna los estados de **evento**; los de agente (`online`, `offline`, `draining`, `dead`, `revoked`) no están en su alcance y `AgentCard` los renderiza con su propio criterio. Cambiarlos de arrastre sería aplicar una regla fuera de su dominio.
- [x] 5.7 Verificar que las tarjetas siguen siendo accesibles por teclado y que el foco es visible: pasan de `div` a enlace, así que entran en el orden de tabulación y ese es un cambio de comportamiento real.

## 6. El rechazo en lote (`api/actions.ts`, `BulkActionBar.tsx`, `useEventActions.ts`)

> Supersession record: tasks 6.1–6.4 originally repaired one `items[]` variant by moving `action` per item. The canonical migration replaces that completed historical approach rather than maintaining it as an alias.

- [x] 6.1 Replace item request types with canonical bulk arguments: approve receives event IDs; reject receives event IDs plus one shared `RejectAction`.
- [x] 6.2 Emit approve `{event_ids:[...]}` and reject `{event_ids:[...], action}`. Do not serialize client versions, confirmation flags, per-item actions or bulk `baseline_absent`.
- [x] 6.3 Keep the modal's single action as the top-level reject action; `BulkActionBar` passes selected IDs without mapping request objects per row.
- [x] 6.4 Update `bulkRejectMutation` and `bulkApproveMutation` to the canonical signatures and invalidate the event list after the response.
- [x] 6.5 Keep 422 distinguishable from an operational failure for both bulk endpoints.
- [x] 6.6 Confirm no frontend caller emits `items` or supplies event versions to a bulk endpoint.
- [x] 6.7 Verify through the real acceptance lab that a canonical bulk action returns 200 and produces the expected result summary.

## 7. El fixture de contrato y el arnés de captura

- [x] 7.1 Keep the shared fixture under root `contracts/`, asserted by both frontend and backend.
- [x] 7.2 Make `contracts/actions.bulk-reject.request.json` canonical: `{"event_ids":[...],"action":"restore"}`. A bulk request has one shared action, not mixed per-item actions.
- [x] 7.3 Keep the severity query fixture in its repeatable form.
- [x] 7.4 Capture the serialized Axios request through the real adapter rather than a module-level belief.
- [x] 7.5 Restore adapter state after every test.
- [x] 7.6 Assert that serialized `bulkReject(eventIds, action)` deep-equals the canonical fixture.
- [x] 7.7 Assert the real severity params serializer against its shared fixture.
- [x] 7.8 Frontend negative case: demonstrate that any body containing `items` differs from the canonical fixture.
- [x] 7.9 Backend schema accepts the canonical fixture.
- [x] 7.10 The real backend endpoint accepts the fixture and processes missing IDs as domain failures rather than validation failures.
- [x] 7.11 Backend negative case: every legacy `items` body receives 422 because `extra=forbid` leaves no compatibility alias.
- [x] 7.12 Keep the backend severity query acceptance/selectivity test.
- [x] 7.13 Resolve both fixture paths from repository root so runner cwd does not change the contract.

## 8. Tests de componente

- [x] 8.1 `EventsTable`: la fila de un `critical` muestra el texto `critical`, y la de un `low` muestra `low`. Aserción sobre el texto, no sobre clases de Tailwind: un test que afirma `text-red-400` se rompe con un retoque de paleta y no dice nada sobre si el operador puede distinguir un `critical`.
- [x] 8.2 `EventsTable`: la fila de un `critical` y la de un `low` **no** comparten la clase de banda — par positivo/negativo, el mismo patrón que `Dashboard.test.tsx` ya usa para el realce del KPI. Es lo que hace que una banda constante falle en vez de pasar.
- [x] 8.3 `EventsTable`: una fila con contexto de proceso lo muestra (exe, pid, uid); una fila con los tres campos nulos no renderiza la sublínea ni el texto `null`.
- [x] 8.4 `Dashboard`: la tarjeta de critical/high es un enlace **a** `/events?status=pending&severity=critical&severity=high`, con los dos `severity` presentes. Asertar el destino parseado como `URLSearchParams` y no la cadena literal, para que el orden de los parámetros no vuelva frágil al test — pero afirmar explícitamente que `getAll('severity')` tiene longitud 2.
- [x] 8.5 `Dashboard`: ninguna etiqueta de estado de evento difiere de su valor canónico. Recorrer los siete estados en lugar de escribir siete aserciones sueltas, para que un estado nuevo entre solo en la cobertura.
- [x] 8.6 `Events`: activar un checkbox de severidad deja el parámetro en la URL y dispara una petición con esa severidad; desactivar el último lo saca de las dos.
- [x] 8.7 `BulkActionBar`: seleccionar tres eventos, elegir `quarantine` y confirmar produce `{event_ids:[id1,id2,id3], action:"quarantine"}`, sin `items`, versiones ni acciones por ítem. El test falla si reaparece el wire legacy.
- [x] 8.8 Correr la suite entera y confirmar que los 78 tests actuales siguen en verde. La migración de la tarea 2 toca tres pantallas y `Dashboard.test.tsx` tiene 9 tests que asertan etiquetas: la tarea 5.5 los va a romper y **hay que actualizarlos, no relajarlos**.

## 9. Documentación y trazabilidad

- [x] 9.1 Agregar la fila 45 a la tabla resumen de `CHANGES.md` (después de la 44, `:68`) y su sección detallada al final del bloque de changes (después de `:878-...`), con el formato de la 44: capa, dependencias, origen, decisiones, capacidades, reglas, "Done" y notas.
- [x] 9.2 Actualizar `docs/trazabilidad_us_tests.md` en los seis puntos que este change mueve: la fila maestra de US-06 (`:113`), el criterio de contenido de fila en §5.6 (`:298`), la fila de US-06 en §6 (`:742`), los contadores del resumen (`:76-78`), la fila maestra de US-25 (`:132`) y el ítem de nivel 1 de §7 (`:799-802`), que este change cierra parcialmente.
- [x] 9.3 Al actualizar US-06, aplicar la regla del propio documento (`:49-53`): el criterio se cierra solo si la fila lleva **path, estado, acción, severidad, fecha y proceso causante**. Si la implementación quedó más angosta que eso, la fila se anota como parcial y la diferencia va a §6 — no se declara cerrada porque el test de lo implementado pase.
- [x] 9.4 Registrar que US-25 ya coincide con el contrato canónico: una acción top-level aplicada a todos los `event_ids`; la divergencia histórica por acción por ítem queda supersedida.
- [x] 9.5 **No** tocar los appendices de decisiones. Este change no abre ninguna suposición: la severidad en la fila la pide US-06:151, el filtro lo habilita D34/RN-128 explícitamente, el proceso causante lo pide US-06:151 y ya viaja en el payload, y el léxico del dashboard es aplicación literal de C1/RN-71. Si durante la implementación aparece una suposición que no esté cerrada, **detener el flujo** y cerrarla en el appendix antes de seguir.
- [x] 9.6 Registrar como observación —sin arreglarlo acá— que el appendix de `docs/arquitectura_stack.md` quedó rezagado: su párrafo introductorio (`:1928`) y su tabla de cierre (hasta `:2469`) se detienen en D34 mientras `reglas_de_negocio.md` va por D39/RN-133.

## 10. Verificación final

- [x] 10.1 `pnpm --dir frontend typecheck` y `pnpm --dir frontend test --run` en verde.
- [x] 10.2 La suite de backend en verde, incluidos los tests nuevos de 7.9–7.12.
- [x] 10.3 Contra el sistema vivo, en este orden: `/events?status=pending` muestra severidad y proceso causante en cada fila.
  - Verificado en el VPS el 2026-09-16: cada fila muestra la columna Severidad con valor (`high`) y la sublínea de contexto de proceso bajo el path. Salvedad del laboratorio, no de la UI: en esa corrida el proceso se renderizó como `? (pid 0)` porque el archivo se escribe **desde el host** y el agente corre **dentro de un contenedor**, así que no puede resolver el proceso que lo tocó. Con el agente en systemd y el proceso en el mismo namespace sí se puebla — el evento #13 de la misma jornada mostró PID 3378243.
- [x] 10.4 (verificado en el VPS el 2026-09-16: la tarjeta informaba 1, el enlace llevó a `/events?status=pending&severity=critical&severity=high` con `pending` y `critical`+`high` tildados, y la lista informó "Mostrando 1–1 de 1 eventos". KPI y deep-link hacen la misma consulta) La tarjeta "Pending critical + high" navega a la lista prefiltrada, y **el total que informa la lista coincide con el número de la tarjeta**. Si difieren, el enlace está mal construido: es la comprobación más barata de que el KPI y el deep-link hacen la misma consulta.
- [x] 10.5 Un rechazo en lote de dos eventos `pending` devuelve 200 y el toast de éxito.
  - Verificado en el VPS el 2026-09-16 con los eventos 305 y 309 (`/watch/base.txt` y `/watch/base2.txt`), rechazados en lote con restauración: ambos quedaron `rejected` y el outbox registró sus dos `restore_file` como `published` con `ack_status = failed`. El fallo de ejecución es el esperado — la carpeta está montada de solo lectura (`read_only_mount`) — y es justamente la separación correcta: la operación en lote responde 200, el comando se entrega, y el resultado real de la acción se reporta aparte en `ack_status` sin falsear el éxito.
- [x] 10.6 (verificado en el VPS el 2026-09-16: las 6 tarjetas de estado del Dashboard rotulan el valor canónico en minúscula snake_case —`Dashboard.tsx:153` usa el propio valor como `label`—, idéntico a los badges de la tabla de eventos. Queda anotado como candidato a change de frontend, NO implementado acá: agregar descripción o tooltip explicativo bajo cada token para lectores no técnicos, conservando el token canónico como título; renombrarlos exigiría una decisión que modifique RN-71) Ninguna etiqueta de estado del dashboard difiere de la que muestra la tabla de eventos para el mismo estado.
- [x] 10.7 Confirmar que los cambios de producción backend quedan limitados al contrato bulk canónico (`schemas.py`, `router.py`, `service.py`) y que el legacy `items` recibe 422.
