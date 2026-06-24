## 1. Estado persistente del cursor (agent/state.py)

- [x] 1.1 Agregar campo `last_stream_command_id: str = "0-0"` al dataclass `AgentState`
- [x] 1.2 En `load_state`, leer el cursor con `data.get("last_stream_command_id", "0-0")` (default si falta o si no hay state.json)
- [x] 1.3 En `save_state`, incluir `last_stream_command_id` en el payload JSON serializado (mantener escritura atómica `.tmp` + `os.replace` + `0o600`)

## 2. Configuración del flush (agent/config.py)

- [x] 2.1 Crear `class PublisherConfig(BaseModel)` con `command_flush_timeout_s: float = 2.0`
- [x] 2.2 Agregar `publisher: PublisherConfig = PublisherConfig()` a `AgentConfig` (default para retrocompatibilidad con configs sin la sección)

## 3. Documentación de config (agent/deploy/config.yaml.example)

- [x] 3.1 Agregar sección `publisher:` con `command_flush_timeout_s: 2.0` y comentario explicando el parámetro (timeout del flush de comandos al reconectar, default 2.0 s)

## 4. Orden de arranque y flush (agent/publisher.py)

- [x] 4.1 Reescribir `run()`: leer cursor de `self._agent_state.last_stream_command_id`, luego flush de comandos, luego `_drain_queue()`, luego `gather(_ack_listener, _retry_loop)` en background
- [x] 4.2 Implementar `_flush_commands(stop_event)`: loop `XREAD COUNT 100` desde el cursor con `BLOCK` acotado al budget restante de `command_flush_timeout_s`; terminar al obtener ronda vacía o al superar el timeout (warning en este último caso)
- [x] 4.3 En el flush, reutilizar `_verify_and_parse` (HMAC, RN-79) y `_handle_command_async` (filtro `target_agent_id`, D5/RN-106) — no duplicar lógica de seguridad
- [x] 4.4 Tras cada mensaje procesado en el flush, actualizar `self._agent_state.last_stream_command_id = msg_id` y persistir vía `save_state`
- [x] 4.5 Modificar `_ack_listener`: reemplazar `last_id = "$"` por `last_id = self._agent_state.last_stream_command_id`; tras cada mensaje, actualizar el cursor en state y persistir
- [x] 4.6 Degradación segura: si `self._agent_state is None`, caer a comportamiento legacy (`"$"`, sin persistencia) emitiendo un warning de log

## 5. Tests (agent/tests/test_reconnect_order.py)

- [x] 5.1 Test de orden: `_drain_queue` no inicia hasta que el flush de comandos termina (con un fake/mock de Valkey client que registre la secuencia de llamadas)
- [x] 5.2 Test de carga de cursor: `last_id` persistido se carga al arrancar y `XREAD` arranca desde él (no desde `"$"`)
- [x] 5.3 Test de primer arranque: sin `state.json`, `AgentState.last_stream_command_id == "0-0"` y el `XREAD` arranca desde el origen
- [x] 5.4 Test de persistencia: el cursor se actualiza en disco (`state.json`) tras cada mensaje procesado
- [x] 5.5 Test de timeout: si no hay mensajes nuevos durante `command_flush_timeout_s`, el flush continúa al drain y deja el cursor en el último mensaje procesado
- [x] 5.6 Test de verificación durante el flush: un mensaje con firma HMAC inválida no se aplica, pero el cursor avanza
