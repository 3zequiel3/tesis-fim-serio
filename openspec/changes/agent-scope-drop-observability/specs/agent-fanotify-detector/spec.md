## ADDED Requirements

### Requirement: El descarte fuera de scope se registra a nivel debug y se agrega en un contador

El detector SHALL emitir el log por ruta descartada `detector.out_of_scope_drop` a nivel **`debug`**,
no a nivel `warning` (D69/RN-163). La marca de fanotify cubre el filesystem completo en modo FID
(D46/RN-140), de modo que **toda** escritura del host fuera de los `watch_paths` produce un descarte:
el descarte es el caso normal, no una anomalía, y un `warning` por ruta inunda el journal y sepulta
los eventos de integridad que el sistema existe para mostrar.

El contador acumulativo `out_of_scope_drops` SHALL seguir incrementándose exactamente una vez por
evento descartado, SHALL seguir expuesto como property pública del detector y SHALL seguir
publicándose en cada heartbeat. El cambio de nivel MUST NOT alterar el filtro de scope, el criterio
de descarte ni el contrato del heartbeat: el agente cambia el nivel al que habla, no lo que publica.

Un valor positivo del contador SHALL considerarse esperado y normal: es la evidencia de que el
filtro de scope está funcionando, no la señal de una pérdida. La distinción con `discarded_events`
(D37/RN-131) es deliberada — allí un positivo **es una detección perdida** (RN-04, RN-71).

#### Scenario: Una escritura fuera de scope no emite warning

- **WHEN** un proceso escribe un archivo en un directorio no configurado en `watch_paths` y el
  detector recibe el evento del kernel
- **THEN** el detector no emite ningún log de nivel `warning` ni superior para ese descarte
- **AND** emite el log `detector.out_of_scope_drop` a nivel `debug` con la ruta descartada y el total
  acumulado

#### Scenario: El contador sigue incrementándose con el nivel bajado

- **WHEN** el detector descarta dos eventos consecutivos por caer fuera de `watch_paths`
- **THEN** `out_of_scope_drops` vale 2

#### Scenario: El contador sigue viajando en el heartbeat

- **WHEN** el detector acumuló descartes fuera de scope y se publica un heartbeat
- **THEN** el payload del heartbeat incluye `out_of_scope_drops` con el valor acumulado

#### Scenario: El filtro de scope no cambia

- **WHEN** un proceso escribe un archivo en un directorio no configurado en `watch_paths`
- **THEN** el detector no produce ningún evento de cambio, igual que antes del cambio de nivel
