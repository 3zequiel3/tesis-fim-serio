# Design — infra-docker-compose

## Context

Este es el primer change ejecutable del proyecto FIM Platform. El repositorio tiene la documentación canónica completa (`docs/`, `CHANGES.md`) pero los directorios `backend/`, `agent/` y `frontend/` están vacíos. El servidor central de la plataforma corre en Docker Compose; el agente FIM se despliega nativo con systemd y NO entra acá (RN-68, RN-108).

El compose de referencia que aparece en `docs/arquitectura_stack.md §Docker Compose` (líneas 1474-1554) corresponde a la versión PRE-D3: incluye un servicio `db-init` que ejecuta migraciones y seed del primer admin. La decisión D3 (appendix "Decisiones de implementación — Abril 2026", líneas 1996-2011) elimina ese servicio: el lifespan de FastAPI ejecuta `SQLModel.metadata.create_all()` y `seed_admin()` directamente. Como los appendices PREVALECEN sobre el contenido previo (regla del proyecto en `CLAUDE.md`), este change implementa la versión D3.

Restricciones que vienen de los docs canónicos:
- **Stack pinneado** (arquitectura_stack §Stack y tabla de tecnologías): PostgreSQL 18.3, Valkey 9.0.3, n8n 2.16.1, Python 3.13.
- **Una instancia de PostgreSQL, dos bases** (RN-67): `fim` y `fim_n8n`.
- **Backend single-instance** (RN-76, C4): `replicas: 1`. No hay HA en M1-M4.
- **mTLS para agentes** (RN-78): el backend expondrá `8443` para conexiones de agentes; los certificados los emite la CA propia que Change 04 implementa. Hoy solo dejamos los paths declarados.
- **Léxico canónico** (RN-71): nombres de servicios, redes, volúmenes y variables en minúsculas snake_case o kebab donde corresponda al ecosistema (ej. variables de entorno en MAYÚSCULAS porque es la convención de shell/Docker).

Stakeholders: yo (desarrollador, único operador en M1-M2). El criterio de éxito viene fijo de `CHANGES.md` línea 87.

## Goals / Non-Goals

**Goals:**
- Dejar funcionando `db`, `valkey` y `n8n` con `docker compose up`, sin errores y con healthchecks verdes.
- Crear las bases `fim` y `fim_n8n` automáticamente en el primer arranque mediante `docker-entrypoint-initdb.d/`.
- Documentar todas las variables de entorno en `.env.example` con un comentario por variable que indique propósito y change donde se empieza a usar (para que cuando Change 02-04 las consuman no haya ambigüedad).
- Dejar declarados los servicios `backend` y `frontend` como placeholders compatibles con `docker compose config`, de modo que el grafo de servicios y dependencias quede listo para Change 02 sin reescribir el compose desde cero.
- Cumplir literalmente el Done criterion: `docker compose up db valkey n8n` arranca limpio + `psql -c "\l"` muestra las dos bases.

**Non-Goals:**
- Implementar el backend, frontend o agente. Eso es Change 02 en adelante.
- Configurar la CA propia ni emitir certificados mTLS. Es Change 04 (RN-78). Acá solo declaramos el volumen `backend_certs` y las variables `CA_CERT_PATH` / `CA_KEY_PATH` para que el contrato de paths quede fijo.
- Configurar workflows de n8n (templates de notificación, webhooks). Eso es Change 13 (`integration-n8n-notifications`).
- HTTPS para el frontend, headers de seguridad CSP/HSTS, reverse proxy, hardening de imágenes, escaneo de vulnerabilidades. Hitos posteriores.
- CI/CD, GitHub Actions, deploy a cloud. Tesis local.
- Migraciones versionadas tipo Alembic. D3 documenta el trigger explícito para introducirlas más adelante.
- Producir un `.env` real con secretos. Solo `.env.example`.

## Decisions

### D-01: Sin servicio `db-init` (aplicación directa de D3)

El compose canónico de la doc principal incluye `db-init` como init-container. Lo eliminamos siguiendo D3.

**Por qué**: backend single-instance (RN-76), no hay race condition, `create_all()` y `seed_admin()` son idempotentes, una imagen menos de mantener, una variable menos duplicada (el password admin solo lo ve el backend en su propio entorno). El lifespan de FastAPI lo resuelve en Change 02.

