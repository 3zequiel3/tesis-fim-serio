## MODIFIED Requirements

### Requirement: Test harness owns schema, seeding, and isolation

The backend test harness SHALL provide a single root `backend/tests/conftest.py`
that owns database setup. It SHALL create the schema via
`SQLModel.metadata.create_all(engine)` exactly once per session on the configured
test engine, seed the canonical admin once, and isolate every test by running
`TRUNCATE ... RESTART IDENTITY CASCADE` on all tables followed by re-seeding the
admin. The harness SHALL NOT rely on the FastAPI lifespan running under
`httpx.AsyncClient` + `ASGITransport` (which does not execute startup/shutdown).
The harness SHALL run against a real PostgreSQL instance, not in-memory SQLite.

El aislamiento de la base de datos no alcanza: **la suite MUST NOT depender de ningún recurso
ambiental compartido con el sistema que la aloja** (D78/RN-172). Un recurso ambiental compartido es
todo aquel cuyo estado lo fija el entorno de invocación y no el arnés — un puerto TCP fijo, un archivo
de configuración resuelto contra el directorio de trabajo, una variable exportada por el proceso
invocante. Una prueba acoplada a uno de ellos produce fallas que **no dicen nada del producto**: el
resultado de la suite pasa a ser función de dónde y cuándo se la corre.

Esta obligación SHALL satisfacerse **sin cambiar ninguna ruta de código de producción**. Un arreglo
del arnés que altere el comportamiento de producción convierte un defecto de instrumentación en un
riesgo de producto, e invalida el arreglo aunque la suite quede verde.

**Puertos de escucha.** Ninguna prueba SHALL depender de que un puerto de escucha fijo esté libre.
El arnés SHALL garantizar que un test que ejecuta el lifespan de la aplicación no intente ligar el
puerto por defecto del servidor mTLS. Cuando una prueba necesite un listener real, SHALL obtener un
puerto efímero del sistema operativo y pasarlo explícitamente. El default de producción del puerto y
la invocación del lifespan MUST permanecer sin cambios.

Esta garantía SHALL implementarse de forma **centralizada, una sola vez**, y no repitiéndola en cada
call site que ejecuta el lifespan. Una garantía centralizada cubre además los call sites futuros; una
enumeración de call sites cubre sólo los que existían cuando se escribió, y el modo de falla no nombra
la causa —el bind fallido rompe el portal de concurrencia compartido y el error que se reporta es el
del teardown, en el test y en sus hermanos de la misma sesión—, de modo que la próxima aparición se
diagnostica desde cero.

**Entorno de configuración.** La suite SHALL partir de un entorno de configuración **determinado**.
Ni las variables exportadas por el proceso invocante ni el archivo de entorno que la aplicación
resuelve contra el directorio de trabajo SHALL poder decidir el valor de una opción que una prueba
afirma. Neutralizar únicamente las variables del proceso MUST considerarse insuficiente: el archivo de
entorno se lee aunque la variable correspondiente no exista en el proceso, y es esa ruta la que
produce el acoplamiento. El saneamiento SHALL hacerse en el conftest raíz, junto al bloque que ya fija
el entorno canónico antes del primer import de la aplicación, y no prueba por prueba.

La configuración de la aplicación MUST NOT cambiar para satisfacer esta obligación: que la aplicación
lea su archivo de entorno es correcto y necesario para el despliegue; lo que MUST cesar es que la
suite lo herede.

#### Scenario: Fresh database produces a green, order-independent suite

- **WHEN** the suite runs against a freshly created empty `fim_test` database with
  Valkey reachable, via `uv run pytest` from `backend/`
- **THEN** the schema and seeded admin are created by the root conftest
- **AND** the full suite passes regardless of test execution order
- **AND** no test depends on state left behind by a previous test

#### Scenario: Per-test isolation resets database state

- **WHEN** one test inserts rows and a subsequent test runs
- **THEN** the subsequent test observes only the freshly re-seeded admin and no
  leftover rows from the previous test

#### Scenario: Dos pruebas con lifespan corren en la misma sesión sin colisionar

- **WHEN** dos o más pruebas que ejecutan el lifespan de la aplicación corren en la misma sesión
- **THEN** ninguna falla por un puerto de escucha ya ocupado
- **AND** el portal de concurrencia compartido no queda inutilizado para las pruebas siguientes

#### Scenario: La suite corre con el puerto por defecto ya ocupado por otro proceso

- **WHEN** la suite se ejecuta en una máquina donde otro proceso ya está escuchando en el puerto por
  defecto del servidor mTLS
- **THEN** la suite produce el mismo resultado que en una máquina donde ese puerto está libre

#### Scenario: Una prueba que necesita un listener real obtiene un puerto efímero

- **WHEN** una prueba necesita un servidor mTLS realmente escuchando
- **THEN** obtiene un puerto efímero del sistema operativo y lo pasa explícitamente
- **AND** no depende del valor por defecto

#### Scenario: El código de producción no cambia para satisfacer el aislamiento del puerto

- **WHEN** se inspecciona la función que construye el servidor mTLS y su invocación en el lifespan
- **THEN** el valor por defecto del puerto y el comportamiento de la invocación son los mismos que
  antes del cambio

#### Scenario: La suite corre desde un directorio con archivo de entorno presente

- **WHEN** la suite se ejecuta con el directorio de trabajo en la raíz del repositorio, donde existe
  un archivo de entorno con opciones de notificación definidas
- **THEN** las pruebas que afirman el valor por defecto de esas opciones lo observan
- **AND** producen el mismo resultado que si se las ejecutara desde un directorio sin ese archivo

#### Scenario: Una variable exportada por el proceso invocante no altera el resultado

- **WHEN** la suite se ejecuta con variables de configuración de la aplicación exportadas en el
  entorno del proceso invocante
- **THEN** las pruebas que afirman valores por defecto no las observan

#### Scenario: La configuración de la aplicación no se modifica para lograr el aislamiento

- **WHEN** se inspecciona la configuración de la aplicación
- **THEN** sigue leyendo su archivo de entorno con la misma resolución que antes del cambio
