## 1. Agente — atribución honesta (D49/RN-143)

- [ ] 1.1 En `agent/detector.py:98-106`, cambiar la firma de `_get_uid` a `def _get_uid(pid: int) -> int | None:` y reemplazar el `return 0` final por `return None`. El `except OSError: pass` se mantiene: la excepción no debe propagarse al hilo lector. Alinear el cuerpo con `_get_exe` (`:91-95`), que ya devuelve `None` en el mismo caso.
- [ ] 1.2 En `agent/detector.py:55`, cambiar `uid: int` a `uid: int | None` en `FanotifyEvent`. En `:72`, cambiar `process_uid: int` a `process_uid: int | None` en `DetectedChange`.
- [ ] 1.3 Verificar que las tres construcciones de `DetectedChange` en `_process_event` pasan `process_uid=fan_event.uid` **sin transformarlo** (sin `or 0`, sin `int(...)`, sin default). El nulo debe propagarse solo. Si aparece una coerción, es un bug preexistente y hay que quitarla.
- [ ] 1.4 Comentar el cambio citando **D49/RN-143** y diciendo explícitamente que `0` significa root y sólo root. El comentario debe nombrar la ventana de fallo (hasta 150 ms de reintentos de hash entre la notificación del kernel y el armado del evento) para que la próxima lectura no reconstruya el razonamiento desde cero.
- [ ] 1.5 En `agent/decision.py:151`, en el payload de `rehydrate`, cambiar `"process_pid": 0` y `"process_uid": 0` a `None` en ambos casos. `"process_exe": None` ya es correcto y no se toca. Comentar citando D49/RN-143 y la razón: en esta ruta el proceso original no existe **por definición**, así que el `0` incondicional hacía que todo evento recuperado del journal se reportara como hecho por root.
- [ ] 1.6 Confirmar que **no** hace falta tocar `backend/app/modules/events/models.py:58` (`process_uid: int | None`), `EventOut.process_uid` (`backend/app/modules/events/router.py:39`) ni `frontend/src/api/events.ts:39`: los tres ya son null-safe. Este punto **no requiere migración**. Si el arreglo parece necesitar tocar alguno de los tres, detenerse: el diseño dice que no hace falta, y esa discrepancia es información.

## 2. Agente — detección de `FAN_Q_OVERFLOW` (D50/RN-144)

- [ ] 2.1 En `agent/_fanotify.py`, agregar `FAN_Q_OVERFLOW = 0x00004000` al bloque de constantes de eventos, con el mismo estilo de comentario que las máscaras vecinas. Verificar contra `fanotify(7)` que el valor es correcto antes de escribirlo.
- [ ] 2.2 Verificar que `_parse_events` (`agent/_fanotify.py:241-258`) ya propaga el `mask` sin filtrarlo en `FanEvent(path=..., pid=..., mask=mask)`. **No** agregar lógica de decisión a `_parse_events`: es una función pura de parseo de buffer (D-3 del design). Si un evento de desbordamiento llega con `_fd >= 0`, el `_safe_close` existente ya lo cubre.
- [ ] 2.3 En `_read_loop` (`agent/detector.py:369-397`), insertar el reconocimiento del bit **antes** del `if ev.path is None` (`:377`) y antes de `_path_location_in_scope` (`:381`). Sin esa ubicación el evento cae en el descarte por path nulo y se pierde con un warning genérico. Verificar leyendo el diff que el orden quedó: overflow → path nulo → scope.
- [ ] 2.4 Implementar `_emit_detection_gap()` en `FanotifyDetector`: arma el payload del evento sintético con `event_id` UUID v4 nuevo, `event_type` y `operation_type` en `"detection_gap"`, `path=None`, `process_pid/process_uid/process_exe` en `None`, causa `fan_q_overflow`, `action="alert_only"`, `hash_detected=""` (contrato D-C13-04 con el backend: `hash_detected` es `str` NOT NULL) y `detected_at` en ISO 8601 UTC.
- [ ] 2.5 La publicación va por `self._publisher.publish(payload)`, el mismo camino que el resto — hereda cola offline, firma HMAC, `schema_version` y reintentos. Como `_read_loop` corre en un hilo y `publish` es async, usar `self._loop.call_soon_threadsafe` con un envoltorio que agende la corrutina, **sin** pasar por `self._raw_queue`: bajo saturación esa cola es lo que está lleno, y perder el aviso de pérdida por `QueueFull` anularía el propósito de la regla (D-3 del design).
- [ ] 2.6 El `detection_gap` **no** invoca `self._decision_engine.evaluate_and_act` ni escribe journal (D-5 del design). Verificar leyendo el diff que ninguna de las dos llamadas queda en el camino del evento sintético.
- [ ] 2.7 El `detection_gap` **no** toca el baseline: ni `write_entry`, ni `write_symlink_entry`, ni `mark_absent`, ni `_pending`, ni `_event_to_path`. El evento no habla de ningún archivo, así que no hay path que indexar.
- [ ] 2.8 Emitir un `log.warning("detector.detection_gap", suppressed_count=..., event_id=...)`. Nivel `warning` y no `info`: es una pérdida de cobertura del sistema, no un evento de rutina.

