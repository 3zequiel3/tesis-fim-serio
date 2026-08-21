## Context

`FanotifyDetector._process_event` (`agent/detector.py:456-730`) es un método con tres ramas, elegidas por `_classify_event` a partir de la máscara del evento:

| Rama | Máscaras | Descarta si el hash no cambió |
|---|---|---|
| `file_deleted` | `FAN_DELETE`, `FAN_MOVED_FROM` | no aplica (no hay hash) |
| `file_created` | `FAN_CREATE`, `FAN_MOVED_TO` | **no** |
| resto (`file_modified` / `file_absent`) | `FAN_CLOSE_WRITE` y sin clasificar | **sí** (`:620-621`) |

Las dos ramas que producen un hash tratan la igualdad con el baseline de manera opuesta. Esa asimetría, combinada con que `os.replace` entrega `FAN_MOVED_TO` sobre el path final, cierra el ciclo descrito en el [proposal](proposal.md).

Tres hechos del código acotan el diseño y conviene tenerlos a la vista antes de decidir nada:

1. **Una restauración exitosa deja el baseline intacto.** `agent/detector.py:709` — `pass  # archivo restaurado, baseline anterior sigue siendo válido`. Es RN-33 implementada. Por lo tanto, cuando llega el `MOVED_TO`, `entry.hash` sigue siendo el hash conocido-bueno y `previous_hash` ya está en una variable local desde `:458-460`, calculada al inicio del método. **El arreglo no necesita ninguna lectura adicional de disco ni de baseline.**
2. **Las reglas se evalúan por path, no por tipo de evento.** `RulesCache.evaluate` matchea el path contra patrones glob; no recibe el `event_type`. D19 describe el loop como condicionado a "una regla `file_created + auto_restore` activa", pero esa condición no existe: **cualquier** regla `auto_restore` sobre el path — la que RN-30 describe como uso normal — alcanza para disparar el ciclo. El defecto es más amplio de lo que su propia decisión anticipó.
3. **El detector procesa los eventos en serie sobre un único event loop** (D8, modelo single-loop; `agent/detector.py:655-659` lo documenta). El `MOVED_TO` que produce la restauración se procesa necesariamente **después** de que la rama `file_modified` terminó de decidir sobre el baseline. No hay carrera que resolver.

## Goals / Non-Goals

**Goals:**

- Que la rama `file_created` / `MOVED_TO` honre el mismo invariante que la rama `file_modified`: sin cambio real, no hay evento.
- Que el ciclo detectar → restaurar → observar converja en una vuelta, de forma verificable con un test que cuente eventos.
- Que un `MOVED_TO` de un tercero que deja contenido idéntico al baseline deje de ser un falso positivo, con loop o sin él.
- Que la garantía cubra también la restauración iniciada por el operador (`restore_file`), y que eso se afirme con un test en vez de deducirse.
- Que los tests corran contra un filesystem real y un `DecisionEngine` real, porque mockear el filesystem es lo que escondió el defecto.

**Non-Goals:**

- No se introduce política nueva de remediación. Nada cambia en *cuándo* el agente decide restaurar ni en *qué* hace al restaurar.
- No se toca `agent/decision.py`, `agent/commands.py` ni `agent/baseline.py`.
- No se cambia el payload del evento, el contrato del stream ni el esquema de la base.
- No se implementa un cortacircuitos de remediación (ver "Open Questions").
- No se corrige la laguna equivalente de la rama `file_modified` (que no exige identidad de tipo de objeto), ni se puebla `hash_expected` en los eventos `file_created`.

## Decisions

### D-1 — El guard va en la rama `file_created`, después del hash y antes de reservar `event_id`

El predicado es el de `:620-621` trasladado al punto equivalente de la rama hermana: después del bloque que calcula `current_hash` (`:529-553`, con el tratamiento symlink-as-object de D33/RN-127 y el contador `hardlink_suspected` intactos) y **antes** de `event_id = str(uuid.uuid4())` (`:554`).

Que vaya antes de la reserva de `event_id` no es cosmético. A partir de ahí el método muta `_pending` y `_event_to_path`, que son el índice de supersesión y el índice inverso para el ack O(1). Un descarte tardío tendría que deshacer esas mutaciones; un descarte temprano no las hace. Es exactamente la ubicación que ya tiene el descarte de la rama `file_modified` respecto de su propia reserva en `:653`.

