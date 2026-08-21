## Why

**Toda fecha de la consola está corrida tres horas.** No es un detalle de presentación: en Argentina (UTC−3) cada evento se muestra tres horas más tarde de lo ocurrido, y la tarjeta del agente llega a informar tiempos transcurridos **negativos**. Para una consola forense, donde la correlación temporal es el instrumento principal, la pantalla no es imprecisa: es inutilizable.

Verificado contra la API viva: `GET /events` devuelve `'2026-08-20T19:55:59.641248'` — **sin `Z` y sin desfase**. La especificación de ECMAScript obliga a interpretar una fecha-hora sin designador de zona como **hora local**, de modo que `new Date(iso)` en el navegador desplaza cada instante por el desfase del operador. El síntoma más visible es `frontend/src/components/ui/AgentCard.tsx:59-66`, que calcula `Date.now() - d.getTime()` sobre `last_heartbeat`: un agente sano que acaba de latir produce una resta negativa.

**Esto no abre una suposición: la cierra D39 / RN-133** (`docs/reglas_de_negocio.md:1245`), que describe los tres defectos encadenados y fija el estado final exigido. Esta change implementa esa decisión; no introduce política.

### El alcance, verificado contra el sistema vivo

Las tres capas del defecto se confirmaron una por una, no se dedujeron:

1. **19 columnas son `timestamp without time zone`** — consultado en `information_schema` del contenedor `db`, coincide exactamente con el inventario de D39: `agents.last_heartbeat`, `alerts.{created_at,delivered_at,failed_at}`, `audit_log.created_at`, `baseline_entries.last_updated`, `events.{created_at,detected_at,received_at,resolved_at}`, `published_commands.{acked_at,published_at}`, `rejected_events_audit.{detected_at,received_at}`, `revoked_certificates.revoked_at`, `rules.{created_at,updated_at}`, `ruleset_versions.updated_at`, `users.created_at`. El instante que guardan es UTC por convención, no por tipo.

2. **`SHOW timezone` en la base viva devuelve `Etc/UTC`, y no hay una sola aparición de `TZ` ni `PGTZ` en `docker-compose.yml`.** La dependencia es aún más débil de lo que D39 le atribuye: no es una configuración implícita, es el **default de la imagen** de PostgreSQL, que nadie eligió. Debajo de esa suerte está la ventana anti-replay de RN-90/RN-131, que es un control de seguridad.

3. **La mezcla naive/aware está donde el conteo de D39 dice, pero no con la forma que sugiere** — y la diferencia es exactamente lo que dejó pasar el defecto. Ver abajo.

### El hallazgo que explica por qué sobrevivió: el test que existe para esto pasa en verde

Ya hay un test dedicado a erradicar `utcnow` del backend. `backend/tests/test_c31_backend_event_correctness.py:754` — `test_fix09_no_utcnow_in_production_modules`, "FIX-09 — `datetime.utcnow()` erradicado de módulos de producción" — recorre todos los `.py` bajo `backend/app/` y falla si encuentra el defecto. **Pasa.** Su predicado es (`:768`):

```python
if "datetime.utcnow()" in content:
```

Busca la cadena literal **con paréntesis**, es decir, la *llamada*. Los 9 usos de producción no son llamadas: son **referencias** pasadas como fábrica, `default_factory=datetime.utcnow`, y ninguna lleva paréntesis. Pasan por debajo del grep sin tocarlo:

| Archivo | Línea | Campo |
|---|---|---|
| `backend/app/modules/events/models.py` | 57 | `created_at` |
| `backend/app/modules/alerts/models.py` | 32 | `created_at` |
| `backend/app/modules/audit/models.py` | 15 | `created_at` |
| `backend/app/modules/auth/models.py` | 16 | `created_at` |
| `backend/app/modules/rules/models.py` | 28, 29 | `created_at`, `updated_at` |
| `backend/app/modules/rules/models.py` | 37 | `updated_at` (`RulesetVersion`) |
| `backend/app/modules/agents/models.py` | 50 | `revoked_at` |
| `backend/app/modules/agents/models.py` | 130 | `last_updated` (`BaselineEntry`) |

Son 9, el número exacto que D39 declara. Enfrente hay 25 `datetime.now(timezone.utc)` en producción (más 3 en `backend/app/core/pki.py` escritos como `datetime.datetime.now(datetime.timezone.utc)`, que ni siquiera entran en ese conteo). El sistema tiene, literalmente, un test que afirma que este defecto no existe, un nombre de test que lo describe, y el defecto en producción — separados por dos caracteres.

**El resto de las 4 llamadas reales a `datetime.utcnow()` están en fixtures de tests** (`test_retention_task.py:36`, `test_event_status_derivation.py:84`, `test_event_service.py:58`, `modules/events/test_retention.py:58`), es decir: escriben datetimes naive contra las mismas columnas. Migrar la columna sin tocarlas cambia lo que esos tests significan.

### Por qué una suite que corre en verde no vio un error de tres horas visible en cada pantalla

Cinco razones independientes, y ninguna sola alcanza:

