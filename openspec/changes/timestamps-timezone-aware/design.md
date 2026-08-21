## Context

Un instante atraviesa cuatro representaciones en este sistema, y hoy tres de las cuatro fronteras pierden información:

| Frontera | Hoy | Después |
|---|---|---|
| Agente → backend (payload Valkey) | ISO con desfase; `_parse_datetime` normaliza a UTC-aware (`events/consumer.py:586-596`) | **sin cambios** |
| Backend → PostgreSQL | datetime aware → columna `timestamp` naive; PostgreSQL coacciona usando la zona de la **sesión** | datetime aware → `timestamptz`; el instante es el instante |
| PostgreSQL → API (JSON) | `'2026-08-20T19:55:59.641248'`, sin designador de zona | `'2026-08-20T19:55:59.641248+00:00'` |
| API → navegador | `new Date(iso)` interpreta como **hora local** (ECMAScript) y desplaza | parseo inequívoco; render deliberado en la zona del operador |

La tercera frontera es la que produce el síntoma; la segunda es la que lo vuelve estructural. Y la segunda hoy acierta por una razón que nadie escribió: `SHOW timezone` en la base viva devuelve `Etc/UTC`, que es el **default de la imagen** de PostgreSQL — no hay `TZ` ni `PGTZ` en `docker-compose.yml`. Todo el sistema es correcto por coincidencia con un default.

Tres hechos del código y del esquema acotan el diseño, y conviene tenerlos a la vista antes de decidir nada:

1. **Las comparaciones temporales no ocurren en Python; ocurren en SQL.** El barrido de agentes (`agents/heartbeat_consumer.py:165-167`) y la retención (`events/service.py:258`) construyen un `datetime.now(timezone.utc)` aware y se lo entregan a PostgreSQL para comparar contra la columna. **Nunca** se restan dos datetimes de origen distinto en Python. Por eso la mezcla naive/aware no explota hoy con un `TypeError`, y por eso migrar la columna no altera ninguna semántica: cambia quién decide el significado, no cuál es.
2. **No hay objetos dependientes.** Ni una vista (`information_schema.views` está vacío) ni un solo índice sobre ninguna de las 19 columnas (verificado en `pg_indexes`). Un `ALTER COLUMN TYPE` no tiene nada que recrear ni nada que lo bloquee.
3. **El esquema de tests se construye desde los modelos.** `backend/tests/conftest.py:80` hace `SQLModel.metadata.create_all(engine)` contra una base efímera. La migración SQL **no alcanza** al arnés de tests: si los modelos no declaran el tipo con zona, la suite entera valida un esquema que no existe en producción. Esta restricción determina D-2.

## Goals / Non-Goals

**Goals:**

- Que el tipo de la columna, y no la configuración de la sesión, sea lo que declara el significado de un instante persistido.
- Que la representación serializada de un instante sea inequívoca en la frontera de la API, sin que ningún cliente tenga que conocer una convención.
- Que la consola muestre el instante correcto, con su zona visible, y que el tiempo transcurrido no pueda ser negativo.
- Que el rango que el operador pide en los filtros de fecha sea el rango que se consulta.
- Que la propiedad "esto no volvió a romperse" sea afirmable por tests que **no puedan pasar bajo el defecto** — lo que descarta toda aserción que solo verifique que la cadena parsea.
- Que el arnés de tests corra contra el mismo tipo de columna que produccion.

**Non-Goals:**

- No se cambia el formato ni el contenido del payload del agente. `agent/` no se toca.
- No se altera la semántica de ninguna comparación: skew (RN-90/RN-131), retención (RN-98) y barridos siguen operando sobre los mismos instantes.
- No se introduce una biblioteca de fechas en el frontend. `Intl.DateTimeFormat` cubre el requisito y ya está en el runtime.
- No se fija `TZ`/`PGTZ` en el compose (ver "Fuera de scope" del proposal).
- No se agrega el índice ausente sobre `events.created_at`.
- No se permite que el operador elija una zona de visualización distinta de la de su navegador. D39 pide mostrar la zona, no configurarla.

## Decisions

### D-1 — La migración usa el cast implícito bajo `SET TimeZone='UTC'`, no `USING ... AT TIME ZONE 'UTC'`

