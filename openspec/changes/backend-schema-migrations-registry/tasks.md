## 0. Verificación previa

- [ ] 0.1 Correr `python3 scripts/check_spec_integrity.py` y registrar que pasa antes de tocar nada (D47/RN-141).
- [ ] 0.2 Listar `backend/db/migrations/` y anotar la mayor versión presente. Si ya existe `023_…sql` (la Change 62 aterrizó primero), todas las referencias a «22» de estas tareas pasan a esa versión (D-7 del design). Confirmar que todo nombre cumple `^\d{3}_[a-z0-9_]+\.sql$`; si alguno no, detenerse.
- [ ] 0.3 Confirmar que ninguna migración `001`–N contiene `BEGIN;`, `COMMIT`, `ROLLBACK`, `CREATE INDEX CONCURRENTLY` ni `VACUUM` fuera de bloques `DO $$` (hoy los únicos `BEGIN` son los de `011_timestamptz.sql:43,77`, dentro de `DO`). Una sentencia que no admite transacción rompe D-4; si aparece, detenerse.

## 1. Registro y versión esperada

- [ ] 1.1 Crear `backend/db/migrations/000_schema_migrations.sql` con el `CREATE TABLE IF NOT EXISTS schema_migrations` de D-1 del design, y un encabezado de comentario con el estilo de las demás migraciones, que cite D84/RN-178 y diga que la tabla no es un modelo SQLModel ni la crea `create_all`.
- [ ] 1.2 Crear `backend/app/core/schema_version.py` con `EXPECTED_SCHEMA_VERSION: Final[int]` igual a la mayor versión anotada en 0.2, `SchemaVersionError(RuntimeError)` y `check_schema_version(engine) -> int` según D-2 (consulta `to_regclass` primero, después `max(version)`; logs `backend.schema_outdated` en `error` y `backend.schema_version` en `info`; `remedy` nombra `python3 scripts/migrar.py`). Una versión mayor que la esperada no aborta.
- [ ] 1.3 Docstring del módulo: explicar por qué la constante vive en `app/` (el `Dockerfile` copia sólo `app/`, `backend/Dockerfile:63`), que el test del árbol la mantiene en sincronía y qué hacer al agregar una migración (subir la constante en el mismo commit).

## 2. Guarda de arranque

- [ ] 2.1 En `backend/app/main.py`, importar `check_schema_version` e invocarla con `engine` inmediatamente después de `_log_console_tls_mode()` (`:80`) y antes de `init_valkey` (`:81`), según D-3. La excepción no se captura.
- [ ] 2.2 Actualizar el docstring de `main.py` (`:4-6`): el paso 2 del orden de inicialización pasa a «verificación de esquema + init_valkey + create_all + seed_admin».
- [ ] 2.3 Verificar leyendo el diff que la guarda queda antes de `ensure_ca` (`:83`) y de `create_all` (`:90`), y que no se agregó ningún `try/except` alrededor.

## 3. Arnés de tests del backend

- [ ] 3.1 En `backend/tests/conftest.py`, extender `_create_schema` (`:202-210`): después de `create_all`, ejecutar el contenido de `000_schema_migrations.sql` y registrar las versiones `0..EXPECTED_SCHEMA_VERSION` leyendo los archivos de `backend/db/migrations/` con su `sha256` sobre bytes crudos, usando `ON CONFLICT (version) DO NOTHING` (D-6). No importar `scripts/migrar.py`.
- [ ] 3.2 Verificar que `_db_isolation` (`:282-298`) sigue armando el `TRUNCATE` desde `SQLModel.metadata.tables` y por lo tanto no toca `schema_migrations`. Agregar un comentario que lo diga y cite D84/RN-178.
- [ ] 3.3 Revisar `backend/tests/test_notify_isolate_executor_lifespan.py:44` y todo test que monkeypatchee `main_module.SQLModel.metadata.create_all` o el `engine` de `app.main`: deben seguir pasando con la guarda activa. Si alguno usa una base distinta de `fim_test` sin registro, registrarla en su fixture en lugar de desactivar la guarda.

## 4. Tests del backend

