## Context

**Secuencia de arranque actual** (`agent/__main__.py`):

| Línea | Paso |
|---|---|
| `:211-215` | `load_state(state.json)` y `RulesCache` |
| `:225` | `BaselineEngine(cfg, master_secret)` |
| `:258` | `engine.init_scan(cfg.watch_paths)` |
| `:307` | `Publisher(cfg, queue, valkey_client)` |
| `:313` | `DecisionEngine(...)` |
| `:325` | `FanotifyDetector(...)` (sólo Linux) y registro de callbacks del publisher |
| `:373` | `coroutines.append(detector.start())` |
| `:380` | `await decision_engine.rehydrate(publisher)` (RN-83) |
| `:381` | `await asyncio.gather(*coroutines)` |

`init_scan` (`agent/baseline.py:463-513`) recorre cada `watch_path` con `rglob`, clasifica symlink
antes que archivo regular (D33/RN-127, `:480`), descarta lo que resuelve fuera de la raíz (`:493`) y
**omite todo path con entrada** (`:481-482`, `:497-499`). Sólo escribe entradas para paths sin
entrada, y lo hace en silencio. `verify_entry` (`:565`) verifica la etiqueta GCM del blob, no el
archivo, y nadie la llama al arrancar. `list_entries` (`:403`) descifra todos los blobs y devuelve
sus paths; `read_entry` (`:376`) devuelve la entrada o `None`; `_sha256_file` (`:191`) hashea y
devuelve el contenido.

**Camino normal de un evento** (`FanotifyDetector._process_event`, `agent/detector.py:823`). Las
tres ramas comparten la misma forma:

1. `read_entry(path)` y `previous_hash` (`:827-828`).
2. Construcción de `DetectedChange` con `event_id` nuevo y `parent_event_id` desde `_pending`.
3. `_stage_approval_candidate(change)` (`:871`, `:976`, `:1123`): guarda cifrado el contenido exacto
   detectado, ligado al `event_id`, uno por path.
4. `DecisionEngine.evaluate_and_act(change)` **antes** de tocar el baseline (D14; `:876`, `:981`,
   `:1131`).
5. Actualización del baseline según la acción: `mark_absent` en borrado (`:896`), `write_entry` en
   creación (`:996`), `add_snapshot` sin reemplazar el hash activo en modificación (BUG-03, `:1165`).
6. `await publisher.publish(enriched_payload)` y luego `commit_fn()` (`:897-900`, `:997-1000`,
   `:1167-1170`).

La rama `file_created` descarta el evento si el hash nuevo coincide con el de la entrada y el tipo
de objeto no cambió (`:945-951`); la rama de `close_write` descarta si el hash coincide
(`:1022-1036`) y, si el archivo ya no existe, emite `file_absent`.

**Consecuencias de BUG-03 para el reconcile.** Una modificación detectada y no aprobada deja el hash
activo del baseline en el valor anterior. Sin un criterio adicional, cada reinicio volvería a
encontrar el hash distinto y re-emitiría el mismo `file_modified`. El candidato de aprobación
(`stage_approval_candidate`, `baseline.py:662`) ya guarda el hash de la última detección del path y
se consume al aprobar (`update_from_command`, `:576-659`): es el registro de «ya reportado» que D80
designa.

**Estado persistido.** `AgentState` (`agent/state.py:17-24`) tiene `ruleset_version`,
`last_stream_command_id` y `rules`; `save_state` (`:57-75`) los serializa los tres y nada más. Todos
los escritores (`agent/rules.py:119`, `agent/commands.py:281,621,713`, `agent/publisher.py:406,459,471`)
pasan por `save_state` con la misma instancia de `AgentState` creada en `__main__.py:212`.

