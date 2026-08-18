## ADDED Requirements

### Requirement: ingest_event derives the event status from action and action_failed

`ingest_event` (`backend/app/modules/events/service.py`) SHALL derive `Event.status` from the `action` and `action_failed` keys of the incoming stream payload, via a pure function `derive_event_status(action, action_failed) -> EventStatus` defined in the same module. The payload keys MUST be read tolerantly — `.get("action")` and `bool(.get("action_failed", False))` — because the agent writes `action_failed` only on the failure path (`agent/decision.py:80`). The derivation table is exactly: `auto_restore` + not failed → `auto_restored`; `quarantine` + not failed → `quarantined`; `alert_only` → `alert_only` regardless of `action_failed`; `manual_review` → `pending`; `auto_restore` or `quarantine` with `action_failed` true → `pending`; absent or unrecognized `action` → `pending`. A failed automatic action MUST NOT produce a terminal status, because the file remains tampered on disk and the incident must return to the operator queue with approve and reject available — terminal statuses have no out-edges in `VALID_TRANSITIONS` and would leave a compromised file with no actor able to intervene. An absent or unrecognized `action` MUST NOT reject the event; it ingests as `pending` (forward tolerance, the same criterion D33 applied to `is_symlink`). (D35 / RN-129, RN-13, RN-06)

#### Scenario: auto_restore action produces a terminal auto_restored event
- **WHEN** the consumer ingests a payload with `action = "auto_restore"` and no `action_failed` key
- **THEN** the persisted event has `status = auto_restored`

#### Scenario: quarantine action produces a terminal quarantined event
- **WHEN** the consumer ingests a payload with `action = "quarantine"` and no `action_failed` key
- **THEN** the persisted event has `status = quarantined`

#### Scenario: alert_only action produces a terminal alert_only event regardless of action_failed
- **WHEN** the consumer ingests a payload with `action = "alert_only"`, with or without `action_failed` set to true
- **THEN** the persisted event has `status = alert_only`, because `alert_only` performs no physical action and has nothing to fail

#### Scenario: manual_review action leaves the event pending
- **WHEN** the consumer ingests a payload with `action = "manual_review"`
- **THEN** the persisted event has `status = pending` and is available for operator approve/reject

#### Scenario: Failed auto_restore returns the event to the operator queue as pending
- **WHEN** the consumer ingests a payload with `action = "auto_restore"` and `action_failed = true`
- **THEN** the persisted event has `status = pending`, NOT `auto_restored`, so that approve and reject remain available on a file that is still tampered

#### Scenario: Failed quarantine returns the event to the operator queue as pending
- **WHEN** the consumer ingests a payload with `action = "quarantine"` and `action_failed = true`
- **THEN** the persisted event has `status = pending`, NOT `quarantined`

#### Scenario: Payload from an older agent without an action key ingests as pending
- **WHEN** the consumer ingests a payload published by an agent version that emits no `action` key
- **THEN** the event ingests without error with `status = pending`, preserving the pre-change behavior

#### Scenario: Unrecognized action value ingests as pending instead of being rejected
- **WHEN** the consumer ingests a payload whose `action` is a value outside `auto_restore | quarantine | manual_review | alert_only`
- **THEN** the event ingests without error with `status = pending`, and is NOT rejected as an invalid schema

### Requirement: The backend is the sole authority over EventStatus and ignores any agent-supplied status

`ingest_event` MUST NOT read a `status` key from the stream payload. The existing `event_data.get("status", "pending")` read and its `ValueError` fallback SHALL be removed; the enum fallback is subsumed by `derive_event_status`. This is a security boundary, not a stylistic choice: `action` is a closed four-value vocabulary produced by the agent rule engine, whereas a free-form `status` field would let a compromised agent inject events already marked `approved` or `rejected`, bypassing the human decision cycle (RN-25 / RN-26) and its audit trail. The statuses `approved`, `rejected` and `superseded` SHALL NOT be derivable from an agent payload under any circumstance: they are backend-exclusive transitions originating from an operator decision or from automatic supersession (RN-77). (D35 / RN-129)

#### Scenario: A payload carrying an explicit status field has it ignored
- **WHEN** the consumer ingests a payload that contains a `status` key
- **THEN** the key is ignored entirely and the persisted status is the one derived from `action` and `action_failed`

