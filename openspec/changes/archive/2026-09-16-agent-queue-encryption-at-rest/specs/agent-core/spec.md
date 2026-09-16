## ADDED Requirements

### Requirement: The offline queue is opened only after master_secret is loaded

El proceso principal del agente SHALL construir la cola offline sólo después de completar el bootstrap, cuando corresponda, y de cargar `master_secret` desde el directorio de secretos. La cola SHALL recibir ese `master_secret` y el `agent_id` de la configuración para derivar su clave; MUST NOT existir un camino de arranque que abra la cola, encole o migre archivos sin esa clave, ni un modo de cola en claro.

Si `master_secret` falta o no tiene 32 bytes, el agente SHALL fallar al arrancar con un error claro antes de abrir la cola, sin escribir ni reescribir ningún archivo de cola o descarte. (D63 / RN-157, RN-50)

#### Scenario: La cola se construye con la clave ya disponible

- **WHEN** el agente arranca con el bootstrap completo y un `master_secret` válido
- **THEN** la cola se abre con ese `master_secret` y el `agent_id` configurado, después de cargarlos y antes de crear el publisher

#### Scenario: Sin master_secret no se toca la cola

- **WHEN** el agente arranca y `master_secret` no existe o no tiene 32 bytes
- **THEN** el proceso termina con un error claro y los archivos de cola y descarte quedan sin modificar

#### Scenario: La cola no admite construcción sin clave

- **WHEN** se intenta construir la cola sin `master_secret` o sin `agent_id`
- **THEN** la construcción falla y no se crea ni se escribe ningún archivo
