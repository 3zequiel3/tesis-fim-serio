## ADDED Requirements

### Requirement: Consumer dedicado del stream event_ack (command_ack)

El backend MUST arrancar un consumer dedicado del stream Valkey `event_ack` como task del lifespan de `main.py`, análogo a `run_consumer` (`events/consumer.py`) y `run_heartbeat_consumer`. El consumer MUST usar un consumer group Valkey propio (p. ej. `fim-command-ack`) para no perder mensajes entre reinicios del backend. Cada `command_ack` procesado MUST hacer el I/O de DB vía `run_in_executor` (D21) para no bloquear el event loop. El concepto se denomina **`command_ack`** para desambiguarlo del ack de ingesta homónimo de RN-40/RN-54 (que el backend publica en el stream `commands`); el nombre del stream Valkey (`event_ack`) no cambia.

#### Scenario: El consumer arranca en el lifespan
- **WHEN** el backend inicia
- **THEN** existe una task activa que lee del stream `event_ack` con un consumer group dedicado, registrada junto a los consumers de `events` y `agent_heartbeat`

#### Scenario: El consumer se detiene cooperativamente en el shutdown
- **WHEN** el backend recibe la señal de shutdown (`stop_event`)
- **THEN** la task del consumer de `command_ack` se cancela y se espera vía `asyncio.gather` como el resto de los consumers

#### Scenario: I/O de DB fuera del event loop
- **WHEN** el consumer procesa un `command_ack`
- **THEN** la escritura en DB ocurre vía `run_in_executor`, no en el hilo del event loop (D21)

---

### Requirement: Validación estructural y de firma del command_ack

El payload de `command_ack` publicado por el agente (`agent/commands.py::_publish_ack`) contiene `command_id`, `command_type`, `event_id`, `agent_id`, `status` (`"ok" | "error"`), `error`, `timestamp` y **`signature`** (HMAC-SHA256, decisión del usuario 2026-07-02 — cierra la asimetría con `events`/`agent_heartbeat`, que ya viajan firmados por RN-79). El consumer MUST validar estructuralmente el payload: descartar con log WARNING cualquier mensaje sin `command_id`, y descartar sin efecto cualquier `command_id` que no corresponda a una fila `PublishedCommand` conocida. El consumer MUST además verificar la firma HMAC-SHA256 contra el `shared_secret` del agente indicado en `agent_id`, usando `verify_payload` (mismo helper que `events/consumer.py`), y MUST rechazar (descartar sin efecto) cualquier ack cuya firma sea inválida o cuyo secret no sea resoluble. El consumer MUST hacer `XACK` de todo mensaje leído (procesado, descartado o rechazado) para no reprocesarlo.

#### Scenario: Ack sin command_id se descarta
- **WHEN** llega un mensaje a `event_ack` cuyo payload no tiene `command_id`
- **THEN** el mensaje se descarta con log WARNING y se hace `XACK` sin tocar la DB

#### Scenario: Ack de un command_id desconocido se descarta
- **WHEN** llega un `command_ack` cuyo `command_id` no existe en `published_commands`
- **THEN** el mensaje se descarta con log (nivel INFO/WARNING) y se hace `XACK` sin actualizar ninguna fila

#### Scenario: Ack con firma HMAC inválida se rechaza
- **WHEN** llega un `command_ack` cuyo `command_id` es conocido pero `signature` no verifica contra el `shared_secret` del `agent_id` declarado
- **THEN** el mensaje se rechaza con log WARNING, la fila `PublishedCommand` no se actualiza, y se hace `XACK`

#### Scenario: Ack de un command_id conocido con firma válida se procesa
- **WHEN** llega un `command_ack` cuyo `command_id` existe en `published_commands` y la firma verifica
- **THEN** la fila correspondiente se actualiza y el mensaje se hace `XACK`

---

### Requirement: Tracking de ejecución en PublishedCommand

