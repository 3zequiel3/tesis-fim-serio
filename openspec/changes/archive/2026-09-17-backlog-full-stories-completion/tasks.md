> **Dos partes, cada una verificable y commiteable por separado (D-1 del design).** La **parte 1**
> (grupos 1 a 6) cambia código y agrega tests; termina con sus suites en verde y un commit. La **parte 2**
> (grupos 7 a 10) es documental y cita los nombres reales de los tests de la parte 1, por eso va después.
> Cada tarea de test nombra el archivo y el criterio canónico que asserta.
>
> **Orden de despliegue — restricción, no preferencia.** El grupo 2 (agente) cambia el payload del
> heartbeat: se despliega **antes** de re-correr las baterías del Capítulo 5 (tarea 12.4 de
> `agent-attribution-and-detection-gap`), igual que el slice del agente del change 56.

# Parte 1 — código y tests (US-07, US-21, US-22, US-27, US-29)

## 1. Precondiciones

- [x] 1.1 Verificar con `openspec list --json` que `agent-scope-drop-observability` (change 56) **ya no figura** como change activo y existe en `openspec/changes/archive/`. Si sigue activo, **detenerse**: este change comparte siete archivos con el 56 y depende de su migración `020` (D-6 del design).
- [x] 1.2 Verificar que existe `backend/db/migrations/020_add_agent_out_of_scope_drops.sql` y que `021_*` está libre. Si el `021` estuviera tomado, detenerse y coordinar el número con el autor; no renumerar migraciones ajenas.
- [x] 1.3 Correr `python3 scripts/check_spec_integrity.py` y dejar el resultado en el reporte de apply como línea base.

## 2. Agente — `queue_pressure_high` en el heartbeat (US-21, D72/RN-166)

- [x] 2.1 En `agent/queue.py`, junto a `_MAX_BYTES` (`:62`), definir `QUEUE_PRESSURE_HIGH_THRESHOLD: float = 0.8` con un comentario que cite W3, RN-84 y D72/RN-166 y aclare que la comparación es estricta ("al superar 80%").
- [x] 2.2 En `agent/heartbeat.py::_publish`, leer `self._queue.queue_pressure` **una sola vez** en una variable local y derivar de ella `"queue_pressure"` (sin cambios) y `"queue_pressure_high": pressure > QUEUE_PRESSURE_HIGH_THRESHOLD` (D-3 del design). La clave nueva va antes del cálculo de la firma, dentro del dict firmado.
- [x] 2.3 Actualizar el docstring del módulo (`agent/heartbeat.py:4`), que enumera el payload, para incluir `queue_pressure_high` citando D72/RN-166.
- [x] 2.4 Crear `agent/tests/test_heartbeat_queue_pressure_high.py` con tests que assertan el requisito modificado de `agent-transport` (US-21, último criterio; W3): (a) ratio `0.85` → `queue_pressure_high is True` y `queue_pressure == 0.85`; (b) ratio `0.5` → `False`; (c) ratio exactamente `0.8` → `False`; (d) el valor es `bool` y no `int`; (e) con `shared_secret`, la firma verifica sobre el payload que incluye la clave. Usar una cola falsa cuyo `queue_pressure` cuente las lecturas y assertar **una sola lectura** por publicación.
- [x] 2.5 Verificar que `agent/tests/test_scope_filter.py`, `test_shutdown_heartbeat.py` y `test_heartbeat_interval.py` siguen verdes sin tocarlos.
- [x] 2.6 Correr la suite completa del agente (`pytest agent/tests`) y dejar el resultado en el reporte de apply.

## 3. Backend — migración, modelo, ingesta y API (US-21, D72/RN-166)

