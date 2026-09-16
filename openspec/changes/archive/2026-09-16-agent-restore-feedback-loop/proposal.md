## Why

`auto_restore` se retroalimenta. Una sola modificación a un archivo bajo una regla `auto_restore` produjo **497 eventos sobre ese único path en 4,7 minutos** y dejó **3240 eventos encolados** en el agente, que dejó de detectar archivos nuevos por completo. Quitar la regla cortó la generación; el backlog tardó minutos en drenar. No es un riesgo teórico: se reprodujo en el laboratorio Docker.

**La raíz es una asimetría entre dos ramas hermanas del mismo método.** `_process_event` clasifica y bifurca:

1. `DecisionEngine._auto_restore` escribe en `path + ".fim_restore_tmp"` (`agent/decision.py:227`) y cierra con `os.replace(tmp_path, path)` (`agent/decision.py:259`).
2. El detector filtra los eventos cuyo path **termina** en `.fim_restore_tmp` (`agent/detector.py:457`). Eso cubre las escrituras del tmp, pero **no** el `FAN_MOVED_TO` que `os.replace` entrega sobre el path **final**, que no lleva el sufijo.
3. `FAN_CREATE` **o** `FAN_MOVED_TO` se clasifican como `file_created` (`agent/detector.py:451-452`).
4. La rama `file_modified` descarta cuando no cambió nada (`agent/detector.py:620-621`):
   ```python
   # Descartar si el contenido no cambió
   if current_hash is not None and current_hash == previous_hash:
       return
   ```
   La rama `file_created` (`agent/detector.py:527` en adelante) hashea y emite **incondicionalmente**: nunca compara contra el baseline. Una restauración que deja contenido **idéntico al baseline** se reporta igual como cambio, el motor de reglas vuelve a ver `auto_restore`, y vuelve a restaurar.

El ciclo se cierra porque la restauración exitosa **no toca el baseline** — `agent/detector.py:709` deja `pass  # archivo restaurado, baseline anterior sigue siendo válido`. La entry conserva el hash conocido-bueno, el archivo en disco vuelve a ese mismo contenido, y la rama que lo observa es precisamente la que no mira el hash previo. Cada vuelta cuesta un evento publicado, una escritura atómica y una entrada de journal.

**No es una suposición nueva: es una decisión ya cerrada y mal implementada.** D19 / RN-117 (`docs/reglas_de_negocio.md:986`, `docs/arquitectura_stack.md:2204`) nombra este loop en su propia **Motivación**, palabra por palabra:

> Sin este filtro, cada restauración genera eventos espurios (FAN_CREATE, FAN_CLOSE_WRITE, FAN_MOVED_FROM para el tmp) que contaminan el baseline y el backend. **Con una regla `file_created + auto_restore` activa, el FAN_MOVED_TO que emite `os.replace` dispara una nueva restauración, generando un loop infinito.**

La decisión identificó el `FAN_MOVED_TO` sobre el path final como el disparador, y sin embargo el mecanismo que se implementó — el filtro de sufijo — no lo alcanza por construcción: el path final nunca termina en `.fim_restore_tmp`. Esta change no introduce política; **termina de implementar D19 / RN-117** y hace explícito en la letra de la regla el invariante que su motivación ya daba por sentado.

**El predicado del arreglo no es una invención: es RN-33 leído literalmente.** RN-32 obliga a verificar, después de restaurar, que el SHA-256 del archivo restaurado coincide con el hash del baseline — y `_auto_restore` lo hace (`agent/decision.py:267-268`, `hash_mismatch_after_restore`). RN-33 cierra el razonamiento diciendo por qué el baseline no se toca:

> El baseline permanece intacto (ya contiene el hash correcto, **que es el mismo del archivo restaurado**).

Es decir: las reglas de negocio ya afirman que, tras una restauración exitosa, `hash(archivo) == hash(entry_baseline)`. El detector observa ese archivo un instante después y, en la rama `file_created`, reporta un cambio de integridad sobre un par de hashes que RN-33 declara idénticos. La condición de descarte que falta es exactamente la negación de lo que RN-32 y RN-33 ya garantizan.

**El defecto es además un falso positivo del caso general, con loop o sin él.** Un `MOVED_TO` cuyo hash resultante es igual al del baseline no es una violación de integridad. Hoy cualquier proceso del sistema que haga escritura atómica y rename dejando contenido conocido-bueno — un gestor de configuración que reaplica su estado, un `install`, un despliegue idempotente — genera un evento `file_created` que el operador tiene que revisar a mano. Corregir la rama corrige las dos cosas de una sola vez.

### Por qué una suite de 417 tests del agente no lo vio

Vale la pena registrarlo: son cuatro razones independientes, y ninguna sola alcanza para explicarlo.

