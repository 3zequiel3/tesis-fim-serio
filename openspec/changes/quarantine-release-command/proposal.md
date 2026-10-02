## Why

Una cuarentena hoy es un viaje de ida. El agente cifra el archivo en `/var/lib/fim-agent/quarantine/`
(`QuarantineStore.quarantine`, `agent/quarantine.py:171`) y retira la entrada de origen, pero no
existe ninguna operación —ni en el agente, ni en el backend, ni en la UI— para devolverlo, restaurar
la versión aprobada en su lugar o descartar el artefacto. `QuarantineStore.read_artifact`
(`agent/quarantine.py:497`), el único camino que autentica y descifra un artefacto, no tiene ningún
llamador. El whitelist de comandos que el publisher despacha (`agent/publisher.py:574-577`) y
`commands.dispatch` (`agent/commands.py:107-202`) conocen `baseline_update`, `restore_file`,
`quarantine_file`, `update_config` y `rescan_baseline`; ninguno libera una cuarentena. Un falso
positivo puesto en cuarentena sólo se corrige hoy con intervención manual como root en el host, sin
traza en `audit_log` y sin que el baseline del agente ni `baseline_entries` del backend se enteren.

Origen: guía de laboratorio de la tesis v29 (ítems L-2…L-9), verificada contra `devel` `b3751b8`;
base para el candidato `v5.0-tesis`. La decisión que gobierna esta change es **D83/RN-177**
(`docs/reglas_de_negocio.md:2737`, fila D83 en `docs/arquitectura_stack.md:2723`), ampliada y
cerrada en `5aa6887` junto con **D82/RN-176**, de la que depende. No se abre ninguna suposición de
producto nueva; los puntos de implementación que el texto de D83 no fija se resuelven en
`design.md` y los tres que conviene ratificar figuran en su sección «Open Questions».

## What Changes

- **Comando firmado `release_quarantine` (D83/RN-177).** Payload firmado con HMAC-SHA256 con
  `event_id`, `agent_event_id` (el UUID del agente, que por D82 es siempre el `action_id` del
  artefacto), `path`, `mode` (`restore_original | restore_baseline | discard`) y `expected_sha256`;
  `restore_original` lleva además `ruleset_version`. Se agrega al whitelist del publisher
  (`agent/publisher.py:574-577`) y a `commands.dispatch`, detrás de la verificación HMAC única
  existente.
- **Handler del agente `handle_release_quarantine`.** Autentica el artefacto con `read_artifact`
  (identidad + `sha256` contra `expected_sha256`) antes de cualquier efecto. `restore_original`
  equivale a **aprobar**: adopta el baseline **antes** de reubicar, reubica sin sobrescribir
  (`path_occupied`), quita setuid/setgid, verifica releyendo desde disco (helper de D81/RN-175),
  elimina el artefacto y avanza `state.ruleset_version` con la guarda de obsolescencia de
  `baseline_update`. `restore_baseline` restaura la versión aprobada desde el baseline sin
  sobrescribir y elimina el artefacto. `discard` sólo elimina el artefacto. Artefacto vencido por
  retención o nombrado por `command_id` (anterior a D82) → `artifact_not_found`.
- **Registro local de comandos destructivos ejecutados.** La re-entrega del mismo `command_id`
  re-publica el mismo `command_ack` sin repetir efectos.
- **Backend: `POST /events/{id}/quarantine/release`.** Sólo admin, de a un evento, `mode` y motivo
  obligatorios. Encola el comando en el outbox transaccional (`published_commands`, D37/RN-131) en
  la misma transacción que la entrada de `audit_log` (RN-94). **El estado del evento no cambia**: el
  resultado se lee del `PublishedCommand` `release_quarantine` y de `quarantine_state`.
- **`command_ack` de `release_quarantine`.** Un `ok` de `restore_original` reconcilia
  `baseline_entries` (D1/RN-104) y avanza `ruleset_version_applied` (D5/RN-106).
- **`quarantine_state` derivado refleja la liberación.** `released` tras un `restore_original` o
  `restore_baseline` confirmado; `discarded` tras un `discard` confirmado. La derivación base la
  introduce la Change 64; esta change la extiende.
- **Frontend.** Botón «Liberar cuarentena» en el detalle del evento, visible sólo con
  `quarantine_state = quarantined`, con un modal que obliga a elegir modo y escribir motivo.

No hay cambios **BREAKING**: el comando, el endpoint y el modal son aditivos; un agente anterior
ignora `release_quarantine` como tipo desconocido (log `commands.dispatch.unknown_type`) y el
comando termina en `timeout` por el barrido existente. No hay migración de esquema.

## Capabilities

### New Capabilities

- `agent-quarantine-release`: semántica del handler `release_quarantine` en el agente —
  autenticación del artefacto, los tres modos, no sobrescritura, verificación desde disco,
  eliminación del artefacto, guarda de `ruleset_version` e idempotencia por `command_id`.
- `backend-quarantine-release`: endpoint `POST /events/{id}/quarantine/release`, elegibilidad,
  autorización, motivo obligatorio, encolado firmado en el outbox y entrada en `audit_log`.

### Modified Capabilities

- `agent-command-dispatch`: `release_quarantine` entra al whitelist del publisher y a
  `commands.dispatch`, sujeto a la verificación HMAC única.
- `backend-command-ack`: `release_quarantine` es un comando confirmable; su `ack` `ok` en modo
  `restore_original` reconcilia `baseline_entries` y avanza `ruleset_version_applied`.
- `backend-events-api`: `quarantine_state` deriva `released` y `discarded` a partir del
  `release_quarantine` confirmado.
- `frontend-events`: control de liberación de cuarentena en el detalle del evento.

## Impact

- **Agente:** `agent/commands.py` (nuevo handler y rama de dispatch), `agent/publisher.py`
  (whitelist), `agent/quarantine.py` (lectura por identidad y eliminación autenticada del
  artefacto), `agent/baseline.py` (adopción del baseline desde el contenido del artefacto, sobre la
  API `mark_quarantined`/estado `"quarantined"` de la Change 64), `agent/decision.py`
  (`rehydrate` no republica entradas de journal `release_quarantine` como eventos), nuevo módulo de
  registro de comandos ejecutados.
- **Backend:** `backend/app/modules/events/router.py` (endpoint), `backend/app/modules/actions/`
  (`schemas.py`, `service.py`, `streams.py`), `backend/app/modules/agents/command_ack_consumer.py`,
  derivación de `quarantine_state` (Change 64).
- **Frontend:** `frontend/src/api/actions.ts`, `frontend/src/hooks/useEventActions.ts`,
  `frontend/src/pages/EventDetail.tsx`, nuevo `frontend/src/components/ui/ReleaseQuarantineModal.tsx`.
- **Dependencias del DAG:** **Change 64** (`quarantine-baseline-preservation`:
  `quarantine_and_record`, `mark_quarantined`, estado de baseline `"quarantined"`,
  `action_id = event_id`, `quarantine_state`) y, transitivamente, **Change 63**
  (`agent-restore-verify-from-disk`: helper de relectura). Ninguna de las dos está archivada al
  proponer; `/opsx:apply` de esta change MUST correr después de archivar ambas.
- **Reglas:** RN-177 (nueva), RN-176 (dependencia), RN-175 (helper de verificación), RN-94
  (preservada), RN-104 y RN-106 (reconciliación en el ack), RN-116 (contención en `watch_paths`),
  RN-131 (outbox), RN-71 (léxico).
- **Re-medición:** única, sobre `v5.0-tesis` (ver Change 61).
