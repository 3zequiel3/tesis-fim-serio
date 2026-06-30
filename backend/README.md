# FIM Platform — Backend

FastAPI 0.136 + SQLModel + structlog. Python 3.13.

## Cómo correr con Docker Compose

Requiere que los servicios de infra (`db`, `valkey`) estén corriendo.
Si es la primera vez, arrancar la infra primero:

```bash
docker compose up -d db valkey
```

Buildear y arrancar el backend:

```bash
docker compose --profile app build backend
docker compose --profile app up -d backend
```

Verificar que levantó:

```bash
docker compose ps                      # backend debe aparecer como running
curl -fsS http://localhost:8000/health # → {"status":"ok"}
```

Ver logs (cada línea es JSON estructurado con trace_id):

```bash
docker compose logs backend
```

## Cómo correr los tests

Los tests corren contra un PostgreSQL 18.3 y un Valkey 9.0.3 efímeros.
Levantar los servicios de backing antes de ejecutar la suite:

```bash
# Postgres efímero (base fim_test, usuario fim, password test)
docker run --rm -d --name fim-test-db \
  -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fim_test \
  -p 5432:5432 postgres:18.3

# Valkey efímero
docker run --rm -d --name fim-test-valkey -p 6379:6379 valkey/valkey:9.0.3
```

Desde el directorio `backend/`:

```bash
# Instalar dependencias de desarrollo (uv recomendado)
uv pip install -r requirements-dev.txt

# Correr la suite completa
uv run pytest
```

El conftest root (`backend/tests/conftest.py`) crea el schema y siembra el admin
exactamente una vez por sesión, y aísla cada test mediante `TRUNCATE ... RESTART
IDENTITY CASCADE` + reseed antes de cada test. No es necesario pre-sembrar la base.

Para un reset completo entre runs:

```bash
docker exec fim-test-db psql -U fim -d postgres \
  -c "DROP DATABASE IF EXISTS fim_test WITH (FORCE);" \
  -c "CREATE DATABASE fim_test;"
docker exec fim-test-valkey valkey-cli flushall
```

## Layout de directorios

```
backend/
├── app/
│   ├── main.py                # Entry point: lifespan, middlewares, /health
│   ├── core/
│   │   ├── config.py          # pydantic-settings (Settings)
│   │   ├── database.py        # engine SQLModel + get_session()
│   │   ├── logging.py         # configure_logging(), sanitize_secrets processor
│   │   └── middleware/
│   │       ├── trace_id.py    # TraceIdMiddleware (ASGI, UUID v4 por request)
│   │       └── sanitize_logs.py  # Wrapper documental (processor real en logging.py)
│   └── modules/               # Placeholder para módulos de dominio (Change 03+)
├── tests/
│   ├── conftest.py            # Fixture client (httpx ASGI)
│   ├── test_health.py         # GET /health → 200, X-Trace-Id
│   ├── test_logging_sanitize.py  # Sanitización de secrets
│   └── test_logging_trace_id.py  # trace_id en contexto structlog
├── Dockerfile                 # Multi-stage, usuario no-root app (uid 10001)
├── requirements.txt           # Dependencias runtime pinneadas
├── requirements-dev.txt       # Dependencias de desarrollo/test
└── pyproject.toml             # Configuración pytest + ruff + mypy
```

## Notas M1

- **`seed_admin.skipped`**: Al arrancar en M1 (antes de Change 03/04), los logs
  muestran `event=seed_admin.skipped reason=users_table_not_yet_created`.
  Esto es **esperado** y no indica un error. La tabla `users` se crea en
  Change 03 (`domain-models`) y el cuerpo de `seed_admin` se completa en
  Change 04 (`backend-auth`).

- **Puerto 8443**: Declarado en compose para mTLS (Change 06), pero no hay
  servidor escuchando ahí hasta que Change 06 (`agent-mtls-bootstrap`) esté
  implementado.

## Variables de entorno requeridas

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `DATABASE_URL` | Sí | URL PostgreSQL (format: `postgresql+psycopg://...`) |
| `VALKEY_URL` | Sí | URL Valkey (format: `valkey://...`) |
| `JWT_SECRET_CURRENT` | No (M1) | Secret JWT actual (requerido en Change 04) |
| `JWT_SECRET_PREVIOUS` | No (M1) | Secret JWT anterior (requerido en Change 04) |
| `ADMIN_USERNAME` | No (M1) | Username del admin inicial (requerido en Change 04) |
| `ADMIN_PASSWORD` | No (M1) | Password del admin inicial (requerido en Change 04) |
| `CA_CERT_PATH` | No (M1) | Path al certificado CA (requerido en Change 06) |
| `CA_KEY_PATH` | No (M1) | Path a la clave CA (requerido en Change 06) |
| `ENVIRONMENT` | No | `dev` / `prod` (default: `dev`) |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING` (default: `INFO`) |
