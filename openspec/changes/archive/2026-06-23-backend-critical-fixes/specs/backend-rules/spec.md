## MODIFIED Requirements

### Requirement: Listar reglas ordenadas por severity

El sistema SHALL exponer `GET /rules` para cualquier usuario con acceso completo (`require_full_access`). Un usuario con `must_change_password=True` (token con `scope=password_change_only`) MUST recibir 403 `password_change_required` y no puede listar reglas hasta cambiar su password (C7). La respuesta MUST listar las reglas ordenadas por severity en el orden canónico critical → high → medium → low (RN-09), y dentro de cada severity por `id` ascendente.

#### Scenario: Listado ordenado por severity
- **WHEN** existen reglas con severities mezcladas y un usuario con acceso completo hace `GET /rules`
- **THEN** el sistema retorna 200 con las reglas ordenadas critical primero, luego high, medium y low
- **AND** dentro de la misma severity las ordena por `id` ascendente

#### Scenario: Listado sin autenticación
- **WHEN** se hace `GET /rules` sin token JWT válido
- **THEN** el sistema retorna 401

#### Scenario: Usuario con must_change_password retorna 403
- **WHEN** se hace `GET /rules` con un access token cuyo `scope=password_change_only`
- **THEN** el sistema retorna 403 con detalle `password_change_required`

### Requirement: Obtener una regla por id

El sistema SHALL exponer `GET /rules/{id}` para cualquier usuario con acceso completo (`require_full_access`), retornando la regla solicitada. Un usuario con `must_change_password=True` MUST recibir 403 `password_change_required` (C7).

#### Scenario: Regla existente
- **WHEN** un usuario con acceso completo hace `GET /rules/{id}` de una regla existente
- **THEN** el sistema retorna 200 con la regla

#### Scenario: Regla inexistente
- **WHEN** un usuario con acceso completo hace `GET /rules/{id}` de un id que no existe
- **THEN** el sistema retorna 404

#### Scenario: Usuario con must_change_password retorna 403
- **WHEN** se hace `GET /rules/{id}` con un access token cuyo `scope=password_change_only`
- **THEN** el sistema retorna 403 con detalle `password_change_required`
