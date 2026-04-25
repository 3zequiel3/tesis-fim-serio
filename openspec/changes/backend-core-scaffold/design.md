## Context

El servicio `backend` ya está declarado en `docker-compose.yml` con `profiles: ["app"]`, depende de `db` y `valkey` healthy, monta el volumen `backend_certs:ro`, expone los puertos `8000` (API HTTP) y `8443` (mTLS, futuro Change 06) y recibe vía environment las variables `DATABASE_URL`, `VALKEY_URL`, `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CA_CERT_PATH`, `CA_KEY_PATH`. El directorio `backend/` del repo está vacío (solo `.gitkeep`). Este change le da contenido al `build: ./backend` que el compose ya espera.

El stack del backend está fijado en `docs/arquitectura_stack.md §Stack` (Python 3.13 + FastAPI 0.136 + SQLModel + structlog + valkey + cryptography + argon2-cffi + python-jose). La estructura de módulos también está fijada (`docs/arquitectura_stack.md §Módulos del backend`): `backend/app/{main.py,core/,modules/}` con `core/` agrupando `config`, `database`, `logging`, `security`, `pki`, `rate_limit`, `dependencies`. En este change sólo aparecen los archivos cuyo feature ya está vivo: `config`, `database`, `logging` y los dos middlewares cross-cutting. Los demás se incorporan en sus respectivos changes (Change 04 para `security` y `dependencies`, Change 06 para `pki`, Change 04/11 para `rate_limit`).

Decisiones cerradas que aplican aquí: **D3** (lifespan FastAPI ejecuta `create_all` + `seed_admin` en lugar de un servicio `db-init`) y **D7** (cross-cutting distribuido: `sanitize_logs` y `trace_id` se introducen en este change, no al final del roadmap). Reglas que aplican: RN-45, RN-62, RN-71, RN-76, RN-81, RN-89.

## Goals / Non-Goals

**Goals:**
- Convertir el placeholder `backend` del compose en un binario que arranca, atiende `GET /health` y emite logs JSON con `trace_id` y secrets sanitizados desde la primera línea de log.
- Establecer la convención de logging para TODOS los changes posteriores: una sola pipeline de structlog, processors compartidos, sin duplicar `configure_logging` por módulo.
- Dejar la pipeline de lifespan armada (D3) aunque hoy no haya tablas ni `User`. Cuando Change 03 agregue `Event`, `Rule`, `User`, etc. y Change 04 implemente `seed_admin` real, esos changes solo registran sus modelos y completan la función — no tocan `main.py`.
- Producir un Dockerfile reproducible (multi-stage, usuario no-root, sin cachés) que el compose ya existente puede buildear sin cambios.

**Non-Goals:**
- Modelos SQLModel concretos (`User`, `Event`, `Rule`, `Agent`, etc.) → **Change 03** (`domain-models`).
- Endpoints de auth (`/auth/login`, `/auth/refresh`, `/auth/logout`) y `core/security.py` → **Change 04** (`backend-auth`).
- Rate limiting (counters Valkey + TTL) → **Change 04** y **Change 11** según la matriz D7.
- CA propia y módulo `core/pki.py` → **Change 06** (`agent-mtls-bootstrap`).
- Consumer de Valkey Streams → **Change 08** (`valkey-streams-transport`).
- Endpoint `GET /health/components` con checks de DB/Valkey/n8n → **Change 11** o **Change 15**. Acá sólo `GET /health` plano.
- Migraciones Alembic → fuera del MVP (D3 documenta el trigger para introducirlas en el futuro).

## Decisions

### D-CHANGE-01 — `sanitize_logs` se implementa como structlog **processor**, no como ASGI middleware

**Decisión**: La sanitización vive en el pipeline de structlog (`structlog.configure(processors=[..., sanitize_secrets, ...])`), no como middleware HTTP. Conservamos el nombre `sanitize_logs` por consistencia con `docs/arquitectura_stack.md §Módulos del backend` (línea 700, "structlog + middleware sanitize_logs"), pero internamente es una función `def sanitize_secrets(logger, method_name, event_dict) -> event_dict`.

**Alternativa considerada**: ASGI middleware que parsee request/response bodies y filtre. Descartada porque (a) los secrets también aparecen en logs de fondo (lifespan, consumers Change 08+, tareas de cron) que no pasan por el ciclo HTTP, (b) un ASGI middleware no puede interceptar logs emitidos directamente con `log.info("...", password=...)`, (c) el processor de structlog es la única superficie por donde TODO log obligatoriamente pasa.

