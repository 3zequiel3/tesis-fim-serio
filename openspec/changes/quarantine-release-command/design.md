## Context

**Estado actual — agente.** La cuarentena tiene dos llamadores: `DecisionEngine._quarantine`
(`agent/decision.py:299-304`) usa el `event_id` del agente como `action_id`, y
`handle_quarantine_file` (`agent/commands.py:422-505`) usa el `command_id` del comando
(`journal_key`, `:458`, `:476`). La Change 64 (D82/RN-176) unifica ambos en
`quarantine_and_record` con `action_id = event_id` **siempre**, deja la entrada de baseline en estado
explícito `"quarantined"` con `quarantine_action_id`, conserva `snapshots` y contenido
(`mark_quarantined`) y suprime el eco del `unlink` por estado. Esta change se apoya en ese estado; no
lo reimplementa.

El artefacto vive en `QuarantineStore.artifact_path(action_id, source_path)`
(`agent/quarantine.py:162-169`): `sha256(action_id || 0x00 || abspath)` + `.fimq`. Su metadata
cifrada (`_capture_source`, `:411-426`) guarda `action_id`, `original_path`, `kind`
(`regular | symlink`), `mode`, `uid`, `gid`, `size` y `sha256`. `read_artifact` (`:497-499`)
autentica (AES-GCM), descifra y verifica `size`/`sha256` contra la metadata
(`_read_artifact`, `:501-581`); hoy no tiene llamadores. No existe operación de eliminación de un
artefacto fuera de `cleanup_expired` (`:237`), que lo borra al vencer `quarantine_retention_days`.

El publisher lee el stream `commands` con cursor persistido **después** del dispatch
(`agent/publisher.py:436-467`): la entrega es *at-least-once* y un comando puede re-entregarse tras
un reinicio. Los comandos destructivos de decisión se despachan desde la tupla de
`agent/publisher.py:574-577` hacia `commands.dispatch` (`agent/commands.py:107-202`), que filtra
`target_agent_id`, verifica HMAC y enruta por `type`; un tipo desconocido sólo emite
`commands.dispatch.unknown_type`.

`handle_restore_file` (`agent/commands.py:300-415`) es el patrón de escritura atómica vigente:
`.fim_restore_tmp` con `O_EXCL`, `fsync`, `fchown` antes que `fchmod` (D36/RN-130), `os.replace`.
`os.replace` **sobrescribe**: no sirve para la regla `path_occupied` de D83. El detector descarta
todo evento sobre `*.fim_restore_tmp` (`agent/detector.py:825-826`) y descarta un `file_created` cuyo
hash coincide con el del baseline (`:944-950`).

**Estado actual — journal y rehidratación.** `DecisionEngine.rehydrate` (`agent/decision.py:135-221`)
republica toda entrada `pending` del journal como evento; una acción que no sea `auto_restore` ni
`quarantine` sale como `alert_only` con `event_id` = clave del journal. Una entrada de journal de un
comando de liberación, si se rehidratara así, produciría un evento fantasma con el `command_id` como
`event_id`.

**Estado actual — backend.** Los comandos de decisión se firman y se insertan en el outbox
`published_commands` dentro de la transacción de la mutación (`actions/streams.py:111-237`,
D37/RN-131); `publish_pending_commands` hace el `XADD` después. `_write_audit`
(`actions/service.py:143-157`) escribe `audit_log` en la misma transacción. Las acciones exigen
`require_admin` (`actions/router.py:42-95`) y el detalle de evento también
(`events/router.py:163-176`). El consumer de `command_ack` toma `command_type` y `event_id` de la
fila persistida, nunca del ack (`agents/command_ack_consumer.py:184-201`), reconcilia
`baseline_entries` en un `ok` de `baseline_update` (`:252-253`, `_reconcile_baseline_entry`
`:280-299`) y avanza `ruleset_version_applied` para `_RECONCILE_ROOT_VERSION_TYPES` (`:73`,
`:256-257`). `_get_ack_status_map` (`events/router.py:221-238`) expone el `ack_status` del comando más
reciente de cada evento. La base de pruebas es PostgreSQL (`backend/tests/conftest.py:111`).

**Estado actual — frontend.** `EventDetail.tsx` habilita aprobar/rechazar con
`canApprove = status === 'pending' || status === 'alert_only'` (`frontend/src/pages/EventDetail.tsx:68`)
y abre `RejectModal` (`:316-321`); las mutaciones viven en `frontend/src/hooks/useEventActions.ts`
con manejo de 409 (`:46-62`).

## Goals / Non-Goals

**Goals:**

- Un único comando firmado `release_quarantine` con tres modos, cuyo efecto en el agente es
  autenticado, sin sobrescritura, verificado desde disco e idempotente por `command_id`.
