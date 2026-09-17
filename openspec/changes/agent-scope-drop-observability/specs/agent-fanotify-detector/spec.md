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

## MODIFIED Requirements

### Requirement: Eventos con path nulo se descartan

El detector SHALL descartar el evento y MUST NOT generar ningún cambio ni tocar el baseline si
`ev.path` es `None` (el backend fanotify no pudo resolver el handle del kernel a un path) (RN-110,
D12). El log por evento `detector.event_null_path` SHALL emitirse a nivel **`debug`**, no `warning`
(D74/RN-168) — el mismo mecanismo de nivel que D69/RN-163 aplicó a `detector.out_of_scope_drop`,
pero por un motivo distinto: el chequeo de path nulo corre **antes** del filtro de scope (que
necesita un path para decidir), así que un evento con path nulo NO tiene la exterioridad confirmada
que sí tiene un descarte fuera de scope. El agente SHALL mantener un contador acumulativo
`null_path_drops`, incrementado exactamente una vez por evento con `ev.path is None`, expuesto como
property pública del detector, y SHALL publicarlo en cada heartbeat junto a `out_of_scope_drops` y
`event_drops`. A diferencia de `out_of_scope_drops` (D69/RN-163), un valor positivo de
`null_path_drops` MUST NOT presentarse como ruido esperado: se documenta como posible brecha de
cobertura, porque el detector no puede determinar si el objeto perdido caía dentro de un
`watch_path`. Esta decisión es estrictamente de agente: no persiste el contador en el backend ni lo
presenta en el frontend (D74/RN-168).

#### Scenario: Evento sin path resoluble se descarta sin emitir warning

- **WHEN** el backend fanotify entrega un evento cuyo path no puede resolverse vía
  `open_by_handle_at(2)`
- **THEN** el detector no emite ningún log de nivel `warning` ni superior para ese descarte
- **AND** emite el log `detector.event_null_path` a nivel `debug` con el `pid` del evento y el total
  acumulado
- **AND** no produce ningún cambio ni toca el baseline

#### Scenario: El contador de path nulo se incrementa por evento descartado

- **WHEN** el detector descarta dos eventos consecutivos con `ev.path is None`
- **THEN** `null_path_drops` vale 2

#### Scenario: El contador de path nulo viaja en el heartbeat

- **WHEN** el detector acumuló descartes por path nulo y se publica un heartbeat
- **THEN** el payload del heartbeat incluye `null_path_drops` con el valor acumulado
