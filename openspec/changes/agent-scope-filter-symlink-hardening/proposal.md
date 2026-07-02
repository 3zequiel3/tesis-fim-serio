## Why

La revisión dual-judge de C37 (`agent-fanotify-scope-filter`, 2026-07-02) encontró el hallazgo MEDIUM-2: el containment por `realpath` completo introducido por D31/RN-125 dereferencia el componente final de un path antes de compararlo contra los `watch_paths`, por lo que un symlink de escape creado dentro de un `watch_path` (p. ej. `/etc/evil -> /root/.ssh/authorized_keys`) resuelve a un destino fuera de alcance y su creación se descarta silenciosamente — el link, que es en sí mismo un vector de persistencia clásico y una entrada de directorio nueva en scope, queda invisible para el FIM. D31 conflaba dos preguntas distintas: "¿el link está en scope?" (ubicación) vs. "¿el destino resuelto está en scope?" (contenido). D33/RN-127 se cerró el 2026-07-02 para refinar la cláusula de symlinks de D31 sin reescribirla, y esta change la implementa cross-capa.

## What Changes

- **Containment por ubicación del link (agente)**: nueva función `_path_location_in_scope(path, watch_paths)` en `agent/detector.py` que canonicaliza únicamente el directorio padre (`os.path.realpath(os.path.dirname(path))`) y compara el basename literal, sin seguir el componente final aunque sea un symlink. Reemplaza al containment por `realpath` completo de D31 en el punto de descarte de `_read_loop`. La función anterior `_realpath_in_scope` se renombra `_target_in_scope` y queda solo para checks de metadata (saber si el destino resuelto cae en scope).
- **Symlink-as-object (agente)**: para todo symlink en scope por ubicación, el agente hace `os.lstat`/`os.readlink` y **nunca** abre, hashea ni cifra el contenido del destino, esté este dentro o fuera de scope. El evento se reporta con el léxico canónico existente de RN-71 (`file_created`/`file_deleted`/`file_modified`, sin `event_type` nuevo); `hash_detected = sha256(os.readlink(path))` (hash de la cadena del destino); no hay diff de contenido.
- **Baseline symlink-aware (agente)**: nueva función `write_symlink_entry` (`os.lstat`/`os.readlink`, `content_b64=None`, `hash=sha256(target)`); `BaselineEntry` gana `symlink_target: str | None = None` (retrocompatible vía `from_dict`); `init_scan` y `run_scan` chequean `is_symlink()` **antes** de `is_file()`.
- **Persistencia del metadato (backend)**: `Event` gana columnas `is_symlink: bool = False` y `symlink_target: str | None = None`; migración SQL idempotente en `backend/db/migrations/` (convención D3, sin Alembic; próximo número tras `004_add_command_ack_tracking.sql`); `ingest_event` toma ambos campos del payload con `.get()` tolerante; `EventOut` los expone.
- **Indicador en UI (frontend)**: badge/indicador en la tabla y el detalle de eventos que distingue un evento sobre un symlink (mostrando `symlink_target`) de un evento sobre un archivo regular; el tipo TS de `frontend/src/api/events.ts` gana los dos campos.
- **Contador detective opcional `hardlink_suspected` (agente)**: se incrementa en el heartbeat cuando se crea un archivo regular en scope con `st_nlink >= 2`, sin cambio de comportamiento. Los hardlinks quedan documentados como limitación conocida no resuelta (limitación inherente a POSIX).
- Resuelve como efecto colateral el hallazgo LOW-1 de la misma revisión: al reportarse y registrarse en baseline en el momento de creación, el borrado posterior de un symlink ya no genera un `file_deleted` espurio.

## Capabilities

### New Capabilities
<!-- Ninguna. Esta change refina el comportamiento de capabilities existentes (detección, baseline, ingesta, UI de eventos); no introduce una capability nueva. -->

### Modified Capabilities
- `agent-fanotify-detector`: el containment de descarte pasa de "por destino resuelto" (D31) a "por ubicación del link" (`_path_location_in_scope`); se agrega la rama symlink-as-object (reporte con léxico RN-71, hash de la cadena del destino, sin leer el contenido del destino) y el contador detective opcional `hardlink_suspected` en el heartbeat.
- `agent-baseline`: el scan clasifica `is_symlink()` antes de `is_file()`, escribe entradas de symlink vía `write_symlink_entry` (metadata del link, sin cifrar contenido del destino) y `BaselineEntry` gana `symlink_target`.
- `backend-events-api`: el modelo `Event` gana las columnas `is_symlink`/`symlink_target` (con migración SQL idempotente) y `EventOut` las expone en el schema de salida de eventos.
- `backend-event-consumer`: `ingest_event` extrae `is_symlink`/`symlink_target` del payload del stream con `.get()` tolerante y los persiste en el `Event`.
- `frontend-events`: la tabla y el detalle de eventos muestran un badge/indicador de symlink con su `symlink_target`, distinguiéndolo de un evento sobre un archivo regular.

## Impact

- **Agente**:
  - `agent/detector.py`: `_path_location_in_scope` (nueva), `_target_in_scope` (renombre de `_realpath_in_scope`), `_read_loop` (punto de descarte por ubicación), `_process_event` (rama symlink-as-object: `lstat`/`readlink`, hash de la cadena), contador `hardlink_suspected`.
  - `agent/baseline.py`: `write_symlink_entry` (nueva), `BaselineEntry.symlink_target`, `init_scan`/`run_scan` (chequeo `is_symlink()` antes de `is_file()`).
  - `agent/heartbeat.py`: campo opcional `hardlink_suspected` en el payload.
  - `agent/tests/`: cobertura de la matriz de edge cases (create/delete/modify de symlink, dir intermedio simbólico in/out, `watch_path` simbólico, archivo regular) y de la no-regresión del borrado legítimo de archivo regular en scope.
- **Backend**:
  - `backend/app/modules/events/models.py`: columnas `is_symlink`/`symlink_target` en `Event`.
  - `backend/db/migrations/005_*.sql`: migración idempotente (`ADD COLUMN IF NOT EXISTS`).
  - `backend/app/modules/events/service.py`: `ingest_event` toma `is_symlink`/`symlink_target` del payload con `.get()`.
  - `backend/app/modules/events/router.py` (o schema equivalente): `EventOut` expone el metadato.
  - `backend/tests/`: ingesta de un evento de symlink con su metadato y su exposición en `EventOut`.
- **Frontend**:
  - `frontend/src/api/events.ts`: tipo del evento gana `is_symlink`/`symlink_target`.
  - Componente de tabla y detalle de eventos: badge/indicador de symlink.
- **Reglas cubiertas**: RN-04, RN-125, RN-127. **Decisiones aplicadas**: D33 (refina D31/RN-125).
- **Dependencias del DAG**: C37 (`agent-fanotify-scope-filter`) aplicada en local (rama `devel`). D33/RN-127 cerrada el 2026-07-02.
- **Sin regresiones**: un `file_deleted` de un archivo regular dentro de scope DEBE seguir publicándose (la trampa de C35); `_path_location_in_scope` canonicaliza solo el directorio padre, que siempre existe en un delete, por lo que el borrado legítimo se preserva.
