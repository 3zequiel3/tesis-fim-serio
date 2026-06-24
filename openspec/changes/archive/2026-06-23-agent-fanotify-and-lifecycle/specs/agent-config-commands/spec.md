## ADDED Requirements

### Requirement: restore_file cae a snapshots cuando el contenido activo es nulo

Al procesar el comando `restore_file`, si la entrada de baseline tiene `content_b64` nulo (típicamente porque el archivo está en estado `absent`), el handler SHALL buscar el snapshot más reciente cuyo `content_b64` no sea nulo, descomprimirlo si `gzip=True`, y usar ese contenido para restaurar el archivo. El handler MUST verificar el SHA-256 del contenido restaurado contra el hash del snapshot usado, journalizar la acción transaccionalmente (pending/completed/failed) y publicar el `event_ack`. Si no existe ningún snapshot utilizable, el handler MUST fallar con el error `no_restorable_content` y journalizar el fallo (RN-30–33, F3).

#### Scenario: Restauración por comando desde snapshot cuando el contenido activo es nulo

- **WHEN** llega un comando `restore_file` para un path cuya entrada de baseline tiene `content_b64=None` pero existe un snapshot con contenido
- **THEN** el handler restaura el archivo desde el snapshot más reciente con contenido, verifica el hash y publica `event_ack`

#### Scenario: Snapshot comprimido se descomprime en el handler

- **WHEN** el snapshot seleccionado para el `restore_file` tiene `gzip=True`
- **THEN** el handler descomprime el contenido antes de escribirlo y verificar el hash

#### Scenario: Comando sin contenido restaurable falla con error claro

- **WHEN** llega un comando `restore_file` y ni el contenido activo ni ningún snapshot tienen contenido
- **THEN** el handler journaliza el fallo con el error `no_restorable_content` y no escribe el archivo

#### Scenario: Contenido activo presente conserva el comportamiento previo

- **WHEN** llega un comando `restore_file` y la entrada de baseline tiene `content_b64` no nulo
- **THEN** el handler restaura desde el contenido activo sin consultar snapshots
