## Context

El agente FIM ya tiene: scaffold systemd (C05), canal mTLS (C06), baseline AES-GCM (C07) y transporte Valkey Streams con cola offline, publisher HMAC y heartbeat (C08). El detector es el módulo que falta para que el agente perciba cambios en el filesystem y los convierta en eventos.

El detector corre en un hilo separado (fanotify es una API de I/O bloqueante en C), consume la API pública de `agent/baseline.py` para comparar hashes, y enqueue en `agent/queue.py` para que el publisher (C08) los entregue al backend.

## Goals / Non-Goals

**Goals:**
- Implementar `agent/detector.py` con el loop fanotify sobre los `watch_paths` de configuración.
- Comparar hash actual vs baseline; ignorar cambios sin delta real.
- Generar diff unificado textual; solo hash para binarios.
- Deduplicar eventos por path en memoria.
- Recargar paths en caliente al recibir `update_config`.
- Shutdown graceful SIGTERM: deja de leer fanotify, drena cola 30 s.

**Non-Goals:**
- Evaluación de reglas y acciones (C10 — decision engine).
- Detección de archivos nuevos creados (solo modificaciones a archivos con baseline).
- Diff de archivos binarios más allá de hash + hex dump parcial.
- Modo permiso (FAN_ACCESS_PERM) — solo notificación pura (RN-02).

## Decisions

### D1 — FAN_MARK_FILESYSTEM sobre cada watch_path

**Elegido**: `FAN_MARK_FILESYSTEM` por mount point del path.
**Por qué**: Marca el FS completo de una vez — elimina el race de registrar watchers por subdirectorio al aparecer `mkdir`. Es el comportamiento indicado en la arquitectura (doc arquitectura_stack.md §"Por qué fanotify").
**Alternativa descartada**: `FAN_MARK_INODE` / `FAN_MARK_MOUNT` por subdirectorio — requiere bookkeeping de inodos y pierde eventos en nuevos subdirectorios.

### D2 — Loop fanotify en hilo con asyncio.to_thread

**Elegido**: El loop de lectura de eventos fanotify corre en un `threading.Thread` dedicado (o `asyncio.to_thread` para bloques cortos); comunica al loop principal con una `asyncio.Queue`.
**Por qué**: La API de pyfanotify es bloqueante. Ponerla en un thread mantiene el loop asyncio libre para heartbeat, command consumer y shutdown.
**Alternativa descartada**: Pyfanotify sobre fd con `asyncio.add_reader` — pyfanotify no expone el fd directamente de forma estable en 0.3.0.

### D3 — Detección texto/binario por null-byte en primer bloque

**Elegido**: Leer los primeros 8 KB del archivo; si contiene byte `\x00` → binario; si no → texto.
**Por qué**: Simple, sin dependencia extra (no chardet). Consistente con la heurística usada en git y diff.
**Alternativa descartada**: chardet — overhead de dependencia adicional para una heurística que no necesita ser exacta.

### D4 — Deduplicación en memoria con `set` de paths pendientes

**Elegido**: `pending_paths: set[str]` en memoria. Si un path ya está en el set al llegar un nuevo evento fanotify: crear evento con `parent_event_id` apuntando al anterior (tomado del objeto en cola), añadir al set.
**Por qué**: La lógica de cadena de eventos (parent_event_id) está definida en la arquitectura y el backend ya la maneja. El set es O(1).
**Limitación conocida**: Si el agente se reinicia, el set se vacía. Los eventos pre-existentes `pending` en el backend no bloquean la detección — es un trade-off aceptado (el backend deduplica por event_id, no por path).

### D5 — Recarga hot de watch_paths vía comando update_config

**Elegido**: El command consumer (C08) ya escucha el stream `commands`. Al recibir `update_config`, llama `detector.reload_paths(new_paths)` que: desmarca los FAN_MARK anteriores, re-marca los nuevos, dispara baseline scan para paths nuevos sin baseline (delegado a `agent/baseline.py`).
**Por qué**: Reutiliza el consumer existente sin añadir otro listener.

### D6 — Graceful shutdown con asyncio.Event

**Elegido**: `stop_event: asyncio.Event` compartido. SIGTERM → `stop_event.set()` → el thread fanotify para de leer (chequea el event en cada iteración) → el loop principal drena la cola con timeout 30 s → heartbeat con `shutdown: true` → exit 0.
**Por qué**: asyncio.Event es thread-safe y ya es el patrón usado en el bootstrap (C08).

## Risks / Trade-offs

- **Solo Linux** — pyfanotify no funciona en Windows/macOS. Los tests unitarios del detector mockean la API fanotify; los de integración requieren Linux con `CAP_SYS_ADMIN`. → Misma estrategia que C07 y C08: skip en Windows con `pytest.mark.skip`.
- **Eventos perdidos durante desmarcado** — al hacer reload_paths hay una ventana de ~microsegundos sin marcado. → Aceptado (RN-02 ya establece modo notificación, no hay garantía de cero pérdida).
- **Archivo borrado entre evento y lectura** — fanotify notifica pero el archivo ya no existe cuando el detector intenta leerlo para hash/diff. → El detector trata `FileNotFoundError` como evento `absent` y actualiza baseline a `status: absent`.
- **Archivos grandes** — diff textual de archivos de varios MB puede demorar. → Se aplica un límite de 1 MB para diff; archivos más grandes → solo hash.

## Migration Plan

1. El módulo `agent/detector.py` se agrega al repo; `agent/bootstrap.py` lo inicializa en el lifespan.
2. No hay cambios a APIs de módulos previos (baseline, queue, publisher).
3. El servicio systemd no requiere cambio de Unit — el detector es parte del proceso agente.
4. Rollback: revertir el commit que añade detector.py y su wiring en bootstrap.py.