**Lista de keys sanitizadas** (case-insensitive match sobre las keys del `event_dict`):

Mínimo canónico exigido por RN-89 / `docs/arquitectura_stack.md` línea 1813:
`password`, `access_token`, `refresh_token`, `bootstrap_secret`, `master_secret`, `shared_secret`, `signature`.

Extensión defensiva de este change (no contradice nada de los appendices, sólo amplía):
`current_password`, `new_password`, `token`, `secret`, `bootstrap_secret_hash`, `authorization`, `cookie`, `set-cookie`, `x-api-key`, `csrf_token`, `jwt`, `private_key`.

Valor de reemplazo: la string literal `"[REDACTED]"`. NO se elimina la key (perder la key haría más difícil debuggear "el log contenía un password"); se preserva la presencia y se oculta el valor.

**Detección recursiva**: el processor camina dicts anidados y listas. Profundidad máxima 5 (defensa contra ciclos). Más allá de eso, se preserva sin tocar y se emite warning interno una vez por proceso.

### D-CHANGE-02 — `trace_id` con `contextvars.ContextVar`, no con `threading.local`

**Decisión**: El middleware `trace_id` usa `contextvars.ContextVar[str | None]("trace_id", default=None)`. El processor `inject_trace_id` lo lee con `.get()` y lo agrega al `event_dict` con la key `trace_id` si no es `None`.

**Alternativa considerada**: `threading.local`. Descartada porque FastAPI/Uvicorn ejecutan handlers en el event loop (corutinas) y `threading.local` no propaga a través de `await` — un `await` cambia de coroutina y se pierde el `trace_id`. `contextvars` es la API estándar de Python para context-local en async (PEP 567) y structlog la soporta nativamente vía `structlog.contextvars.merge_contextvars`.

**Snippet ilustrativo** (no es código final, vive en `core/middleware/trace_id.py`):

```python
import uuid
from contextvars import ContextVar
from starlette.types import ASGIApp, Receive, Scope, Send

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

class TraceIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        trace_id = str(uuid.uuid4())
        token = trace_id_var.set(trace_id)
        async def send_with_trace(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-trace-id", trace_id.encode()))
                message["headers"] = headers
            await send(message)
        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            trace_id_var.reset(token)
```

**Exposición a structlog**: se usa el processor oficial `structlog.contextvars.merge_contextvars` (en lugar de uno custom). El middleware llama `structlog.contextvars.bind_contextvars(trace_id=trace_id)` al inicio y `unbind_contextvars("trace_id")` en el `finally`. Así, además, cualquier código que quiera enriquecer el contexto (`bind_contextvars(user_id=...)` en Change 04) usa la misma API.

### D-CHANGE-03 — Lifespan idempotente desde el día 1, aunque no haya tablas

**Decisión**: `app/main.py` declara `lifespan = asynccontextmanager` con la estructura final que vive todo el roadmap:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("backend.startup", env=settings.environment)
    SQLModel.metadata.create_all(engine)  # no-op si no hay modelos registrados
    seed_admin()                          # no-op si tabla users no existe aún
    yield
    log.info("backend.shutdown")
```

`seed_admin()` en este change tiene la firma final pero el cuerpo guard:

```python
def seed_admin() -> None:
    inspector = sqlalchemy.inspect(engine)
    if not inspector.has_table("users"):
        log.info("seed_admin.skipped", reason="users_table_not_yet_created")
        return
    # Cuerpo real lo completa Change 04 (necesita el modelo User).
