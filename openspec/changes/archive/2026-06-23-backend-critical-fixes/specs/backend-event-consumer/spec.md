## MODIFIED Requirements

### Requirement: Protocolo ACK end-to-end con persistencia y dedup idempotente

Tras pasar todas las validaciones, el consumer SHALL clasificar el resultado del procesamiento de cada mensaje del stream `events` mediante una taxonomía explícita y ejecutar `XACK` de forma **condicional** según el resultado (C8):

- **Éxito** (la ingesta retorna un `Event`): persistir el `Event` en PostgreSQL, ejecutar `XACK`, y publicar un mensaje `event_ack` en el stream `commands` con el `event_id` y `target_agent_id` igual al `agent_id` del evento (D5, RN-73, RN-106). El `event_ack` MUST ir firmado con `HMAC-SHA256(shared_secret, canonical_json(payload))` (RN-79).
- **Skip legítimo** (re-entrega de un `event_id` ya persistido, o carrera de `mark_superseded` que aborta la creación): NO re-insertar el `Event`, ejecutar `XACK` (la entrada ya fue procesada), y para la re-entrega publicar `event_ack`.
- **Error de datos** (`InvalidTransitionError`): ejecutar `XACK` (el mensaje es inválido y no reintentable) y auditar el rechazo. No reintentar.
- **Error transitorio de base de datos** (`SQLAlchemyError`): NO ejecutar `XACK`. El mensaje MUST permanecer en la Pending Entries List (PEL) del consumer group para reintento automático. El consumer MUST loguear el error con `exc_info=True`.

El consumer MUST deduplicar por `event_id`: si el `event_id` ya está persistido, NO re-inserta el `Event` ni audita un rechazo, pero igualmente ejecuta `XACK` y publica `event_ack` (re-entrega legítima at-least-once, RN-73).

#### Scenario: Evento válido persistido y confirmado
- **WHEN** llega un evento válido `e1` del agente `a1` que no existe en la base
- **THEN** el backend inserta el `Event`, ejecuta `XACK`, y publica `event_ack` en `commands` con `event_id = e1` y `target_agent_id = a1`
- **AND** el `event_ack` lleva una `signature` HMAC válida

#### Scenario: Re-entrega de un evento ya persistido
- **WHEN** llega de nuevo el evento `e1` cuyo `event_id` ya está persistido
- **THEN** el backend NO inserta un segundo `Event` ni una fila en `rejected_events_audit`
- **AND** ejecuta `XACK` y vuelve a publicar `event_ack` para `e1`

#### Scenario: Error de datos no reintentable hace XACK
- **WHEN** la ingesta de un evento lanza `InvalidTransitionError`
- **THEN** el consumer ejecuta `XACK` sobre la entrada
- **AND** audita el rechazo
- **AND** no reintenta el mensaje

#### Scenario: Error transitorio de DB NO hace XACK y queda en PEL
- **WHEN** la ingesta de un evento válido lanza `SQLAlchemyError` (fallo transitorio de base de datos)
- **THEN** el consumer NO ejecuta `XACK`
- **AND** el mensaje permanece en la Pending Entries List del consumer group
- **AND** el consumer loguea el error con `exc_info=True`
- **AND** el evento de integridad no se pierde silenciosamente (queda disponible para reintento)

### Requirement: Compactación de cadena a máximo 10 eventos por path

Inmediatamente después de marcar un evento como `superseded` y crear el nuevo evento, el sistema SHALL contar los eventos `superseded` para el mismo path. Si el conteo supera 10, SHALL eliminar los `superseded` más antiguos hasta que la cadena tenga exactamente 10, excluyendo del borrado los que tengan `id` referenciado en `audit_log.target_id` con `target_type='event'`. El borrado SHALL ejecutarse ordenando los candidatos por `created_at` descendente (más nuevos primero), de modo que un evento hijo se elimine antes que el padre al que referencia y nunca quede una referencia colgante; combinado con la FK `ON DELETE SET NULL` sobre `parent_event_id`, la operación MUST completar sin `IntegrityError` incluso en cadenas largas (C9). La eliminación SHALL ocurrir en la misma transacción de base de datos que la creación del nuevo evento (RN-98).

#### Scenario: Cadena bajo 10 no desencadena compactación
- **WHEN** existen 8 eventos `superseded` para un path y se marca el 9no
- **THEN** no se elimina ningún evento

#### Scenario: Cadena llega a 11 — se compacta a 10
- **WHEN** existen 10 eventos `superseded` para un path y se marca el 11mo
- **THEN** se elimina el `superseded` sobrante que no esté referenciado en `audit_log`
- **AND** la cadena queda con exactamente 10 eventos `superseded`

#### Scenario: Compactación de cadena larga no viola la FK
- **WHEN** se compacta una cadena donde los eventos a borrar son `parent_event_id` de otros eventos de la cadena
- **THEN** el borrado completa sin `IntegrityError`
- **AND** `ingest_event` no aborta su transacción ni pierde el nuevo evento

#### Scenario: Compactación respeta referencias en audit_log
- **WHEN** el `superseded` candidato a borrar tiene su `id` en `audit_log.target_id`
- **THEN** no se elimina ese evento
- **AND** se elimina el siguiente candidato que no esté referenciado