## 3. Agente — deduplicación por ventana (D50/RN-144)

- [ ] 3.1 Agregar dos campos de estado privados al detector, escritos y leídos **sólo desde el hilo lector** para no necesitar lock: el instante monótono del último `detection_gap` emitido (`None` al arrancar) y el contador de desbordamientos suprimidos desde esa emisión.
- [ ] 3.2 Usar `time.monotonic()` y no `datetime.now()` para la ventana: un ajuste de reloj del host no debe suprimir ni disparar emisiones. La ventana es de **60 segundos**, declarada como constante de módulo con nombre explícito y un comentario que cite D50/RN-144.
- [ ] 3.3 Lógica de la ventana: si no hubo emisión previa **o** transcurrieron ≥ 60 s desde la última, emitir con `suppressed_count` igual al contador acumulado y **reiniciarlo a cero**; si no, sólo incrementar el contador y no publicar nada.
- [ ] 3.4 Confirmar que el estado de la ventana es en memoria y **no** se persiste: tras un reinicio del agente el primer desbordamiento emite siempre (D-4 del design). Documentarlo en el comentario, porque parece un olvido y es una decisión.
- [ ] 3.5 Verificar que la deduplicación es **por ventana de tiempo**, no por desbordamiento ni por contador de eventos. Un test de la sección 5 lo fija.

## 4. Agente — limpieza de referencias stale a `pyfanotify`

- [ ] 4.1 `agent/detector.py:2` — el docstring de módulo dice "usando pyfanotify". Reemplazar por el backend real: `agent/_fanotify.py`, `ctypes` sobre syscalls crudas, modo FID (D46/RN-140).
- [ ] 4.2 `agent/detector.py:52` — docstring de `FanotifyEvent`: "Evento raw recibido de pyfanotify" → del backend fanotify interno.
- [ ] 4.3 `agent/detector.py:242` — docstring de la clase: "lee eventos pyfanotify (bloqueante)".
- [ ] 4.4 `agent/detector.py:279` — mensaje de `RuntimeError`: `"pyfanotify no disponible — requiere Linux con CAP_SYS_ADMIN"`. Es texto que un operador ve en el log; debe nombrar la causa real (backend fanotify no disponible: se requiere Linux ≥ 5.1 con `CAP_SYS_ADMIN` y `CAP_DAC_READ_SEARCH`).
- [ ] 4.5 `agent/detector.py:363` — docstring de `_read_fan_events`: "Lee eventos de pyfanotify (bloqueante)".
- [ ] 4.6 Docstrings de tests: `agent/tests/test_symlink_hardening.py:22`, `agent/tests/test_detector_multi_event.py:39`, `agent/tests/test_scope_filter.py:14`, `agent/tests/test_scope_filter.py:195`, `agent/tests/test_agent_config.py:17`. Sólo texto: **ninguna aserción ni lógica de test cambia** en esta tarea.
- [ ] 4.7 **NO tocar** `agent/requirements.txt:6` (ya dice explícitamente que no se depende de `pyfanotify`) ni `agent/_fanotify.py:5` (referencia legítima al wrapper descartado, explicando por qué no sirve). Verificar con `rg -n pyfanotify agent/` que después de la limpieza sólo quedan esas dos ocurrencias.

