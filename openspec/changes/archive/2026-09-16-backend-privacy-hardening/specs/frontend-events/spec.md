## MODIFIED Requirements

### Requirement: Feed de alertas en tiempo real vía SSE

El frontend SHALL proveer `frontend/src/hooks/useAlertsSSE.ts` que abre una conexión `EventSource` a `GET /alerts/stream?ticket=<ticket>`. Antes de cada conexión y de cada reconexión, el hook SHALL obtener un ticket nuevo mediante `POST /alerts/stream-ticket` a través del cliente HTTP autenticado (JWT en header, con el refresh automático del interceptor), porque `EventSource` no admite headers y el ticket es de un solo uso (D64/RN-158). La URL del stream MUST NOT contener el access token. Cada alerta nueva recibida SHALL disparar un toast de notificación e invalidar las queries `['alerts']`, `['dashboard']` y `['alerts-failed-count']`, y el hook SHALL registrar el `lastEventId` de la última alerta recibida.

Como la reconexión nativa de `EventSource` reutilizaría la URL con un ticket ya consumido, ante cualquier error de la conexión el hook SHALL cerrar el `EventSource` de inmediato y SHALL reabrir manualmente con un ticket nuevo tras un backoff exponencial (1 s inicial, duplicando hasta un máximo de 30 s, reiniciado al abrir con éxito). Al reabrir, si ya recibió alguna alerta, el hook SHALL pasar el último id en el query param `last_event_id` para no perder alertas (D-EV-6). Tras una reapertura exitosa, el hook SHALL invalidar las mismas queries para reflejar cambios ocurridos durante el corte. Si la obtención del ticket falla por sesión inválida (401 tras el intento de refresh) o falta de permisos (403), el hook SHALL dejar de reintentar. La conexión SHALL depender de la existencia de sesión y no del valor puntual del access token: una rotación del access token MUST NOT reabrir el stream. El hook SHALL cerrar la conexión y cancelar cualquier reintento pendiente al desmontar o al cerrar la sesión.

#### Scenario: Alerta nueva dispara un toast
- **WHEN** el backend emite un evento SSE de alerta y el hook está conectado
- **THEN** el frontend muestra un toast con la información de la alerta
- **AND** invalida las queries `['alerts']`, `['dashboard']` y `['alerts-failed-count']`

#### Scenario: La conexión usa un ticket y no el access token
- **WHEN** el hook se monta con una sesión activa
- **THEN** hace `POST /alerts/stream-ticket` antes de crear el `EventSource`
- **AND** la URL del `EventSource` contiene `ticket=<ticket recibido>` y no contiene `token=` ni el valor del access token

#### Scenario: La conexión se cierra al desmontar
- **WHEN** el componente que usa `useAlertsSSE` se desmonta
- **THEN** la conexión `EventSource` se cierra
- **AND** no se ejecuta ningún reintento programado

#### Scenario: Reconexión tras corte con ticket nuevo y último id
- **WHEN** el hook recibió la alerta con id 9 y la conexión SSE emite un error
- **THEN** el hook cierra el `EventSource` sin esperar la reconexión nativa
- **AND** tras el backoff pide un ticket nuevo y abre un `EventSource` nuevo con `ticket=<ticket nuevo>` y `last_event_id=9`

#### Scenario: Reconexión sin alertas previas no envía last_event_id
- **WHEN** la conexión falla antes de recibir cualquier alerta
- **THEN** la nueva URL contiene un ticket nuevo y no contiene `last_event_id`

#### Scenario: Backoff exponencial acotado
- **WHEN** la obtención del ticket o la conexión fallan de forma consecutiva por errores de red
- **THEN** los reintentos se programan a 1 s, 2 s, 4 s, … hasta un máximo de 30 s entre intentos
- **AND** una apertura exitosa reinicia el backoff a 1 s

#### Scenario: Sesión inválida detiene los reintentos
- **WHEN** `POST /alerts/stream-ticket` responde 401 tras el intento de refresh o responde 403
- **THEN** el hook no programa más reintentos

#### Scenario: Rotación del access token no reabre el stream
- **WHEN** el access token se renueva mientras el stream está abierto
- **THEN** el `EventSource` existente permanece abierto y no se pide un ticket nuevo