El contador `hardlink_suspected` (`:545-553`) queda **antes** del guard, y por lo tanto sigue incrementándose para un evento suprimido. Es correcto: es un contador detective sobre el estado del filesystem (D33/RN-127 lo define explícitamente como "sin cambio de comportamiento"), no un derivado del evento publicado.

**Alternativa descartada — filtrar en `_classify_event`.** Hacer que `FAN_MOVED_TO` deje de clasificarse como `file_created` rompería la detección legítima de un archivo que aparece por rename, que es un vector real de persistencia. El problema nunca fue la clasificación; fue la ausencia del descarte.

**Alternativa descartada — descartar en `DecisionEngine`.** Que el motor se niegue a restaurar dos veces seguidas el mismo path arreglaría el loop pero dejaría intacto el falso positivo del caso general (un tercero que hace write-and-rename), que existe con o sin regla `auto_restore`. El invariante pertenece al detector, que es quien decide qué es un cambio.

### D-2 — La igualdad de hash se acompaña de identidad de tipo de objeto

Se suprime si y solo si:

- `current_hash is not None` y `current_hash == previous_hash`, **y**
- el path es symlink hoy si y solo si lo era en el baseline (`is_symlink == (entry.symlink_target is not None)`).

La segunda condición es defensiva y solo puede hacer el filtro **más estricto**, nunca más permisivo: en el peor caso emite un evento que se podría haber suprimido. Bajo D33/RN-127 el hash de un symlink es `sha256(os.readlink(path))` y el de un archivo regular es el de su contenido; que coincidan a través de un cambio de tipo requiere una colisión de SHA-256. Pero un cambio de tipo *es* una violación de integridad — un archivo regular reemplazado por un symlink es un vector de escape conocido, que es precisamente lo que D33 vino a cubrir — y no corresponde que la única barrera sea la improbabilidad de una colisión.

`was_symlink` ya se calcula en `:462` para la rama de borrado. El guard reusa esa variable; no agrega I/O.

**Nota de asimetría, deliberada:** el predicado de `:620-621` no exige identidad de tipo. Se deja como está (ver Non-Goals): tocarlo cambia el comportamiento de un camino que este defecto no involucra, y merece su propio cambio con sus propios tests.

### D-3 — La auto-atribución por pid se descarta como mecanismo

El evento trae el pid del proceso causante (`agent/_fanotify.py:81`, `:246`, `:256`), así que suprimir por `fan_event.pid == os.getpid()` sería una línea. Se descarta por cuatro razones, en orden de peso:

1. **Crea un punto ciego sobre todas las escrituras del propio agente.** Un FIM que no registra una clase entera de escrituras a paths monitoreados — la de su propio proceso, que corre con `CAP_SYS_ADMIN`, `CAP_DAC_OVERRIDE`, `CAP_FOWNER` y `CAP_CHOWN` (D36/RN-130) — pierde la propiedad que lo define. El sufijo `.fim_restore_tmp` de D19 ya es un punto ciego, pero acotado a un nombre de archivo específico y documentado como tal; extenderlo a "todo lo que escriba este pid" es otra magnitud.
2. **No arregla el falso positivo del caso general.** Un `MOVED_TO` de un tercero que deja contenido conocido-bueno sigue emitiendo. El defecto que se ve en producción es el loop, pero el defecto que está en el código es el falso positivo, y la atribución por pid no lo toca.
3. **Suprimiría eventos de los que depende la lógica de baseline.** La cuarentena usa `shutil.move` (`agent/decision.py:277`, `agent/commands.py:458`), hecho por el mismo pid. El `FAN_MOVED_FROM` resultante es lo que el detector traduce a `mark_absent` (`agent/detector.py:590`, `:711`). Un filtro por pid habría que acotarlo por acción, lo que reintroduce por la ventana la complejidad que pretendía evitar.
4. **El pid es reutilizable.** El evento se encola en `_raw_queue` y se procesa después; entre la producción y el consumo el pid puede haber sido reciclado. El riesgo es bajo, pero un mecanismo de supresión no debería depender de una condición de carrera benigna.

