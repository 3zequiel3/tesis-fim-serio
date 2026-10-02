## ADDED Requirements

### Requirement: El detalle del evento muestra la detección con el agente detenido

El tipo de evento del frontend SHALL incluir `detected_offline?: boolean | null`. La vista de detalle del evento SHALL mostrar, junto a los demás indicadores del encabezado, un indicador de detección offline cuando `detected_offline` es `true`, con un texto accesible que explique que el cambio ocurrió con el agente detenido y que `detected_at` es el instante en que se detectó al arrancar, no el del cambio. Con `false`, `null` o el campo ausente, el indicador MUST NOT renderizarse y los indicadores existentes MUST NOT verse afectados. La tabla de eventos MUST NOT cambiar. (D80 / RN-174, RN-71)

#### Scenario: Evento detectado offline
- **WHEN** se abre el detalle de un evento con `detected_offline: true`
- **THEN** el encabezado muestra el indicador de detección offline con su explicación

#### Scenario: Evento en línea
- **WHEN** se abre el detalle de un evento con `detected_offline: false`
- **THEN** no se renderiza el indicador

#### Scenario: Evento anterior al campo
- **WHEN** se abre el detalle de un evento con `detected_offline` nulo o ausente
- **THEN** no se renderiza el indicador y el resto del encabezado no cambia
