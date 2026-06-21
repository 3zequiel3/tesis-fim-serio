## ADDED Requirements

### Requirement: GET /alerts/stream — Stream SSE autenticado de alertas

El sistema SHALL exponer `GET /alerts/stream` que retorna un stream Server-Sent Events (Content-Type: `text/event-stream`). La autenticación MUST realizarse via query param `?token=<access_token>` (JWT válido, rol admin); token inválido o ausente → 401. Cada evento SSE MUST tener formato `id: <alert.id>\ndata: <alert JSON>\n\n`. El sistema MUST emitir un comment de keepalive (`: keepalive\n\n`) cada 15 segundos si no hay eventos nuevos para prevenir cortes de proxies.

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

---

### Requirement: Reconexión SSE sin pérdida de alertas via Last-Event-ID

El sistema SHALL leer el header `Last-Event-ID` al reconectar. Si está presente, MUST emitir en orden ascendente todas las alertas con `id > Last-Event-ID` antes de suscribir al broadcaster en tiempo real. Luego MUST continuar emitiendo eventos nuevos normalmente.

#### Scenario: Reconexión recupera alertas perdidas
- **WHEN** un cliente se desconecta mientras se crean 3 alertas (ids 10, 11, 12) y reconecta con `Last-Event-ID: 9`
- **THEN** el cliente recibe los eventos con ids 10, 11, 12 en orden antes de recibir eventos nuevos

#### Scenario: Reconexión sin Last-Event-ID no hace replay
- **WHEN** un cliente conecta sin header `Last-Event-ID`
- **THEN** solo recibe alertas creadas a partir de ese momento (sin replay histórico)

#### Scenario: Last-Event-ID con valor ya al día no emite nada extra
- **WHEN** un cliente reconecta con `Last-Event-ID` igual al id de la última alerta existente
- **THEN** no se emiten eventos de replay; el cliente recibe solo alertas nuevas

---

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