**El hash es un mejor mecanismo por una razón de fondo:** es una afirmación sobre el *estado del archivo*, que es lo que el FIM protege, y no sobre *quién lo escribió*, que es contexto forense. El invariante correcto —"si el contenido es el conocido-bueno, no hay violación de integridad"— no menciona al autor.

### D-4 — No hay decisión nueva de appendix; RN-117 se enmienda para decir lo que su motivación ya decía

La regla que se hace cumplir ya está escrita, en tres lugares:

- **RN-32** obliga a verificar que el SHA-256 del archivo restaurado coincide con el del baseline, y `_auto_restore` lo hace (`agent/decision.py:267-268`).
- **RN-33** dice por qué no se toca el baseline: "ya contiene el hash correcto, **que es el mismo del archivo restaurado**".
- **D19 / RN-117** nombra el `FAN_MOVED_TO` sobre el path final como el disparador del loop infinito, en su propia sección de Motivación.

El arreglo es la conjunción de las tres: si RN-33 garantiza que los hashes son iguales, y D19 identifica el evento que los observa, el descarte no es una política nueva sino la consecuencia. **No corresponde abrir D39.** Lo que corresponde es que la letra de RN-117 —hoy limitada al filtro de sufijo— exija las dos mitades del mecanismo, para que la próxima lectura de la regla no vuelva a implementar solo la mitad que estaba en el "Resultado". La enmienda es documental: no altera `Condición` ni `Excepciones`, no cambia el número de la regla, no agrega vocabulario.

**Alternativa considerada — abrir D39 igualmente, "por prolijidad".** Se descarta: inflaría el appendix con una decisión cuyo contenido sería la repetición de RN-33, y devaluaría el appendix como registro de suposiciones realmente abiertas. El appendix existe para cerrar lo que no está decidido; esto ya lo estaba.

### D-5 — `commands.py` queda cubierto por construcción, y el test lo afirma en vez de asumirlo

`handle_restore_file` (`agent/commands.py:349-384`) reproduce `_auto_restore` casi literalmente: mismo `tmp_path` con sufijo `.fim_restore_tmp`, mismo `O_EXCL`, mismo `fchown` antes de `fchmod` (D36/RN-130, D-6), mismo `os.replace`, misma verificación `hash_mismatch_after_restore`. El evento que emite es el mismo `FAN_MOVED_TO` sobre el mismo path final, y lo consume el mismo `_process_event`. **El arreglo del detector lo cubre sin tocar `commands.py`.**

Que la cobertura sea estructural no la vuelve verificada. La duplicación entre `decision.py` y `commands.py` está documentada como deliberada (`agent/commands.py:323-326`), y una divergencia futura entre las dos copias —por ejemplo, un tmp con otro sufijo— rompería la garantía en silencio. El test de la restauración por comando existe para que esa divergencia falle ruidosamente.

`handle_quarantine_file` no está en la misma situación y no se toca: su `shutil.move` produce un `FAN_MOVED_FROM` que representa una ausencia **real** del archivo. No es un falso positivo, y no realimenta, porque la entry queda `absent` y `select_restorable_content` devuelve `None` para entries `absent` (`agent/baseline.py:387`), de modo que un `auto_restore` posterior falla con `no_restorable_content` en lugar de reintentar.

### D-6 — Un evento suprimido no escribe baseline, no toca `_pending` y no supersede

Simetría exacta con `:620-621`: el `return` temprano no llama a `write_entry` ni a `add_snapshot`. Es lo correcto por dos motivos independientes:

- Por definición del guard, la entry ya contiene el hash observado. Reescribirla sería trabajo de cifrado AES-GCM sin efecto.
- El evento `file_modified` original —el de la adulteración— sigue siendo el pendiente de ese path en `_pending`, con `action: auto_restore` y, por D35/RN-129, `status: auto_restored` del lado del backend. Es el evento que el operador debe ver. Si el `MOVED_TO` reservara un `event_id` nuevo lo supersedería, y la traza de la adulteración quedaría reemplazada por la traza de la reparación.

Lo mismo aplica a los metadatos: si la restauración cambió `mode`, `uid` o `gid` respecto de lo que el baseline tenía, no es el guard quien debe notarlo — `_auto_restore` restaura esos tres campos **desde** la entry (D36/RN-130, D-6), así que por construcción coinciden.

