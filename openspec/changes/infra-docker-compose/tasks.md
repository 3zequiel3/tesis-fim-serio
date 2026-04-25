# Tasks — infra-docker-compose

## 1. Preparación del repo

- [x] 1.1 Verificar que la raíz del repo NO tenga ya un `docker-compose.yml`, un `.env.example` ni un directorio `db/init/` (debe estar todo limpio)
- [x] 1.2 Crear el directorio `db/init/` en la raíz del repo

## 2. Script SQL de inicialización (RN-67, D-02)

- [x] 2.1 Crear `db/init/01-create-databases.sql` con:
  - `CREATE DATABASE fim_n8n` como sentencia plana (la base `fim` ya la crea la imagen vía `POSTGRES_DB=fim` antes de que corra este script; `CREATE DATABASE` NO puede ir dentro de `DO $$ … $$` porque PostgreSQL lo prohíbe en funciones/transacciones)
  - `GRANT ALL PRIVILEGES ON DATABASE fim_n8n TO fim` (el ownership ya queda en `fim` porque es quien ejecuta el script — el GRANT explícito protege contra rotación futura de owner)
  - Comentarios SQL explicando RN-67, D-03 y la razón técnica de no usar `DO`/dblink
- [x] 2.2 Confirmar que el archivo es UTF-8, LF endings, sin BOM

## 3. `.env.example` (D-07)

- [x] 3.1 Crear `.env.example` en la raíz con encabezado explicativo
- [x] 3.2 Agregar `DB_PASSWORD` con comentario (uso, formato, generación con `openssl rand -base64 24`, change que la consume)
- [x] 3.3 Agregar `JWT_SECRET_CURRENT` y `JWT_SECRET_PREVIOUS` con comentario (HS256 ≥32 bytes hex, primer deploy puede dejar PREVIOUS vacío, Change 02 las usa)
- [x] 3.4 Agregar `ADMIN_USERNAME` y `ADMIN_PASSWORD` con comentario (D3, seed del primer admin desde el lifespan del backend, password forzada a cambiar en primer login)
- [x] 3.5 Agregar `CA_CERT_PATH=/certs/ca.pem` y `CA_KEY_PATH=/certs/ca-key.pem` con comentario (RN-78, Change 04 las puebla)
- [x] 3.6 Verificar que el archivo termina en newline

## 4. `.gitignore` (D-07)

- [x] 4.1 Verificar el contenido actual del `.gitignore` en la raíz
- [x] 4.2 Agregar la entrada `.env` si no está presente (evitar duplicados)
- [x] 4.3 Confirmar que `.env.example` NO está en `.gitignore`

## 5. `docker-compose.yml` — esqueleto y servicios infra (D-04, D-05, D-06)

- [x] 5.1 Crear `docker-compose.yml` en la raíz, sin `version:` declarado (Compose v2)
- [x] 5.2 Declarar la red `fim_internal` (driver bridge, default)
- [x] 5.3 Declarar volúmenes nombrados: `pg_data`, `n8n_data`, `backend_certs`
- [x] 5.4 Servicio `db`:
  - `image: postgres:18.3`
  - `restart: unless-stopped`
  - `environment`: `POSTGRES_DB=fim`, `POSTGRES_USER=fim`, `POSTGRES_PASSWORD=${DB_PASSWORD}`
  - `volumes`: `pg_data:/var/lib/postgresql/data`, `./db/init:/docker-entrypoint-initdb.d:ro`
  - `networks`: `[fim_internal]`
  - `healthcheck`: `pg_isready -U fim -d fim`, interval 5s, timeout 3s, retries 5, start_period 10s
  - SIN `ports:` mapeados al host
- [x] 5.5 Servicio `valkey`:
  - `image: valkey/valkey:9.0.3`
  - `restart: unless-stopped`
  - `volumes`: `valkey_data:/data` (agregar `valkey_data` a la lista de volúmenes nombrados en 5.3)
  - `networks`: `[fim_internal]`
  - `healthcheck`: `valkey-cli ping`, interval 5s, timeout 3s, retries 5, start_period 5s
  - SIN `ports:`