1. **El test que existe para esto busca la cadena equivocada** — lo anterior. Es el caso más incómodo: no es una laguna de cobertura, es cobertura que afirma lo contrario de la verdad.
2. **La única aserción de contrato sobre timestamps parsea en vez de comparar.** `backend/tests/test_event_listing_contract.py:310-312` afirma `datetime.fromisoformat(body["detected_at"]) == event.detected_at` y `detected_at < received_at`. `fromisoformat` acepta **las dos** formas, con desfase y sin él, y el orden entre dos instantes se conserva bajo cualquiera. Esa aserción pasa antes y después del arreglo: es exactamente la clase "la cadena parece una fecha ISO" que deja sobrevivir al defecto que dice cubrir.
3. **El esquema de tests se construye desde los modelos, no desde las migraciones.** `backend/tests/conftest.py:80` hace `SQLModel.metadata.create_all(engine)` contra una base efímera. Ningún test observa jamás el tipo de columna que corre en producción; la propiedad "la columna es `timestamptz`" **no es expresable** en el arnés actual. Esto tiene una consecuencia directa de diseño, no solo de test: una migración solo-SQL dejaría la suite entera validando un esquema que no existe en producción.
4. **Ningún test renderiza una fecha.** La suite de frontend son 12 archivos sobre utils y tres componentes; ni uno afirma un timestamp formateado.
5. **Todo el lado servidor coincide en UTC, así que nada discrepa.** Backend, sesión de PostgreSQL y reloj del contenedor son UTC. El desplazamiento solo se materializa en el navegador del operador, que es el único participante que ninguna prueba automatizada ejecuta. Y jsdom hereda la zona del host: un test de render en una CI en UTC habría pasado igual, fallando solo en la máquina del desarrollador — el reverso exacto del síntoma de producción. Cualquier test de fecha que se agregue tiene que **fijar la zona explícitamente** o reproduce este punto ciego.

## What Changes

- **Las 19 columnas migran a `timestamptz`** con la migración `011`, idempotente y aplicada a mano (D3, sin Alembic). El contenido almacenado ya es UTC, así que la conversión es de tipo, no de valor.
- **La migración se ejecuta bajo `SET TimeZone = 'UTC'` y con el cast implícito, no con `USING ... AT TIME ZONE 'UTC'`.** Las dos formas producen valores idénticos, pero solo la primera evita reescribir las tablas. Verificado empíricamente contra PostgreSQL 18.3 sobre 300 000 filas indexadas — ver D-1 del [design](design.md), con números. La letra de D39 nombra la variante con `USING`; su **semántica** es lo normativo y se preserva exactamente. Esto no enmienda la decisión: elige la implementación equivalente que no tiene el costo.
- **Los 9 `default_factory=datetime.utcnow` pasan a `datetime.now(timezone.utc)`.** `utcnow()` devuelve un naive que *aparenta* ser UTC, es la fuente de la mezcla, y está desaconsejado desde Python 3.12.
- **Los modelos declaran el tipo con zona**, no solo la migración. Sin esto, `create_all` seguiría fabricando columnas naive y la suite entera correría contra un esquema distinto del de producción (razón 3 de arriba).
- **La API emite ISO-8601 con desfase explícito** (`...+00:00`). Ningún cliente vuelve a adivinar la zona de un instante.
- **Los filtros de fecha del frontend se convierten a UTC antes de enviarse.** Hoy `Events.tsx:125,136` manda el string local crudo de un `<input type="datetime-local">` y el backend lo compara contra columnas UTC (`backend/app/modules/events/router.py:75-76`, `:97-101`): **el rango filtrado no es el rango pedido**, y en Argentina está corrido tres horas como todo lo demás.
- **La interfaz muestra siempre la zona junto a la hora absoluta**, con la forma relativa donde ayuda a decidir. Son 9 sitios de render (`Alerts.tsx:41`, `EventsTable.tsx:156`, `EventDetail.tsx:177,181,186`, `FailedAlerts.tsx:18`, `Dashboard.tsx:91`, `EventTimeline.tsx:55,59`, `AgentCard.tsx:61`), hoy resueltos con nueve llamadas sueltas a `toLocaleString('es-AR')`. Pasan a un único helper con contrato propio.
- **Tests que hacen imposible que el defecto sobreviva**, escritos contra la clase de fallo que lo dejó pasar:
  - Un test que afirma que la forma serializada **lleva desfase explícito** — verificando la propiedad, no que la cadena parsee.
  - Un test de ida y vuelta por la API que afirma que **el instante se preserva**, comparando `datetime` aware contra `datetime` aware.
  - Un test de frontend que renderiza un instante UTC **conocido** con la zona **fijada explícitamente** y afirma la hora local esperada, incluida la etiqueta de zona.
  - Un test de esquema que lee `information_schema` y afirma que las 19 columnas son `timestamptz` — la propiedad que hoy no es expresable.
  - La reparación del guard FIX-09 para que detecte también la forma sin paréntesis, con un test que afirme que el guard **falla** ante `default_factory=datetime.utcnow`. Un guard que no se prueba contra su propio caso negativo es lo que produjo esta situación.

