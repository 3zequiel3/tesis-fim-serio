## 1. El guard en el detector (`agent/detector.py`) — único cambio de producción

- [x] 1.1 En la rama `if event_class == "file_created":` (`:527`), insertar el descarte **después** del bloque que calcula `current_hash` (rama symlink en `:531-540`, rama regular en `:541-553`, incluido el contador `hardlink_suspected`) y **antes** de `event_id = str(uuid.uuid4())` (`:554`). No mover ni reordenar nada del bloque de hash: el contador detective de D33/RN-127 debe seguir incrementándose para eventos suprimidos.
- [x] 1.2 El predicado del descarte es la conjunción de dos condiciones, no una: `current_hash is not None and current_hash == previous_hash` **y** `is_symlink == was_symlink`. Las dos variables de la derecha ya existen en el scope (`previous_hash` en `:459`, `was_symlink` en `:462`); no agregar lecturas de baseline ni de disco.
- [x] 1.3 El descarte es un `return` desnudo, exactamente como el de `:620-621`. NO llamar a `write_entry`, `write_symlink_entry`, `add_snapshot` ni `mark_absent`, y NO tocar `_pending` ni `_event_to_path`. Verificar leyendo el diff que ninguna de esas cinco llamadas queda del lado del `return`.
- [x] 1.4 Emitir un log de nivel `debug` (no `info`) en el descarte, con `path` y `event_class`, para que un operador que investigue un silencio pueda distinguir "suprimido por invariante" de "nunca llegó el evento". `info` haría ruido proporcional al tráfico que el guard existe para eliminar.
- [x] 1.5 Documentar el guard con un comentario que cite **D19/RN-117 y RN-33**, y que diga explícitamente que es la segunda mitad del mecanismo cuya primera mitad es el filtro de sufijo de `:457`. El comentario debe nombrar `os.replace` y `FAN_MOVED_TO`, para que la próxima lectura del código no reconstruya el razonamiento desde cero.
- [x] 1.6 Confirmar que NO se toca `agent/decision.py`, `agent/commands.py` ni `agent/baseline.py`. Si el arreglo parece necesitar tocar alguno de los tres, detenerse: el diseño dice que no hace falta, y esa discrepancia es información.

## 2. Test de integración detector ↔ motor sobre filesystem real (el que habría atrapado el defecto)

- [x] 2.1 Crear `agent/tests/test_restore_feedback_loop.py`. Prohibido en este archivo: `MagicMock` para `BaselineEngine`, para el filesystem o para `DecisionEngine`. Lo único simulado es el publisher (colector de payloads) y el arribo de eventos.
- [x] 2.2 Escribir una fixture `restore_rig(tmp_path)` que arme, todo real: `BaselineEngine` con secreto de prueba sobre `tmp_path`, `RulesCache` con una regla `{"pattern": "<tmp_path>/**", "action": "auto_restore"}`, `JournalManager` sobre un `journal/` real, `DecisionEngine` con quarantine dir real, y un `FanotifyDetector` con `decision_engine=` ese motor. El publisher es una clase de test con `publish` async que acumula payloads en una lista.
- [x] 2.3 En la fixture, sembrar el baseline con `write_entry` sobre un archivo real de contenido conocido, y **verificar en la propia fixture** que `select_restorable_content(entry)` devuelve contenido no nulo con `expected_hash` no vacío. Si el rig no puede restaurar, todos los tests que siguen pasan en verde sin probar nada — es exactamente el modo de fallo que ocultó el defecto (razón 2 del proposal).
- [x] 2.4 Test `test_restore_moved_to_publishes_nothing`: adulterar el archivo en disco, inyectar `FanotifyEvent(path, mask=FAN_CLOSE_WRITE)`, y **antes de cualquier aserción sobre eventos** afirmar que (a) el contenido en disco volvió al conocido-bueno, (b) el journal del evento quedó en estado terminal `completed`, (c) `mode`, `uid` y `gid` del archivo coinciden con los de la entry (D36/RN-130). Recién entonces inyectar `FanotifyEvent(path, mask=FAN_MOVED_TO)` y afirmar que la lista de payloads **no creció**.
- [x] 2.5 Test `test_baseline_entry_survives_the_round_trip`: tras el ciclo de 2.4, releer la entry y afirmar que `hash`, `content_b64` y los tres campos de metadata son los originales. Es RN-33 como aserción ejecutable.
- [x] 2.6 Test `test_tamper_event_remains_the_pending_one`: tras el ciclo, afirmar que `detector._pending[path]` sigue siendo el `event_id` del evento `file_modified` de la adulteración, y que ese payload lleva `action: "auto_restore"` y `action_failed: false`.
- [x] 2.7 Usar las constantes reales de `agent/_fanotify` (`FAN_CLOSE_WRITE`, `FAN_MOVED_TO`, `FAN_CREATE`) para las máscaras. Nunca literales hexadecimales: si el módulo cambia una constante, el test debe seguirlo.

