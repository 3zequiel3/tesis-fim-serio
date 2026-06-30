# Spec: backend-health (delta)

## MODIFIED Requirements

### Requirement: Notificación de cambio de estado de componente con referencia fuerte a la task asyncio

El health checker MUST guardar una referencia fuerte a cualquier `asyncio.Task` creada para notificar cambios de estado de componentes (e.g., `send_n8n`). La referencia SHALL mantenerse en un `set` module-level hasta que la task complete, previniendo cancelación silenciosa por el GC antes de que la notificación se envíe.

#### Scenario: Task de notificación de health no es cancelada por GC

- **WHEN** el health checker detecta un cambio de estado y crea una task para notificar vía n8n
- **THEN** la task mantiene una referencia fuerte hasta completar
- **AND** el GC no puede cancelar la task durante el I/O HTTP de la notificación
