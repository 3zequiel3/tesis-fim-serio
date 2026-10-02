## ADDED Requirements

### Requirement: Registro de migraciones en `schema_migrations` (D84/RN-178)

El sistema SHALL mantener la tabla `schema_migrations` con las columnas `version` (entero, clave
primaria), `filename` (texto no nulo), `sha256` (texto no nulo, 64 caracteres hexadecimales en
minúsculas) y `applied_at` (`TIMESTAMPTZ` no nulo, default `now()`). La tabla SHALL crearla
únicamente la migración `backend/db/migrations/000_schema_migrations.sql`, escrita de forma
idempotente (`CREATE TABLE IF NOT EXISTS`). La tabla MUST NOT declararse como modelo SQLModel:
`create_all` no la crea, y el `TRUNCATE` del arnés de tests, que recorre `SQLModel.metadata`, no la
vacía.

Cada archivo de migración SHALL llamarse `NNN_<descripcion>.sql`, con `NNN` de tres dígitos. La
numeración del árbol SHALL ser contigua desde `000` y sin duplicados. La migración `000` se registra
a sí misma con `version = 0`.

#### Scenario: La migración 000 crea el registro y se registra
- **WHEN** `scripts/migrar.py` corre contra una base sin la tabla `schema_migrations`
- **THEN** la tabla existe con las cuatro columnas declaradas
- **AND** contiene una fila con `version = 0`, `filename = '000_schema_migrations.sql'` y el
  `sha256` del archivo

#### Scenario: `create_all` no crea el registro
- **WHEN** se ejecuta `SQLModel.metadata.create_all(engine)` sobre una base vacía
- **THEN** la tabla `schema_migrations` no existe

#### Scenario: Un hueco en la numeración del árbol se rechaza
- **WHEN** el directorio de migraciones contiene `021_…sql` y `023_…sql` pero no `022_…sql`
- **THEN** `scripts/migrar.py` termina con código distinto de cero sin conectarse a la base
- **AND** el mensaje nombra la versión faltante

### Requirement: Versión de esquema esperada incrustada en el paquete del backend (D84/RN-178)

El backend SHALL declarar la constante `EXPECTED_SCHEMA_VERSION` en un módulo de `backend/app/core/`,
con el número de la mayor migración del árbol. La constante viaja en la imagen porque el `Dockerfile`
copia `app/`; las migraciones no viajan. Un test de la suite de backend SHALL fallar si la constante
difiere de la mayor versión presente en `backend/db/migrations/`.

#### Scenario: La constante coincide con el árbol
- **WHEN** la mayor migración del árbol es `022_add_alert_channel_accepted_at.sql`
- **THEN** `EXPECTED_SCHEMA_VERSION == 22`
- **AND** el test del árbol pasa

#### Scenario: Una migración nueva sin subir la constante rompe la suite
- **WHEN** se agrega `023_<descripcion>.sql` al árbol y `EXPECTED_SCHEMA_VERSION` sigue en `22`
- **THEN** el test del árbol falla nombrando ambos valores

### Requirement: El arranque del backend aborta con un esquema atrasado (D84/RN-178)

El `lifespan` SHALL leer `max(version)` de `schema_migrations` **antes** de ejecutar `create_all`. Si
la tabla no existe, o si `max(version)` es menor que `EXPECTED_SCHEMA_VERSION`, el arranque SHALL
abortar con una excepción, y el backend MUST NOT aceptar requests ni arrancar consumers. Antes de
abortar SHALL emitir el log `backend.schema_outdated` en nivel `error` con `expected_version`,
`found_version` (nulo si el registro no existe) y una instrucción que nombre `scripts/migrar.py`. Con
la versión al día SHALL emitir `backend.schema_version` en nivel `info` y continuar. Una versión mayor
que la esperada MUST NOT abortar el arranque.

#### Scenario: Base registrada hasta N−1 aborta el arranque
- **WHEN** el backend arranca contra una base efímera cuyo registro llega hasta
  `EXPECTED_SCHEMA_VERSION - 1`
- **THEN** el `lifespan` levanta una excepción y el backend no arranca
- **AND** se emite `backend.schema_outdated` con `expected_version = EXPECTED_SCHEMA_VERSION` y
  `found_version = EXPECTED_SCHEMA_VERSION - 1`