- [x] 3.1 Crear `backend/db/migrations/021_add_agent_queue_pressure_high.sql` al estilo de `020`: cabecera que explica por qué existe la columna (W3 pide un flag emitido por el agente), nota de idempotencia, nota D3 con `psql $DATABASE_URL -f 021_add_agent_queue_pressure_high.sql`, y **una sola sentencia** `ALTER TABLE agents ADD COLUMN IF NOT EXISTS queue_pressure_high BOOLEAN;` sin `DEFAULT`, `NOT NULL` ni backfill.
- [x] 3.2 En `backend/app/modules/agents/models.py`, agregar a `Agent` `queue_pressure_high: bool | None = Field(default=None)` junto a `queue_pressure`, y el mismo campo con default `None` en `AgentResponse`. Comentario: D72/RN-166, `None` = nunca reportado, distinto de `False`; migración `021`.
- [x] 3.3 En `backend/app/modules/agents/heartbeat_consumer.py`, leer `queue_pressure_high = payload.get("queue_pressure_high")` junto a `queue_pressure` y aplicarlo con el patrón tolerante del change 56 (D-4 del design): `None` no toca el valor; `isinstance(value, bool)` se persiste; cualquier otro tipo se ignora con `log.warning("heartbeat_consumer.invalid_queue_pressure_high", agent_id=agent_id)`. Ninguna rama interrumpe el resto del heartbeat. Actualizar el docstring del módulo.
- [x] 3.4 En `backend/app/modules/agents/service.py::_agent_to_response`, propagar `queue_pressure_high=agent.queue_pressure_high` sin transformar (sin `or False`).
- [x] 3.5 Tests en `backend/tests/test_heartbeat_consumer.py`, al estilo de `test_discarded_events_*` (requisito ADDED de `backend-agent-management`; US-21 último criterio): `test_queue_pressure_high_persisted` (true y luego false), `test_queue_pressure_high_absent_does_not_reset`, `test_queue_pressure_high_non_bool_ignored` (parametrizado con `1`, `0`, `"true"`; asserta valor intacto, `status == online` y `last_heartbeat` actualizado), `test_queue_pressure_high_never_reported_reads_as_null`.
- [x] 3.6 Test en `backend/tests/test_agent_mgmt.py`: `GET /agents` y `GET /agents/{id}` exponen `queue_pressure_high` con `true`, `false` y `null`, y `queue_pressure` sigue presente sin cambios.
- [x] 3.7 Aplicar `021` dos veces sobre el Postgres efímero de tests y verificar que la segunda no falla y que la columna queda `boolean` nullable (`\d agents`). Dejar la salida en el reporte de apply.
- [x] 3.8 Correr la suite completa del backend con Postgres 18.3 y Valkey 9.0.3 reales y dejar el resultado en el reporte de apply.

## 4. Frontend — banner derivado del flag (US-21, D72/RN-166)

- [x] 4.1 En `frontend/src/api/agents.ts`, agregar `queue_pressure_high?: boolean | null` a `Agent` con comentario: D72/RN-166, `null`/ausente = nunca reportado, el umbral lo decide el agente.
- [x] 4.2 En `frontend/src/components/ui/AgentCard.tsx:80-83`, reemplazar `showQueuePressureBanner = pressurePct > 80` por `agent.queue_pressure_high === true` (D-5 del design). `pressurePct` y los colores de la barra no cambian. Actualizar el comentario citando W3 y D72/RN-166 y diciendo explícitamente que no hay respaldo por umbral en el cliente.
- [x] 4.3 Reescribir en `frontend/src/components/ui/AgentCard.test.tsx` el bloque "US-21 (W3): banner de queue_pressure > 80%" (`:165-180`) contra el flag, cubriendo los cuatro escenarios del requisito ADDED de `frontend-agents`: flag `true` muestra banner; ratio `0.95` con flag `false` no lo muestra y la barra dice 95 %; ratio `0.5` con flag `true` lo muestra; flag `null`/ausente con ratio `0.9` no lo muestra y la tarjeta renderiza sin error.
- [x] 4.4 Actualizar `makeAgent` en el mismo archivo con `queue_pressure_high: false` por defecto.

## 5. Frontend — selector de siete estados (US-07)

