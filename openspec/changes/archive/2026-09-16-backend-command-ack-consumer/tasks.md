## 1. Modelo y migración (base — afecta BD)

- [x] 1.1 Inspeccionar `backend/db/migrations/` y determinar el próximo prefijo secuencial (tras `003` → `004`)
- [x] 1.2 Extender `PublishedCommand` (`backend/app/modules/rules/models.py`): agregar `command_id: str | None` (único, indexado), `ack_status: str | None` (`pending | acked | failed | timeout`), `acked_at: datetime | None`, `error: str | None`, `event_id: int | None` (indexado, D-1bis — correlación evento → estado de ejecución para el frontend). Actualizar el docstring aclarando que `status` (outbox `pending|published`) y `ack_status` (ejecución) son columnas distintas
- [x] 1.3 Crear `backend/db/migrations/004_add_command_ack_tracking.sql`: `ADD COLUMN IF NOT EXISTS` para las 5 columnas + `CREATE UNIQUE INDEX IF NOT EXISTS ix_published_commands_command_id` + `CREATE INDEX IF NOT EXISTS ix_published_commands_event_id`. NO tocar la columna `status` ni su índice
- [x] 1.4 Verificar idempotencia ejecutando el script dos veces en el contenedor de test
- [x] 1.5 Agregar `STREAM_EVENT_ACK = "event_ack"` a `backend/app/core/streams.py` (contrato compartido, mismo lugar que `STREAM_EVENTS`/`STREAM_HEARTBEAT`)
- [x] 1.6 Agregar `command_ack_timeout_seconds: int = 300` a `backend/app/core/config.py` (umbral configurable del barrido, D-5)

## 2. Persistir command_id (y event_id) al publicar comandos confirmables

- [x] 2.1 En `backend/app/modules/actions/streams.py`: `_record_published_command(...)` recibe y persiste `command_id` y `event_id`, y setea `ack_status="pending"`. Generar el `command_id` una sola vez y reusarlo en el payload de `publish_baseline_update`, `publish_restore_file`, `publish_quarantine_file`
- [x] 2.2 **Fix de bug descubierto (bloqueante para este change)**: `publish_baseline_update`/`publish_restore_file`/`publish_quarantine_file` se llaman post-`db.commit()` desde `actions/service.py`; `_record_published_command` nunca persiste porque ninguna de las funciones vuelve a comitear (la sesión se cierra con rollback implícito de lo pendiente). Agregar `session.commit()` inmediatamente después del `XADD` exitoso en las 3 funciones, preservando el rollback-on-XADD-failure que ya cubre `test_published_command_inserted_before_xadd_atomicity`
- [x] 2.3 En `backend/app/modules/agents/streams.py`: `publish_update_config` y `publish_rescan_baseline` empiezan a crear fila `PublishedCommand` (hoy no crean ninguna) con `command_id` (mismo del payload), `target_agent_id`, `ruleset_version` (cuando aplique) y `ack_status="pending"`; mismo fix de `session.commit()` post-XADD que 2.2
- [x] 2.4 Confirmar que los comandos `rule_sync` (outbox H6) se siguen persistiendo con `ack_status=NULL` (excluidos del barrido de timeout) — ajustar sólo si el default del modelo no lo garantiza

## 3. Corregir D5/RN-106 en la publicación

- [x] 3.1 En `backend/app/modules/agents/service.py::update_agent_config`: remover el avance de `agent.ruleset_version_applied = new_version` (líneas ~158-160). El `ruleset_version` se sigue incrementando; sólo NO se aplica al agente al publicar

## 4. Agente — firmar command_ack con HMAC (decisión del usuario, amplía D30/RN-79)

- [x] 4.1 En `agent/commands.py::_publish_ack`: firmar el payload con `sign_payload` (importar de `agent/streams.py`, junto a `canonical_json`/`verify_payload` ya importados) usando el `shared_secret` cargado vía `_load_shared_secret(config)`. Cambiar el parámetro `agent_id: str` de `_publish_ack` por `config: AgentConfig` para poder cargar el secret adentro; actualizar los 8 call sites internos
- [x] 4.2 Si no hay `shared_secret` disponible, publicar sin firma mas loguear ERROR (fail-open observable, igual que `dispatch()` cuando no encuentra secret) — el consumer lo rechazará por firma inválida/faltante, quedando `pending` hasta timeout
- [x] 4.3 Test del agente: `_publish_ack` firma el payload — `verify_payload(shared_secret, ack_payload)` retorna `True` sobre el ack publicado

## 5. Consumer de command_ack

