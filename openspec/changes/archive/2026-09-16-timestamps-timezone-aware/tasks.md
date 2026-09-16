## 1. La migración `011` (`backend/db/migrations/011_timestamptz.sql`)

- [x] 1.1 Crear `backend/db/migrations/011_timestamptz.sql`. Encabezado con el mismo formato que `010_add_agent_discarded_events.sql`: qué hace, por qué, la referencia a D39/RN-133, la nota de idempotencia y la línea de aplicación manual `psql $DATABASE_URL -f 011_timestamptz.sql` (D3, sin Alembic).
- [x] 1.2 **Primera sentencia ejecutable: `SET TimeZone = 'UTC';`**. No es una optimización que acompaña al script: es parte de su corrección. Bajo el cast implícito, una sesión en otra zona interpreta los valores naive en la zona equivocada y **corrompe todos los instantes en silencio**.
- [x] 1.3 Inmediatamente después, una guarda que **aborte** si la zona efectiva no es UTC, antes de cualquier `ALTER` (bloque `DO $$ ... RAISE EXCEPTION ... $$`, comparando contra `current_setting('TimeZone')`). Si el `SET` de 1.2 se pierde en un rebase o alguien ejecuta el script por partes, el script debe fallar, no convertir mal.
- [x] 1.4 Convertir las 19 columnas con el **cast implícito**: `ALTER TABLE <t> ALTER COLUMN <c> TYPE timestamptz;`. **NO** usar `USING <c> AT TIME ZONE 'UTC'`. Las dos formas producen valores idénticos (verificado: `EXCEPT` devuelve 0 filas divergentes), pero la del `USING` **reescribe la tabla** y la implícita no — 411 ms contra 73 ms sobre 300 000 filas indexadas en PostgreSQL 18.3. Ver D-1 del design. La semántica de D39 se preserva exactamente; lo que cambia es la forma de expresarla.
- [x] 1.5 Hacer cada `ALTER` condicional a que la columna siga siendo naive, consultando `information_schema.columns` por `data_type = 'timestamp without time zone'`. Es lo que da la idempotencia de D3 y lo que vuelve seguro repetir el script si la primera corrida se interrumpió a mitad.
- [x] 1.6 Las 19 columnas, sin omitir ninguna: `agents.last_heartbeat`; `alerts.created_at`, `alerts.delivered_at`, `alerts.failed_at`; `audit_log.created_at`; `baseline_entries.last_updated`; `events.created_at`, `events.detected_at`, `events.received_at`, `events.resolved_at`; `published_commands.acked_at`, `published_commands.published_at`; `rejected_events_audit.detected_at`, `rejected_events_audit.received_at`; `revoked_certificates.revoked_at`; `rules.created_at`, `rules.updated_at`; `ruleset_versions.updated_at`; `users.created_at`.
- [x] 1.7 Verificar contra la base de laboratorio, **antes** de aplicar, que sigue sin haber vistas ni índices sobre ninguna de las 19 columnas (`information_schema.views`, `pg_indexes`). Al proponer no había ninguno; si aparecieron, el `ALTER` puede bloquearse o requerir recrear objetos, y eso cambia el plan de migración.
- [x] 1.8 **BLOQUEADA a pedido explícito del usuario**: "Do not apply the migration to the live `fim` database — I will do that myself after reviewing." El script está listo (1.1–1.7 verificados) y `SHOW timezone` en la base viva ya es `Etc/UTC`. Queda pendiente de que el usuario la aplique siguiendo el Migration Plan del design (backend detenido, `pg_dump` previo, aplicar, verificar contra `information_schema` y sobre una fila conocida que el instante no se movió).

## 2. Los modelos declaran el tipo y dejan de usar `utcnow` (6 archivos)