## 5. Tests del agente

- [ ] 5.1 Test de `_get_uid` sobre un pid inexistente: elegir un pid alto libre (verificando que `/proc/<pid>` no existe) y afirmar `_get_uid(pid) is None`. Afirmar además que **no** retorna `0`, explícitamente — un `assert x is None` sobre un valor `0` falla, pero la aserción negativa documenta la intención para el próximo lector.
- [ ] 5.2 Test de `_get_uid` sobre el proceso actual: afirmar `_get_uid(os.getpid()) == os.getuid()`. Sin este test, 5.1 pasaría también con una función que devuelve `None` siempre.
- [ ] 5.3 Test de la rehidratación: en `agent/tests/test_decision.py`, agregar una aserción sobre el payload publicado por `engine.rehydrate()` afirmando `payload["process_uid"] is None` y `payload["process_pid"] is None`. **Verificado: hoy esa línea no tiene ninguna cobertura** — los tests que ejercen `rehydrate()` (`:220`, `:364`, `:399`, `:419`) no assertan sobre `process_uid`.
- [ ] 5.4 **NO modificar** las fixtures `_make_change()` con `process_uid: 0` de `agent/tests/test_decision.py:60-77`, `agent/tests/test_restore_metadata.py:77` y `agent/tests/test_symlink_hardening.py:565`. Son helpers tipo `MagicMock` con `process_pid: 100` que alimentan `evaluate_and_act()` y representan un proceso root **real**. Modificarlas destruiría la única cobertura del caso root legítimo.
- [ ] 5.5 Crear `agent/tests/test_detection_gap.py`. Test `test_overflow_emits_detection_gap`: inyectar un `FanEvent` con `mask` conteniendo `FAN_Q_OVERFLOW` y `path=None` en el hilo lector (o en la unidad que lo procesa) y afirmar que se publica exactamente un payload con `event_type="detection_gap"`, `path is None`, los tres campos de proceso en `None`, causa `fan_q_overflow` y `action="alert_only"`.
- [ ] 5.6 Test `test_overflow_does_not_hit_null_path_discard`: afirmar que el evento de desbordamiento **no** produce el `log.warning("detector.event_null_path")` y **sí** produce el payload. Es la prueba de que el orden de los chequeos en `_read_loop` es el correcto.
- [ ] 5.7 Test `test_overflow_bypasses_decision_engine`: montar el detector con un `DecisionEngine` mockeado y afirmar que `evaluate_and_act` **no** fue llamado, y que no se creó ninguna entrada de journal.
- [ ] 5.8 Test `test_detection_gap_dedup_window`: emitir cinco desbordamientos dentro de la ventana y afirmar un único payload; después avanzar el reloj monótono más de 60 s (parcheando la fuente de tiempo del detector, nunca durmiendo), emitir uno más y afirmar un segundo payload con `suppressed_count == 4`.
- [ ] 5.9 Test `test_isolated_overflow_reports_zero_suppressions`: un desbordamiento aislado emite con `suppressed_count == 0`. Sin este test, 5.8 pasaría también con una implementación que siempre reporta un número distinto de cero.
- [ ] 5.10 Test `test_detection_gap_does_not_consume_internal_queue`: con la `asyncio.Queue` interna llena, afirmar que el `detection_gap` se publica igual y que `detector.event_drops` **no** se incrementó por causa de ese evento.
- [ ] 5.11 Usar las constantes reales de `agent/_fanotify` para las máscaras en todos los tests de esta sección. Nunca literales hexadecimales: si el módulo cambia una constante, el test debe seguirla.

## 6. Base de datos — migración 012

