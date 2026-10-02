## MODIFIED Requirements

### Requirement: Rate limiting 100 eventos/min por agent_id en el consumer

El consumer SHALL limitar la ingesta de eventos nuevos con un **token bucket por `agent_id`**, en
memoria (D85/RN-179). Cada `agent_id` tiene un balde de capacidad `burst` que se rellena de forma
continua a `rate_per_s` tokens por segundo, sin superar nunca la capacidad; un evento nuevo admitido
consume exactamente un token, y un evento sin token disponible excede el límite. Los defaults del
producto SHALL ser un régimen sostenido de 100 eventos por minuto (`rate_per_s = 100/60`) y una
ráfaga de 3.000 eventos (`burst = 3000`), elegida para cubrir el replay de 2.672 eventos de la
batería 5 con margen. Un `agent_id` sin estado previo SHALL comenzar con el balde lleno. El balde de
un agente MUST NOT verse afectado por los eventos de otro.

El check de rate limit se ejecuta DESPUÉS del dedup — re-entregas de eventos ya procesados NO
consumen tokens. Solo los eventos genuinamente nuevos (que superan el dedup) avanzan al check de
rate. Si excede el límite: ejecutar `XACK`, insertar en `rejected_events_audit` con
`reason=rate_limited`, **publicar un `event_nack` con `reason=rate_limited` y `retry_after`**
(D37/RN-131), y NO procesar el evento. El evento **NO se descarta**: el agente lo retiene y lo
reenvía cuando haya presupuesto — esta cláusula prevalece sobre la frase "se descartan con alerta"
de RN-88, que además nunca se implementó. El estado de los baldes SHALL reiniciarse al reiniciar el
backend (no persiste en Valkey). El limiter SHALL exponer `reset_rate_limiter()` para facilitar tests
y un método explícito que devuelva los segundos restantes hasta que haya un token disponible para un
`agent_id`, usado para derivar `retry_after` (RN-88, D7, D37, D85).

#### Scenario: Evento con tokens disponibles pasa el rate check
- **WHEN** el balde de `agent_a1` tiene al menos un token
- **AND** llega un nuevo evento de `agent_a1` que no existe en DB (no es re-entrega)
- **THEN** el evento pasa el rate check, consume un token y continúa la validación normal

#### Scenario: Una ráfaga de hasta 3.000 eventos se admite con el balde lleno
- **WHEN** `agent_a1` no tiene estado previo en el limiter
- **AND** llegan 3.000 eventos nuevos de `agent_a1` sin que transcurra tiempo entre ellos
- **THEN** los 3.000 eventos pasan el rate check
- **AND** el evento 3.001, en el mismo instante, excede el límite

#### Scenario: El régimen sostenido se limita a 100 eventos por minuto
- **WHEN** el balde de `agent_a1` está vacío
- **AND** `agent_a1` ofrece eventos nuevos de forma continua durante 10 minutos
- **THEN** se admiten 1.000 eventos en esos 10 minutos, con una tolerancia de un evento
- **AND** el resto excede el límite

#### Scenario: El relleno nunca supera la capacidad del balde
- **WHEN** `agent_a1` vació su balde y luego permanece inactivo durante 2 horas
- **THEN** su balde vuelve a tener exactamente 3.000 tokens, no más

#### Scenario: Los baldes de agentes distintos son independientes
- **WHEN** `agent_a1` vació su balde
- **AND** llega un evento nuevo de `agent_a2` sin estado previo
- **THEN** el evento de `agent_a2` pasa el rate check
- **AND** `agent_a2` conserva 2.999 tokens

#### Scenario: Evento que excede el límite es auditado y nackeado con retry_after
- **WHEN** el balde de `agent_a1` no tiene un token disponible
- **AND** llega un evento de `agent_a1` con un `event_id` nuevo (no re-entrega)
- **THEN** el consumer ejecuta `XACK`
- **AND** inserta en `rejected_events_audit` con `reason=rate_limited` y `agent_id='a1'`
- **AND** publica un `event_nack` con `reason=rate_limited` y un `retry_after` numérico positivo
- **AND** NO persiste el `Event`

#### Scenario: Re-entrega no consume tokens
- **WHEN** al balde de `agent_a1` le queda exactamente un token
- **AND** llega de nuevo el evento `e1` que ya existe en DB (re-entrega legítima)
- **THEN** el balde de `agent_a1` conserva ese token
- **AND** el evento `e1` es procesado como dedup (XACK + event_ack)

#### Scenario: Un evento rate-limited reenviado más tarde se ingesta
- **WHEN** un evento fue rechazado por rate limit y el agente lo reenvía una vez que hay un token
- **THEN** el evento se persiste normalmente y recibe `event_ack`

#### Scenario: reset_rate_limiter limpia el estado
- **WHEN** se llama `reset_rate_limiter()`
- **THEN** todos los agentes vuelven a no tener estado y su próximo evento encuentra el balde lleno

