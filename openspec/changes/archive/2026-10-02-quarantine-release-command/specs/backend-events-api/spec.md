## ADDED Requirements

### Requirement: quarantine_state refleja la liberación confirmada

La derivación de `quarantine_state` SHALL devolver `discarded` cuando el evento tiene un
`release_quarantine` con `ack_status = acked` y `mode = discard` en su payload persistido, y
`released` cuando lo tiene con `mode ∈ {restore_original, restore_baseline}`. Estas ramas SHALL
evaluarse antes que `quarantined`. Un `release_quarantine` `pending`, `failed` o `timeout` MUST NOT
cambiar `quarantine_state`. La derivación SHALL seguir siendo de lectura, sin columna en `events`, y
filtrable desde `GET /events`; `GET /events/{id}` y `GET /events` SHALL exponerla. (D83/RN-177,
D82/RN-176)

#### Scenario: Liberación confirmada
- **WHEN** un evento `quarantined` tiene un `release_quarantine` `acked` con `mode = restore_baseline`
- **THEN** `GET /events/{id}` devuelve `quarantine_state = "released"` y `status = "quarantined"`

#### Scenario: Descarte confirmado
- **WHEN** el `release_quarantine` `acked` tiene `mode = discard`
- **THEN** `quarantine_state = "discarded"`

#### Scenario: Liberación pendiente o fallida
- **WHEN** el único `release_quarantine` del evento está `pending` o `failed`
- **THEN** `quarantine_state = "quarantined"`

#### Scenario: Filtro por estado de cuarentena
- **WHEN** se consulta `GET /events?quarantine_state=released`
- **THEN** la lista contiene sólo eventos con una liberación confirmada no descartada