- [x] 5.1 En `frontend/src/pages/Events.tsx`, agregar `'superseded'` al final de `ALL_STATUSES` y eliminar el checkbox condicional (`:107-117`). Comentario citando US-07 C1, W1 y D-2 del design.
- [x] 5.2 En `handleStatusToggle`, al **marcar** `superseded` setear también `include_superseded: true`; al desmarcarlo, sólo quitarlo de `status`.
- [x] 5.3 En el `onChange` del toggle "Mostrar superseded" (`:175-186`), al **apagarlo** quitar también `superseded` de `status`; al encenderlo, no marcar `superseded`.
- [x] 5.4 En `frontend/src/utils/eventFilters.ts::parseEventFilters`, si `status` incluye `superseded`, devolver `include_superseded: true` aunque la URL no lo traiga. Comentar por qué: el backend excluye `superseded` antes de filtrar por estado (`events/router.py:129-133`).
- [x] 5.5 Tests en `frontend/src/utils/eventFilters.test.ts`: `status=superseded` sin toggle se parsea con `include_superseded: true`; sin `superseded` el default sigue `undefined`; el round-trip parse → serialize conserva ambos (US-07 C3, W1).
- [x] 5.6 Tests en `frontend/src/pages/Events.test.tsx`, un `describe('Events — filtro por estado (US-07)')` con un caso por criterio canónico: **C1** los siete checkboxes existen sin activar el toggle y en el orden canónico; **C2** marcar `pending` y `approved` emite ambos `status` en la petición; **C3** sin parámetros ningún estado está marcado y la petición no lleva `include_superseded`; **C4** encender el toggle emite `include_superseded=true` y apagarlo con `superseded` marcado lo desmarca y lo quita de la petición; **C5** desmarcar el último estado emite una petición nueva sin `status`. Más los escenarios del requisito ADDED de `frontend-events`: marcar `superseded` emite `include_superseded=true`; desmarcarlo conserva el toggle; el deep-link `/events?status=superseded` arranca con ambos activos.
- [x] 5.7 Verificar que el ícono de cadena rota de US-31 sigue asertado por sus tests existentes, sin tocarlos.

## 6. Tests de criterios sin aserción y cierre de la parte 1 (US-22, US-27, US-29)

- [x] 6.1 **US-22** — crear `frontend/src/pages/Agents.test.tsx` (D-7 del design): mockear `@/api/client` y `sonner`; (a) rescan sin conflicto → `toast.success('Rescan iniciado')`; (b) rescan con 409 → abre `RescanConfirmModal` y, al confirmar, `toast.success('Rescan forzado iniciado')`. Asserta el criterio "Se muestra confirmación de que la solicitud fue enviada al agente".
- [x] 6.2 **US-27** — en `backend/tests/test_auth.py`, junto a `test_change_password_deja_fila_en_audit_log`, agregar `test_login_deja_fila_en_audit_log` y `test_logout_deja_fila_en_audit_log`: consultan `AuditLog` por `action` y `user_id` del usuario autenticado. Asserta el criterio de `audit_log` de US-27 (RN-94).
- [x] 6.3 **US-29** — en `backend/tests/test_notifications.py`, junto a `test_get_failed_alerts_returns_only_failed`, agregar `test_get_failed_alerts_expone_last_error_retry_count_failed_at`: siembra una alerta en fallo terminal con `last_error`, `retry_count` y `failed_at` conocidos y asserta los tres valores en la respuesta HTTP, con `failed_at` en ISO-8601 con zona. Asserta el criterio de la tabla de US-29 (primer intento, error y `retry_count`).
- [x] 6.4 Correr `pnpm typecheck`, `pnpm build` y `pnpm test --run` en `frontend/` y dejar los resultados en el reporte de apply.
- [x] 6.5 Re-correr las suites completas de agente y backend (si 2.6 y 3.8 fueron antes de 6.2/6.3) y dejar los resultados.
- [x] 6.6 **Punto de corte de la parte 1**: commit convencional con el código y los tests de los grupos 2 a 6 (sin tocar `docs/`). Registrar el hash en el reporte de apply; la parte 2 lo cita. Commit: `2d07cb2`.

# Parte 2 — declaraciones y trazabilidad (US-01, US-05, US-11, US-12, US-23 y recuento)

## 7. Inventario de ajustes y decisiones pendientes

- [x] 7.1 Ruta `/alerts/failed` (US-05, US-29) cerrada antes del apply: D70/RN-164 se amplió el 2026-09-17 para cubrir `/change-password` y `/alerts/failed` (esta última vigente desde `f8508eb`), y RN-102 se reescribió con la tabla `alerts` (D6/RN-107) y la nueva ruta, con nota de reescritura.
- [x] 7.2 Etiqueta de US-05 y US-29 corregida en `docs/historias_de_usuario.md` a "D6/RN-107, reescritura de RN-102" (2026-09-17). La tabla de ajustes de 8.5 lo registra igual.
- [x] 7.3 Inventariar **todo** el diff de `cc73c2d` sobre `docs/historias_de_usuario.md` (`git show cc73c2d -- docs/historias_de_usuario.md`) y producir una fila por línea cambiada: US-01 (ruta), US-05 (banner sin umbral), US-23 (fila en `alerts`), US-27 (ruta), US-29 (banner, tabla y ruta), W11. Agregar US-11 C4 (alineado el 2026-09-17 por D71/RN-165) y US-12 (criterio de `ruleset_version` superado por D66/RN-160, sin cambio de texto).
- [x] 7.4 Confirmar leyendo `backend/app/modules/actions/streams.py:145` y `agent/commands.py:250-257` que US-11 C5 **no** está afectado por D66/RN-160 (el `baseline_update` lleva `ruleset_version`) y dejarlo escrito en la fila de US-11.

