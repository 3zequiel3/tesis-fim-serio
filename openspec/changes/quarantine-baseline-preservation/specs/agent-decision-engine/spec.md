## MODIFIED Requirements

### Requirement: Acción quarantine — aislamiento cifrado local

Cuando la acción determinada es `quarantine`, el `DecisionEngine` SHALL delegar en `quarantine_and_record` (`agent/quarantine.py`), que usa el almacén único de cuarentena para cifrar contenido y metadatos con AES-256-GCM antes de retirar la entrada de origen y, recién después de una cuarentena exitosa, marca la entrada de baseline como `quarantined` conservando la versión aprobada (D82/RN-176). La clave MUST derivarse de `master_secret` con HKDF-SHA256 e `info="quarantine-v1"`, separada de la clave del baseline. El nombre del artefacto MUST ser opaco y determinístico por identidad de acción y ruta, y la identidad de acción MUST ser el `event_id` del agente. Si el archivo no existe, la acción MUST fallar con `error: "file_not_found"`. El evento MUST conservar `action: "quarantine"` y el `quarantine_path` opaco resultante. El paso terminal del journal (`completed`/`failed`) MUST quedar en el `commit_fn` que el detector invoca después de publicar, de modo que un crash entre la acción y la publicación deje la entrada `pending` para la rehidratación.

#### Scenario: Quarantine exitosa

- **WHEN** el archivo `/opt/app/malware.sh` debe ser puesto en cuarentena
- **THEN** existe un artefacto autenticado `0400` bajo `/var/lib/fim-agent/quarantine/`, el nombre original no aparece en el nombre del artefacto, el origen se retira solamente después de verificar el artefacto, la entrada de baseline queda `quarantined` con el contenido aprobado, el evento incluye `quarantine_path`, y el journal queda `completed` después de la publicación

#### Scenario: Reintento idempotente

- **WHEN** el artefacto autenticado de la misma acción ya existe por una interrupción previa
- **THEN** no se crea un duplicado y sólo se retira el origen si su identidad todavía coincide con la capturada

#### Scenario: Enlaces

- **WHEN** el origen es un enlace simbólico
- **THEN** se cifra el target textual sin seguirlo y no se conserva un enlace vivo en cuarentena
- **WHEN** el archivo regular tiene más de un hardlink
- **THEN** la acción falla con `hardlink_not_isolatable` y no afirma aislamiento del inode

#### Scenario: Archivo ya eliminado — falla graceful

- **WHEN** el archivo `/opt/app/gone.sh` no existe al momento de ejecutar quarantine
- **THEN** journal queda `failed` con `error: "file_not_found"`, evento publicado con `action_failed: true`, y la entrada de baseline no cambia

#### Scenario: La publicación falla después de la cuarentena

- **WHEN** la cuarentena y el marcado `quarantined` tienen éxito pero la publicación del evento falla
- **THEN** el journal sigue `pending` y la rehidratación del próximo arranque reintenta y publica el evento

### Requirement: Rehidratación de journal al arrancar

Al iniciar, el agente SHALL escanear `/var/lib/fim-agent/journal/` y procesar todas las entradas con `state: "pending"` (RN-83). Para cada entrada pendiente con acción `auto_restore` o `quarantine`: MUST reintentarse la acción. Una acción `quarantine` reintentada MUST pasar por `quarantine_and_record`, con la clave de la entrada de journal como identidad de acción, de modo que la entrada de baseline quede `quarantined` aunque el agente haya caído entre el retiro del origen y el marcado (D82/RN-176). Para cada entrada pendiente con acción `manual_review` o `alert_only`: MUST marcarse `state: "failed"` con `error: "rehydrated_without_action"` y re-publicarse como evento `alert_only` para que el backend lo registre. La rehidratación MUST completarse antes de que el detector comience a aceptar nuevos eventos.

#### Scenario: Journal pending auto_restore — reintentado al arrancar

- **WHEN** el agente arranca y encuentra `journal/evt-001.json` con `action: "auto_restore"` y `state: "pending"`
- **THEN** intenta restaurar el archivo, actualiza el journal a `completed` o `failed`, y publica el resultado