D39 nombra la forma `ALTER COLUMN ... TYPE timestamptz USING columna AT TIME ZONE 'UTC'` y la justifica bien: el contenido ya es UTC, así que esa es la semántica correcta. **La semántica es normativa y se preserva exactamente.** Lo que cambia es la forma de expresarla, porque las dos variantes no cuestan lo mismo.

Desde PostgreSQL 12, un `ALTER COLUMN TYPE` de `timestamp` a `timestamptz` es **binariamente coercible y evita la reescritura de la tabla** cuando la zona de la sesión es UTC. Esa optimización inspecciona la expresión de transformación: un `USING ts AT TIME ZONE 'UTC'` es una llamada a función, no una recoerción, y **fuerza la reescritura completa**.

No se dio por sabido. Se midió contra PostgreSQL 18.3 —la versión que corre en el contenedor `db`— sobre dos tablas idénticas de 300 000 filas, cada una con un índice btree sobre la columna, usando `pg_relation_filenode()` como señal definitiva de reescritura:

| Variante | filenode antes → después | Tiempo | ¿Reescribe? |
|---|---|---|---|
| `ALTER ... TYPE timestamptz` (sesión en UTC) | `751592` → `751592` | **73 ms** | **no** |
| `ALTER ... TYPE timestamptz USING ts AT TIME ZONE 'UTC'` | `751596` → `751606` | **411 ms** | **sí** |

Y son semánticamente indistinguibles: un `EXCEPT` entre las dos tablas resultantes devuelve **0 filas divergentes**, y el valor migrado es `2026-08-20 19:55:59.641248+00` — el naive interpretado como UTC, que es exactamente lo que D39 pide.

La variante sin reescritura es entonces estrictamente mejor: mismo resultado, ~5,6× más rápida, sin duplicar el espacio en disco durante la operación y sin reconstruir índices. En este laboratorio la diferencia es de milisegundos y da igual; el motivo para elegirla es que **la propiedad se sostiene a escala**, y una tesis que documenta una migración debería documentar la que no se degrada con el tamaño de la tabla.

El precio es una precondición explícita: **la migración depende de que la sesión esté en UTC**, y si no lo está, el cast implícito interpreta los valores naive en la zona equivocada y **corrompe los datos en silencio**. Por eso el `SET TimeZone = 'UTC'` no es una optimización que acompaña al script: es parte de su corrección, va en la primera línea, y el script verifica la precondición antes de tocar nada (ver D-3).

**Alternativa descartada — `USING` tal cual, aceptando la reescritura.** Es la lectura literal de D39 y es correcta. Se descarta por el costo, y sobre todo porque tiene una propiedad peor de lo que aparenta: `AT TIME ZONE 'UTC'` es explícito respecto de la zona de *origen*, lo que la hace parecer más segura que el cast implícito, cuando en realidad ambas dependen de que el contenido sea UTC y solo una de las dos depende además de la sesión. Elegir la implícita **obliga** a hacer explícita esa dependencia en el script, que es mejor que dejarla tácita detrás de una cláusula que parece cubrirla.

**Alternativa descartada — columna nueva, backfill, swap.** Es el procedimiento correcto cuando el `ALTER` reescribe y la tabla es grande. Acá el `ALTER` no reescribe, así que introduce complejidad, una ventana de inconsistencia y código de doble escritura a cambio de nada.

### D-2 — El tipo se declara en dos lugares: la migración y los modelos

La migración cubre producción. Los modelos cubren el arnés de tests, que construye su esquema con `create_all` (`conftest.py:80`). Declarar solo uno de los dos produce el peor resultado posible: una suite verde validando un esquema distinto del real.

Los campos `datetime` de los modelos pasan a declarar explícitamente el tipo con zona, de modo que `create_all` fabrique `timestamptz`. Es la misma propiedad expresada en los dos dialectos en que el proyecto la necesita, y la duplicación es deliberada porque las dos rutas de creación de esquema son reales.

Para que la duplicación no derive con el tiempo, se agrega el test de esquema de D-5: lee `information_schema` de la base de tests —construida por `create_all`— y afirma que las 19 columnas son `timestamptz`. Ese test hace fallar cualquier modelo nuevo que nazca con una columna de fecha sin zona, que es la forma de que la corrección sobreviva a la próxima tabla.