**Alternativa rechazada**: mantener `db-init` "por si las dudas". Rechazada porque el appendix D3 ya cerró la decisión y agregar complejidad operativa preventiva contradice la motivación documentada.

### D-02: Inicialización de bases vía `/docker-entrypoint-initdb.d/`

Las dos bases (`fim`, `fim_n8n`) se crean con un script SQL montado read-only en `/docker-entrypoint-initdb.d/`. La imagen oficial de PostgreSQL ejecuta automáticamente todo `*.sh`, `*.sql` y `*.sql.gz` que encuentra ahí en orden alfabético, **solo en el primer arranque** (cuando el data directory está vacío).

**Por qué**: es el mecanismo nativo, no requiere imagen adicional, no compite con el approach D3, y la idempotencia la garantiza la imagen oficial (no re-ejecuta si ya hay datos). Compatible con `POSTGRES_DB=fim` que la imagen también respeta.

**Detalle**: `POSTGRES_DB: fim` crea `fim` automáticamente y deja al usuario `fim` como owner. El script SQL solo necesita crear `fim_n8n` y darle privilegios al usuario `fim`. El script usa `CREATE DATABASE fim_n8n` como sentencia plana (NO dentro de `DO $$ … $$` ni de transacción) — PostgreSQL prohíbe ejecutar `CREATE DATABASE` desde una función o transaction block, y el comportamiento del init dir (correr una sola vez con `pg_data` vacío) hace innecesarias las protecciones idempotentes. Tampoco usamos `dblink_exec` porque la extensión `dblink` no está cargada por defecto en la imagen oficial.

**Alternativa rechazada (originalmente propuesta)**: bloque `DO` defensivo que verifica `pg_database` antes de crear `fim` y `fim_n8n` para que el script fuera autocontenido si se desactivaba `POSTGRES_DB`. Rechazada por dos razones técnicas duras: (1) `CREATE DATABASE` no puede correr dentro de `DO`/función — falla con `ERROR: CREATE DATABASE cannot be executed from a function`; (2) `dblink_exec` (la salida típica para sortear lo anterior) requiere `CREATE EXTENSION dblink`, que la imagen oficial no precarga. Dejar `POSTGRES_DB=fim` fijo y crear solo `fim_n8n` es la versión que efectivamente funciona en `postgres:18.3`.

**Alternativa rechazada**: invocar `psql` desde otro contenedor (`db-init` revivido). Choca con D-01.

### D-03: Usuario PostgreSQL único (`fim`) con privilegios sobre ambas bases

No creo un usuario adicional para n8n. El usuario `fim` es owner de `fim` y de `fim_n8n`.

**Por qué**: la separación que pide RN-67 es **a nivel de base** (que n8n no comparta tablas con la app), no a nivel de usuario. Crear un segundo usuario añade gestión de credenciales y rotación sin un beneficio de seguridad relevante en un deployment single-host single-tenant. El servidor PostgreSQL no está expuesto al host (`fim_internal` interna), así que el blast radius de una credencial comprometida es el mismo.

**Alternativa considerada**: crear usuario `n8n` con privilegios solo sobre `fim_n8n`. Rechazada por costo/beneficio en M1; queda anotada como mejora futura si en M4 se decide endurecer.

**Trigger para revisar**: si en algún momento se expone n8n a internet o se permite acceso de terceros, hay que separar usuarios. Hoy n8n solo recibe webhooks del backend en la red interna.

### D-04: Red interna `fim_internal`, sin puertos expuestos al host salvo backend (futuro)

Defino una red `fim_internal` (driver `bridge`, default). Todos los servicios la usan. Ningún servicio expone puertos al host **excepto** el `backend`, que cuando exista (Change 02) publicará `8000` (API) y `8443` (mTLS agentes, RN-78). El frontend cuando exista (Change 14) publicará el `80` o `3000` que decida ese change — hoy lo dejo sin `ports:` para evitar premature binding.

**Por qué**: superficie de ataque mínima. Ni `db`, ni `valkey`, ni `n8n` necesitan ser accesibles desde el host del operador para uso normal. Para debugging puntual existe `docker compose exec` o `docker compose run --rm --service-ports …`. RN-76 (single-instance) y RN-78 (mTLS único punto de entrada) refuerzan que el frente público es solamente el backend.

