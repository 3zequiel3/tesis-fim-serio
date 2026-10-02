## MODIFIED Requirements

### Requirement: Baseline present and absent states

Una entrada de baseline SHALL tener `status` con valor `present`, `absent` o `quarantined` (minúsculas, snake_case). Cuando `status` es `present`, `hash` MUST ser el SHA-256 hex del contenido. Cuando `status` es `absent`, `hash` MUST ser `null` y la entrada MUST NOT contener contenido de archivo. `absent` significa «no debe existir» y la cuarentena MUST NOT producirlo. Cuando `status` es `quarantined`, la entrada SHALL registrar la ausencia física causada por una cuarentena del propio agente y SHALL conservar sin cambios `hash`, `size`, `mode`, `uid`, `gid`, `mtime`, `content_b64`, `oversize`, `symlink_target`, `approved_event_id` y `snapshots` de la entrada previa, junto con `quarantine_action_id` igual a la identidad de acción del artefacto (D82/RN-176). Las entradas `present` y `absent` SHALL tener `quarantine_action_id` nulo; una entrada sin la clave SHALL leerse como nula.

#### Scenario: Entrada present con hash

- **WHEN** el motor registra un archivo existente
- **THEN** la entrada tiene `status: present` y `hash` con el SHA-256 del contenido

#### Scenario: Marcar un path como absent

- **WHEN** el motor marca un path como ausente (un archivo que no debe existir)
- **THEN** la entrada tiene `status: absent`, `hash: null`, y no almacena contenido cifrado del archivo

#### Scenario: Marcar un path como quarantined conserva la versión aprobada

- **WHEN** el motor marca como `quarantined` un path cuya entrada era `present` con contenido y dos snapshots
- **THEN** la entrada tiene `status: quarantined`, el mismo `hash`, `content_b64`, `mode`, `uid`, `gid` y los mismos dos snapshots que antes, y `quarantine_action_id` igual al `event_id` de la acción

#### Scenario: Entrada previa a esta versión sin quarantine_action_id

- **WHEN** el motor lee una entrada cifrada escrita por una versión anterior, sin la clave `quarantine_action_id`
- **THEN** la lectura no falla y el campo vale `null`

## ADDED Requirements

### Requirement: La cuarentena preserva la última versión aprobada en el baseline local

`BaselineEngine.mark_quarantined(path, action_id)` SHALL ser la única operación de baseline que sigue a una cuarentena exitosa, en cualquiera de sus caminos (automático, por rechazo del operador o por rehidratación del journal); `mark_absent` MUST NOT invocarse en ese camino (D82/RN-176). Si existe una entrada previa, `mark_quarantined` SHALL copiar todos sus campos y cambiar sólo `status`, `quarantine_action_id` y `captured_at`; si no existe, SHALL escribir una entrada `quarantined` con `hash`, contenido y metadatos nulos, que conserva la semántica de que el estado sano de esa ruta es la ausencia. La escritura SHALL ser atómica y cifrada con el mismo esquema que el resto del motor. Una entrada `quarantined` con contenido SHALL seguir siendo fuente válida de `select_restorable_content`, y `add_snapshot` SHALL operar sobre ella igual que sobre una entrada `present`.

#### Scenario: La versión aprobada sigue siendo restaurable tras la cuarentena

- **WHEN** un path con entrada `present` y contenido aprobado se pone en cuarentena
- **THEN** `select_restorable_content` sobre la entrada resultante no es `None` y devuelve exactamente los bytes aprobados y su hash

#### Scenario: Cuarentena sin entrada previa

- **WHEN** se pone en cuarentena un path sin entrada de baseline
- **THEN** queda una entrada `quarantined` con `hash: null`, sin contenido, y `select_restorable_content` devuelve `None`

#### Scenario: Snapshot sobre una entrada quarantined

- **WHEN** se invoca `add_snapshot` sobre una entrada `quarantined` con `hash` no nulo
- **THEN** el comportamiento es el mismo que sobre una entrada `present` (deduplicación y FIFO incluidos)

### Requirement: Salidas del estado quarantined de una entrada de baseline

Una entrada `quarantined` SHALL pasar a `present` únicamente cuando (a) una restauración —automática o del operador— termina con verificación desde disco exitosa (D81/RN-175); (b) una aprobación (`baseline_update`) adopta un candidato; o (c) el detector observa en la ruta un archivo recreado cuyo hash es **exactamente** el hash aprobado de la entrada, con el mismo tipo de objeto (archivo regular o symlink): es el estado sano, equivalente a una restauración verificada, y la transición evita suprimir en silencio un borrado posterior (ratificación de RN-176). En los casos (a) y (c) la transición SHALL conservar los campos preservados de la entrada (incluidos `mode`, `uid` y `gid` aprobados) y limpiar `quarantine_action_id`, sin re-hashear ni adoptar metadatos del disco. En el caso (b) rige `update_from_command` sin cambios. Un archivo nuevo con un hash distinto del aprobado MUST NOT sobrescribir la entrada: se reporta como evento y su contenido sólo se adopta por aprobación (D82/RN-176). Una restauración fallida MUST NOT cambiar el estado. Una entrada `quarantined` sin hash aprobado (cuarentena sin entrada previa) no tiene caso (c).

#### Scenario: Restauración verificada desde quarantined

- **WHEN** una restauración de un path con entrada `quarantined` escribe el contenido aprobado y la relectura desde disco coincide con el hash
- **THEN** la entrada queda `present`, con el mismo `hash`, `content_b64`, metadatos y snapshots, y `quarantine_action_id: null`

#### Scenario: Aprobación desde quarantined

- **WHEN** llega un `baseline_update` válido para un path con entrada `quarantined`
- **THEN** la entrada queda `present` (o `absent`, según el comando) con el contenido del candidato aprobado, conserva los snapshots previos y `quarantine_action_id` es `null`

#### Scenario: Recreación con exactamente el hash aprobado

- **WHEN** en una ruta con entrada `quarantined` y hash aprobado `H` aparece un archivo regular cuyo SHA-256 es `H`
- **THEN** la entrada queda `present` con el mismo `hash`, `content_b64`, metadatos aprobados y snapshots, y `quarantine_action_id: null`

#### Scenario: Restauración fallida no cambia el estado

- **WHEN** una restauración de un path con entrada `quarantined` falla (por ejemplo, `hash_mismatch_after_restore`)
- **THEN** la entrada sigue `quarantined` y conserva el contenido aprobado

### Requirement: La reconciliación del baseline no reporta borrados sobre entradas quarantined

Todo componente que compare el baseline contra el filesystem para emitir eventos —en particular la reconciliación al arrancar de D80/RN-174— MUST NOT emitir `file_deleted` ni `file_absent` para una entrada `quarantined` cuyo archivo no existe: esa ausencia es la consecuencia registrada de la cuarentena, no un cambio (D82/RN-176).

#### Scenario: Reconciliación sobre una ruta en cuarentena

- **WHEN** la reconciliación encuentra una entrada `quarantined` y el archivo no existe en disco
- **THEN** no se emite ningún evento para esa ruta y la entrada no cambia
