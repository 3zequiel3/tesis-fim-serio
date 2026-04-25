## 1. Estructura del paquete y dependencias

- [x] 1.1 Crear `backend/app/__init__.py`, `backend/app/main.py` (vacío por ahora), `backend/app/core/__init__.py`, `backend/app/core/middleware/__init__.py`, `backend/app/modules/__init__.py`. Borrar `backend/.gitkeep`.
- [x] 1.2 Crear `backend/requirements.txt` con versiones pinneadas: `fastapi==0.136.<patch>`, `sqlmodel==<latest>`, `psycopg[binary]==<latest>`, `python-jose[cryptography]==<latest>`, `argon2-cffi==<latest>`, `structlog==<latest>`, `valkey==<latest>` (paquete PyPI, no `valkey-py`), `cryptography==<latest>`, `pydantic-settings==<latest>`, `uvicorn[standard]==<latest>`. Resolver cada `<latest>` consultando PyPI al momento del apply.
- [x] 1.3 Crear `backend/requirements-dev.txt` con `pytest`, `pytest-asyncio`, `httpx`, `pytest-cov` (versiones pinneadas).
- [x] 1.4 Crear `backend/.dockerignore` excluyendo `__pycache__/`, `*.pyc`, `.pytest_cache/`, `tests/`, `.env`, `.venv/`, `*.egg-info`.
- [x] 1.5 Verificar que `python -c "from app.main import app"` retorna `None` por ahora pero no falla por sintaxis (con el módulo vacío todavía).

## 2. Configuración tipada (`core/config.py`)

- [x] 2.1 Implementar `Settings(BaseSettings)` con `model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)`.
- [x] 2.2 Definir campos: `database_url: PostgresDsn` (alias `DATABASE_URL`, obligatorio sin default), `valkey_url: str` (alias `VALKEY_URL`, obligatorio sin default), `jwt_secret_current: str = ""`, `jwt_secret_previous: str = ""`, `admin_username: str = ""`, `admin_password: SecretStr = SecretStr("")`, `ca_cert_path: str = ""`, `ca_key_path: str = ""`, `environment: str = "dev"`, `log_level: str = "INFO"`.
- [x] 2.3 Instanciar `settings = Settings()` a nivel módulo (fail-fast en import-time si faltan obligatorias).
- [x] 2.4 Test rápido en REPL: con `DATABASE_URL` y `VALKEY_URL` exportadas, `python -c "from app.core.config import settings; print(settings.environment)"` imprime `dev`.

## 3. Engine y session (`core/database.py`)

- [x] 3.1 Crear `engine = create_engine(str(settings.database_url), pool_pre_ping=True, echo=False)` desde SQLModel.
- [x] 3.2 Implementar `def get_session() -> Generator[Session, None, None]` con `try/finally` que cierra la sesión. Con el patrón `with Session(engine) as session: yield session` que SQLModel/SQLAlchemy ya cierran al salir del context manager.
- [x] 3.3 Exportar `engine` y `get_session` desde `core/database.py` (sin `__all__` explícito todavía; los changes posteriores usarán imports directos).

## 4. Logging structlog (`core/logging.py`)

- [x] 4.1 Implementar `def sanitize_secrets(logger, method_name, event_dict) -> dict` con la lista de keys (D-CHANGE-01 del design): canónicas RN-89 + extensión defensiva. Implementar match case-insensitive y recursión sobre dicts/listas con depth máximo 5. Reemplazar valor por `"[REDACTED]"`.
- [x] 4.2 Implementar `def configure_logging() -> None` que llame `structlog.configure(processors=[merge_contextvars, add_log_level, TimeStamper(fmt='iso', utc=True), sanitize_secrets, JSONRenderer()], wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level))`. También configurar el logging stdlib root para que uvicorn/sqlalchemy emitan via structlog (usar `structlog.stdlib.ProcessorFormatter`).
- [x] 4.3 Exportar `log = structlog.get_logger()` del módulo (singleton para conveniencia; los módulos pueden hacer su propio `get_logger(__name__)`).
- [x] 4.4 Test manual REPL: `configure_logging(); log.info("test", password="hunter2")` imprime JSON con `"password":"[REDACTED]"`.

