## Context

La auditoría de junio 2026 detectó tres defectos de implementación en el backend que no fueron cubiertos durante C16, C17 y C29:

1. **Session leak SSE (FIX-01)**: `alerts/stream.py` abre una sesión de DB para el replay inicial pero no la libera explícitamente. FastAPI/SQLModel cierra la sesión al salir del contexto del generador, pero ese contexto no termina hasta que la conexión SSE se cierra — lo que puede ser horas. Con N clientes simultáneos el pool se agota. Adicionalmente, `asyncio.Queue()` sin límite puede crecer ilimitado bajo rafaga, consumiendo RAM hasta OOM.
2. **Agente revocado sin estado (FIX-02)**: `AgentStatus` no tiene valor `revoked`. Los consumers de eventos y heartbeats no filtran por estado del agente — un agente revocado (cuyo certificado fue invalidado) sigue siendo procesado como activo.
3. **Trazabilidad incompleta (FIX-03)**: `actions/streams.py` solo crea registro `PublishedCommand` para el tipo `rule_sync`. Los tipos `restore_file`, `quarantine_file` y `baseline_update` no generan registro de auditoría, rompiendo el compromiso D10.

Las restricciones relevantes: backend Python 3.13 + FastAPI async, Valkey Streams para la comunicación agent↔backend, PostgreSQL 18.3, pool de conexiones SQLAlchemy gestionado por SQLModel.

## Goals / Non-Goals

**Goals:**
- Liberar la sesión de DB inmediatamente después del replay SSE (antes de entrar al loop de eventos en tiempo real)
- Limitar la cola SSE por conexión a `maxsize=100` con política drop-newest y WARNING en `QueueFull`
- Agregar `AgentStatus.revoked` al enum Python y a la columna PostgreSQL
- Hacer que `events/consumer.py` y `agents/heartbeat_consumer.py` rechacen mensajes de agentes con `status == revoked`
- Insertar `PublishedCommand` para todos los tipos de comando de acción
- Documentar D27 (shared_secret_hex en plaintext) y D28 (gap de heartbeat en restart) como limitaciones conocidas

**Non-Goals:**
- Cambios en el protocolo de mensajes Valkey (formato de streams)
- Cambios en endpoints HTTP (ningún endpoint nuevo ni renombrado)
- Implementar key wrapping / KMS (D27 — trabajo futuro explícito)
- Reducir el gap de heartbeat durante restart de backend (D28 — aceptable para tesis)
- Cambios en el frontend o en el agente FIM

## Decisions

### FIX-01 — Gestión de sesión DB y cola SSE acotada

**Elección**: Usar un bloque `async with session:` que wrappea **solo** la fase de replay, cerrado explícitamente antes de entrar al bucle `while True` del stream SSE. La `asyncio.Queue` se reemplaza por `asyncio.Queue(maxsize=100)`.

**Alternativa considerada**: Context manager `yield` de FastAPI para la sesión — pero ese lifetime está atado al lifetime del generador (la conexión SSE entera), que es exactamente el problema.

**Política drop-newest**: Cuando la cola está llena, se descarta el evento nuevo (no el más antiguo) y se registra `WARNING`. Esto preserva el historial ya encolado y evita ordenamiento inestable. D24 cierra esta decisión.

**Por qué maxsize=100**: Con alertas de severidad crítica como eventos más frecuentes esperados, 100 eventos en cola equivalen a varios segundos de buffer. Es suficiente para absorber picos sin consumo de RAM descontrolado. Valor fijado en D24.

### FIX-02 — AgentStatus.revoked y filtro en consumers

**Elección**: Agregar `revoked = "revoked"` al enum Python `AgentStatus` en `agents/models.py` y un script SQL idempotente `backend/db/migrations/XXX_add_agent_status_revoked.sql` que agrega el valor a la columna enum PostgreSQL con `ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'revoked'`.

