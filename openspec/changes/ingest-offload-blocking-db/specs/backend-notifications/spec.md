## MODIFIED Requirements

### Requirement: Notificación asincrónica post-ingesta de eventos críticos o altos

El sistema SHALL disparar una notificación asincrónica no bloqueante (`asyncio.create_task`) tras
persistir exitosamente un evento en DB. La notificación MUST evaluarse solo para eventos con
`status != superseded` (RN-22). La severidad SHALL determinarse buscando en la tabla `rules` las
reglas cuyo `pattern` (glob) matchee el `event.path` usando `fnmatch.fnmatch`; si hay matches, se usa
la severidad más alta; si no hay matches, se usa `low`. La notificación solo se envía si la severidad
resultante es `critical` o `high` (RN-52).

"No bloqueante" SHALL entenderse en sentido estricto: ninguna operación síncrona a PostgreSQL del
camino de notificación **por evento** MUST ejecutarse sobre el event loop (D75/RN-169, que extiende
D21 a todo camino que abra una `Session` síncrona dentro de una corrutina). Esto alcanza tanto a la
`Session` con la que se crea la fila `Alert` como a las `Session` del camino de entrega y de la
marca de entregado. Todas ellas MUST ejecutarse via
`asyncio.get_running_loop().run_in_executor(None, fn, *args)`; las funciones síncronas NO deben
convertirse en async — solo cambia el call site.

El fundamento es medido y no se puede sustituir por una versión parcial: la cadena de notificación
completa cuesta unos 5,7 ms por evento entre la creación de la alerta y su entrega, y corre en
**todos** los eventos cuando las reglas vigentes los clasifican `high` o `critical`. Desbloquear
únicamente la creación de la fila `Alert` dejaría el resto de la cadena frenando el event loop y
anularía el solapamiento que la corrutina fire-and-forget existe para habilitar: mientras la
notificación de un evento previo ocupa el loop, el consumer no puede despachar el evento siguiente.

Las `Session` de los caminos que NO corren por evento —la recuperación de notificaciones pendientes
del arranque— quedan fuera de esta obligación: su costo no participa del carril de ingesta.

#### Scenario: Evento critical o high dispara notificación
- **WHEN** se ingiere un evento cuyo path matchea una regla con `severity=critical`
- **THEN** se crea una fila en `alerts` con `severity=critical` y se intenta el envío al canal primario

#### Scenario: Evento con severidad low o medium no notifica
- **WHEN** se ingiere un evento cuyo path matchea solo reglas con `severity=low` o `severity=medium`
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Evento sin regla matching no notifica
- **WHEN** se ingiere un evento cuyo path no matchea ninguna regla
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Evento superseded no notifica
- **WHEN** se ingiere un evento que resulta en `status=superseded`
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Notificación no bloquea el consumer
- **WHEN** el envío del webhook n8n tarda 5 segundos
- **THEN** el consumer procesa el siguiente evento de Valkey sin esperar al webhook

#### Scenario: La creación de la fila de alerta no bloquea el event loop
- **WHEN** la notificación crea la fila `alerts` correspondiente a un evento recién persistido
- **THEN** la sesión, el alta y el commit se ejecutan en un hilo del executor y no sobre el event loop
- **AND** el estado publicado al broadcaster SSE y el payload canónico de notificación no cambian

#### Scenario: La actualización del estado de entrega no bloquea el event loop
- **WHEN** la notificación registra el resultado de un intento de entrega sobre la fila `alerts`
  (entregada, con canal y contador de reintentos, o fallida con su último error)
- **THEN** la sesión y el commit correspondientes se ejecutan en un hilo del executor y no sobre el
  event loop
- **AND** la cascada de canales y la política de reintentos conservan exactamente su comportamiento
  previo

#### Scenario: El despacho del consumer avanza mientras una notificación previa está en curso
- **WHEN** el consumer despacha un evento mientras la cadena de notificación de un evento anterior
  está resolviendo su trabajo de base de datos
- **THEN** ninguna de las dos espera a que la otra libere el event loop

#### Scenario: La recuperación de notificaciones pendientes del arranque queda fuera de alcance
- **WHEN** el backend arranca y recupera las notificaciones pendientes
- **THEN** ese camino conserva su implementación actual, por correr una sola vez y fuera del carril
  de ingesta
