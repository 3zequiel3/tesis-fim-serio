# sse-alerts Specification

## Purpose
Stream SSE autenticado sobre la tabla `alerts` para entrega de alertas en tiempo real al frontend, con replay via `Last-Event-ID` y listado paginado completo. Implementado en C16 (backend-sse-alerts).
## Requirements
### Requirement: GET /alerts/stream — Stream SSE autenticado de alertas

El sistema SHALL exponer `GET /alerts/stream` que retorna un stream Server-Sent Events (Content-Type: `text/event-stream`). La autenticación MUST realizarse via query param `?ticket=<ticket>` emitido por `POST /alerts/stream-ticket` (D64/RN-158). El sistema MUST consumir el ticket de forma atómica con `GETDEL` sobre `fim:sse_ticket:<sha256(ticket)>` antes de abrir el stream, de modo que un mismo ticket habilite como máximo una conexión. Un ticket ausente, inexistente, vencido o ya consumido MUST rechazarse con 401. Tras consumir el ticket, el sistema MUST verificar que el `user_id` asociado corresponde a un usuario existente, activo y con rol admin (401 si no existe o está inactivo, 403 si no es admin) y MUST aplicar el rate limit por usuario. El endpoint MUST NOT aceptar un JWT como credencial en la URL: una request con `?token=<jwt>` y sin `?ticket=` MUST rechazarse con 401 aunque el JWT sea válido. Cada evento SSE MUST tener formato `id: <alert.id>\ndata: <alert JSON>\n\n`. El sistema MUST emitir un comment de keepalive (`: keepalive\n\n`) cada 15 segundos si no hay eventos nuevos para prevenir cortes de proxies.

La sesión de DB usada para el replay inicial MUST ser liberada inmediatamente después de que el replay complete — antes de entrar al bucle de eventos en tiempo real. La sesión no MUST permanecer abierta durante el lifetime de la conexión SSE.

La cola interna por conexión MUST ser creada con `asyncio.Queue(maxsize=100)`. Cuando la cola está llena (QueueFull), el evento nuevo MUST ser descartado (política drop-newest) y MUST registrarse un log de nivel WARNING con el `agent_id` o contexto relevante.

#### Scenario: Cliente recibe alerta nueva en tiempo real
- **WHEN** se ingiere un evento critical y se crea una fila en `alerts`, y hay al menos un cliente conectado al stream SSE con un ticket válido
- **THEN** el cliente recibe el evento SSE con `id: <alert.id>` y `data: {JSON del alert}` en menos de 1 segundo

#### Scenario: Ticket válido abre el stream y se consume
- **WHEN** un admin obtiene un ticket y hace `GET /alerts/stream?ticket=<ticket>` dentro de los 30 segundos
- **THEN** la respuesta es 200 con Content-Type `text/event-stream`
- **AND** la clave `fim:sse_ticket:<sha256(ticket)>` ya no existe en Valkey

#### Scenario: Ticket reutilizado retorna 401
- **WHEN** un ticket ya abrió una conexión y se hace otro `GET /alerts/stream?ticket=<mismo ticket>`
- **THEN** la segunda conexión se rechaza con HTTP 401

#### Scenario: Consumo concurrente del mismo ticket habilita una sola conexión
- **WHEN** dos requests `GET /alerts/stream?ticket=<ticket>` con el mismo ticket llegan en paralelo
- **THEN** exactamente una recibe 200 y la otra recibe 401

#### Scenario: Ticket vencido retorna 401
- **WHEN** se hace `GET /alerts/stream?ticket=<ticket>` después de que venció su TTL de 30 segundos
- **THEN** la conexión se rechaza con HTTP 401

#### Scenario: Ticket inexistente retorna 401
- **WHEN** se hace `GET /alerts/stream?ticket=invalid`
- **THEN** la conexión se rechaza con HTTP 401

#### Scenario: Ticket ausente retorna 401
- **WHEN** se hace `GET /alerts/stream` sin query param `ticket`
- **THEN** la conexión se rechaza con HTTP 401 (no 422)

