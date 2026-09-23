## MODIFIED Requirements

### Requirement: Dimensionamiento conjunto y explícito del pool de conexiones y del executor

El engine de base de datos y los executors de hilos del backend MUST dimensionarse **en conjunto y de
forma explícita**, nunca por los defaults implícitos de la librería (D75/RN-169, D76/RN-170). Mover
trabajo bloqueante a un executor sin acotar el pool cambia un cuello de botella por **agotamiento de
conexiones**, que además falla en vez de degradar.

El engine SHALL construirse con `pool_size`, `max_overflow` y `pool_timeout` explícitos.

El backend SHALL instalar **dos** executors de hilos propios, con presupuestos separados y explícitos
(D76/RN-170):

- Un **executor de ingesta**, instalado como executor por defecto del event loop. Todo
  `run_in_executor(None, ...)` del proceso tira de él.
- Un **executor de notificación**, exclusivo del camino de notificación por evento, referenciado
  **explícitamente** por sus call sites.

Los dos executors MUST tener conjuntos de hilos **disjuntos**. Ningún trabajo del camino de
notificación SHALL poder ocupar un hilo del executor de ingesta, y esa propiedad MUST sostenerse por
construcción —porque los call sites de notificación nombran su executor— y no por convención de uso.
Un call site del camino de notificación que pase `None` MUST considerarse un defecto: `None` designa
el executor de ingesta.

El carril de ingesta MUST NOT ceder capacidad para financiar este aislamiento: el número de hilos de
su executor SHALL permanecer al menos igual al vigente antes de introducir el segundo executor.

`pool_size`, `max_overflow` y el número máximo de hilos de **cada** executor MUST ser configurables
por entorno a través de `Settings`, con valores por defecto que reproduzcan el dimensionamiento
documentado.

La **suma** de los hilos de los dos executors MUST ser menor o igual que `pool_size + max_overflow`
descontando las conexiones reservadas para las dependencias HTTP de FastAPI, para el consumer de
heartbeat y para las corrutinas del lifespan que abren `Session` fuera de los executors:

```
hilos_executor_ingesta + hilos_executor_notificacion
    ≤ pool_size + max_overflow − reserva_no_executor
```

El invariante SHALL expresarse como **una sola desigualdad sobre la suma**, NO como dos desigualdades
independientes: los dos pools de hilos tiran del mismo pool de conexiones, y dos condiciones
separadas admitirían una configuración donde cada executor cabe por su cuenta y juntos agotan el
pool.

La reserva de conexiones no destinadas a los executors SHALL ser una constante documentada del
código, NO un parámetro configurable: permitir ajustarla habilitaría desactivar el invariante que
esta regla existe para sostener.

El arranque del backend MUST abortar con error de validación si la configuración viola ese
invariante, con el mismo criterio fail-fast que el resto de `Settings`. El mensaje de error SHALL
nombrar los valores en juego, la reserva, el máximo permitido y la suma recibida. Un dimensionamiento
capaz de agotar el pool MUST NOT descubrirse bajo carga.

Los dos executors SHALL cerrarse ordenadamente en el shutdown, esperando a sus hilos en vuelo,
**después** de la cancelación y recolección de las tasks del lifespan. El executor de notificación
SHALL cerrarse antes que el de ingesta: es el que puede tener trabajo pendiente más tarde en el ciclo
de vida.

El backend MUST NOT escalar horizontalmente para resolver este problema: sigue siendo single-instance
(RN-76).

#### Scenario: El engine se construye con pool explícito

- **WHEN** el backend crea el engine de base de datos
- **THEN** `pool_size`, `max_overflow` y `pool_timeout` provienen de valores explícitos y no de los
  defaults de la librería

#### Scenario: El executor de ingesta es el executor por defecto del loop

- **WHEN** el backend completa su arranque
- **THEN** existe un executor de hilos propio del proceso, con su número máximo de hilos tomado de la
  configuración, instalado como executor por defecto del event loop
- **AND** los call sites que ya usaban el executor por defecto pasan a tirar de ese mismo presupuesto
  sin ser modificados

#### Scenario: El executor de notificación es distinto y se referencia explícitamente

- **WHEN** el backend completa su arranque
- **THEN** existe un segundo executor de hilos, con su propio número máximo tomado de la
  configuración, que NO es el executor por defecto del loop
- **AND** los call sites del camino de notificación por evento lo referencian explícitamente en lugar
  de pasar `None`

#### Scenario: El trabajo de notificación no puede ocupar un hilo del carril de ingesta

- **WHEN** el camino de notificación ejecuta cualquiera de sus operaciones de base de datos
- **THEN** la ejecución ocurre en un hilo del executor de notificación
- **AND** ningún hilo del executor de ingesta queda ocupado por ella

#### Scenario: El carril de ingesta no pierde capacidad

- **WHEN** se compara el dimensionamiento del executor de ingesta con el vigente antes de introducir
  el segundo executor
- **THEN** su número de hilos no disminuyó

#### Scenario: La suma de los dos executors se valida contra la capacidad del pool

- **WHEN** se configura una combinación cuyos dos executors caben por separado pero cuya suma excede
  la capacidad del pool menos las conexiones reservadas
- **THEN** el arranque falla con un error de validación antes de aceptar tráfico

#### Scenario: Una configuración que puede agotar el pool aborta el arranque

- **WHEN** se configura un número de hilos mayor que la capacidad del pool menos las conexiones
  reservadas
- **THEN** el arranque falla con un error de validación antes de aceptar tráfico

#### Scenario: Valores fuera de dominio abortan el arranque

- **WHEN** se configura un `pool_size` menor que 1, un `max_overflow` negativo o un número de hilos
  menor que 1 en cualquiera de los dos executors
- **THEN** el arranque falla con un error de validación

#### Scenario: Los dos executors se cierran ordenadamente en el shutdown

- **WHEN** el backend recibe señal de apagado
- **THEN** los dos executors se cierran esperando a sus hilos en vuelo, después de la cancelación de
  las tasks del lifespan
- **AND** el executor de notificación se cierra antes que el de ingesta

#### Scenario: Un despliegue sin configuración explícita arranca con el dimensionamiento documentado

- **WHEN** el entorno no declara ninguna de las variables de dimensionamiento
- **THEN** el backend arranca con los valores por defecto documentados y el invariante se cumple

#### Scenario: La reserva de conexiones no es configurable

- **WHEN** se inspecciona la configuración expuesta por entorno
- **THEN** la reserva de conexiones no destinadas a los executors no figura entre los parámetros
  ajustables