**Backend.** `Event` (`backend/app/modules/events/models.py:25-94`) no tiene marca de origen
offline; `_ingest_event_outcome` (`backend/app/modules/events/service.py:281`) construye la fila en
`:402-428` leyendo cada clave con `.get()` tolerante. `EventOut` (`router.py:30-68`) agrega campos
de forma aditiva (precedentes `is_symlink`, `action_failed`, `action_error`). La última migración es
`backend/db/migrations/022_add_alert_channel_accepted_at.sql`; el patrón de columna anulable sin
backfill es `021_add_agent_queue_pressure_high.sql`.

**Frontend.** `EventDetail.tsx:119-122` renderiza los indicadores del encabezado
(`SymlinkBadge`, `StatusBadge`, `ActionFailedBadge`, `AckStatusBadge`); cada uno se omite cuando
no aplica (`:348-369`). El tipo del evento es `EventListItem` (`frontend/src/api/events.ts:25-70`), extendido por `EventDetail` (`:77`).

**Decisiones normativas que gobiernan esta change** — cerradas, no se re-deciden acá: D80/RN-174
con su ampliación de `1c308d5`. Restricciones heredadas: D8/RN-108 (sin HTTP en el agente), D14
(decidir antes de mutar el baseline), BUG-03, D33/RN-127, D49/RN-143, RN-83, RN-71, D3 (migraciones
SQL manuales).

## Goals / Non-Goals

**Goals:**

- Que toda modificación, eliminación o creación ocurrida con el agente detenido en una raíz ya
  inicializada produzca **un** evento con `detected_offline: true` al arrancar.
- Que esos eventos recorran exactamente el mismo camino que un evento de fanotify: candidato de
  aprobación, `DecisionEngine`, actualización del baseline, publisher, `commit_fn`.
- Que la recreación idéntica de un archivo cuya eliminación offline ya se reportó se detecte como
  `file_created` (hoy queda suprimida).
- Que una modificación offline ya reportada no se re-emita en cada reinicio.
- Que el primer arranque y una raíz nueva sigan dando de alta en silencio.

**Non-Goals:**

- Cerrar la ventana entre el reconcile y la instalación de las marcas de fanotify (riesgo declarado
  abajo).
- Reconstruir el instante real del cambio o el proceso causante: no hay fuente confiable.
- Cambiar el orden del publisher o el límite de ingesta: los resuelven las Changes 61 (D79) y 67
  (D85).
- Introducir el registro `schema_migrations`: lo hace la Change 66 (D84).
- Mostrar la marca en la tabla de eventos: D80 pide sólo el detalle.

## Decisions

### D-1. Clasificación en `BaselineEngine`, emisión en el detector

`BaselineEngine.reconcile_on_start(watch_paths, initialized_roots) -> ReconcilePlan` es
**síncrono y sin efectos sobre el baseline**: lee entradas, hashea el disco y devuelve una lista de
hallazgos `OfflineFinding(path, event_class)` más los contadores de lo que no produce evento
(`unchanged`, `suppressed_already_reported`, `errors`). La emisión la hace un método nuevo del
detector, `FanotifyDetector.emit_offline(finding)`, que delega en `_process_event`.

*Por qué*: D80 ubica `reconcile_on_start()` en `agent/baseline.py` y a la vez prohíbe publicar por
fuera del camino del detector. Separar «qué cambió» de «cómo se reporta» cumple las dos cosas: el
baseline no conoce al publisher ni al motor de decisión, y el detector no aprende a recorrer el
árbol.

*Alternativas descartadas*: que `reconcile_on_start` reciba un callback de emisión (acopla el
baseline al loop asyncio y mezcla lectura con mutación del baseline a mitad del recorrido); que el
reconcile viva entero en el detector (contradice D80 y duplica el recorrido de `init_scan`).

### D-2. Un solo camino: `_process_event` con clase forzada