- **AND** `create_all` no se ejecutó: las tablas de aplicación siguen sin existir

#### Scenario: Base sin registro aborta el arranque
- **WHEN** el backend arranca contra una base sin la tabla `schema_migrations`
- **THEN** el `lifespan` levanta una excepción
- **AND** `backend.schema_outdated` lleva `found_version` nulo

#### Scenario: Base al día arranca
- **WHEN** el registro llega hasta `EXPECTED_SCHEMA_VERSION`
- **THEN** el `lifespan` continúa con `create_all` y `seed_admin`
- **AND** se emite `backend.schema_version` con la versión encontrada

### Requirement: `scripts/migrar.py` aplica las pendientes en orden, una transacción por migración (D84/RN-178)

`scripts/migrar.py` SHALL calcular como pendientes las versiones del árbol ausentes del registro y
aplicarlas en orden ascendente. Cada migración SHALL ejecutarse en **una sola transacción** que
contiene el contenido del archivo y el `INSERT` de su fila en `schema_migrations`: si el archivo
falla, ni sus cambios ni su fila persisten. Ante el primer fallo, `migrar.py` SHALL detenerse sin
intentar las siguientes y terminar con código distinto de cero nombrando el archivo. Una versión
pendiente menor que la mayor versión registrada (un hueco en el registro) SHALL abortar sin aplicar
nada.

#### Scenario: Dos pendientes se aplican en orden
- **WHEN** el registro llega hasta `20` y el árbol hasta `22`
- **THEN** `migrar.py` aplica `021` y luego `022`, cada una en su propia transacción
- **AND** el registro queda con `max(version) = 22`

#### Scenario: Una migración que falla no deja rastro
- **WHEN** la migración `022` falla a mitad de su ejecución
- **THEN** no queda fila con `version = 22` en el registro
- **AND** ningún cambio parcial de `022` persiste
- **AND** `migrar.py` termina con código distinto de cero nombrando `022_add_alert_channel_accepted_at.sql`

#### Scenario: Sin pendientes no se ejecuta nada
- **WHEN** el registro ya llega hasta la mayor versión del árbol
- **THEN** `migrar.py` no ejecuta ninguna migración y termina con código cero

### Requirement: Una base nueva se registra sin ejecutar migraciones (D84/RN-178, D3)

`scripts/migrar.py` SHALL tratar como base nueva a la que no tiene **tablas de aplicación** —ninguna
tabla en el esquema `public` distinta de `schema_migrations`—. Sobre una base nueva SHALL aplicar
`000` y registrar las versiones `1` a N con su
`sha256` **sin ejecutar** sus archivos, porque `create_all` construirá la forma vigente del esquema en
el primer arranque del backend (D3). La instalación SHALL correr `migrar.py` con el servicio `db`
levantado y **antes** del primer arranque del backend.

#### Scenario: Instalación nueva queda lista para arrancar
- **WHEN** `migrar.py` corre contra una base `fim` recién creada, sin tablas
- **THEN** el registro contiene las versiones `0` a N
- **AND** ninguna sentencia de las migraciones `001` a N se ejecutó
- **AND** el backend arranca a continuación y `create_all` crea las tablas

### Requirement: Una base existente se registra con `--marcar-hasta N` (D84/RN-178)

`scripts/migrar.py --marcar-hasta N` SHALL aplicar `000` si falta y registrar las versiones `1` a N
ausentes del registro, con su `sha256`, **sin ejecutar** sus archivos, y SHALL terminar sin aplicar
pendientes posteriores. N mayor que la mayor versión del árbol SHALL rechazarse, y también
`--marcar-hasta` sobre una base sin tablas de aplicación, cuyo camino ya registra hasta N. Cuando la base tiene
tablas de aplicación, el registro está vacío o sólo contiene `0`, y no se pasó `--marcar-hasta`,
`migrar.py` SHALL abortar sin aplicar nada e indicar que la base existente debe registrarse con
`--marcar-hasta N`.

#### Scenario: Registrar una base existente sin reaplicar
- **WHEN** una base con las migraciones `001`–`022` aplicadas a mano y sin registro recibe
  `migrar.py --marcar-hasta 22`
