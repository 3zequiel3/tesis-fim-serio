## Context

El loop de confirmación de ejecución de comandos está roto: el agente publica `command_ack` en el stream Valkey `event_ack` (`agent/commands.py::_publish_ack`, `STREAM_EVENT_ACK = "event_ack"`), pero el backend (`main.py` lifespan) solo arranca consumers para `events` (`events/consumer.py::run_consumer`) y `agent_heartbeat` (`agents/heartbeat_consumer.py::run_heartbeat_consumer`). Nadie lee `event_ack`.

Estado actual relevante del código:
- `PublishedCommand` (`backend/app/modules/rules/models.py:40-63`): tiene `id`, `command_type`, `target_agent_id`, `ruleset_version`, `payload`, `status` (`"pending" | "published"` — **outbox** H6/D9/D10, indexado) y `published_at`. NO tiene `command_id` ni estado de ejecución.
- `actions/streams.py` (`publish_baseline_update`, `publish_restore_file`, `publish_quarantine_file`): generan `command_id` vía `uuid.uuid4()` en el payload pero lo **descartan**; `_record_published_command(...)` no lo recibe ni lo persiste.
- `agents/streams.py` (`publish_update_config`, `publish_rescan_baseline`): generan `command_id` en el payload pero **no crean ninguna fila `PublishedCommand`**.
- `agents/service.py::update_agent_config` (líneas 155-161): avanza `agent.ruleset_version_applied = new_version` al **publicar** — viola D5/RN-106.
- El `command_ack` del agente, a la fecha del diseño inicial, no estaba firmado con HMAC. **Decisión del usuario (2026-07-02, ver nota en D30 del appendix)**: se firma. `_publish_ack` (`agent/commands.py`) ahora incluye `signature` (HMAC-SHA256 vía `sign_payload`, ya importado de `agent/streams.py` — el mismo helper que verifica los comandos entrantes). Payload firmado: `{command_id, command_type, event_id, agent_id, status: "ok"|"error", error, timestamp, signature}`.
- `baseline_entries` (`agents/models.py::BaselineEntry`) y su upsert (`actions/service.py::_upsert_baseline_entry`) ya existen — se reutilizan para D1/RN-104.
- Consumer group de referencia: `events/consumer.py` usa `xgroup_create(STREAM_EVENTS, "fim-backend", id="0", mkstream=True)` + `xreadgroup` + `xack`, con `run_in_executor` para el I/O de DB (D21).

Restricciones: Python 3.13 + FastAPI async, Valkey Streams, PostgreSQL 18.3 sin Alembic (D3 — migraciones SQL idempotentes numeradas en `backend/db/migrations/`). D30/RN-124 cerrada en los appendices el 2026-07-02. El agente NO se toca.

## Goals / Non-Goals

**Goals:**
- Consumer dedicado de `event_ack` con consumer group propio, arrancado en el lifespan y detenido cooperativamente.
- `PublishedCommand` con tracking de ejecución (`command_id`, `ack_status`, `acked_at`, `error`) y migración idempotente.
- Persistir `command_id` en todos los comandos confirmables al publicarlos (incluyendo `update_config`/`rescan_baseline`, que hoy no crean fila).
- Reconciliar `baseline_entries` (D1/RN-104) y `ruleset_version_applied` (D5/RN-106) al confirmar.
- Barrido de timeout configurable.
- Indicador secundario de estado de ejecución en el frontend, sin nuevo `EventStatus`.
- **Firmar el `command_ack` con HMAC-SHA256** (`agent/commands.py::_publish_ack`, vía `sign_payload`) y **verificar la firma en el consumer** (`verify_payload`), rechazando acks con firma inválida — mismo patrón que `events/consumer.py:191`. Decisión del usuario (2026-07-02): cierra la asimetría con `events`/`agent_heartbeat`, que ya viajan firmados (RN-79). Ver nota en el appendix D30 de `arquitectura_stack.md`.

**Non-Goals:**
- Nuevos endpoints HTTP o cambios en el protocolo de mensajes de `event_ack` (el nombre del stream y el esqueleto del payload no cambian, solo se agrega `signature`).
- Nuevos valores en la máquina de estados del evento (RN-72 intacto).
- Reintentos de comandos vencidos (`timeout` es informativo; el re-envío queda fuera de scope).

## Decisions

### D-1 — Resolución de la colisión de columna: nueva columna `ack_status` (NO renombrar `status`)

