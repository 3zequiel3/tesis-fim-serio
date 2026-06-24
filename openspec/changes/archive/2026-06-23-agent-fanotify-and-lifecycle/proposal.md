## Why

El detector fanotify solo reacciona a `FAN_CLOSE_WRITE`: borrados, renames y creaciones de archivos vigilados pasan desapercibidos, dejando ciegos los escenarios de manipulación más comunes (RN-110/D12). En paralelo, el agente arrastra dos fallas de robustez que ya se reproducen en operación normal: `state.json` pierde reglas o el cursor de comandos según qué escritor corra último (F2), y `auto_restore`/`restore_file` fallan en seco cuando el baseline está en estado `absent` aunque existan snapshots restaurables (F3). Cerramos además dos brechas de ciclo de vida: el flag `shutdown` no se propaga al heartbeat durante el drenaje (G4) y el certificado mTLS no se renueva proactivamente, arriesgando expiración silenciosa (RN-111/D13/G3).

## What Changes

- **Detector fanotify multi-evento (D12/RN-110)**: el mark agrega `FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE` además de `FAN_CLOSE_WRITE`. Dispatch por tipo de evento; `ev.path is None` se descarta con warning.
- **Campo `operation_type` en el payload de evento**: `file_modified` | `file_absent` | `file_deleted` | `file_created` (str, snake_case, RN-71). Borrados/moved-from no hashean (`hash: null`); created/moved-to hashean y crean entrada de baseline. Payloads sin el campo se tratan como `file_modified`.
- **G4 — propagación de `shutdown` al heartbeat**: el handler SIGTERM/SIGINT llama `publisher.set_shutdown(True)` antes de drenar, de modo que el heartbeat publique `shutdown=true` durante el drenaje (RN-93).
- **G3 — renovación proactiva de certificado (D13/RN-111)**: nueva tarea asyncio `_cert_renewal_loop` que cada `cert_renewal_check_interval_h` (default 24 h) verifica vigencia; si el cert vence en ≤ 15 días llama `POST /agents/renew` vía mTLS con el cert actual y persiste el nuevo cert con escritura atómica. Fallo → warning + retry, sin interrumpir operación. El endpoint backend queda fuera de scope.
- **F2 — escritura unificada de `state.json`**: se elimina la doble escritura (`AgentState.save_state` y `RulesCache._persist`) que se pisaban entre sí. Un único punto de escritura serializa `ruleset_version`, `last_stream_command_id` y `rules` juntos. **BREAKING (interno)**: la firma de persistencia de reglas cambia para pasar por `AgentState`.
- **F3 — fallback a snapshots en restauración**: antes de decodificar `content_b64`, si es `None` se busca el snapshot más reciente con contenido (descomprimiendo si `gzip=True`); si no hay ninguno utilizable se falla con `no_restorable_content`.
- **Config**: nuevo campo `cert_renewal_check_interval_h: float = 24.0`.
- Tests nuevos para cada item.

Sin Alembic, sin nuevos servidores HTTP (RN-108/D8). El agente sigue comunicándose con el backend solo vía Valkey Streams, salvo la llamada HTTPS mTLS puntual a `/agents/renew`.

## Capabilities

### New Capabilities
- `agent-cert-renewal`: tarea asyncio en background que renueva proactivamente el certificado mTLS vía `POST /agents/renew` antes de su expiración, con persistencia atómica y degradación tolerante a fallos (D13/RN-111).

### Modified Capabilities
- `agent-fanotify-detector`: el mark registra máscaras adicionales (`FAN_DELETE`, `FAN_MOVED_FROM`, `FAN_MOVED_TO`, `FAN_CREATE`) y el procesamiento despacha por tipo de evento emitiendo `operation_type`; `ev.path is None` se descarta (D12/RN-110).
- `agent-decision-engine`: `auto_restore` cae a snapshots cuando el `content_b64` activo es `None` (F3).
- `agent-config-commands`: `restore_file` cae a snapshots cuando el `content_b64` activo es `None` (F3).
- `agent-core`: `state.json` se escribe en un único punto no destructivo que preserva `ruleset_version`, `last_stream_command_id` y `rules` (F2); el handler de shutdown propaga `set_shutdown(True)` al publisher (G4); el loop principal arranca la tarea de renovación de cert (G3).

## Impact

- **Código agente**: `agent/detector.py` (máscaras + dispatch + `operation_type`), `agent/__main__.py` (shutdown flag, `_cert_renewal_loop`, registro de tarea), `agent/bootstrap.py` (extracción de función de renovación reutilizable), `agent/config.py` (`cert_renewal_check_interval_h`), `agent/state.py` (`save_state` no destructivo / punto único), `agent/rules.py` (delega persistencia a `AgentState`), `agent/decision.py` (fallback snapshots), `agent/commands.py` (fallback snapshots).
- **Payload de evento**: nuevo campo `operation_type`; el backend consumer ya acepta `hash: null` (D12).
- **Dependencias externas**: ninguna nueva (httpx ya está en `agent/requirements.txt`).
- **Backend**: el endpoint `/agents/renew` NO se implementa en esta change (fuera de scope, change futura).
- **Reglas cubiertas**: RN-110, RN-111, RN-71, RN-93, RN-30–33 (restauración), RN-39/40 (drenaje). **Decisiones aplicadas**: D12, D13, D8 (sin HTTP server más allá de la llamada saliente puntual).
- **Dependencia DAG**: C25 (`agent-reconnect-order`) — archivada como `2026-06-23-agent-reconnect-order`. Satisfecha.
