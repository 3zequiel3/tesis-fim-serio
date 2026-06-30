# Spec: backend-event-consumer (delta)

## MODIFIED Requirements

### Requirement: Consumer resiliente en startup ante Valkey no disponible

El consumer de eventos MUST envolver las llamadas de inicialización (`_ensure_group`, `_process_batch("0")`) en un bloque try/except antes del loop principal. Si Valkey no está disponible al arrancar, el consumer MUST loguear el error con nivel ERROR, esperar 1 segundo, y reintentar hasta conectarse. No MUST morir permanentemente por fallo en la inicialización.

#### Scenario: Valkey no disponible al arrancar — consumer reintenta

- **WHEN** el backend arranca y Valkey no responde durante `_ensure_group`
- **THEN** el consumer loguea el error y reintenta cada 1 segundo
- **AND** el consumer NO muere permanentemente ni deja de procesar eventos cuando Valkey se recupera

#### Scenario: Procesamiento de pendientes falla al arrancar — consumer entra al loop de todas formas

- **WHEN** `_process_batch("0")` falla por un error transitorio de Valkey o DB al arrancar
- **THEN** el consumer loguea el error y continúa al loop principal de mensajes nuevos
- **AND** los mensajes pendientes serán reprocesados en el próximo reinicio

### Requirement: Notificaciones post-ingesta con referencia fuerte a la task asyncio

El consumer de eventos MUST guardar una referencia fuerte a cualquier `asyncio.Task` creada para `notify_if_applicable`. La referencia SHALL mantenerse en un `set` module-level hasta que la task complete, previniendo cancelación silenciosa por el GC. La task MUST removerse del set al completar (callback `discard`).

#### Scenario: Task de notificación no es cancelada por GC

- **WHEN** el consumer crea una task de notificación para un evento crítico
- **THEN** la task mantiene una referencia fuerte hasta que `notify_if_applicable` complete
- **AND** el GC no puede cancelar la task mientras está en vuelo
