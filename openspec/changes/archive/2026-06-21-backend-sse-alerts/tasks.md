## 1. Dependencia SSE

- [x] 1.1 Agregar `sse-starlette>=2.1.3` a `backend/requirements.txt`

## 2. AlertsBroadcaster

- [x] 2.1 Crear `backend/app/modules/alerts/stream.py` con clase `AlertsBroadcaster`: mantiene `list[asyncio.Queue]` de suscriptores activos; método `publish(alert_dict: dict)` que pone en todas las queues; método `subscribe()` que retorna una nueva queue y la registra; método `unsubscribe(queue)` que la elimina de la lista
- [x] 2.2 Exponer instancia singleton `alerts_broadcaster = AlertsBroadcaster()` al final de `stream.py`

## 3. Integración broadcaster en service

- [x] 3.1 Modificar `notify_if_applicable` en `backend/app/modules/alerts/service.py`: tras el `session.commit()` que crea la fila `Alert`, llamar `alerts_broadcaster.publish({"id": alert.id, "event_id": alert.event_id, "severity": alert.severity.value, "channel": None, "delivered_at": None, "failed_at": None, "last_error": None, "retry_count": 0, "created_at": alert.created_at.isoformat()})` (importar `alerts_broadcaster` de `stream.py`)

## 4. Endpoint GET /alerts

- [x] 4.1 Agregar `list_alerts()` en `backend/app/modules/alerts/service.py`: acepta `status: str | None` (`pending`/`delivered`/`failed`), `severity: AlertSeverity | None`, `page: int`, `size: int`; retorna `(items: list[Alert], total: int)`; filtra con `WHERE` apropiado; ordena por `created_at DESC`; aplica `OFFSET/LIMIT`
- [x] 4.2 Agregar schema `AlertPaginatedResponse(BaseModel)` en `backend/app/modules/alerts/router.py`: campos `items: list[AlertResponse]`, `total: int`, `page: int`, `size: int`; `AlertResponse` existente ya tiene todos los campos pero agregar `delivered_at: datetime | None`
- [x] 4.3 Agregar endpoint `GET /alerts` en `backend/app/modules/alerts/router.py` con query params `page: int = 1`, `size: int = 50` (máx 100), `status: str | None = None`, `severity: AlertSeverity | None = None`; requiere JWT admin; retorna `AlertPaginatedResponse`

## 5. Endpoint GET /alerts/stream

- [x] 5.1 Agregar función `_get_current_user_from_token(token: str = Query(...))` en `backend/app/modules/alerts/router.py` que valida el JWT del query param y retorna el usuario admin (reutilizar lógica de `require_admin` / `get_current_user` de `core/deps.py`)
- [x] 5.2 Agregar función generadora async `_alert_event_generator(request: Request, token: str)` en `backend/app/modules/alerts/router.py` (o `stream.py`): (a) valida auth, (b) lee `Last-Event-ID` header y hace replay de alertas con `id > last_id` desde DB, (c) subscribe al `alerts_broadcaster`, (d) en loop: `asyncio.wait_for(queue.get(), timeout=15.0)` — si hay evento lo emite como SSE `"id: {id}\ndata: {json}\n\n"`, si timeout emite `": keepalive\n\n"`, (e) al finalizar (GeneratorExit / desconexión), llama `alerts_broadcaster.unsubscribe(queue)`
- [x] 5.3 Agregar endpoint `GET /alerts/stream` en `backend/app/modules/alerts/router.py` que retorna `EventSourceResponse` (de `sse_starlette`) con el generador de 5.2; media type `text/event-stream`; no requiere `Depends` para auth (la auth va dentro del generador via query param `token`)

## 6. Tests

- [x] 6.1 Crear `backend/tests/alerts/test_broadcaster.py`: test que instancia `AlertsBroadcaster`, subscribe 2 queues, llama `publish({"id": 1, ...})`, verifica que ambas queues reciben el dict; test que `unsubscribe` elimina la queue
- [x] 6.2 Agregar tests en `backend/tests/alerts/test_service.py` para `list_alerts()`: filtro `status=pending`, `status=delivered`, `status=failed`, filtro `severity=critical`, paginación `page=2 size=1`
- [x] 6.3 Agregar tests en `backend/tests/alerts/test_router.py` para `GET /alerts`: sin filtros retorna todo; filtro `status=failed`; filtro `severity=high`; paginación; sin auth → 401
- [x] 6.4 Agregar test para `GET /alerts/stream` en `backend/tests/alerts/test_router.py`: token inválido → 401; token válido → conexión SSE establecida (verifica Content-Type `text/event-stream`)
- [x] 6.5 Agregar test para replay via `Last-Event-ID` en `backend/tests/alerts/test_router.py`: crear 3 alertas en DB, conectar con `Last-Event-ID: <id_primera - 1>`, verificar que las 3 alertas se emiten en el stream de replay

## 7. Commit

- [x] 7.1 Commit `feat(backend): add SSE alerts stream and full alerts listing (C16)`
