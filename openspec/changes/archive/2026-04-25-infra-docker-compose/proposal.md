# infra-docker-compose

## Why

La FIM Platform necesita una base operativa reproducible antes de poder escribir una sola línea del backend, agente o frontend. Hoy `backend/`, `agent/` y `frontend/` están vacíos y no existe forma de levantar PostgreSQL, Valkey ni n8n localmente. Este es el Change 01 del roadmap (Hito M1) y no tiene dependencias: establece la infraestructura sobre la que corre todo lo demás (RN-67, RN-76, RN-78). Sin esta base, ningún feature posterior puede testearse end-to-end ni cumplir el criterio de aceptación de M1 ("el servidor central arranca con `docker compose up`").

## What Changes

- Nuevo `docker-compose.yml` en la raíz con cinco servicios: `db` (PostgreSQL 18.3), `valkey` (Valkey 9.0.3), `backend` (placeholder, build context vacío para que el target exista en el grafo de Compose), `frontend` (placeholder análogo), `n8n` (n8nio/n8n:2.16.1).
- **Sin servicio `db-init`** — D3 (appendix de implementación) elimina el init-container; el lifespan de FastAPI ejecutará `create_all` + `seed_admin` en Change 02. El compose canónico que aparece en `arquitectura_stack.md §Docker Compose` (líneas 1474-1554) corresponde a la versión PRE-D3 y queda superado por este change.
- Script SQL `db/init/01-create-databases.sql` montado en `/docker-entrypoint-initdb.d/` que crea las dos bases requeridas por RN-67 (`fim` y `fim_n8n`) con permisos restringidos al usuario aplicativo `fim`.
- `.env.example` en la raíz con todas las variables que el compose lee documentadas (qué hace cada una, qué formato espera, en qué change se empieza a usar): `DB_PASSWORD`, `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CA_CERT_PATH`, `CA_KEY_PATH`. Las variables JWT/ADMIN/CA quedan declaradas aunque el backend todavía no exista, para que `docker compose config` valide en seco y para evitar drift entre changes.
- Red interna Docker dedicada (`fim_internal`) por la que se comunican los servicios; ningún puerto de `db`, `valkey` ni `n8n` expuesto al host. El backend quedará declarado con los puertos `8443` (mTLS para agentes, RN-78) y `8000` (API/frontend) cuando se construya en Change 02; en este change el servicio backend está como placeholder sin imagen activa.
- Volúmenes nombrados: `pg_data` (persistencia PostgreSQL), `n8n_data` (workflows n8n), `backend_certs` (placeholder donde Change 04 montará la CA, RN-78).
- Healthchecks para `db` y `valkey` (necesarios para que `depends_on … condition: service_healthy` funcione cuando el backend exista).
- `.gitignore`: agregar `.env` (el `.env.example` se commitea, el real no).

## Capabilities

### New Capabilities

- `infra-compose`: orquestación local de los servicios del servidor central (db, valkey, n8n + placeholders de backend/frontend), incluida la inicialización de las dos bases PostgreSQL (`fim`, `fim_n8n`) y la red interna donde se comunican.

### Modified Capabilities

<!-- Ninguno: este es el primer change del proyecto, no hay specs previos en openspec/specs/. -->

## Impact

- **Archivos nuevos**: `docker-compose.yml`, `db/init/01-create-databases.sql`, `.env.example`, `db/init/.gitkeep` (si quedara vacío en algún momento del flujo).
- **Archivos modificados**: `.gitignore` (agregar `.env`).
- **Dependencias externas**: imágenes `postgres:18.3`, `valkey/valkey:9.0.3`, `n8nio/n8n:2.16.1` (versiones pinneadas al stack declarado en `arquitectura_stack.md §Stack`).
- **Cambios de comportamiento**: ninguno todavía — no hay aplicación corriendo. Habilita el resto del roadmap.
- **Reglas de negocio cubiertas**: RN-67 (dos DBs en el mismo PostgreSQL), RN-76 (single-instance: `deploy.replicas: 1` declarado para backend cuando exista), RN-78 (preparación de paths de CA propia para el bootstrap mTLS, sin emitir certificados todavía — eso es Change 04).
- **Decisiones aplicadas**: D3 (no hay `db-init` container; el seed lo hará el lifespan de FastAPI en Change 02).
- **Aguas abajo**: desbloquea Change 02 (`backend-core-scaffold`), que necesita la DB `fim` lista y la conexión a Valkey resuelta por nombre de servicio (`db`, `valkey`).
