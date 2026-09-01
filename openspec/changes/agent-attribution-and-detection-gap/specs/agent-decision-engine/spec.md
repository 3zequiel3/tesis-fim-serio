## MODIFIED Requirements

### Requirement: Rehidratación de journal al arrancar

Al iniciar, el agente SHALL escanear `/var/lib/fim-agent/journal/` y procesar todas las entradas con
`state: "pending"` (RN-83). Para cada entrada pendiente con acción `auto_restore` o `quarantine`:
MUST reintentarse la acción. Para cada entrada pendiente con acción `manual_review` o `alert_only`:
MUST marcarse `state: "failed"` con `error: "rehydrated_without_action"` y re-publicarse como evento
`alert_only` para que el backend lo registre. La rehidratación MUST completarse antes de que el
detector comience a aceptar nuevos eventos.

El payload que la rehidratación reconstruye MUST emitir `process_pid`, `process_uid` y `process_exe`
en **`null`** (D49/RN-143). En esta ruta el proceso causante ya no existe **por definición** —la
rehidratación corre tras un reinicio del agente—, de modo que el contexto de proceso es
irrecuperable. El agente MUST NOT escribir `0` en `process_uid`: ese valor significa root, y usarlo
acá haría que **todo** evento recuperado del journal se reportara como un cambio hecho por root. Por
la misma razón MUST NOT escribir `0` en `process_pid`, que es el pid del scheduler del kernel y no
el de un proceso de usuario.

#### Scenario: Journal pending auto_restore — reintentado al arrancar

- **WHEN** el agente arranca y encuentra `journal/evt-001.json` con `action: "auto_restore"` y `state: "pending"`
- **THEN** intenta restaurar el archivo, actualiza el journal a `completed` o `failed`, y publica el resultado

#### Scenario: Journal pending manual_review — descartado con aviso

- **WHEN** el agente arranca y encuentra `journal/evt-002.json` con `action: "manual_review"` y `state: "pending"`
- **THEN** marca el journal `failed` con `error: "rehydrated_without_action"` y publica un evento `alert_only` al stream

#### Scenario: Sin entradas pending — arranque limpio

- **WHEN** el agente arranca y no hay entradas `pending` en el journal
- **THEN** la fase de rehidratación termina sin publicar eventos adicionales

#### Scenario: El evento rehidratado no atribuye contexto de proceso

- **WHEN** el agente rehidrata cualquier entrada pendiente del journal y publica el evento resultante
- **THEN** el payload publicado contiene `process_pid=None`, `process_uid=None` y `process_exe=None`
- **AND** no contiene el valor `0` en ninguno de esos tres campos

## ADDED Requirements

### Requirement: Un evento sin ruta no ejecuta acción física

Un evento con `path` nulo SHALL emitirse con `action: "alert_only"` y MUST NOT ejecutar `auto_restore` ni `quarantine` bajo ninguna configuración de reglas.

El motor de decisión evalúa reglas contra la **ruta** del evento (`RulesCache.evaluate` matchea
patrones glob contra el path) y sus dos acciones físicas —`_auto_restore` y `_quarantine`— reciben el
path y operan sobre el filesystem. Un evento sin ruta no tiene nada que matchear ni nada sobre qué
actuar.

El motor MUST NOT ser el punto
donde se decide esto: el productor del evento sin ruta lo publica con la acción ya resuelta y sin
invocar `evaluate_and_act`, de modo que ni el ruleset ni el journal transaccional participen de un
evento que no tiene acción que registrar (D50/RN-144).

Si por una ruta futura un evento sin ruta llegara igualmente a `evaluate_and_act`, el motor SHALL
degradar a `alert_only` sin lanzar excepción y sin tocar el filesystem: la ausencia de ruta MUST NOT
propagarse como error al pipeline de publicación.

#### Scenario: Un detection_gap se publica como alert_only

- **WHEN** el detector emite un evento `detection_gap` con `path=None`
- **THEN** el payload publicado lleva `action="alert_only"`
- **AND** no se creó ninguna entrada de journal para ese evento

#### Scenario: Ninguna regla puede convertir un evento sin ruta en una acción física

- **WHEN** el ruleset contiene una regla `auto_restore` con patrón `**` que matchearía cualquier path
- **AND** se procesa un evento con `path=None`
- **THEN** no se restaura ni se pone en cuarentena ningún archivo
- **AND** la acción resultante es `alert_only`

#### Scenario: El motor degrada sin romper si recibe un evento sin ruta

- **WHEN** `evaluate_and_act` recibe un cambio con `path=None`
- **THEN** retorna un payload con `action="alert_only"` sin lanzar excepción
- **AND** no se realiza ninguna escritura ni movimiento en el filesystem