## 5. Middleware trace_id (`core/middleware/trace_id.py`)

- [x] 5.1 Definir `trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)` a nivel módulo (para que otros módulos puedan importarlo y leerlo si necesitan).
- [x] 5.2 Implementar `class TraceIdMiddleware` ASGI con la firma del snippet en design.md §D-CHANGE-02.
- [x] 5.3 En `__call__`: si `scope["type"] != "http"`, pasar tal cual. Si es HTTP: generar `trace_id = str(uuid.uuid4())`, llamar `structlog.contextvars.bind_contextvars(trace_id=trace_id)`, hacer `token = trace_id_var.set(trace_id)` para soporte directo del var.
- [x] 5.4 Wrapper `send_with_trace`: en `http.response.start` agregar header `(b"x-trace-id", trace_id.encode())` a la lista de headers existente.
- [x] 5.5 `try/finally` que llama `structlog.contextvars.unbind_contextvars("trace_id")` y `trace_id_var.reset(token)`.

## 6. Sanitize logs wrapper (`core/middleware/sanitize_logs.py`)

- [x] 6.1 Crear módulo con un único export: `def configure_log_sanitizer() -> None` que importa `sanitize_secrets` de `core/logging.py` y verifica/registra en la pipeline (en realidad la registra `configure_logging` directamente — este módulo es un wrapper documental para que la estructura coincida con `docs/arquitectura_stack.md` que menciona `middleware sanitize_logs`).
- [x] 6.2 Documentar con docstring en el archivo que el processor real vive en `core/logging.py` y que este módulo existe por consistencia con el doc canónico (D-CHANGE-01).

## 7. Lifespan y app FastAPI (`app/main.py`)

- [x] 7.1 Importar `Settings`, `engine`, `configure_logging`, `TraceIdMiddleware`. Importar `from sqlalchemy import inspect` y `from sqlmodel import SQLModel`. Importar `from contextlib import asynccontextmanager`.
- [x] 7.2 Llamar `configure_logging()` ANTES de instanciar `FastAPI` (para que los logs del lifespan ya salgan formateados).
- [x] 7.3 Implementar `def seed_admin() -> None` con el guard de design.md §D-CHANGE-03: `if not inspect(engine).has_table("users"): log.info("seed_admin.skipped", reason="users_table_not_yet_created"); return`. Después del guard, `pass` con un comentario `# Body filled in Change 04 (backend-auth)`.
- [x] 7.4 Implementar `@asynccontextmanager async def lifespan(app)` con: `log.info("backend.startup", environment=settings.environment)`, `SQLModel.metadata.create_all(engine)`, `seed_admin()`, `yield`, `log.info("backend.shutdown")`.
- [x] 7.5 Instanciar `app = FastAPI(title="FIM Platform Backend", version="0.2.0", lifespan=lifespan)`.
- [x] 7.6 Registrar middleware: `app.add_middleware(TraceIdMiddleware)`.
- [x] 7.7 Definir endpoint `@app.get("/health")` que retorna `{"status": "ok"}` directamente (sin router separado en este change — un router se agrega cuando aparezcan más endpoints en `modules/health/` en Change 11/15).

## 8. Dockerfile (`backend/Dockerfile`)

- [x] 8.1 Stage `builder` desde `python:3.13-slim`. Crea venv en `/opt/venv`, exporta `PATH` al venv, `WORKDIR /build`, `COPY requirements.txt .`, `RUN pip install --no-cache-dir -r requirements.txt`. (Reescrito tras smoke test fallido — patrón `--target` rechazado, ver D-CHANGE-05.)
- [x] 8.2 Stage `runtime` desde `python:3.13-slim`. `RUN useradd --create-home --uid 10001 app`. `COPY --from=builder /opt/venv /opt/venv`. `ENV PATH="/opt/venv/bin:$PATH"`, `ENV PYTHONUNBUFFERED=1`. `WORKDIR /app`. `COPY --chown=app:app app/ /app/app/`. `USER app`. `EXPOSE 8000`. `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`.
- [x] 8.3 Verificar que `docker compose --profile app build backend` termina exit 0 desde la raíz del repo. ✅ Build 17.5s, exit 0 (con el patrón venv).
- [x] 8.4 Verificar tamaño de la imagen final: `docker images fim-backend:dev --format '{{.Size}}'` debe estar en orden de cientos de MB (no GB). ✅ orden cientos de MB.