### Requirement: retry_after is derived from the live rate limiter state

El consumer SHALL derivar el `retry_after` del `event_nack` de `rate_limited` del estado vivo del
token bucket del agente, no de una constante: el tiempo hasta que el balde acumule el token que le
falta, `(1 − tokens) / rate_per_s` (D85/RN-179). Con los defaults del producto ese valor no supera
0,6 s. El valor SHALL tener un piso positivo pequeño (0,5 s) para que un resultado cero o negativo
por una carrera no induzca un busy-loop en el agente. Si el agente tiene al menos un token, o no tiene
estado, el método SHALL devolver `0.0`.

El limiter SHALL exponer esto como un método explícito. El consumer MUST NOT leer el estado interno
del limiter. (D37 / RN-131, RN-88, D85 / RN-179)

#### Scenario: Un agente que acaba de vaciar el balde espera el intervalo de un token
- **WHEN** el balde de un agente tiene 0 tokens con el régimen de 100 eventos por minuto
- **THEN** el `retry_after` del nack es de 0,6 segundos

#### Scenario: Un agente con un token casi completo espera el piso
- **WHEN** el balde de un agente tiene 0,9 tokens con el régimen de 100 eventos por minuto
- **THEN** el `retry_after` del nack es el piso de 0,5 segundos

#### Scenario: El retry_after acompaña la tasa configurada
- **WHEN** la tasa configurada es de 0,1 tokens por segundo y el balde del agente tiene 0 tokens
- **THEN** el `retry_after` del nack es de 10 segundos

#### Scenario: retry_after is never zero or negative
- **WHEN** el remanente calculado es cero o negativo
- **THEN** el `retry_after` emitido es el mínimo positivo configurado

#### Scenario: Sin déficit no hay espera
- **WHEN** el agente tiene al menos un token, o no tiene estado en el limiter
- **THEN** el método devuelve `0.0`

## ADDED Requirements

### Requirement: Configuración del límite de ingesta y advertencia por settings heredados

El backend SHALL leer el límite de ingesta de dos settings (D85/RN-179):
`rate_limit_ingest_rate_per_s` (variable `RATE_LIMIT_INGEST_RATE_PER_S`, número real estrictamente
positivo, default `100/60`) y `rate_limit_ingest_burst` (variable `RATE_LIMIT_INGEST_BURST`, entero
mayor o igual a 1, default `3000`). Un valor fuera de rango MUST hacer fallar el arranque con un
error de validación. El limiter construido sin argumentos SHALL tomar ambos valores de la
configuración.

Los settings `rate_limit_ingest_events` y `rate_limit_ingest_window_seconds` SHALL NOT existir. Si
`RATE_LIMIT_INGEST_EVENTS` o `RATE_LIMIT_INGEST_WINDOW_SECONDS` tienen un valor no vacío en el
entorno del proceso o en el archivo `.env` que lee la configuración, el arranque del backend SHALL
registrar una única advertencia que nombre las variables ignoradas y sus reemplazos, y SHALL
continuar. Esos valores MUST NOT influir en el límite efectivo.

#### Scenario: Los defaults del producto son 100 eventos por minuto y ráfaga de 3.000
- **WHEN** el backend arranca sin `RATE_LIMIT_INGEST_RATE_PER_S` ni `RATE_LIMIT_INGEST_BURST`
- **THEN** el limiter usa una tasa de 100/60 tokens por segundo y una capacidad de 3.000 tokens

#### Scenario: El limiter respeta la configuración
- **WHEN** `RATE_LIMIT_INGEST_BURST=3` y `RATE_LIMIT_INGEST_RATE_PER_S=0.5`
- **THEN** un agente sin estado puede enviar 3 eventos nuevos en el mismo instante y el cuarto excede el límite
- **AND** el `retry_after` de ese cuarto evento es de 2 segundos

#### Scenario: Un valor fuera de rango impide arrancar
- **WHEN** `RATE_LIMIT_INGEST_RATE_PER_S=0` o `RATE_LIMIT_INGEST_BURST=0`
- **THEN** la carga de la configuración falla con un error de validación

#### Scenario: Una variable heredada produce una advertencia y no tiene efecto
- **WHEN** el entorno del backend define `RATE_LIMIT_INGEST_EVENTS=100000`
- **THEN** el arranque registra una advertencia que nombra `RATE_LIMIT_INGEST_EVENTS` y los reemplazos `RATE_LIMIT_INGEST_RATE_PER_S` y `RATE_LIMIT_INGEST_BURST`
- **AND** el backend arranca
- **AND** el limiter usa los valores de `rate_limit_ingest_rate_per_s` y `rate_limit_ingest_burst`

#### Scenario: Una variable heredada vacía no produce advertencia
- **WHEN** el entorno define `RATE_LIMIT_INGEST_EVENTS` con valor vacío y no define `RATE_LIMIT_INGEST_WINDOW_SECONDS`
- **THEN** el arranque no registra la advertencia
