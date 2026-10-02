# US-19 — Listado de alertas — Trazabilidad de criterios

Fuente canónica: `docs/historias_de_usuario.md` líneas 363-372.

> **Criterios de aceptación:**
> - [ ] Se muestra una lista de alertas ordenada por fecha descendente.
> - [ ] Cada alerta muestra: path del archivo, severidad, tipo de acción, fecha, canal de entrega.
> - [ ] Las alertas son navegables hacia el detalle del evento asociado.

## Mapping

| Criterio | Archivo:línea | Test id | Estado |
|---|---|---|---|
| Orden DESC por fecha | `backend/app/modules/alerts/service.py:414` (`list_alerts`, `.order_by(Alert.created_at.desc())` — ya existía, sin cobertura previa) | `backend/tests/test_sse_alerts.py::test_list_alerts_order_desc_by_created_at` (service) | PASS |
| Orden DESC por fecha (HTTP) | `backend/app/modules/alerts/router.py:219-236` (`GET /alerts`) | `backend/tests/test_sse_alerts.py::test_get_alerts_order_desc_by_created_at` | PASS |
| Severidad, fecha, canal de entrega | `backend/app/modules/alerts/router.py:45-58` (`AlertResponse`, ya existían) + `frontend/src/pages/Alerts.tsx` columnas Severidad/Canal/Creada (ya existían) | `backend/tests/test_sse_alerts.py::test_get_alerts_returns_all`, `::test_get_alerts_serializa_status_derivado` (pre-existentes) | PASS (pre-existente) |
| Path del archivo | `backend/app/modules/alerts/router.py:65` (`AlertResponse.path`), `:78-93` (`_to_alert_response`), `:95-101` (`_events_by_id`, join con `events` sin migración) | `backend/tests/test_sse_alerts.py::test_get_alerts_includes_path_and_action_taken`, `::test_get_failed_alerts_includes_path_and_action_taken` | PASS |
| Path del archivo (UI) | `frontend/src/pages/Alerts.tsx:129-144` (columna "Path") | `frontend/src/pages/Alerts.test.tsx::"muestra el path del archivo y el tipo de acción de cada alerta"` | PASS |
| Tipo de acción | `backend/app/modules/alerts/router.py:66` (`AlertResponse.action_taken`, deriva con `action_taken_for(event.status)` de `alerts/contract.py`) | `backend/tests/test_sse_alerts.py::test_get_alerts_includes_path_and_action_taken`, `::test_get_alerts_action_taken_null_when_pending` | PASS |
| Tipo de acción (UI, null → "—") | `frontend/src/pages/Alerts.tsx:150-152` | `frontend/src/pages/Alerts.test.tsx::"muestra un guion cuando la alerta todavía no tiene acción tomada"` | PASS |
| Navegable al detalle del evento | `frontend/src/pages/Alerts.tsx:141` (`<Link to={`/events/${alert.event_id}`}>`, mismo patrón que `EventsTable.tsx`) | `frontend/src/pages/Alerts.test.tsx::"cada alerta es navegable hacia el detalle del evento asociado"` | PASS |

## Demostrado

8/8 sub-criterios PASS. 0 bloqueados.

## Hallazgo colateral (no un criterio de US-19)

`backend/tests/test_sse_alerts.py::mem_engine` (fixture SQLite `:memory:`) tenía un flake
preexistente: sin `poolclass=StaticPool`, `SingletonThreadPool` liga la conexión al
`threading.get_ident()` del hilo que llamó `create_all`; el hilo *portal* que
`TestClient`/anyio usa para correr la app ASGI puede recibir un id de hilo reciclado por
el SO/intérprete y heredar una conexión ya cerrada de un hilo previo — "no such table:
alerts", 100% reproducible en aislamiento, no reproducible fuera de `TestClient` (probado
con un script standalone y con `ASGITransport`). Se agregó `poolclass=StaticPool` a la
fixture (`test_sse_alerts.py`), que fija una única conexión física para todo el engine.
Confirmado determinístico en 5 corridas consecutivas tras el fix. No es parte del scope
de US-19 pero bloqueaba escribir el test de orden DESC vía HTTP — reportado como hallazgo,
no como refactor: no se tocó ninguna otra fixture ni patrón de test.

## No tocado (fuera de scope, verificado sin conflicto)

- `GET /events/{event_id}` sigue admin-only (`backend/app/modules/events/router.py:138-145`,
  ya así antes de esta lane).
- Contrato canónico de notificación (`backend/tests/test_n8n_workflow_contract.py`,
  `backend/app/modules/alerts/contract.py`) sin cambios — 10/10 tests verdes.
- Sin migración de esquema: `path`/`action_taken` se derivan en el router con un join a
  `events` ya existente en memoria (`_events_by_id`), la tabla `alerts` no cambia.