- [x] 5.1 Crear `backend/app/modules/agents/command_ack_consumer.py` con `run_command_ack_consumer(client, stop_event)`: `_ensure_group` (`xgroup_create(STREAM_EVENT_ACK, "fim-command-ack", id="0", mkstream=True)`), loop `xreadgroup` + `xack`, patrón `events/consumer.py`
- [x] 5.2 Handler síncrono `_handle_command_ack(msg_data)` vía `run_in_executor` (D21): parsear payload, validar `command_id` presente (WARNING + XACK si falta), buscar `PublishedCommand` por `command_id` (descartar si desconocido)
- [x] 5.3 Verificación HMAC (decisión del usuario, D30 nota 2026-07-02): resolver el `shared_secret` del `agent_id` que viaja en el payload del ack y llamar `verify_payload`; **RECHAZAR** (log WARNING, sin tocar `PublishedCommand`) acks con firma inválida o sin secret resoluble — igual que `events/consumer.py:191`
- [x] 5.4 Actualizar la fila: `status=="ok"` → `ack_status=acked`, `acked_at=now`, `error=None`; `status=="error"` → `ack_status=failed`, `acked_at=now`, `error=<mensaje>`. Idempotente si ya está en estado terminal
- [x] 5.5 Reconciliación `baseline_entries` (D1/RN-104): en ack `ok` de `baseline_update`, reutilizar `actions/service.py::upsert_baseline_entry` (renombrado de `_upsert_baseline_entry` para reuso cross-módulo) con `agent_id`/`path`/`hash` recuperados del `Event` asociado (vía `event_id` del payload del ack)
- [x] 5.6 Reconciliación `ruleset_version_applied` (D5/RN-106): en ack `ok` de `update_config`/`baseline_update` con `ruleset_version=N`, avanzar `Agent.ruleset_version_applied` a `N` sólo si `N >` actual (monotónico). Todo en la misma `Session`/transacción que 5.4-5.5
- [x] 5.7 Barrido de timeout: `_sweep_loop` (patrón `heartbeat_consumer`) que marca `ack_status=timeout` filas `ack_status=pending` con `published_at < now - umbral`; excluir `ack_status IS NULL`. Umbral desde `settings.command_ack_timeout_seconds` (tarea 1.6)
- [x] 5.8 Componer lector + barrido con `asyncio.gather` dentro de `run_command_ack_consumer` (como `run_heartbeat_consumer`)

## 6. Arranque en el lifespan

- [x] 6.1 En `backend/app/main.py`: importar y crear `command_ack_task = asyncio.create_task(run_command_ack_consumer(async_valkey, stop_event))` junto a los consumers existentes
- [x] 6.2 Cancelar `command_ack_task` en el shutdown y agregarlo a `tasks_to_gather`

## 7. Frontend — indicador secundario de ejecución

- [x] 7.1 Exponer el `ack_status` del comando asociado en la respuesta del backend de eventos (`EventOut` en `events/router.py`, `GET /events` y `GET /events/{id}`) vía lookup por `PublishedCommand.event_id`, sin alterar el `status` del evento
- [x] 7.2 En `frontend/src/api/events.ts`: declarar el tipo del estado de ejecución (`pending | acked | failed | timeout`) como campo opcional del evento (`ack_status?`)
- [x] 7.3 Renderizar un badge secundario en la tabla (`EventsTable.tsx`) y detalle (`EventDetail.tsx`) de eventos, visualmente distinto del `status`; omitirlo cuando no hay comando confirmable asociado. NO agregar valores a la máquina de estados del evento (RN-72)
- [x] 7.4 Test frontend de la función pura que mapea `ack_status` → label/clase (sin librería de render, mismo estilo que `eventFilters.test.ts`)

## 8. Tests de regresión backend/agente

- [x] 8.1 Migración idempotente: correr el script dos veces sin error; verificar columnas + índices
- [x] 8.2 Publicación: `publish_baseline_update`/`publish_restore_file`/`publish_quarantine_file` persisten `PublishedCommand` con `command_id` real (no solo dentro del test que comitea manualmente — regresión del fix 2.2)
- [x] 8.3 Consumer: `command_ack` `ok` de `baseline_update` → fila `acked`, `baseline_entries` upserteado, `ruleset_version_applied` avanzado
- [x] 8.4 Consumer: `command_ack` `error` → fila `failed` con `error`; `baseline_entries` y `ruleset_version_applied` sin cambio
- [x] 8.5 Consumer: ack sin `command_id` y ack de `command_id` desconocido → descartados con XACK, sin tocar DB
- [x] 8.6 Consumer: ack con firma HMAC inválida → descartado con XACK, sin tocar DB (nuevo, decisión de firma)
- [x] 8.7 Consumer: ack repetido idempotente (no re-aplica efectos)
- [x] 8.8 Publicación: `update_config` NO avanza `ruleset_version_applied`; sí crea `PublishedCommand` con `command_id` y `ack_status=pending`
- [x] 8.9 Barrido: comando `pending` vencido → `timeout`; `rule_sync` (`ack_status NULL`) y comandos terminales no se tocan
- [x] 8.10 Agente: `_publish_ack` firma el payload publicado (tarea 4.3)
- [x] 8.11 Correr la suite completa (backend + agente) y confirmar verde (mismo baseline de fallas preexistentes que antes de este change)

## 9. Commits y cierre (3 slices, decisión del usuario — sin PR, commits locales en `devel`)

- [x] 9.1 Commit slice 1 — `feat(agents): track command execution in PublishedCommand + migration` (tareas 1-3, incluye fix 2.2 y tests 8.1/8.2/8.8 parcial)
- [x] 9.2 Commit slice 2 — `feat(agents): dedicated command_ack consumer with HMAC verification, timeout sweep and reconciliation` (tareas 4-6, incluye tests 8.3-8.7, 8.9, 8.10)
- [x] 9.3 Commit slice 3 — `feat(frontend): secondary command execution status badge on events` (tarea 7, incluye test 7.4)
- [x] 9.4 Correr la suite completa final (backend + agente + frontend) y confirmar verde antes de cerrar (tarea 8.11)