- [ ] 6.1 Crear `backend/db/migrations/012_add_event_type_and_nullable_path.sql` siguiendo la convención de 005–011: encabezado de comentario que explique la decisión (D51/RN-145), la idempotencia y la línea de aplicación `psql $DATABASE_URL -f 012_add_event_type_and_nullable_path.sql`. Sin Alembic (D3).
- [ ] 6.2 Sentencia 1: `ALTER TABLE events ADD COLUMN IF NOT EXISTS event_type VARCHAR(32) NOT NULL DEFAULT 'file_modified';`. Documentar en el comentario que el default para filas preexistentes es **irrecuperable, no adivinado**: el backend nunca persistió `event_type`, así que el valor real de los eventos históricos no existe en ningún lado.
- [ ] 6.3 Sentencia 2: `ALTER TABLE events ALTER COLUMN path DROP NOT NULL;`. Documentar en el comentario que no lleva `IF EXISTS` porque la sintaxis no lo admite, pero **es un no-op sin error** sobre una columna ya nullable, de modo que el script sigue siendo idempotente por efecto.
- [ ] 6.4 **Sin índice sobre `event_type`**: no hay endpoint ni filtro que consulte por ese campo en el alcance de esta change, e indexar una columna de baja cardinalidad sin consulta que lo justifique no aporta nada. Mismo criterio que la migración 008 con `action_error`. Documentarlo.
- [ ] 6.5 **Sin `CHECK` ni tipo enum de PostgreSQL sobre `event_type`**: tolerancia hacia adelante explícita en D51/RN-145, mismo criterio que `action` y `action_error` (D33, D36/RN-130). Un enum a nivel de base convertiría "el agente va adelantado del backend" en pérdida de eventos de integridad. Documentar la razón en el encabezado.
- [ ] 6.6 Verificar la idempotencia ejecutando el script **dos veces** contra la base de test y confirmando que la segunda corrida completa sin error y sin alterar datos.

## 7. Backend — modelo

- [ ] 7.1 En `backend/app/modules/events/models.py`, agregar `event_type: str = Field(default="file_modified")` a `Event`, con un comentario que cite D51/RN-145 y explique la tolerancia hacia adelante (sin validación contra enum, mismo criterio que `action_error`).
- [ ] 7.2 Cambiar `path: str = Field(index=True)` a `path: str | None = Field(default=None, index=True)`. Mantener el índice: sigue sirviendo al filtro `path_prefix` y a la búsqueda de `pending` por ruta.
- [ ] 7.3 Verificar que `backend/tests/conftest.py` (que usa `create_all`) fabrica la tabla con las dos columnas nuevas y con la nulabilidad correcta. La suite corre sobre `create_all`, no sobre las migraciones, así que modelo y migración son dos verdades que hay que mantener alineadas a mano.

## 8. Backend — ingesta, supersesión, severidad

- [ ] 8.1 En `backend/app/modules/events/service.py:164`, cambiar `path = event_data.get("path", "")` a `path = event_data.get("path")`. **Este es el defecto central de D51/RN-145**: ese `""` es la clave con la que el backend busca el `pending` anterior para supersedirlo, así que con él **todos** los `detection_gap` se supersederían entre sí y cada brecha nueva borraría la anterior.
- [ ] 8.2 Guardar `event_data.get("event_type")` y pasarlo al constructor de `Event`. Sin validación contra enum: un valor desconocido se persiste tal cual. Un payload sin la clave toma el default del modelo (agente anterior a esta change).
- [ ] 8.3 En `ingest_event`, envolver la búsqueda de pending en una guarda: si `path is None`, **no** invocar `get_pending_event_for_path` y dejar `parent_event_id = None`. `get_pending_event_for_path` mantiene su firma `path: str` — no recibe nunca un nulo porque el llamador no la invoca (D-6 del design).
- [ ] 8.4 En `ingest_event`, declarar explícitamente la guarda de compactación: si `path is None`, **no** invocar `compact_chain`. Ya se satisface por construcción (`compact_chain` sólo corre cuando `parent_event_id is not None`), pero la guarda explícita evita que un refactor futuro la pierda y borre eventos de brecha de detección al alcanzar el umbral de 10.
- [ ] 8.5 Severidad: si `path is None`, asignar `RuleSeverity.high` **sin** llamar a `determine_severity_for_path`. La excepción se dispara por **ausencia de ruta**, no por `event_type == "detection_gap"`, de modo que un tipo futuro sin ruta herede el tratamiento correcto sin tocar el código (D-7 del design, D51/RN-145). Comentar por qué `high` y no `critical`: una brecha de detección es una pérdida de garantía, no una violación de integridad confirmada.
- [ ] 8.6 Verificar que `derive_event_status("alert_only", False)` (`service.py:78-79`) ya retorna `EventStatus.alert_only` y que `is_terminal` ya lo trata como resolución automática sin operador (`resolved_at = received_at`, `resolved_by = NULL`). **No debería hacer falta ningún cambio en esa ruta**; si lo hace, es información sobre un supuesto roto del diseño.
- [ ] 8.7 Verificar que `backend/app/modules/events/consumer.py` **no** requiere cambios: ninguno de sus siete pasos de validación mira `path`. Confirmarlo leyendo el archivo, no asumiéndolo.

