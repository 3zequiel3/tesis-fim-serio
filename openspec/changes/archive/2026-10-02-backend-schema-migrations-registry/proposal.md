## Why

El esquema de la base de datos no tiene versión. El arranque del backend sólo ejecuta
`SQLModel.metadata.create_all(engine)` (`backend/app/main.py:90`, dentro del `lifespan` de `:77-78`),
que crea las tablas ausentes pero **nunca agrega una columna a una tabla existente**. Las 22
migraciones manuales (`backend/db/migrations/001_add_agent_status_revoked.sql` a
`022_add_alert_channel_accepted_at.sql`) se aplican a mano con `psql` (convención D3) y nada registra
cuáles se aplicaron. El `Dockerfile` copia sólo `app/` (`backend/Dockerfile:63`), de modo que la
imagen tampoco sabe qué migraciones existen.

El resultado es que un backend puede arrancar contra una base atrasada y fallar en silencio. Así ocurrió
en la corrida inválida `v4-eval-20260923T190201Z-esquema-desactualizado`: el modelo traía la columna
de la migración `022`, la tabla no la tenía, todo `INSERT` sobre `alerts` falló, las baterías de
notificación reportaron cero entregas, y el drenaje de ingesta pareció **más rápido** porque el carril
de notificación no hacía trabajo. El arnés de laboratorio agregó después un parche
(`lab/corrida_unificada.sh:68-105`): reaplica todas las migraciones y compara columnas del modelo
contra `information_schema`. Ese parche existe sólo en el laboratorio; el producto sigue sin defensa.

Origen: guía de laboratorio de la tesis v29 (ítems L-2…L-9), verificada contra `devel` `b3751b8`.
La decisión que gobierna esta change está cerrada: **D84/RN-178** (`docs/reglas_de_negocio.md:2747`,
`docs/arquitectura_stack.md:2724`, ampliada en `1c308d5`). Es base del candidato `v5.0-tesis`; la
re-medición es única y se hace sobre ese candidato (ver Change 61). No se abre ninguna suposición
nueva.

## What Changes

- **Tabla `schema_migrations`** (`version`, `filename`, `sha256`, `applied_at`), creada por la
  migración nueva `backend/db/migrations/000_schema_migrations.sql`. No es un modelo SQLModel: la crea
  sólo la migración `000`, nunca `create_all`.
- **`scripts/migrar.py`**: aplica las migraciones pendientes en orden, **cada una en su propia
  transacción** junto con su fila de registro; se conecta por
  `docker compose exec -T db psql -v ON_ERROR_STOP=1` (sin exponer el puerto 5432), con `--dsn`
  opcional para conexión directa.
  - **Base nueva** (sin tablas de aplicación): registra hasta N **sin ejecutar** nada, y `create_all`
    construye la forma vigente en el primer arranque (D3 se conserva).
  - **Base existente sin registro**: `--marcar-hasta N` registra hasta N sin reaplicar.
  - **Integridad**: aborta si el `sha256` de una migración ya registrada no coincide con su archivo.
  - **Verificación de sólo lectura** (`--verificar`) para el preflight del laboratorio.
- **Versión esperada incrustada**: constante versionada `EXPECTED_SCHEMA_VERSION` en `backend/app/`,
  con un test que la iguala a la mayor migración del árbol. La imagen la lleva porque vive en `app/`.
- **Guarda de arranque** (**BREAKING** para el despliegue): el `lifespan` lee `max(version)` de
  `schema_migrations` **antes** de `create_all` y aborta, con un mensaje que nombra la versión
  encontrada, la esperada y el comando que la corrige, si la versión es menor o el registro no existe.
  Una instalación nueva tiene que correr `scripts/migrar.py` con `db` levantado y **antes** del primer
  arranque del backend.
- **Suite de backend**: el setup de sesión de `backend/tests/conftest.py` crea el registro y lo llena
  hasta la versión esperada, de modo que los tests que ejecutan el `lifespan` real sigan pasando.
- **Preflight del laboratorio**: el bloque de `lab/corrida_unificada.sh:68-105` deja de reaplicar las
  migraciones con un bucle de `psql` y pasa a `scripts/migrar.py` + lectura de `schema_migrations`.
  Los scripts que levantan un backend sobre una base nueva
  (`scripts/run-isolated-acceptance-lab.sh:94`, `scripts/run-us02-us20-us31-acceptance-lab.sh:127`)
  corren `migrar.py` entre `db` y `backend`.
- **Procedimiento de instalación**: el README y `docs/despliegue_servidor_remoto.md` agregan el paso
  `migrar.py` antes del primer `up` del backend, y el paso de registro de una base existente.

## Capabilities

### New Capabilities

- `backend-schema-migrations`: registro `schema_migrations`, herramienta `scripts/migrar.py` (orden,
  transacción por migración, base nueva, `--marcar-hasta`, verificación de `sha256`, `--verificar`,
  conexión por `docker compose exec` o `--dsn`), constante de versión esperada con su test, guarda de
  arranque y preflight del laboratorio. RN-178.

### Modified Capabilities

- `backend-core`: el requisito «Lifespan FastAPI ejecuta create_all + seed_admin idempotentes» agrega
  la verificación de versión de esquema **antes** de `create_all` y redefine el arranque sobre base
  vacía: ahora presupone el registro hecho por `migrar.py`.
- `backend-test-harness`: el requisito «Test harness owns schema, seeding, and isolation» agrega que el
  setup de sesión crea `schema_migrations` y registra la versión esperada, y que el `TRUNCATE` por test
  no lo toca.

## Impact

- **Código backend**: `backend/app/main.py` (`lifespan`), módulo nuevo en `backend/app/core/` con la
  constante y la guarda; `backend/db/migrations/000_schema_migrations.sql` (nuevo).
- **Scripts**: `scripts/migrar.py` (nuevo, sin dependencias fuera de la biblioteca estándar en el modo
  por defecto; `--dsn` importa `psycopg` de forma diferida), `scripts/README.md`, tests en
  `scripts/tests/`.
- **Laboratorio**: `lab/corrida_unificada.sh`, `scripts/run-isolated-acceptance-lab.sh`,
  `scripts/run-us02-us20-us31-acceptance-lab.sh`.
- **Imagen**: `backend/Dockerfile` no cambia de contenido; su comentario documenta por qué las
  migraciones no se copian y de dónde sale la versión esperada.
- **Despliegue**: toda base existente (lab, VPS) necesita una corrida única de
  `scripts/migrar.py --marcar-hasta 22` antes de desplegar esta versión del backend.
- **Change 62** (`agent-offline-reconcile-on-start`): su migración `023` se registra aquí. La que
  aterrice segunda sube `EXPECTED_SCHEMA_VERSION`; el test del árbol lo exige (ver design, D-7).
- **Dependencias**: ninguna nueva. `psycopg[binary]==3.2.4` (`backend/requirements.txt:7`) ya existe.