**Alternativa descartada — solo la migración, y que los tests corran sobre naive.** Es lo que hay hoy y es exactamente el mecanismo que impidió detectar el defecto: la propiedad no es expresable en el arnés.

**Alternativa descartada — hacer que el arnés aplique las migraciones en vez de `create_all`.** Es la solución de fondo y probablemente correcta a largo plazo: eliminaría la duplicación y validaría las migraciones. Pero cambia el arnés de test de todo el backend —10 migraciones, orden, idempotencia, el `seed_admin` que hoy vive en el conftest— y eso es una change propia, no un efecto colateral de arreglar las fechas.

### D-3 — El script de migración verifica su propia precondición y falla ruidosamente

D-1 introduce una dependencia real: si la sesión no está en UTC, el script corrompe los datos sin error. Un `SET TimeZone='UTC'` al principio la satisface, pero un `SET` que alguien borre en un rebase, o un script ejecutado por partes copiando y pegando, la pierde sin señal.

El script abre entonces con una guarda que aborta si la zona efectiva no es UTC, antes de cualquier `ALTER`. Una migración que puede corromper en silencio bajo una condición de entorno debe volver esa condición imposible de incumplir accidentalmente, no documentarla en un comentario.

La idempotencia (D3) se resuelve consultando `information_schema.columns`: cada `ALTER` se ejecuta solo si la columna todavía es `timestamp without time zone`. Correr el script dos veces no produce error y la segunda corrida no hace nada — que es además lo que lo vuelve seguro si la primera se interrumpió a mitad.

### D-4 — La conversión de hora local a UTC ocurre en la frontera HTTP, no en la URL

Los filtros de fecha tienen un round-trip que no es obvio: `Events.tsx` los guarda en el estado, `frontend/src/utils/eventFilters.ts:33-34` los serializa a la **query string de la URL**, y `:15-16` los vuelve a leer de ahí. La URL es estado compartible: el operador la marca, la pega en un ticket, la manda por chat. Hay entonces dos lugares posibles para convertir, y no son equivalentes.

**Se convierte al construir la petición HTTP** (`frontend/src/api/events.ts:93-94`), no al escribir la URL. Consecuencias, todas deliberadas:

- La URL sigue llevando la hora de pared que el operador tipeó, que es la que puede leer y verificar de un vistazo. Una URL que dijera `date_from=2026-08-20T22:00:00Z` para un filtro tipeado como las 19:00 sería correcta y de lectura hostil.
- El `<input type="datetime-local">` se repuebla desde la URL sin conversión inversa. Convertir en la URL obligaría a un round-trip local→UTC→local en cada render, con un redondeo y un caso de borde por cada uno.
- Las URLs guardadas de antes de esta change conservan su significado literal: siguen queriendo decir la misma hora de pared. Convertir en la URL las reinterpretaría en silencio, corriéndolas tres horas — el mismo defecto que esta change existe para eliminar, aplicado al historial.
- Hay **un** punto de conversión, y por lo tanto un punto donde ponerle un test.

El costo es que la URL es ambigua respecto de la zona si se comparte entre operadores en zonas distintas. Es un costo aceptable y acotado: el sistema es de un único laboratorio, la interpretación es siempre "la zona de quien abre el link", y la pantalla muestra la zona junto a los resultados, así que la ambigüedad es visible en vez de tácita. La alternativa cambia la semántica de todos los enlaces existentes para resolver un caso que este despliegue no tiene.

`frontend/src/utils/eventFilters.test.ts:37-43` fija hoy la forma naive de esas cadenas en la URL. Bajo esta decisión **sigue siendo correcto** y no se toca: la URL efectivamente conserva la hora local sin desfase. Que ese test siga pasando es una confirmación de la decisión, no una omisión.

### D-5 — Los tests afirman propiedades que el defecto vuelve falsas, nunca que la cadena parsee

Es la decisión de diseño más importante de esta change, porque el defecto sobrevivió a un test escrito para atraparlo. Tres reglas, y cada test nuevo cumple las tres:

1. **Nunca `fromisoformat` como aserción.** `datetime.fromisoformat` acepta la forma con desfase y la forma sin él; usarla para "verificar el formato" es equivalente a no verificar nada. La aserción sobre serialización interroga el `tzinfo` del resultado, o la presencia del desfase en la cadena. `test_event_listing_contract.py:310-312` es el ejemplo a no repetir: pasa idéntico antes y después.
2. **Nunca comparar un instante contra sí mismo por la misma ruta que lo produjo.** El test de ida y vuelta fija un instante UTC **conocido y literal**, lo escribe, lo lee por la API y compara contra la constante — no contra lo que la API devolvió antes. Un round-trip que compara la salida consigo misma pasa aunque las dos puntas estén corridas por igual, que es justamente el estado actual del sistema.
3. **La zona se fija explícitamente en todo test que involucre render.** jsdom hereda la zona del proceso. Un test de formateo en una CI en UTC pasa bajo el defecto y falla solo en la máquina del desarrollador: el punto ciego que produjo esto, reproducido dentro de la suite. Los tests de frontend fijan `TZ` a una zona con desfase **no nulo** —`America/Argentina/Buenos_Aires`, que es además la del operador real— porque una zona en UTC no distingue el código correcto del roto.

A esas tres se suma la reparación del guard existente. `test_fix09_no_utcnow_in_production_modules` (`test_c31_backend_event_correctness.py:754`) pasa a detectar también la forma sin paréntesis, y **se prueba contra su propio caso negativo**: un test que le entrega un fragmento con `default_factory=datetime.utcnow` y afirma que el guard lo rechaza. Un guard que nunca se vio fallar no es evidencia de nada — es la lección literal de esta change.

### D-6 — Un único helper de presentación, con el nulo y el futuro en el contrato

Los nueve sitios de render resuelven hoy lo mismo nueve veces con `toLocaleString('es-AR')` suelto, y `AgentCard.tsx:59-66` agrega su propia aritmética de tiempo transcurrido. Pasan a un módulo único bajo `frontend/src/utils/`, junto a los helpers que ya viven ahí (`ackStatus`, `actionError`, `eventFilters`), cada uno con su test al lado — la convención del directorio.

El contrato incluye dos casos que hoy nadie trata y que son la firma del defecto:

- **El nulo** es un estado real (`last_heartbeat` de un agente que nunca latió; `resolved_at` de un evento pendiente) y se renderiza como tal, no como una fecha inventada ni como `Invalid Date`.
- **El instante futuro** deja de producir un transcurrido negativo. Un latido con fecha futura ya no es posible por el desfase, pero sigue siendo posible por reloj desincronizado en el host del agente — que es precisamente el escenario que RN-90/RN-131 vigilan. El helper lo muestra como tal en vez de como un número negativo: es información operativa, no un error de formato que convenga esconder redondeando a cero.

La forma relativa acompaña a la absoluta donde ayuda a decidir; no la reemplaza. Un operador que correlaciona con `journalctl` o con un `.pcap` necesita el instante absoluto y necesita saber contra qué reloj lo está leyendo — por eso la zona es parte del render, no de un tooltip opcional.

## Risks / Trade-offs

**[La migración corrompe los datos en silencio si la sesión no está en UTC]** → La guarda de D-3 aborta antes de tocar nada. Es la única forma en que este cambio puede perder información, y es la razón por la que la precondición se verifica en vez de documentarse.

**[Un `ALTER COLUMN TYPE` toma `ACCESS EXCLUSIVE` sobre cada tabla]** → Bajo D-1 no hay reescritura: el lock se toma y se suelta en el orden de decenas de milisegundos (73 ms sobre 300 000 filas indexadas, medido). Aun así es un lock exclusivo, así que la migración se aplica con el backend detenido, que es de todos modos el procedimiento de D3 (aplicación manual, single-instance por RN-76). No hay escenario de despliegue en caliente que defender.

**[La reversión pierde el desfase]** → Verificado: `ALTER COLUMN ... TYPE timestamp` bajo sesión UTC también evita la reescritura (mismo filenode) y devuelve exactamente el valor naive original — `2026-08-20 19:55:59.641248`. La migración es reversible sin pérdida y sin costo, siempre bajo la misma precondición de zona. El rollback completo es: revertir el código y correr el `ALTER` inverso.

