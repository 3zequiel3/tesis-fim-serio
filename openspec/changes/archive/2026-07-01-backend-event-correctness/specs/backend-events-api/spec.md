## MODIFIED Requirements

### Requirement: GET /events con paginación y filtros multi-select

El sistema SHALL exponer `GET /events` en `backend/app/modules/events/router.py` que retorna eventos paginados. Los parámetros de query SHALL ser: `status` (multi-value, acepta múltiples valores, e.g. `?status=pending&status=approved`), `path_prefix` (string, match case-sensitive de prefijo), `date_from` (ISO8601 datetime), `date_to` (ISO8601 datetime), `include_superseded` (bool, default `false`), `page` (int, default `1`, min `1`), `page_size` (int, default `50`, min `1`, max `200`). La respuesta SHALL ser `{"total": int, "page": int, "page_size": int, "items": [...]}`. Cuando `include_superseded=false` (default), los eventos con `status=superseded` SHALL ser excluidos del resultado y del conteo `total` (RN-22, RN-98). El endpoint SHALL requerir `require_full_access` (no solo `get_current_user`): un usuario con `must_change_password=True` (token con `scope=password_change_only`) MUST recibir 403 `password_change_required` y no puede leer eventos hasta cambiar su password (C7).

La paginación MUST implementarse a nivel SQL con `LIMIT/OFFSET/ORDER BY created_at DESC` — está prohibido cargar todos los registros en memoria y paginar en Python. El `total` MUST obtenerse mediante una query `SELECT COUNT(*) FROM (subquery con filtros)`, no mediante `len(result)` (FIX-04).

#### Scenario: Listado default excluye superseded
- **WHEN** `GET /events` sin parámetros, con un access token de acceso completo
- **THEN** la respuesta retorna `200 OK`
- **AND** `items` contiene solo eventos cuyo `status != superseded`
- **AND** `total` refleja el conteo sin superseded

#### Scenario: Filtro por estado único
- **WHEN** `GET /events?status=pending`
- **THEN** `items` contiene solo eventos con `status=pending`
- **AND** `total` es el conteo de eventos pending (excluyendo superseded del conteo si `include_superseded=false`)

#### Scenario: Filtro por múltiples estados
- **WHEN** `GET /events?status=pending&status=approved`
- **THEN** `items` contiene eventos con `status` en `{pending, approved}`

#### Scenario: include_superseded habilita superseded en resultados
- **WHEN** `GET /events?include_superseded=true`
- **THEN** `items` puede contener eventos con `status=superseded`
- **AND** `total` incluye superseded en el conteo

#### Scenario: Filtro por path_prefix
- **WHEN** `GET /events?path_prefix=/etc/`
- **THEN** `items` contiene solo eventos cuyo `path` empieza con `/etc/`

#### Scenario: Paginación SQL retorna subconjunto correcto sin full table scan
- **WHEN** existen 120 eventos y se hace `GET /events?page=2&page_size=50`
- **THEN** `items` contiene los eventos 51–100 (ordenados por `created_at DESC`)
- **AND** `total` es `120`
- **AND** `page` es `2`
- **AND** `page_size` es `50`
- **AND** la query NO carga los 120 eventos en memoria (usa LIMIT/OFFSET en SQL)

#### Scenario: Sin autenticación retorna 401
- **WHEN** `GET /events` sin header `Authorization`
- **THEN** la respuesta es `401 Unauthorized`

#### Scenario: Usuario con must_change_password retorna 403
- **WHEN** `GET /events` con un access token cuyo `scope=password_change_only`
- **THEN** la respuesta es `403 Forbidden` con detalle `password_change_required`