`_process_event(fan_event, *, forced_class: str | None = None, detected_offline: bool = False)`.
Si `forced_class` no es `None` reemplaza a `_classify_event(fan_event.mask)`; `detected_offline` se
copia a las tres construcciones de `DetectedChange`. `emit_offline` arma un `FanotifyEvent` sintético
con `path`, `pid=None`, `uid=None`, `exe=None`, `mask=0` y `timestamp` igual al instante de emisión
en ISO 8601 UTC, y llama a `_process_event` con `forced_class` ∈ {`file_deleted`, `close_write`,
`file_created`}. La clase `file_modified` del hallazgo se mapea a `close_write`, que es la rama que
hoy produce `file_modified`.

*Por qué*: reutiliza las tres ramas sin copiarlas, incluidas sus guardas (descarte por hash igual,
symlink como objeto, BUG-03, D14). Si el archivo cambió entre la clasificación y la emisión, la rama
actúa sobre el estado vigente, igual que con un evento de fanotify tardío.

*Alternativas descartadas*: sintetizar una máscara `FAN_*` (depende de `_HAS_FAN`; en un entorno sin
fanotify `_classify_event` devuelve siempre `file_modified`, `detector.py:813-814`, y los tests
dejarían de distinguir las clases); extraer una función `_emit_change` común (refactor mayor de
`_process_event` sin beneficio funcional para esta change).

### D-3. `detected_offline` en todo payload; contexto de proceso nulo

`DetectedChange.detected_offline: bool = False`, serializado siempre por `to_event_data`. Los eventos
del reconcile llevan `true`; los de fanotify, `false`. `FanotifyEvent.pid` y
`DetectedChange.process_pid` pasan a `int | None`, y el reconcile emite los tres campos de proceso en
`None`, con el mismo argumento que `DecisionEngine.rehydrate` (`agent/decision.py:158-168`): el
proceso causante no existe por definición y `0` significa root. No cambia `schema_version`: el campo
es aditivo y opcional en el contrato.

*Por qué siempre presente*: permite al backend distinguir «agente nuevo, detección en línea»
(`false`) de «agente anterior a esta change» (clave ausente → `NULL`).

### D-4. `detected_at` es el instante del reconcile

El instante real del cambio es desconocido. `mtime` es controlable por quien modificó el archivo y
no existe para un archivo borrado, así que no se usa ni se transporta. La marca `detected_offline`
es precisamente la que le dice al operador que `detected_at` es una cota superior.

### D-5. `initialized_roots`: clave, alta y poda

- **Clave**: el string de `watch_path` tal como figura en la configuración, el mismo con el que
  `init_scan` construye los paths de las entradas (`rglob` sobre `Path(watch_path)`, `:472`).
- **Alta**: `init_scan(watch_paths, initialized_roots)` recorre **sólo** las raíces que no están en
  el conjunto, las da de alta en silencio como hoy y devuelve las que completó en
  `ScanReport.initialized`. Una raíz inexistente no se marca. Un error de lectura en un archivo
  individual no impide marcar la raíz: se registra como hoy (`baseline.scan_error`).
- **Raíces ya inicializadas**: `init_scan` no las recorre. Sus archivos sin entrada quedan para el
  reconcile, que los emite como `file_created` y el detector les crea la entrada en la rama normal
  (`detector.py:991-996`).
- **Runtime**: `handle_update_config` (`agent/commands.py:578`) agrega a `initialized_roots` las
  raíces que da de alta con `run_scan` y quita las que se retiran, en el mismo `save_state` que ya
  hace (`:621`).
- **Poda al arrancar**: el conjunto se interseca con `cfg.watch_paths` antes de `init_scan`. Una
  raíz que dejó de vigilarse pierde la continuidad; si vuelve, se trata como nueva.
- **Persistencia**: `AgentState.initialized_roots: list[str]` (lista ordenada para serializar de
  forma determinista), incluida en `load_state` y `save_state`. Ausente → lista vacía.

### D-6. Algoritmo de `reconcile_on_start`

Para cada raíz `r` en `initialized_roots ∩ watch_paths`:

**Fase A — entradas.** Para cada path de `list_entries()` ubicado bajo `r` (igualdad para una raíz
archivo, `Path(path).is_relative_to(r)` para un directorio; un archivo borrado no se puede resolver
con `realpath`, por eso la pertenencia es por ubicación):