### D-7 — Arquitectura de los tests: filesystem real, motor real, transporte simulado

La línea se traza en un solo lugar: **lo que se simula es el transporte y la fuente de eventos del kernel; nunca el filesystem ni el baseline.**

- **Real**: `BaselineEngine` sobre `tmp_path` con secreto de prueba, `RulesCache` con una regla `auto_restore`, `DecisionEngine` con `JournalManager` real, y los `os.open` / `os.replace` verdaderos de `_auto_restore`. Los archivos se escriben y se renombran de verdad.
- **Simulado**: el `Publisher`, reducido a un colector de payloads (es un cliente de red, no un hecho del filesystem), y el arribo de eventos, que se inyecta llamando `_process_event(FanotifyEvent(path=..., mask=...))` con las constantes reales de `agent/_fanotify.py`. `fanotify` requiere `CAP_SYS_ADMIN` y no está disponible en CI; inyectar en `_process_event` es el mismo punto de entrada que usan los tests existentes (`agent/tests/test_detector_discard.py:39`) y no elude nada del código bajo prueba.

**El test debe afirmar que la restauración ocurrió, antes de afirmar que no hubo evento.** Es la parte que no puede omitirse: "no se publicó nada" también es cierto cuando la restauración **falla**, que es exactamente el estado en que vivió el sistema hasta la change 41. Un test que solo cuenta eventos habría pasado en verde durante todo ese período sin ejercitar una sola línea del camino que importa. El orden de las aserciones es: contenido del archivo en disco == contenido conocido-bueno → journal en `completed` → cero payloads publicados por el `MOVED_TO`.

**La cota de eventos se prueba con una bomba de eventos acotada.** Un pump que, tras cada `_process_event`, reinyecta el `FAN_MOVED_TO` correspondiente cuando el motor efectivamente restauró — que es lo que haría el kernel — y que corre con un **techo duro de iteraciones que hace fallar el test si se alcanza**. Con el defecto presente el pump no termina; el techo convierte un cuelgue de CI en un fallo legible. Con el arreglo, N adulteraciones producen exactamente N payloads.

**El guard necesita su prueba negativa.** Un filtro que suprime de más es indistinguible de uno correcto si solo se prueban los casos que debe suprimir. Por cada escenario de supresión hay uno simétrico que debe emitir: mismo `MOVED_TO` con contenido **distinto** del baseline → un evento `file_created`; y `MOVED_TO` sobre un path que el baseline registra como symlink y ahora es archivo regular → un evento, aunque los hashes coincidan (D-2).

### D-8 — El invariante se especifica como propiedad del detector, no de la rama

Los deltas de spec no dicen "la rama `file_created` descarta si el hash coincide": dicen que **toda clasificación que produce un hash** descarta cuando ese hash coincide con el del baseline y el tipo de objeto no cambió. Es la formulación que sobrevive a que mañana aparezca una cuarta rama —`FAN_ATTRIB` está en el backlog— sin que haya que recordar agregarle el descarte. La rama `file_deleted` queda explícitamente fuera porque no produce hash: la ausencia de un archivo nunca es "sin cambio".

## Risks / Trade-offs