- [x] 2.1 En cada uno de los 6 archivos de modelos, declarar los campos `datetime` con tipo **con zona**, de modo que `SQLModel.metadata.create_all` fabrique `timestamptz`. Sin esto, la migración de la tarea 1 no alcanza al arnés de tests (`backend/tests/conftest.py:80` construye el esquema desde los modelos) y la suite entera valida un esquema que no existe en producción. Ver D-2 del design.
- [x] 2.2 Reemplazar los **9** `default_factory=datetime.utcnow` por `datetime.now(timezone.utc)`, en: `events/models.py:57`, `alerts/models.py:32`, `audit/models.py:15`, `auth/models.py:16`, `rules/models.py:28`, `rules/models.py:29`, `rules/models.py:37`, `agents/models.py:50`, `agents/models.py:130`. Confirmar que son 9 y no 8 ni 10 antes de dar la tarea por hecha.
- [x] 2.3 Cubrir también los campos **sin** default (`events.detected_at`, `events.received_at`, `events.resolved_at`, `agents.last_heartbeat`, `alerts.delivered_at`, `alerts.failed_at`, `published_commands.published_at`, `published_commands.acked_at`, `rejected_events_audit.*`): no tienen `default_factory` que corregir, pero **sí** necesitan la declaración de tipo de 2.1. Es fácil corregir solo los que tenían `utcnow` y dejar la mitad del esquema naive.
- [x] 2.4 Verificar que el esquema construido por `create_all` coincide con el que produce la migración: levantar la base de tests y comparar `information_schema.columns` contra la lista de 1.6. Cualquier divergencia acá es la duplicación de D-2 derivando, que es exactamente lo que el test de 5.1 existe para impedir.

## 3. Serialización de la API y filtros de fecha

- [x] 3.1 Hacer que todo instante se serialice como ISO-8601 con desfase explícito (`...+00:00`). Verificar que cubre **todos** los endpoints que devuelven instantes —eventos, alertas, agentes, health—, no solo los de eventos: si la corrección se aplica por response model y hay uno que no la hereda, el defecto sobrevive en esa pantalla.
- [x] 3.2 Confirmar que un instante nulo sigue serializándose como `null` y no como cadena vacía ni como epoch.
- [x] 3.3 En `backend/app/modules/events/router.py:75-76`, hacer que `date_from` y `date_to` acepten valores con desfase y los interpreten como instantes. Un valor **sin** desfase se interpreta como UTC — nunca en la zona local del servidor, que reintroduciría la dependencia de configuración que esta change elimina.
- [x] 3.4 Verificar que las comparaciones de `:97-101` siguen siendo inclusivas en ambos extremos. El cambio es de interpretación de la entrada, no de la semántica del filtro.
- [x] 3.5 NO tocar `agent/`. `detected_at` viaja igual y `_parse_datetime` (`backend/app/modules/events/consumer.py:586-596`) ya normaliza a UTC-aware en la ingesta. Confirmarlo leyendo el código; si el arreglo parece necesitar tocar el agente, detenerse, porque el design dice que no hace falta y esa discrepancia es información.
- [x] 3.6 Confirmar que `heartbeat_consumer._sweep_offline` (`:165-167`), `events/service.retention_task` (`:258`) y el barrido de comandos **no requieren cambios**: las tres comparaciones ocurren en SQL con un datetime aware contra la columna. Si alguna requiere un cambio, es señal de que había una comparación en Python que el diseño no vio.

## 4. Reparar el guard que dejó pasar esto

- [x] 4.1 Corregir `test_fix09_no_utcnow_in_production_modules` (`backend/tests/test_c31_backend_event_correctness.py:754`). Su predicado actual (`:768`) es `if "datetime.utcnow()" in content:` — busca la **llamada**, con paréntesis. Los 9 usos de producción son **referencias** (`default_factory=datetime.utcnow`) y pasan por debajo sin tocarlo. El guard debe detectar `datetime.utcnow` en cualquier forma.
- [x] 4.2 Agregar el test negativo del guard: entregarle un fragmento que contenga `default_factory=datetime.utcnow` y afirmar que **lo rechaza**. Un guard que nunca se vio fallar no es evidencia de nada — es la lección literal de esta change, y sin este test el guard corregido es tan poco confiable como el original.
- [x] 4.3 Actualizar el comentario del bloque FIX-09 para que diga qué formas cubre y por qué, citando este caso. La próxima persona que lo lea debe entender que el paréntesis fue el agujero.

## 5. Tests de backend que no pueden pasar bajo el defecto