**[Un cliente que hoy asume la forma sin desfase se rompe]** → El único consumidor de la API es el frontend de este repositorio, que se modifica en la misma change. El agente **no** consume la API: publica por Valkey Streams (RN-108, D8) y su `detected_at` viaja por un camino que no se toca. El riesgo real es el inverso al esperado: no hay consumidor externo que romper, pero sí tests que fijan la forma vieja, y esos deben migrar deliberadamente en vez de ajustarse hasta que pasen.

**[`test_event_listing_contract.py:310` puede empezar a fallar]** → Afirma `datetime.fromisoformat(body["detected_at"]) == event.detected_at` con `_NOW = datetime(2026, 5, 1, 12, 0, 0)` naive (`:44`). Tras el cambio el lado izquierdo es aware; si el atributo del ORM sigue siendo el valor naive de la fixture, `==` devuelve `False` **sin lanzar excepción** y el test falla por la razón correcta. Es una señal útil, no un daño: la fixture pasa a construir instantes aware. Lo que no debe hacerse es relajar la aserción para que pase.

**[La suite empieza a depender de una variable de entorno de zona]** → Los tests de frontend fijan `TZ`. Si esa configuración se pierde, los tests siguen pasando en una CI en UTC y dejan de proteger nada — el mismo modo de fallo silencioso que esta change combate. Mitigación: la fijación va en la configuración de vitest, no en cada archivo, y uno de los tests afirma que el desfase efectivo **no es cero**, de modo que perder la configuración rompe la suite en vez de vaciarla.

**[Queda una duplicación entre modelos y migraciones]** → D-2 la asume a conciencia. El test de esquema es lo que impide que derive; la eliminación de fondo (que el arnés aplique migraciones) queda declarada como follow-up.

## Migration Plan

1. Detener el backend. `docker compose stop backend`. La migración toma locks exclusivos y el proyecto es single-instance (RN-76); no hay despliegue en caliente que preservar.
2. Respaldar. `pg_dump` de la base antes del `ALTER`. La operación es reversible sin pérdida (verificado), pero el respaldo es lo que vuelve la afirmación anterior innecesaria.
3. Aplicar `psql $DATABASE_URL -f backend/db/migrations/011_*.sql`. El script fija la zona, verifica la precondición, y convierte solo las columnas que todavía sean naive.
4. Verificar contra `information_schema`: las 19 columnas devuelven `timestamp with time zone` y ninguna otra columna cambió de tipo. Comprobar además, sobre una fila conocida previa a la migración, que el instante no se movió.
5. Desplegar backend y frontend. Levantar el backend y confirmar que `GET /events` devuelve el desfase explícito.
6. Verificar en la consola: la hora mostrada coincide con la del reloj de pared para un evento recién generado, la zona es visible, y el transcurrido de un agente vivo es positivo y pequeño.

**Rollback**: revertir el código, correr el `ALTER` inverso a `timestamp` bajo sesión UTC (metadata-only, sin pérdida), levantar. Como los valores almacenados no cambian en ninguna de las dos direcciones, el rollback es seguro aunque hayan entrado datos nuevos después de la migración.

## Open Questions

- **¿El arnés de tests debe aplicar las migraciones en vez de `create_all`?** D-2 lo deja fuera por tamaño, y el test de esquema tapa el agujero mientras tanto. Es la solución de fondo: eliminaría la duplicación de D-2 y, sobre todo, haría que las 11 migraciones se ejecuten alguna vez en CI, cosa que hoy no ocurre. Merece su propia change.
- **¿Se fija `TZ`/`PGTZ` explícitamente en el compose una vez migrado?** Después de la migración deja de afectar la corrección, pero la sesión sigue determinando cómo se interpreta un literal naive escrito a mano en `psql`. Es higiene, no corrección, y conviene decidirla cuando ya no pueda enmascarar una migración incompleta.
- **¿El índice ausente sobre `events.created_at`?** Fuera de scope acá, pero la migración toca justamente esa columna y vale dejar registrado que el `ORDER BY` y el filtro de rango del listado principal corren hoy sin índice.