- **[Un cambio real queda sin reportar por colisión de SHA-256]** → Requeriría una preimagen de SHA-256. Es el mismo supuesto criptográfico sobre el que ya descansa todo el baseline (RN-32, D19) y la rama `file_modified` desde el primer día. No se agrega superficie.
- **[El guard se aplica a `FAN_CREATE` además de a `FAN_MOVED_TO`]** → Deseado, no colateral. Un `FAN_CREATE` sobre un path con entry de baseline `present` y contenido idéntico es el mismo falso positivo por otra máscara. El caso que importa —recrear un archivo previamente borrado— no se suprime: `mark_absent` deja `hash=None` (`agent/baseline.py:351-360`), y `None == current_hash` es falso para cualquier hash real.
- **[Una restauración desde snapshot podría dejar un hash distinto de `entry.hash`, y entonces el guard no suprime]** → Reachability analizada y descartada. `select_restorable_content` (`agent/baseline.py:187-196`) devuelve el contenido activo con `entry.hash`, o el snapshot más reciente con `snap.hash`. Los snapshots los crea `add_snapshot`, que archiva el contenido activo y por lo tanto nace con `snap.hash == entry.hash`; y `entry.hash` solo cambia por `write_entry`, que escribe hash y contenido juntos. Llegar a una divergencia exige una entry con `content_b64 = None` y `hash` no nulo (caso `oversize`), en cuya cadena de snapshots tampoco hay contenido — con lo que la restauración falla con `no_restorable_content` antes de escribir nada. **Residual aceptado**: si esa combinación se volviera alcanzable por un cambio futuro en el baseline, el loop reaparecería. Es lo que un cortacircuitos acotaría, y está registrado en Open Questions.
- **[Un `expected_hash` vacío desactiva la verificación post-restauración]** → `select_restorable_content` devuelve `entry.hash or ""` (`:188`), y tanto `_auto_restore` (`agent/decision.py:268`) como `handle_restore_file` (`agent/commands.py:382-383`) verifican bajo `if expected_hash and ...`. Con `entry.hash = None` la verificación de RN-32 se saltea en silencio. **No se corrige acá** —es un defecto de `baseline.py` que este arreglo no introduce ni empeora— pero se deja anotado: es el único camino conocido por el que una restauración puede reportar éxito sin cumplir RN-32, y por lo tanto sin cumplir la premisa del guard.
- **[El operador deja de ver el evento de su propia restauración por comando]** → Correcto y buscado. El resultado de un `restore_file` ya llega al backend por el `event_ack` del handler (`agent/commands.py:395-399`), con su razón en el vocabulario cerrado de D36/RN-130. Un evento `file_created` adicional sobre el mismo path sería una segunda notificación del mismo hecho, presentada como si fuera una detección.
- **[Menos eventos publicados podría leerse como una regresión de detección]** → Se mitiga con las pruebas negativas de D-7: todo escenario de supresión tiene un gemelo que debe emitir. La cota que se prueba es "a lo sumo N", con un piso de N verificado en el mismo test.

## Migration Plan

No hay migración. Un solo archivo de producción cambia (`agent/detector.py`), sin estado persistido, sin esquema, sin contrato de red.

- **Despliegue**: reemplazar el código del agente y reiniciar el servicio. Sin orden respecto del backend; sin ventana.
- **Compatibilidad**: total en ambas direcciones. Un backend de cualquier versión simplemente deja de recibir eventos que no debían existir.
- **Rollback**: revertir el commit y reiniciar. El único efecto de volver atrás es que el defecto vuelve.
- **Efecto operativo del despliegue**: si hay agentes corriendo con reglas `auto_restore` activas, el backlog acumulado en `/var/lib/fim-agent/queue/` drena después del reinicio y el backend va a recibir esa cola. El arreglo corta la generación, no purga lo ya encolado. Vaciar la cola a mano es una decisión del operador, no un paso de esta change.

## Open Questions

1. **Cortacircuitos de remediación acotado por path — requiere cerrar una decisión primero.** Un contador por path de acciones automáticas en una ventana deslizante, que suspende la remediación y emite un diagnóstico al superarse, acotaría cualquier realimentación futura y no solo esta. Es la defensa en profundidad que de verdad corresponde —más que la atribución por pid, ver D-3— pero **introduce política nueva**: qué hace el agente cuando decide dejar de remediar, cómo se entera el operador, y si la suspensión se rearma sola o requiere intervención, no está en RN-30..RN-33 ni en ningún appendix. Debe cerrarse como decisión de implementación antes de proponerse como change. **No se implementa acá.**
2. **`entry.hash` nulo con contenido restaurable** (ver Risks): ¿corresponde que `select_restorable_content` falle en vez de devolver `""` como `expected_hash`, convirtiendo un salteo silencioso de RN-32 en un error explícito? Es un cambio en `agent/baseline.py` con su propio blast radius; se deja planteado para el trabajo de robustez del baseline.
3. **Identidad de tipo de objeto en la rama `file_modified`**: el guard de `:620-621` no la exige, y por consistencia debería. Es una supresión que hoy puede ocurrir a través de un cambio de tipo con hashes coincidentes. Mismo razonamiento que D-2, distinto camino de código y distintos tests; se deja como follow-up declarado.
