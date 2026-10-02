## Context

**Estado actual — la cuarentena vacía el baseline.** La entrada de baseline tiene dos estados,
`present` y `absent` (`agent/baseline.py:67`). `mark_absent` (`:385-401`) construye una entrada nueva
con todo nulo y `snapshots=[]`. El detector la invoca después de una cuarentena exitosa en dos ramas:
`file_created` (`agent/detector.py:990-992`) y la rama genérica `file_modified` (`:1157-1158`). Como
`select_restorable_content` (`agent/baseline.py:207-228`) recorre `content_b64` y `snapshots`, después
de una cuarentena no queda nada que restaurar.

**Estado actual — el eco.** El detector no tiene supresión de eventos propios por origen: sólo filtra
el temporal `.fim_restore_tmp` (`agent/detector.py:825-826`) y descarta por igualdad de hash
(`:945-951`, `:1023-1036`). `QuarantineStore.quarantine` (`agent/quarantine.py:171-198`) termina en
`_remove_matching_source` → `os.unlink(source)` (`:626`). El kernel entrega `FAN_DELETE` (o
`FAN_MOVED_FROM`), `_classify_event` (`agent/detector.py:805-821`) lo clasifica `file_deleted`, y la
rama `:847-904` evalúa reglas por ruta y, salvo un `auto_restore` exitoso, llama a `mark_absent`
(`:896`). Consecuencias según la regla que cubra la ruta: `alert_only`/`manual_review` publican un
evento extra y vacían la entrada; `quarantine` reintenta la cuarentena, falla con `file_not_found`
(`agent/quarantine.py:369-371`) y deja un evento `pending` espurio; `auto_restore` **restaura** lo que
el operador acababa de aislar.

**Estado actual — dos implementaciones.** `DecisionEngine._quarantine` (`agent/decision.py:299-311`)
usa el `event_id` del agente como identidad de acción, traduce `QuarantineError` a su `reason` y todo
lo demás a `quarantine_failed`; el journal lo maneja `evaluate_and_act` (`:96-125`): `pending` antes de
actuar, terminal en `commit_fn` después de publicar. `handle_quarantine_file`
(`agent/commands.py:422-505`) usa el `command_id` como identidad y clave de journal (`:458`), cierra el
journal antes del ack, construye el almacén de forma perezosa si no lo recibe (`:466-475`), mapea
`FileNotFoundError` a `quarantine_store_unavailable`, `OSError` con `action_error_from_oserror` y el
resto a `str(exc)` (`:494-499`), que puede llevar texto del sistema operativo. `dispatch` no le pasa el
`BaselineEngine` (`:170-180`).

**Estado actual — la identidad en el comando.** `enqueue_quarantine_file`
(`backend/app/modules/actions/streams.py:203-237`) firma `event_id = event.id`, el entero del backend.
El UUID del agente vive en `Event.event_id` (`backend/app/modules/events/models.py:29`). El agente, en
el camino del operador, hoy no conoce el UUID del evento que se rechaza.

**Estado actual — el rechazo.** `_reject_single` fija `status = rejected` en el UPDATE optimista
(`backend/app/modules/actions/service.py:283-301`) y encola `quarantine_file` (`:327`). El resultado
físico sólo es visible como `ack_status` del `PublishedCommand` más reciente
(`backend/app/modules/events/router.py:221-238`). Filtrar por `status = quarantined` no muestra lo
cuarentenado por el operador.

**Restricciones.** D82/RN-176 cerrada (ampliación de `5aa6887`, ratificada en `453caba`): estado explícito `"quarantined"` +
`quarantine_action_id`; eco suprimido por estado; terminal del journal en el llamador; `action_id =
event_id`; máquina de estados de eventos intacta; `quarantine_state` derivado en lectura. Sin servidor
HTTP en el agente (RN-108). Léxico en minúsculas snake_case (RN-71). Change 63 (D81/RN-175) se aplica
antes y deja en `agent/decision.py` un helper de verificación desde disco que usan `_auto_restore` y
`handle_restore_file`; también modifica en specs los requisitos «Handler restore_file» y «Action
failures carry a closed-vocabulary cause», por lo que esta change **no** los modifica (los
complementa con requisitos `ADDED`) para no pisar el texto de 63 al archivar.