#### Scenario: JWT en query string no autentica
- **WHEN** se hace `GET /alerts/stream?token=<access_token válido de un admin>` sin `ticket`
- **THEN** la conexión se rechaza con HTTP 401

#### Scenario: Ticket de un usuario desactivado retorna 401
- **WHEN** un admin obtiene un ticket, su usuario se desactiva y luego se usa el ticket en `GET /alerts/stream`
- **THEN** la conexión se rechaza con HTTP 401

#### Scenario: Sin eventos — keepalive emitido
- **WHEN** no se crean alertas durante 15 segundos con un cliente conectado
- **THEN** el cliente recibe al menos un comment SSE de keepalive

#### Scenario: Sesión DB liberada tras replay
- **WHEN** un cliente conecta con `Last-Event-ID` (o `last_event_id`) que desencadena replay de alertas históricas
- **THEN** la sesión de DB se cierra antes de que el handler emita el primer evento en tiempo real; el pool de conexiones no retiene la sesión durante el lifetime de la conexión SSE

#### Scenario: Cola llena descarta evento nuevo y registra WARNING
- **WHEN** la cola interna del stream tiene 100 eventos pendientes y llega un evento nuevo
- **THEN** el evento nuevo se descarta, no se encola, y se emite un log WARNING; los 100 eventos previos permanecen en la cola intactos

### Requirement: Reconexión SSE sin pérdida de alertas via Last-Event-ID

El sistema SHALL leer el último id recibido por el cliente al conectar, desde el header `Last-Event-ID` o, como equivalente en la URL (D64/RN-158, D-EV-6), desde el query param `last_event_id`. Si ambos están presentes, el header MUST prevalecer. Si hay un id presente, el sistema MUST emitir en orden ascendente todas las alertas con `id > <último id>` antes de suscribir al broadcaster en tiempo real. Luego MUST continuar emitiendo eventos nuevos normalmente. Un valor no entero MUST tratarse como `0`, igual que para el header. El query param `last_event_id` MUST NOT reemplazar la autenticación por ticket.

#### Scenario: Reconexión recupera alertas perdidas
- **WHEN** un cliente se desconecta mientras se crean 3 alertas (ids 10, 11, 12) y reconecta con `Last-Event-ID: 9`
- **THEN** el cliente recibe los eventos con ids 10, 11, 12 en orden antes de recibir eventos nuevos

#### Scenario: Reconexión con last_event_id en la URL recupera alertas perdidas
- **WHEN** un cliente se desconecta mientras se crean 3 alertas (ids 10, 11, 12) y reconecta con `GET /alerts/stream?ticket=<ticket nuevo>&last_event_id=9`
- **THEN** el cliente recibe los eventos con ids 10, 11, 12 en orden antes de recibir eventos nuevos

#### Scenario: El header prevalece sobre el query param
- **WHEN** un cliente conecta con `Last-Event-ID: 11` y `?last_event_id=9`
- **THEN** solo se reemite la alerta con id 12

#### Scenario: Reconexión sin Last-Event-ID no hace replay
- **WHEN** un cliente conecta sin header `Last-Event-ID` y sin query param `last_event_id`
- **THEN** solo recibe alertas creadas a partir de ese momento (sin replay histórico)

#### Scenario: Last-Event-ID con valor ya al día no emite nada extra
- **WHEN** un cliente reconecta con `Last-Event-ID` (o `last_event_id`) igual al id de la última alerta existente
- **THEN** no se emiten eventos de replay; el cliente recibe solo alertas nuevas

### Requirement: GET /alerts — Listado paginado completo de alertas

El sistema SHALL exponer `GET /alerts` (requiere JWT admin) que retorna todas las alertas de la tabla `alerts` ordenadas por `created_at DESC`. La respuesta SHALL ser `{"items": [...], "total": int, "page": int, "size": int}` con paginación de 50 ítems por página (query params `page` y `size`, máximo `size=100`). Cada ítem incluye todos los campos del modelo `Alert`: `id`, `event_id`, `severity`, `channel`, `delivered_at`, `failed_at`, `last_error`, `retry_count`, `created_at`. El endpoint SHALL soportar filtros opcionales:
- `status`: `pending` (sin `delivered_at` y sin `failed_at`), `delivered` (`delivered_at IS NOT NULL`), `failed` (`failed_at IS NOT NULL`)
- `severity`: `critical`, `high`, `medium`, `low`

