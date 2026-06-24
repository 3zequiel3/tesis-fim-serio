## Why

El Publisher del agente FIM tiene dos bugs acoplados que rompen la garantía de la tesis (Tabla 14) y hacen inejecutable RN-85:

1. **Orden de reconexión invertido** (CRÍTICO): `run()` ejecuta `_drain_queue()` (publicar eventos encolados) ANTES de procesar los comandos pendientes del stream `commands`. Los eventos encolados se evalúan contra el ruleset previo al crash, potencialmente con reglas obsoletas.
2. **Pérdida de comandos durante downtime**: el listener arranca siempre con `last_id = "$"`, que sólo entrega mensajes futuros. Todo comando emitido por el backend mientras el agente estaba caído se pierde silenciosamente.

Estos defectos derrotan el propósito mismo del FIM en el escenario de reconexión: el agente puede aplicar acciones contra reglas viejas o nunca recibir un `rule_sync` emitido durante su downtime.

## What Changes

- **BREAKING (comportamiento de arranque)**: el orden de arranque del Publisher cambia a flush de comandos → drain de eventos → ack listener en background. El drain de eventos encolados NO inicia hasta que el flush de comandos termina.
- Persistir el cursor del stream `commands` en `AgentState.last_stream_command_id` (`str`, default `"0-0"`), actualizado en disco tras cada mensaje procesado con éxito.
- Reemplazar `last_id = "$"` por el cursor persistido, de modo que `XREAD` arranque desde el último comando confirmado (o desde el origen en el primer arranque).
- Nuevo flush loop al arrancar: `XREAD COUNT 100 BLOCK 0` en loop desde el cursor guardado, aplicando cada comando, hasta una ronda vacía o hasta superar `command_flush_timeout_s`.
- Nuevo parámetro de config `command_flush_timeout_s: float = 2.0` (sección `publisher`), documentado en `config.yaml.example`.

## Capabilities

### New Capabilities
- `agent-command-cursor`: persistencia del cursor del stream `commands` en `AgentState` y su uso como `last_id` de `XREAD`, garantizando recuperación de comandos emitidos durante downtime (cierra el gap de RN-85).
- `agent-reconnect-ordering`: orden de arranque determinístico del Publisher — flush de comandos pendientes antes del drain de eventos encolados, con timeout configurable (cierra el requisito de la Tabla 14 de la tesis).

### Modified Capabilities
<!-- Ninguna spec previa de capability del agente vive en openspec/specs/ todavía; estos comportamientos se introducen como capabilities nuevas de esta change. -->

## Impact

- **Reglas cubiertas**: RN-109 (cursor persistente + orden de reconexión), RN-85 (consume y aplica todos los comandos pendientes, ahora ejecutable), RN-79 (verificación HMAC se mantiene en todos los mensajes del flush), RN-106 / D5 (filtrado por `target_agent_id`).
- **Decisiones aplicadas**: D11 (cierre de la suposición abierta; appendix "Decisiones de implementación — 2026-06-23").
- **Dependencia DAG**: C24 (`agent-valkey-mtls`) — archivada. Satisfecha.
- **Código afectado**:
  - `agent/state.py` — nuevo campo `last_stream_command_id: str = "0-0"`; persistir/cargar en `save_state` / `load_state`.
  - `agent/publisher.py` — reordenar `run()`; nuevo flush loop; `_ack_listener` arranca desde el cursor persistido; actualizar cursor en disco tras cada mensaje.
  - `agent/config.py` — nueva sub-config `PublisherConfig` con `command_flush_timeout_s: float = 2.0`.
  - `agent/deploy/config.yaml.example` — documentar la sección `publisher` y el parámetro.
  - `agent/tests/test_reconnect_order.py` — nuevo, cubre orden, persistencia de cursor, primer arranque, update en disco y timeout.
- **Sin Alembic, sin nuevos servidores HTTP** (RN-108, D8). Todo el cambio es agent-side sobre Valkey Streams.