- [x] 5.6 Servicio `n8n`:
  - `image: n8nio/n8n:2.16.1`
  - `restart: unless-stopped`
  - `depends_on`: `db: { condition: service_healthy }`
  - `environment`: `DB_TYPE=postgresdb`, `DB_POSTGRESDB_HOST=db`, `DB_POSTGRESDB_PORT=5432`, `DB_POSTGRESDB_DATABASE=fim_n8n`, `DB_POSTGRESDB_USER=fim`, `DB_POSTGRESDB_PASSWORD=${DB_PASSWORD}`, `N8N_RUNNERS_ENABLED=true`
  - `volumes`: `n8n_data:/home/node/.n8n`
  - `networks`: `[fim_internal]`
  - SIN `ports:` mapeados al host

## 6. `docker-compose.yml` — placeholders backend y frontend (D-05)

- [x] 6.1 Servicio `backend` con `profiles: ["app"]`:
  - `build: ./backend` (directorio aún no existe; el profile evita que se buildee por defecto)
  - `image: fim-backend:dev`
  - `restart: unless-stopped`
  - `depends_on`: `db: { condition: service_healthy }`, `valkey: { condition: service_healthy }`
  - `environment`: `DATABASE_URL=postgresql+psycopg://fim:${DB_PASSWORD}@db:5432/fim`, `VALKEY_URL=valkey://valkey:6379`, `JWT_SECRET_CURRENT=${JWT_SECRET_CURRENT}`, `JWT_SECRET_PREVIOUS=${JWT_SECRET_PREVIOUS}`, `ADMIN_USERNAME=${ADMIN_USERNAME}`, `ADMIN_PASSWORD=${ADMIN_PASSWORD}`, `CA_CERT_PATH=${CA_CERT_PATH}`, `CA_KEY_PATH=${CA_KEY_PATH}`
  - `volumes`: `backend_certs:/certs:ro`
  - `ports`: `["8443:8443", "8000:8000"]` (RN-78 + API)
  - `networks`: `[fim_internal]`
  - `deploy: { replicas: 1 }` (RN-76)
- [x] 6.2 Servicio `frontend` con `profiles: ["app"]`:
  - `build: ./frontend`
  - `image: fim-frontend:dev`
  - `restart: unless-stopped`
  - `depends_on`: `[backend]`
  - `networks`: `[fim_internal]`
  - SIN `ports:` por ahora (Change 14 lo define)

## 7. Validación sintáctica del compose

- [x] 7.1 Ejecutar `docker compose config` con un `.env` derivado de `.env.example` (rellenar `DB_PASSWORD` con un valor de ejemplo) y verificar exit 0 sin warnings de variables faltantes
- [x] 7.2 Verificar que el output renderizado contiene los servicios `db`, `valkey`, `backend`, `frontend`, `n8n` y NO contiene `db-init`
- [x] 7.3 Verificar que aparecen las cadenas exactas `postgres:18.3`, `valkey/valkey:9.0.3` y `n8nio/n8n:2.16.1`

## 8. Smoke test del Done criterion

- [ ] 8.1 `docker compose up -d db valkey n8n` — verificar exit 0
- [ ] 8.2 Esperar healthchecks: `docker compose ps` debe mostrar `db` y `valkey` con estado `healthy`
- [ ] 8.3 `docker compose exec db psql -U fim -c "\l"` — verificar que la salida lista `fim` y `fim_n8n`, ambas con owner `fim`
- [ ] 8.4 Inspeccionar `docker compose logs db valkey n8n` y confirmar que NO hay errores fatales ni tracebacks
- [ ] 8.5 Confirmar que n8n migra su schema en `fim_n8n` sin errores de permisos (`docker compose logs n8n` muestra migraciones internas OK; `docker compose exec db psql -U fim -d fim_n8n -c "\dt"` lista tablas creadas por n8n)
- [ ] 8.6 `docker compose down` para dejar la máquina limpia (sin `-v`, mantenemos los volúmenes para no rehacer la inicialización en la próxima)

## 9. Cierre del change

- [x] 9.1 `git status` y revisar que solo se hayan creado/modificado: `docker-compose.yml`, `db/init/01-create-databases.sql`, `.env.example`, `.gitignore`
- [x] 9.2 Stage de los archivos relevantes
- [x] 9.3 Commit con mensaje convencional: `feat(infra): docker compose con db, valkey, n8n y placeholders backend/frontend`
- [x] 9.4 No incluir atribución a IA ni "Co-Authored-By"
- [ ] 9.5 (Opcional, si el operador quiere) `openspec status --change infra-docker-compose` debe mostrar todos los artefactos como `done` y el change como listo para `/opsx:apply`
