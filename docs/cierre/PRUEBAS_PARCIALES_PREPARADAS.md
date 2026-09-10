# Resultados de pruebas para historias parciales

> **EJECUTADO PARCIALMENTE — VALIDACIÓN PENDIENTE**

Este artefacto se creó originalmente con el estado **PREPARADO — NO EJECUTADO — VALIDACIÓN PENDIENTE**. El 2026-09-10 se ejecutaron los contratos dirigidos preparados y, después, los nuevos casos de US-03 y US-25: **23 PASS frontend y 6 PASS backend, sin FAIL ni BLOCKED finales**. Los dos casos multi-key de US-03 usaron PostgreSQL 18.3 efímero. Un FAIL anterior del camino crítico de US-20 se diagnosticó como drift del fixture y quedó resuelto al representar explícitamente la severidad persistida del evento.

Estos resultados acreditan solamente contratos unitarios. No acreditan integraciones reales con backend, navegador, Valkey, SSE ni agentes, y ninguna historia se reclasifica como aprobada.

## Resumen verificable

| Alcance | Resultado del 2026-09-10 | Interpretación |
|---|---:|---|
| Frontend, contratos únicos dirigidos | **23 PASS / 0 FAIL / 0 BLOCKED** | Incluye refresh anticipado, fallback reactivo transparente, salida a login y resumen bulk expandible. Las validaciones manuales, E2E y externas siguen pendientes. |
| Backend dirigido | **6 PASS / 0 FAIL / 0 BLOCKED**; exit `0` en cada proceso | Cuatro casos de decisión/notificación de US-20 y dos casos multi-key de US-03 con aceptación de CURRENT/PREVIOUS y rechazo de una clave ajena. |
| Total ejecutado | **29 PASS / 0 FAIL / 0 BLOCKED** | No constituye aprobación integral de ninguna historia. |

El PostgreSQL efímero fue eliminado después de la ejecución. No se modificaron contenedores ni volúmenes preexistentes.

## Inventario por historia

