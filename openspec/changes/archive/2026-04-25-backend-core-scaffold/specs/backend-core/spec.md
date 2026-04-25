# Spec delta: backend-core

## ADDED Requirements

### Requirement: Estructura de paquete backend según docs canónicos

El sistema SHALL crear el paquete Python `backend/app/` con submódulos `core/` y `modules/` según `docs/arquitectura_stack.md §Módulos del backend`. El subpaquete `core/` SHALL contener al menos los archivos `config.py`, `database.py`, `logging.py`, y un subpaquete `middleware/` con `trace_id.py` y `sanitize_logs.py`. El subpaquete `modules/` SHALL existir con un `__init__.py` vacío como placeholder para los módulos de dominio que introducen los changes posteriores (Change 03+). El paquete `app/` SHALL exportar la app FastAPI desde `app/main.py` como `app: FastAPI`.

#### Scenario: Layout del paquete coincide con el doc canónico
- **WHEN** se inspecciona `backend/app/`
- **THEN** existen los archivos `__init__.py`, `main.py`
- **AND** existe el subdirectorio `core/` con `__init__.py`, `config.py`, `database.py`, `logging.py`
- **AND** existe el subdirectorio `core/middleware/` con `__init__.py`, `trace_id.py`, `sanitize_logs.py`
- **AND** existe el subdirectorio `modules/` con un `__init__.py` (puede estar vacío)

#### Scenario: La app FastAPI es importable
- **WHEN** se ejecuta `python -c "from app.main import app; assert app is not None"` desde `backend/`
- **THEN** el comando termina con exit 0
- **AND** `app` es una instancia de `fastapi.FastAPI`

### Requirement: Configuración tipada vía pydantic-settings

El sistema SHALL exponer un objeto `settings: Settings` en `app/core/config.py` que herede de `pydantic_settings.BaseSettings`. La clase SHALL leer variables de entorno y opcionalmente un archivo `.env`. Las variables `DATABASE_URL` y `VALKEY_URL` SHALL ser obligatorias (sin default). Las variables `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CA_CERT_PATH`, `CA_KEY_PATH` SHALL existir como atributos del modelo, pueden tener default vacío en este change y serán requeridas por los changes que las consumen (04, 06). El modelo SHALL configurarse con `extra="ignore"` para tolerar variables del compose que el backend no usa.

#### Scenario: DATABASE_URL ausente al arrancar
- **WHEN** se intenta importar `app.core.config` sin `DATABASE_URL` en el environment
- **THEN** se lanza `pydantic.ValidationError`
- **AND** el mensaje menciona el campo `DATABASE_URL`

#### Scenario: Variables extra son ignoradas
- **WHEN** el environment incluye `DB_PASSWORD=foo` (variable de otro servicio)
- **AND** se importa `app.core.config`
- **THEN** la importación termina sin error
- **AND** el objeto `settings` no tiene atributo `db_password`

### Requirement: Engine SQLModel y Unit of Work por request

El sistema SHALL crear un `engine` SQLModel en `app/core/database.py` usando `settings.DATABASE_URL`. SHALL exportar una función generadora `get_session()` que yield-ee una `Session` y la cierre al finalizar, apta para usar como dependency de FastAPI. La sesión SHALL hacer rollback automáticamente si la request termina con excepción no capturada.

#### Scenario: get_session entrega una sesión funcional
- **WHEN** se obtiene una sesión llamando `next(get_session())`
- **THEN** el objeto retornado es instancia de `sqlmodel.Session`
- **AND** el atributo `bind` apunta al `engine` exportado por el módulo

#### Scenario: La sesión se cierra al finalizar la dependency
- **WHEN** un endpoint usa `Depends(get_session)` y termina la request
- **THEN** la sesión se cierra (no quedan conexiones abiertas en el pool)

### Requirement: Logging JSON estructurado con structlog

