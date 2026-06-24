## ADDED Requirements

### Requirement: auto_restore cae a snapshots cuando el contenido activo es nulo

Al ejecutar `auto_restore`, si la entrada de baseline tiene `content_b64` nulo (típicamente porque el archivo está en estado `absent`), el motor de decisión SHALL buscar el snapshot más reciente cuyo `content_b64` no sea nulo, descomprimirlo si `gzip=True`, y usar ese contenido para restaurar el archivo. El motor MUST verificar el SHA-256 del contenido restaurado contra el hash del snapshot usado. Si no existe ningún snapshot utilizable, el motor MUST fallar con el error `no_restorable_content` (RN-30–33, F3).

#### Scenario: Restauración desde snapshot cuando el contenido activo es nulo

- **WHEN** se gatilla `auto_restore` sobre un path cuya entrada de baseline tiene `content_b64=None` pero existe un snapshot con contenido
- **THEN** el motor restaura el archivo desde el snapshot más reciente con contenido y verifica el hash

#### Scenario: Snapshot comprimido se descomprime antes de restaurar

- **WHEN** el snapshot seleccionado tiene `gzip=True`
- **THEN** el motor descomprime el contenido antes de escribirlo y verificar el hash

#### Scenario: Sin contenido restaurable falla con error claro

- **WHEN** se gatilla `auto_restore` y ni el contenido activo ni ningún snapshot tienen contenido
- **THEN** el motor falla la acción con el error `no_restorable_content` y journaliza el fallo

#### Scenario: Contenido activo presente conserva el comportamiento previo

- **WHEN** se gatilla `auto_restore` y la entrada de baseline tiene `content_b64` no nulo
- **THEN** el motor restaura desde el contenido activo sin consultar snapshots