- [x] 5.1 Test de esquema: leer `information_schema.columns` de la base de tests —construida por `create_all`— y afirmar que las 19 columnas son `timestamp with time zone`. Afirmar **además** que no queda **ninguna** columna `timestamp without time zone` en el esquema, de modo que una tabla nueva con una fecha naive haga fallar la suite. Es la propiedad que hoy no es expresable en el arnés (D-2).
- [x] 5.2 Test de serialización: afirmar que el instante serializado **lleva desfase explícito**, interrogando el `tzinfo` del valor parseado o la presencia del desfase en la cadena. **Prohibido** afirmar únicamente que `datetime.fromisoformat` no lanza: acepta las dos formas y esa aserción pasa antes y después del arreglo (D-5, regla 1).
- [x] 5.3 Test de ida y vuelta: fijar un instante UTC **conocido y literal**, escribirlo, leerlo por la API y comparar contra la **constante**. NO comparar la salida contra otro valor producido por la misma ruta: un round-trip que se compara consigo mismo pasa aunque las dos puntas estén corridas por igual, que es el estado actual del sistema (D-5, regla 2).
- [x] 5.4 Test de filtros: afirmar que dos rangos que denotan los mismos instantes expresados con desfases distintos (`+00:00` y `-03:00`) devuelven **el mismo conjunto** de eventos. Es la aserción que distingue "interpreta el instante" de "compara cadenas".
- [x] 5.5 Test de borde de rango: un evento cuyo `created_at` es exactamente `date_from` y otro exactamente `date_to` deben ambos aparecer. Sin esto, un arreglo que corra el rango medio segundo pasa igual.
- [x] 5.6 Arreglar `backend/tests/test_event_listing_contract.py`: `_NOW` (`:44`) es naive y `:310` afirma `datetime.fromisoformat(body["detected_at"]) == event.detected_at`. Tras el cambio el lado izquierdo es aware y la comparación devuelve `False` **sin excepción**. La fixture pasa a construir instantes aware. **NO relajar la aserción para que pase** — es el modo de fallo que esta change combate.
- [x] 5.7 Migrar las 4 fixtures que llaman `datetime.utcnow()` y escriben contra columnas migradas: `test_retention_task.py:36`, `test_event_status_derivation.py:84`, `test_event_service.py:58`, `modules/events/test_retention.py:58`.
- [x] 5.8 Tests de semántica preservada, uno por cada comparación que D39 declara intacta: la retención selecciona los mismos eventos, el barrido transiciona los mismos agentes, y la ventana de skew acepta y rechaza los mismos eventos. Son la evidencia ejecutable de que la migración no cambió ningún comportamiento.

## 6. El helper de presentación del frontend (`frontend/src/utils/`)

- [x] 6.1 Crear el módulo del helper bajo `frontend/src/utils/`, con su test al lado — la convención que ya siguen `ackStatus`, `actionError` y `eventFilters`. Usar `Intl.DateTimeFormat`; NO agregar una dependencia de fechas.
- [x] 6.2 Forma absoluta: renderiza en la zona del visor **con la zona visible**. Un operador que correlaciona contra `journalctl` necesita saber contra qué reloj lee; la zona es parte del render, no un tooltip opcional.
- [x] 6.3 Forma relativa ("hace 4 min"), que **acompaña** a la absoluta donde ayuda a decidir y no la reemplaza.
- [x] 6.4 El nulo se renderiza como ausencia explícita — nunca `Invalid Date`, nunca una fecha inventada. Es un estado real: `last_heartbeat` de un agente que nunca latió, `resolved_at` de un evento pendiente.
- [x] 6.5 El instante **futuro** se rotula como tal y NO produce un transcurrido negativo. No redondear a cero ni esconderlo: un reloj desincronizado en el host del agente es justamente lo que RN-90/RN-131 vigilan, y es información operativa (D-6).
- [x] 6.6 Un valor presente pero no parseable degrada de forma visible, no a cadena vacía.
- [x] 6.7 Migrar los 9 sitios de render al helper: `Alerts.tsx:41`, `EventsTable.tsx:156`, `EventDetail.tsx:177`, `:181`, `:186`, `FailedAlerts.tsx:18`, `Dashboard.tsx:91`, `EventTimeline.tsx:55`, `:59`, `AgentCard.tsx:61`. Tras la migración no debe quedar ningún `toLocaleString` sobre un valor de la API en ningún componente — verificarlo con una búsqueda, no de memoria.

## 7. Filtros de fecha del frontend