**Fuera de scope** (no traerlos acá):

- **Configurar `TZ`/`PGTZ` explícitamente en el compose.** Después de la migración deja de importar para la corrección: `timestamptz` almacena el instante independientemente de la sesión. Fijarla seguiría siendo higiene, pero hacerlo *ahora* enmascararía si la migración quedó incompleta en algún punto — precisamente la señal que conviene conservar visible.
- **El índice ausente sobre `events.created_at`.** No hay un solo índice sobre ninguna de las 19 columnas (verificado en `pg_indexes`), y `created_at` es a la vez el `ORDER BY` y el filtro de rango del listado principal (`router.py:97-107`). Es un problema de rendimiento real, independiente de este defecto, y merece su propia change con su propia medición.
- **Migrar las fixtures de tests que usan `datetime.utcnow()`** más allá de lo necesario para que la suite siga siendo verdadera. Se corrigen las 4 que escriben contra columnas migradas; barrer el resto es limpieza sin propiedad asociada.
- **Cambiar el formato de `detected_at` en el payload del agente.** Viaja como cadena ISO y `_parse_datetime` (`backend/app/modules/events/consumer.py:586-596`) ya normaliza a UTC-aware en la ingesta. D39 lo excluye explícitamente y la verificación lo confirma.

## Capabilities

### New Capabilities

- `frontend-time-display`: contrato único de presentación de instantes en la interfaz — parseo del ISO con desfase, render en la zona del operador con la zona **visible**, forma relativa para lo reciente, y tratamiento explícito del nulo y del instante futuro. Hoy esta responsabilidad está replicada en nueve sitios sin contrato; que sea una capacidad propia es lo que permite afirmarla con un test en vez de revisarla a ojo.

### Modified Capabilities

- `domain-models`: las columnas de fecha pasan a ser `timestamptz` y los defaults de los modelos pasan a producir datetimes aware. Cambia el contrato de persistencia, no solo su implementación: el tipo de la columna deja de delegar el significado del instante en la configuración de la sesión.
- `backend-events-api`: la serialización de todo instante pasa a llevar desfase explícito, y los filtros `date_from`/`date_to` pasan a aceptar entrada con desfase e interpretarla como instante y no como hora de pared.
- `frontend-events`: los filtros de fecha convierten de hora local a UTC antes de consultar, y el detalle, la tabla y el timeline muestran la zona junto a la hora.
- `frontend-agents`: el tiempo transcurrido desde el último latido deja de poder ser negativo y la tarjeta expone también el instante absoluto con su zona.

## Impact

**Base de datos** — 19 columnas en 11 tablas. Estado vivo del laboratorio al proponer: 7664 eventos, 7288 alertas, y `rejected_events_audit` como tabla mayor con 23 MB. **No hay vistas ni índices que dependan de ninguna de las 19 columnas** (verificado en `information_schema.views` y `pg_indexes`), de modo que la migración no tiene objetos dependientes que la bloqueen o que haya que recrear.

**Backend** — 6 archivos de modelos (`events`, `alerts`, `audit`, `auth`, `rules`, `agents`), la serialización de respuesta, el parseo de los filtros de fecha en `backend/app/modules/events/router.py`, y una migración nueva `backend/db/migrations/011_*.sql`.

**Semántica preservada, sin excepción** — la ventana de skew de RN-90/RN-131, la retención de RN-98 (`backend/app/modules/events/service.py:258`) y el barrido de comandos y agentes (`backend/app/modules/agents/heartbeat_consumer.py:165-167`) siguen operando sobre los mismos instantes. Las tres comparaciones ocurren **en SQL**, con un datetime aware de Python contra la columna: hoy PostgreSQL lo coacciona usando la zona de la sesión y acierta porque esa zona es UTC; después lo compara como instante. Mismo resultado, ya no contingente.

**Agente** — sin cambios. `detected_at` viaja igual y `_parse_datetime` ya lo normaliza a UTC-aware.

**Frontend** — 9 sitios de render, los dos `<input type="datetime-local">` de `Events.tsx`, el cliente de API (`frontend/src/api/events.ts:93-94`) y el round-trip de filtros por URL (`frontend/src/utils/eventFilters.ts:15-16,33-34`), cuyo test actual (`eventFilters.test.ts:37-43`) fija la forma naive de la cadena y debe revisarse junto con la decisión sobre dónde ocurre la conversión (D-4 del design).

**Reglas cubiertas**: RN-71 (léxico canónico, sin cambios), RN-90 y RN-131 (ventana anti-replay, semántica intacta), RN-98 (retención, semántica intacta), RN-133 (nueva, implementada acá). **Decisiones aplicadas**: D39/RN-133 (implementada), D3 (migración idempotente sin Alembic), D37/RN-131 y D35/RN-129 (sin alterar). **Ninguna decisión nueva de appendix**: D39 fija el estado final y esta change lo construye.

**Historias afectadas**: US-08 y US-21, cuyos criterios dependen de la correlación temporal que hoy la consola no entrega.