| Historia | Estado actual | Prueba y resultado | Criterio cubierto por el contrato unitario | Sigue requiriendo verificación manual, nativa o externa |
|---|---|---|---|---|
| US-02 | **1 PASS unitario — VALIDACIÓN PENDIENTE** | `frontend/src/components/layout/Navbar.test.tsx::muestra el botón y al usarlo limpia el token y el usuario, solicita logout y navega a /login con replace` | Botón visible; limpieza local del access token y usuario en memoria; invocación al adaptador `logoutApi` simulado; llamada exacta `navigate('/login', { replace: true })`. El mock sólo observa la solicitud: **no acredita que el backend invalide la sesión ni la cookie**. | Confirmar con backend y navegador reales la invalidación de la cookie `httpOnly`, el rechazo posterior de credenciales revocadas y que navegación Atrás no reabra una vista autenticada. Los TTL tienen tests backend existentes, pero deben reejecutarse. |
| US-03 | **7 PASS frontend / 2 PASS backend — VALIDACIÓN INTEGRADA PENDIENTE** | `frontend/src/api/auth.test.ts` (2), `frontend/src/stores/auth.store.test.ts` (3), `frontend/src/api/client.test.ts` (1), `frontend/src/components/layout/ProtectedRoute.test.tsx` (1), `backend/tests/test_jwt_key_rotation.py` (2) | Single-flight; refresh 60 s antes de `exp`; reemplazo en memoria; token ilegible sin confianza proactiva; reintento transparente tras 401; limpieza y navegación a login al perder la sesión; aceptación de claves CURRENT/PREVIOUS y rechazo de una clave ajena. | Falta aceptación con navegador y backend reales de la cookie `httpOnly`, el timer y la navegación. El `exp` decodificado en cliente es sólo una pista de scheduling; el backend conserva toda autoridad de autenticación. |
| US-16 | **1 PASS unitario — VALIDACIÓN PENDIENTE** | `frontend/src/pages/Rules.test.tsx::abre el formulario de edición precargado con patrón, severidad y acción de la regla elegida` | Formulario de edición precargado con los tres valores de la regla seleccionada. | Aceptación visual del modal y verificación posterior de la sincronización efectiva en un agente real. Persistencia, incremento de versión y auditoría continúan apoyándose en los tests backend existentes hasta volver a ejecutarlos. |
| US-17 | **1 PASS unitario — VALIDACIÓN PENDIENTE** | `frontend/src/pages/Rules.test.tsx::no elimina al mostrar la confirmación y llama al endpoint sólo después de confirmar` | Opción de eliminar y confirmación previa; la petición DELETE sólo ocurre tras confirmar. | El escenario integrado “regla borrada → rule sync recibido por un agente real → path cae a `alert_only`” sigue pendiente. Los casos unitarios existentes prueban sus tramos por separado. |
| US-20 | **2 PASS frontend / 4 PASS backend — VALIDACIÓN INTEGRADA PENDIENTE** | Frontend: `frontend/src/hooks/useAlertsSSE.test.tsx` (2 casos). Backend: `backend/tests/test_notifications.py::{test_notify_skip_superseded,test_notify_skip_low_severity,test_notify_skip_medium_severity,test_notify_critical_event_creates_alert_and_publishes_sse}`. | Frontend: apertura del stream autenticado; toast e invalidación de vistas; intento de refresh ante cierre definitivo. Backend: decisiones desde el snapshot persistido para `superseded`, `low`, `medium` y `critical`; el camino crítico persiste Alert, publica el payload SSE y delega a `notify_event`. | Sigue pendiente una prueba integrada con consumer, Valkey, backend y navegador reales. La reconexión automática ante corte transitorio es conducta nativa de `EventSource` y requiere navegador/E2E. |
| US-25 | **6 PASS unitarios — VALIDACIÓN INTEGRADA PENDIENTE** | `frontend/src/components/ui/EventsTable.test.tsx` (2 casos US-25); `frontend/src/components/ui/BulkActionBar.test.tsx` (4 casos) | Checkbox individual y selección de página; botones; modal con cantidad, primeros diez paths y excedente; acción de rechazo por ítem; resumen expandible accesible con resultado por path; invalidación de `events`. La conciliación se aplica funcionalmente sobre la selección actual: quita sólo éxitos del lote enviado, conserva fallidos aún seleccionados y no pierde selecciones nuevas ni reintroduce deselecciones hechas mientras la petición estaba pendiente. | Falta aceptación visual en navegador y una prueba integrada contra una respuesta parcial de backend real. Los unitarios mockean sólo el límite HTTP existente; no acreditan cuarentena ni ejecución en agentes. |
| US-31 | **5 PASS unitarios — VALIDACIÓN PENDIENTE** | `frontend/src/pages/Events.test.tsx` (2 casos US-31); `frontend/src/api/events.test.ts` (2 casos); `frontend/src/components/ui/EventsTable.test.tsx::un superseded con parent_event_id muestra el indicador y enlaza al evento padre` | Toggle apagado por defecto; activación/restauración desde URL; propagación de `include_superseded` al request del cliente; omisión cuando está apagado; indicador de cadena y enlace al padre. | Aceptación visual en navegador y contraste contra backend real con datos `superseded`. Los tests backend existentes deben reejecutarse antes de afirmar que la respuesta respeta el parámetro. |

## Drift histórico del fixture resuelto

El FAIL backend observado inicialmente correspondía al caso positivo de **US-20**, no a US-31. La investigación posterior demostró que no era un defecto de producción: el fixture creaba directamente un `Event` sin severidad y obtenía el valor predeterminado `low`, mientras `notify_if_applicable` consume correctamente el snapshot persistido por la ingesta.

- Caso: `backend/tests/test_notifications.py::test_notify_critical_event_creates_alert_and_publishes_sse`
- Entorno: PostgreSQL `18.3` efímero mediante `TEST_DATABASE_URL`.
- Resultado histórico: **FAIL**, exit `1`; se esperaba una alerta persistida y se obtuvo `0`.
- Causa: drift del fixture respecto del contrato de snapshot de severidad introducido en producción; no se restauró el recálculo de reglas.
- Corrección: `_make_event` acepta y persiste `severity`; los cuatro casos de decisión/notificación declaran explícitamente el snapshot que ejercitan.
- Resultado posterior: **4 PASS**, cada caso en un proceso individual con PostgreSQL 18.3 efímero.

## Otros bloqueos que continúan abiertos

- **US-03:** la capacidad y sus contratos dirigidos están implementados; queda validar en navegador real el timer, la cookie `httpOnly` y la navegación integrada.
- **US-20:** los casos unitarios no sustituyen una integración real consumer → Valkey → SSE → navegador.
- **US-25:** el detalle expandible ya existe y la conciliación preserva los cambios concurrentes de selección; queda aceptación visual e integración con backend real.
- **US-17:** la caída a `alert_only` después de borrar una regla sólo tiene cobertura indirecta por tramos.

