## Why

El baseline cifrado (C07) y el transporte Valkey (C08) están implementados. La pieza que cierra el loop de M2 es el detector reactivo: el módulo que escucha eventos `fanotify`, compara el hash actual contra el baseline y decide si crear un evento de cambio y encolarlo al publisher. Sin él el agente no puede detectar ni reportar ningún cambio en el filesystem.

## What Changes

- **Nuevo módulo `agent/detector.py`** — loop principal de detección sobre pyfanotify 0.3.0:
  - Marca filesystems completos con `FAN_MARK_FILESYSTEM` sobre cada `watch_path` configurado.
  - Exclusión obligatoria de `/var/lib/fim-agent/**` para evitar ciclos de auto-detección (RN-04).
  - Captura contexto del proceso causante: PID, UID, path del ejecutable (RN-01).
  - Modo notificación pura (post-write) — sin bloqueo de escritura (RN-02).
  - Compara SHA-256 del archivo actual contra el baseline cifrado: si hash igual → descarta evento (RN-01).
  - Genera diff textual unificado para archivos de texto; para binarios solo comparación de hash (RN-03).
  - Deduplicación en memoria: si un path ya tiene un evento `pending` en cola, el segundo cambio en el mismo path lo referencia vía `parent_event_id` (no duplica payload).
  - Recarga de `watch_paths` en caliente al recibir comando `update_config` desde el stream `commands` (RN-04).
  - Graceful shutdown SIGTERM: deja de aceptar eventos fanotify, drena la cola local (timeout 30 s), emite heartbeats con `shutdown: true`, exit 0 (RN-93).

## Capabilities

### New Capabilities

- `agent-fanotify-detector`: Loop de detección reactiva sobre fanotify — marcado de FS, captura de contexto de proceso, comparación contra baseline, generación de diff textual, deduplicación y recarga en caliente de paths.

### Modified Capabilities

_(sin cambios a requirements existentes)_

## Impact

- **`agent/detector.py`** — módulo nuevo; se inicializa desde `agent/bootstrap.py` y corre en el loop principal.
- **`agent/bootstrap.py`** — wiring del detector junto a publisher, heartbeat y command consumer ya existentes.
- **Dependencias**: consume la API pública de `agent/baseline.py` (C07) para lectura de hash, y de `agent/queue.py` + `agent/publisher.py` (C08) para encolar eventos. No modifica esas APIs.
- **`pyfanotify 0.3.0`** ya declarado en `agent/requirements.txt` desde C05.
- Reglas cubiertas: RN-01, RN-02, RN-03, RN-04, RN-93.