#### Scenario: An agent payload cannot induce an approved event
- **WHEN** a payload attempts to set `status = "approved"`, whether directly or via an `action` value naming it
- **THEN** the persisted event is `pending` (or the status derived from a recognized `action`), never `approved`

#### Scenario: An agent payload cannot induce a rejected or superseded event
- **WHEN** a payload attempts to induce `rejected` or `superseded`
- **THEN** the persisted event is `pending` (or the status derived from a recognized `action`), because those statuses are reachable only through backend-originated transitions

### Requirement: Agent-originated terminal events record an automatic resolution

When `ingest_event` derives a terminal status (`auto_restored`, `quarantined`, `alert_only`), it SHALL persist `resolved_at = received_at` and leave `resolved_by = NULL`. `received_at` is the timestamp already passed into `ingest_event` by the consumer, which keeps the function deterministic and free of wall-clock reads. The combination `resolved_by IS NULL AND resolved_at IS NOT NULL` identifies an automatic agent resolution with no human operator, distinguishable from an approve/reject, which always sets `resolved_by`. Events that derive `pending` — including those whose automatic action failed — MUST NOT set `resolved_at` or `resolved_by`: they remain open. (D35 / RN-129)

#### Scenario: Terminal event records resolved_at and a null resolved_by
- **WHEN** an event is ingested with a derived status of `auto_restored`, `quarantined` or `alert_only`
- **THEN** the row has `resolved_at` equal to its `received_at` and `resolved_by` null

#### Scenario: Pending event leaves the resolution fields empty
- **WHEN** an event is ingested with a derived status of `pending`
- **THEN** `resolved_at` and `resolved_by` are both null

#### Scenario: Failed remediation stays unresolved
- **WHEN** an event with `action = "auto_restore"` and `action_failed = true` is ingested
- **THEN** it is `pending` with `resolved_at` null, because the file remains tampered and the incident is not resolved

### Requirement: ingest_event persists the action_failed flag

`ingest_event` SHALL persist `Event.action_failed` on every ingested event, with the value read from the payload (defaulting to `false`), independently of the derived status. Without this column a `pending` produced by a failed `auto_restore` would be indistinguishable from a `pending` produced by `manual_review`, and the fact that the system attempted remediation and could not complete it would be lost — it is not recorded anywhere else on the backend side. A `pending` with `action_failed = true` means the file is still tampered AND automatic remediation already failed, which carries operational priority over an ordinary `pending`. (D35 / RN-129)

#### Scenario: Failed action persists the flag alongside the pending status
- **WHEN** an event with `action_failed = true` is ingested
- **THEN** the row has `action_failed = true` and `status = pending`

#### Scenario: Successful action persists the flag as false
- **WHEN** an event with a successful action is ingested (no `action_failed` key in the payload)
- **THEN** the row has `action_failed = false`

## MODIFIED Requirements

### Requirement: Cadena superseded en ingesta con optimistic locking y re-consulta ante race

Cuando el consumer ingesta un evento válido para un path que ya tiene un evento con `status=pending`, el sistema SHALL: (1) marcar el evento pending anterior como `superseded` usando `UPDATE events SET status='superseded', version=version+1 WHERE id=? AND version=? AND status='pending'`; (2) si la UPDATE afecta 0 filas (carrera), re-consultar si todavía existe un pending activo para el mismo path (D25, RN-121): si hay pending → logear warning y abortar la creación del nuevo evento (skip legítimo); si NO hay pending → insertar el nuevo evento sin `parent_event_id`; (3) crear el nuevo evento con `parent_event_id` apuntando al ID del anterior. Si no existe evento `pending` para el path, el nuevo evento se crea sin `parent_event_id` (RN-21–23, RN-77). La supersesión SHALL evaluarse **antes** de derivar el estado del evento entrante y MUST NOT depender de él: un evento entrante terminal (`auto_restored`, `quarantined`, `alert_only`) supersede al `pending` activo del mismo path exactamente igual que un evento entrante `pending`. Recíprocamente, como la consulta de supersesión solo alcanza eventos `pending`, un evento terminal nunca es superseded a posteriori — es un hecho consumado, no un pendiente desplazable. (D35 / RN-129 refina la cláusula de estado; el resto es D25 / RN-121 sin cambios)

