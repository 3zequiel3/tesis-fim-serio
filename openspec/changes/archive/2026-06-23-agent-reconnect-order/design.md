## Context

El `Publisher` (`agent/publisher.py`) es el componente del agente FIM que publica eventos firmados al stream `events` y consume comandos del stream `commands` (event_ack, rule_sync, baseline_update, restore_file, quarantine_file, update_config, rescan_baseline). Estado actual relevante:

- `run()` (líneas 73-79): ejecuta `await self._drain_queue()` y luego `asyncio.gather(self._ack_listener(...), self._retry_loop(...))`. El drain de eventos corre ANTES del listener de comandos.
- `_ack_listener()` (línea 185): inicializa `last_id = "$"`, por lo que `XREAD` sólo entrega mensajes futuros. Avanza `last_id = msg_id` en memoria pero no lo persiste.
- `_verify_and_parse()` (líneas 165-181): único punto de verificación HMAC + parseo JSON de mensajes del stream `commands` (RN-79).
- `_handle_command_async()` (líneas 203-256): filtra por `target_agent_id` (D5, RN-106) y despacha por tipo.

`AgentState` (`agent/state.py`) hoy sólo persiste `ruleset_version`. `save_state`/`load_state` usan escritura atómica (`.tmp` + `os.replace`, `0o600`).

`AgentConfig` (`agent/config.py`) es plano (Pydantic `BaseModel`) y NO tiene sección `publisher`. La sub-config existente es `StorageConfig`.

Esta change implementa D11 / RN-109, cerrada en `docs/arquitectura_stack.md` (§D11) y `docs/reglas_de_negocio.md` (§D11/RN-109) el 2026-06-23. Depende de C24 (`agent-valkey-mtls`), ya archivada.

## Goals / Non-Goals

**Goals:**
- Garantizar el orden de arranque del Publisher: flush de comandos pendientes → drain de eventos → ack listener.
- Persistir el cursor del stream `commands` para recuperar comandos emitidos durante downtime.
- Introducir `command_flush_timeout_s` configurable sin romper configs existentes.
- Reutilizar la maquinaria de verificación/dispatch ya existente (`_verify_and_parse`, `_handle_command_async`) — no duplicar lógica de seguridad.

**Non-Goals:**
- No tocar el flujo de `event_ack`, retry loop ni el formato de eventos publicados.
- No introducir Alembic, migraciones ni servidores HTTP (RN-108, D8).
- No cambiar el modelo de firma HMAC ni el filtrado por `target_agent_id`.
- No persistir el cursor de `events` (fuera de scope; los eventos ya tienen su cola durable propia).

## Decisions

### D-A: El cursor vive en `AgentState`, no en un archivo aparte

Agregar `last_stream_command_id: str = "0-0"` a `AgentState` y serializarlo en el mismo `state.json`. `load_state` lo lee con `data.get("last_stream_command_id", "0-0")`; `save_state` lo incluye en el payload JSON.

**Por qué**: el patrón de persistencia atómica (`.tmp` + `os.replace` + `0o600`) ya existe y es correcto. Un archivo separado duplicaría ese cuidado y abriría una ventana de inconsistencia entre dos archivos. El default `"0-0"` es exactamente lo que pide D11 para el primer arranque (lee desde el origen del stream).

**Alternativa descartada**: cursor en Valkey (consumer groups con `XACK`/`XCLAIM`). Más robusto a nivel teórico, pero introduce una máquina de estados de consumer groups que excede el scope y contradice el modelo simple `XREAD` + cursor que la tesis describe en la Tabla 14.

### D-B: `command_flush_timeout_s` en una sub-config `PublisherConfig`, no flat

`AgentConfig` hoy es plano. D11 especifica explícitamente "sección `[publisher]`". Crear:

```python
class PublisherConfig(BaseModel):
    command_flush_timeout_s: float = 2.0
```

y agregar `publisher: PublisherConfig = PublisherConfig()` a `AgentConfig` (con default para que configs existentes sin la sección sigan validando).

**Por qué**: respeta el contrato del doc canónico (sección `publisher`), agrupa el parámetro semánticamente con su dueño (el Publisher) y deja la puerta abierta a futuros parámetros del publisher sin volver a tocar el esquema flat. El default en el campo Y en la sub-config garantiza retrocompatibilidad: un `config.yaml` sin bloque `publisher` valida con `command_flush_timeout_s = 2.0`.

**Alternativa descartada**: campo flat `command_flush_timeout_s` directo en `AgentConfig`. Más simple pero contradice la sección `[publisher]` que pide D11 y ensucia el namespace raíz.

### D-C: Cursor compartido entre flush y ack listener vía `AgentState`, no variable local

Hoy `_ack_listener` tiene `last_id` como variable local. El flush y el listener deben compartir el mismo cursor para que el listener continúe exactamente donde terminó el flush. Solución: ambos leen/escriben `self._agent_state.last_stream_command_id` (la instancia ya está disponible vía `register_command_handlers`, atributo `_agent_state`).

Flujo concreto en `run()`:

```
1. cursor = self._agent_state.last_stream_command_id   # "0-0" si primer arranque
2. await self._flush_commands(cursor)                  # loop XREAD COUNT 100 BLOCK 0
3. await self._drain_queue()
4. await asyncio.gather(self._ack_listener(stop_event), self._retry_loop(stop_event))
```

`_ack_listener` ya NO inicializa `last_id = "$"`; arranca desde `self._agent_state.last_stream_command_id` (que el flush dejó actualizado). Tras procesar cada mensaje (en flush y en listener), se actualiza `self._agent_state.last_stream_command_id = msg_id` y se llama a `save_state(self._agent_state)`.

**Por qué**: elimina el race "comando emitido entre el fin del flush y el arranque del listener" — el listener retoma desde el cursor exacto donde quedó el flush. Reutiliza `_verify_and_parse` + `_handle_command_async` sin duplicar.

**Precondición**: `register_command_handlers` (que inyecta `_agent_state`) DEBE haberse llamado antes de `run()`. Hoy bootstrap ya lo hace para C13/C14. Si `_agent_state is None`, el Publisher cae a comportamiento legacy (`"$"`, sin persistencia) y emite warning — degradación segura, no crash.

### D-D: El flush usa `BLOCK 0` con guarda de timeout por wall-clock

D11 pide `XREAD COUNT 100 BLOCK 0` en loop. `BLOCK 0` bloquea indefinidamente si el stream está vacío, lo que colgaría el arranque. La guarda: medir wall-clock al entrar al flush y, antes de cada `XREAD`, comparar contra `command_flush_timeout_s`. En la práctica se usa `BLOCK` con un timeout pequeño derivado del presupuesto restante (`min(restante, ronda)` en ms) para no bloquear más allá del budget, y se trata "ronda vacía" como condición de fin. Si se agota el budget sin ronda vacía, se loguea warning y se sale al drain.

**Por qué**: `BLOCK 0` literal es incompatible con un timeout de arranque. La semántica que importa para la spec es: "termina al vaciarse el stream o al superar el timeout", y eso se cumple acotando el block al budget restante.

### D-E: Persistencia del cursor tras cada mensaje, no en batch

Tras cada mensaje procesado con éxito (tanto en flush como en listener), persistir el cursor a disco. Es un `save_state` por mensaje.

**Por qué**: D11 lo exige explícitamente ("se actualiza en disco tras cada mensaje procesado con éxito"). Garantiza que un crash a mitad del flush no reprocese comandos ya aplicados de forma no idempotente. El costo de I/O es aceptable: el volumen de comandos es bajo (rule_sync, acks) y la escritura es atómica y pequeña.

## Risks / Trade-offs

- **[I/O por mensaje]** `save_state` tras cada comando agrega una escritura de disco por mensaje → en una ráfaga grande de comandos pendientes el arranque hace muchas escrituras pequeñas. **Mitigación**: el payload es mínimo y el volumen real de comandos es bajo; aceptable para el caso de uso. Si en producción aparece presión, se puede pasar a persistencia batch al final de cada ronda de `XREAD COUNT 100` sin cambiar la semántica observable.
- **[`BLOCK 0` colgante]** Un `XREAD BLOCK 0` literal colgaría el arranque indefinidamente. **Mitigación**: D-D acota el block al budget restante de `command_flush_timeout_s`.
- **[`_agent_state` no inyectado]** Si `register_command_handlers` no corrió antes de `run()`, no hay dónde persistir el cursor. **Mitigación**: degradación segura a comportamiento legacy con warning; bootstrap ya inyecta el state hoy.
- **[Comando aplicado pero crash antes de persistir cursor]** Si el agente aplica un comando y crashea antes del `save_state`, al reiniciar reprocesa ese comando. **Mitigación**: los handlers de comandos ya deben ser idempotentes (rule_sync compara `ruleset_version`; event_ack es idempotente sobre `_queue.remove`). Riesgo residual bajo.
- **[Timeout demasiado corto]** Un `command_flush_timeout_s` muy bajo en un backend lento dejaría comandos sin aplicar al arrancar. **Mitigación**: default 2.0 s, configurable; el cursor no avanza más allá de lo procesado, así que el listener en background termina de aplicar el resto tras el drain.

## Migration Plan

1. Cambio agent-side puro; sin migración de datos ni de DB.
2. `state.json` existentes sin `last_stream_command_id` cargan con default `"0-0"` → primer arranque post-deploy lee el stream desde el origen una vez (puede reprocesar comandos históricos idempotentes). Comportamiento esperado y seguro.
3. `config.yaml` existentes sin bloque `publisher` validan con `command_flush_timeout_s = 2.0`. No requieren edición.
4. Rollback: revertir el commit del agente. El campo extra en `state.json` es ignorado por la versión previa de `load_state` (usa `.get`), así que no hay corrupción de estado al hacer rollback.

## Open Questions

- Ninguna bloqueante. El presupuesto exacto de `BLOCK` por ronda (D-D) es un detalle de implementación a fijar en apply; la spec sólo exige la semántica "ronda vacía o timeout".