#### Scenario: Journal pending manual_review — descartado con aviso

- **WHEN** el agente arranca y encuentra `journal/evt-002.json` con `action: "manual_review"` y `state: "pending"`
- **THEN** marca el journal `failed` con `error: "rehydrated_without_action"` y publica un evento `alert_only` al stream

#### Scenario: Sin entradas pending — arranque limpio

- **WHEN** el agente arranca y no hay entradas `pending` en el journal
- **THEN** la fase de rehidratación termina sin publicar eventos adicionales

#### Scenario: Ventana de crash de la cuarentena

- **WHEN** el agente arranca con una entrada `pending` de `quarantine`, el artefacto autenticado presente, el origen ausente y la entrada de baseline todavía `present`
- **THEN** la rehidratación no crea un artefacto nuevo, deja la entrada de baseline `quarantined` con el contenido aprobado, publica el evento y cierra el journal

## ADDED Requirements

### Requirement: La cuarentena tiene una única implementación compartida por ambos caminos

`quarantine_and_record` (`agent/quarantine.py`) SHALL ser la única implementación de la cuarentena, usada por `DecisionEngine._quarantine` (camino automático y rehidratación) y por `handle_quarantine_file` (camino del operador) (D82/RN-176, residual §9). Su orden SHALL ser: (1) entrada `pending` en el journal para la identidad de acción, sin pisar una entrada `pending` que el llamador ya haya escrito; (2) `QuarantineStore.quarantine(action_id, path)`; (3) sólo si (2) tuvo éxito, `BaselineEngine.mark_quarantined(path, action_id)`; (4) devolver al llamador el artefacto o la causa de falla. MUST NOT escribir el paso terminal del journal: lo hace el llamador. MUST NOT propagar excepciones por fallas esperadas: toda falla se devuelve como causa del vocabulario cerrado. Si (3) falla, la causa SHALL ser `baseline_mark_failed` y el artefacto SHALL conservarse.

#### Scenario: Los dos caminos producen el mismo efecto observable

- **WHEN** el mismo archivo con la misma versión aprobada se pone en cuarentena una vez por el camino automático y otra por el camino del operador (prueba parametrizada sobre ambos caminos)
- **THEN** en los dos casos existe un artefacto autenticado direccionado por el `event_id` del agente, el origen no existe, la entrada de baseline es `quarantined` y `select_restorable_content` devuelve los bytes aprobados

#### Scenario: El marcado del baseline falla

- **WHEN** la cuarentena tiene éxito pero la escritura de la entrada `quarantined` levanta un error
- **THEN** la causa devuelta es `baseline_mark_failed`, el artefacto existe y el llamador cierra el journal como `failed`

### Requirement: Las fallas de cuarentena usan un único vocabulario en ambos caminos

Las causas de falla de una cuarentena SHALL ser literales en minúsculas snake_case (RN-71), idénticos en el evento publicado, en el journal y en el `command_ack`: la `reason` de `QuarantineError` (por ejemplo `file_not_found`, `hardlink_not_isolatable`, `unsupported_file_type`, `quarantine_source_changed`, `quarantine_identity_missing`, `quarantine_identity_mismatch`), `quarantine_store_unavailable` cuando no hay almacén utilizable, el resultado de `action_error_from_oserror` con fallback `move_failed` para un `OSError`, `baseline_mark_failed` cuando falla el marcado, y `quarantine_failed` para cualquier otra excepción. La causa MUST NOT interpolar el mensaje del sistema operativo ni la ruta; el detalle va a campos estructurados del log.

#### Scenario: Una excepción inesperada no filtra su mensaje

- **WHEN** la cuarentena del camino del operador levanta una excepción no prevista cuyo mensaje contiene la ruta del archivo
- **THEN** el `command_ack` y el journal llevan `quarantine_failed` y no contienen la ruta

#### Scenario: Misma causa en ambos caminos

- **WHEN** se intenta poner en cuarentena un archivo regular con dos hardlinks por cada uno de los dos caminos
- **THEN** ambos reportan `hardlink_not_isolatable`