| Entrada | Disco | Hallazgo |
|---|---|---|
| `present` | `os.path.lexists` falso | `file_deleted` |
| `present` | hash igual y mismo tipo de objeto | ninguno (`unchanged`) |
| `present` | hash distinto o tipo cambiado | `file_modified`, salvo D-7 |
| `absent` | existe | `file_created` |
| `absent` | no existe | ninguno |

El hash del disco sigue la regla de D33/RN-127: para un symlink, `sha256(os.readlink(path))`; para
un archivo regular, el SHA-256 del contenido completo (también si supera 10 MiB, igual que
`write_entry`).

**Fase B — archivos sin entrada.** Se recorre `r` con el mismo iterador de candidatos que
`init_scan` (extraído a un helper privado compartido: symlink antes que archivo, descarte de
directorios, `_target_in_scope` para archivos regulares). Todo candidato sin entrada →
`file_created`.

Los hallazgos se emiten ordenados por path. Un `BaselineIntegrityError` o un `OSError` sobre un path
se registra (`baseline.reconcile.path_error`), suma a `errors` y no detiene el recorrido.

### D-7. Supresión de una modificación ya reportada

`BaselineEngine.read_approval_candidate(path) -> ApprovalCandidate | None` descifra el candidato del
path. Un hallazgo `file_modified` se suprime (`suppressed_already_reported`) si y sólo si el
candidato existe, tiene `status == "present"`, su `hash` es igual al hash actual del disco y su tipo
de objeto (`symlink_target` nulo o no) coincide con el del disco. Un candidato ilegible (etiqueta GCM
inválida, JSON corrupto) se trata como inexistente: el error se resuelve **hacia reportar**, nunca
hacia callar. La supresión aplica sólo a `file_modified`, como dice D80: un borrado reportado deja la
entrada `absent` y una creación reportada deja la entrada `present`, así que ninguno de los dos se
repite.

### D-8. Ubicación en el arranque y tolerancia a fallas

En `agent/__main__.py`, dentro del `try` de `:376`, después de `decision_engine.rehydrate(publisher)`
y antes del `gather`. Un helper `_run_offline_reconcile(engine, detector, state, cfg)` ejecuta
`reconcile_on_start` en `asyncio.to_thread` (hashea todo el árbol), emite los hallazgos con
`await detector.emit_offline(...)` uno por vez y registra
`log.info("baseline.reconcile.complete", deleted=..., modified=..., created=...,
suppressed_already_reported=..., unchanged=..., errors=..., duration_ms=...)`.

Una excepción inesperada del reconcile se registra como `baseline.reconcile.failed` y **no** aborta
el arranque: la detección en línea es la función primaria. Sin detector (plataforma no Linux,
`:354`) el reconcile no corre y se registra `baseline.reconcile.skipped` con
`reason="no_detector"`, porque sin el camino del detector no hay forma permitida de emitir.

*Por qué después de `rehydrate`*: RN-83 resuelve primero las acciones pendientes del journal; si una
restauración rehidratada repone un archivo, el reconcile ya ve el estado final y no reporta un
cambio que la propia plataforma revirtió.

### D-9. Backend: columna anulable, ingesta tolerante, salida aditiva

- `023_add_event_detected_offline.sql`: `ALTER TABLE events ADD COLUMN IF NOT EXISTS
  detected_offline BOOLEAN;` — sin `DEFAULT`, sin backfill, sin índice, idempotente, con el
  encabezado de convención (número, D80/RN-174, change). Cuando la Change 66 (D84/RN-178) introduzca
  `000_schema_migrations.sql`, `023` queda registrado por número; esta change no lo necesita.
- `Event.detected_offline: bool | None = Field(default=None)`.
- Ingesta: `True`/`False` se persisten tal cual; clave ausente → `NULL`; cualquier otro valor →
  `NULL` y `log.warning("consumer.detected_offline_invalid", ...)`, sin rechazar el evento (mismo
  criterio que D72 para `queue_pressure_high`). No influye en el status, la severidad ni la
  supersesión.