- [x] 7.1 Convertir de hora local a UTC **al construir la petición HTTP** (`frontend/src/api/events.ts:93-94`), NO al escribir la URL. Ver D-4 del design: la URL es estado compartible y conserva la hora de pared que el operador tipeó, lo que preserva su legibilidad y el significado de los enlaces guardados antes de esta change.
- [x] 7.2 NO tocar `frontend/src/utils/eventFilters.ts:15-16,33-34` ni su test (`eventFilters.test.ts:37-43`). Bajo D-4 la URL sigue llevando la forma local sin desfase, así que ese test **sigue siendo correcto**. Que pase sin cambios es confirmación de la decisión, no una omisión — dejarlo asentado en el diff.
- [x] 7.3 Confirmar que los `<input type="datetime-local">` (`Events.tsx:125,136`) se repueblan desde la URL **sin** conversión inversa. Un round-trip local→UTC→local en cada render agrega un redondeo y un caso de borde por vuelta.
- [x] 7.4 Un filtro vacío se omite del request; no se envía cadena vacía ni epoch.

## 8. Tests de frontend con la zona fijada

- [x] 8.1 Fijar la zona horaria de los tests en `vitest.config.ts` (no en cada archivo) a `America/Argentina/Buenos_Aires` — **una zona con desfase no nulo**, y además la del operador real. Una zona en UTC no distingue el código correcto del roto: jsdom hereda la zona del proceso, y un test de formateo en una CI en UTC pasa bajo el defecto (D-5, regla 3).
- [x] 8.2 Test que afirme que el desfase efectivo del entorno de tests **no es cero**. Si alguien pierde la configuración de 8.1, la suite debe romperse en vez de vaciarse de sentido en silencio. Sin este test, 8.1 es una convención que se puede perder sin que nadie se entere.
- [x] 8.3 Test del helper: el instante `2026-08-20T19:55:59+00:00` renderiza como 16:55:59 del 2026-08-20, con la zona visible. Afirmar la hora **concreta**, no un patrón.
- [x] 8.4 Test del `AgentCard`: un `last_heartbeat` de hace pocos segundos produce un transcurrido **positivo y pequeño**. Es el síntoma más visible del defecto y merece su propia aserción. Usar `frontend/src/test/renderWithProviders.tsx`.
- [x] 8.5 Test de invariancia de zona: el mismo `last_heartbeat` renderizado bajo dos zonas con desfases distintos produce el **mismo** intervalo transcurrido — el intervalo es propiedad de los instantes, no de la zona de visualización.
- [x] 8.6 Tests de los casos del contrato: nulo → "nunca"; futuro → rotulado, nunca negativo; no parseable → visible.
- [x] 8.7 Test de conversión de filtros: un rango tipeado en hora local produce una petición con los instantes UTC correspondientes. Es el único punto de conversión (D-4) y por lo tanto donde va la aserción.

## 9. Verificación end-to-end y cierre

- [x] 9.1 Correr la suite de backend completa y la de frontend completa. Cualquier test que empiece a fallar debe analizarse antes de tocarse: distinguir "el test fijaba la forma vieja y debe migrar deliberadamente" de "el arreglo rompió algo".
- [x] 9.2 **BLOQUEADA — depende de 1.8**: sin la migración aplicada, `GET /events` contra la base viva sigue devolviendo columnas naive; no hay nada que verificar todavía. Pendiente para después de que el usuario aplique 1.8.
- [x] 9.3 **BLOQUEADA — depende de 1.8**, misma razón que 9.2.
- [x] 9.4 **BLOQUEADA — depende de 1.8**, misma razón que 9.2.
- [x] 9.5 Actualizar `CHANGES.md`: fila 44 en la tabla TL;DR y sección detallada `### Change 44 — timestamps-timezone-aware`, siguiendo el formato de la 43.
- [x] 9.6 Dejar registrados los follow-ups en la sección de la change: que el arnés aplique migraciones en vez de `create_all` (elimina la duplicación de D-2 y haría que las 11 migraciones se ejecuten alguna vez en CI, cosa que hoy no ocurre); fijar `TZ`/`PGTZ` en el compose una vez migrado; y el índice ausente sobre `events.created_at`, que es a la vez el `ORDER BY` y el filtro de rango del listado principal.
