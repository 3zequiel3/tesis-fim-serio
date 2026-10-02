## ADDED Requirements

### Requirement: El eco de la cuarentena propia no genera eventos

Un evento clasificado `file_deleted` (por `FAN_DELETE` o `FAN_MOVED_FROM`), o un `file_absent` de la rama genérica, sobre una ruta cuya entrada de baseline es `quarantined` SHALL descartarse **antes de asignar `event_id`**, registrando la traza `decision_suppressed` con razón `quarantined_by_agent` (D82/RN-176). El descarte MUST NOT evaluar reglas, MUST NOT escribir journal, MUST NOT preparar candidato de aprobación, MUST NOT publicar y MUST NOT mutar la entrada de baseline. El mecanismo SHALL basarse en el estado de la entrada, nunca en el PID del proceso causante (criterio de la Change 43). Riesgo aceptado por RN-176: si alguien crea en la ruta en cuarentena un archivo con contenido **distinto** del aprobado y luego lo borra, la creación se reporta y el borrado no. Un archivo recreado con exactamente el hash aprobado devuelve la entrada a `present` (requisito siguiente), de modo que su borrado posterior sí se reporta.

#### Scenario: Eco de la cuarentena automática

- **WHEN** una regla `quarantine` aísla un archivo modificado y luego llega el `FAN_DELETE` sobre la ruta
- **THEN** se publicó exactamente un evento (el de la cuarentena, con `action: "quarantine"` y sin `action_failed`)
- **AND** el eco no publica ningún evento, no escribe journal nuevo y no reintenta la cuarentena
- **AND** la entrada sigue `quarantined` con el contenido aprobado y se registró `decision_suppressed` con razón `quarantined_by_agent`

#### Scenario: Una ausencia genuina sigue reportándose

- **WHEN** llega un `FAN_DELETE` sobre una ruta con entrada `present`
- **THEN** el comportamiento no cambia: se publica `file_deleted` y la entrada queda según la regla aplicada

#### Scenario: Crear y borrar en una ruta en cuarentena

- **WHEN** en una ruta con entrada `quarantined` se crea un archivo con contenido distinto del aprobado y luego se lo borra
- **THEN** la creación produce un evento y el borrado se descarta con `quarantined_by_agent`

### Requirement: Las ramas del detector mantienen la entrada quarantined

Tras una acción `quarantine` exitosa en las ramas `file_created` y `file_modified`, el detector MUST NOT invocar `mark_absent`: el marcado `quarantined` ya ocurrió dentro de la acción, antes del primer `await` (D82/RN-176). En la rama `file_created`, si la entrada de la ruta es `quarantined`, el detector MUST NOT escribir la entrada con el contenido nuevo (`write_entry`/`write_symlink_entry`): el archivo se reporta y su contenido sólo se adopta por aprobación. En la rama genérica, un `auto_restore` exitoso sobre una ruta cuya entrada era `quarantined` SHALL devolver la entrada a `present` conservando los campos preservados. Cuando el descarte por igualdad de hash (rama `file_created` o rama genérica) se produce sobre una entrada `quarantined` —el archivo recreado tiene exactamente el hash aprobado y, en la rama `file_created`, el mismo tipo de objeto—, el detector SHALL devolver la entrada a `present` conservando los campos preservados, y el evento se sigue descartando sin publicar (ratificación de RN-176). Cualquier otro resultado MUST dejarla `quarantined`.

#### Scenario: Archivo nuevo en una ruta en cuarentena

- **WHEN** se crea un archivo con contenido distinto en una ruta cuya entrada es `quarantined`
- **THEN** se publica un evento por la creación
- **AND** la entrada sigue `quarantined` con el `hash` y el `content_b64` aprobados

#### Scenario: Una regla auto_restore recupera una ruta en cuarentena

- **WHEN** la regla de una ruta en cuarentena cambia a `auto_restore` y el archivo reaparece con contenido alterado
- **THEN** se publica exactamente un evento con `action: "auto_restore"` sin falla, el archivo en disco es el contenido aprobado y la entrada queda `present`, dentro del techo de iteraciones del banco de pruebas de retroalimentación

#### Scenario: Recreación idéntica y borrado posterior

- **WHEN** en una ruta con entrada `quarantined` se recrea un archivo con exactamente el contenido aprobado y luego ese archivo se borra
- **THEN** la recreación no publica evento y deja la entrada `present`
- **AND** el borrado posterior **sí** publica un `file_deleted` (no se suprime con `quarantined_by_agent`)

#### Scenario: Cuarentena en la rama file_created

- **WHEN** una regla `quarantine` aísla un archivo recién creado sobre una ruta con entrada previa `present`
- **THEN** la entrada queda `quarantined` con el contenido aprobado previo, no con el contenido del archivo aislado