El sistema SHALL configurar `structlog` en `app/core/logging.py` para emitir cada línea de log como un objeto JSON con al menos las keys `event`, `timestamp` (ISO 8601 UTC), `level`. La función `configure_logging()` SHALL llamarse una sola vez al arrancar la app (desde `main.py`, antes de instanciar FastAPI). La pipeline SHALL incluir, en orden: `structlog.contextvars.merge_contextvars`, `add_log_level`, `TimeStamper(fmt='iso', utc=True)`, `sanitize_secrets` (processor de este change), y un renderer JSON al final.

#### Scenario: Cada log es JSON parseable
- **WHEN** la app emite cualquier log durante una request
- **THEN** la línea de log es un objeto JSON válido
- **AND** contiene las keys `event`, `timestamp`, `level`

#### Scenario: Timestamp en ISO 8601 UTC
- **WHEN** se emite un log
- **THEN** el campo `timestamp` cumple el formato `YYYY-MM-DDTHH:MM:SS(.ffffff)?Z` o equivalente con offset `+00:00`

### Requirement: Sanitización de secretos en logs (RN-89, D7)

El sistema SHALL incluir un structlog processor `sanitize_secrets` en la pipeline de logging que detecte keys sensibles (case-insensitive) en el `event_dict` y reemplace su valor por la string literal `[REDACTED]` sin remover la key. La lista mínima obligatoria de keys SHALL ser exactamente: `password`, `access_token`, `refresh_token`, `bootstrap_secret`, `master_secret`, `shared_secret`, `signature` (la lista canónica de RN-89 / `docs/arquitectura_stack.md` §1813). El processor MAY incluir keys adicionales defensivas (`current_password`, `new_password`, `token`, `secret`, `bootstrap_secret_hash`, `authorization`, `cookie`, `set-cookie`, `x-api-key`, `csrf_token`, `jwt`, `private_key`). La detección SHALL ser recursiva sobre dicts y listas anidados con profundidad máxima 5.

#### Scenario: Password sanitizada en log directo
- **WHEN** el código ejecuta `log.info("login_attempt", username="alice", password="hunter2")`
- **THEN** la línea de log JSON contiene `"username": "alice"`
- **AND** contiene `"password": "[REDACTED]"`
- **AND** no contiene la string `"hunter2"` en ninguna parte

#### Scenario: Token sanitizado en dict anidado
- **WHEN** el código ejecuta `log.info("auth", payload={"user": "alice", "access_token": "eyJ..."})`
- **THEN** la línea de log contiene `"payload": {"user": "alice", "access_token": "[REDACTED]"}`
- **AND** no contiene la string `"eyJ"` en ninguna parte

#### Scenario: Secrets canónicos de RN-89 sanitizados
- **WHEN** se emite un log con cualquiera de las keys `password`, `access_token`, `refresh_token`, `bootstrap_secret`, `master_secret`, `shared_secret`, `signature`
- **THEN** el valor asociado SHALL aparecer como `"[REDACTED]"` en la salida JSON

#### Scenario: Match case-insensitive
- **WHEN** el código ejecuta `log.info("x", Password="hunter2")` (P mayúscula)
- **THEN** el valor sigue siendo redactado a `"[REDACTED]"`

### Requirement: trace_id por request (D7, RN-89)

El sistema SHALL incluir un middleware ASGI `TraceIdMiddleware` registrado en `app/main.py` que genere un UUID v4 nuevo por cada request HTTP, lo bind-ee al contexto de structlog vía `structlog.contextvars.bind_contextvars(trace_id=...)`, y lo emita como header `X-Trace-Id` en la response. Al terminar la request (incluso por excepción), el middleware SHALL hacer unbind del trace_id del contexto. Todos los logs emitidos durante el procesamiento de la request SHALL incluir la key `trace_id` con el mismo valor que el header.

#### Scenario: Header X-Trace-Id presente en la response
- **WHEN** el cliente hace `GET /health`
- **THEN** la response incluye el header `X-Trace-Id`
- **AND** el valor del header es un UUID v4 válido (`xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx` con `y ∈ {8,9,a,b}`)