## Goals / Non-Goals

**Goals:**

- La versión aprobada sobrevive a toda cuarentena, en los tres caminos (automático, operador,
  rehidratación) y sigue siendo restaurable.
- El `unlink` propio de la cuarentena no produce eventos, journal ni mutación del baseline.
- Una sola implementación de cuarentena con un solo vocabulario de fallas.
- El operador puede ver y filtrar lo que está en cuarentena, sea por regla automática o por rechazo,
  sin tocar la máquina de estados de eventos.

**Non-Goals:**

- Liberar, descartar o restaurar desde cuarentena (Change 65, D83/RN-177). Acá sólo se **lee**
  `release_quarantine`.
- Recuperar entradas ya vaciadas por cuarentenas anteriores: ni la entrada ni el artefacto conservan
  la versión aprobada (el artefacto guarda la versión alterada). Se declara, no se migra.
- Rediseñar la reconciliación al arrancar (Change 62, aplicada antes). Esta change sólo le agrega la
  guarda de RN-176: no reportar borrados sobre entradas `quarantined`.
- Controles de replay de comandos (`issued_at`/nonce). Riesgo preexistente fuera de alcance.
- Cambiar la política general de archivos nuevos en rutas `absent`.

## Decisions

### D-1. Estado `quarantined` con `quarantine_action_id` (opción A de RN-176)

`BaselineEntry.status` documenta tres valores; se agrega `quarantine_action_id: str | None = None`
después de `approved_event_id`. Default `None`, así que las entradas viejas parsean igual
(`from_dict`, `agent/baseline.py:90-93`). `write_entry`, `write_symlink_entry`, `mark_absent` y
`update_from_command` construyen entradas nuevas sin el campo, por lo que lo dejan en `None` sin
cambio de código: una aprobación o un re-escaneo limpian la marca solos.

*Alternativa descartada (opción B):* `absent` con contenido. Rompe la main spec «Baseline present and
absent states» y le da dos significados a `absent`, que consumen RN-60, RN-66 y RN-74.

*Costo aceptado:* un agente anterior no lee entradas con la clave nueva (`cls(**fields)` falla con
clave desconocida). Rollback = borrar esas entradas (ver Migration Plan).

### D-2. `mark_quarantined` copia la entrada previa; `clear_quarantine` la devuelve a `present`

`mark_quarantined(path, action_id)` lee la entrada, la copia con `dataclasses.replace` cambiando sólo
`status`, `quarantine_action_id` y `captured_at`, y la escribe con `_atomic_write` cifrado. Sin entrada
previa escribe una `quarantined` con nulos. Si la entrada ya es `quarantined` (segunda cuarentena en la
misma ruta, rehidratación), actualiza `quarantine_action_id` y conserva el contenido.

`clear_quarantine(path)` hace la transición inversa para el caso de restauración verificada: cambia
`status` a `present` y limpia `quarantine_action_id`, **sin** re-hashear ni leer metadatos del disco.
*Por qué no `write_entry`:* `write_entry` adopta `mode`/`uid`/`gid` del archivo en disco; tras una
restauración verificada coinciden con los aprobados, pero hacer depender la entrada del disco abre una
ventana para adoptar metadatos alterados entre la restauración y la escritura. La entrada preservada ya
es la verdad aprobada.

### D-3. `quarantine_and_record` en `agent/quarantine.py`, sin el terminal del journal

```
quarantine_and_record(*, store, baseline, journal, action_id, path) -> QuarantineOutcome
  1. journal.ensure_pending(action_id, path, "quarantine")
  2. store.quarantine(action_id, path)            # QuarantineError / OSError / Exception → causa
  3. baseline.mark_quarantined(path, action_id)   # error → "baseline_mark_failed"
  4. return QuarantineOutcome(artifact | None, error | None)
```

