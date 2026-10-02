## ADDED Requirements

### Requirement: Los hallazgos offline se emiten por el camino normal del detector

El detector SHALL exponer `emit_offline(finding)`, que procesa un hallazgo de la reconciliación al arrancar a través del mismo `_process_event` que procesa un evento de fanotify, con la clase de evento forzada según el hallazgo (`file_deleted`, `file_modified` o `file_created`). Cada hallazgo MUST recorrer, en este orden, la captura del candidato de aprobación, `DecisionEngine.evaluate_and_act`, la actualización del baseline que corresponda a la rama y a la acción resultante, `publisher.publish` y `commit_fn`. El reconcile MUST NOT publicar ningún payload que no provenga de `evaluate_and_act`, y MUST NOT actualizar el baseline por fuera de ese camino. Las guardas existentes de cada rama (descarte por hash igual, symlink como objeto, decidir antes de mutar el baseline, hash activo fijo ante una modificación no aprobada) SHALL aplicarse sin excepción. (D80 / RN-174, D14, D33 / RN-127)

#### Scenario: Modificación offline
- **WHEN** el reconcile entrega un hallazgo `file_modified` para un path cuyo disco difiere del baseline
- **THEN** se publica un evento `file_modified` con `detected_offline: true`, producido por `evaluate_and_act`
- **AND** el hash activo del baseline no cambia y el contenido detectado queda como snapshot

#### Scenario: Eliminación offline
- **WHEN** el reconcile entrega un hallazgo `file_deleted`
- **THEN** se publica un evento `file_deleted` con `detected_offline: true` y la entrada del baseline queda `absent`, salvo que la acción resultante sea una restauración exitosa

#### Scenario: Recreación idéntica tras una eliminación offline reportada
- **WHEN** una eliminación offline ya fue reportada por el reconcile y, con el detector en marcha, el archivo se recrea con el mismo contenido que tenía
- **THEN** el detector emite `file_created` para ese path en lugar de descartarlo como «sin cambio real»

#### Scenario: Creación offline
- **WHEN** el reconcile entrega un hallazgo `file_created`
- **THEN** se publica un evento `file_created` con `detected_offline: true` y el path queda con entrada `present`, salvo que la acción resultante sea una cuarentena exitosa

#### Scenario: Acción automática sobre un hallazgo offline
- **WHEN** una regla de `auto_restore` cubre el path de un hallazgo `file_modified`
- **THEN** el archivo se restaura y el evento publicado refleja la acción, igual que para un evento en línea

#### Scenario: El reconcile nunca publica por separado
- **WHEN** se procesan hallazgos offline con un `DecisionEngine` instrumentado
- **THEN** cada llamada a `publisher.publish` recibe exactamente el payload devuelto por `evaluate_and_act` para ese hallazgo, y `commit_fn` se invoca después de cada publicación

### Requirement: Campo detected_offline y contexto de proceso de un evento offline

`DetectedChange` SHALL incluir `detected_offline: bool`, serializado en todo payload de evento: `true` para los eventos emitidos por la reconciliación al arrancar y `false` para los producidos por fanotify. En un evento offline, `process_pid`, `process_uid` y `process_exe` MUST ser nulos, porque el proceso causante no existe por definición; `0` MUST NOT usarse como sustituto (D49 / RN-143). `detected_at` MUST ser el instante UTC de la emisión; el `mtime` del archivo MUST NOT usarse. El `schema_version` del payload MUST NOT cambiar. (D80 / RN-174)

#### Scenario: Evento en línea
- **WHEN** fanotify entrega una modificación con el detector en marcha
- **THEN** el payload publicado lleva `detected_offline: false`

#### Scenario: Evento offline sin atribución
- **WHEN** el reconcile emite cualquier hallazgo
- **THEN** el payload lleva `detected_offline: true` y `process_pid`, `process_uid` y `process_exe` en `null`

#### Scenario: schema_version sin cambios
- **WHEN** se publica un evento offline
- **THEN** su `schema_version` es el mismo que el de un evento en línea