```

**Por qué el guard y no dejar la función vacía**: si Change 03 olvida agregar `seed_admin` al lifespan, la regresión sería silenciosa hasta que un admin intentara loguearse. Con el guard ya conectado, en cuanto Change 04 reemplace el cuerpo, el seed corre automáticamente al primer `docker compose up backend` post-merge.

**Idempotencia** (RN-62): cuando Change 04 escriba el cuerpo real, la lógica canónica es `select(User).first()` — si existe ya un admin, retornar. Esto es seguro en single-instance (RN-76) sin lock distribuido.

### D-CHANGE-04 — `Settings` con `extra="ignore"` y validación al startup

**Decisión**: `core/config.py` define `Settings(BaseSettings)` con `model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)`. Las variables que el compose ya inyecta se mapean 1:1. `DATABASE_URL` y `VALKEY_URL` son obligatorias (sin default); el resto puede tener default vacío en este change y volverse obligatorio en su change correspondiente (`JWT_SECRET_CURRENT` se vuelve obligatorio en Change 04, `CA_CERT_PATH` en Change 06).

**Por qué `extra="ignore"` y no `extra="forbid"`**: el `.env` real va a contener variables de OTROS servicios del compose (`DB_PASSWORD` para `db`, etc.) que el backend NO necesita leer. Con `extra="forbid"` el arranque falla. Con `extra="ignore"`, el backend solo lee lo suyo.

**Validación al startup**: la instancia `settings = Settings()` se crea al import-time del módulo. Si falta una variable obligatoria, pydantic lanza `ValidationError` antes de que uvicorn empiece a aceptar conexiones — fail-fast.

### D-CHANGE-05 — Dockerfile multi-stage, usuario no-root, sin healthcheck propio

**Decisión**:
- **Stage builder**: `python:3.13-slim`, `pip install --no-cache-dir --target=/install -r requirements.txt`. Sin `gcc` ni `build-essential` salvo que `psycopg[binary]` lo requiera (la variante `[binary]` provee wheels precompiladas; si en `apply` se descubre que falla, se cambia a `psycopg[c]` y se documenta).
- **Stage runtime**: `python:3.13-slim`, copia `/install` del builder, agrega usuario `app` con `useradd -m -u 10001 app`, `WORKDIR /app`, `COPY --chown=app:app . /app/`, `USER app`. `EXPOSE 8000`. `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`.
- **Sin `HEALTHCHECK` en el Dockerfile**: el compose ya define healthchecks en otros servicios; el del backend se agregará cuando exista `GET /health/components` (Change 11/15) y dependa de DB/Valkey. En este change, `GET /health` plano sirve para smoke test manual y para `wait-for` en CI futuros, pero no necesita estar declarado en Dockerfile.
- **Sin `ENV PYTHONDONTWRITEBYTECODE=1` ni `PYTHONUNBUFFERED=1` en el Dockerfile**: se setean en el `Settings` de pydantic via env, o se confía en uvicorn (que ya hace flush). Mantener Dockerfile mínimo.

**Alternativa considerada**: imagen `python:3.13-alpine`. Descartada — `psycopg` y `cryptography` con musl libc son problemáticos (necesitan compilación nativa, ABI distinta). `slim` (debian) es el default seguro para stack Python científico/criptográfico.

### D-CHANGE-06 — Tests mínimos en este change, no fixtures de DB todavía

**Decisión**: `backend/tests/` arranca con tres archivos:
- `test_health.py`: cliente httpx con `app` montado (no necesita DB), assert `GET /health → 200 {"status": "ok"}` y header `X-Trace-Id` presente con formato UUID v4.
- `test_logging_sanitize.py`: capture de logs con `structlog.testing.capture_logs()`, emite `log.info("test", password="hunter2", access_token="abc")`, assert que ambos valores aparecen como `"[REDACTED]"` y las keys siguen presentes.
- `test_logging_trace_id.py`: cliente httpx, hace request, captura logs, assert que cada entrada de log emitida durante la request tiene `trace_id` con valor UUID y que coincide con el header `X-Trace-Id` de la response.

**Sin fixtures de DB con transacción rolled-back todavía**: SQLModel no tiene modelos registrados aún. La fixture `session` de pytest llega en Change 03 cuando haya algo que testear contra DB. Para `/health` no hace falta tocar la DB.

**Stack de testing**: `pytest`, `pytest-asyncio` (modo `asyncio_mode = "auto"`), `httpx` (`AsyncClient(transport=ASGITransport(app=app))`). Versiones se pinean en `requirements.txt` o en un `requirements-dev.txt` separado — decisión menor del apply.

### D-CHANGE-07 — `core/middleware/` como subpaquete, no archivos sueltos

**Decisión**: `backend/app/core/middleware/__init__.py` exporta `TraceIdMiddleware` y `configure_log_sanitizer()`. Los archivos físicos: `trace_id.py` y `sanitize_logs.py`. El nombre `middleware/` es plural porque ya esperamos `cors.py` (Change 04) y `rate_limit.py` (Change 04/11) en el mismo subpaquete.

**Alternativa considerada**: archivos sueltos en `core/` (`core/trace_id_middleware.py`, etc.). Descartada — agrupar middlewares en un subpaquete escala mejor y refleja la estructura mental "esto es middleware HTTP/processor cross-cutting".

## Risks / Trade-offs

- **`seed_admin` skipped silencioso en M1** → en M1 (changes 02–04 sin merge), un operador podría arrancar el backend, ver el log `"seed_admin.skipped reason=users_table_not_yet_created"` y asumir que algo está roto. Mitigación: el log es nivel `info` con razón explícita; documentar en `backend/README.md` (lo agrega `apply`) que es esperado hasta que Change 04 esté merged.
- **Lista de keys sanitizadas no exhaustiva** → un nuevo secret introducido en un change futuro (ej. `n8n_webhook_url` con basic auth embebido) podría no estar en la lista. Mitigación: cada change que introduzca nuevos secrets debe extender la lista (regla a documentar en `openspec-propose` skill o equivalente). Con la base canónica + extensión defensiva de D-CHANGE-01, la cobertura para M1 es completa.
- **`extra="ignore"` en `Settings`** → un typo en `.env` (`DATABSE_URL`) no se detecta al startup, sale como `DATABASE_URL` ausente con el ValidationError de pydantic, lo cual es correcto pero podría confundir. Trade-off aceptado: la alternativa (`extra="forbid"`) rompe con compose multi-servicio.
- **psycopg[binary] vs psycopg[c]** → `[binary]` es wheel precompilada (rápido), `[c]` necesita `libpq-dev` en build stage (más lento, más confiable en arquitecturas raras). Empezamos con `[binary]`; si falla en `apply` o en CI, se cambia y se documenta.
- **No hay test de `lifespan` real en este change** → `create_all` no crea tablas (sin modelos), `seed_admin` corre por la rama del guard. El test que verifique que el lifespan ejecuta sin tirar excepción se cubre indirectamente con `test_health.py` (que monta la app con `lifespan`). Se agrega un test explícito de lifespan en Change 03 cuando haya algo que crear.
- **Falta CHANGES.md y proposal mencionan `core/security.py`, `core/pki.py`, etc. — alguien podría asumir que faltan en este change** → mitigación: el design.md (esta sección) lista explícitamente cada archivo y su change owner. Boundary explícito.

## Migration Plan

Este change introduce código nuevo, no migra estado. Plan de despliegue:

1. Merge del PR del change.
2. `docker compose --profile app build backend` → debe terminar exit 0.
3. `docker compose --profile app up -d backend` → contenedor `running`.
4. Smoke test: `curl http://localhost:8000/health` → `{"status":"ok"}`, header `X-Trace-Id` presente.
5. `docker compose logs backend` → cada línea es JSON válido, contiene `trace_id` para las que correspondan a una request, y un POST con `{"password":"foo"}` (cuando haya endpoint que lo acepte, en Change 04) NO debe filtrar `foo`.

