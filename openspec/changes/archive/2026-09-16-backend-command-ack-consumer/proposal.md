## Why

El agente publica confirmaciones de ejecución de comandos (`baseline_update`, `restore_file`, `quarantine_file`, `update_config`, `rescan_baseline`) en el stream Valkey `event_ack` (`agent/commands.py`, `STREAM_EVENT_ACK`), pero el backend no consume ese stream — nadie lee `event_ack`. Como consecuencia hay dos violaciones vivas de reglas de negocio: `agents/service.py::update_agent_config` avanza `Agent.ruleset_version_applied` al **publicar** el comando (no al confirmarlo), contradiciendo D5/RN-106; y D1/RN-104 (cada confirmación de `baseline_update` actualiza `baseline_entries` en el backend) nunca se implementó. La decisión D30/RN-124 (cerrada 2026-07-02) resuelve el gap; este change lo implementa. Es el hallazgo #3 de la auditoría dual-judge 2026-07-02, diferido en C35 por requerir una decisión de diseño nueva.

## What Changes

- **Consumer dedicado del stream `event_ack`** para el concepto renombrado **`command_ack`** (confirmación de ejecución de comandos), distinto del ack de ingesta homónimo de RN-40/RN-54 (que el backend publica en el stream `commands`). Nuevo módulo (p. ej. `backend/app/modules/agents/command_ack_consumer.py`) que sigue el patrón de `events/consumer.py` (consumer group Valkey, verificación estructural del payload, `run_in_executor` para el I/O de DB per D21), arrancado como task adicional en el lifespan de `backend/app/main.py`.
- **`PublishedCommand` gana tracking de ejecución**: `command_id` (hoy se genera vía `uuid.uuid4()` en `actions/streams.py` y `agents/streams.py` pero se descarta — ahora se persiste), `ack_status` (`pending | acked | failed | timeout`), `acked_at` y `error`. Ver `design.md` para la resolución de la colisión con la columna `status` de outbox ya existente.
- **Todos los comandos que el agente confirma persisten su `command_id`** al publicarse. Hoy `update_config` y `rescan_baseline` (`agents/streams.py`) no crean ninguna fila `PublishedCommand`; este change agrega ese registro para poder correlacionar sus `command_ack`.
- **Corrige D5/RN-106**: `Agent.ruleset_version_applied` avanza **solo** al recibir el `command_ack` de `update_config`/`baseline_update`, nunca al publicar. Se remueve el avance prematuro de `agents/service.py::update_agent_config`.
- **Cierra D1/RN-104**: el `command_ack` exitoso de un `baseline_update` actualiza `baseline_entries` en el backend, reutilizando el upsert existente en `actions/service.py`.
- **Sweep de timeout**: barrido periódico (patrón `heartbeat_consumer._sweep_offline`) que marca `timeout` los comandos `ack_status=pending` que superan un umbral configurable.
- **Frontend**: indicador secundario de estado de ejecución por evento. NO crea un nuevo `EventStatus` — `approved`/`rejected` siguen siendo terminales (RN-72).
- **Migración SQL idempotente** (`backend/db/migrations/`, convención D3 sin Alembic) para las columnas nuevas.

Sin cambios del lado del agente: `agent/commands.py` ya publica correctamente en `event_ack` (D30 lo confirma).

## Capabilities

### New Capabilities

- `backend-command-ack`: consumer dedicado del stream `event_ack`, tracking de ejecución de comandos en `PublishedCommand`, reconciliación de `baseline_entries` y `ruleset_version_applied` al confirmar, y barrido de timeout.

### Modified Capabilities

- `backend-agent-management`: `POST /agents/{id}/config` deja de avanzar `ruleset_version_applied` al publicar el comando; ese campo ahora solo lo avanza el consumer de `command_ack` al confirmarse la ejecución (D5/RN-106).
- `frontend-events`: la vista de eventos expone un indicador secundario de estado de ejecución del comando asociado (`pending | acked | failed | timeout`), sin alterar la máquina de estados del evento (RN-72).

## Impact

- **Archivos afectados (backend)**: nuevo `agents/command_ack_consumer.py`; `rules/models.py` (`PublishedCommand`); `actions/streams.py` y `agents/streams.py` (persistir `command_id`); `agents/service.py` (`update_agent_config` — remover avance prematuro); `main.py` (arranque del consumer task); `actions/service.py` (reutilizar upsert de `baseline_entries`); `core/config.py` (umbral de timeout configurable).
- **Archivos afectados (frontend)**: `api/events.ts` (tipo de estado de ejecución), tabla/detalle de eventos (badge secundario).
- **Migración de BD**: script idempotente en `backend/db/migrations/` que agrega `command_id`, `ack_status`, `acked_at`, `error` a `published_commands` (ADD COLUMN IF NOT EXISTS + índice sobre `command_id`).
- **Sin cambio de API HTTP**: ningún endpoint nuevo ni renombrado.
- **Sin cambio de protocolo Valkey**: el formato de mensajes de `event_ack` no cambia; el agente no se toca.
- **Reglas cubiertas**: RN-104, RN-106, RN-124. **Decisiones aplicadas**: D30.
- **Dependencias**: C34 (`backend-residual-fixes`) y C35 (`e2e-contract-fixes`), ambos aplicados en local. D30/RN-124 cerrada en los appendices el 2026-07-02.
