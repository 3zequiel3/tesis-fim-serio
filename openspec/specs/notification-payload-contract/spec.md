# notification-payload-contract Specification

## Purpose
TBD - created by archiving change n8n-contract-and-config. Update Purpose after archive.
## Requirements
### Requirement: Forma canónica del payload de notificación (D40/RN-134)

El sistema SHALL emitir todas las notificaciones hacia el canal n8n con un **sobre plano**: los campos de metadatos del sobre (`schema_version`, `notification_id`, `type`) SHALL ser hermanos de los campos de datos y NO SHALL anidarse bajo una clave contenedora.

El payload de una notificación de alerta SHALL contener exactamente los siguientes campos:

| Campo | Origen | Obligatorio |
|---|---|---|
| `schema_version` | constante, entero, valor inicial `1` | sí |
| `notification_id` | uuid v4 generado al crear la notificación | sí |
| `type` | `"alert"` | sí |
| `alert_id` | `Alert.id` | sí |
| `event_id` | `Event.event_id` | sí |
| `path` | `Event.path` | sí |
| `severity` | `Alert.severity` | sí |
| `status` | `Event.status` | sí |
| `action_taken` | `Event.status` interpretado como acción ejecutada (D35/RN-129) | sí |
| `action_failed` | `Event.action_failed` | sí |
| `is_symlink` | `Event.is_symlink` | sí |
| `agent_id` | `Event.agent_id` | sí |
| `process_pid` | `Event.process_pid` | sí, puede ser `null` |
| `process_uid` | `Event.process_uid` | sí, puede ser `null` |
| `process_exe` | `Event.process_exe` | sí, puede ser `null` |
| `detected_at` | `Event.detected_at`, ISO 8601 con zona | sí |
| `received_at` | `Event.received_at`, ISO 8601 con zona | sí |
| `alert_created_at` | `Alert.created_at`, ISO 8601 con zona | sí |

El nombre canónico del path SHALL ser `path`. El sistema SHALL NO emitir `file_path`.

Ningún campo de esta tabla requiere captura nueva por parte del agente: el modelo `Event` ya los persiste.

#### Scenario: El payload cumple RN-53
- **WHEN** se construye el payload de una alerta a partir de un `Alert` y su `Event`
- **THEN** el payload contiene `action_taken`, `process_pid`, `process_uid`, `process_exe` y `received_at`
- **AND** contiene `event_id`, `path` y `severity`

#### Scenario: El sobre es plano
- **WHEN** se construye el payload de una alerta
- **THEN** `schema_version`, `notification_id` y `type` están en el nivel superior del objeto
- **AND** no existe ninguna clave `data` que contenga los campos de la alerta
- **AND** `payload["path"]` es accesible sin atravesar ninguna clave intermedia

#### Scenario: El nombre del path es `path`, no `file_path`
- **WHEN** se inspecciona cualquier payload emitido
- **THEN** la clave `path` está presente
- **AND** la clave `file_path` NO está presente

#### Scenario: Contexto de proceso ausente se emite como null
- **WHEN** el `Event` tiene `process_pid`, `process_uid` y `process_exe` en `None`
- **THEN** las tres claves están presentes en el payload con valor `null`
- **AND** el payload no las omite

### Requirement: `notification_id` estable a lo largo de la escalera de reintentos

El sistema SHALL generar un `notification_id` (uuid v4) por notificación y SHALL reutilizar el mismo valor en todos los reintentos de esa notificación. Dos notificaciones distintas SHALL tener `notification_id` distintos.

Este identificador existe para permitir deduplicación aguas abajo (D41/RN-135). Su consumo por parte de los workflows de n8n queda fuera de este change.

#### Scenario: Reintentos comparten el identificador
- **WHEN** una notificación falla y se reintenta dos veces más
- **THEN** los tres envíos llevan el mismo `notification_id`

#### Scenario: Notificaciones distintas no colisionan
- **WHEN** se generan payloads para dos alertas distintas
- **THEN** sus `notification_id` son distintos

### Requirement: `type` discrimina alerta de cambio de salud

El sistema SHALL incluir un campo `type` en todo payload emitido hacia el canal n8n, con valor `"alert"` para notificaciones de evento y `"health_change"` para notificaciones de cambio de estado de componente.

Ambas formas comparten una única URL de webhook, por lo que sin este discriminador el receptor no puede distinguirlas.

#### Scenario: Notificación de alerta
- **WHEN** se construye el payload de una alerta de evento
- **THEN** `payload["type"] == "alert"`

#### Scenario: Notificación de cambio de salud
- **WHEN** el health checker detecta un cambio de estado de componente
- **THEN** el payload emitido tiene `payload["type"] == "health_change"`
- **AND** incluye `schema_version` y `notification_id`

### Requirement: Test de contrato entre los workflows de n8n y el payload emitido

La suite del backend SHALL incluir un test que cargue todos los archivos `n8n/workflows/*.json` y extraiga por expresión regular cada referencia a un campo del payload en las formas de acceso aceptadas (D44/RN-138):

- `$json.body.<campo>` en el enrutador, que recibe el payload por webhook;
- `$json.payload.<campo>` o `.json.payload.<campo>` (por ejemplo `$('<nodo>').item.json.payload.<campo>`) en los sub-flujos invocados por `Execute Workflow Trigger`, que reciben el payload bajo la clave `payload`.

El test SHALL afirmar que cada `<campo>` referenciado existe en al menos una de las formas del payload que el backend produce (`type = "alert"` o `type = "health_change"`), y SHALL fallar si un workflow lee un campo que el backend no emite, nombrando el campo y el archivo.

El test SHALL incluir un caso negativo que verifique que el propio mecanismo de extracción funciona: si el conjunto de campos extraídos queda vacío, el test SHALL fallar en lugar de pasar vacuamente. SHALL fallar también si algún sub-flujo no produce ninguna referencia, de modo que un sub-flujo no pueda quedar fuera del contrato por usar una forma de acceso no aceptada. La lista de referencias toleradas sin respaldo en el payload SHALL estar vacía: el destinatario del correo y el sistema de ticketing son configuración de n8n, no datos del payload (RN-52).

#### Scenario: Contrato alineado
- **WHEN** todos los campos referenciados por los workflows, en ambas formas de acceso, existen en el payload
- **THEN** el test pasa

#### Scenario: Workflow lee un campo inexistente
- **WHEN** un workflow referencia `$json.body.nonexistent_field` o `$json.payload.nonexistent_field` y el payload no lo emite
- **THEN** el test falla nombrando el campo y el archivo de workflow que lo referencia

#### Scenario: Caso negativo — extracción vacía no pasa vacuamente
- **WHEN** la extracción de referencias no encuentra ningún campo
- **THEN** el test falla
- **AND** el mensaje indica que el fixture no produjo referencias, en lugar de reportar éxito

#### Scenario: Sub-flujo fuera del contrato
- **WHEN** un sub-flujo con `Execute Workflow Trigger` no contiene ninguna referencia en las formas aceptadas
- **THEN** el test falla nombrando el archivo del sub-flujo

#### Scenario: Sin referencias toleradas
- **WHEN** se inspecciona la lista de referencias toleradas sin respaldo
- **THEN** está vacía y ningún workflow lee `recipient` ni `ticketing_system`

