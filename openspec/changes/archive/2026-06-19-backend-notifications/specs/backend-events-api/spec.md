# Spec: backend-events-api (delta)

Delta sobre la capability `backend-events-api`. Agrega el hook de notificación post-ingesta en el event consumer.

---

## ADDED Requirements

### Requirement: Hook de notificación post-ingesta en el event consumer

El consumer SHALL disparar una tarea asincrónica de notificación (`asyncio.create_task(notify_if_applicable(event))`) tras persistir exitosamente un evento en DB y realizar XACK, sin bloquear el flujo del consumer ni depender el XACK del resultado de la notificación.

**Contexto existente**: El consumer `consumer.py` ingiere eventos de Valkey Streams, persiste en DB y hace XACK. Este delta agrega la llamada de notificación después del XACK, sin modificar la lógica de ingesta ni el flujo de XACK.

**Cambio**: Después de que un evento se persiste exitosamente en DB y se realiza XACK, el consumer SHALL disparar `asyncio.create_task(notify_if_applicable(event))` donde `notify_if_applicable` está definido en `backend/app/modules/alerts/service.py`. La función retorna inmediatamente sin await — es fire-and-forget desde la perspectiva del consumer.

**Invariante preservado**: El XACK NO depende del resultado de la notificación. Si la notificación falla internamente, no impacta el procesamiento del stream.

#### Scenario: Evento persistido dispara tarea de notificación
- **WHEN** el consumer persiste exitosamente un evento en DB y hace XACK
- **THEN** se crea un `asyncio.Task` con `notify_if_applicable(event)` sin bloquear el loop del consumer

#### Scenario: Evento que falla la persistencia no dispara notificación
- **WHEN** `_ingest()` lanza una excepción o retorna None
- **THEN** NO se llama `notify_if_applicable`

#### Scenario: Error en la notificación no afecta el consumer
- **WHEN** `notify_if_applicable` levanta una excepción internamente
- **THEN** el consumer continúa procesando el siguiente mensaje normalmente (la excepción queda en el Task)