`QuarantineOutcome` es un dataclass inmutable. La función no levanta por fallas esperadas: mapea con
el vocabulario de D-5. El llamador decide el terminal:

- `DecisionEngine._quarantine` levanta `_ActionFailed(outcome.error)` o fija `quarantine_path`; el
  terminal sigue en `commit_fn` tras publicar (`agent/decision.py:110-122`), y la rehidratación lo
  cierra tras publicar (`:208-217`). Así un crash entre la acción y la publicación sigue dejando
  `pending` (FA3).
- `handle_quarantine_file` cierra `completed`/`failed` y después publica el ack.

*Por qué `ensure_pending` y no `write_pending`:* en el camino automático `evaluate_and_act` ya escribió
`pending` (`agent/decision.py:98`) y en la rehidratación la entrada existe; reescribirla cambiaría su
`created_at`, que la rehidratación usa como `detected_at` (`:169`). `JournalManager.ensure_pending`
escribe sólo si no hay entrada para la clave; si la hay, no la toca. Mismo HMAC, mismo `_write`.

*Por qué el marcado ocurre dentro y no en el detector:* el marcado tiene que ocurrir **antes** de que
el eco pueda procesarse. `evaluate_and_act` es síncrono y corre en el mismo loop que `_process_event`
(D8); el hilo lector sólo agenda con `call_soon_threadsafe`. Ningún eco se procesa entre la cuarentena
y el marcado si los dos ocurren dentro de la misma llamada síncrona. En el handler,
`quarantine_and_record` es síncrona y precede al primer `await` (`_publish_ack`).

*Alternativa descartada:* que la función cierre el journal (letra original de D82). Rompía el replay
del camino automático; la ampliación de RN-176 lo resolvió a favor del llamador.

### D-4. Identidad de acción = `event_id` del agente; el comando lleva `agent_event_id`

El único identificador común a los dos caminos es el UUID que el agente asigna al evento: en el camino
automático el backend todavía no asignó `id`. Por eso `enqueue_quarantine_file` agrega
`agent_event_id = event.event_id` al payload firmado. Es aditivo: `sign_payload` firma todas las
claves, el agente verifica todas las claves recibidas, y el `command_ack` sigue correlacionando por la
fila `PublishedCommand` (D-1bis), no por el payload.

El handler usa `agent_event_id` como identidad de artefacto **y** como clave de journal. Efecto
colateral deseado: si el agente cae con ese journal `pending`, la rehidratación lo reintenta con la
misma identidad y publica un evento con `event_id = agent_event_id`, que el backend descarta por
duplicado (RN-73), en vez del evento sintético con `event_id = command_id` que publica hoy.

Sin `agent_event_id` el handler no actúa y responde `quarantine_identity_missing` (literal que
`QuarantineStore.artifact_path` ya usa, `agent/quarantine.py:163-164`). *Alternativa descartada:*
caer al `command_id`; contradice «`action_id` = `event_id` siempre» y produciría artefactos que la
Change 65 no puede direccionar.

*Alternativa descartada:* reinterpretar `event_id` del comando como UUID. Cambia el significado de un
campo que comparten los cinco comandos y que el agente ya reporta en el `command_ack`.

### D-5. Vocabulario único de fallas

Orden de mapeo en `quarantine_and_record`: `QuarantineError` → `exc.reason`; `OSError` →
`action_error_from_oserror(exc, fallback="move_failed")`; cualquier otra → `quarantine_failed`; falla
del marcado → `baseline_mark_failed`. La construcción perezosa del almacén queda en el handler (es
adquisición de recurso, no cuarentena) y su falla sigue siendo `quarantine_store_unavailable`, igual
que `DecisionEngine` sin almacén. Se elimina `str(exc)`. Detalle a campos estructurados del log.

### D-6. Supresión del eco por estado

En `_process_event`, la entrada ya se lee al principio (`agent/detector.py:827`). Dos puntos de corte:

