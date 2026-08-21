# `contracts/`

Fixtures JSON versionados de contrato de wire entre el frontend y el backend
de la FIM Platform. Cada archivo describe la forma de una petición HTTP en
un punto donde los dos lados ya divergieron una vez sin que ninguna suite lo
detectara.

## Qué es

Un fixture acá no es un ejemplo ni documentación: es el único artefacto que
**los dos lados afirman contra sí mismo**.

- El **frontend** instala un adaptador de captura sobre el cliente HTTP real
  (`apiClient.defaults.adapter`), invoca la función de API sin mockear
  `@/api/client`, y compara el cuerpo/query **serializado** que el cliente
  emitiría contra el fixture.
- El **backend** lee el mismo archivo y afirma que el schema Pydantic lo
  acepta y que el endpoint real no lo rechaza.

Si un lado cambia su forma sin que el fixture cambie con él, su propia
aserción se pone en rojo. Ninguno de los dos puede moverse solo sobre este
contrato.

## Por qué acá y no bajo `frontend/` o `backend/`

Un fixture bajo cualquiera de los dos lados sería "la creencia de ese lado,
que el otro consume" — el mismo problema que tenía un archivo compartido
antes de existir esta convención, sólo que con una capa de indirección
encima. En la raíz el archivo no le pertenece a ninguno de los dos: es el
contrato, y ambos responden a él por igual.

## Por qué existe

`frontend/src/api/actions.ts` publicó `{items:[{event_id, version}], action}`
—con `action` al nivel superior— durante toda la vida del proyecto, mientras
`backend/app/modules/actions/schemas.py::BulkRejectItem` la exige **dentro**
de cada ítem. `POST /actions/bulk-reject` devolvió 422 el 100% de las veces.
Las dos suites de test estaban en verde: cada una verificaba la creencia de
su propio lado (`backend/tests/test_actions_router.py::test_bulk_reject_uses_items_contract_with_per_item_action`
del lado backend, el mock de módulo del lado frontend) y ninguna observaba
la del otro. El 422 sólo era observable en el punto de encuentro, que ningún
test ejecutaba. `contracts/` es ese punto de encuentro, hecho explícito.

## Alcance

Esta capacidad (`api-contract-fixtures`) cubre las fronteras donde los dos
lados ya divergieron o son estructuralmente propensas a hacerlo — no todas
las llamadas del cliente. Ver D-6 del design de `frontend-severity-triage`
para el criterio completo.

## Contenido

- `actions.bulk-reject.request.json` — cuerpo de `POST /actions/bulk-reject`.
- `events.list-severity.request.json` — query string de `GET /events` al
  filtrar por severidad.