**Problema:** `PublishedCommand.status` ya existe con semántica de **outbox** (`pending | published` — indica si el `XADD` a Valkey se ejecutó, H6/D9/D10). El estado de **ejecución** confirmado por el agente (`pending | acked | failed | timeout`) es un concepto distinto y no puede reusar esa columna. El appendix D30 deja la nomenclatura abierta: "campo separado (ej. `ack_status`) o renombrar el existente a `delivery_status`".

**Elección:** Agregar una **columna nueva `ack_status`** (`pending | acked | failed | timeout`, nula para comandos no confirmables) y **dejar `status` intacta** como columna de outbox.

**Por qué (no renombrar):**
- **Blast radius mínimo.** `status` está referenciada por el outbox publisher (`publish_pending_commands`), la migración `003_add_published_commands_outbox.sql`, el índice `ix_published_commands_status` y código/tests de C34. Renombrar a `delivery_status` implica `RENAME COLUMN` + backfill + reindex + tocar todos esos call sites — un diff más grande y riesgoso a cambio de cero ganancia funcional.
- **Separación de conceptos.** `status` responde "¿se publicó a Valkey?" (entrega/outbox); `ack_status` responde "¿el agente ejecutó el comando?" (ejecución). Dos preguntas ortogonales → dos columnas. Sobrecargar una sola columna con ambas semánticas sería peor diseño.
- **RN-124 fija el conjunto de valores de ejecución** (`pending | acked | failed | timeout`); el nombre `ack_status` es descriptivo y no colisiona léxicamente con la máquina de estados del evento.

**Nota sobre el "pending" duplicado:** tanto `status` (outbox) como `ack_status` (ejecución) tienen un valor `pending`, pero en columnas separadas con significados distintos (`pending`=por-publicar vs `pending`=por-confirmar). Se documenta en el docstring del modelo para evitar confusión.

**Alternativa considerada:** renombrar `status` → `delivery_status` y usar `status` para ejecución. Descartada: cosmética, con costo de migración y refactor de call sites sin beneficio.

### D-2 — Consumer group dedicado sobre `event_ack` (durable), patrón `events/consumer.py`

**Elección:** El consumer usa un consumer group Valkey propio (`fim-command-ack`) con `xgroup_create(..., id="0", mkstream=True)` + `xreadgroup` + `xack`, replicando `events/consumer.py`. NO se usa el patrón `xread last_id="$"` del heartbeat consumer.

**Por qué:** el heartbeat con `last_id="$"` acepta perder mensajes en reinicios (D28, tradeoff explícito: un heartbeat perdido se recupera en <30s). Un `command_ack` perdido dejaría el comando en `pending` hasta que el barrido lo marque `timeout` — un falso `timeout` sobre un comando que sí se ejecutó. El consumer group entrega desde el último `XACK`, evitando esa pérdida. El appendix D30 pide explícitamente "el mismo patrón que `events/consumer.py` (consumer group Valkey)".

**Arranque/parada:** una task más en el lifespan (`main.py`), cancelada y `gather`-eada junto a las existentes vía el `stop_event` compartido.

**Verificación HMAC + autorización cross-agent:** antes de aplicar cualquier efecto, el consumer resuelve el `shared_secret` desde **`cmd.target_agent_id`** — el dueño del comando según la fila persistida (autoridad en DB) — **no** desde el `agent_id` que viaja en el payload (controlado por el emisor). Motivo: el stream `commands` es broadcast, así que resolver el secret por `payload.agent_id` permitiría un *confused deputy* — un agente A con su propio secret válido firmaría un ack para el `command_id` de otra víctima V y el consumer lo aceptaría, avanzando el `ruleset_version_applied`/baseline de V. Resolviendo el secret por `cmd.target_agent_id`, solo el agente dueño del comando (el que posee ese secret) puede producir un ack que verifique. Como defensa explícita adicional, si el payload trae un `agent_id` distinto de `cmd.target_agent_id`, el ack se rechaza (log WARNING, sin tocar `cmd`) antes de la verificación. Luego llama `verify_payload(secret, payload)`. Un ack con firma inválida se descarta con log WARNING (sin tocar `PublishedCommand`) y de todos modos se hace `XACK` (no es reprocesable — reintentar no cambia el resultado de una firma inválida). **`command_type` y `event_id` para las decisiones de reconciliación se leen de la fila (`cmd.command_type`, `cmd.event_id`, D-1bis), NUNCA del payload** — del payload solo se toman `status` y `error`, que son lo que el agente legítimamente reporta; así un ack firmado no puede declarar `command_type="baseline_update"` + `event_id` arbitrario para envenenar el baseline saltándose el approve.