- Un endpoint admin que encola el comando y audita en la misma transacción, sin mutar el evento.
- Reconciliación de `baseline_entries` cuando `restore_original` se confirma.
- `quarantine_state` = `released | discarded` visible y filtrable tras la confirmación.
- Un control en el detalle del evento que no se ofrece fuera de `quarantine_state = quarantined`.

**Non-Goals:**

- Liberación en lote. D83 fija «de a un evento».
- Cambiar la máquina de estados de eventos (RN-11, RN-12, RN-72) o agregar columnas a `events`.
- Liberar artefactos anteriores a D82 nombrados por `command_id`: se declaran no liberables
  (`artifact_not_found`) por D82.
- Restaurar symlinks en modo `restore_original` (ver D-6 y Open Questions).
- Reparar la rehidratación de entradas de journal de `restore_file`/`quarantine_file`, que hoy
  también se republican como `alert_only`; se registra como observación, fuera de alcance.

## Decisions

### D-1 · Payload del comando

```
type="release_quarantine", command_id, event_id (int, PK del backend),
agent_event_id (UUID del agente = action_id del artefacto), target_agent_id, path,
mode ∈ {restore_original, restore_baseline, discard}, expected_sha256,
ruleset_version (sólo restore_original), issued_at, schema_version, signature
```

D83 enuncia `{event_id, mode}`; el resto es el sobre que ya llevan `restore_file`/`quarantine_file`
(`actions/streams.py:183-191`) más los dos datos que el agente necesita para encontrar y autenticar
el artefacto sin estado propio: `agent_event_id` (por D82, el `action_id`) y `expected_sha256`
(`event.hash_detected`, que D83 nombra como el hash esperado del backend). El **motivo** del operador
no viaja al agente: es dato de auditoría y queda sólo en `audit_log`.

*Alternativa descartada:* que el agente resuelva el artefacto por `event_id` recorriendo el
directorio de cuarentena y descifrando metadata. Es O(n) en descifrados y agrega un índice que D82
ya hace innecesario.

### D-2 · Endpoint en el router de eventos, lógica en el módulo `actions`

`POST /events/{id}/quarantine/release` (ruta fijada por D83) vive en `events/router.py`, pero delega
en `actions/service.release_quarantine_single` y `actions/streams.enqueue_release_quarantine`, junto
a approve/reject. Cuerpo `ReleaseQuarantineRequest {mode, reason}` con `extra="forbid"`; `reason` se
recorta y MUST tener entre 1 y 500 caracteres. Respuesta `202 Accepted`
`{event_id, command_id, mode, ack_status: "pending"}`: la operación es asíncrona y su resultado
llega por `command_ack`. Errores: `403` (no admin o `password_change_required`), `404` (evento
inexistente), `409 {code: "quarantine_not_releasable"}` (`quarantine_state ≠ quarantined`, o
`hash_detected` vacío), `409 {code: "release_in_progress"}` (ya hay un `release_quarantine` con
`ack_status ∈ {pending, acked}`), `422` (validación).

### D-3 · Elegibilidad y concurrencia sin tocar el evento

El evento no cambia de estado (D83), así que no hay `UPDATE` optimista que serialice dos pedidos. El
servicio toma `SELECT … FOR UPDATE` sobre la fila del evento, evalúa `quarantine_state` con el
helper de la Change 64 y busca un `PublishedCommand` `release_quarantine` del evento con
`ack_status ∈ {pending, acked}`. Sólo si no lo hay inserta el comando y el `audit_log` y comitea. Un
`failed` o `timeout` previo **no** bloquea un nuevo intento: es como D83 garantiza «a lo sumo una
liberación o descarte **completado** por evento» sin dejar al operador sin salida ante un fallo.

### D-4 · `quarantine_state` derivado, sin columna

La Change 64 deriva `quarantine_state` en lectura. Esta change agrega dos ramas, evaluadas antes que
`quarantined`: existe un `release_quarantine` del evento con `ack_status = acked` y
`CAST(payload AS JSONB)->>'mode' = 'discard'` → `discarded`; con otro `mode` → `released`. El `mode`
se lee del payload firmado persistido en la fila (confiable, igual que `command_type` en el
consumer), nunca del ack. Es filtrable en SQL desde `GET /events`.

*Alternativa descartada:* una columna `release_mode` en `published_commands`. Requiere migración
(y su registro, Change 66) para un dato que ya está en el payload.

### D-5 · Reubicación sin sobrescritura: `os.link` sobre un temporal