1. **Los tests unitarios mockean el baseline y el motor.** `agent/tests/test_detector_discard.py` — el test que cubre exactamente este invariante en la rama hermana — usa `baseline = MagicMock()` con un `entry_mock.hash` fijo (`:19-22`). Los tests de decisión (`agent/tests/test_decision.py`) sí escriben en un `tmp_path` real, pero mockean el baseline (`:49`) y **nunca devuelven la mutación del filesystem al detector**. Cada unidad está probada; la propiedad que falla es la del acople entre las dos.
2. **La unidad systemd hacía imposible la restauración.** Antes de la change 41 (commit `af25c50`), `agent/deploy/fim-agent.service` tenía `ProtectSystem=strict` con `ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent` — los watch paths quedaban read-only — y `AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH`, sin `CAP_DAC_OVERRIDE`, `CAP_FOWNER` ni `CAP_CHOWN`. `os.open(tmp_path, O_CREAT|O_WRONLY|O_EXCL)` fallaba con `EROFS` antes de llegar a `os.replace`. El camino de código nunca se ejecutó en producción.
3. **Las corridas de medición del capítulo 5 usaron `alert_only` a propósito.** `docs/plan_medicion_cap5.md:25` (P6) siembra las reglas del laboratorio "ambas con acción `alert_only` para no inyectar cambios ajenos al manifiesto", y `scripts/seed-reglas-lab.sh:27-31` lo documenta explícitamente. El único escenario de carga sostenida que existía estaba, por diseño, fuera del camino que falla.
4. **La change 41 (`agent-deployment-caps`) es la que desbloqueó la restauración** — y por lo tanto la que expuso el defecto. El commit `af25c50` agregó las capabilities de remediación y derivó `ReadWritePaths` desde los watch paths. El bug es tan viejo como D19; recién ahora hay un entorno donde puede correr.

## What Changes

- **La rama `file_created` / `MOVED_TO` honra el mismo invariante que la rama `file_modified`: sin cambio real, no hay evento.** Tras calcular `current_hash` (con el tratamiento symlink-as-object de D33/RN-127 intacto) y antes de reservar `event_id` o tocar `_pending`, el detector compara contra el hash del baseline y descarta si son iguales. Es el mismo predicado de `agent/detector.py:620-621`, aplicado en el punto equivalente de la rama hermana.
- **La igualdad exige también identidad de tipo de objeto.** Se suprime solo si el hash coincide **y** el path es symlink hoy si y solo si lo era en el baseline (`entry.symlink_target is not None`). Un cambio de tipo es una violación de integridad aunque los hashes coincidan, y el guard solo puede hacer el filtro más estricto, nunca más permisivo. D33/RN-127 se preserva sin excepción: el hash de un symlink sigue siendo el del **string** del destino, jamás el de su contenido.
- **Se descarta la auto-atribución por pid como mecanismo.** El evento trae `pid` (`agent/_fanotify.py:246`, `:256`), así que suprimir por `fan_event.pid == os.getpid()` sería trivial de escribir. Se rechaza: crearía un punto ciego sobre **todas** las escrituras del propio agente — exactamente lo que un FIM no debe tener —, no arregla el falso positivo del caso general, y suprimiría también el `FAN_MOVED_FROM` que produce el `shutil.move` de la cuarentena, del que depende la lógica de `mark_absent` (`agent/detector.py:590`, `:711`). Ver D-2 del design.
- **RN-117 se enmienda para que el invariante esté en la letra, no solo en la motivación.** El texto de la regla pasa a exigir las dos mitades del mecanismo: el filtro de sufijo para los eventos del tmp **y** el descarte por hash para el `MOVED_TO` del path final. No es una decisión nueva; es la regla diciendo lo que su propia motivación ya decía.
- **Los handlers `restore_file` y `quarantine_file` quedan cubiertos por construcción — y se prueba que así sea.** `agent/commands.py:349-384` es un duplicado casi literal de `_auto_restore` (mismo tmp con `O_EXCL`, mismo `fchown` antes de `fchmod` por D36/RN-130 D-6, mismo `os.replace`, misma verificación `hash_mismatch_after_restore`). Emite el mismo `MOVED_TO` sobre el mismo path final y el arreglo del detector lo cubre sin tocar `commands.py`. Se agrega el test que lo afirma en vez de asumirlo.
- **Tests que hacen imposible que el defecto sobreviva.** Tres, y ninguno mockea el filesystem:
  - Un test que maneja el `DecisionEngine` **real** contra un filesystem temporal **real** y afirma que el `MOVED_TO` resultante **no** produce evento. Mockear el filesystem es precisamente lo que escondió esto durante toda la vida del proyecto.
  - Un test de regresión que **acota el conteo**: N modificaciones a un path bajo una regla `auto_restore` producen a lo sumo N eventos, no N×k.
  - Un test del falso positivo general: una escritura atómica con rename hecha por un tercero, que deja contenido idéntico al baseline, no emite nada.

