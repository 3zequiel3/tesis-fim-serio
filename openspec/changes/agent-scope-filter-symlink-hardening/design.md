## Context

C37 (`agent-fanotify-scope-filter`) implementó D31/RN-125: un filtro de containment por `realpath` completo en `_read_loop` que descarta todo evento cuyo `os.path.realpath()` no cae en un `watch_path` canonicalizado. La revisión dual-judge de C37 (2026-07-02) encontró MEDIUM-2: ese `realpath` completo **dereferencia el componente final** antes de comparar, así que un symlink de escape creado dentro de un `watch_path` (`/etc/evil -> /root/.ssh/authorized_keys`) resuelve a un destino fuera de alcance y su creación se descarta silenciosamente. El link es en sí mismo una entrada de directorio nueva en scope — un vector de persistencia clásico — que un FIM debe reportar. D31 conflaba "¿el link está en scope?" (ubicación) con "¿el destino resuelto está en scope?" (contenido).

D33/RN-127 se cerró el 2026-07-02 en los appendices canónicos (`docs/arquitectura_stack.md` §D33, `docs/reglas_de_negocio.md` D33/RN-127) y refina la cláusula de symlinks de D31 sin reescribirla. Esta change es **cross-capa** (agente + backend + frontend) e implementa D33.

Restricciones vigentes que el diseño respeta:
- `FAN_MARK_FILESYSTEM` es un tradeoff arquitectónico intencional (limitación del kernel), no el bug — no se toca.
- Cola acotada `_raw_queue` (`maxsize=1000`), reactiva: no se admite ningún escaneo de filesystem completo (descarta la vía "resolver hardlinks").
- Backend single-instance (RN-76); migraciones raw SQL sin Alembic (D3).
- Léxico canónico de eventos RN-71: sin `event_type` nuevo.
- El agente NO tiene servidor HTTP (D8): la señal operativa viaja por heartbeat.

## Goals / Non-Goals

**Goals:**
- Que la creación de un symlink de escape dentro de un `watch_path` deje de ser invisible: se reporta como `file_created`.
- Tratar el symlink como objeto de filesystem propio: nunca seguir el link, nunca leer/hashear/cifrar el contenido del destino (dentro o fuera de scope).
- Persistir y exponer el metadato del symlink end-to-end: agente → backend (`Event` + `EventOut`) → frontend (badge).
- Resolver como efecto colateral el LOW-1 (delete espurio) al registrar el symlink en baseline al crearse.
- No re-romper el borrado legítimo de un archivo regular en scope (la trampa de C35).

**Non-Goals:**
- Resolver hardlinks: queda documentado como limitación conocida (POSIX-inherente), con un contador detective opcional `hardlink_suspected`. No hay cambio de comportamiento por hardlinks.
- Reabrir o modificar los artefactos de C37: esta es una change nueva; su delta refina el requirement de containment vía MODIFIED, sin tocar los archivos de C37.
- Introducir un `event_type` nuevo o cambiar el léxico RN-71.
- Firmar/verificar el destino del symlink, seguir cadenas de symlinks, o normalizar destinos relativos a absolutos (se reporta el string crudo de `os.readlink`).

## Decisions

### D-1: Containment por ubicación del link (`_path_location_in_scope`), no por destino resuelto

`_path_location_in_scope(path, watch_paths)` canonicaliza **solo el directorio padre** (`os.path.realpath(os.path.dirname(path))`) y compara el `basename` literal contra los `watch_paths` canonicalizados, sin seguir el componente final. Reemplaza a `_realpath_in_scope` en el punto de descarte de `_read_loop`. La función vieja se renombra `_target_in_scope` y queda solo para checks de metadata (saber si el destino resuelto cae en scope), fuera del path de descarte.

- **Por qué el parent y no el path completo**: el parent es un directorio que **siempre existe** en el momento del evento (incluso en un DELETE, donde el componente final ya no existe). Canonicalizar el parent es seguro y determinista; canonicalizar el componente final lo dereferencia (el bug de D31) o falla en un delete.
- **Alternativa descartada — `os.path.realpath(path, strict=False)` + comparar el último segmento aparte**: más frágil (mezcla resolución parcial con string-munging) y no expresa la intención "no seguir el link final".
- **Alternativa descartada — `lstat` del path completo para decidir scope**: `lstat` no canonicaliza symlinks intermedios del parent, así que un dir intermedio simbólico rompería el containment. Canonicalizar el parent con `realpath` sí resuelve intermedios correctamente.

### D-2: Philosophy B — symlink-as-object (nunca seguir el link)

Para todo path en scope por ubicación cuyo componente final sea un symlink, `_process_event` toma la rama symlink: `os.lstat`/`os.readlink`, `hash_detected = sha256(os.readlink(path))`, `diff = None`. Se reporta con el léxico RN-71 existente (`file_created`/`file_deleted`/`file_modified`) — el re-pointing cambia el string de `readlink`, luego su hash, luego se detecta como `file_modified`. El payload gana `is_symlink=true` y `symlink_target`.

- **Por qué hashear la cadena del destino y no su contenido**: el objeto que cambió es el link, no el archivo apuntado. Hashear el contenido del destino (a) requeriría abrir un path posiblemente fuera de scope (fuga de RN-04) y (b) confundiría "cambió el link" con "cambió el destino". `sha256(readlink)` detecta re-pointing, que es la amenaza.
- **Por qué sin `event_type` nuevo**: RN-71 fija el léxico; el metadato `is_symlink` distingue el caso sin ampliar el vocabulario de estados.
- **Alternativa descartada — Philosophy A (seguir el link si el destino está en scope)**: reintroduce exactamente el conflado de D31 y no reporta el link como objeto.