#### Scenario: trace_id propagado a logs
- **WHEN** el cliente hace una request HTTP
- **AND** el handler emite un log
- **THEN** la línea de log contiene la key `trace_id`
- **AND** el valor de `trace_id` en el log es idéntico al valor del header `X-Trace-Id` de esa misma response

#### Scenario: trace_id distinto entre requests
- **WHEN** el cliente hace dos requests HTTP secuenciales
- **THEN** los headers `X-Trace-Id` de las dos responses son distintos
- **AND** los logs de cada request tienen su propio `trace_id` sin mezclarse

#### Scenario: Logs fuera de request HTTP no tienen trace_id
- **WHEN** el lifespan emite un log durante el startup (antes de aceptar requests)
- **THEN** la línea de log NO contiene la key `trace_id` (o la contiene con valor `null`)

### Requirement: Lifespan FastAPI ejecuta create_all + seed_admin idempotentes (D3, RN-62, RN-76)

El sistema SHALL declarar el lifespan de FastAPI en `app/main.py` usando `@asynccontextmanager` que, en startup, ejecute `SQLModel.metadata.create_all(engine)` y `seed_admin()` (en ese orden), y en shutdown emita un log de cierre. La función `seed_admin()` SHALL existir con la firma final `def seed_admin() -> None:` y SHALL ser idempotente. Si la tabla `users` no existe todavía (estado de M1 antes de Change 03), SHALL retornar temprano emitiendo un log `info` con razón explícita (`reason="users_table_not_yet_created"`) y SHALL NO lanzar excepción. NO SHALL existir un servicio `db-init` en `docker-compose.yml` (D3).

#### Scenario: Backend arranca sin tablas en M1
- **WHEN** se ejecuta `docker compose --profile app up backend` en un entorno donde la base `fim` está vacía y ningún modelo SQLModel está registrado
- **THEN** el contenedor llega a estado `running`
- **AND** el lifespan termina sin excepción
- **AND** los logs incluyen una línea con `event=seed_admin.skipped` y `reason=users_table_not_yet_created`

#### Scenario: create_all es idempotente
- **WHEN** el backend se reinicia con la base ya inicializada por un arranque previo
- **THEN** `SQLModel.metadata.create_all(engine)` no lanza error
- **AND** no recrea ni borra tablas existentes

### Requirement: Endpoint GET /health responde 200 (Done criterion)

El sistema SHALL exponer un endpoint `GET /health` que retorne `200 OK` con cuerpo JSON `{"status": "ok"}` y `Content-Type: application/json`. El endpoint SHALL NO realizar checks de dependencias (DB, Valkey, n8n) en este change — eso es responsabilidad de `GET /health/components` que se introduce en Change 11/15.

#### Scenario: Health responde con 200 y cuerpo esperado
- **WHEN** el cliente hace `GET /health`
- **THEN** el código de respuesta es `200`
- **AND** el cuerpo es exactamente `{"status": "ok"}`
- **AND** el header `Content-Type` empieza con `application/json`

#### Scenario: Health no falla cuando DB está caída
- **WHEN** el contenedor `db` está detenido
- **AND** el cliente hace `GET /health` al backend
- **THEN** el código de respuesta sigue siendo `200`
- **AND** el cuerpo sigue siendo `{"status": "ok"}`

### Requirement: Dockerfile multi-stage con usuario no-root

El sistema SHALL incluir `backend/Dockerfile` con dos stages (`builder` y `runtime`) basados en `python:3.13-slim`. La imagen final SHALL ejecutar como un usuario no-root creado explícitamente (`uid=10001`, nombre `app`). SHALL NO ejecutar como `root`. El `CMD` final SHALL invocar uvicorn escuchando en `0.0.0.0:8000`. La imagen SHALL respetar el nombre `fim-backend:dev` declarado en `docker-compose.yml`.

