## ADDED Requirements

### Requirement: El filtro path_prefix es un prefijo literal

El filtro `path_prefix` de `GET /events` SHALL compararse como prefijo literal y case-sensitive de `Event.path`: los caracteres `%`, `_` y `\` del valor recibido MUST escaparse antes de construir el `LIKE`, de modo que nunca actúen como comodines (D91/RN-185). El conteo `total` MUST usar el mismo filtro escapado.

#### Scenario: Un porcentaje no matchea todo
- **WHEN** existen eventos con `path="/etc/passwd"` y `path="/var/www/index.html"`
- **AND** se hace `GET /events?path_prefix=%`
- **THEN** `items` está vacío y `total == 0`

#### Scenario: Un guion bajo es literal
- **WHEN** existen eventos con `path="/srv/a_b/x"` y `path="/srv/axb/x"`
- **AND** se hace `GET /events?path_prefix=/srv/a_b`
- **THEN** `items` contiene sólo el evento de `/srv/a_b/x`

#### Scenario: Un prefijo normal sigue funcionando
- **WHEN** se hace `GET /events?path_prefix=/etc/`
- **THEN** `items` contiene sólo eventos cuyo `path` empieza con `/etc/`
