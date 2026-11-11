## MODIFIED Requirements

### Requirement: SystemBanner con polling de /health/components

El sistema SHALL tener `frontend/src/components/layout/SystemBanner.tsx` que hace polling a `GET /health/components` cada 10 segundos (RN-101). Si algún componente devuelve `"down"`, MUST mostrar un banner rojo visible en la parte superior del layout con un mensaje indicando degradación. Si todos están `"ok"` o `"degraded"`, no se muestra el banner rojo (solo se muestra para `"down"`). Si la propia consulta a `/health/components` falla (red, `5xx` o timeout), MUST mostrar un banner de advertencia «No se puede consultar el estado del sistema.» en lugar de ocultarse o seguir mostrando el último resultado como vigente; el banner desaparece con la siguiente respuesta exitosa (D93/RN-187). El banner MUST usar los tokens de estado del tema activo.

#### Scenario: Componente down muestra banner rojo
- **WHEN** `GET /health/components` retorna algún componente con `"down"`
- **THEN** aparece un banner rojo en la parte superior con mensaje de alerta del sistema

#### Scenario: Todos los componentes ok — sin banner
- **WHEN** todos los componentes retornan `"ok"` o `"degraded"`
- **THEN** no se muestra el banner rojo (puede mostrarse amarillo por degraded según criterio de implementación)

#### Scenario: Polling actualiza el estado cada 10 segundos
- **WHEN** un componente pasa de `"ok"` a `"down"` entre polls
- **THEN** el banner aparece en el próximo ciclo de 10 segundos sin recargar la página

#### Scenario: La consulta de salud falla
- **WHEN** `GET /health/components` responde `502` o no responde
- **THEN** se muestra «No se puede consultar el estado del sistema.»
- **AND** con la siguiente respuesta exitosa sin componentes `"down"` el banner desaparece