**Fuera de scope** (no traerlos acá):

- **`hash_expected` en los eventos `file_created`.** Hoy la rama emite `hash_expected=None` (`agent/detector.py:562`) incluso cuando existe una entry de baseline con hash. Poblarlo sería coherente, pero cambia el payload que consumen el backend y la UI; es una change de contrato, no parte de este arreglo.
- **Guard de tipo de objeto en la rama `file_modified`.** El predicado de `:620-621` no exige identidad de tipo. Es la misma laguna defensiva que acá se cierra, pero tocarla es un cambio de comportamiento en un camino que este defecto no involucra.
- **Cortacircuitos de remediación acotado por path.** Es la defensa en profundidad que de verdad corresponde — acotaría cualquier realimentación futura, no solo esta —, pero **introduce política nueva**: qué hace el agente cuando deja de remediar no está en RN-30..RN-33 ni en ningún appendix. Debe cerrarse como decisión antes de proponerse. Ver "Open questions" del design.
- **El evento `file_deleted` que produce el `shutil.move` de `quarantine_file`** (`agent/commands.py:458`). Es un evento real (el archivo efectivamente ya no está), no un falso positivo, y no realimenta: la entry queda `absent` y `select_restorable_content` devuelve `None` para entries `absent` (`agent/baseline.py:387`), de modo que un `auto_restore` posterior falla en vez de reintentar.

## Capabilities

### New Capabilities

<!-- Ninguna. Esta change no introduce una capacidad nueva: completa el contrato de dos existentes. -->

### Modified Capabilities

- `agent-fanotify-detector`: el descarte por hash sin cambio pasa a ser un invariante del detector válido para **toda** clasificación que produce un hash — `file_modified` y `file_created` / `MOVED_TO` por igual —, con identidad de tipo de objeto exigida además de igualdad de hash.
- `agent-decision-engine`: una remediación `auto_restore` exitosa es un punto fijo observable — el ciclo detectar → restaurar → observar converge en una vuelta, y el conteo de eventos por un path bajo regla `auto_restore` queda acotado por el número de modificaciones reales.
- `agent-approve-reject-handler`: la restauración iniciada por el operador (`restore_file`) tampoco produce el evento espurio de su propio `os.replace`; la garantía se hereda del detector y se afirma con test.

## Impact

- **Agente**: `agent/detector.py` — único archivo de producción que se toca. El guard va en la rama `file_created` de `_process_event`, después del cálculo de `current_hash` (símbolo y symlink) y antes de la reserva de `event_id` / mutación de `_pending` (`:527-573`). Sin cambios en `agent/decision.py`, `agent/commands.py` ni `agent/baseline.py`.
- **Tests**: `agent/tests/` — un archivo nuevo de integración detector↔motor sobre filesystem real, más el test de cota de eventos y el del falso positivo general.
- **Docs**: `docs/reglas_de_negocio.md` (RN-117: la letra pasa a exigir las dos mitades del mecanismo) y `docs/arquitectura_stack.md` (D19: idem).
- **Sin migración de BD, sin cambio de contrato de red, sin cambio de payload.** El único efecto observable desde el backend es que dejan de llegar eventos que nunca debieron existir.
- **Dependencias del DAG**: 41 (`agent-deployment-caps`), que habilitó el camino de restauración y expuso el defecto. Está implementada y comiteada (`af25c50`), aunque todavía no archivada — igual que las changes 40 y 42, que siguen activas en `openspec/changes/`. La 42 (`stream-ack-durability`) no es prerequisito: es ortogonal, aunque el incidente (3240 eventos encolados) es exactamente la clase de presión de cola que la 42 acota por el otro lado. Esta change no toca ninguno de los archivos que la 42 modifica.
- **Reglas cubiertas**: RN-30, RN-31, RN-32, RN-33, RN-71, RN-73, RN-117, RN-127, RN-129, RN-130. **Decisiones aplicadas**: D19 / RN-117 (se completa su implementación), D33 / RN-127 (symlink-as-object, preservado sin excepción), D35 / RN-129 (`status` derivado de `action` / `action_failed`, sin alterar), D36 / RN-130 (preflight de escritura y capabilities, sin alterar). **Ninguna decisión nueva**: el arreglo hace cumplir un invariante que el código ya implementa en la rama hermana y que D19 ya declara en su motivación.
- **Roadmap**: change 43 en [CHANGES.md](../../../CHANGES.md).
