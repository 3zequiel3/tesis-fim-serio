## ADDED Requirements

### Requirement: EventOut expone el motivo del fallo del último comando

`EventOut` (lista, detalle y cadena) SHALL incluir `ack_error: str | null`, tomado del mismo `PublishedCommand` del que sale `ack_status` (el más reciente asociado al evento con `ack_status` no nulo) y truncado a 200 caracteres. MUST ser `null` cuando `ack_status` es `null`, `pending`, `acked` o `timeout`, o cuando el comando no tiene `error`. La consulta MUST reutilizar la que arma `ack_status`, sin una consulta adicional por evento (D93/RN-187).

#### Scenario: Comando fallido con motivo
- **WHEN** el último comando de un evento tiene `ack_status = failed` y `error = "no_restorable_content"`
- **THEN** `GET /events/{id}` devuelve `ack_status = "failed"` y `ack_error = "no_restorable_content"`

#### Scenario: Comando confirmado sin motivo
- **WHEN** el último comando de un evento tiene `ack_status = acked`
- **THEN** `ack_error` es `null`

#### Scenario: Motivo largo truncado
- **WHEN** el `error` del comando tiene 500 caracteres
- **THEN** `ack_error` tiene 200 caracteres

#### Scenario: Sin consultas por evento
- **WHEN** se lista una página de 50 eventos
- **THEN** la cantidad de consultas SQL no crece con la cantidad de eventos de la página
