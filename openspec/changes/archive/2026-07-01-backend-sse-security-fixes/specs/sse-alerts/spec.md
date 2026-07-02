## MODIFIED Requirements

### Requirement: GET /alerts/stream — Stream SSE autenticado de alertas

El sistema SHALL exponer `GET /alerts/stream` que retorna un stream Server-Sent Events (Content-Type: `text/event-stream`). La autenticación MUST realizarse via query param `?token=<access_token>` (JWT válido, rol admin); token inválido o ausente → 401. Cada evento SSE MUST tener formato `id: <alert.id>\ndata: <alert JSON>\n\n`. El sistema MUST emitir un comment de keepalive (`: keepalive\n\n`) cada 15 segundos si no hay eventos nuevos para prevenir cortes de proxies.

La sesión de DB usada para el replay inicial MUST ser liberada inmediatamente después de que el replay complete — antes de entrar al bucle de eventos en tiempo real. La sesión no MUST permanecer abierta durante el lifetime de la conexión SSE.

La cola interna por conexión MUST ser creada con `asyncio.Queue(maxsize=100)`. Cuando la cola está llena (QueueFull), el evento nuevo MUST ser descartado (política drop-newest) y MUST registrarse un log de nivel WARNING con el `agent_id` o contexto relevante.

#### Scenario: Cliente recibe alerta nueva en tiempo real
- **WHEN** se ingiere un evento critical y se crea una fila en `alerts`, y hay al menos un cliente conectado al stream SSE
- **THEN** el cliente recibe el evento SSE con `id: <alert.id>` y `data: {JSON del alert}` en menos de 1 segundo

#### Scenario: Token inválido retorna 401
- **WHEN** se hace `GET /alerts/stream?token=invalid`
- **THEN** la conexión se rechaza con HTTP 401

#### Scenario: Token ausente retorna 401
- **WHEN** se hace `GET /alerts/stream` sin query param `token`
- **THEN** la conexión se rechaza con HTTP 401

#### Scenario: Sin eventos — keepalive emitido
- **WHEN** no se crean alertas durante 15 segundos con un cliente conectado
- **THEN** el cliente recibe al menos un comment SSE de keepalive

#### Scenario: Sesión DB liberada tras replay
- **WHEN** un cliente conecta con `Last-Event-ID` que desencadena replay de alertas históricas
- **THEN** la sesión de DB se cierra antes de que el handler emita el primer evento en tiempo real; el pool de conexiones no retiene la sesión durante el lifetime de la conexión SSE

#### Scenario: Cola llena descarta evento nuevo y registra WARNING
- **WHEN** la cola interna del stream tiene 100 eventos pendientes y llega un evento nuevo
- **THEN** el evento nuevo se descarta, no se encola, y se emite un log WARNING; los 100 eventos previos permanecen en la cola intactos