## 3. Test de cota de eventos (regresión del loop)

- [x] 3.1 Test `test_n_tampers_produce_at_most_n_events`: escribir una bomba de eventos que, tras cada `_process_event`, detecte si el motor efectivamente restauró (por el `action` / `action_failed` del payload o por observación del journal) y en ese caso reinyecte el `FAN_MOVED_TO` correspondiente — que es lo que haría el kernel.
- [x] 3.2 La bomba MUST correr con un techo duro de iteraciones (p. ej. `N * 4`) que haga **fallar** el test con un mensaje explícito al alcanzarse. Sin ese techo, reintroducir el defecto cuelga CI en vez de reportarlo.
- [x] 3.3 Con `N = 5` adulteraciones reales, afirmar `len(published) == 5`, no `<= 5`: la cota superior sola pasaría también con un guard que suprime de más. El piso y el techo se afirman juntos.
- [x] 3.4 Test `test_failed_restore_emits_once_and_does_not_loop`: armar el rig con una entry cuyo `content_b64` sea `None` y sin snapshots restaurables, adulterar, inyectar el `CLOSE_WRITE`, y afirmar un único payload con `action_failed: true` y ningún `MOVED_TO` subsiguiente porque no hubo escritura.

## 4. Tests del falso positivo general y pruebas negativas del guard

- [x] 4.1 Test `test_third_party_atomic_rename_of_identical_content_is_silent`: sin regla `auto_restore` (default `alert_only`), escribir `<path>.other-tmp` con el contenido idéntico al baseline, hacer `os.replace` real hacia el path monitoreado, inyectar `FAN_MOVED_TO` y afirmar cero eventos. Es el caso general que existe con loop o sin él.
- [x] 4.2 Test `test_atomic_rename_of_different_content_emits_one_event`: idéntico a 4.1 pero con contenido distinto; afirmar exactamente un payload con `event_type: "file_created"`. Sin este test, 4.1 pasaría igual con un guard que suprime todo.
- [x] 4.3 Test `test_fan_create_of_identical_content_is_silent` y su gemelo con contenido distinto: mismo par, con `FAN_CREATE` en lugar de `FAN_MOVED_TO`.
- [x] 4.4 Test `test_type_change_is_not_suppressed`: sembrar la entry con `write_symlink_entry` (baseline dice symlink), reemplazar el path por un archivo regular cuyo contenido hashee **exactamente** al mismo valor que el string del destino del symlink original — construir el caso a mano: el contenido del archivo es literalmente ese string. Inyectar `FAN_MOVED_TO` y afirmar que **sí** se publica un evento. Es la única prueba de la mitad "identidad de tipo" del predicado (D-2 del design).
- [x] 4.5 Test `test_recreated_after_delete_is_not_suppressed`: `mark_absent(path)` y luego crear el archivo con el contenido original; afirmar que se publica un `file_created`. Cubre que `hash=None` no colisiona con ningún hash real.
- [x] 4.6 Test `test_suffix_filter_still_applies`: inyectar un evento sobre `<path>.fim_restore_tmp` y afirmar cero eventos y cero lecturas de baseline. D19/RN-117 no se debilita.

## 5. Tests del camino del operador (`agent/commands.py`)

- [x] 5.1 Test `test_operator_restore_publishes_ack_and_no_event`: ejecutar `handle_restore_file` **real** contra el baseline y el filesystem reales del rig, afirmar que el contenido en disco es el conocido-bueno y que se publicó el `event_ack` de éxito; luego inyectar el `FAN_MOVED_TO` y afirmar cero eventos de integridad. Es la aserción que impide que una divergencia futura entre `decision.py` y `commands.py` rompa la garantía en silencio (D-5 del design).
- [x] 5.2 Test `test_operator_restore_failure_publishes_only_its_ack`: `restore_file` sobre un path sin contenido restaurable; afirmar `event_ack` con la razón, path sin modificar y cero eventos.
- [x] 5.3 Test `test_quarantine_still_reports_the_absence`: ejecutar `handle_quarantine_file` real, inyectar el `FAN_MOVED_FROM` y afirmar que **sí** se publica un `file_deleted`. Fija la asimetría deliberada: el guard cubre las clasificaciones que producen hash, y esta no produce ninguno.
- [x] 5.4 Test `test_auto_restore_on_absent_entry_fails_without_looping`: entry en `absent`, regla `auto_restore`, evento nuevo sobre el path; afirmar un único evento con `action_failed: true` y razón `no_restorable_content`, sin mutación del filesystem.