## 8. `docs/cierre/MATRIZ_TRAZABILIDAD.md`

- [x] 8.1 Actualizar el encabezado del corte: rama `devel`, commit de cierre de la parte 1 (6.6), fecha.
- [x] 8.2 Filas US-07, US-21, US-22, US-27 y US-29 a `COMPLETA`, citando los tests de los grupos 2 a 6 por `archivo::nombre` y el commit de 6.6.
- [x] 8.3 Fila US-11 a `COMPLETA` citando D71/RN-165, el texto alineado y `test_actions.py::test_no_get_file_hash_published` como aserción del criterio vigente.
- [x] 8.4 Filas US-01, US-05, US-12, US-23 (y US-27, US-29 por 7.3): conservar `COMPLETA` y referenciar su fila en la tabla de ajustes.
- [x] 8.5 Agregar la sección **"Ajustes de criterio declarados"** con columnas Historia, Criterio, Texto original, Texto vigente, Decisión, Fecha, Commit, con las filas de 7.3. Decisiones: D70/RN-164 (US-01, US-27), D6/RN-107 como reescritura de RN-102 (US-05, US-23, US-29), D66/RN-160 (US-12), D71/RN-165 (US-11), y D70/RN-164 también para la ruta `/alerts/failed` (US-05, US-29).
- [x] 8.6 Reemplazar la tabla de conteo por **31 / 0 / 0** y, al lado, el **conteo estricto** (historias completas sin ningún ajuste de criterio) con la lista de historias excluidas. Con el inventario de 7.3 el estricto esperado es **24**; si el inventario da otro número, usar el verificado y explicar la diferencia. US-07 y US-21 **no** son ajustes: cerraron por cambio de código.
- [x] 8.7 Reemplazar la tabla "Las seis parciales" por una nota de cierre que diga cómo se cerró cada una (código, test o decisión), y agregar la fila **31 / 0 / 0** a "Reconciliación de los conteos históricos" sin borrar las anteriores.
- [x] 8.8 Actualizar "Criterios de lectura → Divergencia": ya no quedan casos vigentes; nombrar dónde se declararon.

## 9. `docs/trazabilidad_us_tests.md`

- [x] 9.1 Actualizar el encabezado del documento y §2 ("Lo que el Capítulo 5 puede afirmar"): 31/0/0 con ajustes declarados, más el conteo estricto.
- [x] 9.2 Actualizar §3 (resumen), las filas de §4 y los títulos de §5.7, §5.11, §5.21, §5.22, §5.27 y §5.29 a `completa`, con los tests nuevos por `archivo::nombre`.
- [x] 9.3 Agregar en §5.1, §5.5, §5.11, §5.12, §5.23, §5.27 y §5.29 una línea "Ajuste de criterio declarado" que remita a la tabla de la matriz de cierre.
- [x] 9.4 Actualizar §6 (criterios no implementados: filas de US-21 `:853`) y §7 (brechas: cerrar las de US-07, US-11, US-21, US-22, US-27, US-29, incluido el nivel 4 de `:978`).
- [x] 9.5 Verificar con `rg -n "parcial|PARCIAL|25 / 6|25/6" docs/trazabilidad_us_tests.md docs/cierre/MATRIZ_TRAZABILIDAD.md` que no queda ningún conteo ni estado vigente desactualizado (las menciones históricas deben estar marcadas como tales).

## 10. Verificación final

- [x] 10.1 Correr `python3 scripts/check_spec_integrity.py` y `openspec validate backlog-full-stories-completion --strict`.
- [x] 10.2 Re-correr las suites completas: agente (`pytest agent/tests`), backend con Postgres y Valkey reales, frontend (`pnpm typecheck`, `pnpm build`, `pnpm test --run`). Dejar los resultados en el reporte de apply.
- [x] 10.3 Dejar constancia en el reporte de apply de que **queda fuera de alcance** un nuevo candidato consolidado con cadena de custodia: el 31/0/0 de este change es un corte de `devel`, no una validación del candidato.
- [x] 10.4 **Punto de corte de la parte 2**: commit convencional sólo con `docs/`. Commit: `66e5484`.
