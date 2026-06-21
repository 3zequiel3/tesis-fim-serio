## Context

C15 creó la tabla `alerts` unificada (D6) y el módulo `backend/app/modules/alerts/notifier.py` que inserta filas de forma asíncrona post-ingesta. El frontend aún no tiene canal de tiempo real: actualmente tendría que hacer polling para ver alertas nuevas. Este change agrega el stream SSE sobre esa tabla ya existente y el listado completo paginado.

Estado actual relevante:
- `Alert` SQLModel: `id`, `event_id`, `severity`, `channel`, `delivered_at`, `failed_at`, `last_error`, `retry_count`, `created_at`.
- `notifier.py` crea la fila en `alerts` y luego intenta el envío al canal n8n/SMTP/log_only.
- Backend single-instance (RN-76) — no hay coordinación multi-worker.

## Goals / Non-Goals

**Goals:**
- Exponer `GET /alerts/stream` como SSE autenticado que emite cada alerta nueva en tiempo real.
- Exponer `GET /alerts` con listado paginado de todo el historial de alertas.
- Reconexión automática del cliente sin perder alertas intermedias (via `Last-Event-ID`).

**Non-Goals:**
- WebSockets bidireccionales.
- Notificaciones push a dispositivos móviles.
- Multi-instance fan-out (el backend es single-instance, RN-76).
- Modificar la lógica de creación de alertas (responsabilidad de C15/notifier.py).

## Decisions

### D-SSE-1: In-process broadcaster con `asyncio.Queue` por suscriptor

**Decisión**: `stream.py` expone un singleton `AlertsBroadcaster` que mantiene una lista de `asyncio.Queue` activas (una por conexión SSE). Cuando `notifier.py` crea una fila en `alerts`, llama a `broadcaster.publish(alert_dict)`. Cada conexión SSE consume de su propia queue vía `asyncio.wait_for`.

**Alternativas descartadas**:
- *Valkey pub-sub*: overhead innecesario para backend single-instance (RN-76); agrega dependencia de conectividad en el hot path de alertas.
- *Long polling / polling del frontend*: más simple pero introduce latencia y carga innecesaria en DB.
- *WebSockets*: bidireccional, más complejo; SSE es suficiente para un flujo read-only.

### D-SSE-2: Auth via query param `?token=<access_token>`

**Decisión**: El endpoint SSE acepta el JWT como query param `token` porque la API nativa `EventSource` del browser no soporta headers customizados. El servidor valida el JWT igual que `get_current_user`.

**Alternativa descartada**: Cookie httpOnly — requiere que el browser envíe cookie al endpoint SSE; funcionaría pero acopla la auth al mecanismo de cookie del refresh token.

### D-SSE-3: Replay de alertas perdidas via `Last-Event-ID`

**Decisión**: Cada evento SSE lleva `id: <alert.id>` (entero). Al reconectar, el browser envía `Last-Event-ID` header. El handler consulta `SELECT * FROM alerts WHERE id > last_event_id ORDER BY id ASC` y re-emite esas filas antes de suscribirse al broadcaster en tiempo real.

**Garantía**: no se pierden alertas entre desconexión y reconexión. No requiere buffer en memoria.

### D-SSE-4: Keepalive comment cada 15s

**Decisión**: El handler emite `: keepalive\n\n` cada 15s si no hay eventos nuevos, para prevenir que proxies/load balancers corten la conexión idle.

## Risks / Trade-offs

- **[Risk] Memory leak de queues huérfanas** → El broadcaster elimina la queue de su lista cuando el generador del SSE recibe `GeneratorExit` (cliente desconectado). FastAPI/Starlette garantiza que el `async for` del `EventSourceResponse` cierra el generador al desconectarse el cliente.
- **[Risk] Spike de reconexiones simultáneas** → Cada reconexión hace una query DB de replay. En caso de restart del backend con muchos clientes, habrá N queries simultáneas. Mitigación: el índice existente en `alerts.id` (PK) hace esta query barata.
- **[Trade-off] token en URL** → El access token queda en access logs del servidor. Mitigación: el access token tiene TTL corto (15min); los logs deben ser tratados como secretos (ya cubierto por logging sanitizado de C02).