**Consumer check**: Ambos consumers (`events/consumer.py` y `agents/heartbeat_consumer.py`) realizarán una consulta de punto a DB al inicio del procesamiento de cada mensaje para verificar `agent.status`. Si `status == revoked`, se descarta el mensaje sin error y se registra `INFO`.

**Alternativa considerada**: Filtrar en la capa de Valkey Streams (consumer group con ACK selectivo). Descartado: añade complejidad al protocolo sin ganancia — el check en DB es más explícito y auditable.

**Sobre la numeración de migración**: seguir la convención existente en `backend/db/migrations/` — prefijo numérico secuencial (`NNN_<name>.sql`). Inspeccionar el directorio para determinar el próximo número.

### FIX-03 — PublishedCommand para todos los tipos de comando

**Elección**: Refactorizar la función de publicación en `actions/streams.py` para que el registro `PublishedCommand` se inserte dentro del bloque de despacho de cualquier tipo de comando, no solo `rule_sync`.

**Implementación**: Extraer la lógica de inserción a una función auxiliar `_record_published_command(session, agent_id, command_type, payload_json)` y llamarla antes del `XADD` a Valkey para todos los tipos. Esto garantiza que si el `XADD` falla, el registro queda en la misma transacción y se revierte.

**Alternativa considerada**: Insertar el registro después del `XADD`. Descartado: si el backend falla entre el `XADD` y el `INSERT`, el comando se ejecuta sin registro de auditoría.

## Risks / Trade-offs

- **[FIX-01] Drop-newest vs. backpressure**: La política drop-newest puede hacer que un cliente SSE lento pierda alertas recientes en su cola. Mitigación: el cliente puede reconectar con `Last-Event-ID` para recuperar el historial desde DB.
- **[FIX-02] Check de estado por mensaje**: El consumer valida `agent.status` en cada mensaje procesado — una consulta extra por evento. Con el volumen esperado de la tesis (pocos agentes, ~1 evento/seg) esto es negligible. En producción real sería recomendable un cache TTL corto.
- **[FIX-02] ALTER TYPE en PostgreSQL**: `ALTER TYPE ... ADD VALUE` no puede ejecutarse dentro de una transacción en PostgreSQL < 16. En PostgreSQL 18.3 esto está soportado. Validar en el script de migración.
- **[FIX-03] Atomicidad INSERT + XADD**: La inserción de `PublishedCommand` ocurre en la misma sesión DB que el resto de la operación. Si el `XADD` a Valkey falla después del commit de DB, el registro existe pero el comando nunca se ejecutó. Aceptable para tesis — en producción se requeriría outbox pattern o transacción Valkey.
- **[D27] shared_secret_hex en plaintext**: Limitación conocida. El campo es sensible (usado para HMAC de heartbeats). Key wrapping con KMS o cifrado en capa de aplicación queda fuera del scope de la tesis.
- **[D28] Gap de heartbeat en restart**: Con `last_id="$"` el consumer de heartbeats pierde los mensajes publicados durante el restart. El agente puede aparecer como `offline` durante <30 segundos. Comportamiento documentado y aceptable para la tesis.

## Migration Plan

1. Correr tests existentes (257+) en verde antes de tocar nada.
2. Aplicar FIX-02 primero: agregar `revoked` al enum Python + script SQL de migración. Validar con `pytest` aislado.
3. Aplicar FIX-01: modificar `stream.py` y `router.py`. Validar con test de regresión de sesión.
4. Aplicar FIX-03: modificar `actions/streams.py`. Validar con test de PublishedCommand por tipo.
5. Escribir tests de regresión para los tres fixes.
6. Commit único por fix (3 commits de code + 1 de docs para D27/D28).
7. Rollback: revertir el commit del fix afectado. La migración SQL de `revoked` es aditiva — no hay rollback automático del tipo enum, pero `revoked` sin filas que lo usen es inocuo.

## Open Questions

_(ninguna — D24, D26, D27 y D28 están cerradas en los appendices de decisiones de implementación — Abril 2026)_