### D-1bis — `PublishedCommand.event_id`: correlación evento → estado de ejecución para el frontend

**Problema:** la capability `frontend-events` (6.1) necesita exponer, por evento, el `ack_status` del comando de ejecución asociado (`baseline_update` tras un approve, `restore_file`/`quarantine_file` tras un reject). `PublishedCommand` no tenía forma de correlacionar hacia atrás desde un `Event.id` — solo `command_id` correlaciona hacia adelante (ack → comando).

**Elección:** agregar `PublishedCommand.event_id: int | None` (nulo para `update_config`/`rescan_baseline`/`rule_sync`, que no están atados a un evento puntual), indexado, poblado con el mismo `event.id` que ya viaja en el payload del comando (`actions/streams.py`). El endpoint de eventos (`GET /events`, `GET /events/{id}`) hace un lookup por `event_id` para exponer el `ack_status` más reciente como campo opcional, sin alterar `Event` ni su máquina de estados.

**Por qué no una alternativa:** no es una regla de negocio nueva, es un detalle de persistencia necesario para satisfacer un requisito ya aprobado (6.1); mantenerlo fuera del modelo forzaría parsear `payload` (JSON, no poblado para estos tipos de comando hoy) en cada request de listado — peor performance y peor legibilidad que una columna indexada.

### D-3 — command_id: generar una vez, persistir en ambos lados

**Elección:** En cada publicador de comando confirmable, generar `command_id = str(uuid.uuid4())` una sola vez, usarlo en el payload firmado **y** pasarlo a la fila `PublishedCommand`. Concretamente:
- `actions/streams.py`: `_record_published_command(...)` gana el parámetro `command_id` y lo persiste; el payload usa el mismo valor.
- `agents/streams.py`: `publish_update_config` y `publish_rescan_baseline` empiezan a crear fila `PublishedCommand` (hoy no crean ninguna), con `command_id` y `ack_status = pending`.

**Correlación:** el consumer busca la fila por `command_id` (índice único). Si no existe → descarta (ack de un comando desconocido). Si existe → actualiza.

**Alcance de `ack_status = pending`:** solo los tipos que el agente confirma (`baseline_update`, `restore_file`, `quarantine_file`, `update_config`, `rescan_baseline`). `rule_sync` (broadcast, sin handler de ack en el agente) se persiste con `ack_status = NULL` para no entrar al barrido de timeout (si no, todos los `rule_sync` irían a `timeout`).

### D-4 — Reconciliación al confirmar

**baseline_entries (D1/RN-104):** en un `command_ack` `ok` de `baseline_update`, el consumer reutiliza `actions/service.py::_upsert_baseline_entry` para reflejar el hash aprobado. Localiza la entrada por `agent_id` + `path` (obtenidos del comando persistido o del `event_id` asociado). Necesita el `path`/`hash` del comando: se persisten en `PublishedCommand.payload` (ya existe la columna `payload` de outbox) o se recuperan del `Event` vía `event_id`. Se prefiere el `Event` (fuente de verdad del hash aprobado, D2).

**ruleset_version_applied (D5/RN-106):** en un `command_ack` `ok` de `update_config`/`baseline_update` con `ruleset_version = N`, avanzar `Agent.ruleset_version_applied` a `N` si `N >` el valor actual (monotónico). Se **remueve** el avance prematuro de `agents/service.py::update_agent_config` (líneas 158-160).

**Idempotencia:** si la fila ya está en estado terminal (`acked`/`failed`), un ack repetido no re-aplica efectos secundarios (baseline / ruleset_version).

### D-5 — Barrido de timeout, patrón `_sweep_offline`

**Elección:** un `_sweep_loop` análogo al del heartbeat (intervalo fijo, `run_in_executor`), que marca `ack_status = timeout` las filas `pending` con `published_at < now - umbral`. El umbral vive en `core/config.py` (configurable, default explícito — p. ej. 300 s, alineado con `_DEAD_THRESHOLD_S`). Puede vivir dentro del mismo módulo del consumer (una task `gather`-eada como hace `run_heartbeat_consumer`) para no multiplicar tasks en el lifespan.

## Risks / Trade-offs