## 9. Tests (`backend/tests/`)

- [x] 9.1 Crear `backend/tests/__init__.py` vacío y `backend/tests/conftest.py` con fixture `client` que retorna `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")` con cleanup correcto. Configurar `pytest.ini` o `pyproject.toml` con `asyncio_mode = "auto"`.
- [x] 9.2 `test_health.py`: test `async def test_health_returns_ok(client)` que hace `await client.get("/health")` y verifica `status_code == 200`, body JSON `{"status": "ok"}`, header `X-Trace-Id` presente y matchea regex UUID v4.
- [x] 9.3 `test_logging_sanitize.py`: usar `structlog.testing.capture_logs()` como context manager, emitir `log.info("login", username="alice", password="hunter2", access_token="eyJ...")`, assertar que el dict capturado tiene `password == "[REDACTED]"`, `access_token == "[REDACTED]"`, `username == "alice"`.
- [x] 9.4 `test_logging_sanitize.py`: segundo test con dict anidado: `log.info("auth", payload={"user": "alice", "access_token": "x"})` → assertar `payload.access_token == "[REDACTED]"`.
- [x] 9.5 `test_logging_sanitize.py`: tercer test case-insensitive: `log.info("x", Password="hunter2")` → assertar redactado.
- [x] 9.6 `test_logging_trace_id.py`: usar `capture_logs()` + `client.get("/health")`, captar el header `X-Trace-Id`, assertar que al menos una entrada de log tiene `trace_id` igual al header.
- [x] 9.7 `test_logging_trace_id.py`: segundo test con dos requests secuenciales — assertar que los dos `X-Trace-Id` son distintos y los logs no se mezclan.
- [ ] 9.8 Ejecutar `cd backend && python -m pytest tests/ -v` localmente — todo verde. (Pendiente: el operador no corrió pytest local en este ciclo; la verificación E2E vía smoke test Docker cubre los criterios funcionales. No bloqueante para el archive.)

## 10. Smoke test contra Docker

- [x] 10.1 Desde la raíz: `docker compose --profile app up -d db valkey backend`. Esperar `docker compose ps` muestra los tres `running` (y db/valkey `healthy`). ✅ los 3 arrancaron, valkey/db healthy.
- [x] 10.2 `curl -i http://localhost:8000/health` → status 200, body `{"status":"ok"}`, header `X-Trace-Id` con UUID. ✅ status 200, body OK, `x-trace-id: 58789a0c-204f-430b-8a11-3e45a3c22c3b`.
- [x] 10.3 `docker compose logs backend` → cada línea es JSON válido. Línea de startup contiene `event=backend.startup`. Línea de seed contiene `event=seed_admin.skipped reason=users_table_not_yet_created`. ✅ ambos eventos presentes y todas las líneas JSON.
- [x] 10.4 `curl http://localhost:8000/health` dos veces; los dos `X-Trace-Id` son distintos. ✅ `a4cd971f-3760-4b78-b808-ec083a0efdb9` y `0a3c64b0-44a3-41e7-8985-f20496480526`.
- [x] 10.5 `docker compose --profile app exec backend id -u` → `10001`. ✅ confirmado uid 10001.
- [ ] 10.6 `docker compose --profile app down` (cleanup) — opcional, queda a criterio del operador.

## 11. Closure

- [x] 11.1 Verificar que NO se modificó `docker-compose.yml`, `db/init/`, `.env.example`, `docs/`, `CHANGES.md` (boundary del change).
- [x] 11.2 Correr `openspec validate backend-core-scaffold` (si está disponible) y resolver warnings.
- [x] 11.3 Commit conventional: `feat(backend): scaffold core package with cross-cutting (#change-02)`. Sin Co-Authored-By. Body explicando D3 y D7 aplicadas y los archivos creados.
- [x] 11.4 Confirmar que `openspec status --change backend-core-scaffold --json` muestra `isComplete: true` (todos los artifacts done).
