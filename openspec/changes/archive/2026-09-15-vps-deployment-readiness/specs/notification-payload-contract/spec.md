## MODIFIED Requirements

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