El modelo `PublishedCommand` (`rules/models.py`) MUST incorporar las columnas: `command_id` (str, único, indexado, nulo permitido para filas históricas), `ack_status` (str: `pending | acked | failed | timeout`, nulo para comandos que el agente no confirma), `acked_at` (datetime, nulo hasta la confirmación) y `error` (str, nulo salvo falla reportada por el agente). La columna `status` preexistente (semántica de outbox `pending | published`, H6/D9/D10) NO se reutiliza ni se altera: el estado de ejecución vive en la columna separada `ack_status`. Una migración SQL idempotente en `backend/db/migrations/` MUST agregar las columnas con `ADD COLUMN IF NOT EXISTS` y crear un índice único sobre `command_id`.

#### Scenario: Migración idempotente
- **WHEN** el script SQL de migración se ejecuta dos veces
- **THEN** no produce error en la segunda ejecución (`ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`)

#### Scenario: La columna status de outbox no se modifica
- **WHEN** se aplica la migración
- **THEN** la columna `status` (`pending | published`) conserva su semántica de outbox y su índice, sin cambios; el estado de ejecución se lee/escribe exclusivamente en `ack_status`

#### Scenario: command_id único correlaciona ack con comando
- **WHEN** se busca la fila `PublishedCommand` de un `command_ack` por su `command_id`
- **THEN** la búsqueda usa el índice único sobre `command_id` y retorna a lo sumo una fila

---

### Requirement: Todo comando confirmable persiste su command_id al publicarse

Todo comando que el agente confirma vía `command_ack` (`baseline_update`, `restore_file`, `quarantine_file`, `update_config`, `rescan_baseline`) MUST persistir en su fila `PublishedCommand` el mismo `command_id` que viaja en el payload publicado al stream `commands`, con `ack_status = pending`. El `command_id` MUST generarse una sola vez y usarse tanto en el payload firmado como en la fila persistida. Los comandos de tipo `rule_sync` (broadcast, sin handler de confirmación en el agente) MUST persistirse con `ack_status = NULL` para quedar excluidos del barrido de timeout.

#### Scenario: baseline_update persiste command_id
- **WHEN** el backend publica un `baseline_update` al stream `commands`
- **THEN** la fila `PublishedCommand` correspondiente guarda el mismo `command_id` del payload y `ack_status = pending`

#### Scenario: update_config y rescan_baseline registran PublishedCommand
- **WHEN** el backend publica `update_config` o `rescan_baseline` (`agents/streams.py`)
- **THEN** se crea una fila `PublishedCommand` con su `command_id` y `ack_status = pending` (hoy no se crea ninguna fila para estos tipos)

#### Scenario: rule_sync no participa del timeout
- **WHEN** el backend publica un comando `rule_sync` (broadcast)
- **THEN** su fila `PublishedCommand` tiene `ack_status = NULL` y el barrido de timeout no la considera

---

### Requirement: command_ack actualiza el estado de ejecución del comando

Al recibir un `command_ack` correlacionado con una fila `PublishedCommand`, el consumer MUST actualizar esa fila: si `status == "ok"` → `ack_status = acked`, `acked_at = now`, `error = NULL`; si `status == "error"` → `ack_status = failed`, `acked_at = now`, `error = <mensaje del agente>`. Una fila ya en estado terminal (`acked` o `failed`) MUST ser idempotente ante un ack repetido (no re-procesar efectos secundarios).

#### Scenario: Ack ok marca acked
- **WHEN** llega un `command_ack` con `status = "ok"` para un comando `pending`
- **THEN** la fila queda `ack_status = acked`, `acked_at` poblado y `error = NULL`

#### Scenario: Ack error marca failed y guarda el mensaje
- **WHEN** llega un `command_ack` con `status = "error"` y un `error` no nulo
- **THEN** la fila queda `ack_status = failed`, `acked_at` poblado y `error` con el mensaje reportado por el agente