- **THEN** el registro contiene las versiones `0` a `22`
- **AND** ninguna sentencia de `001`–`022` se ejecutó

#### Scenario: Base existente sin registro y sin bandera aborta
- **WHEN** `migrar.py` corre sin `--marcar-hasta` contra una base con tablas de aplicación y sin
  versiones registradas mayores que `0`
- **THEN** termina con código distinto de cero sin aplicar ninguna migración
- **AND** el mensaje indica `--marcar-hasta N`

### Requirement: `sha256` distinto en una migración registrada aborta (D84/RN-178)

Antes de aplicar o registrar nada, `scripts/migrar.py` SHALL comparar el `sha256` de cada fila del
registro con el del archivo de igual versión en el árbol. Si difieren, o si una versión registrada no
tiene archivo en el árbol, SHALL abortar con código distinto de cero sin modificar la base, nombrando
cada versión discordante.

#### Scenario: Un archivo editado después de aplicarse
- **WHEN** `021_add_agent_queue_pressure_high.sql` fue modificado después de registrarse
- **THEN** `migrar.py` termina con código distinto de cero antes de aplicar cualquier pendiente
- **AND** el mensaje nombra la versión `21` y ambos hashes

#### Scenario: Una versión registrada que no existe en el árbol
- **WHEN** el registro contiene `version = 23` y el árbol termina en `022`
- **THEN** `migrar.py` aborta sin modificar la base nombrando la versión `23`

### Requirement: Conexión por `docker compose exec` sin exponer el puerto 5432 (D84/RN-178)

Por defecto, `scripts/migrar.py` SHALL ejecutar SQL mediante
`docker compose exec -T <servicio> psql -X -v ON_ERROR_STOP=1 -U <usuario> -d <base>`, con servicio
`db`, usuario `fim` y base `fim` como valores por defecto, y con banderas para pasar archivos y
proyecto de compose (`-f`, `-p`). Cada transacción de migración SHALL correr en una invocación
`psql --single-transaction`. Con `--dsn <url>`, `migrar.py` SHALL conectarse directamente a esa URL y
preservar las mismas garantías de transacción y registro. El modo por defecto MUST NOT requerir
dependencias fuera de la biblioteca estándar de Python ni exponer el puerto 5432 al host.

#### Scenario: Modo por defecto usa el contenedor `db`
- **WHEN** `migrar.py` corre sin `--dsn`
- **THEN** toda sentencia SQL viaja por `docker compose exec -T db psql` con `ON_ERROR_STOP=1`
- **AND** el puerto 5432 no se publica en ningún archivo compose

#### Scenario: Modo `--dsn` con las mismas garantías
- **WHEN** `migrar.py --dsn postgresql://…` aplica una migración que falla
- **THEN** no persiste ni la migración ni su fila de registro

### Requirement: Verificación de sólo lectura y preflight del laboratorio (D84/RN-178)

`scripts/migrar.py --verificar` SHALL leer el registro, comprobar los `sha256` y comparar
`max(version)` con la mayor versión del árbol, sin modificar la base: código `0` si está al día, y
distinto de cero —con mensaje que nombra lo pendiente o lo discordante— en cualquier otro caso. El
preflight de `lab/corrida_unificada.sh` SHALL correr `migrar.py` (aplicar pendientes) y luego
`migrar.py --verificar`, y SHALL abortar la corrida si la verificación falla; no SHALL volver a
aplicar migraciones con un bucle de `psql`. Los scripts que levantan el backend sobre una base nueva
(`scripts/run-isolated-acceptance-lab.sh`, `scripts/run-us02-us20-us31-acceptance-lab.sh`) SHALL
correr `migrar.py` después de levantar `db` y antes de levantar `backend`.

#### Scenario: El preflight detecta un esquema atrasado
- **WHEN** la base del laboratorio tiene registro hasta `21` y el árbol del candidato llega a `22`, y
  la aplicación de la pendiente falla
- **THEN** `lab/corrida_unificada.sh` registra un mensaje `ABORTA` que nombra la versión encontrada y
  la esperada
- **AND** termina antes de medir

#### Scenario: El preflight no modifica una base al día
- **WHEN** el registro ya llega a la mayor versión del árbol
- **THEN** `migrar.py --verificar` termina con código `0` y la base no cambia