- rama `file_deleted`: primera instrucción, antes de `uuid.uuid4()` (`:848`);
- rama genérica: cuando `current_hash is None` (será `file_absent`), antes de asignar `event_id`
  (`:1043` decide `file_absent`; `event_id` se asigna en `:1092`).

Si `entry.status == "quarantined"`: `_trace_record("decision_suppressed", reason="quarantined_by_agent",
outcome="dropped", …)` y `return`. No se toca `_pending` ni `_event_to_path`.

*Por qué por estado y no por PID o por token esperado:* la Change 43 rechazó la auto-atribución por
PID; un token «espero un DELETE en X» se pierde si el agente cae entre el `unlink` y el eco, y el
estado persistido no. El riesgo aceptado está en RN-176.

### D-7. Ramas del detector

- `file_created` (`:990-996`): con cuarentena exitosa, no se llama nada (el marcado ya ocurrió); si la
  entrada previa es `quarantined`, no se llama `write_entry`/`write_symlink_entry`.
- Rama genérica (`:1155-1165`): con cuarentena exitosa, nada; con `auto_restore` exitoso y entrada
  previa `quarantined`, `clear_quarantine(path)`; el resto (`add_snapshot`) no cambia y no cambia el
  estado.
- Descartes por igualdad de hash (`:945-951`, `:1023-1036`) sobre una entrada `quarantined`:
  `clear_quarantine(path)` antes de retornar (D-10).
- `file_deleted` con `auto_restore` exitoso (`:886-894`): inalcanzable para una entrada `quarantined`
  (se suprimió antes); sin cambio.

### D-8. `quarantine_state` como expresión SQL única

En `backend/app/modules/events/service.py` se agrega `quarantine_state_expr()` que devuelve un
`sa.case(...)` con subconsultas `EXISTS` correlacionadas sobre `published_commands` (índice existente
en `event_id`):

```
base = or_(Event.status == quarantined,
           and_(Event.status == rejected, EXISTS(qf acked)))
case((not_(base), 'none'),
     (EXISTS(release acked, mode = 'discard'), 'discarded'),
     (EXISTS(release acked, mode in restore_*), 'released'),
     else_='quarantined')
```

El modo se lee del payload firmado con `cast(PublishedCommand.payload, JSONB)['mode'].astext`.
`list_events` selecciona `Event` junto con la expresión etiquetada y filtra con
`expr.in_(quarantine_state_filter)`; `get_event` y la cadena usan la misma expresión. Un enum
`QuarantineState(str, Enum)` valida el parámetro (422 en valor desconocido).

*Por qué en SQL y no en Python sobre la página:* el filtro tiene que afectar `total` y la paginación;
filtrar en Python después del `LIMIT` devuelve páginas cortas y totales falsos (la misma razón de
FIX-04). *Por qué leer `release_quarantine` ya:* RN-176 define el dominio completo; con las ramas
escritas, la Change 65 sólo produce filas. Se prueban sembrando filas `PublishedCommand` a mano.

*Alternativa descartada:* columna en `events` actualizada por el consumer de `command_ack`. RN-176 la
prohíbe y duplicaría estado derivable.

### D-9. Frontend

`QuarantineState` en `frontend/src/api/events.ts`, opcional en el tipo de lectura por tolerancia hacia
adelante. Un helper puro `getQuarantineStateMeta` (patrón de `getAckStatusMeta`) decide etiqueta y
estilo y devuelve `null` para `none`/ausente. `eventFilters.ts` parsea y serializa
`quarantine_state` como `status`/`severity` (`string[]`, el backend valida). El filtro reutiliza el
componente multi-select de la página de eventos.

### D-10. Recreación con exactamente el hash aprobado (ratificación de RN-176)