- [ ] 4.1 `backend/tests/test_schema_version.py` — test del árbol: `EXPECTED_SCHEMA_VERSION` es igual a la mayor versión de `backend/db/migrations/`, la numeración es contigua desde `000` sin duplicados y `000_schema_migrations.sql` existe. El mensaje de falla nombra la constante y el máximo del árbol.
- [ ] 4.2 Fixture de base efímera: con una conexión `AUTOCOMMIT` al servidor de test, `CREATE DATABASE fim_schema_<uuid>`, engine propio, y `DROP DATABASE … WITH (FORCE)` en el teardown aunque el test falle.
- [ ] 4.3 Test de `check_schema_version` sobre la base efímera: sin registro → `SchemaVersionError` con `found_version` nulo; registro hasta `EXPECTED_SCHEMA_VERSION - 1` → `SchemaVersionError`; registro hasta la esperada → devuelve la versión; registro hasta la esperada + 1 → no aborta. Verificar los campos del log `backend.schema_outdated` con la captura de logs que ya use la suite.
- [ ] 4.4 Test de arranque abortado: base efímera **sin tablas de aplicación** con registro hasta `EXPECTED_SCHEMA_VERSION - 1`; monkeypatchear `app.main.engine` al engine efímero; `with TestClient(app)` levanta la excepción de la guarda. Después, verificar sobre la base efímera que `agents` no existe (prueba que `create_all` no corrió) y que no se insertó ningún usuario.
- [ ] 4.5 Test de arranque exitoso: misma base efímera con registro hasta la esperada → el `lifespan` completa, `create_all` crea las tablas y `seed_admin` siembra el admin.
- [ ] 4.6 Test del arnés: tras un test que inserta filas, `schema_migrations` sigue conteniendo `0..EXPECTED_SCHEMA_VERSION` (escenario «El registro de esquema sobrevive al aislamiento por test»).

## 5. `scripts/migrar.py`

- [ ] 5.1 Crear `scripts/migrar.py` (ejecutable, `#!/usr/bin/env python3`, sólo biblioteca estándar en el modo por defecto) con docstring que cite D84/RN-178, describa los modos, los códigos de salida de D-5 y el procedimiento de instalación y de registro de una base existente.
- [ ] 5.2 Capa de árbol: `leer_arbol(directorio)` según D-4 (regex de nombre, duplicados, contigüidad desde `000`, `sha256` de bytes crudos). Error de árbol → código `2` sin conectarse a la base.
- [ ] 5.3 Capa de plan: `planificar(arbol, registro, hay_tablas_app, marcar_hasta, verificar)` como función pura que implementa la tabla de D-5, con el orden de verificación árbol → sha/archivo faltante → clasificación → pendientes. Errores tipados que mapean a los códigos `2`, `3` y `4`.
- [ ] 5.4 `EjecutorCompose`: arma `docker compose [-p] [-f]… exec -T <servicio> psql -X -q -v ON_ERROR_STOP=1 -U <usuario> -d <base>`; `consultar` agrega `-A -t -F '|' -c <sql>`; `transaccion` agrega `--single-transaction -f -` y pasa el SQL por stdin. Un código de salida distinto de cero de `psql` → código `1` con el stderr de `psql`.
- [ ] 5.5 `EjecutorDsn`: import diferido de `psycopg` con mensaje claro si falta; normaliza `postgresql+psycopg://`; `transaccion` dentro de `with conn.transaction():`.
- [ ] 5.6 Aplicación: cada acción `aplicar` llama una sola vez a `transaccion` con el contenido del archivo + el `INSERT` de su fila; cada acción `registrar` inserta sólo la fila. `000` siempre se aplica (no se registra sin ejecutar). Detenerse ante el primer fallo, nombrando el archivo.
- [ ] 5.7 CLI con `argparse`: `--marcar-hasta N`, `--verificar` (mutuamente excluyentes), `--dsn`, `-f/--compose-file` repetible, `-p/--project-name`, `--servicio` (default `db`), `--usuario` (default `fim`), `--base` (default `fim`), `--migraciones` (default `backend/db/migrations` relativo a la raíz del repo). Cada acción ejecutada se imprime en una línea; el resumen final dice versión inicial y final.

## 6. Tests de `scripts/migrar.py`

- [ ] 6.1 `scripts/tests/test_migrar.py` — árbol: hueco, duplicado, nombre inválido y ausencia de `000` producen código `2` sin invocar al ejecutor.
- [ ] 6.2 Plan con un ejecutor falso que registra llamadas: base nueva registra `1..N` sin ejecutar y aplica `000`; base nueva + `--marcar-hasta` es error de uso; base existente sin registro y sin bandera → código `3` sin acciones; `--marcar-hasta 22` registra sin ejecutar y no aplica posteriores; `N` mayor que el árbol se rechaza; dos pendientes se aplican en orden, una transacción cada una; hueco en el registro → código `3`.
- [ ] 6.3 Integridad: `sha256` discordante y versión registrada sin archivo → código `3` antes de cualquier acción, nombrando cada versión.
- [ ] 6.4 Fallo: el ejecutor falso falla en la segunda pendiente → la tercera no se intenta y el código es `1`.
- [ ] 6.5 `--verificar`: al día → `0`; pendientes → `4`; nunca llama a `transaccion`.
- [ ] 6.6 `EjecutorCompose`: test que fija la línea de comando exacta (`-T`, `-X`, `ON_ERROR_STOP=1`, `--single-transaction`, `-p`/`-f` en orden) parcheando `subprocess.run`.
- [ ] 6.7 Integración (`@pytest.mark.integration`, `--dsn` contra una base efímera del Postgres de test, con `psycopg` disponible): base nueva → registro `0..N` y ninguna tabla creada; una migración sintética que falla a mitad (en un directorio temporal) no deja fila ni cambio parcial; `--marcar-hasta` sobre una base con tablas no ejecuta SQL de las migraciones (verificable porque una migración sintética que fallaría si se ejecutara queda registrada).