## Comandos exactos ejecutados

Los 15 comandos frontend se ejecutaron desde `frontend/` el 2026-09-10; cada invocación seleccionó un solo caso:

```bash
pnpm exec vitest --config vitest.config.ts run src/api/events.test.ts -t 'serializa include_superseded=true en el camino real que construye GET /events'
pnpm exec vitest --config vitest.config.ts run src/api/events.test.ts -t 'omite include_superseded cuando el toggle está apagado'
pnpm exec vitest --config vitest.config.ts run src/components/ui/BulkActionBar.test.tsx -t 'el modal resume la cantidad, muestra sólo los primeros 10 paths y anuncia el excedente'
pnpm exec vitest --config vitest.config.ts run src/components/ui/EventsTable.test.tsx -t 'permite seleccionar una fila individual sin seleccionar las demás'
pnpm exec vitest --config vitest.config.ts run src/components/ui/EventsTable.test.tsx -t 'seleccionar todo agrega exclusivamente los eventos de la página visible'
pnpm exec vitest --config vitest.config.ts run src/components/ui/EventsTable.test.tsx -t 'un superseded con parent_event_id muestra el indicador y enlaza al evento padre'
pnpm exec vitest --config vitest.config.ts run src/pages/Events.test.tsx -t 'está desmarcado por defecto y al activarlo persiste en la URL lógica y llega a la petición'
pnpm exec vitest --config vitest.config.ts run src/pages/Events.test.tsx -t 'restaura el toggle desde include_superseded=true de la URL'
pnpm exec vitest --config vitest.config.ts run src/api/auth.test.ts -t 'comparte una única petición de refresh entre llamadores concurrentes'
pnpm exec vitest --config vitest.config.ts run src/api/auth.test.ts -t 'libera el single-flight al terminar para permitir la próxima rotación'
pnpm exec vitest --config vitest.config.ts run src/components/layout/Navbar.test.tsx -t 'muestra el botón y al usarlo limpia el token y el usuario, solicita logout y navega a /login con replace'
pnpm exec vitest --config vitest.config.ts run src/hooks/useAlertsSSE.test.tsx -t 'abre el stream autenticado y una alerta muestra una notificación sin recargar e invalida las vistas relacionadas'
pnpm exec vitest --config vitest.config.ts run src/hooks/useAlertsSSE.test.tsx -t 'ante un cierre definitivo cierra el stream vencido e intenta renovar la sesión'
pnpm exec vitest --config vitest.config.ts run src/pages/Rules.test.tsx -t 'abre el formulario de edición precargado con patrón, severidad y acción de la regla elegida'
pnpm exec vitest --config vitest.config.ts run src/pages/Rules.test.tsx -t 'no elimina al mostrar la confirmación y llama al endpoint sólo después de confirmar'
```

Los cuatro casos backend se ejecutaron desde `backend/`, cada uno en un proceso independiente. El puerto `45765` pertenecía exclusivamente al PostgreSQL efímero de esta corrida:

```bash
TEST_DATABASE_URL=postgresql+psycopg://fim:test@127.0.0.1:45765/fim_test uv run pytest tests/test_notifications.py::test_notify_skip_superseded
TEST_DATABASE_URL=postgresql+psycopg://fim:test@127.0.0.1:45765/fim_test uv run pytest tests/test_notifications.py::test_notify_skip_low_severity
TEST_DATABASE_URL=postgresql+psycopg://fim:test@127.0.0.1:45765/fim_test uv run pytest tests/test_notifications.py::test_notify_skip_medium_severity
TEST_DATABASE_URL=postgresql+psycopg://fim:test@127.0.0.1:45765/fim_test uv run pytest tests/test_notifications.py::test_notify_critical_event_creates_alert_and_publishes_sse
```

Para reproducirlo debe levantarse otro PostgreSQL efímero y sustituirse el puerto:

```bash
TEST_DATABASE_URL=postgresql+psycopg://fim:test@127.0.0.1:<puerto-efímero>/fim_test uv run pytest tests/test_notifications.py::<caso-individual>
```

## Verificación dirigida de US-03 y US-25

Los siguientes archivos frontend se ejecutaron individualmente después de observar RED en los huecos nuevos. Todos terminaron con exit `0`:

```bash
cd frontend
pnpm exec vitest --config vitest.config.ts run src/stores/auth.store.test.ts
pnpm exec vitest --config vitest.config.ts run src/api/auth.test.ts
pnpm exec vitest --config vitest.config.ts run src/api/client.test.ts
pnpm exec vitest --config vitest.config.ts run src/components/layout/ProtectedRoute.test.tsx
pnpm exec vitest --config vitest.config.ts run src/components/layout/Navbar.test.tsx
pnpm exec vitest --config vitest.config.ts run src/components/ui/BulkActionBar.test.tsx
pnpm exec vitest --config vitest.config.ts run src/pages/Events.test.tsx
```

Los dos contratos multi-key se ejecutaron individualmente contra PostgreSQL 18.3 efímero. Estos son los literales históricos ejecutados; el puerto `32768` dejó de existir cuando se eliminó el contenedor y **no es un comando reproducible por sí solo**:

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://fim:test@127.0.0.1:32768/fim_test uv run pytest tests/test_jwt_key_rotation.py::test_decode_token_acepta_clave_actual_y_anterior_durante_rotacion
TEST_DATABASE_URL=postgresql+psycopg://fim:test@127.0.0.1:32768/fim_test uv run pytest tests/test_jwt_key_rotation.py::test_decode_token_no_acepta_una_clave_ajena_a_la_rotacion
```

Para repetirlos sin depender de ese puerto histórico, este bloque es reproducible y elimina únicamente su propio contenedor:

```bash
cd backend
name="fim-us03-jwt-repro-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
docker run --rm -d --name "$name" --label fim.test-owner=us03-jwt \
  -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fim_test \
  -p 127.0.0.1::5432 postgres:18.3
port="$(docker port "$name" 5432/tcp | sed 's/.*://')"
until docker exec "$name" pg_isready -U fim -d fim_test; do sleep 0.5; done
TEST_DATABASE_URL="postgresql+psycopg://fim:test@127.0.0.1:${port}/fim_test" \
  uv run pytest tests/test_jwt_key_rotation.py::test_decode_token_acepta_clave_actual_y_anterior_durante_rotacion
TEST_DATABASE_URL="postgresql+psycopg://fim:test@127.0.0.1:${port}/fim_test" \
  uv run pytest tests/test_jwt_key_rotation.py::test_decode_token_no_acepta_una_clave_ajena_a_la_rotacion
docker rm -f "$name"
trap - EXIT
```

**RED observado antes de implementar:** `auth.store.test.ts` tuvo 2 FAIL funcionales por ausencia de timer; `ProtectedRoute.test.tsx` tuvo 1 FAIL funcional porque la pérdida de token posterior al montaje no navegaba; `BulkActionBar.test.tsx` tuvo 1 FAIL funcional porque no existía el resumen. `client.test.ts` pasó desde el primer intento, demostrando que la transparencia reactiva tras 401 ya estaba implementada y sólo carecía de prueba.

La corrección posterior de la carrera de selección se verificó con estos comandos realmente ejecutados:

```bash
cd frontend
pnpm exec vitest --config vitest.config.ts run src/components/ui/BulkActionBar.test.tsx -t 'aplica el resultado sobre la selección actual sin perder cambios hechos durante la petición'
pnpm exec vitest --config vitest.config.ts run src/components/ui/BulkActionBar.test.tsx src/pages/Events.test.tsx
```

El primer comando produjo RED antes del fix (`Expected: 3`, `Received: 2`, exit `1`) y GREEN después (`1 passed`, exit `0`). El conjunto dirigido final produjo `8 passed`, exit `0`.

## Criterio de cierre posterior

- [x] Ejecutar individualmente los 15 contratos unitarios frontend y registrar el resultado.
- [x] Diagnosticar el FAIL inicial de US-20 como drift del fixture, corregirlo sin alterar producción y conservar su registro histórico.
- [x] Ejecutar individualmente los cuatro contratos backend de decisión/notificación y registrar **4 PASS**.
- [ ] Ejecutar las verificaciones manuales, nativas, E2E y externas enumeradas.
- [ ] Recién entonces actualizar clasificación y cierre en `MATRIZ_TRAZABILIDAD.md`.

**Estado actual: EJECUTADO PARCIALMENTE — 23 PASS FRONTEND — 6 PASS BACKEND — VALIDACIÓN INTEGRADA PENDIENTE.**