### D-3: Baseline clasifica `is_symlink()` antes de `is_file()`

`Path.is_file()` **sigue** symlinks, así que un symlink se clasificaría como archivo regular. `init_scan`/`run_scan` chequean `p.is_symlink()` primero y, si es symlink, llaman `write_symlink_entry` (`os.lstat`/`os.readlink`, `content_b64=None`, `hash=sha256(target)`, `symlink_target=target`). `BaselineEntry` gana `symlink_target: str | None = None`, retrocompatible en `from_dict` (default). Un archivo regular alcanzado vía un dir intermedio simbólico que apunta fuera de scope se sigue omitiendo con warning (el contenido real vive afuera) — pero el symlink intermedio, si está en un `watch_path`, se reporta como objeto propio.

- **Efecto colateral (LOW-1)**: como el symlink queda en baseline al crearse, un borrado posterior es un `file_deleted` real distinguible, no espurio. `rglob` no recursa dentro de dirs simbólicos, así que no hay doble conteo.

### D-4: Persistencia backend con migración idempotente (D3, sin Alembic)

`Event` gana `is_symlink: bool = False` y `symlink_target: str | None = None`. Migración raw SQL `backend/db/migrations/005_*.sql` con `ADD COLUMN IF NOT EXISTS` (idempotente, re-ejecutable). `ingest_event` toma ambos con `.get()` tolerante (agentes viejos que omiten las keys ingieren sin error). `EventOut` los expone, mismo patrón que `ack_status` de D30/C36.

- **Por qué tolerante**: durante un rollout parcial pueden coexistir agentes con y sin el campo; el backend no debe romper la ingesta por su ausencia (el consumer ya elige keys por `.get()`).

### D-5: Hardlinks — limitación documentada + contador detective opcional

`realpath`/`lstat` no distinguen un hardlink de un archivo regular; determinar si otro nombre del mismo inodo cae fuera de scope exigiría un escaneo de filesystem completo, incompatible con la cola acotada reactiva. Se documenta como limitación POSIX-inherente. Mitigación: baseline cifrado AES-256-GCM bajo `0700`. Señal detective opcional sin cambio de comportamiento: `hardlink_suspected` en el heartbeat, incrementado al crear un archivo regular en scope con `st_nlink >= 2`.

- **Por qué opcional y solo contador**: `st_nlink >= 2` tiene alto falso-positivo y no determina scope; usarlo para clasificar sería peor que no hacer nada. Como contador es una señal barata para el operador sin afectar detección.

## Risks / Trade-offs

- **[MODIFIED sobre un requirement aún no archivado]** El requirement "Detector discards events outside the configured watch_path scope" fue ADDED por el delta de C37, que todavía NO está archivado; solo vive en el delta de C37, no en `openspec/specs/`. → **Mitigación**: el DAG garantiza que C37 se archiva antes que C39 (C39 depende de C37). Al momento de archivar C39 el requirement ya estará en el main spec. Si por alguna razón se archivara C39 antes que C37, el sync de specs fallaría al no encontrar el requirement; el orden de archivado debe respetar el DAG.
- **[Symlink target string crudo, sin normalizar]** Se reporta `os.readlink` tal cual (puede ser relativo). → **Mitigación**: es el dato fiel de lo que el atacante escribió; normalizar podría ocultar la intención. La detección de re-pointing por hash del string es correcta con destinos crudos.
- **[Falso negativo de hardlink]** Un hardlink a un archivo fuera de scope no se detecta como escape. → **Mitigación**: aceptado como limitación conocida (POSIX); baseline cifrado + `hardlink_suspected` acotan/visibilizan el impacto.
- **[auto_restore sobre un symlink]** `select_restorable_content` retorna `None` cuando `content_b64=None`, así que un restore degrada limpiamente (no hay contenido que restaurar). → **Mitigación**: cubrir con un test explícito de que auto_restore sobre un symlink no crashea y no intenta restaurar bytes.
- **[Doble punto de verdad del containment]** Coexisten `_path_location_in_scope` (descarte) y `_target_in_scope` (metadata). → **Mitigación**: nombres explícitos y comentario; solo `_path_location_in_scope` se usa en el descarte, `_target_in_scope` nunca ahí.

## Migration Plan

1. **Agente primero** (compatible hacia atrás con el backend viejo): `_path_location_in_scope`, rama symlink-as-object, `write_symlink_entry`, `BaselineEntry.symlink_target`, `hardlink_suspected`. El backend viejo ignora `is_symlink`/`symlink_target` del payload (elige keys por `.get()`), así que el agente puede desplegarse antes sin romper nada.
2. **Backend**: migración `005_*.sql` idempotente (`ADD COLUMN IF NOT EXISTS`), `Event`, `ingest_event` (`.get()` tolerante), `EventOut`.
3. **Frontend**: tipo TS + badge en tabla/detalle. Renderiza el badge solo si `is_symlink`; los eventos regulares no cambian.
4. **Rollback**: revertir por capa en orden inverso. La migración es idempotente y las columnas tienen default, así que dejar las columnas tras un rollback de código es inofensivo (los eventos viejos ya tenían defaults). No hay migración de datos destructiva.

## Open Questions

Ninguna que bloquee la implementación. El diseño (árbol de decisión, matriz de edge cases verificada, pseudocódigo de `_path_location_in_scope`, manejo de baseline y recomendación de hardlinks) está cerrado en engram (`sdd/agent-fanotify-scope-filter/hardening-design`, obs #238) y en los appendices D33/RN-127. Detalles de implementación abiertos (no suposiciones nuevas): nombre exacto de la columna del frontend/badge y el número final de secuencia de la migración si aparece otra migración intermedia antes del apply.