- `EventOut.detected_offline: bool | None = None`; `EventDetailOut` lo hereda.

### D-10. Frontend: indicador en el detalle

`EventListItem.detected_offline?: boolean | null` en `frontend/src/api/events.ts`. Componente
`OfflineDetectionBadge` en `EventDetail.tsx`, junto a los demás indicadores del encabezado, que se
renderiza sólo con `true` y explica en su `title` que el cambio ocurrió con el agente detenido y que
`detected_at` es el instante en que se detectó al arrancar. `false`, `null` y ausente no renderizan
nada. La tabla de eventos no cambia.

## Risks / Trade-offs

- **[Ventana sin cobertura entre el reconcile y las marcas de fanotify]** El reconcile hashea antes
  de que `detector.start()` instale las marcas (`detector.py:1187`); un cambio dentro de esa ventana
  no lo ve ninguno de los dos. → Se declara como limitación. Instalar las marcas antes del reconcile
  exigiría partir `start()` y tratar los eventos duplicados que la cola acumularía durante el
  recorrido; queda fuera del alcance de D80.
- **[Ráfaga contra el límite de ingesta]** Un reinicio tras muchos cambios offline emite una ráfaga
  que el límite actual (100 ev / 60 s) va a frenar con `event_nack` retenible. → No se pierde nada
  (la cola es durable); la Change 67 (D85) lo resuelve con token bucket.
- **[Orden de la ráfaga]** Sin la Change 61, el publisher puede adelantar eventos nuevos sobre un
  backlog. → El apply de esta change espera a que la 61 esté archivada.
- **[Costo de arranque]** El reconcile hashea todo archivo de las raíces inicializadas: el mismo
  orden de costo que un primer escaneo, en cada arranque. → Se corre en un hilo y se mide con
  `duration_ms`.
- **[Archivo grande modificado se re-emite en cada reinicio]** `stage_approval_candidate` no guarda
  candidato por encima de 10 MiB (`baseline.py:731-732`), así que D-7 nunca suprime esa
  modificación. → Consecuencia literal de D80; se documenta en el código. Re-reportar es el lado
  seguro.
- **[Actualización de un agente existente]** Un `state.json` previo no tiene `initialized_roots`: en
  el primer arranque tras actualizar, todas las raíces se tratan como nuevas y los archivos sin
  entrada creados durante esa parada se dan de alta en silencio, como hoy. Las eliminaciones y
  modificaciones de archivos con entrada **sí** se reportan, porque el reconcile corre sobre las
  raíces recién marcadas. → Se declara en el procedimiento de despliegue.
- **[Archivo con error de lectura en el primer escaneo]** La raíz se marca igual; en el arranque
  siguiente ese archivo, todavía sin entrada, sale como `file_created`. → Preferible a dejar la raíz
  sin marcar, que absorbería en silencio todo lo creado después.

## Migration Plan

1. Aplicar `023_add_event_detected_offline.sql` con `psql` antes de desplegar el backend nuevo. La
   migración es aditiva: el backend anterior funciona con la columna presente.
2. Desplegar el backend y el frontend. Un agente anterior sigue funcionando (sin la clave →
   `NULL`).
3. Desplegar el agente. Primer arranque: `initialized_roots` se puebla y se emiten los cambios
   offline de los archivos que ya tenían entrada.

**Rollback**: volver al agente anterior ignora `initialized_roots` (clave desconocida que su
`save_state` descarta en la próxima escritura). La columna puede quedar; no hace falta revertirla.

## Open Questions

Ninguna bloqueante. D-5 (poda de `initialized_roots` al retirar una raíz) es una derivación del
criterio «la raíz completó un primer escaneo» de D80; si el usuario prefiere conservar la marca
de una raíz retirada, cambia una línea y un test.