**Rollback**: revert del commit. El compose sigue funcionando sin el profile `app` (`docker compose up -d` sin flags solo levanta `db`, `valkey`, `n8n` — el placeholder backend queda inerte). Cero impacto en los servicios infra.

**No-op M1 confirmado**: hasta que Change 03 cree modelos y Change 04 escriba el cuerpo de `seed_admin`, la lifespan corre en menos de 50ms (ambos hooks son no-op por el guard). El backend levanta y atiende /health.

## Open Questions

- **¿Versión exacta de `valkey-py`?** El paquete en PyPI es `valkey` (no `valkey-py`); la última versión compatible con Valkey 9.0.3 se resuelve en `apply` consultando PyPI. Si no se puede verificar online, se pinea provisional `>=6.0.0,<7` y se ajusta en Change 08 (`valkey-streams-transport`) cuando se use de verdad.
- **¿`requirements-dev.txt` separado o todo en `requirements.txt`?** Decisión menor de `apply`. Preferencia: separar (`pytest`, `pytest-asyncio`, `httpx` para tests no van a la imagen de runtime). El Dockerfile copia solo `requirements.txt`, no el dev.
- **¿Se commitea un `.env.example` adicional a nivel `backend/`?** No — el `.env.example` ya existe en la raíz (Change 01) y el compose ya inyecta las variables. Duplicarlo a nivel backend introduce drift. Si en `apply` aparece la necesidad de variables backend-only (ej. `LOG_LEVEL`), se agregan al `.env.example` raíz.