#### Scenario: Nuevo evento en path con pending existente genera cadena
- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=pending`
- **AND** llega un nuevo evento válido para `path='/etc/hosts'`
- **THEN** `event_A.status` pasa a `superseded` y `event_A.version` incrementa en 1
- **AND** se crea `event_B` con `parent_event_id = event_A.id`

#### Scenario: Nuevo evento en path sin pending — no genera cadena
- **WHEN** no existe evento `pending` para `path='/etc/passwd'`
- **AND** llega un nuevo evento válido para `path='/etc/passwd'`
- **THEN** se crea el evento con `parent_event_id = None`

#### Scenario: Carrera en superseded — pending resuelto concurrentemente — nuevo evento insertado
- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **AND** la re-consulta de pending para el path retorna None (el pending fue resuelto concurrentemente por un approve/reject)
- **THEN** el consumer inserta el nuevo evento sin `parent_event_id`
- **AND** ejecuta `XACK` sobre la entrada

#### Scenario: Carrera en superseded — pending todavía existe — consumer aborta
- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **AND** la re-consulta de pending para el path retorna un evento pending activo
- **THEN** el consumer no crea el nuevo evento (skip legítimo)
- **AND** ejecuta `XACK` sobre la entrada
- **AND** emite un log de warning

#### Scenario: Evento entrante terminal supersede al pending del mismo path
- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=pending`
- **AND** llega un evento válido para `path='/etc/hosts'` cuyo estado derivado es `auto_restored`
- **THEN** `event_A` pasa a `superseded` y se crea `event_B` con `status=auto_restored` y `parent_event_id = event_A.id`

#### Scenario: Un evento terminal ya persistido no es superseded por uno posterior
- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=auto_restored`
- **AND** llega un nuevo evento válido para `path='/etc/hosts'`
- **THEN** `event_A` conserva su estado terminal y el nuevo evento se crea sin `parent_event_id`, porque la consulta de supersesión solo alcanza eventos `pending`

### Requirement: Validación de transición de estado en service.py

El sistema SHALL definir en `backend/app/modules/events/service.py` la tabla de transiciones canónicas `VALID_TRANSITIONS: dict[EventStatus, set[EventStatus]]` alineada a RN-72: `pending → {approved, rejected, superseded}`; todos los demás estados son terminales (out-edges vacías). La función `validate_transition(from_status, to_status)` SHALL lanzar `InvalidTransitionError` si la transición no está en la tabla. `InvalidTransitionError` SHALL ser una excepción de dominio definida en el mismo módulo. El consumer SHALL capturar `InvalidTransitionError`, ejecutar `XACK`, loguear el intento y NO persistir el evento resultante. El HTTP handler de C13 (approve/reject) también SHALL capturarla y retornar `409 Conflict`. La derivación del estado de un evento entrante (D35/RN-129) es una asignación en la **creación** de la fila y MUST NOT pasar por `validate_transition`: la tabla de transiciones y la máquina de estados de RN-72 quedan inalteradas por esa derivación. (RN-72; cláusula de creación por D35 / RN-129)

#### Scenario: Transición válida pending → superseded no lanza error
- **WHEN** se llama `validate_transition(EventStatus.pending, EventStatus.superseded)`
- **THEN** la llamada retorna sin lanzar excepción

#### Scenario: Transición inválida approved → pending lanza InvalidTransitionError
- **WHEN** se llama `validate_transition(EventStatus.approved, EventStatus.pending)`
- **THEN** se lanza `InvalidTransitionError`

#### Scenario: Transición inválida pending → alert_only lanza InvalidTransitionError
- **WHEN** se llama `validate_transition(EventStatus.pending, EventStatus.alert_only)`
- **THEN** se lanza `InvalidTransitionError`

#### Scenario: Crear un evento con estado terminal derivado no invoca validate_transition
- **WHEN** `ingest_event` deriva `alert_only` para un evento nuevo
- **THEN** la fila se crea directamente con `status=alert_only` sin consultar `VALID_TRANSITIONS`, porque no hay estado de origen del cual transicionar
