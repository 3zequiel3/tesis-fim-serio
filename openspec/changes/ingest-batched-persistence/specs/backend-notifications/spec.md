## ADDED Requirements

### Requirement: Las entregas HTTP del carril de notificación reutilizan un cliente de larga vida

Las entregas HTTP del carril de notificación (`send_n8n` y `send_webhook_fallback`) SHALL usar un
único cliente HTTP asíncrono de larga vida. MUST NOT construir un cliente nuevo por entrega
(ampliación del 2026-10-03 de D87/RN-181).

**Ciclo de vida.**
- El cliente SHALL crearse en el arranque del backend.
- SHALL cerrarse al apagarse, después de detener las tareas que agendan entregas y antes de apagar
  los executors.
- Si una entrega ocurre sin el cliente creado (fuera del ciclo de vida de la aplicación), el cliente
  SHALL crearse con la misma configuración.
- Una vez cerrado en el apagado, el cliente MUST NOT recrearse: una entrega que sobreviva al cierre
  SHALL fallar y seguir la escalera de reintentos durable en el próximo arranque.

**TLS.** La verificación de certificados MUST permanecer activa, con el almacén de confianza por
defecto, y el contexto TLS SHALL construirse una sola vez, al crear el cliente.

**Timeouts.** El timeout de cada canal (10 s) SHALL aplicarse por pedido.

**Pool de conexiones.**
- SHALL acotarse a `notify_max_concurrent_deliveries` conexiones, abiertas y en reposo.
- Las conexiones en reposo SHALL expirar a los 4 s, por debajo del keep-alive de 5 s del servidor
  HTTP de n8n.

**Errores y reintentos.** La semántica de error y reintento de cada entrega MUST NOT cambiar:
- un error de transporte, incluido un reset de conexión o un reinicio de n8n, SHALL hacer fallar
  sólo esa entrega, que sigue la escalera de reintentos durable (D42/RN-136);
- la entrega siguiente SHALL abrir una conexión nueva sin intervención.

El chequeo de salud de n8n queda fuera de este requisito y conserva su cliente por llamada.

#### Scenario: Dos entregas usan el mismo cliente
- **WHEN** el carril de notificación entrega dos alertas consecutivas a n8n
- **THEN** ambas entregas usan la misma instancia del cliente HTTP
- **AND** no se construye ningún cliente HTTP nuevo entre ellas

#### Scenario: El cliente se cierra al apagar el backend
- **WHEN** el backend se apaga
- **THEN** el cliente HTTP del carril de notificación queda cerrado
- **AND** no quedan conexiones abiertas a n8n

#### Scenario: Una entrega posterior al cierre no recrea el cliente
- **WHEN** una entrega pendiente se ejecuta después de que el backend cerró el cliente HTTP
- **THEN** la entrega falla sin construir un cliente nuevo

#### Scenario: La verificación TLS permanece activa
- **WHEN** se crea el cliente HTTP del carril de notificación
- **THEN** su contexto TLS exige un certificado válido y verifica el nombre del host

#### Scenario: Un reset de conexión se recupera en la entrega siguiente
- **WHEN** n8n se reinicia o cierra la conexión reutilizada y una entrega falla con un error de transporte
- **THEN** esa entrega devuelve fallo y sigue la escalera de reintentos durable
- **AND** la entrega siguiente abre una conexión nueva y se entrega con éxito si n8n responde

#### Scenario: El timeout por canal se conserva
- **WHEN** n8n no responde dentro de 10 s
- **THEN** la entrega falla por timeout igual que antes del cliente compartido