Los dos modos de restauración escriben `<path>.fim_restore_tmp` con `O_CREAT|O_EXCL`, `fsync`,
`fchown` y después `fchmod`, y publican con `os.link(tmp, path)` + `unlink(tmp)` + `fsync` del
directorio. `link(2)` falla con `EEXIST` si el destino existe, de forma atómica: es la garantía de
`path_occupied` sin ventana TOCTOU. Antes del `link` se hace un `lstat(path)` para fallar temprano
con el mismo código. Un `EXDEV`/`EPERM`/`EOPNOTSUPP` de `link` se traduce por
`action_error_from_oserror` (vocabulario cerrado de D36/RN-130). El sufijo `.fim_restore_tmp` ya está
excluido por el detector, así que el temporal no genera eventos; el `link` produce un `FAN_CREATE`
sobre el path final.

*Alternativas descartadas:* `os.replace` (sobrescribe); `renameat2(RENAME_NOREPLACE)` vía ctypes
(mismo efecto, más superficie nativa y sin soporte en todos los filesystems).

### D-6 · `restore_original` = aprobar

Orden, cada paso con su código de error:

1. Guarda de obsolescencia: `ruleset_version < state.ruleset_version` → `stale_ruleset_version`.
2. Contención en `watch_paths` (D18/RN-116) → `path_outside_watch_paths`.
3. `read_artifact(artifact_path(agent_event_id, path))`: inexistente → `artifact_not_found`; fallo
   de autenticación → `artifact_integrity_failed`; `action_id`/`original_path` distintos →
   `artifact_identity_mismatch`; `sha256 ≠ expected_sha256` → `artifact_hash_mismatch`.
4. `kind = symlink` → `unsupported_file_type` (Non-Goal; ver Open Questions).
5. `lstat(path)` existe → `path_occupied`.
6. **Adopción del baseline antes de reubicar** (D83): se guarda la entrada previa y se escribe
   `present` con el contenido, hash y metadata del artefacto, `mode` sin `S_ISUID|S_ISGID`. Así el
   `FAN_CREATE` del paso 7 encuentra `previous_hash == current_hash` y el descarte existente
   (`agent/detector.py:944-950`) lo suprime.
7. Escritura y `link` (D-5) con `mode & ~(S_ISUID|S_ISGID)`, `uid`/`gid` del artefacto.
8. Verificación por relectura con el helper de D81/RN-175: `verify_failed` o
   `hash_mismatch_after_restore`.
9. Eliminación autenticada del artefacto (D-8).
10. `state.ruleset_version = ruleset_version`, `save_state`.

Un fallo en 5–7 restaura la entrada de baseline previa (`quarantined`) y conserva el artefacto. Un
fallo en 8 también revierte el baseline y conserva el artefacto; el archivo escrito queda en disco y,
como su contenido ya no coincide con el baseline revertido, el detector lo reporta como un cambio
real, que es lo honesto.

### D-7 · `restore_baseline` y `discard`

`restore_baseline`: pasos 2, 3 (el artefacto debe existir y autenticar: es lo que se va a eliminar y
lo que prueba que la cuarentena sigue vigente), 5; luego `select_restorable_content` sobre la entrada
`quarantined` (`agent/baseline.py:207`) → `no_restorable_content` si no hay contenido;
metadata (`mode`, `uid`, `gid`) de la entrada de baseline, como `handle_restore_file`, sin quitar
bits (es la versión aprobada); escritura y `link` (D-5); verificación (D81); la entrada pasa a
`present` (D82: «tras una restauración verificada»); eliminación del artefacto. No lleva
`ruleset_version`: no cambia qué contenido está aprobado.

`discard`: pasos 2 y 3, luego eliminación del artefacto. Baseline y evento no cambian; la entrada
sigue `quarantined`.

### D-8 · Eliminación autenticada del artefacto

`QuarantineStore.remove_artifact(action_id, source_path, expected_sha256)` toma el lock del store,
re-lee el artefacto **sin** contenido (`_read_artifact(include_content=False)`), revalida identidad
y hash, hace `unlink` y `fsync` del directorio. Así nunca se borra un archivo que no sea el artefacto
autenticado que el backend nombró.

### D-9 · Journal e idempotencia por `command_id`

El handler escribe journal `pending` con clave `command_id` y acción `release_quarantine` antes del
primer efecto (RN-83) y lo cierra `completed`/`failed`. `DecisionEngine.rehydrate` MUST NOT
republicar esas entradas como eventos: las deja intactas para que la re-entrega del comando (el
cursor se persiste después del dispatch) las complete.

Registro local `executed_commands.json` en `storage.journal_dir` (mismo dominio de durabilidad,
`0700`): mapa `command_id → {type, ok, error, executed_at}`, escrito con temporal + `fsync` +
`os.replace` **antes** de publicar el `command_ack`. Si el `command_id` ya está registrado, el
handler re-publica el mismo ack y no ejecuta nada. Poda por antigüedad mayor que
`quarantine_retention_days` al escribir (un comando más viejo que el artefacto más viejo ya no puede
tener efecto).