## 9. Backend — API

- [ ] 9.1 En `backend/app/modules/events/router.py`, agregar `event_type: str` a `EventOut` y cambiar `path: str` a `path: str | None`.
- [ ] 9.2 Verificar que `path_prefix` (`router.py:100-101`, `Event.path.startswith(path_prefix)`) se traduce a `LIKE 'prefijo%'` y que un `NULL` no matchea, de modo que un evento sin ruta quede fuera de una búsqueda por prefijo — el comportamiento correcto. Confirmarlo con un test, no por lectura.
- [ ] 9.3 Verificar que los filtros de `status`, `severity` y rango de fechas siguen alcanzando a un evento con `path` nulo. No hay razón para que no, pero es la clase de regresión que un `JOIN` o un `WHERE` implícito introduce sin avisar.
- [ ] 9.4 Buscar en `backend/` cualquier otro consumidor que asuma `Event.path` no nulo (serializadores de alertas, payload de notificaciones a n8n, `audit_log`). Si aparece uno, resolverlo en esta change; si no aparece ninguno, dejarlo asentado en el reporte de apply.

## 10. Tests del backend

- [ ] 10.1 Test: la ingesta de un payload sin `path` crea una fila con `path IS NULL`, y explícitamente **no** con `path = ''`. Afirmar las dos cosas: la segunda es el defecto que se está arreglando.
- [ ] 10.2 Test: dos `detection_gap` consecutivos coexisten en la tabla, ninguno queda en `superseded`, y ninguno tiene `parent_event_id`. Es la regresión que protege el dato que D50/RN-144 existe para preservar.
- [ ] 10.3 Test: la ingesta de un evento sin `path` **no** invoca `determine_severity_for_path` (parchearla y afirmar cero llamadas) y produce `severity = high`.
- [ ] 10.4 Test: un evento sin `path` con `action="alert_only"` ingresa con `status = alert_only`, `resolved_at = received_at` y `resolved_by IS NULL`.
- [ ] 10.5 Test: `event_type` del payload llega a la columna; un `event_type` desconocido se persiste literal sin registrar rechazo en `rejected_events_audit`; un payload sin `event_type` ingiere con el default.
- [ ] 10.6 Test de no-regresión: la cadena de supersesión para eventos **con** ruta sigue comportándose exactamente igual, incluidos los dos escenarios de carrera de `service.py:190-205`. Correr los tests existentes de `backend/tests/test_event_service.py` y `test_event_consumer_c11.py` sin modificarlos.
- [ ] 10.7 Test de API: `GET /events` incluye `event_type` en cada ítem; un evento sin ruta aparece con `path: null` cuando no hay `path_prefix` y desaparece cuando lo hay; `GET /events/{id}` sobre un evento sin ruta responde `200` con `path: null` sin fallar la serialización.
- [ ] 10.8 Correr la suite completa del backend y confirmar que las **550 pruebas** existentes siguen pasando. Una caída acá es señal de un consumidor de `path` que la tarea 9.4 no encontró.

