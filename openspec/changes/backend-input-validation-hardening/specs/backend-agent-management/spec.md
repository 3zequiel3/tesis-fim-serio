## MODIFIED Requirements

### Requirement: POST /agents/{id}/config — actualizar watch_paths y publicar update_config

El sistema SHALL exponer `POST /agents/{id}/config` (requiere JWT admin) que acepta `{watch_paths: list[str]}`. MUST validar `watch_paths` según D91/RN-185 antes de cualquier escritura, incremento de `ruleset_version` o publicación: la lista MUST tener entre 1 y 64 entradas; cada entrada MUST empezar con `/`, MUST NOT contener un segmento `..` ni caracteres de control (U+0000–U+001F y U+007F) y MUST medir a lo sumo 1.024 caracteres; dos entradas MUST NOT ser iguales una vez quitada la barra final (salvo la raíz `/`). La existencia de la ruta MUST NOT verificarse en el backend: la reporta el agente en `watch_path_status` (D36/RN-130). Cada rechazo MUST responder `422` con `detail` `{"code": <código>, "message": <texto en español>}` (D90/RN-184): `watch_paths_empty`, `watch_paths_too_many`, y, para una entrada, `watch_path_not_absolute`, `watch_path_parent_segment`, `watch_path_control_char`, `watch_path_too_long` y `watch_path_duplicate`, éstos con el campo `index` (posición, desde 0) de la primera entrada rechazada. Con una lista válida, MUST persistir los nuevos `watch_paths` en DB (replace-all), incrementar `ruleset_version` (D5), publicar el comando `update_config` HMAC-signed al stream `commands` de Valkey con `target_agent_id` y la lista de paths, y registrar en `audit_log`. Si el agente no existe SHALL retornar `404`.

El campo `detail` del registro `audit_log` de esta operación MUST ser JSON válido, serializado con `json.dumps(...)` (comillas dobles, escape correcto), y no una interpolación f-string sobre `str(list)`. El `detail` MUST permanecer JSON válido aunque algún path contenga caracteres especiales como comillas dobles (`"`) o barras invertidas (`\`).

#### Scenario: Config actualizado y comando publicado
- **WHEN** un admin hace `POST /agents/agent-01/config` con `watch_paths=["/etc"]`
- **THEN** la respuesta es `200 OK`
- **AND** `agents.watch_paths` es `["/etc"]` en DB
- **AND** se publicó el mensaje `update_config` en el stream `commands` con `target_agent_id="agent-01"` y `watch_paths=["/etc"]`
- **AND** el mensaje tiene `signature` verificable con HMAC-SHA256 y el `shared_secret` del agente

#### Scenario: watch_paths vacío es rechazado
- **WHEN** el admin envía `watch_paths=[]`
- **THEN** la respuesta es `422` con `detail.code == "watch_paths_empty"`
- **AND** `agents.watch_paths`, `ruleset_version` y el stream `commands` no cambian

#### Scenario: Más de 64 rutas
- **WHEN** el admin envía 65 rutas absolutas distintas
- **THEN** la respuesta es `422` con `detail.code == "watch_paths_too_many"`

#### Scenario: Ruta relativa con su posición
- **WHEN** el admin envía `watch_paths=["/etc", "var/www"]`
- **THEN** la respuesta es `422` con `detail.code == "watch_path_not_absolute"` y `detail.index == 1`

#### Scenario: Segmento de directorio padre o caracteres de control
- **WHEN** el admin envía `watch_paths=["/srv/../etc"]` o una ruta con `\n`
- **THEN** la respuesta es `422` con `detail.code` `watch_path_parent_segment` o `watch_path_control_char` respectivamente

#### Scenario: Ruta demasiado larga
- **WHEN** el admin envía una ruta absoluta de 1.025 caracteres
- **THEN** la respuesta es `422` con `detail.code == "watch_path_too_long"`

#### Scenario: Duplicado por barra final
- **WHEN** el admin envía `watch_paths=["/etc", "/etc/"]`
- **THEN** la respuesta es `422` con `detail.code == "watch_path_duplicate"` y `detail.index == 1`

#### Scenario: Ruta inexistente es aceptada
- **WHEN** el admin envía `watch_paths=["/opt/no-existe"]`
- **THEN** la respuesta es `200 OK` y el comando se publica
- **AND** la existencia se informa después por `watch_path_status` del heartbeat

#### Scenario: Agente inexistente retorna 404
- **WHEN** se hace `POST /agents/unknown-agent/config` con una lista válida
- **THEN** la respuesta es `404 Not Found`

#### Scenario: Config registrado en audit_log
- **WHEN** se actualiza la config
- **THEN** existe una fila en `audit_log` con `action="agent_config"` y el `agent_id`

#### Scenario: detail del audit_log es JSON válido con paths que contienen comillas
- **WHEN** se actualiza la config con un path absoluto que contiene comillas dobles o barras invertidas
- **THEN** el `detail` del `audit_log` es JSON parseable (comillas dobles, escape correcto) y no rompe el parseo posterior
