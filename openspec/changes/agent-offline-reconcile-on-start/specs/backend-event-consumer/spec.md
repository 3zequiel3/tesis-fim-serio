## ADDED Requirements

### Requirement: La ingesta persiste detected_offline con tolerancia hacia adelante

`ingest_event` SHALL leer `detected_offline` del payload y persistirlo en `Event.detected_offline`: un booleano se guarda tal cual; una clave ausente se guarda como `NULL`; cualquier otro valor se guarda como `NULL` y se registra `consumer.detected_offline_invalid`, sin rechazar el evento. El campo MUST NOT alterar la validación de `schema_version`, la verificación HMAC, la derivación del status, la severidad ni la supersesión. (D80 / RN-174)

#### Scenario: Evento offline
- **WHEN** se ingiere un payload con `detected_offline: true`
- **THEN** la fila persistida tiene `detected_offline = true` y el mismo status que tendría el evento sin el campo

#### Scenario: Evento en línea
- **WHEN** se ingiere un payload con `detected_offline: false`
- **THEN** la fila persistida tiene `detected_offline = false`

#### Scenario: Agente anterior sin el campo
- **WHEN** se ingiere un payload sin la clave `detected_offline`
- **THEN** la fila persistida tiene `detected_offline IS NULL`

#### Scenario: Valor no booleano
- **WHEN** se ingiere un payload con `detected_offline: "yes"`
- **THEN** el evento se persiste con `detected_offline IS NULL` y se registra `consumer.detected_offline_invalid`
