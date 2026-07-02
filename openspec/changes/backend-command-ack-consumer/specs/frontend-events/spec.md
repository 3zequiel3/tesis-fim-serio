## ADDED Requirements

### Requirement: Indicador secundario de estado de ejecución del comando por evento

El frontend SHALL exponer, en la vista de eventos (tabla y/o detalle), un indicador secundario que refleje el estado de ejecución del comando asociado al evento (`pending | acked | failed | timeout`), derivado del tracking de `PublishedCommand` expuesto por el backend. Este indicador SHALL ser visualmente distinto del `status` del evento y NO SHALL introducir un nuevo valor en la máquina de estados del evento: `approved` y `rejected` siguen siendo terminales (RN-72). Cuando un evento no tiene comando asociado con estado de ejecución, el indicador SHALL omitirse (no mostrar un estado vacío o engañoso). El tipo de dato correspondiente SHALL declararse en `frontend/src/api/events.ts`.

#### Scenario: Comando confirmado muestra indicador acked
- **WHEN** el evento tiene un comando asociado con `ack_status = acked`
- **THEN** la vista muestra un indicador secundario "acked" distinguible del `status` del evento

#### Scenario: Comando fallido o vencido se distingue
- **WHEN** el comando asociado está en `failed` o `timeout`
- **THEN** el indicador secundario refleja ese estado, sin cambiar el `status` terminal del evento (`approved`/`rejected`)

#### Scenario: Evento sin comando confirmable no muestra indicador
- **WHEN** el evento no tiene un comando asociado con estado de ejecución
- **THEN** el indicador secundario se omite

#### Scenario: El estado del evento no gana nuevos valores
- **WHEN** se renderiza el filtro/columna de `status` del evento
- **THEN** los valores posibles siguen siendo los de RN-72 (`pending | approved | rejected | superseded | ...`), sin agregar `acked`/`timeout`
