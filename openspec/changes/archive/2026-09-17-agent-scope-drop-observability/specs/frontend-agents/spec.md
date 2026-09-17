## ADDED Requirements

### Requirement: La tarjeta del agente muestra los descartes fuera de scope como contador informativo

La tarjeta del agente SHALL mostrar el contador de eventos que el agente descartó por caer fuera de
los `watch_paths`, junto a la presión de cola que ya expone. El contador SHALL presentarse como
**informativo**: un valor positivo es esperado y normal —la marca de fanotify cubre el filesystem
completo, así que toda escritura ajena al alcance del agente produce un descarte— y SHALL NOT recibir
tratamiento visual de anomalía (D69/RN-163).

La presentación SHALL ser **neutra** y explícitamente distinguible de la de los descartes locales
(`discarded_events`, D37/RN-131), que sí resalta anomalía porque allí un positivo es una detección
perdida. El indicador MUST NOT usar la paleta de alarma en ninguno de sus estados. Presentar los dos
contadores con el mismo énfasis le enseñaría al operador a ignorar un indicador rojo, que es
exactamente cómo se pierde una alerta real.

La presentación SHALL distinguir tres estados, igual que los otros contadores del agente: nunca
reportado, reportado como cero, y un valor positivo. Nunca reportado MUST NOT renderizarse como cero
(RN-71, RN-92).

#### Scenario: Un valor positivo se muestra con tratamiento neutro

- **WHEN** el agente reporta 2748492 descartes fuera de scope
- **THEN** la tarjeta muestra el conteo con el tratamiento visual neutro de la telemetría de rutina
- **AND** no usa el tratamiento de anomalía reservado para los descartes locales

#### Scenario: El valor positivo se explica al operador

- **WHEN** el operador consulta la descripción del indicador con un valor positivo
- **THEN** la descripción dice que los descartes fuera de scope son esperados y que el contador es la
  evidencia de que el filtro de scope está funcionando

#### Scenario: Cero se muestra como cero

- **WHEN** el agente reporta 0 descartes fuera de scope
- **THEN** la tarjeta muestra el valor cero con el mismo tratamiento neutro

#### Scenario: Un agente que nunca reportó no se muestra como cero

- **WHEN** el agente no tiene un contador de descartes fuera de scope reportado
- **THEN** la tarjeta indica que el valor es desconocido en vez de mostrar cero

#### Scenario: Los dos contadores conviven y se distinguen

- **WHEN** el agente reporta a la vez descartes locales positivos y descartes fuera de scope
  positivos
- **THEN** la tarjeta muestra los dos indicadores con tratamientos visuales distintos entre sí

### Requirement: La presentación de los descartes fuera de scope es un mapper puro propio

El mapeo del contador crudo de descartes fuera de scope a su forma presentada SHALL vivir en una
función pura bajo `frontend/src/utils/`, con su propio test unitario que cubra los tres estados,
siguiendo el patrón que ya establecieron los mappers de estado y error existentes. El componente
SHALL consumir esa función en vez de ramificar en línea.

El mapper SHALL ser **propio y separado** del de los descartes locales: los dos difieren justo en el
eje que D69/RN-163 exige mantener distinguible —en uno el positivo es una anomalía, en el otro es lo
esperado—, de modo que compartirlos mediante un parámetro acoplaría dos presentaciones que deben
poder evolucionar por separado. El mapper MUST NOT lanzar excepciones (RN-71).

#### Scenario: El mapper cubre los tres estados

- **WHEN** se invoca el mapper con un número positivo, con cero y con un valor nulo o indefinido
- **THEN** retorna tres resultados distintos y nunca lanza

#### Scenario: El mapper es independiente del de descartes locales

- **WHEN** se comparan las presentaciones que los dos mappers producen para el mismo valor positivo
- **THEN** difieren en el tratamiento visual, y cada mapper está definido en su propio módulo

#### Scenario: El componente no duplica la ramificación

- **WHEN** la tarjeta del agente renderiza el contador de descartes fuera de scope
- **THEN** deriva la presentación del mapper y no de condicionales en línea