## 6. No-regresión de la suite existente

- [x] 6.1 Correr la suite completa del agente y confirmar que los 417 tests previos siguen pasando. Cualquier test que ahora falle porque **esperaba** un evento en un `MOVED_TO` de contenido idéntico es un test que codificaba el defecto: corregirlo explícitamente y anotar cuál era en el mensaje del commit, no ajustarlo en silencio.
- [x] 6.2 Verificar en particular `agent/tests/test_detector_discard.py`, `test_detector_multi_event.py`, `test_symlink_hardening.py`, `test_scope_filter.py` y `test_restore_metadata.py`, que son los que tocan las ramas afectadas.
- [x] 6.3 Correr la suite del backend. No debería verse afectada — no se toca ningún archivo suyo —; si algo falla, es señal de acoplamiento no documentado y hay que reportarlo antes de seguir.

## 7. Verificación manual en el laboratorio (no simulable en tests unitarios)

- [x] 7.1 En el laboratorio Docker con el agente desplegado como servicio systemd (con las capabilities y el drop-in de `ReadWritePaths` de la change 41), sembrar una regla `auto_restore` sobre el prefijo de watch y modificar **un** archivo una sola vez.
- [x] 7.2 Afirmar el resultado contra la línea base del incidente: **un** evento para ese path, no 497; y la cola del agente sin crecimiento sostenido, no 3240 entradas. Registrar los dos números medidos.
- [x] 7.3 Confirmar que el archivo quedó restaurado en disco con su modo, dueño y grupo originales, y que el evento llegó al backend con estado `auto_restored` (D35/RN-129).
- [x] 7.4 Confirmar que el agente sigue detectando archivos **nuevos** durante y después del ejercicio — la consecuencia operativa del incidente fue que dejó de hacerlo, y esa es la propiedad que hay que ver recuperada.
- [x] 7.5 Ejercitar el camino del operador de punta a punta: aprobar un evento desde la UI para disparar `restore_file`, y confirmar que llega el ack y que no aparece un evento espurio sobre el mismo path.

## 8. Documentación canónica

- [x] 8.1 En `docs/reglas_de_negocio.md`, enmendar el **Resultado** de D19 / RN-117 (`:986`) para que exija las dos mitades del mecanismo: el filtro de sufijo para los eventos del tmp, y el descarte por hash con identidad de tipo de objeto para el `FAN_MOVED_TO` del path final. NO cambiar el número de la regla, ni su `Condición`, ni sus `Excepciones`, ni la `Limitación conocida`.
- [x] 8.2 En el mismo bloque, corregir la afirmación de la Motivación de que el loop requiere "una regla `file_created + auto_restore` activa": las reglas se evalúan por path y no por tipo de evento, así que **cualquier** regla `auto_restore` sobre el path lo dispara.
- [x] 8.3 Replicar ambas correcciones en la D19 de `docs/arquitectura_stack.md` (`:2204`), manteniendo las dos versiones consistentes entre sí.
- [x] 8.4 **NO** agregar una decisión D39 al appendix "Decisiones de implementación — Abril 2026", **NO** tocar su párrafo introductorio y **NO** agregar RN-133. El arreglo hace cumplir RN-32, RN-33 y D19, que ya están cerradas; ver D-4 del design. Si durante la implementación aparece una suposición que estas tres no cubren, detenerse y cerrarla en el appendix antes de seguir.

## 9. Roadmap y cierre

- [x] 9.1 En `CHANGES.md`, agregar la fila del change 43 a la tabla resumen, inmediatamente después de la del 42. **Hecho en la fase propose.**
- [x] 9.2 En `CHANGES.md`, agregar la sección detallada `### Change 43 — agent-restore-feedback-loop` después de la sección del 42 y antes del `---` que precede a `## Decisiones de implementación cerradas — Abril 2026`, con la plantilla del 42 y los follow-ups declarados. **Hecho en la fase propose.**
- [x] 9.3 Al cerrar la implementación, actualizar el `**Done**:` de esa sección con los dos números realmente medidos en 7.2, en lugar de la formulación prospectiva. El roadmap debe registrar el resultado, no la intención.
- [ ] 9.4 Commit con conventional commits, sin `Co-Authored-By`. El cuerpo debe mencionar los números del incidente (497 eventos / 3240 encolados) y por qué la suite de 417 tests no lo vio: es la parte que se pierde si solo queda el diff.
