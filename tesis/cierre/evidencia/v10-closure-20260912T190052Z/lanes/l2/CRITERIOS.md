# Lane L2 — Criterios de aceptación → evidencia

Fuente canónica: `docs/historias_de_usuario.md`. Citas verbatim de cada criterio.
Base: v10-base (7df4935 + hardening de privacidad, HEAD=6790e40).

## US-28: Banner de degradación del sistema (`historias_de_usuario.md:533-545`)

| # | Criterio (verbatim) | Archivo:línea | Test id | Estado |
|---|---|---|---|---|
| 1 | "El frontend consume `GET /health/components` cada **10 segundos**." | `frontend/src/components/layout/SystemBanner.tsx:23` (`refetchInterval: 10_000`) | `SystemBanner.test.tsx > US-28 > consulta GET /health/components cada 10 segundos` | PASS (ya implementado; test nuevo con fake timers confirma cadencia exacta) |
| 2 | "El endpoint retorna el estado de: `postgres`, `valkey`, `n8n`, y cada agente (`ok` \| `degraded` \| `down`)." | `backend/app/core/health.py:136-210` (`check_components`), ruteado en `backend/app/main.py:132-141` | `backend/tests/test_health.py::test_health_components_reports_every_monitored_component` (nuevo, HTTP-level) | PASS |
| 3 | "Si algún componente no está `ok`, se muestra un banner rojo persistente en el header con el nombre del componente afectado y timestamp del último check saludable." | `frontend/src/components/layout/SystemBanner.tsx:33-48,63-77` (`lastHealthyAtRef` por componente) | `SystemBanner.test.tsx > US-28 > muestra el timestamp del ultimo check saludable del componente afectado` | PASS (antes solo nombraba el componente, sin timestamp — fix agregado) |
| 4 | "El banner es cerrable manualmente pero reaparece en el siguiente poll si la condición persiste." | `frontend/src/components/layout/SystemBanner.tsx:39,61,79-86` (`dismissedFor` keyed por `checked_at`) | `SystemBanner.test.tsx > US-28 > es cerrable manualmente y reaparece en el siguiente poll si la condicion persiste` | PASS (no existía botón de cierre — agregado) |
| 5 | "El banner NO bloquea el uso normal de la UI." | `frontend/src/components/layout/SystemBanner.tsx:64-88` (div en flujo normal, sin `fixed`/`absolute`/`aria-modal`), montado en `frontend/src/components/layout/MainLayout.tsx:16` | `SystemBanner.test.tsx > US-28 > no bloquea el uso normal de la UI (no es overlay ni modal)` | PASS (ya cumplía estructuralmente; test nuevo lo deja verificado) |
| 6 | "El backend dispara webhook n8n ante cambios de estado (p. ej. `ok → degraded`)." | `backend/app/core/health.py:172-207` | `backend/tests/test_notifications.py::test_health_state_change_triggers_webhook`, `::test_health_change_payload_carries_the_discriminator` (preexistentes, verificados) | PASS (ya implementado y testeado; sin cambios) |

**US-28: 6/6 demostrados.**

## US-26: Paginación de eventos (`historias_de_usuario.md:498-509`)

| # | Criterio (verbatim) | Archivo:línea | Test id | Estado |
|---|---|---|---|---|
| 1 | "La tabla de Eventos muestra **50 eventos por página** por defecto." | `frontend/src/utils/eventFilters.ts:4,24` (`DEFAULT_PAGE_SIZE=50`), `backend/app/modules/events/router.py:98` (`page_size: int = Query(default=1, ge=1, le=200)` → default 50 vía firma completa) | `backend/tests/test_event_listing_contract.py::test_list_events_default_page_size_is_50` (preexistente) | PASS (sin cambios) |
| 2 | "Existe navegación numerada (primera / anterior / números / siguiente / última)." | `frontend/src/components/ui/Pagination.tsx:47-92` | `Pagination.test.tsx > muestra primera, anterior, siguiente y última`, `> muestra botones numerados y marca la página actual`, `> deshabilita primera/anterior en la página 1`, `> deshabilita siguiente/última en la última página` | PASS (antes solo existía Anterior/Siguiente — componente nuevo) |
| 3 | "Existe input \"ir a página\" con validación (número entre 1 y total)." | `frontend/src/components/ui/Pagination.tsx:94-113` (`handleGoToPage`) | `Pagination.test.tsx > el input "ir a página" navega a una página válida`, `> rechaza un número fuera de rango sin navegar`, `> rechaza un valor no numérico sin navegar` | PASS (no existía — agregado) |
| 4 | "El endpoint `GET /events` soporta `?page=N&page_size=50`." | `backend/app/modules/events/router.py:97-98,126` | `backend/tests/test_event_listing_contract.py::test_list_events_default_page_size_is_50` (usa `?page=2`), `test_pagination_total_respects_status_filter` (usa `?page_size=1`) (preexistentes) | PASS (ya implementado; sin cambios backend) |
| 5 | "La paginación respeta los filtros activos (estado, path, fecha, toggle `include_superseded`)." | `frontend/src/pages/Events.tsx:39-42,68-71,216-220` (`handlePageChange` conserva `filters`), backend `router.py:104-121` (filtros aplican antes del `COUNT`/`LIMIT`) | `Events.test.tsx > US-26 > clickear un número de página respeta el filtro de estado activo`, `> el input "ir a página" navega y conserva los filtros activos`; backend `test_pagination_total_respects_status_filter/_path_prefix_filter/_date_range_filter` (preexistentes) | PASS |

**US-26: 5/5 demostrados.**

## Sin bloqueos

Ningún criterio de US-28 o US-26 entra en conflicto con los appendices "Decisiones de
auditoría/implementación — Abril 2026" de `docs/reglas_de_negocio.md` o
`docs/arquitectura_stack.md`. Se revisaron explícitamente D43/RN-137 (health check de n8n,
no relacionado con el banner) y W15/RN-99 (50/página, consistente con lo implementado).
No hay `BLOCKED-BY-DECISION`.

## GET /events/{id} — base de privacidad preservada

No se tocó `backend/app/modules/events/router.py::get_event` — sigue exigiendo
`require_admin` (línea 145). Confirmado por `backend/tests/test_event_listing_contract.py::test_get_event_by_id_requires_admin_role`,
que sigue pasando sin modificaciones (ver `backend-full.xml`).