**Alternativa rechazada**: exponer `5432` y `6379` a localhost en dev. Crea hábitos malos (clientes locales conectándose directo y saltándose la app), y choca con la idea de que el agente FIM en su propia máquina dev se conecte a Valkey por mTLS pasando por el backend, no por TCP plano.

### D-05: Servicios `backend` y `frontend` como placeholders compatibles con `docker compose config`

`backend` y `frontend` aparecen en el compose con bloques mínimos: build context apuntando a `./backend` y `./frontend` respectivamente (directorios que hoy no tienen Dockerfile), `image:` con un tag local que se construirá cuando el Dockerfile exista, y la directiva `profiles: ["app"]` para que NO arranquen con `docker compose up` por defecto.

**Por qué**: el smoke test del Done criterion es `docker compose up db valkey n8n` (servicios explícitos), no `docker compose up` global. Los profiles aseguran que `docker compose up` global tampoco intente buildearlos hasta que existan Dockerfiles. Al mismo tiempo, declarar el bloque ahora me deja fijar el contrato (dependencias, env vars, volúmenes, puertos) y evito que cada change posterior tenga que tocar el grafo del compose.

**Alternativa rechazada**: omitir `backend` y `frontend` del compose hasta que tengan código. Rechazada porque obliga a Change 02 y Change 14 a reintroducirlos, lo que duplica trabajo y genera diffs cruzados.

### D-06: Versiones pinneadas estrictamente (sin `latest`)

`postgres:18.3`, `valkey/valkey:9.0.3`, `n8nio/n8n:2.16.1`. Reproducibilidad estricta es lo que la tesis necesita.

**Por qué**: `latest` rompe reproducibilidad y los tribunales académicos legítimamente piden poder reproducir la corrida. Las versiones están explícitas en `arquitectura_stack.md §Stack`.

**Trade-off**: actualizaciones de seguridad requieren bump explícito de versión (no `docker compose pull` mágico). Es deseable: cualquier cambio de versión es revisable en git.

### D-07: `.env.example` documentado, `.env` ignorado

Cada variable en `.env.example` lleva un comentario sobre qué hace, qué formato, en qué change empieza a usarse. Listo todas las variables que aparecen en el compose, aunque en este change solo `DB_PASSWORD` se consume realmente (las otras están en bloques placeholder). Esto evita que cuando Change 02 las necesite haya que adivinar.

**Variables incluidas**:
- `DB_PASSWORD` — password del usuario PostgreSQL `fim`. Usado por `db`, `n8n` (y `backend` cuando exista). Mín. 16 chars, generar con `openssl rand -base64 24`.
- `JWT_SECRET_CURRENT` — secret HS256 actual del backend. Usado en Change 02 (`backend-core-scaffold`) cuando se implemente JWT. ≥32 bytes hex.
- `JWT_SECRET_PREVIOUS` — secret previo durante rotación; vacío en primer deploy. Documentado como opcional. Usado en Change 02.
- `ADMIN_USERNAME` — username del primer admin que el lifespan de FastAPI seedea (D3). Default sugerido `admin`.
- `ADMIN_PASSWORD` — password inicial del primer admin. Forzado a cambiar en primer login (HU del módulo auth, M1).
- `CA_CERT_PATH` / `CA_KEY_PATH` — paths dentro del contenedor backend a la CA propia (Change 04, RN-78). Default `/certs/ca.pem` y `/certs/ca-key.pem`. El volumen `backend_certs` los respaldará.

**`.gitignore`**: agregar `.env`. Mantener `.env.example` versionado.

### D-08: Healthchecks de `db` y `valkey`

`db`: `pg_isready -U fim -d fim`, intervalo 5s, timeout 3s, retries 5, start_period 10s. `valkey`: `valkey-cli ping`, intervalo 5s, timeout 3s, retries 5, start_period 5s.

**Por qué**: Change 02 va a usar `depends_on: db: condition: service_healthy` para que el lifespan de FastAPI no haga `create_all` antes de que PostgreSQL acepte conexiones. Definir los healthchecks acá evita modificar el compose otra vez después.

**n8n**: la imagen oficial trae su propio HEALTHCHECK en el Dockerfile. No agrego uno extra.

### D-09: Volúmenes — `pg_data`, `n8n_data`, `backend_certs`

Tres volúmenes nombrados:
- `pg_data` → `/var/lib/postgresql/data` en `db`. Persistencia de la base.
- `n8n_data` → `/home/node/.n8n` en `n8n`. Persistencia de credentials/workflows de n8n.
- `backend_certs` → `/certs` en `backend` (cuando exista). Hoy el volumen se declara pero no se usa.

