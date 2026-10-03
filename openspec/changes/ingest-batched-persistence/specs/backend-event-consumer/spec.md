## MODIFIED Requirements

### Requirement: Piso de rendimiento de la ingesta y INSERT por lote condicional

El carril de ingesta SHALL sostener al menos 95 eventos por segundo, con objetivo de 150 (D87/RN-181).
Con el caché de autenticación y el ACK por lote, el laboratorio midió 76,6 ev/s sobre `v5.0-tesis`
(diagnóstico del 2026-10-03). La ampliación del 2026-10-03 de D87/RN-181, revisada tras medir,
atribuye la caída a la construcción de un cliente HTTP con su contexto SSL por cada entrega de
notificación. Por eso las optimizaciones SHALL adoptarse en este orden:

- **Fase A, obligatoria.** El cliente HTTP de larga vida del carril de notificación (requisito «Las
  entregas HTTP del carril de notificación reutilizan un cliente de larga vida» de
  `backend-notifications`).
- **Fase B, condicional.** Sólo si con la fase A el banco de desarrollo no alcanza el umbral de
  abajo: la persistencia de los eventos validados de un lote en una única transacción por lote. Debe
  preservar:
  - el orden FIFO de inserción;
  - la cadena `superseded`, incluido el caso en que dos eventos del mismo lote afectan la misma ruta;
  - el dedup idempotente por `event_id`, en la base y dentro del lote;
  - que un error transitorio deje todo el lote en la PEL.

  MUST NOT introducir concurrencia entre eventos del lote (D75/RN-169).
- **Dentro de la fase B, y sólo si tampoco alcanza el umbral,** la creación de la fila `Alert` en
  esa transacción (enmienda condicional de D76/RN-170).

Antes de etiquetar `v5.1-tesis`, el banco de desarrollo `lab/bench_ingest_consumer.py` SHALL medir,
con la cadena de notificación **sin stub**, al menos 1,5 veces su línea base sin stub en el mismo
host. Sin stub significa:

- reglas que hacen alertar a cada evento;
- un sumidero HTTP local que persiste una fila por pedido en otra base de la misma instancia de
  PostgreSQL;
- rutas repetidas como el generador de carga.

La línea base registrada es 62,0 ev/s, así que el umbral es ≥93 ev/s.

Si la fase A alcanza el umbral, la fase B MUST NOT implementarse y SHALL registrarse como no
necesaria, con su medición. Si la fase B se adopta, su delta de requisitos SHALL escribirse en la
change antes del código.

El piso de laboratorio SHALL medirse en la Batería 5 del arnés unificado sobre `v5.1-tesis`, como
ventana de consumo entre el primer y el último `received_at` de los eventos drenados. Las
mediciones de desarrollo, antes y después de cada fase, y las decisiones sobre la fase B y su paso
condicional SHALL quedar registradas en la change. El resultado del laboratorio SHALL registrarse
tal como se mida, sin declarar una mejora antes de medirla.

#### Scenario: La fase A alcanza el umbral de desarrollo
- **WHEN** el banco de desarrollo sin stub mide con la fase A al menos 1,5 veces su línea base sin stub en el mismo host
- **THEN** la persistencia por lote no se implementa
- **AND** la change registra ambas mediciones y la decisión

#### Scenario: La fase A no alcanza el umbral de desarrollo
- **WHEN** el banco de desarrollo sin stub mide con la fase A menos de 1,5 veces su línea base sin stub
- **THEN** se adopta la persistencia de los eventos validados de un lote en una única transacción, con su delta de requisitos escrito antes del código
- **AND** dos eventos válidos consecutivos de la misma ruta en un lote, sin pending previo, dejan al primero `superseded` y al segundo `pending` con `parent_event_id` igual al id del primero

#### Scenario: La ventana de consumo de la Batería 5 se registra
- **WHEN** la Batería 5 drena el stream tras restaurar Valkey
- **THEN** registra el ritmo como la cantidad de eventos drenados dividida por la diferencia entre el último y el primer `received_at`
