# Spec: backend-notifications (delta)

## MODIFIED Requirements

### Requirement: Retry manual de alerta con referencia fuerte a la task asyncio

El endpoint `POST /alerts/{id}/retry` MUST guardar una referencia fuerte a la `asyncio.Task` creada para `notify_event`. La referencia SHALL mantenerse en un `set` module-level hasta que la task complete, previniendo cancelación silenciosa por el GC durante los sleeps del retry loop (hasta 120 s de espera).

#### Scenario: Task de reintento no es cancelada durante sleep

- **WHEN** un operador llama `POST /alerts/{id}/retry` y `notify_event` está esperando en `asyncio.sleep(30)`
- **THEN** la task mantiene una referencia fuerte durante el sleep
- **AND** el GC no puede cancelar la task antes de que complete el reintento
