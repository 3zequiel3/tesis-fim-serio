## 1. Modelo y migración (base — afecta BD)

- [x] 1.1 Agregar la columna `action_failed: bool = Field(default=False)` al modelo `Event` en `backend/app/modules/events/models.py`, ubicándola junto a `is_symlink`/`symlink_target` para mantener agrupados los metadatos aditivos.
- [x] 1.2 Crear `backend/db/migrations/007_add_event_action_failed.sql` con `ALTER TABLE events ADD COLUMN IF NOT EXISTS action_failed BOOLEAN NOT NULL DEFAULT FALSE;`. Encabezado siguiendo el molde de `006_add_event_severity.sql`: número, decisión (D35/RN-129) y change, nota de idempotencia, y la línea exacta `psql $DATABASE_URL -f 007_add_event_action_failed.sql`. Sin índice y sin `UPDATE` de backfill separado — el `DEFAULT FALSE` lo cubre.

## 2. Derivación del estado en la ingesta (`backend/app/modules/events/service.py`)

- [x] 2.1 Agregar la función pura `derive_event_status(action: str | None, action_failed: bool) -> EventStatus` implementando la tabla de D35/RN-129: `auto_restore` sin fallo → `auto_restored`; `quarantine` sin fallo → `quarantined`; `alert_only` → `alert_only` (sin consultar `action_failed`); `manual_review`, `auto_restore`/`quarantine` con fallo, y `action` ausente o desconocida → `pending`.
- [x] 2.2 Eliminar de `ingest_event` la lectura `status_str = event_data.get("status", "pending")` y su bloque `try/except ValueError` (líneas ~140-145). El backend deja de aceptar un `status` del payload; el fallback del enum queda subsumido en `derive_event_status`.
- [x] 2.3 En `ingest_event`, leer `action = event_data.get("action")` y `action_failed = bool(event_data.get("action_failed", False))` — lectura tolerante, porque el agente escribe la clave solo en la rama de fallo (`agent/decision.py:80`) — y calcular el status con `derive_event_status`.
- [x] 2.4 Pasar `action_failed=action_failed` al constructor `Event(...)` (líneas ~169-188), en toda ingesta e independientemente del status derivado.
- [x] 2.5 En el mismo constructor, setear `resolved_at=received_at` y dejar `resolved_by=None` cuando el status derivado es terminal (`auto_restored`, `quarantined`, `alert_only`); dejar ambos en `None` cuando es `pending`. Usar el argumento `received_at` que ya recibe la función — no leer el reloj adentro.
- [x] 2.6 Verificar por lectura que la lógica de supersesión (líneas ~147-167) sigue corriendo antes de la derivación y sin depender del status entrante, de modo que un evento terminal supersede igual al `pending` activo del path (D-6 del design). No debería requerir cambios; si los requiere, documentarlo.

## 3. Exposición en la API (`backend/app/modules/events/router.py`)

- [x] 3.1 Agregar `action_failed: bool = False` a `EventOut`, siguiendo el patrón aditivo de `ack_status` e `is_symlink`. Verificar que `_to_event_out` no necesita cambios (el campo viene por `from_attributes`).

## 4. Limpieza del léxico en el agente (`agent/decision.py`)

- [x] 4.1 Eliminar la línea `payload["event_type"] = "auto_restored"` al final de `_auto_restore` (línea ~188). NO agregar nada simétrico en `_quarantine`.
- [x] 4.2 Verificar que `agent/detector.py:729` (`enriched_payload.get("event_type", event_type)`, usado para logging) ahora observa el tipo real de operación, y que ningún otro consumidor dependía del valor contaminado.
- [x] 4.3 Revisar la ruta `rehydrate` (líneas ~95-154): confirmar que el payload hand-built mantiene `action` (línea ~116), `action_failed` (~128) y `action = "alert_only"` (~139) con la misma semántica, y que tras 4.1 su `event_type` ya no se sobrescribe al pasar por `_auto_restore` (~121). Ajustar solo si la verificación revela una inconsistencia real.

