## Why

La auditoría de junio 2026 detectó tres vulnerabilidades operativas en el backend: (1) el handler SSE filtra sesiones de DB después del replay inicial y usa una cola `asyncio.Queue` sin límite que provoca OOM bajo carga explosiva, (2) no existe el estado `revoked` en `AgentStatus`, por lo que agentes revocados siguen procesándose como si fueran activos, y (3) solo los comandos `rule_sync` crean registro `PublishedCommand`, rompiendo la trazabilidad de auditoría comprometida en D10. Las decisiones D24, D26/RN-122, D27 y D28 están cerradas en los appendices de decisiones de implementación — Abril 2026.

## What Changes

- **FIX-01 (ALTO)** — `backend/app/modules/alerts/stream.py` + `alerts/router.py`: liberar la sesión de DB inmediatamente después de completar el replay inicial; reemplazar `asyncio.Queue()` sin límite por `asyncio.Queue(maxsize=100)` con política drop-newest y log `WARNING` en `QueueFull`. Decisión D24.
- **FIX-02 (ALTO)** — `backend/app/modules/agents/models.py` + `events/consumer.py` + `agents/heartbeat_consumer.py`: agregar valor `revoked` al enum `AgentStatus`; ambos consumers deben verificar `agent.status != revoked` antes de procesar mensajes. Decisión D26 / RN-122.
- **FIX-03 (BAJO)** — `backend/app/modules/actions/streams.py`: insertar registro `PublishedCommand` para TODOS los tipos de comando de acción (`restore_file`, `quarantine_file`, `baseline_update`, `rule_sync`), completando la trazabilidad D10.
- **D27 (limitación documentada)** — `shared_secret_hex` en plaintext en DB. Sin cambio de código. Se documenta como limitación conocida (key wrapping / KMS como trabajo futuro).
- **D28 (limitación documentada)** — El heartbeat consumer con `last_id="$"` pierde heartbeats durante reinicios del backend. Sin cambio de código. Se documenta el falso positivo `offline` de <30s como comportamiento aceptable para la tesis.

## Capabilities

### New Capabilities

_(ninguna — este change no introduce nuevas capacidades, solo corrige comportamiento incorrecto y completa trazabilidad pendiente)_

### Modified Capabilities

- `sse-alerts`: el stream handler libera la sesión DB tras el replay y aplica una cola acotada con política drop-newest (cambio de comportamiento en gestión de recursos del stream SSE). Decisión D24.
- `backend-agents`: el enum `AgentStatus` incorpora el valor `revoked`; los consumers de eventos y heartbeats rechazan mensajes de agentes revocados. Decisión D26 / RN-122.

## Impact

- **Archivos afectados**: `backend/app/modules/alerts/stream.py`, `alerts/router.py`, `agents/models.py`, `events/consumer.py`, `agents/heartbeat_consumer.py`, `actions/streams.py`
- **Migración de BD**: agrega `'revoked'` a la columna `status` del tipo enum `agent_status` en PostgreSQL — requiere script SQL idempotente en `backend/db/migrations/`
- **Tests**: se agregan tests de regresión para FIX-01 (leak de sesión + QueueFull), FIX-02 (rechazo de agente revocado), FIX-03 (PublishedCommand por tipo). El harness de aislamiento C33 permanece sin cambios.
- **Sin cambio de API HTTP**: ningún endpoint nuevo ni modificado
- **Sin cambio de protocolo Valkey**: el formato de mensajes en streams no cambia
- **Reglas cubiertas**: RN-122
- **Decisiones aplicadas**: D24, D26, D27, D28
- **Dependencias satisfechas**: C31 (`backend-event-correctness`) archivado el 2026-07-01