#### Scenario: Ack repetido es idempotente
- **WHEN** llega un segundo `command_ack` para un comando ya `acked`
- **THEN** la fila no cambia de estado y los efectos secundarios (baseline, ruleset_version_applied) no se re-aplican

---

### Requirement: command_ack de baseline_update reconcilia baseline_entries (D1/RN-104)

Cuando el `command_ack` confirma exitosamente (`status = "ok"`) un comando de tipo `baseline_update`, el consumer MUST actualizar la fila correspondiente en `baseline_entries` del backend, reutilizando el upsert existente (`actions/service.py`), de modo que el baseline del backend refleje el hash aprobado que el agente aplicó (RN-104). La reconciliación MUST usar el `event_id`/`path`/`agent_id` asociados al comando para localizar la entrada.

#### Scenario: Ack ok de baseline_update actualiza baseline_entries
- **WHEN** llega un `command_ack` con `status = "ok"` para un `baseline_update`
- **THEN** la fila de `baseline_entries` del `path`/`agent_id` correspondiente se actualiza al hash aprobado (upsert)

#### Scenario: Ack error de baseline_update no toca baseline_entries
- **WHEN** llega un `command_ack` con `status = "error"` para un `baseline_update`
- **THEN** `baseline_entries` no se modifica y la fila queda `ack_status = failed`

---

### Requirement: ruleset_version_applied avanza solo al confirmar (D5/RN-106)

Cuando el `command_ack` confirma exitosamente (`status = "ok"`) un comando de tipo `update_config` o `baseline_update` que lleva `ruleset_version`, el consumer MUST avanzar `Agent.ruleset_version_applied` al `ruleset_version` de ese comando, de forma monotónica (nunca retrocede). Este es el único punto donde `ruleset_version_applied` avanza: la publicación del comando NO lo avanza (ver la capability `backend-agent-management`).

#### Scenario: Ack ok de update_config avanza ruleset_version_applied
- **WHEN** llega un `command_ack` con `status = "ok"` para un `update_config` con `ruleset_version = N`
- **THEN** `Agent.ruleset_version_applied` pasa a `N` si `N > ruleset_version_applied` actual

#### Scenario: Comando no confirmado no avanza ruleset_version_applied
- **WHEN** el backend publica `update_config` pero nunca llega su `command_ack`
- **THEN** `Agent.ruleset_version_applied` conserva su valor anterior

#### Scenario: Avance monotónico
- **WHEN** llega un `command_ack` cuyo `ruleset_version` es menor o igual al `ruleset_version_applied` actual
- **THEN** `ruleset_version_applied` no cambia

---

### Requirement: Barrido periódico de timeout de comandos sin confirmar

El backend MUST ejecutar un barrido periódico (patrón `heartbeat_consumer._sweep_offline`, vía `run_in_executor`) que marque `ack_status = timeout` toda fila `PublishedCommand` con `ack_status = pending` cuyo `published_at` sea anterior a `now - umbral`. El umbral MUST ser configurable (`core/config.py`, con un default explícito). Las filas con `ack_status = NULL` (p. ej. `rule_sync`) MUST quedar excluidas del barrido.

#### Scenario: Comando pending vencido pasa a timeout
- **WHEN** un comando lleva `ack_status = pending` más tiempo que el umbral configurado
- **THEN** el barrido lo marca `ack_status = timeout`

#### Scenario: Comando confirmado no se marca timeout
- **WHEN** un comando ya está `acked` o `failed`
- **THEN** el barrido no lo toca

#### Scenario: rule_sync excluido del barrido
- **WHEN** existe una fila `rule_sync` con `ack_status = NULL` más antigua que el umbral
- **THEN** el barrido no la marca `timeout`

#### Scenario: Umbral configurable
- **WHEN** se configura el umbral de timeout en `core/config.py`
- **THEN** el barrido usa ese valor; si no se configura, usa el default documentado