Re-ejecución tras una caída entre el efecto y el registro: si el artefacto no existe, el path existe
con hash igual al objetivo del modo y la entrada de baseline está `present` con ese hash, el handler
concluye que la liberación ya ocurrió y responde `ok`. En `discard` no hay forma de distinguir
«ya descartado» de «vencido»: responde `artifact_not_found`, y el registro hace que esto sólo pase
si la caída ocurrió antes de registrarlo.

### D-10 · Reconciliación en el backend

`release_quarantine` entra a los tipos confirmables de `backend-command-ack`. Con `status = ok`, el
consumer lee `mode` del payload persistido: `restore_original` → `_reconcile_baseline_entry`
(usa `event.hash_detected`, que es el `expected_sha256` enviado) y avance monotónico de
`ruleset_version_applied`. `restore_baseline` y `discard` no tocan `baseline_entries`: el backend
nunca registró la cuarentena en esa tabla. `ruleset_version` para `restore_original` se obtiene con
`increment_ruleset_version` al encolar, como `_approve_single` (`actions/service.py:221`).
`baseline_entries` **no** se escribe al encolar: el contenido no está aprobado en el host hasta que el
agente confirma.

### D-11 · Auditoría

Una entrada `audit_log` con `action = "quarantine_release"`, `target_type = "event"`,
`target_id = event.id` y `detail = {mode, reason, command_id}`, en la misma transacción que la fila
del outbox. El resultado de ejecución vive en `PublishedCommand.ack_status`; no se duplica en
`audit_log`.

### D-12 · Frontend

`ReleaseQuarantineModal` (atómico, junto a `RejectModal`): tres opciones con texto explicativo de la
consecuencia de cada una —`restore_original` advierte que **aprueba** el contenido—, `textarea` de
motivo obligatoria y confirmación. El botón «Liberar cuarentena» se muestra sólo con
`event.quarantine_state === 'quarantined'` y se deshabilita con `ack_status === 'pending'`. Un `409`
muestra un toast específico por `code` e invalida la query del evento.

## Risks / Trade-offs

- [La Change 64 implementa el `file_created` sobre una entrada `quarantined` como reporte
  incondicional, aun con hash idéntico] → `restore_baseline` reportaría su propia escritura. Un test
  de esta change lo fija (spec `agent-quarantine-release`); si falla, `restore_baseline` adopta el
  mismo orden que `restore_original` (entrada `present` antes del `link`, revertible), lo que
  contradice la letra de D82. Ver Open Questions.
- [Caída entre la adopción del baseline y el `link`] → el baseline queda `present` sin archivo. El
  journal `pending` y la re-entrega del comando la resuelven por D-9; si el comando no se re-entrega,
  el próximo arranque (D80/RN-174) reportará un `file_deleted` real sobre una entrada `present`.
- [`link(2)` no soportado por el filesystem del `watch_path`] → falla honesta con el código cerrado de
  D36; no hay degradación a `os.replace`.
- [Registro local corrupto o borrado] → se pierde sólo la deduplicación; la re-ejecución sigue
  protegida por la autenticación del artefacto y por `path_occupied`.
- [El operador elige `restore_original` sin entender que aprueba] → el modal lo dice explícitamente y
  `audit_log` guarda el motivo.

## Migration Plan

Sin migración de esquema. Despliegue: backend y frontend primero (un agente viejo ignora el tipo y el
comando termina `timeout`), luego agente. Rollback: revertir el agente deja artefactos y registro
intactos; revertir el backend deja filas `release_quarantine` en el outbox que nadie nuevo produce.

## Open Questions

1. **Eco de `restore_baseline` sobre una entrada `quarantined`.** D82 dice que un archivo nuevo en una
   ruta `quarantined` «se reporta» y que la entrada pasa a `present` «tras una restauración
   verificada». Este diseño asume que el descarte por hash idéntico (`detector.py:944-950`) sigue
   aplicando a entradas `quarantined`, como aplica a `present`. Confirmar contra el diseño de la
   Change 64 antes de `/opsx:apply`.
2. **`restore_original` de un artefacto `symlink`.** Se rechaza con `unsupported_file_type`; `discard`
   sí aplica. Ratificar o extender D83.
3. **Comando obsoleto.** `baseline_update` obsoleto retorna sin ack (`agent/commands.py:253-260`) y
   termina en `timeout`. Aquí se publica ack de error `stale_ruleset_version` para que el operador lo
   vea sin esperar el barrido. Ratificar.