#### Scenario: Listado sin filtros retorna todo el historial
- **WHEN** existen 3 alertas (1 delivered, 1 failed, 1 pending) y se hace `GET /alerts`
- **THEN** la respuesta contiene `total=3` con los 3 ítems ordenados por `created_at DESC`

#### Scenario: Filtro por status=failed retorna solo fallidas
- **WHEN** existen 2 alertas delivered y 1 failed, y se hace `GET /alerts?status=failed`
- **THEN** la respuesta contiene `total=1` con solo la alerta fallida

#### Scenario: Filtro por status=pending retorna alertas en tránsito
- **WHEN** existe 1 alerta sin `delivered_at` y sin `failed_at`, y se hace `GET /alerts?status=pending`
- **THEN** la respuesta contiene esa alerta

#### Scenario: Filtro por severity=critical retorna solo alertas críticas
- **WHEN** existen alertas con severidades mixed y se hace `GET /alerts?severity=critical`
- **THEN** la respuesta contiene solo alertas con `severity=critical`

#### Scenario: Paginación retorna página correcta
- **WHEN** existen 75 alertas y se hace `GET /alerts?page=2&size=50`
- **THEN** la respuesta contiene `total=75`, `page=2`, `size=50`, y `items` con las alertas 51–75

#### Scenario: Sin alertas retorna lista vacía
- **WHEN** no existen alertas en DB
- **THEN** la respuesta es `{"items": [], "total": 0, "page": 1, "size": 50}`

### Requirement: POST /alerts/stream-ticket — Emisión de ticket SSE de un solo uso (D64, RN-158)

El sistema SHALL exponer `POST /alerts/stream-ticket`, protegido por la misma dependencia `require_admin` que el resto de los endpoints de alertas (JWT en el header `Authorization`, scope completo, usuario activo, rol admin y rate limit por usuario). El endpoint SHALL generar un ticket opaco con `secrets.token_urlsafe(32)` (256 bits de entropía) y SHALL guardarlo en Valkey con TTL de 30 segundos, asociado al `user_id` del admin autenticado. La clave en Valkey MUST derivarse del SHA-256 del ticket (`fim:sse_ticket:<sha256_hex>`), de modo que el valor en claro del ticket no aparezca en el keyspace. La respuesta SHALL ser HTTP 200 con body `{"ticket": "<ticket>", "expires_in": 30}`. El valor del ticket MUST NOT registrarse en ningún log del backend.

#### Scenario: Admin autenticado obtiene un ticket
- **WHEN** un admin hace `POST /alerts/stream-ticket` con un JWT de acceso válido en `Authorization: Bearer`
- **THEN** la respuesta es 200 con `ticket` no vacío y `expires_in = 30`
- **AND** existe en Valkey la clave `fim:sse_ticket:<sha256(ticket)>` con valor igual al `user_id` y TTL menor o igual a 30 segundos

#### Scenario: Sin JWT no se emite ticket
- **WHEN** se hace `POST /alerts/stream-ticket` sin header `Authorization`
- **THEN** la respuesta es 401 y no se crea ninguna clave `fim:sse_ticket:*`

#### Scenario: Usuario no admin no obtiene ticket
- **WHEN** un usuario con rol distinto de admin hace `POST /alerts/stream-ticket` con JWT válido
- **THEN** la respuesta es 403

#### Scenario: Token con scope password_change_only no obtiene ticket
- **WHEN** un admin con JWT de scope `password_change_only` hace `POST /alerts/stream-ticket`
- **THEN** la respuesta es 403 con `detail = password_change_required`

#### Scenario: Tickets sucesivos son distintos
- **WHEN** el mismo admin pide dos tickets seguidos
- **THEN** los dos valores de `ticket` son distintos y ambos quedan guardados de forma independiente