#### Scenario: La imagen builda
- **WHEN** se ejecuta `docker compose --profile app build backend`
- **THEN** el comando termina con exit 0
- **AND** existe la imagen local `fim-backend:dev`

#### Scenario: El proceso corre como usuario no-root
- **WHEN** el contenedor backend está corriendo
- **AND** se ejecuta `docker compose --profile app exec backend id -u`
- **THEN** la salida es `10001` (no `0`)

#### Scenario: Uvicorn escucha en 8000
- **WHEN** el contenedor backend está corriendo
- **AND** se hace `curl http://localhost:8000/health` desde el host
- **THEN** se obtiene respuesta 200

### Requirement: requirements.txt fija dependencias del stack canónico

El sistema SHALL incluir `backend/requirements.txt` con todas las dependencias declaradas en `docs/arquitectura_stack.md §Stack`: `fastapi==0.136.x`, `sqlmodel`, `psycopg[binary]`, `python-jose[cryptography]`, `argon2-cffi`, `structlog`, `valkey`, `cryptography`, `pydantic-settings`, `uvicorn[standard]`. Cada dependencia SHALL tener una versión exacta o un rango cerrado pinneado (no `latest`, no rangos abiertos `>=X` sin upper bound). Las dependencias de testing (`pytest`, `pytest-asyncio`, `httpx`) MAY ir en un `requirements-dev.txt` separado.

#### Scenario: requirements.txt tiene FastAPI 0.136
- **WHEN** se inspecciona `backend/requirements.txt`
- **THEN** existe una línea `fastapi==0.136.<patch>` (con `<patch>` siendo un número concreto)

#### Scenario: Sin versiones latest ni rangos abiertos
- **WHEN** se inspecciona `backend/requirements.txt`
- **THEN** no aparece la cadena `latest` en ninguna línea de dependencia
- **AND** ninguna línea tiene la forma `<paquete>>=X` sin un upper bound `,<Y`

### Requirement: Tests mínimos cubren health, sanitización y trace_id

El sistema SHALL incluir tests automatizados en `backend/tests/` ejecutables vía `pytest` que verifiquen: (a) `GET /health` retorna 200 con el cuerpo esperado y header `X-Trace-Id`, (b) un log con campo `password` aparece sanitizado a `[REDACTED]`, (c) los logs emitidos durante una request HTTP incluyen la key `trace_id` con el mismo valor que el header `X-Trace-Id` de la response.

#### Scenario: La suite pasa
- **WHEN** se ejecuta `pytest backend/tests/` desde la raíz del repo (con dependencias dev instaladas)
- **THEN** todos los tests pasan
- **AND** la suite incluye al menos un test por cada uno de los tres requisitos arriba

### Requirement: Done criterion del Change 02

La infraestructura backend SHALL satisfacer el criterio de aceptación adaptado de `CHANGES.md` línea 107: `docker compose --profile app up backend` arranca limpio en M1; `GET /health` responde 200; los logs son JSON con `trace_id` por request y sin secrets cuando una request los pasa. La parte original "tabla `users` con seed admin" del done criterion del roadmap se cumple en Change 03 (modelo `User`) + Change 04 (cuerpo de `seed_admin`); este change deja el hook listo y verificable cuando esos changes se merguen.

#### Scenario: Smoke test M1 reproducible
- **WHEN** un operador clona el repo en estado `Change 02 merged, Change 03 no merged`
- **AND** ejecuta `docker compose --profile app up -d db valkey backend`
- **THEN** el contenedor backend queda `running` en menos de 30 segundos
- **AND** `curl http://localhost:8000/health` retorna `{"status":"ok"}` con header `X-Trace-Id`
- **AND** `docker compose logs backend` contiene al menos una línea JSON con `event=seed_admin.skipped reason=users_table_not_yet_created`
- **AND** no hay tracebacks ni errores fatales en los logs