## 7. Laboratorio, aceptación e imagen

- [ ] 7.1 `lab/corrida_unificada.sh:68-105`: reemplazar el bucle de `:76-79` por `python3 scripts/migrar.py` con los mismos `-f` que `DC` y, a continuación, `python3 scripts/migrar.py … --verificar`; un código distinto de cero en cualquiera → `say "ABORTA: …"` con la salida de `migrar.py`, y `exit 1`. Conservar la comparación de columnas (`:80-105`) y actualizar el comentario de `:69-75` para explicar que el registro prueba qué scripts corrieron y la comparación prueba que el modelo tiene script (D-8). No usar `--marcar-hasta` en el harness.
- [ ] 7.2 `lab/README.md`: documentar el paso único `python3 scripts/migrar.py -f … --marcar-hasta 22` sobre la base persistente del laboratorio antes de la primera corrida con `v5.0-tesis`, y que los tags anteriores a esta change no traen `migrar.py`.
- [ ] 7.3 `scripts/run-isolated-acceptance-lab.sh:94` y `scripts/run-us02-us20-us31-acceptance-lab.sh:127`: partir el `dc up` en `dc up -d --wait db`, `python3 scripts/migrar.py -p "$FIM_LAB_PROJECT" -f "$COMPOSE"` (con salida a la carpeta de evidencia) y el `up` del resto de los servicios. Un fallo de `migrar.py` aborta el script con el mismo patrón de error que ya usa.
- [ ] 7.4 Verificación manual del modo compose: contra una base de laboratorio con tablas y **sin registro**, correr `migrar.py --verificar`, `migrar.py --marcar-hasta 21`, `migrar.py` (aplica `022`, idempotente) y `migrar.py --verificar`; adjuntar la salida en la evidencia de apply. Confirmar con `docker compose ps` que 5432 no está publicado.
- [ ] 7.5 `backend/Dockerfile`: actualizar el comentario sobre `COPY … app/` (`:61-63`) para decir que `db/migrations/` no viaja en la imagen a propósito y que la versión esperada viaja como `EXPECTED_SCHEMA_VERSION` en `app/core/schema_version.py` (D84/RN-178). Sin cambios de instrucciones.

## 8. Documentación de instalación

- [ ] 8.1 `README.md` (`:389` y `:1128`, donde aparece `--profile app up -d`): insertar antes del primer arranque del backend `docker compose … up -d --wait db` + `python3 scripts/migrar.py -f … -f …`, y una subsección «Actualizar una instalación existente» con el Migration Plan del design (marcar, aplicar, verificar, reiniciar) y la recomendación de marcar hasta una versión menor ante la duda.
- [ ] 8.2 `docs/despliegue_servidor_remoto.md:146`: el mismo paso antes del `up -d --build`.
- [ ] 8.3 `scripts/README.md`: entrada para `migrar.py` con modos, flags y códigos de salida.

## 9. Cierre

- [ ] 9.1 Correr la suite de backend completa (`uv run pytest` desde `backend/`, con los servicios efímeros de `conftest.py:9-15`) y la de `scripts/tests/` (rápida e integración). Todas pasan.
- [ ] 9.2 Confirmar con `rg -n "create_all" backend/app` que el único llamado de producción sigue en el `lifespan`, ahora precedido por la guarda.
- [ ] 9.3 Correr `python3 scripts/check_spec_integrity.py`; pasa.
- [ ] 9.4 Revisar el Done de la Change 66 en `CHANGES.md` punto por punto contra la evidencia: base al día arranca (4.5), base con pendiente aborta con mensaje explícito (4.4), `--marcar-hasta` registra sin reaplicar (6.2, 6.7, 7.4), el preflight detecta el esquema atrasado (7.1, 7.4), suite de backend (9.1), integridad de specs (9.3).
