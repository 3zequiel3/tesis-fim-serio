## Why

El Change 01 (`infra-docker-compose`) dejó al servicio `backend` declarado como placeholder en `docker-compose.yml` con `profiles: ["app"]`, pero el directorio `backend/` está vacío (solo `.gitkeep`) y `docker compose --profile app build backend` falla porque no existe Dockerfile ni código Python. Sin un esqueleto funcional de backend no se puede avanzar a Change 03 (modelos), Change 04 (auth) ni a ningún feature posterior.

Este change le da contenido al placeholder: crea la estructura de paquete Python, fija dependencias, instala los **controles cross-cutting desde el día 1** que exige D7 (logging JSON sanitizado + `trace_id` por request) y deja un endpoint mínimo `GET /health` que prueba que la app levanta y atiende. Hacer esto ahora — antes de que aparezcan endpoints con secrets o usuarios — evita el riesgo concreto de filtrar `password`/`token` en logs durante toda la ventana de los changes 03–04 y de tener que retro-ajustar el logging cuando el ruido ya está en producción local.

## What Changes

- Crear estructura `backend/app/{core,modules}/` con `__init__.py` por paquete; `modules/` queda vacío (placeholder para Change 03+).
- `backend/app/core/config.py` con `Settings` (pydantic-settings) que lee `.env` y mapea las variables que el compose ya inyecta (`DATABASE_URL`, `VALKEY_URL`, `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CA_CERT_PATH`, `CA_KEY_PATH`).
- `backend/app/core/database.py` con `engine` SQLModel y dependency `get_session()` (Unit of Work por request).
- `backend/app/core/logging.py` con `configure_logging()` (structlog → JSON), processor `sanitize_secrets` y processor `inject_trace_id` que lee del `ContextVar`.
- `backend/app/core/middleware/trace_id.py`: middleware HTTP ASGI que genera UUID v4 por request, lo guarda en `ContextVar` y lo emite como header `X-Trace-Id` en la response.
- `backend/app/core/middleware/sanitize_logs.py`: thin wrapper que registra el processor `sanitize_secrets` en la pipeline de structlog (no es middleware HTTP — es un structlog processor; el nombre se conserva por consistencia con docs canónicos).
- `backend/app/main.py` con `lifespan` async (D3): ejecuta `SQLModel.metadata.create_all(engine)` y `seed_admin()` (idempotentes); ambos son **no-op funcional en M1 hasta Change 03/04** — `create_all` no crea tablas porque ningún modelo está registrado, y `seed_admin` retorna temprano si la tabla `users` no existe todavía.
- `backend/app/main.py` registra middlewares y monta el router `health` con `GET /health → 200 {"status": "ok"}`. **NO** se incluye `/health/components` (eso es Change 11/15).
- `backend/requirements.txt` con versiones fijadas: FastAPI 0.136.x, SQLModel, psycopg[binary], python-jose[cryptography], argon2-cffi, structlog, valkey, cryptography, pydantic-settings, uvicorn[standard]. Las versiones puntuales de cada lib se resuelven en `/opsx:apply` contra PyPI (la pinning exacta es trabajo del apply).
- `backend/Dockerfile`: imagen basada en `python:3.13-slim`, multi-stage (builder con `--no-cache-dir` + runtime mínimo), usuario no-root `app` (`uid 10001`), `WORKDIR /app`, `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`. Listening sólo en 8000 — el puerto 8443 declarado en compose es para mTLS, que aparece en Change 06.
- `backend/.dockerignore` para excluir `__pycache__`, `.pytest_cache`, `tests/`, `.env`.
- Tests mínimos en `backend/tests/` (pytest + httpx): `test_health.py` (GET /health → 200), `test_logging_sanitize.py` (un log con `password` en kwargs sale con la key redacted), `test_logging_trace_id.py` (request HTTP genera `trace_id` en log y header response).

**No** se incluye en este change (boundary explícito): modelos SQLModel concretos, endpoints de auth, consumer/publisher Valkey, CA mTLS, `seed_admin` con datos reales. Todo eso es Change 03+.

## Capabilities

### New Capabilities

- `backend-core`: Esqueleto del paquete Python `backend/app/`, configuración tipada vía pydantic-settings, engine SQLModel + Unit of Work, logging JSON estructurado con sanitización de secretos y `trace_id` por request, lifespan FastAPI idempotente con hooks `create_all` + `seed_admin`, endpoint `GET /health`, Dockerfile multi-stage con usuario no-root.

### Modified Capabilities

<!-- Ninguna. infra-compose no se modifica: el placeholder del backend ya está
     correcto. Este change sólo le da contenido al build context, no toca el
     compose ni el spec archivado. -->

## Impact

- **Código nuevo**: `backend/app/{__init__.py,main.py}`, `backend/app/core/{config,database,logging}.py`, `backend/app/core/middleware/{trace_id,sanitize_logs}.py`, `backend/app/modules/__init__.py`, `backend/requirements.txt`, `backend/Dockerfile`, `backend/.dockerignore`, `backend/tests/{conftest.py,test_health.py,test_logging_sanitize.py,test_logging_trace_id.py}`.
- **Build pipeline**: a partir de este change, `docker compose --profile app build backend` debe terminar exit 0 y `docker compose --profile app up backend` debe arrancar y responder 200 en `GET http://localhost:8000/health`.
- **Cross-cutting establecido** (D7, RN-89, RN-62, RN-81): toda emisión de log de la app pasa por la pipeline structlog con sanitización + trace_id desde el día 1. Los changes posteriores que agreguen logs heredan el comportamiento gratis.
- **Reglas cubiertas**: RN-45 (admin first-login: queda preparado el hook de `seed_admin` con `must_change_password=True`, sin tabla todavía), RN-62 (seed admin idempotente: misma idea, hook listo), RN-71 (snake_case en código y logs), RN-76 (single-instance: lifespan asume un solo proceso ejecutando `create_all`/`seed_admin` sin coordinación), RN-81 (parámetros Argon2id explícitos: la dependencia `argon2-cffi` queda fijada para Change 04), RN-89 (logging JSON estructurado con sanitización de `password`, `access_token`, `refresh_token`, `bootstrap_secret`, `master_secret`, `shared_secret`, `signature` + retención 30 días — las dos primeras se implementan; la retención es responsabilidad operativa de docker logging driver).
- **Decisiones aplicadas**: D3 (lifespan FastAPI ejecuta `create_all` + `seed_admin`, sin servicio `db-init`), D7 (cross-cutting distribuido: `sanitize_logs` y `trace_id` se introducen en este change, no al final del roadmap).
- **Dependencias bloqueadas resueltas**: este change desbloquea Change 03 (`domain-models`) y, transitivamente, Change 04 (`backend-auth`) y Change 06+ (`agent-mtls-bootstrap` necesita el módulo `core/`).
- **Riesgos**: el `seed_admin()` esqueleto debe tolerar que la tabla `users` aún no exista (en M1, antes de Change 03). Estrategia: detectar la ausencia con `inspect(engine).has_table("users")` y retornar `log.info("seed_admin skipped: users table not yet created")`. Sin esto, `docker compose up backend` fallaría hasta que Change 03 cree la tabla.