## 5. Frontend — tipo y mapper

- [x] 5.1 Agregar `action_failed: boolean` a `EventListItem` en `frontend/src/api/events.ts`, con el comentario que nombra decisión y change siguiendo la convención del archivo (`// D35/RN-129 (C40): ...`).
- [x] 5.2 Crear `frontend/src/utils/actionFailed.ts` exportando `getActionFailedMeta(actionFailed: boolean)` que retorna `{ label, className }` o `null` cuando es `false`, con el mismo contrato de `getAckStatusMeta`. Label `'Remediación fallida'`, clases `bg-red-950 text-red-300 border border-red-800`.

## 6. Frontend — render

- [x] 6.1 En `frontend/src/components/ui/EventsTable.tsx`, renderizar el indicador en la celda de estado, adyacente al badge de status, consumiendo `getActionFailedMeta`. Debe renderizar siempre que `action_failed` sea true, sin acoplarlo a `status === 'pending'`.
- [x] 6.2 En `frontend/src/pages/EventDetail.tsx`, agregar el indicador a la fila de badges del header (líneas ~89-93), después de `<StatusBadge/>`, siguiendo la forma de `AckStatusBadge` (~276-287).

## 7. Tests que cruzan el límite real de contrato

- [x] 7.1 Crear `backend/tests/test_event_status_derivation.py` con un test parametrizado sobre las 7 filas de la tabla que llama directamente a `derive_event_status`, sin base de datos.
- [x] 7.2 En el mismo archivo, el test central: construir un `DetectedChange` real, pasarlo por `DecisionEngine.evaluate_and_act` real y alimentar el payload resultante a `ingest_event` real, afirmando `status` y `action_failed` persistidos, para cada fila de la tabla. Seguir el patrón de importación de `agent.detector` desde tests del backend ya usado en `test_event_service.py:155-197` (inserción de `repo_root` en `sys.path`, `agent_id` agregado a mano).
- [x] 7.3 Para las filas de fallo del test 7.2, provocar un `_ActionFailed` genuino (por ejemplo destino no escribible bajo `tmp_path`). NO parchear `payload["action_failed"] = True` a mano: eso reintroduce exactamente el vicio que este test existe para eliminar.
- [x] 7.4 Test de que un payload con una clave `status` explícita la tiene ignorada, y de que no puede inducir `approved` ni `rejected`.
- [x] 7.5 Test de `resolved_at = received_at` / `resolved_by = None` para los tres terminales, y de ambos en `None` para `pending` (incluido el `pending` por acción fallida).
- [x] 7.6 Test de que un evento entrante terminal supersede al `pending` activo del mismo path, y de que un terminal ya persistido no es superseded después.
- [x] 7.7 Test de la ruta `rehydrate` del journal: que produce un status consistente con la misma derivación y un `event_type` no contaminado.
- [x] 7.8 Test de idempotencia de `007_add_event_action_failed.sql` (ejecutarlo dos veces) y de presencia de la columna, copiando el molde de `backend/tests/test_event_severity.py:201-223`.
- [x] 7.9 Test de que `EventOut` expone `action_failed` en `GET /events` y `GET /events/{id}`.

## 8. Tests de regresión y actualización de la suite existente

- [x] 8.1 Actualizar los dos tests cross-boundary de `backend/tests/test_event_service.py` (líneas ~155-197 y ~200-250): ahora producen estados no-`pending`. Afirmar el estado derivado explícitamente — no relajar el assert ni quitarle el `action` al payload.
- [x] 8.2 Actualizar `agent/tests/test_event_payload_contract.py`: verificar el vocabulario de claves emitido y que `event_type` conserva su vocabulario declarado tras la limpieza. Corregir de paso la referencia `service.py:172` de su docstring, que quedó desfasada.
- [x] 8.3 Crear `frontend/src/utils/actionFailed.test.ts` (vitest) afirmando el caso `null` y el caso poblado, siguiendo `frontend/src/utils/ackStatus.test.ts`.
- [x] 8.4 Correr la suite completa de backend, agente y frontend y confirmar que no hay regresiones fuera de las actualizaciones deliberadas de 8.1 y 8.2.

