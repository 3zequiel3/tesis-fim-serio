## ADDED Requirements

### Requirement: El detalle del evento ofrece liberar una cuarentena vigente

`EventDetail` SHALL mostrar el botón «Liberar cuarentena» sólo cuando
`event.quarantine_state === 'quarantined'`, y SHALL deshabilitarlo mientras
`event.ack_status === 'pending'`. El botón SHALL abrir `ReleaseQuarantineModal`, que exige elegir uno
de los tres modos (`restore_original`, `restore_baseline`, `discard`), explica la consecuencia de
cada uno —`restore_original` advierte que **aprueba** el contenido cuarentenado— y exige un motivo no
vacío antes de habilitar la confirmación. La confirmación SHALL llamar a
`POST /events/{id}/quarantine/release`; un `202` SHALL cerrar el modal, mostrar un aviso de
liberación solicitada e invalidar las queries del evento y de la lista. Un `409` SHALL mostrar un
mensaje según `code` (`quarantine_not_releasable`, `release_in_progress`) e invalidar el evento.
(D83/RN-177)

#### Scenario: Botón visible sólo con cuarentena vigente
- **WHEN** el detalle muestra un evento con `quarantine_state = "quarantined"`
- **THEN** el botón «Liberar cuarentena» está presente
- **AND** para eventos con `quarantine_state` `none`, `released` o `discarded` no lo está

#### Scenario: Evento rechazado con cuarentena
- **WHEN** el evento tiene `status = "rejected"` y `quarantine_state = "quarantined"`
- **THEN** el botón «Liberar cuarentena» está presente

#### Scenario: Motivo obligatorio
- **WHEN** el operador elige un modo y deja el motivo vacío
- **THEN** el botón de confirmación está deshabilitado

#### Scenario: Confirmación envía modo y motivo
- **WHEN** el operador elige `discard`, escribe un motivo y confirma
- **THEN** se envía `POST /events/{id}/quarantine/release` con `{"mode": "discard", "reason": "<motivo>"}`

#### Scenario: Liberación ya en curso
- **WHEN** la API responde `409` con `code = "release_in_progress"`
- **THEN** se muestra un mensaje que indica que ya hay una liberación en curso y se refresca el evento
