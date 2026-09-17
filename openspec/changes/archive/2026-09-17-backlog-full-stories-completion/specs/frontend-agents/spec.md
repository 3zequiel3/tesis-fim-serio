## ADDED Requirements

### Requirement: El banner de presión de cola se deriva del flag que emite el agente

La tarjeta del agente SHALL mostrar el banner de alerta específico del agente (US-21, W3) **si y sólo si**
`queue_pressure_high` vale `true`. El frontend SHALL NOT calcular el umbral del 80 % a partir del ratio
`queue_pressure`: el umbral es una propiedad de la cola del agente y lo decide el agente (D72/RN-166).

Cuando `queue_pressure_high` es `false`, `null` o ausente, el banner SHALL NOT mostrarse. No SHALL existir
un respaldo que recalcule el umbral en el cliente para agentes que no envían la clave: reintroduciría la
divergencia que D72/RN-166 cierra.

La barra de presión SHALL seguir mostrando el porcentaje derivado del ratio `queue_pressure`, de modo que
la ocupación de la cola siga visible aunque el flag falte. El tipo `Agent` de `frontend/src/api/agents.ts`
SHALL declarar `queue_pressure_high?: boolean | null`.

#### Scenario: El flag en verdadero muestra el banner

- **WHEN** el agente tiene `queue_pressure_high: true`
- **THEN** la tarjeta muestra el banner de alerta específico del agente

#### Scenario: El flag decide aunque el ratio diga otra cosa

- **WHEN** el agente tiene `queue_pressure: 0.95` y `queue_pressure_high: false`
- **THEN** la tarjeta no muestra el banner y la barra muestra 95 %

#### Scenario: El flag en verdadero muestra el banner con cualquier ratio

- **WHEN** el agente tiene `queue_pressure: 0.5` y `queue_pressure_high: true`
- **THEN** la tarjeta muestra el banner

#### Scenario: Un agente anterior a la clave no muestra el banner ni rompe la tarjeta

- **WHEN** el agente tiene `queue_pressure: 0.9` y `queue_pressure_high` nulo o ausente
- **THEN** la tarjeta se renderiza sin error, no muestra el banner y la barra muestra 90 %