## 9. Roadmap y cierre

- [x] 9.1 Agregar la fila 40 a la tabla resumen de `CHANGES.md` y su sección detallada `### Change 40 — \`event-status-contract\`` (hecho en la fase de propose). Actualizar su estado al momento de archivar, si corresponde.
- [x] 9.2 Aplicar la migración `007` a la base de desarrollo/demo con `psql $DATABASE_URL -f backend/db/migrations/007_add_event_action_failed.sql` — no hay runner automatizado (D3).
- [x] 9.3 Verificar el orden de despliegue del design (backend → agente → frontend) y confirmar en un host real que un `auto_restore` fallido llega a la UI como `pending` con el indicador de remediación fallida.
  - Corrida 2026-09-16 contra el VPS. Orden de despliegue respetado: backend (con las migraciones aplicadas a mano, D3) y frontend ya corrían el commit actual antes de construir la imagen del agente.
  - Montaje: agente `ro-agent` en contenedor con la carpeta vigilada montada **de solo lectura** (`-v /srv/fim-watch-ro:/watch:ro`), de modo que el host puede escribir y el agente no puede restaurar. Regla `/watch/*` con acción `auto_restore` creada por API. Detalle a recordar para futuras corridas: el agente solo recibe reglas por `rule_sync`, y el backend arma ese comando **por cada agente registrado al momento del cambio** (`rules/service.py::enqueue_rule_sync`), así que un agente registrado después de crear la regla arranca con `ruleset_version=0`; hubo que forzar el fan-out con un `PUT /rules/1` antes de la prueba, o el evento habría salido como pendiente común y el resultado habría sido un falso negativo.
  - Resultado en la base: `status = pending`, `action_failed = t`, `action_error = read_only_mount`. En el agente: `agent.preflight.degraded classification=read_only_mount path=/watch` al arrancar y `decision.evaluated action=auto_restore action_failed=True`. En la UI (`/events/305`): badge `pending` + **"Remediación fallida"**, la causa legible "el path no es escribible (mount de solo lectura del despliegue)" y los botones Aprobar/Rechazar disponibles — el `pending` deliberado de D-3, porque el archivo sigue adulterado en disco.
  - Observación, no defecto: el detalle muestra `Tipo de acción: manual_review` porque `derive_action_type` (`events/service.py:188`) deriva ese campo 1:1 desde el `status` — responde "qué hay que hacer ahora", no "qué se intentó". El intento fallido solo es visible por el badge y la causa; un operador no ve en ningún campo que la acción intentada fue `auto_restore`.
- [x] 9.4 Commits convencionales, sin atribución a IA. Slices sugeridos: (a) modelo + migración + derivación + API, (b) limpieza del agente, (c) frontend, (d) tests y roadmap.
  - Cumplida por los tres slices ya en la historia: `eacc89c` (`feat(events): deriva el status del evento y persiste la causa del fallo` — elimina la lectura `event_data.get("status", "pending")`, agrega `action_failed`/`action_error` y documenta por qué una acción fallida deriva a `pending`), `9939bae` (`feat(agent): restauracion con metadata del baseline y causas de fallo` — lado del agente y limpieza del léxico) y `6e7e1cb` (`feat(frontend): indicadores de accion fallida, causa y estado de watch paths`). Los tres son conventional commits y un barrido de toda la historia (`git log --all --grep`) por `Co-Authored-By` y por `Generated with` no devuelve ninguna coincidencia: no hay atribución a IA en el repositorio.
