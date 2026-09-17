## ADDED Requirements

### Requirement: El selector de estado enumera los siete estados y es coherente con include_superseded

El panel de filtros de `frontend/src/pages/Events.tsx` SHALL ofrecer un selector de estado con los siete
estados canónicos, siempre visibles y en este orden: `pending`, `approved`, `rejected`, `auto_restored`,
`quarantined`, `alert_only`, `superseded` (US-07, RN-71). La visibilidad de la opción `superseded` SHALL
NOT depender del toggle "Mostrar superseded".

Por defecto, sin parámetros de URL, ningún estado SHALL estar marcado, `superseded` SHALL quedar
desmarcado y el listado SHALL excluir los eventos `superseded` (W1, RN-22, RN-98).

La selección SHALL mantener la coherencia con `include_superseded`, porque el backend excluye
`superseded` antes de aplicar el filtro de estado y un filtro `status=superseded` sin
`include_superseded=true` devolvería siempre una lista vacía:

- Marcar `superseded` en el selector SHALL activar también `include_superseded=true`.
- Desmarcar `superseded` en el selector SHALL quitarlo del filtro de estado y SHALL dejar el toggle como
  estaba.
- Apagar el toggle "Mostrar superseded" SHALL quitar también `superseded` del filtro de estado.
- Encender el toggle SHALL reincorporar los `superseded` al listado sin marcar `superseded` en el selector.
- Una URL con `status=superseded` y sin `include_superseded=true` SHALL normalizarse al parsearla, tratando
  `include_superseded` como activo.

Los eventos `superseded` reincorporados SHALL conservar el ícono visual distintivo de US-31.

#### Scenario: El selector muestra los siete estados sin activar el toggle

- **WHEN** el admin navega a `/events` sin parámetros
- **THEN** el selector de estado muestra siete opciones, incluida `superseded`, todas desmarcadas
- **AND** la petición a `GET /events` no lleva `include_superseded` ni `status`

#### Scenario: Selección múltiple incluyendo superseded

- **WHEN** el admin marca `pending` y `superseded`
- **THEN** la URL contiene `status=pending&status=superseded&include_superseded=true`
- **AND** la petición a `GET /events` lleva los dos estados y `include_superseded=true`

#### Scenario: Apagar el toggle quita superseded del filtro

- **WHEN** `superseded` está marcado en el selector y el admin apaga "Mostrar superseded"
- **THEN** `superseded` queda desmarcado, la URL no lleva `include_superseded` y la petición excluye los superseded

#### Scenario: Desmarcar superseded no apaga el toggle

- **WHEN** `superseded` y el toggle están activos y el admin desmarca `superseded`
- **THEN** la URL conserva `include_superseded=true` y ya no lleva `status=superseded`

#### Scenario: Un deep-link con superseded sin toggle se normaliza

- **WHEN** se carga `/events?status=superseded` directamente
- **THEN** la opción `superseded` aparece marcada, el toggle aparece activo y la petición lleva `include_superseded=true`

#### Scenario: Quitar un filtro actualiza el listado

- **WHEN** el admin desmarca el último estado seleccionado
- **THEN** la URL deja de llevar `status` y se emite una nueva petición a `GET /events` sin ese parámetro