- **[command_ack sin HMAC — CERRADO 2026-07-02]** → La versión inicial de este diseño asumía "agente sin cambios" y dejaba el `command_ack` sin firma como limitación aceptada (un atacante con acceso de escritura a Valkey podría haber inyectado acks falsos). El usuario decidió firmar el `command_ack` (cambio trivial: `_publish_ack` ya importa `sign_payload` de `agent/streams.py` para verificar comandos entrantes). El consumer ahora rechaza acks con firma inválida, igual que `events/consumer.py`. Riesgo cerrado; no queda como limitación conocida.
- **[Falso timeout en reinicio]** → Mitigado por el consumer group (D-2): los acks pendientes se re-entregan tras el reinicio antes de que el barrido los venza, siempre que el umbral de timeout sea mayor al tiempo de reinicio. Con default 300 s hay margen amplio.
- **[Reconciliación de baseline necesita path/hash]** → Recuperarlos del `Event` vía `event_id` acopla el consumer al modelo de eventos. Aceptable: el `event_id` viaja en el `command_ack` y en el comando; el `Event` es la fuente de verdad del hash aprobado (D2). Alternativa (persistir path/hash en `PublishedCommand.payload`) queda disponible si el `Event` no fuera localizable.
- **["pending" duplicado entre columnas]** → `status.pending` (outbox) y `ack_status.pending` (ejecución) coexisten con el mismo literal en columnas distintas. Riesgo de confusión en queries/lectura. Mitigación: docstring explícito en el modelo + nombres de columna claros.
- **[Atomicidad ack → efectos]** → La actualización de `PublishedCommand`, `baseline_entries` y `Agent.ruleset_version_applied` debe ocurrir en la misma transacción de sesión para no dejar estados parciales ante un fallo. Se maneja en una sola `Session` por ack.
- **[Bug preexistente descubierto en apply — commit faltante en publish_* post-commit]** → `actions/streams.py` (`publish_baseline_update`/`publish_restore_file`/`publish_quarantine_file`) y `agents/streams.py` (`publish_update_config`/`publish_rescan_baseline`) se invocan DESPUÉS de que el caller (`actions/service.py`, `agents/service.py`) ya hizo `db.commit()`. `_record_published_command` hace `session.add(cmd)` pero ninguna de las dos funciones vuelve a llamar `commit()`: al cerrarse la sesión (`with Session(engine) as session: ... session.close()`), SQLAlchemy hace rollback de lo no comprometido y la fila `PublishedCommand` nunca llega a Postgres en producción (los tests existentes lo ocultan porque llaman `session.commit()` explícitamente después del `publish_*`, algo que ningún caller real hace). Esto rompe la premisa entera de este change: sin la fila persistida, el consumer nunca puede correlacionar el `command_ack` por `command_id`. Fix aplicado: cada función agrega `session.commit()` inmediatamente después del `XADD` exitoso, preservando la semántica "insert antes del XADD, rollback si el XADD falla" que ya cubre el test `test_published_command_inserted_before_xadd_atomicity`.

## Migration Plan

1. Correr la suite existente en verde antes de tocar nada.
2. Migración SQL `004_add_command_ack_tracking.sql` (próximo número secuencial tras `003`): `ADD COLUMN IF NOT EXISTS command_id VARCHAR`, `ack_status VARCHAR`, `acked_at TIMESTAMP`, `error TEXT`, `event_id INTEGER`; `CREATE UNIQUE INDEX IF NOT EXISTS ix_published_commands_command_id`, `CREATE INDEX IF NOT EXISTS ix_published_commands_event_id`. Validar idempotencia ejecutándola dos veces.
3. Extender el modelo `PublishedCommand` con las columnas nuevas (default `ack_status=None`, ver D-1bis para `event_id`).
4. Persistir `command_id` (y `event_id` donde aplique) en `actions/streams.py` y agregar registro en `agents/streams.py`; agregar el `session.commit()` faltante en ambos módulos (ver Risk arriba).
5. Remover el avance de `ruleset_version_applied` en `agents/service.py::update_agent_config`.
5bis. Firmar `command_ack` en `agent/commands.py::_publish_ack` (HMAC-SHA256, `sign_payload`).
6. Implementar `command_ack_consumer.py` (consumer group + handler + barrido) y arrancarlo en `main.py`.
7. Reconciliación de `baseline_entries` reutilizando `actions/service.py`.
8. Frontend: tipo en `api/events.ts` + badge secundario en tabla/detalle.
9. Tests de regresión (ver tasks). Rollback: revertir commits; la migración es aditiva (columnas nulas inocuas si no se usan).

## Open Questions

_(ninguna — D30/RN-124 está cerrada en los appendices "Decisiones de implementación — Abril 2026". La colisión de columna se resuelve en D-1 de este diseño, per la nota de implementación del appendix D30, que la delega explícitamente a la change.)_
