## ADDED Requirements

### Requirement: Badge y filtro de quarantine_state en la lista y el detalle de eventos

El tipo `EventListItem` SHALL incluir `quarantine_state: 'none' | 'quarantined' | 'released' | 'discarded'` (D82/RN-176). `EventsTable` y `EventDetail` SHALL mostrar un badge con el valor en minúsculas (RN-71) cuando es distinto de `none`, visualmente distinto del badge de `status` —porque no es un estado del evento— y SHALL omitirlo cuando vale `none` o cuando el campo falta (tolerancia hacia adelante). La página de eventos SHALL ofrecer un filtro multi-select `quarantine_state`, sincronizado en la URL con el mismo parseo y serialización que `status` y `severity` (`frontend/src/utils/eventFilters.ts`), y `getEvents` SHALL enviarlo como parámetro repetible. La UI MUST NOT presentar el rechazo con cuarentena como un estado `quarantined` del evento: el badge de `status` sigue mostrando `rejected`.

#### Scenario: Evento rechazado con cuarentena

- **WHEN** la tabla recibe un evento con `status: "rejected"` y `quarantine_state: "quarantined"`
- **THEN** la fila muestra el badge de estado `rejected` y, aparte, el badge `quarantined` de cuarentena

#### Scenario: Sin cuarentena

- **WHEN** un evento tiene `quarantine_state: "none"` o no trae el campo
- **THEN** no se muestra badge de cuarentena

#### Scenario: Filtro sincronizado con la URL

- **WHEN** el operador selecciona `quarantined` y `released` en el filtro de cuarentena
- **THEN** la URL contiene `quarantine_state=quarantined&quarantine_state=released`, la petición a `/events` lleva el parámetro repetido, y recargar la página restaura la selección
