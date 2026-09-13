## ADDED Requirements

### Requirement: Enrutador único `fim-alert` con sub-flujos invocados (D44/RN-138, RN-52)

`n8n/workflows/` SHALL contener exactamente un workflow con nodo webhook: el enrutador, con path `fim-alert` y método `POST`. Los workflows de correo, mensajería y ticketing SHALL ser sub-flujos cuyo disparador es `Execute Workflow Trigger` y SHALL NOT contener nodos webhook. El enrutador SHALL discriminar por `type` (`alert`, `health_change`) y SHALL invocar cada sub-flujo habilitado con `Execute Workflow`, pasando el payload recibido bajo la clave `payload` y esperando a que el sub-flujo termine. El conjunto de canales habilitados SHALL ser configuración del despliegue, no un dato del payload: SHALL declararse en el `.env` del servidor (`N8N_FIM_CHANNELS` y las variables de cada canal) y el servicio de provisioning SHALL importar las credenciales con `import:credentials` y fijar ese conjunto en el enrutador en cada arranque (D58/RN-152). El entorno del contenedor SHALL NOT exponerse a las expresiones de los workflows (`N8N_BLOCK_ENV_ACCESS_IN_NODE` conserva su default). Un canal no habilitado SHALL NOT invocarse.

#### Scenario: Un solo webhook en todo el directorio
- **WHEN** se inspeccionan todos los archivos de `n8n/workflows/`
- **THEN** existe exactamente un nodo de tipo webhook, con path `fim-alert`

#### Scenario: Alerta enrutada a los canales habilitados
- **WHEN** se hace `POST /webhook/fim-alert` con un payload `type = "alert"` y hay dos canales habilitados
- **THEN** el enrutador ejecuta los dos sub-flujos habilitados y ninguno más

#### Scenario: Cambio de salud enrutado
- **WHEN** se hace `POST /webhook/fim-alert` con un payload `type = "health_change"`
- **THEN** el enrutador ejecuta la rama de `health_change` sin error

### Requirement: Workflows importables con identidad estable (D44/RN-138)

Cada archivo de `n8n/workflows/` SHALL tener en la raíz un `id` UUID estable y distinto, un `name` y la estructura estándar de exportación de n8n. SHALL NOT contener claves no estándar como `__meta`. El `id` de un workflow SHALL NOT cambiar entre versiones del repositorio, porque es la clave de idempotencia del provisioning. Las referencias del enrutador a sus sub-flujos SHALL hacerse por esos `id`.

#### Scenario: Identidades estables y únicas
- **WHEN** se cargan todos los workflows
- **THEN** cada uno tiene un `id` UUID en la raíz y no hay dos iguales
- **AND** ninguno contiene la clave `__meta`

#### Scenario: El enrutador referencia sub-flujos existentes
- **WHEN** se inspeccionan los nodos `Execute Workflow` del enrutador
- **THEN** cada `id` referenciado corresponde a un sub-flujo presente en el directorio

### Requirement: La respuesta al backend refleja la entrega efectiva

El enrutador SHALL usar `responseMode: responseNode` y responder con un nodo `Respond to Webhook` después de que terminen los sub-flujos invocados. SHALL responder con un código 2xx sólo si al menos un sub-flujo confirmó la entrega, y con un código no-2xx en cualquier otro caso, incluido que ningún canal esté habilitado, de modo que el backend no marque como entregada una alerta que nadie recibió y aplique su cascada (D43/RN-137, D42/RN-136). El cuerpo de la respuesta SHALL incluir el resultado por canal. SHALL NOT usarse `responseMode: onReceived`.

#### Scenario: Al menos un canal entrega
- **WHEN** uno de los sub-flujos invocados confirma la entrega y otro falla
- **THEN** el enrutador responde 2xx con el resultado de ambos canales

#### Scenario: Ningún canal entrega
- **WHEN** todos los sub-flujos invocados fallan
- **THEN** el enrutador responde con un código no-2xx con el error de cada canal

#### Scenario: Ningún canal habilitado
- **WHEN** no hay canales habilitados y llega una alerta
- **THEN** el enrutador responde con un código no-2xx que indica que no hay canal configurado

### Requirement: Expresiones y nodos válidos en n8n 2.17.8

Los workflows SHALL usar sólo expresiones JavaScript válidas de n8n: SHALL NOT usar filtros estilo Jinja (`| upper`) y SHALL usar métodos como `.toUpperCase()`. SHALL NOT referenciar `$credentials` dentro de expresiones de parámetros; todo nodo que requiere una credencial SHALL declararla en su bloque `credentials`. Los nodos Switch SHALL usar la versión 3 con `numberOutputs` y conexiones por índice numérico de salida. `responseMode` y `responseData` SHALL ser coherentes entre sí en cada nodo webhook.

#### Scenario: Sin filtros Jinja ni `$credentials` en expresiones
- **WHEN** se inspecciona el texto de todos los workflows
- **THEN** no aparece `| upper` ni `$credentials.`

#### Scenario: Nodos con credencial declarada
- **WHEN** se inspeccionan los nodos de correo, Slack, Jira y Linear
- **THEN** cada uno tiene un bloque `credentials` no vacío

#### Scenario: Switch con salidas numéricas
- **WHEN** se inspeccionan los nodos Switch
- **THEN** tienen `typeVersion` 3, declaran `numberOutputs` y sus conexiones usan índices numéricos

### Requirement: Search-before-create en el sub-flujo de ticketing (D41/RN-135)

Antes de crear un ticket, el sub-flujo de ticketing SHALL consultar al sistema de tickets por un marcador determinístico derivado de `event_id`, que SHALL escribir también en todo ticket que cree. Si encuentra un ticket con ese marcador, SHALL NOT crear otro y SHALL informar la entrega como confirmada. Los sub-flujos de correo y mensajería SHALL NOT deduplicar: la entrega at-least-once es comportamiento declarado.

#### Scenario: Reintento del mismo evento
- **WHEN** se hacen dos `POST /webhook/fim-alert` con el mismo `event_id` y ticketing habilitado contra un sistema de tickets controlado
- **THEN** el sistema de tickets contiene exactamente un ticket con el marcador de ese `event_id`
- **AND** ambas respuestas del enrutador informan la entrega de ticketing como confirmada

#### Scenario: Eventos distintos
- **WHEN** se hacen dos `POST` con `event_id` distintos
- **THEN** se crean dos tickets, cada uno con su marcador