`db/init/` se monta como **bind mount read-only** (`./db/init:/docker-entrypoint-initdb.d:ro`), no como volumen nombrado, porque es código versionado en el repo.

### D-10: Layout de directorios nuevos

```
.
├── docker-compose.yml
├── .env.example
├── .gitignore                  (modificado)
└── db/
    └── init/
        └── 01-create-databases.sql
```

`backend/` y `frontend/` NO se crean como directorios en este change (están vacíos hoy y los van a poblar Change 02 y Change 14 con sus propios Dockerfiles). Si la falta de `./backend` y `./frontend` rompiera `docker compose config`, mitigo con `profiles: ["app"]` (ver D-05).

## Risks / Trade-offs

- **[Riesgo] El compose declara `build: ./backend` que no existe** → mitigación: D-05 con `profiles: ["app"]`. El Done criterion explícito es `docker compose up db valkey n8n`, así que el build de placeholders nunca se dispara en este change. Si `docker compose config` complain igual, fallback es comentar el bloque `build:` y dejar solo `image: fim-backend:dev` referenciado.
- **[Riesgo] El usuario `fim` es owner de `fim_n8n` (D-03), n8n podría modificar tablas de la base de la app si se confunde de DSN** → mitigación: las bases están separadas físicamente (RN-67), n8n recibe `DB_POSTGRESDB_DATABASE: fim_n8n` explícito. Configuración pinneada en compose, no llega vía UI de n8n.
- **[Riesgo] Pinning estricto de versiones genera deuda de actualización** → mitigación: aceptado. Las actualizaciones se proponen como changes propios (`infra-bump-versions-…`) en M3/M4 si hay CVEs.
- **[Riesgo] Sin reverse proxy ni TLS para n8n** → mitigación: n8n no se expone al host (D-04). El backend lo consume por nombre interno. Cuando Change 13 implemente las llamadas backend → n8n, evaluamos si hace falta TLS interno (probablemente no, red interna controlada).
- **[Riesgo] El `pg_data` quedó inicializado con un set de credenciales y luego se rota `DB_PASSWORD` en `.env`** → la imagen oficial NO re-ejecuta los scripts ni cambia la password automáticamente. Mitigación: documentar en `.env.example` que cambiar `DB_PASSWORD` después del primer arranque requiere `ALTER USER fim WITH PASSWORD …` manualmente. Trade-off aceptado.
- **[Riesgo] `backend_certs` queda vacío y rompe el bind del backend cuando se construya** → mitigación: D-09 declara el volumen como named volume, Docker lo crea vacío sin error. Change 04 lo poblará. Si en Change 02 (que precede a Change 04) se necesita arrancar el backend, el lifespan no requiere certs (mTLS sólo se usa con agentes, que aún no existen).
- **[Trade-off] Sin segundo usuario PostgreSQL** → ver D-03. Aceptado en M1, revisable.

## Migration Plan

No hay migración: es la primera infra del proyecto, repo limpio.

**Procedimiento de aplicación**:
1. Operador clona el repo.
2. `cp .env.example .env` y rellena `DB_PASSWORD`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`. Las JWT y paths CA pueden quedar con valores placeholder (no los lee nadie en este change).
3. `docker compose up -d db valkey n8n`.
4. `docker compose exec db psql -U fim -c "\l"` → debe listar `fim` y `fim_n8n`.

**Rollback**:
1. `docker compose down -v` (destruye volúmenes y red).
2. `git revert` del commit del change.

**Re-correrlo**: borrar `pg_data` (`docker volume rm <proyecto>_pg_data`) y volver a hacer `docker compose up -d db`. Las bases se recrean desde el script.

## Open Questions

Ninguna pendiente para este change. Todo lo necesario está cerrado en los appendices D1-D8 de los docs canónicos.

Anotaciones para revisar en changes futuros (NO bloquean este change):
- Change 02 confirmará que el lifespan de FastAPI hace `create_all` + `seed_admin` correctamente con `depends_on: db: condition: service_healthy`.
- Change 04 emitirá la CA propia y los certs del backend, poblando `backend_certs`.
- Change 13 definirá si se necesitan workflows de n8n versionados en el repo (export/import) o solo runtime.