Los dos descartes por igualdad de hash del detector —rama `file_created` (`agent/detector.py:945-951`,
que además exige el mismo tipo de objeto) y rama genérica (`:1023-1036`)— comparan contra
`entry.hash`, que en una entrada `quarantined` es el hash aprobado preservado. Cuando el descarte se
produce y la entrada es `quarantined`, el detector llama a `clear_quarantine(path)` antes de
retornar: el archivo en disco es el contenido aprobado, el estado sano, equivalente a una
restauración verificada. El evento sigue sin publicarse (invariante de descarte de la Change 43).
Sin esto, la entrada quedaba `quarantined` con el archivo presente y un borrado posterior se suprimía
con `quarantined_by_agent`.

*Por qué `clear_quarantine` y no `write_entry`:* igual que en D-2, no se adoptan `mode`/`uid`/`gid`
del archivo recreado; la entrada conserva los metadatos aprobados.

*Por qué no exigir también igualdad de metadatos:* el descarte por hash nunca los comparó; exigirlo
sólo acá dejaría la entrada `quarantined` con el archivo presente, que es el defecto que la
ratificación corrige.

## Risks / Trade-offs

- [Crear en una ruta en cuarentena un archivo con contenido **distinto** del aprobado y luego borrarlo:
  el borrado no se reporta] → aceptado por RN-176; prueba que lo fija para que no cambie sin decisión.
- [Recreación con contenido idéntico al aprobado pero metadatos distintos (por ejemplo, bit setuid
  agregado): la entrada vuelve a `present` con los metadatos **aprobados** y el cambio de modo no se
  reporta] → es el comportamiento preexistente del descarte por hash (el detector no compara
  metadatos); D-10 no lo agrava porque no adopta metadatos del disco. Fuera de alcance.
- [`baseline_mark_failed`: la cuarentena ocurrió pero la entrada quedó `present`, así que el eco no se
  suprime y vuelve el comportamiento previo (evento `file_deleted` y `mark_absent`)] → el operador lo ve
  en el evento/`command_ack` con causa explícita; el artefacto se conserva.
- [Rollback del agente con entradas `quarantined`] → limitación declarada; Migration Plan.
- [Agente nuevo con backend viejo: `quarantine_file` sin `agent_event_id`] → el handler responde
  `quarantine_identity_missing` sin tocar el archivo. Backend y agente se despliegan desde el mismo
  repositorio y la re-medición es única sobre `v5.0-tesis`.
- [Colisión de clave de journal entre la entrada del camino automático y la del operador para el
  mismo UUID] → sólo posible si el journal del evento original quedó `pending` (crash entre publicar y
  `commit_fn`); `ensure_pending` no la pisa y la rehidratación converge en el mismo artefacto.
- [El cast a JSONB del payload falla si una fila tiene payload no JSON] → todas las filas se escriben
  con `json.dumps` (`streams.py`); el filtro de `command_type` restringe el cast a `release_quarantine`.
  Test con una fila de payload vacío de otro tipo.

## Migration Plan

1. Aplicar después de la Change 63 (verificar `openspec list`; si 63 no está aplicada, detenerse).
2. Sin migración SQL: `quarantine_state` es derivado.
3. Despliegue conjunto backend + agente (el backend nuevo agrega `agent_event_id`).
4. Entradas ya vaciadas por cuarentenas previas: no se recuperan; se declara en la tesis.
5. Rollback del agente: detener el agente, borrar las entradas `quarantined` del baseline (o
   re-escanear con `rescan_baseline` después del rollback, que reescribe por ruta existente) y
   desplegar la versión anterior. Rollback del backend: revertir; el campo extra en `quarantine_file`
   no lo lee un agente anterior y el campo `quarantine_state` desaparece de la respuesta.

## Open Questions

Ninguna abierta. Resueltas por la ratificación de RN-176 (`453caba`):

- Recreación con exactamente el hash aprobado → la entrada vuelve a `present` (D-10).
- `agent_event_id` es el nombre oficial del campo; la Change 65 ya lo usa en `release_quarantine`.
- Orden de apply 61 → 62 → 63 → 64: `reconcile_on_start` existe al aplicar esta change, y la tarea
  6.1 le agrega la guarda de RN-176.
