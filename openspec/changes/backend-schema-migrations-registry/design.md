## Context

**Cómo se construye hoy el esquema.** El `lifespan` (`backend/app/main.py:77-78`) inicializa Valkey
(`:81-82`), asegura la CA (`:83-89`) y ejecuta `SQLModel.metadata.create_all(engine)` (`:90`) y
`seed_admin()` (`:91`). `create_all` crea tablas ausentes y no toca las existentes. Toda columna
agregada después de la creación inicial llega por un script SQL manual en `backend/db/migrations/`
(`001`–`022`), aplicado con `psql` según la convención D3 (`docs/arquitectura_stack.md:2099`). Los 22
scripts son idempotentes (`ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, y `011` consulta
`information_schema` antes de cada `ALTER`). Ninguno usa control de transacción: los `BEGIN` de
`011_timestamptz.sql:43,77` abren bloques `DO $$`, no transacciones.

**Qué no sabe nadie.** No existe registro de qué scripts se aplicaron. La imagen sólo copia `app/`
(`backend/Dockerfile:63`), así que el contenedor no puede consultar el árbol de migraciones. El motor
vive en `backend/app/core/database.py:38-45` (`create_engine` con `pool_pre_ping`, sin otro hook).

**El parche del laboratorio.** `lab/corrida_unificada.sh:68-105` reaplica cada `.sql` por
`docker compose exec -T db psql` (`:77-79`, descartando la salida y los errores) y luego compara cada
columna de `SQLModel.metadata` contra `information_schema.columns` desde dentro del contenedor
`backend` (`:80-105`). Detecta la falta de una columna, pero sólo en el laboratorio y sólo después de
haber intentado arreglarla en silencio.

**Restricciones de topología.** El servicio `db` no publica 5432 al host (`docker-compose.yml:45-68`).
`docker-compose.yml:60` monta `./db/init` como `docker-entrypoint-initdb.d`, que crea bases
auxiliares; no toca las tablas de `fim`. El host de desarrollo no tiene `psql` instalado.

**El arnés de tests.** `backend/tests/conftest.py:202-210` crea el esquema con `create_all` una vez por
sesión, y `_db_isolation` (`:282-298`) trunca **sólo** las tablas de `SQLModel.metadata`. Hay al menos
41 call sites con `TestClient(app)` que ejecutan el `lifespan` real (D78/RN-172).

**Decisión que gobierna.** D84/RN-178, ampliada en `1c308d5`: base nueva → registrar hasta N sin
ejecutar y dejar a `create_all`; conexión por `docker compose exec -T db psql -v ON_ERROR_STOP=1` con
`--dsn` opcional; `sha256` discordante → abortar; versión esperada como constante en `backend/app/`
con test contra el árbol; la suite registra la versión esperada en su setup.

## Goals / Non-Goals

**Goals:**

- Que un backend nunca arranque contra una base cuyo registro esté atrasado respecto de su modelo.
- Que aplicar migraciones sea un comando con orden, atomicidad por archivo y registro verificable.
- Que el registro detecte un archivo de migración editado después de aplicarse.
- Que una instalación nueva y una base existente tengan, cada una, un camino explícito al registro.
- Que el preflight del laboratorio deje de reparar en silencio y pase a verificar.

**Non-Goals:**

- Adoptar Alembic o cualquier herramienta de migraciones con *downgrade*. D3 se conserva.
- Mover las migraciones a un init-container (el disparador de D3 queda documentado pero no se activa).
- Detectar que a una columna del modelo le falta una migración: eso lo sigue cubriendo la comparación
  de columnas del preflight, que se conserva.
- Verificar `sha256` en el arranque del backend: la imagen no tiene los archivos.
- Reescribir las migraciones `001`–`022`.

## Decisions

### D-1. `schema_migrations` vive fuera de `SQLModel.metadata`

La tabla se crea sólo con `000_schema_migrations.sql` (`CREATE TABLE IF NOT EXISTS`) y se lee con SQL
crudo. **Por qué:** si fuera un modelo, `create_all` la crearía vacía en una base nueva y el registro
pasaría a depender del orden del arranque; además `_db_isolation` la truncaría en cada test
(`conftest.py:295` arma el `TRUNCATE` desde `SQLModel.metadata.tables`) y la guarda fallaría en el test
siguiente. **Alternativa descartada:** modelo SQLModel excluido del `TRUNCATE` por nombre — agrega una
excepción en el arnés y deja a `create_all` como segundo creador del registro.

Esquema:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER     PRIMARY KEY,
    filename    TEXT        NOT NULL,
    sha256      CHAR(64)    NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`sha256` es el hash de los **bytes crudos** del archivo, en hexadecimal minúsculo. Se fija así para que
`migrar.py` y el `conftest` lo calculen idéntico sin normalizar finales de línea.

### D-2. Constante y guarda en `backend/app/core/schema_version.py`

El módulo declara `EXPECTED_SCHEMA_VERSION: Final[int] = 22`, la excepción
`SchemaVersionError(RuntimeError)` y `check_schema_version(engine) -> int`. La función:

1. abre `engine.connect()` y consulta `SELECT to_regclass('public.schema_migrations')`; si es nulo, la
   versión encontrada es `None`;
2. si existe, `SELECT max(version) FROM schema_migrations`;
3. si es `None` o menor que la esperada, emite `log.error("backend.schema_outdated",
   expected_version=…, found_version=…, remedy="python3 scripts/migrar.py")` y levanta
   `SchemaVersionError`; si no, emite `log.info("backend.schema_version", …)` y devuelve la versión.

`to_regclass` evita provocar un `UndefinedTable` dentro de la conexión. La función recibe el engine
como argumento para poder probarla contra una base efímera sin tocar el global.

**Alternativas descartadas:** (a) copiar `db/migrations/` a la imagen y calcular el máximo al arrancar
— contradice D84(4) y hace que la versión esperada dependa de qué se copió, no de qué se compiló;
(b) `ARG` de Docker con la versión — los tests corren desde el árbol fuente sin build, y habría dos
fuentes de verdad; (c) archivo generado en el build — idem.

### D-3. La guarda corre primero en el `lifespan`

Se invoca inmediatamente después de `_log_console_tls_mode()` (`main.py:80`) y antes de
`init_valkey` (`:81`), es decir, antes de cualquier efecto: `ensure_ca` escribe certificados,
`create_all` crea tablas y `seed_admin` inserta. D84 sólo exige «antes de `create_all`»; adelantarla
más es la forma más estricta de cumplirlo. Si la guarda levanta, la excepción se propaga fuera del
`lifespan`, Starlette reporta el fallo de arranque y uvicorn termina con código distinto de cero.

**Alternativa descartada:** `sys.exit` dentro de la guarda — oculta la causa a los tests y a uvicorn.

### D-4. `scripts/migrar.py`: núcleo puro + dos ejecutores

Estructura en tres capas, para que la lógica sea testeable sin base de datos:

- **Árbol** — `leer_arbol(directorio) -> list[Migracion]` (`version`, `filename`, `sha256`, `ruta`).
  Valida nombre `^(\d{3})_[a-z0-9_]+\.sql$`, ausencia de duplicados y numeración contigua desde `000`.
  La regex además garantiza que `filename` y `sha256` sean seguros para interpolar en el `INSERT`.
- **Plan** — `planificar(arbol, registro, hay_tablas_app, marcar_hasta) -> Plan`, función pura que
  devuelve la lista ordenada de acciones (`aplicar`, `registrar`) o un error tipado. Orden de
  verificación: (1) árbol válido; (2) cada fila registrada tiene archivo y su `sha256` coincide;
  (3) clasificación de la base; (4) pendientes.
- **Ejecutor** — protocolo con `consultar(sql) -> list[tuple]` y `transaccion(sql) -> None`.
  - `EjecutorCompose` (por defecto): `docker compose [-p P] [-f F]… exec -T <servicio> psql -X -q
    -v ON_ERROR_STOP=1 -U <usuario> -d <base>`; las consultas agregan `-A -t -F '|' -c`; las
    transacciones agregan `--single-transaction -f -` y pasan el SQL por stdin. Sólo biblioteca
    estándar (`subprocess`).
  - `EjecutorDsn` (`--dsn`): importa `psycopg` de forma diferida; acepta y normaliza
    `postgresql+psycopg://`. `transaccion` corre dentro de `with conn.transaction():`; psycopg 3 admite
    varias sentencias en un `execute` sin parámetros.

Cada migración se aplica con **una sola** llamada a `transaccion`, cuyo texto es el contenido del
archivo seguido del `INSERT INTO schema_migrations (version, filename, sha256) VALUES (…)`. Así la
fila y los cambios comparten transacción en ambos ejecutores. `ALTER TYPE … ADD VALUE` (`001`) es válido
dentro de una transacción en Postgres 18 mientras el valor no se use en la misma transacción, que es el
caso. `SET TimeZone` de `011` vale para la sesión de esa invocación.

**Alternativa descartada:** `--dsn` vía `psql` local — el host de desarrollo no tiene `psql`, y los
tests de integración no podrían correr.

### D-5. Clasificación de la base y modos

`hay_tablas_app` = `SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <>
'schema_migrations'` > 0. Se consulta **antes** de aplicar `000`.

| Base | Registro (> 0) | Bandera | Resultado |
|---|---|---|---|
| sin tablas de aplicación | — | ninguna | aplica `000`, registra `1..N` sin ejecutar |
| sin tablas de aplicación | — | `--marcar-hasta` | error de uso: el camino de base nueva ya registra hasta N |
| con tablas | vacío | ninguna | aborta: «base existente sin registro, usar `--marcar-hasta N`» |
| con tablas | cualquiera | `--marcar-hasta N` | aplica `000` si falta, registra `1..N` ausentes, no aplica más |
| con tablas | no vacío | ninguna | aplica pendientes en orden; hueco (pendiente < máximo registrado) aborta |
| cualquiera | cualquiera | `--verificar` | sólo lee: sha, hueco y `max(version)` contra el árbol |

Códigos de salida: `0` éxito o al día; `1` fallo de ejecución o de conexión; `2` uso o árbol inválido;
`3` integridad (sha discordante, versión registrada sin archivo, hueco, base existente sin registro);
`4` `--verificar` encontró pendientes.

### D-6. El `conftest` registra con su propio helper

`_create_schema` (`conftest.py:202-210`) agrega, después de `create_all`, la ejecución de
`000_schema_migrations.sql` y el registro de `0..EXPECTED_SCHEMA_VERSION` leyendo los archivos del
árbol (`Path(__file__).parents[1] / "db" / "migrations"`) con `ON CONFLICT (version) DO NOTHING`. No
importa `scripts/migrar.py`: la suite de backend no debe depender de `scripts/` en `sys.path`, y la
lógica es una lectura de directorio más `hashlib.sha256`. El registro se completa también si la base
de test ya existía de una sesión previa.

### D-7. Coordinación con la Change 62 (`023`)

La constante y el test del árbol (D-2) resuelven el orden de aterrizaje sin acuerdo previo:

- **66 aterriza primero.** `EXPECTED_SCHEMA_VERSION = 22`. Cuando la 62 agregue `023_…sql`, el test
  del árbol falla hasta que la 62 suba la constante a `23`; su `migrar.py` ya existe para aplicarla.
- **62 aterriza primero.** Al implementar esta change el árbol ya llega a `023`, y la tarea 1.1 fija la
  constante en el máximo **que encuentre**, no en `22`. Las bases existentes se registran con
  `--marcar-hasta` la mayor versión efectivamente aplicada; si hay duda sobre `023`, conviene marcar
  hasta `22` y dejar que `migrar.py` aplique `023`, que es aditiva e idempotente.

### D-8. Preflight del laboratorio y scripts de aceptación

En `lab/corrida_unificada.sh`, el bucle de `:76-79` se reemplaza por
`python3 scripts/migrar.py -f docker-compose.yml -f docker-compose.tls.yml -f
"$LAB/docker-compose.mailpit.yml"` seguido de `… --verificar`; un código distinto de cero en cualquiera
de los dos produce `say "ABORTA: …"` y `exit 1`. La comparación de columnas (`:80-105`) **se conserva**
como segunda verificación independiente: el registro prueba qué scripts corrieron, no que exista un
script para cada columna del modelo. El preflight nunca invoca `--marcar-hasta`: registrar
automáticamente ocultaría la deriva que la guarda existe para mostrar. La primera corrida sobre la base
persistente del laboratorio requiere un `--marcar-hasta` manual, documentado en `lab/README.md`.

`scripts/run-isolated-acceptance-lab.sh:94` y `scripts/run-us02-us20-us31-acceptance-lab.sh:127`
levantan `db` y `backend` en la misma línea sobre un proyecto efímero. Se parten en
`dc up -d --wait db`, `python3 scripts/migrar.py -p "$FIM_LAB_PROJECT" -f "$COMPOSE"` y el `up` del
resto. Esas bases son nuevas: `migrar.py` toma el camino de D-5 fila 1.

## Risks / Trade-offs

- **[Bucle de reinicio]** Con `restart: unless-stopped`, un backend que aborta por esquema reinicia en
  bucle. → Es el comportamiento buscado (no atiende con esquema atrasado); el log
  `backend.schema_outdated` nombra el remedio en cada intento. La guarda corre antes de `ensure_ca`,
  así que el bucle no tiene efectos.
- **[`--marcar-hasta` miente]** Un operador puede marcar una versión que nunca aplicó. → El README
  recomienda, ante la duda, marcar hasta una versión menor y dejar que `migrar.py` aplique el resto:
  las 22 migraciones son idempotentes. El preflight del laboratorio conserva la comparación de columnas.
- **[Dos ejecutores divergen]** `EjecutorCompose` y `EjecutorDsn` podrían comportarse distinto ante un
  error. → El plan y el texto de la transacción son comunes; los tests de integración corren con
  `--dsn` contra la base de test, y el modo compose se prueba en el preflight real (tarea 7.4) y con un
  test que fija la línea de comando.
- **[Despliegue rompe]** Toda base existente sin registro hace abortar al backend nuevo. → Paso de
  actualización documentado (`--marcar-hasta 22`) en README y `docs/despliegue_servidor_remoto.md`.
- **[Candidatos viejos]** `lab/corrida_unificada.sh:42` hace checkout del tag; un tag anterior a esta
  change no trae `migrar.py`. → El harness corregido sólo se usa con `v5.0-tesis` en adelante; para
  tags viejos el script aborta al no encontrar `scripts/migrar.py`.

## Migration Plan

1. Desplegar el código (backend + `scripts/migrar.py`) sin reiniciar el backend.
2. Con `db` levantado: `python3 scripts/migrar.py --marcar-hasta 22` (o la mayor versión aplicada).
3. `python3 scripts/migrar.py` para aplicar pendientes, si las hay.
4. `python3 scripts/migrar.py --verificar` → código `0`.
5. Reiniciar el backend; el log `backend.schema_version` confirma la versión.

**Rollback:** volver a la imagen anterior funciona sin tocar la base: el backend viejo ignora
`schema_migrations`, y una versión mayor que la esperada no aborta el nuevo.

## Open Questions

Ninguna bloqueante. D84/RN-178 cubre todas las decisiones de producto; lo restante (códigos de salida,
nombre del módulo, flags `-f`/`-p`/`--servicio`/`--usuario`/`--base`) es ergonomía de la herramienta.
