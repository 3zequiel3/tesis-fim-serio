## MODIFIED Requirements

### Requirement: POST /agents/{id}/config — actualizar watch_paths y publicar update_config

El sistema SHALL exponer `POST /agents/{id}/config` (requiere JWT admin) que acepta `{watch_paths: list[str]}`. MUST persistir los nuevos `watch_paths` en DB (replace-all), incrementar `ruleset_version` (D5), publicar el comando `update_config` HMAC-signed al stream `commands` de Valkey con `target_agent_id` y la lista de paths, y registrar en `audit_log`. Si el agente no existe SHALL retornar `404`.

El campo `detail` del registro `audit_log` de esta operación MUST ser JSON válido, serializado con `json.dumps(...)` (comillas dobles, escape correcto), y no una interpolación f-string sobre `str(list)`. El `detail` MUST permanecer JSON válido aunque algún path contenga caracteres especiales como comillas dobles (`"`) o barras invertidas (`\`).

#### Scenario: Config actualizado y comando publicado
- **WHEN** un admin hace `POST /agents/agent-01/config` con `watch_paths=["/etc"]`
- **THEN** la respuesta es `200 OK`
- **AND** `agents.watch_paths` es `["/etc"]` en DB
- **AND** se publicó el mensaje `update_config` en el stream `commands` con `target_agent_id="agent-01"` y `watch_paths=["/etc"]`
- **AND** el mensaje tiene `signature` verificable con HMAC-SHA256 y el `shared_secret` del agente

#### Scenario: watch_paths vacío es válido
- **WHEN** el admin envía `watch_paths=[]`
- **THEN** la respuesta es `200 OK` y el agente deja de monitorear paths

#### Scenario: Agente inexistente retorna 404
- **WHEN** se hace `POST /agents/unknown-agent/config`
- **THEN** la respuesta es `404 Not Found`

#### Scenario: Config registrado en audit_log
- **WHEN** se actualiza la config
- **THEN** existe una fila en `audit_log` con `action="agent_config"` y el `agent_id`

#### Scenario: detail del audit_log es JSON válido con paths que contienen comillas
- **WHEN** se actualiza la config con un path que contiene comillas dobles o barras invertidas
- **THEN** el `detail` del `audit_log` es JSON parseable (comillas dobles, escape correcto) y no rompe el parseo posterior