## 11. Frontend

- [ ] 11.1 En `frontend/src/api/events.ts`, agregar `event_type: string` a `EventListItem` y cambiar `path: string` a `path: string | null`. Comentar citando D51/RN-145, en el mismo estilo que los comentarios de `is_symlink` y `action_error` que ya están en el archivo.
- [ ] 11.2 En `frontend/src/components/ui/EventsTable.tsx:134`, ramificar la celda de ruta sobre **`event_type`**, no sobre `path === null` (D-10 del design): el tipo produce una etiqueta legible ("brecha de detección") en vez de un hueco. Mantener el `<Link>` a `/events/:id` — la fila sigue siendo navegable.
- [ ] 11.3 Dar a la etiqueta un tratamiento visual propio, en la línea de la insignia `symlink` que ya existe en `EventsTable.tsx:136-144`. **Prohibido** renderizar un guion, una cadena vacía o `path ?? '—'`: el punto de la decisión es que la ausencia se lea como información, no como un dato faltante.
- [ ] 11.4 En `frontend/src/pages/EventDetail.tsx:89`, sustituir la fila de ruta por la del tipo de evento y su causa cuando `path` es nulo. Verificar que la vista no lanza error al renderizar.
- [ ] 11.5 Verificar que `processContextLabel` (`EventsTable.tsx:29-35`) ya omite el bloque completo cuando los tres campos de proceso son nulos. **No debería requerir cambios** — es el comportamiento que D49/RN-143 necesita. Si los requiere, es información sobre un supuesto roto.
- [ ] 11.6 Tests con el arnés jsdom + Testing Library que la change 44 dejó: una fila con `path: null` y `event_type: "detection_gap"` muestra la etiqueta y sigue enlazando al detalle; una fila con ruta renderiza igual que antes; el detalle de un evento sin ruta no rompe; el bloque de proceso se omite con los tres campos nulos.
- [ ] 11.7 Actualizar cualquier fixture de test del frontend que construya un `EventListItem` (por ejemplo `EventsTable.test.tsx` y `BulkActionBar.test.tsx`, que usan `makeItem`) para incluir `event_type`. Es mecánico, pero sin él el typecheck falla.
- [ ] 11.8 Correr `tsc --noEmit` y la suite de tests del frontend.

## 12. Documentación y cierre

- [ ] 12.1 Verificar que las correcciones a `docs/arquitectura_stack.md` ya aplicadas siguen siendo consistentes con lo implementado: la precisión sobre qué entrega `struct fanotify_event_metadata`, la aclaración de que el sistema usa `FAN_CLASS_NOTIF` exclusivamente, y la fila 3 de la tabla de limitaciones reescrita según D50/RN-144.
- [ ] 12.2 Verificar que `CHANGES.md` — Change 51 refleja lo efectivamente implementado. Si el alcance cambió durante el apply, actualizar la entrada: el roadmap es índice, no historia.
- [ ] 12.3 Correr `python3 scripts/check_spec_integrity.py` antes y después de cualquier archive (D47/RN-141, sección MANDATORIA de `CLAUDE.md`).
- [ ] 12.4 **Re-correr las baterías del Capítulo 5** contra el sistema migrado y regenerar `resultados/`. Los datos actuales corresponden al esquema previo a la migración `012` y a un agente que atribuía a root la atribución no resuelta: toda afirmación de la tesis sobre la fiabilidad de la atribución de procesos medida sobre ellos es insostenible. **Es condición para reportar**, no una mejora opcional de los números.
- [ ] 12.5 Documentar en el reporte de apply cualquier consumidor de `Event.path` encontrado en 9.4 que no estuviera previsto, y cualquier suposición que haya aparecido y no esté cubierta por D49/RN-143, D50/RN-144 ni D51/RN-145. En ese caso **detener el flujo** y cerrar la decisión en el appendix correspondiente antes de continuar.
