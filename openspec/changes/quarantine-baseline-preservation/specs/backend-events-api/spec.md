## ADDED Requirements

### Requirement: quarantine_state derivado en lectura y filtrable en SQL

`EventOut` (y por herencia `EventDetailOut`) SHALL exponer `quarantine_state` con valores `none`, `quarantined`, `released` o `discarded` (minúsculas snake_case, RN-71), derivado en cada lectura y sin columna en `events` (D82/RN-176). La derivación SHALL ser:

- **base en cuarentena**: `status = quarantined`, o `status = rejected` y existe un `PublishedCommand` con `command_type = "quarantine_file"`, `event_id` igual al `id` del evento y `ack_status = "acked"`;
- sin base en cuarentena → `none`;
- con base en cuarentena y un `PublishedCommand` `acked` de `command_type = "release_quarantine"` para el evento cuyo payload firmado lleva `mode = "discard"` → `discarded`;
- con base en cuarentena y un `release_quarantine` `acked` con `mode` `restore_original` o `restore_baseline` → `released`;
- en otro caso → `quarantined`.

El comando `release_quarantine` lo crea la Change 65 (D83/RN-177); este requisito sólo lo lee. Un `quarantine_file` en `pending`, `failed` o `timeout`, o el no-op de baseline `absent` (RN-74), dejan `none`. La derivación MUST NOT modificar `Event` ni su máquina de estados (RN-72).

`GET /events` SHALL aceptar el parámetro repetible `quarantine_state` (mismo patrón que `status` y `severity`), validado contra el enum (valor desconocido → 422) y resuelto **en SQL** con la misma expresión que produce el campo, de modo que `total` y la paginación reflejen el filtro. Varios valores se combinan con OR; el filtro se combina con AND con los demás.

#### Scenario: Cuarentena automática

- **WHEN** se lista un evento con `status = quarantined`
- **THEN** su `quarantine_state` es `quarantined`

#### Scenario: Rechazo con cuarentena confirmado por el agente

- **WHEN** un evento `rejected` tiene un `quarantine_file` con `ack_status = acked`
- **THEN** su `quarantine_state` es `quarantined` y su `status` sigue siendo `rejected`

#### Scenario: Rechazo con cuarentena todavía no confirmado o fallido

- **WHEN** un evento `rejected` tiene su `quarantine_file` en `pending`, `failed` o `timeout`
- **THEN** su `quarantine_state` es `none`

#### Scenario: Rechazo con restauración

- **WHEN** un evento `rejected` tiene sólo un `restore_file` `acked`
- **THEN** su `quarantine_state` es `none`

#### Scenario: Liberación y descarte

- **WHEN** un evento con base en cuarentena tiene un `release_quarantine` `acked` con `mode = "discard"`
- **THEN** su `quarantine_state` es `discarded`
- **WHEN** el `release_quarantine` `acked` tiene `mode = "restore_original"` o `"restore_baseline"`
- **THEN** su `quarantine_state` es `released`

#### Scenario: Filtro por quarantine_state en SQL

- **WHEN** `GET /events?quarantine_state=quarantined` sobre una base con un evento `quarantined`, un `rejected` con `quarantine_file` `acked`, un `rejected` con `restore_file` `acked` y un `pending`
- **THEN** `total` es 2 y los ítems son exactamente los dos primeros

#### Scenario: Valor de filtro desconocido

- **WHEN** `GET /events?quarantine_state=foo`
- **THEN** la respuesta es `422`
