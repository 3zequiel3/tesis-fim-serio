# Cuarentena y diff de contenido — cómo implementar

> Documento de exploración (OPSX explore). No implementa nada, no modifica documentación canónica ni
> `openspec/`. Complementa `docs/implementaciones/cuarentena-y-diff-arreglos.md` (en adelante, «el
> diagnóstico») con el **cómo**: verificación de cada defecto, desglose en changes, borradores de decisiones,
> diseño técnico con `archivo:línea`, deltas de specs, pruebas, seguridad y orden sugerido.
>
> **Bases verificadas (2026-09-15):**
>
> - `devel` en `277a458`. El diagnóstico se verificó sobre `2f84d60`; los 7 commits posteriores
>   (`ed286d9`…`277a458`) no tocan ningún archivo citado en este documento (`git log 2f84d60..HEAD --
>   agent/{detector,baseline,decision,commands,quarantine,logging,queue}.py backend/app/modules/{events,actions}
>   backend/app/core/logging.py frontend/src/{components/ui/DiffViewer.tsx,pages/EventDetail.tsx,api/events.ts}`
>   devuelve vacío). Las citas del diagnóstico siguen siendo válidas.
> - Clon `integration/v10` en `/home/ezequiel/Facultad/tesis/tesis-fim-serio-worktrees/integration`, HEAD
>   `7a7ee50`; carril L6 = `1b62905` (padre `6790e40`), integrado por `793bda2`.
>
> **Convenciones:** las citas `archivo:línea` son de `devel` salvo el prefijo **[v10]**. Marcas de evidencia:
> **[lectura]** verificado leyendo el código; **[prueba]** respaldado por una prueba existente; **[no
> verificado]** inferencia que debe confirmarse antes o durante el apply.

---

## 0. Resumen

- **Q-1 es más grave de lo descrito.** La pérdida de la versión aprobada no ocurre sólo en la cuarentena
  automática: el `os.unlink` del camino del operador vuelve como `FAN_DELETE`, entra en la rama
  `file_deleted` del detector y ejecuta `mark_absent`. Una prueba existente lo fija
  (`agent/tests/test_restore_feedback_loop.py:556-595`). **X-1 queda resuelto: sí hay eco y sí altera la
  baseline en ambos caminos.** En el camino automático, además, el eco genera un evento `file_deleted`
  **`pending`** espurio.
- **X-2 queda confirmado como mecanismo** por lectura de `_classify_event`. No se reprodujo con una prueba
  dedicada. Tiene una consecuencia no descrita: el archivo nuevo mal clasificado nunca obtiene entrada de
  baseline.
- **A5 es más barato de lo previsto.** Los 23 archivos que toca `1b62905` son idénticos byte a byte entre su
  padre `6790e40` y `devel` `277a458`, y `git apply --check` del parche sobre `devel` termina con código 0.
  En cambio, **no es viable fusionar `integration/v10` completa**: su raíz `7df4935` no tiene historia común
  con `devel`.
- Se proponen **4 changes**:
  1. `quarantine-baseline-preservation`: A1, supresión del eco y U-1. Es urgente y puede entrar al próximo
     candidato.
  2. `event-diff-binary-port`: A5 más el rótulo de D-2 y la E2E de US-09.
  3. `quarantine-recovery-actions`: A2, A3 y A4.
  4. `agent-create-event-classification`: X-2, opcional.
- Se redactan **7 decisiones** (D70–D76 / RN-164–RN-170, numeración provisional; ver §2.1). Cinco requieren
  decisión del usuario.

---

## 1. Verificación del diagnóstico

### 1.1 Estado por defecto

| ID | Veredicto | Evidencia en `devel` | [v10] |
|---|---|---|---|
| Q-1 | **Confirmado y ampliado** | Las ramas de cuarentena llaman `mark_absent`: `agent/detector.py:847-849` (`file_created`) y `:986-987` (`file_modified`). `mark_absent` reescribe la entrada con `content_b64=None`, `snapshots=[]` y metadatos nulos (`agent/baseline.py:385-401`). Después, `select_restorable_content` devuelve `None` (`agent/baseline.py:207-228`) y `_auto_restore` falla con `no_restorable_content` (`agent/decision.py:228-234`) [lectura]. **Ampliación:** el camino del operador también pierde la versión aprobada (§1.2) [prueba]. | Presente en `:958` y `:1124`. **`:1119` no es de cuarentena**: es la rama `file_absent` genuina. |
| Q-2 | Confirmado | Sólo existen 5 tipos de comando: `dispatch` en `agent/commands.py:150-201` y la lista blanca en `agent/publisher.py:557-560`. El router de acciones sólo expone approve, reject y sus variantes bulk (`backend/app/modules/actions/router.py:42`, `:72`, `:97`, `:114`). `QuarantineStore.read_artifact` (`agent/quarantine.py:497-499`) sólo se invoca desde pruebas (`agent/tests/test_quarantine.py`, `test_quarantine_maintenance.py`, `test_decision.py:319`, `test_audit_fixes.py:144`, `test_commands.py:753`) [lectura]. | Presente |
| Q-3 | Confirmado | `evaluate_and_act` sólo ramifica `auto_restore` y `quarantine` (`agent/decision.py:105-108`). El léxico `RuleAction` está en `backend/app/modules/rules/models.py:11-15` y `RejectAction` en `backend/app/modules/actions/schemas.py:16-18` [lectura]. | Presente |
| Q-4 | Confirmado | `derive_event_status`: `quarantine` exitosa ⇒ `quarantined` (`backend/app/modules/events/service.py:151-152`). El rechazo fija `rejected` cualquiera sea la acción (`backend/app/modules/actions/service.py:283-301`, `:322-327`). La letra de RN-37 («El evento se crea con estado `quarantined`», `docs/reglas_de_negocio.md:287`) sólo describe el camino automático [lectura]. | Presente |
| U-1 | Confirmado | `canApprove = status === 'pending' \|\| status === 'alert_only'` en `frontend/src/pages/EventDetail.tsx:59`; los botones están en `:133-174`. La guarda del backend es `Event.status == EventStatus.pending` (`actions/service.py:202`, `:289`), por lo que la acción termina en 409. Precisión: en bulk no hay 409, porque el nuevo contrato devuelve `failed` con `not_pending`. No existe prueba que cubra `alert_only`: `rg` sin coincidencias en `EventDetail.test.tsx`, `backend/tests/test_actions.py` y `test_actions_router.py` [lectura]. | Presente en `EventDetail.tsx:68` |
| D-1 | Confirmado | `frontend/src/components/ui/DiffViewer.tsx:1-29` renderiza un `<pre>`, invocado en `EventDetail.tsx:242-251`. `react-diff-viewer-continued` está declarada en `frontend/package.json:22` y no se importa. **Además:** `devel` no cumple su propia main spec: `openspec/specs/frontend-events/spec.md:83-101` ya exige detección binaria y hex dump de 256 bytes. RN-03 también lo exige (`docs/reglas_de_negocio.md:50-54`). | No aplica |
| D-2 | Confirmado | El diff se genera contra `entry.content_b64` (`agent/detector.py:911-924`). Ante modificaciones no aprobadas sólo se archiva un snapshot y el contenido activo queda fijado (`:989-994`, BUG-03), así que el diff es acumulado [lectura]. | Presente |
| D-3 | Confirmado | `frontend/e2e/` contiene `helpers.ts`, `us-isolated-lab.spec.ts` (US-03, US-16/17, US-25), `us02-…`, `us03-…`, `us20-…`, `us25-…` y `us31-…`, pero ninguna prueba de US-09 ni de cuarentena. La trazabilidad de US-09 está en `tesis/trazabilidad_us_tests.md:123` y `:342`. | Presente |

### 1.2 X-1 — resuelto: hay eco y altera la baseline en ambos caminos

**Mecanismo común [lectura]:**

1. El detector no tiene supresión de eventos propios por origen. Sólo filtra el temporal `.fim_restore_tmp`
   (`agent/detector.py:682-683`) y descarta por igualdad de hash (`:802`, `:880`). El change 43 rechazó
   explícitamente la auto-atribución por PID y dejó escrito que la cuarentena «mantiene deliberadamente su
   evento `file_deleted`» (`CHANGES.md`, Change 43, cuarto punto de «Capacidades»).
2. `fanotify_init` fuerza `FAN_REPORT_DFID_NAME` (`agent/_fanotify.py:136`) y las marcas incluyen
   `FAN_DELETE` y `FAN_MOVED_FROM` (`agent/detector.py:384-388`).
3. El hilo lector (`_read_loop`, `:458`) entrega cada evento al loop con `call_soon_threadsafe` (`:510`), a
   una `asyncio.Queue` (`:308`) que se consume en el mismo loop (`:1035`).
4. Ambos caminos terminan en `QuarantineStore.quarantine` (`agent/quarantine.py:171-198`) y, dentro de
   `_remove_matching_source`, en `os.unlink(source)` (`:625-629`).
5. `_classify_event` convierte ese `FAN_DELETE` en `file_deleted` (`agent/detector.py:674-675`).

**Camino del operador (`handle_quarantine_file`):**

- El handler, literalmente, no toca la baseline. No recibe `baseline_engine` (`agent/commands.py:421-428`) y
  `dispatch` no se lo pasa (`:169-180`), aunque sí lo recibe (`:109`) [lectura].
- El eco, en cambio, entra en la rama `file_deleted` (`agent/detector.py:704`) y evalúa reglas por ruta
  (`:733`; `agent/rules.py:62-74`). Salvo que la acción sea un `auto_restore` exitoso, ejecuta
  `self._baseline.mark_absent(path)` (`:752-753`).
- **Prueba existente:** `test_quarantine_still_reports_the_absence`
  (`agent/tests/test_restore_feedback_loop.py:556-595`) ejecuta `handle_quarantine_file` e inyecta el
  `FAN_MOVED_FROM`. Afirma exactamente un payload `file_deleted` y `entry.status == "absent"` [prueba].
- Consecuencias según la regla que coincide con la ruta:
  - `manual_review`: queda un evento `file_deleted` `pending` adicional y la baseline vaciada.
  - `alert_only`: queda un evento `alert_only` adicional y la baseline vaciada.
  - `auto_restore`: el eco **restaura la versión aprobada** inmediatamente (`:742-751`). El «Rechazar →
    Cuarentena» del operador se convierte, sin que nadie lo pida, en cuarentena más restauración.
  - `quarantine`: se comporta como el camino automático.

**Camino automático (`DecisionEngine`):**

1. La cuarentena ocurre dentro de `evaluate_and_act` y luego se ejecuta `mark_absent` (`:849` / `:987`).
2. El eco llega como `file_deleted`. La regla vuelve a devolver `quarantine`, porque `rules.evaluate` es sólo
   `fnmatch` sobre la ruta.
3. Se escribe un journal `pending` nuevo (`agent/decision.py:98`) y se reintenta la cuarentena. `os.lstat`
   falla con `FileNotFoundError`, que se convierte en `QuarantineError("file_not_found")`
   (`agent/quarantine.py:369-371`) y queda `action_failed=True`.
4. El agente publica ese evento y el backend lo deriva a **`pending`** (`backend/app/modules/events/service.py:151-152`).
   No se supersede el evento original, porque es `quarantined` (terminal) y
   `get_pending_event_for_path` sólo busca `pending` (`:156-162`).

Resultado: **cada cuarentena automática deja un evento `file_deleted` `pending` espurio**, con
`action_error="file_not_found"`, en la cola del operador [lectura]. No existe prueba de detector que lo
cubra: `test_decision_quarantine_file_gone` sólo ejercita el motor. Tampoco se encontró evidencia de
laboratorio: las coincidencias de `file_not_found` en `tesis/cierre/evidencia/` son JUnit y logs de suites que
no se revisaron en detalle [no verificado en runtime].

**Ventana de crash [lectura]:** `rehydrate` reintenta la cuarentena (`agent/decision.py:166-171`) pero no toca
la baseline. Si el agente cae entre el `unlink` y `mark_absent`, la entrada queda `present` con el archivo
ausente, y el eco se pierde con la cola del kernel.

### 1.3 X-2 — mecanismo confirmado por lectura; falta prueba dedicada

`_classify_event` (`agent/detector.py:662-678`) evalúa `FAN_CLOSE_WRITE` antes que `FAN_CREATE`
(`:672-673`); el docstring lo declara deliberado (`:667-668`). Con `FAN_REPORT_DFID_NAME` forzado
(`agent/_fanotify.py:136`), `FAN_CREATE` y `FAN_CLOSE_WRITE` del mismo hijo llevan el mismo registro de
directorio y nombre. Eso hace posible que el kernel fusione ambos eventos en uno con las dos máscaras
[no verificado: comportamiento del kernel]. Cuando ocurre la fusión:

- el evento va a la rama genérica; `entry` es `None`, así que `previous_hash` también (`:684-686`);
- `current_hash` no es `None` y el evento se clasifica `file_modified` (`:895-901`), con `hash_expected=None`
  y sin diff (`:912` exige `entry`).

**Consecuencia no descrita en el diagnóstico [lectura]:**

1. La rama `file_modified` sólo llama `add_snapshot` (`:989-994`), que devuelve `False` si no hay entrada
   (`agent/baseline.py:421`). Por lo tanto el archivo nuevo **nunca obtiene entrada de baseline**. La rama
   `file_created` sí la crea (`agent/detector.py:853`).
2. Cada `close_write` posterior, aun sin cambio de contenido, vuelve a emitir `file_modified`: el descarte
   por hash de `:880` nunca coincide contra `None`. Esto dura hasta que una aprobación crea la entrada vía
   `update_from_command`.

La observación original está en
`tesis/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md:97-98`. La propuesta de arreglo
es el change 63 (§4.7).

### 1.4 Afirmaciones del diagnóstico que son incorrectas o imprecisas

1. **§2.2, fila «Baseline local» del camino del operador («Sin cambios (el handler no toca la baseline)»).**
   Es cierto sólo para el handler; en el efecto es falso por el eco (§1.2). Q-1 afecta a los dos caminos.
2. **§3, Q-1, cita [v10] `agent/detector.py:1119`.** Corresponde a la rama `file_absent` genuina. Las ramas de
   cuarentena en [v10] son `:958` y `:1124`.
3. **§4.5 y §6.4, «integrar la rama completa».**
   - `integration/v10` tiene como raíz `7df4935` («chore: freeze corrected consolidated validation
     candidate»), un commit sin padres (`git rev-list --max-parents=0 7a7ee50`).
   - Ningún commit de `devel` es ancestro de `7a7ee50`: `merge-base --is-ancestor` da negativo para
     `2f84d60`, `ca34335`, `26c6cee` y `6948aae`.
   - `integration/v10` integra 10 carriles (`8f2a484` l1 … `d35fb9c` l9).
   - Un `git merge` no es aplicable. El carril L6, además, se aplica limpio como parche (§4.6).
4. **§4.4, derivación de `quarantine_state` «a partir del comando `quarantine_file` y su `event_ack`».**
   - La cuarentena automática no genera `PublishedCommand`; hay que derivarla también de `Event.status`.
   - La confirmación de comandos se llama `command_ack` y viaja por el stream `event_ack` (D30/RN-124,
     `docs/reglas_de_negocio.md:1077-1090`). C3/RN-73 es el ack de ingesta.
5. **§4.3, comandos de liberación «con `ruleset_version` (C11)».** RN-75 no lo exige para comandos de
   filesystem: `restore_file` y `quarantine_file` lo excluyen por diseño
   (`backend/app/modules/actions/streams.py:174`, `:211`; `tesis/trazabilidad_us_tests.md:757`). Hay que
   decidirlo por comando (D74).
6. **§7, «la tesis describe la cuarentena como conservación de evidencia sin modificar la baseline (RN-37)».**
   No se encontró esa afirmación en los markdown de cierre. `tesis/cierre/CAMBIOS_PARA_TESIS.md:29`, `:49` e
   `INFORME_CIERRE_TECNICO.md:31-32`, `:71-72`, `:134` sólo afirman cifrado, retención y store único. Puede
   estar en el `.docx` [no verificado].
7. **§3, D-3, cita `tesis/trazabilidad_us_tests.md:407-421`.** Es la sección de US-12; US-09 está en `:123` y
   `:342`.
8. **§2.2, «Nombre opaco `sha256(action_id‖ruta)`».** Precisión: es `sha256(action_id + NUL + abspath)`
   (`agent/quarantine.py:162-169`). `action_id` es el `event_id` UUID del agente en el camino automático y el
   `command_id` en el del operador (`agent/commands.py:457`, `:475`). Esto importa para direccionar
   artefactos en A3.

### 1.5 Hallazgos adicionales relevantes para el diseño

- **H-1 — dos listas de comandos.** Un tipo de comando nuevo debe agregarse tanto a la lista blanca
  `agent/publisher.py:557-560` como a `dispatch` (`agent/commands.py:150-201`); si falta en la primera no se
  enruta [lectura].
- **H-2 — spec del handler desactualizada.** La main spec `agent-approve-reject-handler`, requisito «Handler
  quarantine_file — cuarentena con journal» (`openspec/specs/agent-approve-reject-handler/spec.md:87-105`),
  describe mover a `<filename>.<timestamp>` y reutilizar `agent/actions.py`. El código usa `QuarantineStore`
  (`agent/commands.py:463-475`).
- **H-3 — replay de comandos.**
  - `verify_payload` sólo verifica HMAC (`agent/streams.py:31-35`); no hay control de `issued_at` ni nonce
    en el agente (`rg` sin coincidencias).
  - El cursor `last_stream_command_id` vuelve a `"0-0"` si falta `state.json` (`agent/state.py:20`; main spec
    `agent-command-cursor`), lo que relee todo el stream.
  - Un `quarantine_file` repetido sobre una ruta ya restaurada volvería a cuarentenarla. La idempotencia por
    artefacto (`agent/quarantine.py:180-184`) sólo evita duplicados mientras el artefacto existe.
  - Es un riesgo preexistente que se agrava con la liberación [lectura].
- **H-4 — `file_created` adopta el contenido nuevo.** La rama escribe la entrada activa con ese contenido
  (`agent/detector.py:850-853`; `agent/baseline.py:299-338`). Con A1 no debe sobrescribir una entrada en
  cuarentena. La política general para archivos nuevos queda fuera de alcance.
- **H-5 — la rehidratación publica comandos como eventos.**
  - `rehydrate` trata toda entrada `pending` del journal como un evento a publicar (`agent/decision.py:141-201`).
  - Los handlers de comandos también escriben journal (`agent/commands.py:338` con `"restore"`, `:460` con
    `"quarantine"`).
  - Un crash durante un `restore_file` del operador se re-publica tras reiniciar como evento `alert_only`
    sintético.
  - Un `quarantine_file` se re-ejecuta y se publica como evento con `event_id = command_id`.
  - Las acciones de comando nuevas (liberar, descartar) deben tratarse explícitamente en `rehydrate`
    [lectura].
- **H-6 — cambios sin commitear en main specs.** Hay cambios en `openspec/specs/backend-approve-reject/spec.md`
  y `openspec/specs/frontend-events/spec.md` (migración del contrato bulk a `event_ids`, notas
  `SUPERSEDED.md`), de otra sesión. `scripts/check_spec_integrity.py` devolvió `OK — 44 main specs, 249
  requisitos` en esta verificación.

---

## 2. Desglose de changes para OPSX

### 2.1 Numeración (provisional)

| Recurso | Próximo libre canónico | Reservado por borradores no registrados | Propuesta de este documento |
|---|---|---|---|
| Change | 53 (`CHANGES.md` termina en 52) | 53–59 en `instalador-unificado-y-token-de-union-como-implementar.md` | **60–63** |
| Decisión | D63 / RN-157 (último: D62/RN-156, `docs/arquitectura_stack.md:2685-2693`) | D63–D69 / RN-157–RN-163 en el mismo borrador | **D70–D76 / RN-164–RN-170** |
| Migración | `015_…` (`backend/db/migrations/` termina en `014_add_alert_delivery_state.sql`) | 015–017 en el borrador del instalador; en [v10], `015_add_agent_queue_size.sql` (carril l5) y `016_add_event_binary_diff_metadata.sql` (carril l6) | Número libre **al momento del apply** |

Regla práctica: gana el número quien registre primero en `CHANGES.md` y en los appendices. Si este paquete se
registra antes que el del instalador, se desplaza a 53–56 y D63–D69 sin otro cambio. Los números no
imponen orden de ejecución; por ejemplo, 52 depende de 41.

### 2.2 DAG

```
  D70, D71 (docs)                         D76 (docs)
        │                                     │
        ▼                                     ▼
  60 quarantine-baseline-preservation   61 event-diff-binary-port
        │          │                          ┆  (coordinación: detector.py,
        │          ▼                          ┆   EventDetail.tsx, decision.py)
        │   63 agent-create-event-classification (opcional)
        ▼                                     ┆
  D72–D75 (docs) ──────► 62 quarantine-recovery-actions ◄┄┄ 61 (recomendado, no bloqueante)
```

### 2.3 Tabla de changes

| # | Nombre | Arreglos | Depende de | Tamaño estimado | ¿Puede empezar ya? |
|---|---|---|---|---|---|
| 60 | `quarantine-baseline-preservation` | A1, supresión del eco (X-1), U-1 | D70, D71 registradas | 25–30 tareas | **Sí**, tras registrar D70/D71. El delta de `frontend-events` debe partir de la main spec ya commiteada (H-6). |
| 61 | `event-diff-binary-port` | A5 (D-1), rótulo de D-2, E2E de US-09 (D-3) | D76 registrada (sólo para el rótulo) | 15–18 tareas | **Sí.** El parche aplica limpio hoy; cualquier commit sobre los 23 archivos lo invalida. |
| 62 | `quarantine-recovery-actions` | A2, A3, A4 (Q-2, Q-3, Q-4) | 60 archivado; D72–D75; 61 recomendado | 45–55 tareas | No |
| 63 | `agent-create-event-classification` (opcional) | X-2 | 60 (misma función y banco de pruebas) | 8–10 tareas | Tras 60 |

**Superposición con changes activos:**

- `openspec list --json` muestra 10 changes `in-progress`. Ninguna tarea sin marcar de
  `vps-deployment-readiness`, `frontend-severity-triage`, `backend-agent-cert-renewal`,
  `agent-attribution-and-detection-gap`, `agent-restore-feedback-loop`, `stream-ack-durability`,
  `event-status-contract`, `agent-deployment-caps`, `backend-residual-fixes` ni
  `agent-scope-filter-symlink-hardening` menciona archivos de este paquete.
- Excepciones informativas:
  - `backend-agent-cert-renewal` 5.5.4 (preservar `master_secret`): condiciona A3, porque la clave de
    cuarentena deriva de él (RN-35).
  - `agent-deployment-caps` 15.5 menciona «dos implementaciones divergentes de cuarentena», algo ya
    unificado por `b060e5f`.
- `vps-deployment-readiness` (72/78) no menciona `agent/{detector,baseline,decision,commands,quarantine}.py`,
  `backend/app/modules/{actions,events}`, `EventDetail`, `DiffViewer` ni migraciones 015–019 en ninguno de
  sus artefactos.

### 2.4 Contenido por change

**60 — `quarantine-baseline-preservation`.**

- Estado `quarantined` en la entrada local, que conserva contenido y snapshots.
- Las dos ramas automáticas y el handler del operador marcan ese estado.
- La rehidratación también marca, lo que cierra la ventana de crash.
- Supresión del eco `file_deleted`/`file_absent` sobre entradas `quarantined`.
- Transición a `present` tras una restauración verificada.
- Un archivo nuevo en una ruta cuarentenada no sobrescribe el contenido conservado.
- `canApprove` sólo para `pending`.
- Sin cambios de backend ni migraciones.
- Rollback: revertir y reiniciar el agente. Las entradas `quarantined` escritas por la versión nueva no son
  legibles por la anterior si se agrega un campo; ver §4.1.

**61 — `event-diff-binary-port`.**

- Aplicación del parche de `1b62905`: 23 archivos, +1026/−40.
- Renumeración de la migración.
- Rótulo «Cambios respecto de la última versión aprobada».
- E2E de US-09 para texto y binario en el laboratorio aislado.
- Deltas de spec para alinear `devel` con RN-03 y con su propia main spec.

**62 — `quarantine-recovery-actions`.**

- Acción `quarantine_restore` como regla y como rechazo.
- Endpoints y comandos para liberar, descartar y restaurar desde cuarentena.
- Entidad `quarantine_resolutions` y migración.
- `quarantine_state` derivado, con su filtro.
- Controles de replay para comandos destructivos.
- Botones, confirmación y E2E.

**63 — `agent-create-event-classification`.**

- Clasificar como `file_created` todo evento con hash sobre una ruta sin entrada de baseline, o con
  `FAN_CREATE`/`FAN_MOVED_TO` en la máscara.
- Pruebas con máscara fusionada.

---

## 3. Decisiones a registrar antes de `/opsx:propose`

Son borradores en el formato de `docs/reglas_de_negocio.md:1993-2035` (D62/D57) y de la tabla de
`docs/arquitectura_stack.md:2685-2693`. **No se escriben en los docs canónicos desde este documento.**
Numeración provisional según §2.1.

### D70 / RN-164 — La cuarentena conserva la última versión aprobada en la baseline local — **requiere decisión del usuario**

**Descripción:** Al completarse una acción `quarantine` —automática, por rechazo del operador o por
rehidratación del journal— el agente SHALL registrar la entrada de baseline de la ruta con
`status: "quarantined"` y `quarantine_action_id` igual a la identidad del artefacto. SHALL conservar sin
cambios los campos `hash`, `size`, `mode`, `uid`, `gid`, `mtime`, `content_b64`, `oversize`,
`symlink_target`, `approved_event_id` y `snapshots` de la entrada previa, cualquiera haya sido su estado.
`mark_absent` SHALL quedar reservado a ausencias no causadas por el agente.

Una entrada `quarantined`:

1. SHALL seguir siendo fuente válida de `select_restorable_content`;
2. SHALL pasar a `present` al completarse una restauración verificada o una aprobación posterior
   (`baseline_update`);
3. SHALL NOT ser sobrescrita cuando se crea un archivo nuevo en la ruta: ese archivo se reporta como evento
   y su contenido sólo se adopta por aprobación (candidato local, D-C13).

**Motivo:** RN-37 afirma que la baseline permanece intacta, y el código la vacía en los dos caminos
(§1.1, §1.2). Sin la versión aprobada no hay restauración posible (RN-30 a RN-33) ni diff contra la versión
sana.

**Condición:** Acción `quarantine` exitosa en `DecisionEngine`, `handle_quarantine_file` o `rehydrate`.

**Resultado:**

- La restauración posterior recupera la versión aprobada byte a byte.
- RN-37 se enmienda en su letra: «El baseline conserva la última versión aprobada; la entrada registra la
  ausencia física por cuarentena. La cuarentena automática crea el evento con estado `quarantined`; el
  rechazo con cuarentena deja el evento en `rejected` (RN-72)».
- RN-66 se precisa: `absent` significa «no debe existir por aprobación», y la cuarentena no produce `absent`.

**Migración:** Las entradas ya vaciadas por cuarentenas previas **no son recuperables**. Ni la entrada ni el
artefacto conservan la versión aprobada: el artefacto guarda la versión alterada. No se migran. Se declara
como limitación y la recuperación operativa es una aprobación nueva o un re-scan confirmado (RN-70).

**Opciones a decidir:**

| Opción | Cambio | A favor | En contra |
|---|---|---|---|
| **A (recomendada)** — `status: "quarantined"` + `quarantine_action_id` | Tercer valor en `BaselineEntry.status` (`agent/baseline.py:67`) | Estado explícito; los chequeos a revisar son pocos (`agent/baseline.py:421`, `:605`, `:678`). No altera el significado de `absent`, que consumen RN-60, RN-66 y RN-74. | Una versión anterior del agente no lee entradas con el campo nuevo: `from_dict` pasa claves desconocidas a `cls(**fields)` (`agent/baseline.py:88-93`). El rollback exige limpiar esas entradas o no agregar el campo. |
| B — `status: "absent"` + campo `quarantine_action_id` y contenido conservado | Sólo un campo nuevo | Menos valores de estado | `absent` pasa a tener dos significados y la spec «Baseline present and absent states» (`openspec/specs/agent-baseline/spec.md:65-79`) exige que `absent` no contenga contenido: habría que reescribirla. Todo consumidor de `absent` debe distinguir casos. |

**Excepciones:** Sin versión aprobada previa (entrada inexistente o `absent`), la entrada queda `quarantined`
con `hash` y contenido nulos. Eso conserva la semántica de que el estado sano es la ausencia.

### D71 / RN-165 — El eco de la cuarentena propia no genera eventos — *consecuencia de D70; confirmar*

**Descripción:** Un evento clasificado `file_deleted` o `file_absent` sobre una ruta cuya entrada está
`quarantined` SHALL descartarse antes de asignar `event_id`, con traza `decision_suppressed` y razón
`quarantined_by_agent`: sin evaluar reglas, sin journal, sin publicación y sin mutar la baseline. El mecanismo
se basa en el estado, no en el PID, con el mismo criterio que el change 43.

**Motivo:** El eco duplica una ausencia ya informada (evento `quarantined` o `command_ack` del
`quarantine_file`), vacía la baseline y, en el camino automático, crea un `pending` espurio (§1.2).

**Resultado:** Se enmienda la afirmación del change 43 de que la cuarentena «mantiene deliberadamente su
evento `file_deleted`».

**Riesgo aceptado a confirmar:** si alguien crea un archivo en la ruta cuarentenada y luego lo borra, la
creación se reporta pero el borrado se descarta, porque devuelve la ruta al estado registrado (ausente).

### D72 / RN-166 — Acción combinada `quarantine_restore` — **requiere decisión del usuario**

**Descripción:** Se incorpora la acción `quarantine_restore` (snake_case, RN-71) como acción de regla
(`RuleAction`) y como acción de rechazo (`RejectAction`). El agente SHALL ejecutarla como una sola operación
journalizada, en este orden:

1. selección del contenido restaurable y validación de metadatos, antes de tocar el archivo;
2. captura cifrada y verificada del archivo alterado, **sin** `unlink`;
3. verificación de que la identidad del origen no cambió;
4. reemplazo atómico por la versión aprobada (`os.replace` sobre la misma ruta);
5. verificación del hash **releyendo el disco**.

**Estado del evento a decidir:**

- **(a, recomendada)** Estado nuevo `quarantine_restored`, terminal, con in-edge de creación
  (`action=quarantine_restore`). Modifica RN-71 y RN-72 y requiere
  `ALTER TYPE … ADD VALUE IF NOT EXISTS 'quarantine_restored'`. El precedente es
  `backend/db/migrations/001_add_agent_status_revoked.sql:9`; que `eventstatus` sea un enum nativo es
  [no verificado]. Es coherente con D35/RN-129: el estado es la acción ejecutada.
- (b) Reutilizar `auto_restored` y exponer la evidencia sólo vía `quarantine_state` (D75). No cambia el
  léxico, pero filtrar por estado oculta la evidencia.
- En el camino del operador el estado sigue siendo `rejected` en ambas opciones.

**Fallos:**

| Falla | Estado del archivo | Artefacto | Evento |
|---|---|---|---|
| Sin contenido restaurable o sin metadatos | Intacto | No se crea | `action_failed` ⇒ `pending` |
| Captura fallida | Intacto | No se crea o queda incompleto sin autenticar | `action_failed` ⇒ `pending` |
| Captura ok, escritura o reemplazo fallido (`EROFS`/`EACCES`) | Alterado, en su lugar | Conservado (evidencia) | `action_failed` con `restore_failed_after_capture` ⇒ `pending` |
| Reemplazo ok, hash releído distinto | Lo que haya en disco | Conservado | `action_failed` con `hash_mismatch_after_restore` ⇒ `pending` |

**Casos borde a decidir:**

- Ruta sin versión aprobada (entrada inexistente o `absent`). Recomendado: ejecutar sólo la cuarentena,
  porque el estado sano ya es la ausencia, y marcar `quarantined` (D70).
- Evento `file_deleted`, donde no hay nada que capturar. Recomendado: comportarse como `auto_restore`.

### D73 / RN-167 — Registro de la resolución de cuarentena — **requiere decisión del usuario**

**Descripción (opción a, recomendada):**

- La liberación, el descarte y la restauración desde cuarentena SHALL registrarse en una entidad nueva
  `quarantine_resolutions` enlazada al evento. El evento conserva su estado terminal y RN-72 no cambia.
- Cada resolución tiene `kind` (`release | discard | restore`), `status` (`pending | completed | failed`,
  espejo del `command_ack`), `command_id` único, `requested_by`, `requested_at`, `reason`,
  `expected_sha256`, `completed_at` y `error`.
- SHALL existir a lo sumo una resolución `pending` o `completed` de tipo `release` o `discard` por artefacto.

**Opción b:** agregar transiciones `quarantined → approved | rejected` y `rejected → …` a RN-72. Exige tocar
`VALID_TRANSITIONS` (`backend/app/modules/events/service.py:90-98`), el UPDATE optimista de acciones y
`derive_event_status`, y rompe la lectura «estado = acción ejecutada» (D35/RN-129).

**Precedente de (a):** D30/RN-124 expone el estado de ejecución como indicador secundario «sin crear un nuevo
estado en la máquina de eventos» (`docs/reglas_de_negocio.md:1088`).

### D74 / RN-168 — Semántica de liberar y descartar — **requiere decisión del usuario**

**Descripción (propuesta):**

- **Liberar** significa aceptar el contenido cuarentenado como nueva versión aprobada. El agente SHALL:
  - autenticar el artefacto y validar identidad (`action_id`, `original_path`) y `sha256` contra el
    `expected_sha256` enviado por el backend;
  - rechazar artefactos legacy con `original_path_known: false` (RN-37a);
  - adoptar la baseline **antes** de reubicar el archivo;
  - reubicarlo **sin sobrescribir** nada existente en la ruta (falla `path_occupied`);
  - verificar el hash releyendo el disco;
  - eliminar el artefacto tras la verificación.
  - El backend reconcilia `baseline_entries` al recibir el `command_ack` (D1/RN-104).
- **Descartar** significa eliminar el artefacto autenticado antes de la retención. La baseline y el evento no
  cambian.
- **Restaurar desde cuarentena** reutiliza `restore_file` sobre un evento con `quarantine_state=quarantined`,
  lo que requiere D70.
- Sólo admin, de a un evento (sin bulk), con motivo obligatorio y confirmación explícita.

**Puntos a decidir:**

1. ¿La liberación adopta la baseline (recomendado) o sólo reubica y deja el cambio pendiente de aprobación?
2. Bits `setuid`/`setgid` del artefacto. Recomendado: quitarlos salvo confirmación reforzada.
3. ¿Eliminar el artefacto tras liberar (recomendado) o conservarlo hasta la retención?
4. `ruleset_version` en `quarantine_release`. Recomendado: sí, con la guarda de obsolescencia de
   `baseline_update` (`agent/commands.py:249-258`), porque muta estado replicado. No en `quarantine_discard`.
5. Registro local de `command_id` ya ejecutados para comandos destructivos (H-3). Recomendado: sí.

### D75 / RN-169 — `quarantine_state` derivado — *recomendada; confirmación liviana*

**Descripción:** `EventOut` y `EventDetailOut` SHALL exponer `quarantine_state ∈ {none, quarantined, released,
discarded}`, calculado en lectura y sin columna en `events`, con esta precedencia:

1. resolución `release` `completed` ⇒ `released`;
2. resolución `discard` `completed` ⇒ `discarded`;
3. `status ∈ {quarantined, quarantine_restored}`, o `status = rejected` con un `PublishedCommand`
   `quarantine_file` `acked` ⇒ `quarantined`;
4. en otro caso ⇒ `none`.

`GET /events` SHALL aceptar el filtro repetible `quarantine_state`, resuelto en SQL y no en memoria, para no
romper la paginación. No crea estado en RN-72.

**Limitación a declarar:** la retención local (RN-37a) elimina artefactos sin informar rutas al backend. Un
`quarantined` puede referir un artefacto ya vencido, y la liberación falla entonces con `artifact_not_found`.

### D76 / RN-170 — Semántica del diff de modificaciones sucesivas (D-2) — **requiere decisión del usuario**

**Descripción (recomendada):** El diff y la comparación binaria SHALL rotularse «Cambios respecto de la última
versión aprobada». No se implementa diff incremental.

**Motivo:** un diff incremental exige conservar el contenido de cada versión pendiente. Hoy
`stage_approval_candidate` guarda sólo el candidato más reciente por ruta (`agent/baseline.py:662-676`), así
que habría que agregar una cadena de candidatos. Eso amplía la superficie de contenido sensible descrita en
la Tabla 21a (cola y descarte sin cifrar, `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md:381`).

### Contraparte técnica (tabla para `docs/arquitectura_stack.md`)

| Decisión | Resolución técnica (borrador) |
|---|---|
| D70 | `BaselineEngine.mark_quarantined(path, action_id)`. Llamada en `agent/detector.py:849`, `:987`, en `handle_quarantine_file` tras `quarantine()` y en `rehydrate`. `write_entry` en restauraciones exitosas de entradas `quarantined`. Sin migración de datos. |
| D71 | Retorno temprano en la rama `file_deleted` (`agent/detector.py:704`) y en `file_absent` (`:895`) si `entry.status == "quarantined"`. Traza `decision_suppressed`. |
| D72 | `QuarantineStore.capture` y `verify_source_unchanged`, que dividen `quarantine()`. Primitiva de restauración compartida que relee el disco. `RuleAction`/`RejectAction` más `ALTER TYPE` idempotente. |
| D73 | Tabla `quarantine_resolutions` con índice único parcial. Migración SQL idempotente (D3). |
| D74 | Comandos `quarantine_release` y `quarantine_discard` HMAC en el outbox (D37/RN-131). Reubicación con `renameat2(RENAME_NOREPLACE)`, con alternativa `link`+`unlink`. Libro local de `command_id` destructivos. |
| D75 | `_get_quarantine_state_map` análogo a `_get_ack_status_map` (`backend/app/modules/events/router.py:175-192`) y filtro por subconsultas `EXISTS`. |
| D76 | Rótulo en `DiffViewer`/`EventDetail`; sin cambios de agente. |

---

## 4. Diseño técnico por arreglo

### 4.1 A1 más supresión del eco — change 60

**`agent/baseline.py`**

| Punto | Línea | Cambio |
|---|---|---|
| `BaselineEntry.status` | `:67` | Documentar `"quarantined"`; campo `quarantine_action_id: str \| None = None` tras `approved_event_id` (`:83`). |
| `mark_quarantined(path, action_id)` (nuevo) | junto a `mark_absent` `:385-401` | Lee la entrada existente con `read_entry`. Si existe, copia todos sus campos y sólo cambia `status`, `quarantine_action_id` y `captured_at`, **preservando `snapshots`**, igual que `update_from_command` en `:644`. Si no existe, escribe la entrada `quarantined` con campos nulos. Escritura atómica cifrada con el mismo patrón de `:398-400`. |
| `mark_absent` | `:385-401` | Sin cambios: queda para ausencias genuinas (`agent/detector.py:753`, `:982`). |
| `add_snapshot` | `:421` | Guarda actual: `entry.status == "absent" or entry.hash is None`. Con `quarantined` y hash no nulo debe permitir el snapshot (la deduplicación de `:425` lo vuelve inocuo). Afirmarlo con prueba. |
| `update_from_command` | `:576-660`, comparación de estado en `:605` | Sin cambio de código: una aprobación posterior pasa la entrada a `present`/`absent` y conserva snapshots (`:644`). Afirmarlo con prueba. |
| `stage_approval_candidate` | `:662-676`, literal en `:678` | Sin cambio: recibe el estado derivado del evento (`present`/`absent`), no el de la entrada. |
| `select_restorable_content` | `:207-228` | Sin cambio; vuelve a devolver contenido para entradas `quarantined`. |
| `init_scan` / `run_scan` | `:463`, `:515` | Según el relevamiento no inspeccionan `status`; una ruta cuarentenada no existe en disco y no se recorre [no verificado línea a línea; confirmar en apply]. |

**`agent/detector.py`**

| Punto | Línea | Cambio |
|---|---|---|
| Rama `file_deleted` | `:704` | Antes de asignar `event_id` (`:705`), si `entry is not None and entry.status == "quarantined"`, registrar `_trace_record("decision_suppressed", reason="quarantined_by_agent", …)` y retornar. |
| Rama `file_created`, cuarentena | `:847-849` | `mark_absent` pasa a `mark_quarantined(path, change.event_id)`. |
| Rama `file_created`, resto | `:850-853` | Si `entry` está `quarantined`, **no** llamar `write_entry` (sobrescribiría el contenido aprobado, H-4). El candidato ya quedó registrado por `_stage_approval_candidate`. Opcional con contrato de payload: poblar `hash_expected` y `diff_text` contra el contenido conservado reutilizando `:911-924`. Es el follow-up declarado en el change 43; los campos ya son anulables en el backend. |
| Rama genérica, `file_absent` | `:895` y `:970-982` | Misma supresión que en `file_deleted` si la entrada está `quarantined`. |
| Rama genérica, `file_modified` con `auto_restore` exitoso | `:984-985` (`pass`) | Si la entrada estaba `quarantined`, llamar `write_entry(path)` para volver a `present`. |
| Rama genérica, cuarentena | `:986-987` | `mark_quarantined(path, change.event_id)`. |

**Ordenamiento y carreras [lectura]:**

- `_process_event` y los handlers corren en el mismo loop (`agent/detector.py:931-932`, D8). El hilo lector
  sólo agenda con `call_soon_threadsafe` (`:510`).
- En el detector, `evaluate_and_act` es síncrono (`:838`, `:960`) y el marcado (`:849`, `:987`) ocurre antes
  del primer `await` (`publish`). Ningún eco puede procesarse entre la cuarentena y el marcado.
- En el handler, el marcado debe ubicarse inmediatamente después de `quarantine_store.quarantine(...)`
  (`agent/commands.py:475`) y antes de `await _publish_ack` (`:501-504`). `QuarantineStore.quarantine` es
  síncrono.
- Confirmar en apply que `agent/publisher.py:568-579` despacha en ese mismo loop (aparece como `await
  _commands.dispatch(...)`).

**`agent/commands.py`**

| Punto | Línea | Cambio |
|---|---|---|
| `dispatch` | `:169-180` | Pasar `baseline_engine=baseline_engine`, que ya está en la firma, `:109`. |
| `handle_quarantine_file` | `:421-428` y `:475-479` | Nuevo parámetro `baseline_engine`. Tras la cuarentena, `baseline_engine.mark_quarantined(path, journal_key)`. Si el marcado falla: `journal.mark_failed(journal_key, "baseline_mark_failed")` y ack con error. El artefacto existe; el eco seguirá el camino previo y el operador lo ve en el ack. |
| `handle_restore_file` | `:341-401` | Tras verificar el hash (`:399-401`), si la entrada estaba `quarantined`, `baseline_engine.write_entry(path)`. `write_entry` rehashea el disco y conserva snapshots (`agent/baseline.py:332`). El `MOVED_TO` del `os.replace` se descarta por igualdad de hash (`agent/detector.py:802`). |

**`agent/decision.py`**

| Punto | Línea | Cambio |
|---|---|---|
| `rehydrate` | `:166-171` y `:205` | Tras un `_quarantine` exitoso en la rehidratación, `self._baseline.mark_quarantined(entry.path, entry.event_id)`. Cubre la ventana de crash de los dos caminos: la clave de journal es el `event_id` o el `command_id`, y la identidad del artefacto coincide (`agent/quarantine.py:162-169`, `:180-184`). |
| `_auto_restore` | `:219-290` | Sin cambio de código. Vuelve a funcionar para entradas `quarantined`: la validación de metadatos (`:242-246`) pasa porque `mark_quarantined` conserva `mode`/`uid`/`gid`. Si la entrada estaba `quarantined`, el detector la devuelve a `present` (tabla anterior). |

**Pruebas existentes a actualizar:**

- `agent/tests/test_audit_fixes.py:801-869`: `assert` de `mark_absent` en `:868`.
- `agent/tests/test_restore_feedback_loop.py:556-595`: con D71 pasa a afirmar cero payloads y la entrada
  `quarantined` con contenido. Renombrar la prueba o documentar la inversión.

### 4.2 U-1 — change 60

- `frontend/src/pages/EventDetail.tsx:59` pasa a `const canApprove = event.status === 'pending'`; se corrige el
  comentario de `:133`.
- En `frontend/src/pages/EventDetail.test.tsx`, prueba parametrizada sobre los siete valores de
  `EventStatus` (`frontend/src/api/events.ts:5-13`): botones presentes sólo en `pending`.
- En `backend/tests/test_actions_router.py`, prueba de contrato: `POST /actions/approve` y `/reject` sobre un
  evento `alert_only` ⇒ 409.
- Bulk: sin cambio, porque devuelve `failed` con `not_pending`. Decidir si `EventsTable` debe impedir
  seleccionar eventos no `pending`; hoy sólo distingue `superseded` (`frontend/src/components/ui/EventsTable.tsx:104`).
  Queda fuera de 60 salvo pedido.

### 4.3 A2 `quarantine_restore` — change 62

**Agente:**

- `agent/decision.py:105-108`: rama `elif action == "quarantine_restore": self._quarantine_restore(...)`.
- Extraer una primitiva única de restauración desde `_auto_restore` (`:248-290`) y `handle_restore_file`
  (`agent/commands.py:367-401`), hoy duplicadas y con paridad afirmada por el change 43.
  - Firma sugerida: `restore_approved_content(entry, path) -> None`.
  - Mismo orden `O_EXCL` → `fchown` → `fchmod` → `os.replace`.
  - Verificación **releyendo el disco**, no el buffer. Hoy `_hash_bytes(content)` en `agent/decision.py:288`
    y `agent/commands.py:399` hashean el búfer en memoria; es la verificación tautológica señalada en la
    tarea 15.5 de `agent-deployment-caps`.
- `agent/quarantine.py`:
  - dividir `quarantine()` (`:171-198`) en `capture(action_id, source) -> QuarantineArtifact` (captura,
    escritura cifrada y verificación, sin `_remove_matching_source`);
  - extraer de `_remove_matching_source` (`:588-624`) la comparación de identidad como
    `verify_source_unchanged(source, metadata)`, sin `unlink`;
  - `quarantine()` queda como `capture` más `verify_source_unchanged` más `unlink`, sin cambio de
    comportamiento.
- Secuencia de `_quarantine_restore`:
  1. `read_entry`, `select_restorable_content` y validación de metadatos. Si falla, sin tocar nada.
  2. `capture`.
  3. `verify_source_unchanged`.
  4. Primitiva de restauración (reemplazo atómico sobre el archivo alterado).
  5. `payload["quarantine_path"]`.
  - Como no hay `unlink`, no hay `FAN_DELETE`. El `MOVED_TO` resultante se descarta por igualdad de hash
    (`agent/detector.py:802`).
  - La carrera residual (escritura entre la verificación de identidad y el `os.replace`) sólo pierde bytes
    posteriores a la captura: la evidencia capturada es la del instante de la captura. Se declara.
- Detector:
  - `file_modified` exitoso ⇒ baseline sin cambios (como `:985`);
  - `file_created` sin versión aprobada ⇒ se comporta como cuarentena y marca `quarantined` (D72);
  - `file_deleted` ⇒ semántica `auto_restore` (D72).
- `rehydrate` (`agent/decision.py:166`): agregar `quarantine_restore` con regla idempotente. Si el artefacto
  existe y el hash en disco coincide con el aprobado ⇒ `completed`; si el artefacto existe y el disco sigue
  alterado ⇒ reintentar desde el paso 3.
- Journal: acción `"quarantine_restore"` en `write_pending` (`agent/decision.py:98`).
- Comando del operador `quarantine_restore`: handler en `agent/commands.py`, lista blanca en
  `agent/publisher.py:557-560` (H-1) y la misma secuencia.

**Backend:**

- `RuleAction` (`backend/app/modules/rules/models.py:11-15`) y `RejectAction`
  (`backend/app/modules/actions/schemas.py:16-18`).
- `derive_event_status` (`backend/app/modules/events/service.py:135-153`): éxito ⇒ `quarantine_restored`
  (D72a) o `auto_restored` (D72b); fallo ⇒ `pending`.
- `_reject_single` (`backend/app/modules/actions/service.py:322-327`): rama nueva
  `enqueue_quarantine_restore`, con el mismo patrón que `enqueue_quarantine_file`
  (`backend/app/modules/actions/streams.py:203-237`).
- Migración: `ALTER TYPE` idempotentes si aplica D72a. Los nombres de tipo (`eventstatus`, `ruleaction`) son
  [no verificado]: confirmar con `\dT` en la base del laboratorio.

**Frontend:**

- `frontend/src/api/rules.ts:6`, `frontend/src/components/ui/RuleForm.tsx:23`, `frontend/src/pages/Rules.tsx:17`.
- Tercera opción en `frontend/src/components/ui/RejectModal.tsx:37-49` y en `BulkActionBar`.
- Si hay estado nuevo, mapas de clases y listas: `frontend/src/pages/Events.tsx:10-17`,
  `frontend/src/api/dashboard.ts:30`, `EventsTable.tsx:16-22`, `EventDetail.tsx:288`,
  `EventTimeline.tsx:78`, `Dashboard.tsx:23`, `:91`.

### 4.4 A3 liberar, descartar y restaurar desde cuarentena — change 62

**Agente — `agent/quarantine.py`:**

- `release_to_path(action_id, path, expected_sha256) -> QuarantineArtifact`:
  1. calcula el artefacto con `artifact_path(action_id, path)` (`:162-169`); el backend **nunca** envía nombres
     de archivo de artefacto;
  2. `read_artifact` (`:497-499`) autentica AES-GCM y verifica `size` y `sha256` (`:576-579`);
  3. `_validate_identity` (`:584-586`);
  4. rechaza `original_path_known is False` y cualquier `kind` distinto de `regular`/`symlink`; exige
     `metadata["sha256"] == expected_sha256`;
  5. en `kind == "regular"`: escribe `path + ".fim_restore_tmp"` con `O_EXCL` (así el filtro
     `agent/detector.py:682-683` suprime los eventos del temporal); `fchown`/`fchmod` desde `metadata`
     (`mode`, `uid`, `gid`, `agent/quarantine.py:416-418`), con la política `setuid` de D74; `fsync`;
  6. coloca el archivo **sin reemplazar**: `renameat2(..., RENAME_NOREPLACE)` vía ctypes, igual que
     `agent/_fanotify.py` usa libc; alternativa `os.link(tmp, path)` + `os.unlink(tmp)`, que falla con `EEXIST`;
  7. en `kind == "symlink"`: `os.symlink(target, path)`, que falla con `EEXIST` y no sigue el enlace;
  8. reabre con `O_NOFOLLOW`, hashea desde disco y ejecuta `_fsync_directory` (`:108`);
  9. elimina el artefacto (D74).
- `discard(action_id, path)`: autentica e identifica, `unlink` del artefacto y `fsync` del directorio.

**Agente — `agent/baseline.py`:**

- `adopt_released(path, content, metadata, source_event_id)`: archiva la versión aprobada vigente como
  snapshot y escribe `present` con el contenido liberado, respetando el límite de contenido y `oversize` de
  `write_entry`.
- Se ejecuta **antes** de colocar el archivo, para que el `FAN_CREATE`/`FAN_MOVED_TO` resultante se descarte
  por igualdad de hash (`agent/detector.py:802`) y una regla `quarantine` sobre la ruta no lo vuelva a
  cuarentenar.
- Entre la adopción y la colocación no hay `await`. Si la colocación falla, se reescribe la entrada previa,
  conservada en memoria.

**Agente — `agent/commands.py`:**

- `handle_quarantine_release(command, baseline_engine, journal, valkey_client, config, quarantine_store)`:
  1. contención de rutas con `_path_is_within_watch_paths` (`:214`), mismo patrón de `:441-455`;
  2. guarda de `ruleset_version` como en `:249-258` (D74);
  3. libro de `command_id` ejecutados (D74, H-3);
  4. `journal.write_pending(command_id, path, "quarantine_release")`;
  5. `release_to_path`;
  6. `journal.mark_completed`/`mark_failed`;
  7. `_publish_ack(..., "quarantine_release", ...)` (`:62-100`).
  - Errores cerrados: `artifact_not_found`, `quarantine_identity_mismatch`, `artifact_hash_mismatch`,
    `path_occupied`, `legacy_artifact_without_path`, `stale_ruleset_version`.
- `handle_quarantine_discard`: el mismo esqueleto sin baseline.
- Registro: ramas en `dispatch` (`:150-201`) con requisito de journal como en `:158-180`, y tipos en
  `agent/publisher.py:557-560`.
- `rehydrate` (`agent/decision.py:141-208`): las acciones `quarantine_release` y `quarantine_discard`
  **no** se publican como eventos (H-5). Se re-evalúa idempotentemente y se re-emite sólo el ack:
  - liberar: la ruta tiene el hash liberado y el artefacto ya no existe ⇒ `completed`; la ruta está libre y el
    artefacto existe ⇒ colocar;
  - descartar: el artefacto ya no existe ⇒ `completed`.

**Backend:**

| Archivo | Cambio |
|---|---|
| `backend/app/modules/actions/schemas.py` | `QuarantineResolutionKind` (`release \| discard \| restore`); `QuarantineResolutionRequest {event_id: int, expected_sha256: str (64 hex), reason: str (1..500), confirm: Literal[True]}`. |
| `backend/app/modules/actions/router.py` | `POST /actions/quarantine/release`, `/discard` y `/restore`, con `Depends(require_admin)` como las rutas de `:42-114` (`backend/app/core/deps.py:81-87`). 409 si `quarantine_state != quarantined`, si ya hay una resolución activa o si `expected_sha256` no coincide con el hash del evento. |
| `backend/app/modules/actions/service.py` | `_resolve_quarantine(db, valkey_client, event_id, kind, user_id, reason, expected_sha256)`: identidad del artefacto = `Event.event_id` si la cuarentena fue automática, o `PublishedCommand.command_id` del `quarantine_file` `acked` si fue del operador; inserta `QuarantineResolution(pending)`; `_write_audit` (patrón `:228`, `:312`); encola; `db.commit()`; `publish_pending_commands`, igual que `:329-338`. |
| `backend/app/modules/actions/streams.py` | `enqueue_quarantine_release` y `enqueue_quarantine_discard`, con el patrón de `:203-237`: `sign_payload` (`backend/app/core/streams.py:31-34`) y `_record_published_command` (`:60-91`), en la misma transacción (D37/RN-131). Payload: `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `artifact_action_id`, `expected_sha256`, `issued_at`, `schema_version`, `ruleset_version` (sólo en release, D74) y `signature`. La restauración reutiliza `enqueue_restore_file`. |
| `backend/app/modules/agents/command_ack_consumer.py` | En `_handle_command_ack` (`:168-265`), junto a la reconciliación de `:250-253`: `quarantine_release` `ok` ⇒ `upsert_baseline_entry` con `expected_sha256` y resolución `completed`; error o timeout ⇒ resolución `failed`. `command_type` se sigue leyendo de la fila, no del payload (`:182-198`). |
| Modelo | `QuarantineResolution` (SQLModel), importado antes de `create_all` (spec `domain-models`, «main.py importa todos los módulos de modelos…»). Sin FK en cascada hacia `events`: la retención de 30 días de eventos terminales (spec `backend-event-consumer`) no debe borrar la resolución; seguir el criterio de `AuditLog` sin FK o usar `SET NULL`. |
| Migración | `NNN_add_quarantine_resolutions.sql`: `CREATE TABLE IF NOT EXISTS quarantine_resolutions (...)` y `CREATE UNIQUE INDEX IF NOT EXISTS ... ON quarantine_resolutions (event_id) WHERE kind IN ('release','discard') AND status IN ('pending','completed')`. Además los `ALTER TYPE` de D72a si aplican. Prueba de idempotencia con el patrón de `backend/tests/test_event_severity.py:204`. |

**Frontend:**

- `frontend/src/api/actions.ts`: funciones `releaseQuarantine`, `discardQuarantine` y
  `restoreFromQuarantine`.
- `frontend/src/hooks/useEventActions.ts`: mutaciones con invalidación, igual que approve/reject.
- `EventDetail.tsx`: sección «Cuarentena» visible sólo con `quarantine_state === 'quarantined'`, con botones
  «Restaurar versión aprobada», «Liberar» y «Descartar».
- Modal de confirmación con ruta, `sha256`, tamaño y motivo:
  - «Liberar» exige tipear el nombre del archivo y muestra una advertencia si una regla `quarantine` o
    `auto_restore` coincide con la ruta;
  - no hay descarga del artefacto al navegador;
  - el diff mostrado es el `diff_text` ya persistido del evento; no se transfiere contenido nuevo.
- RBAC: el único rol es admin (RN-44). No existe condicional de rol en frontend
  (`frontend/src/components/layout/ProtectedRoute.tsx:44-51` sólo mira `scope`); la autorización es la del
  backend (`require_admin`).

### 4.5 A4 visibilidad (`quarantine_state`) — change 62

- `backend/app/modules/events/router.py`:
  - campo `quarantine_state: str | None` en `EventOut` (`:27-65`), junto a `ack_status` (`:54`);
  - helper `_get_quarantine_state_map(session, events)` análogo a `_get_ack_status_map` (`:175-192`), con
    una consulta por página;
  - asignación en `_to_event_out` y `_to_event_detail_out` (`:195-204`);
  - filtro `quarantine_state: list[QuarantineState] = Query(alias="quarantine_state")` en `list_events`
    (`:82-135`), con subconsultas `EXISTS` sobre `published_commands` y `quarantine_resolutions` antes del
    `COUNT` (`:120-121`).
- Frontend:
  - tipo en `frontend/src/api/events.ts` (junto a `ack_status`, `:52`) y en `EventFilters` (`:83`);
  - filtro «Cuarentena» en `frontend/src/pages/Events.tsx`, separado de `ALL_STATUSES` (`:10-17`);
  - insignia en `EventsTable.tsx`.
- El arreglo de `canApprove` va en el change 60 (§4.2).

### 4.6 A5 port del visor de diferencias — change 61

**Inventario de `1b62905` (padre `6790e40`) contra `devel` `277a458`:**

| Archivo | Δ en L6 | ¿Base = devel? | Contenido |
|---|---|---|---|
| `agent/detector.py` | +121 | idéntico | `_HEX_DUMP_BYTES=256`; campos `is_binary`, `hex_dump_before` y `hex_dump_after` en `DetectedChange`; `_hex_dump` y `_binary_diff_info` ([v10] `:235-286`); `size_delta` en la traza; cableado en la rama `file_modified` ([v10] `:1004-1087`). |
| `agent/decision.py` | +7 | idéntico | Rehidratación con `is_binary=False` y `hex_dump_*=None`, justo después de `diff_text` (`agent/decision.py:148-150`). |
| `agent/experiment_trace.py` | +4 | idéntico | `size_delta` en `_ALLOWED_FIELDS`. |
| `agent/logging.py` | 5 ±, +/− | idéntico | Agrega `hex_dump` a `_SENSITIVE_RE`. |
| `agent/queue.py` | 7 ±, +/− | idéntico | Docstring de permisos que menciona `hex_dump_*`. |
| `backend/app/core/logging.py` | +5 | idéntico | Claves `hex_dump_before` y `hex_dump_after` en la redacción (hoy `diff_text` en `:61`). |
| `backend/app/modules/events/consumer.py` | +29 | idéntico | `_build_payload_dump` también redacta `hex_dump_*` (hoy sólo `diff_text`, `:104-123`). |
| `backend/app/modules/events/models.py` | +10 | idéntico | Columnas `is_binary`, `hex_dump_before` y `hex_dump_after`. |
| `backend/app/modules/events/router.py` | +7 | idéntico | Campos en `EventDetailOut`, sólo en el detalle (admin). |
| `backend/app/modules/events/service.py` | +33 | idéntico | `_bounded_hex_dump` (cota de 4096 caracteres y regex de línea) y persistencia en la ingesta. |
| `backend/db/migrations/016_add_event_binary_diff_metadata.sql` | +24 | nuevo | `ADD COLUMN IF NOT EXISTS` ×3. |
| `frontend/src/components/ui/DiffViewer.tsx` | +187 | idéntico | `parseUnifiedDiff` por hunk ([v10] `:39-69`), `TextDiff` con `ReactDiffViewer` split ([v10] `:71-110`), `BinaryComparison` ([v10] `:112-157`), despachador automático ([v10] `:170-196`). |
| `frontend/src/pages/EventDetail.tsx` | 18 ±, +/− | idéntico | Pasa `isBinary`, hashes y hex dumps a `DiffViewer`; retira el ternario de `:244-250`. |
| `frontend/src/api/events.ts` | +7 | idéntico | Campos en el tipo de detalle. |
| `frontend/src/vite-env.d.ts` | −2 | idéntico | Retira la declaración manual del módulo. |
| Pruebas | `agent/tests/test_detector_binary_diff.py` (nuevo, 180), `agent/tests/test_log_inspection.py` (nuevo, 142), `agent/tests/test_logging.py` (+18), `backend/tests/test_consumer.py` (+91), `backend/tests/test_event_service.py` (+77), `backend/tests/test_logging_sanitize.py` (+12), `frontend/src/components/ui/DiffViewer.test.ts` (+56), `frontend/src/pages/EventDetail.test.tsx` (+24) | idénticos o nuevos | Cobertura de los criterios 2 a 6 de US-09, según `tesis/cierre/evidencia/v10-closure-20260912T190052Z/lanes/l6/CRITERIOS.md`. |

**Factibilidad verificada:**

- Comparación por archivo con `git -C <integration> show 6790e40:<archivo> | cmp - <devel>/<archivo>`: los 20
  archivos preexistentes son idénticos y los 3 restantes son nuevos.
- `git apply --check <l6.patch>` sobre `devel` terminó con código 0.
- **No hay conflicto** en `agent/logging.py` ni en `agent/queue.py`. La base del carril ya contenía el
  equivalente de `ca34335` y `26c6cee`; se descarta la hipótesis contraria.

**Recomendación:** portar como **parche**. No usar cherry-pick: `devel` no resuelve `1b62905` sin traer
objetos del clon. Tampoco fusionar la rama entera (§1.4.3). Pasos del apply:

1. `git -C /home/ezequiel/Facultad/tesis/tesis-fim-serio-worktrees/integration format-patch -1 1b62905 --stdout > <scratch>/l6.patch`.
2. En `devel`: `git apply --check` y luego `git apply`. Si hubo commits intermedios sobre los 23 archivos,
   usar `git apply --3way` tras `git fetch` del clon para disponer de los blobs base.
3. Renumerar `016_add_event_binary_diff_metadata.sql` al número libre y actualizar su comentario (línea 874
   del parche). Ninguna prueba referencia el nombre del archivo. En una base ya migrada por el candidato V10
   la migración es un no-op (`IF NOT EXISTS`).
4. Commit convencional con el cuerpo «Porta 1b62905 (lane/l6-diff, integration/v10)» para la trazabilidad.
5. Rótulo de D76 en `DiffViewer` (texto y binario).
6. E2E de US-09 (§6.3).

**Puntos de conflicto con otros changes** (si 60 se aplica antes que 61, conviene `--3way`):

| Archivo | L6 | Change 60 | Riesgo |
|---|---|---|---|
| `agent/detector.py`, rama `file_modified` | inserta `_binary_diff_info` y `size_delta` alrededor de `:911-924` y del constructor `DetectedChange` | `:984-994` (cuarentena y restauración) | Medio: hunks cercanos. |
| `agent/decision.py` | `:148-150` (payload de rehidratación) | `:166-171` y `:205` (marcado) | Bajo: adyacentes. |
| `frontend/src/pages/EventDetail.tsx` | `:242-251` | `:59`, `:133` | Bajo |

El resto de los carriles de `integration/v10` (l1–l5, l7–l10) quedan fuera de alcance. Si se desea
llevarlos a `devel`, cada uno se porta con su propio change, con la misma técnica.

### 4.7 X-2 clasificación de archivos creados — change 63 (opcional)

- En la rama genérica (`agent/detector.py:863`), si `entry is None and current_hash is not None`, derivar a la
  lógica de `file_created` (`:764-861`). Así se crea la entrada y se evita la ráfaga de `file_modified` de
  §1.3. Es un criterio por estado, coherente con el change 43.
- Alternativa: tratar como `file_created` toda máscara que contenga `FAN_CREATE` o `FAN_MOVED_TO`, aunque
  incluya `FAN_CLOSE_WRITE`. Queda por debajo de la anterior porque el docstring de `:667-668` motiva la
  prioridad actual por kernels que combinan flags, sin detallar el caso; revisar su historia antes de
  invertirla.
- Interacción con el change 60: para una entrada `quarantined` (no `None`) el comportamiento no cambia y se
  compara contra la versión conservada.

---

## 5. Capacidades OpenSpec y deltas de spec

Los deltas se escriben sólo con el CLI (D47/RN-141). Antes y después de cada `openspec archive`, correr
`python3 scripts/check_spec_integrity.py`, que hoy da OK con 44 specs y 249 requisitos. **No renombrar
encabezados de requisito:** un `MODIFIED` con encabezado cambiado cuenta como pérdida para la guarda y obliga
a registrarlo en `CONFIRMED_RENAMES`.

| Change | Capability (`openspec/specs/…`) | Requisito | Tipo |
|---|---|---|---|
| 60 | `agent-baseline` | «Baseline present and absent states» (`:65-79`) | MODIFIED: tercer estado `quarantined`, que conserva contenido. |
| 60 | `agent-baseline` | «Quarantine preserves the last approved baseline version» | ADDED (RN-37 enmendada, D70) |
| 60 | `agent-decision-engine` | «Acción quarantine — aislamiento cifrado local» (`:95-121`) | MODIFIED: escenario de baseline conservada. |
| 60 | `agent-decision-engine` | «Rehidratación de journal al arrancar» (`:140-159`) | MODIFIED: marca `quarantined` tras reintento exitoso. |
| 60 | `agent-approve-reject-handler` | «Handler quarantine_file — cuarentena con journal» (`:87-105`) | MODIFIED: reescribe el texto desactualizado (H-2) y agrega el marcado. |
| 60 | `agent-approve-reject-handler` | «Handler restore_file — restauración desde baseline con journal» (`:64-87`) | MODIFIED: `quarantined` pasa a `present`. |
| 60 | `agent-fanotify-detector` | «El eco de la cuarentena propia no genera eventos» | ADDED (D71) |
| 60 | `frontend-events` | «Aprobar y rechazar un evento individual con manejo de 409» (`:114-133`) | MODIFIED: escenario «sin acciones fuera de `pending`». Partir de la main spec ya commiteada (H-6). |
| 61 | `agent-fanotify-detector` | «Generación de diff unificado para archivos de texto» (`:72-91`) | MODIFIED |
| 61 | `agent-fanotify-detector` | «Metadatos binarios acotados: hashes y hex dump de 256 bytes» | ADDED |
| 61 | `backend-event-consumer` | «Validación de evento en orden barato a caro con rechazo tipado» (`:20-61`) | MODIFIED: hex dump acotado. |
| 61 | `backend-events-api` | «GET /events/{id} con timestamps dobles y contexto proceso» (`:54-76`) | MODIFIED: campos binarios. |
| 61 | `domain-models` | «Modelo Event con EventStatus canónico y optimistic locking» (`:8-25`) | MODIFIED: columnas. |
| 61 | `frontend-events` | «DiffViewer seguro sin dangerouslySetInnerHTML» (`:83-101`) | MODIFIED: el modo lo decide `is_binary` informado por el agente, no un byte nulo en el componente; rótulo D76. |
| 61 | `frontend-events` | «Detalle de evento con timestamps dobles, contexto de proceso y diff seguro» (`:69-83`) | MODIFIED |
| 62 | `agent-decision-engine` | «Acción quarantine_restore» | ADDED (D72) |
| 62 | `agent-decision-engine` | «Cache local de reglas con evaluación glob y negación» (`:8-47`) | MODIFIED si enumera acciones. |
| 62 | `agent-approve-reject-handler` | «Dispatch de comandos entrantes por tipo» (`:8-20`) | MODIFIED |
| 62 | `agent-approve-reject-handler` | «Handler quarantine_release», «Handler quarantine_discard», «Handler quarantine_restore» | ADDED (D74) |
| 62 | `agent-command-dispatch` | «Destructive command handlers are registered at startup» (`:8-29`) | MODIFIED |
| 62 | `backend-approve-reject` | «POST /actions/reject — reject single pending event» (`:44-70`) | MODIFIED: acción `quarantine_restore`. |
| 62 | `backend-approve-reject` | «Comandos restore_file / quarantine_file publicados en Valkey al rechazar» (`:148-164`) | MODIFIED |
| 62 | `backend-approve-reject` | «Resolución de cuarentena: liberar, descartar y restaurar» | ADDED (D73/D74) |
| 62 | `backend-events-api` | «GET /events con paginación y filtros multi-select» (`:8-54`) | MODIFIED: filtro `quarantine_state` (D75). |
| 62 | `domain-models` | «Modelo QuarantineResolution» | ADDED |
| 62 | `domain-models` | «Modelos Rule y RulesetVersion con léxico canónico» (`:25-41`); «Modelo Event…» (`:8-25`) si D72a | MODIFIED |
| 62 | `backend-event-consumer` | «Validación de transición de estado en service.py» (`:127-149`) | MODIFIED sólo si D72a o D73b. |
| 62 | `frontend-events` | «RejectModal con branch baseline_absent» (`:133-148`) | MODIFIED |
| 62 | `frontend-events` | «Acciones de cuarentena en el detalle del evento» | ADDED |
| 62 | `frontend-rules`, `backend-rules` | Requisitos del léxico de acciones | MODIFIED [encabezados no relevados; confirmar en propose]. |
| 63 | `agent-fanotify-detector` | «Dispatch por tipo de evento y campo operation_type en el payload» (`:148-181`) | MODIFIED |

**Alineación con reglas:**

- RN-37 queda cumplida en su intención y enmendada en su letra (D70).
- RN-66 y RN-74 se precisan: `absent` es por aprobación y la cuarentena no produce `absent` local.
  `baseline_entries` del backend no cambia en 60.
- RN-72 no cambia con D73a y D75. Con D72a gana un estado terminal de creación.
- RN-03 queda cumplida por `devel` con el change 61.

---

## 6. Estrategia de pruebas

### 6.1 Change 60

**Agente (pytest).** Extender el banco de `agent/tests/test_restore_feedback_loop.py`: `BaselineEngine`,
`DecisionEngine` y filesystem reales; inyección vía `_process_event`; sin `MagicMock` (reglas en `:13-19`).
Cada prueba de supresión afirma **primero** que la acción ocurrió (artefacto presente, journal `completed`) y
recién después la ausencia de eventos, con el criterio D-7 del change 43.

1. Cuarentena automática sobre `file_modified`: entrada `quarantined`, `content_b64` y `snapshots` iguales a
   los previos, `select_restorable_content` devuelve los bytes aprobados.
2. Lo mismo sobre `file_created` en ruta con entrada previa, y sin entrada previa (queda `quarantined` con
   nulos).
3. Eco automático: `FAN_DELETE` inyectado tras 1 ⇒ cero payloads, sin journal nuevo y entrada intacta.
4. Eco del operador: `handle_quarantine_file` más `FAN_MOVED_FROM` ⇒ cero payloads y entrada `quarantined`.
   Reemplaza la afirmación de `:556-595`.
5. `restore_file` posterior a 1 y 4: archivo byte a byte igual al aprobado, `mode`/`uid`/`gid` restaurados,
   entrada `present`, sin evento por el `MOVED_TO`.
6. Ventana de crash: journal `pending` de `quarantine`, artefacto presente y origen ausente ⇒ `rehydrate`
   marca `quarantined`.
7. Ausencia genuina sin cambios: `FAN_DELETE` sobre una entrada `present` con `alert_only` ⇒ `mark_absent`
   vacía (mantener `agent/tests/test_detector_multi_event.py:81`, `:100`; `test_symlink_hardening.py:166`,
   `:260`).
8. Archivo nuevo en ruta `quarantined`: se publica un evento y la entrada **no** se sobrescribe.
9. Unitarias de `BaselineEngine`: `mark_quarantined` preserva snapshots; `add_snapshot` sobre `quarantined`;
   `update_from_command` desde `quarantined` pasa a `present`.
10. Actualizar `agent/tests/test_audit_fixes.py:868`.

**Cómo probar que A1 no regresa `auto_restore` ni las cadenas de supersede:**

- Correr completas `test_restore_feedback_loop.py` (bombas de eventos con techo duro de iteraciones,
  `test_n_tampers_produce_at_most_n_events` en `:343`), `test_decision.py`, `test_baseline_restore.py`,
  `test_detector_multi_event.py`, `test_audit_fixes.py` y `test_commands.py`.
- Prueba nueva «cuarentena → regla cambia a `auto_restore` → archivo reaparece alterado»: exactamente un
  evento `auto_restored`, archivo restaurado y entrada `present`, dentro del techo de iteraciones.
- Prueba nueva de cadena en el agente: dos modificaciones sobre una ruta recreada tras la cuarentena ⇒ el
  segundo payload lleva `parent_event_id` del primero (`_pending`, `agent/detector.py:926-937`).
- En el backend, las pruebas de supersede existentes (`backend/tests/test_c22_consumer.py`,
  `test_event_consumer_c11.py`, `test_event_status_derivation.py`) siguen verdes.
- Prueba nueva: un evento `quarantined` no supersede ni es supersedido por el siguiente `pending` de la misma
  ruta (`get_pending_event_for_path` sólo busca `pending`).

**Frontend (vitest):** `EventDetail.test.tsx` parametrizada por estado. **Backend (pytest):** contrato 409
para `alert_only`.

**Laboratorio privilegiado (patrón L7):**

- Base: `docker-compose.acceptance-lab.yml` con agente `cap_add: [SYS_ADMIN, DAC_READ_SEARCH]` y script en el
  estilo de `tesis/cierre/evidencia/v10-closure-20260912T190052Z/lanes/l7/us24/scripts/run_us24_fanotify_lab.sh`.
- **Antes del arreglo**, en `devel` actual, capturar la evidencia de X-1 para declararla con respaldo:
  - aprobar un archivo, crear una regla `quarantine`, modificar;
  - esperado: un evento `quarantined` más un `file_deleted` `pending` con `action_error=file_not_found`;
  - la entrada, descifrada dentro del contenedor del agente, queda `absent` sin contenido.
- **Después del arreglo:**
  - un solo evento;
  - entrada `quarantined` con contenido;
  - `restore_file` desde la consola recupera el hash aprobado;
  - «Rechazar → Cuarentena» no produce `file_deleted`.
- X-2: `mkdir` y creación con escritura inmediata; registrar el `event_type` de 20 repeticiones.

### 6.2 Change 61

- Portar las pruebas del parche (§4.6) y verificar las suites de agente, backend y frontend.
- **E2E en el laboratorio aislado (Playwright)**, extendiendo `frontend/e2e/us-isolated-lab.spec.ts` con sus
  helpers `composePython` y `agentPython` (`:21-36`):
  - *US-09 texto:* aprobar un archivo de texto, modificarlo desde el contenedor del agente y abrir el detalle.
    Se afirma el diff lado a lado (`ReactDiffViewer`), que un `<script>` del contenido aparece como texto
    escapado y el rótulo D76.
  - *US-09 binario:* aprobar un binario de más de 256 bytes y modificarlo. Se afirman el indicador de hashes
    distintos y los dos hex dumps de 16 filas, y que no hay diff textual.
  - *Privacidad:* `docker compose logs agent backend` sin el marcador de contenido insertado en ambos
    archivos (criterio 6 de US-09).
- Migración renumerada ejecutada dos veces sin error.

### 6.3 Change 62

- **Agente:**
  - liberación exitosa: archivo, hash, entrada `present` con snapshot de la versión anterior, artefacto
    eliminado y sin evento por el `FAN_CREATE`;
  - `path_occupied`: la ruta existe; el artefacto se conserva y la entrada no cambia (rollback);
  - artefacto alterado (un byte invertido): `QuarantineIntegrityError`, ack de error y nada escrito;
  - identidad cruzada (`action_id` de otra ruta), `expected_sha256` distinto y legacy sin ruta;
  - replay del mismo `command_id`: sin efecto. Replay de un `quarantine_file` antiguo tras liberar: rechazado
    por el libro de comandos;
  - liberación con regla `quarantine` activa: no se re-cuarentena;
  - descarte: sólo el artefacto autenticado;
  - `quarantine_restore`: las cuatro filas de fallo de D72 más el éxito (sin `FAN_DELETE`, artefacto
    presente y archivo aprobado);
  - rehidratación de cada acción nueva sin publicar eventos sintéticos.
- **Backend:**
  - 401 y 403 en las rutas nuevas;
  - 409 por estado, resolución activa o hash;
  - dos liberaciones concurrentes ⇒ una sola resolución (índice único);
  - comando firmado verificable con `sign_payload`;
  - `PublishedCommand.command_type` correcto;
  - `command_ack` `ok` reconcilia `baseline_entries`; error y timeout marcan la resolución `failed`;
  - tabla de derivación de `quarantine_state` y filtro con paginación correcta;
  - migración idempotente.
- **Frontend:** botones sólo con `quarantine_state === 'quarantined'`; confirmación con nombre tipeado; sin
  descarga; opción `quarantine_restore` en `RejectModal` y `RuleForm`; clientes en `api/actions.test.ts`.
- **E2E en el laboratorio aislado:**
  - cuarentena automática ⇒ «Liberar» ⇒ ack `acked` ⇒ archivo presente con el hash esperado ⇒ entrada
    `present` en el agente ⇒ sin evento nuevo ⇒ `quarantine_state=released`;
  - «Descartar» ⇒ artefacto ausente en `/var/lib/fim-agent/quarantine` ⇒ `discarded`;
  - «Restaurar versión aprobada» sobre un evento cuarentenado ⇒ archivo aprobado, `quarantine_state` sigue
    `quarantined`.

### 6.4 Escenarios manuales

1. Diagnóstico §8.1 repetido tras el change 60: el `restore_file` posterior **tiene éxito**.
2. «Rechazar → Cuarentena» con reglas `manual_review`, `alert_only` y `auto_restore` sobre la ruta: sin
   evento adicional y sin restauración implícita.
3. Evento `alert_only` en la consola: sin botones Aprobar ni Rechazar.
4. Modificar tres veces un archivo pendiente: el tercer diff se muestra rotulado como acumulado respecto de la
   versión aprobada.
5. Liberar un archivo con una regla `quarantine` activa: permanece en disco y aparece la advertencia de regla.
6. Liberar con la ruta ocupada: error visible y artefacto conservado.
7. Reiniciar el agente con `state.json` borrado tras una liberación: ningún comando antiguo re-ejecuta
   efectos.

---

## 7. Revisión de seguridad

| Riesgo | Control propuesto | Residual |
|---|---|---|
| **Liberar contenido malicioso** | Sólo admin (`require_admin`, `backend/app/core/deps.py:81-87`); de a un evento; motivo obligatorio; nombre tipeado; muestra `sha256`, tamaño, ruta y el diff ya persistido; sin descarga al navegador; `audit_log` con hash (W18); advertencia si una regla coincide; política `setuid`/`setgid` (D74); no sobrescribe; adopción explícita de baseline. | Un admin puede reintroducir malware conscientemente. Es una decisión humana auditada. |
| **Autorización** | Backend: única vía por `require_admin`. Agente: HMAC por agente (`agent/streams.py:31-35`), filtro `target_agent_id` (`agent/commands.py:127-131`), contención en `watch_paths` (`:214`). El nombre del artefacto se calcula localmente desde `(action_id, path)` y el backend nunca envía rutas del directorio de cuarentena. | Rol único (RN-44): no hay separación entre quien aprueba y quien libera. |
| **Replay de comandos** | Libro local persistente de `command_id` destructivos (`quarantine_file`, `restore_file`, `quarantine_release`, `quarantine_discard`, `quarantine_restore`); idempotencia por artefacto ausente (liberar, descartar); `ruleset_version` con guarda en liberar; índice único de resolución en backend; el ack consumer toma `command_type` de la fila (`backend/app/modules/agents/command_ack_consumer.py:182-198`). | Sin expiración por `issued_at`, por el desfase de relojes. Hoy un cursor reiniciado a `"0-0"` relee el stream completo (H-3); el libro lo neutraliza sólo para comandos registrados tras su despliegue. |
| **Manipulación del artefacto** | AES-256-GCM autenticado con metadatos cifrados (`agent/quarantine.py:540-560`, `:576-579`); identidad `fstat` contra `lstat` al leer (`:524-526`); directorio `0700` (`:150-160`) y artefactos `0400` (RN-36); identidad `action_id`/`original_path` (`:584-586`); `expected_sha256` independiente, enviado por el backend. | Root con `master_secret` puede forjar artefactos válidos (RN-35 lo declara). |
| **Carrera en la reubicación** | Temporal `O_EXCL`; `RENAME_NOREPLACE` o `link` (sin reemplazo); `O_NOFOLLOW` al verificar; symlinks recreados con `os.symlink`, sin seguirlos. | Un proceso puede crear la ruta entre la verificación y la colocación: la operación falla cerrada (`path_occupied`). |
| **Privacidad de hex dumps y diffs (Tabla 21)** | Detalle sólo admin (D57/RN-151, `backend/app/modules/events/router.py:145`); redacción por clave en logs de agente y backend y en `payload_dump` (L6); cota de 256 bytes y 4096 caracteres; sin diff incremental (D76); la liberación no transfiere contenido. | Los hex dumps viajan por la cola local sin cifrar y por Valkey, igual que `diff_text` (Tabla 21a, `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md:381`), y se retienen con el evento. **Agregar filas para `hex_dump_before`/`hex_dump_after` y `quarantine_resolutions` (sin contenido) en la Tabla 21.** |
| **Supresión del eco como punto ciego** | Criterio por estado (D71) acotado a entradas `quarantined`; una creación en esa ruta sí se reporta. | El borrado de un archivo recreado en una ruta cuarentenada no se reporta (D71). |

---

## 8. Orden sugerido y porción mínima para la tesis

### 8.1 Orden

1. Registrar D70 y D71 (documentación; excepción de CLAUDE.md). D76 si el change 61 incluye el rótulo.
2. **Change 61** (`event-diff-binary-port`). Es mecánico y hoy aplica limpio; cada commit sobre los 23
   archivos (incluidos `agent/detector.py` y `EventDetail.tsx`, que toca el change 60) degrada esa condición.
3. **Change 60** (`quarantine-baseline-preservation`).
4. Change 63 (opcional).
5. Registrar D72–D75 y luego el **change 62** (`quarantine-recovery-actions`).

Si la fecha de la tesis sólo admite un change, invertir 2 y 3 y aplicar 61 con `--3way`.

### 8.2 Porción mínima para el próximo candidato

| Base del candidato | Changes necesarios | Motivo |
|---|---|---|
| `devel` | **60 + 61** | Sin 61, un candidato desde `devel` retrocede respecto de V10 en US-09 (modo binario, detección automática y `react-diff-viewer-continued` existen sólo en `7a7ee50`). Sin 60 persisten Q-1, X-1 y U-1. |
| `integration/v10` (`7a7ee50`) sin cambios | Ninguno; declarar limitaciones (§8.3) | Q-1, X-1 y U-1 están presentes (`[v10] agent/detector.py:958`, `:1124`; `[v10] EventDetail.tsx:68`). |
| `integration/v10` más el change 60 | No recomendado | Obliga a portar 60 en sentido inverso y a sostener dos implementaciones. |

Cualquier candidato nuevo exige repetir la validación consolidada (suites, E2E y laboratorios), como ocurrió
con `7a7ee50`.

### 8.3 Limitaciones a declarar si Q-1 y U-1 no se corrigen

- **L-1 (Q-1, ampliado por X-1).**
  - Tras una cuarentena, tanto automática como iniciada por el operador, el agente borra de su baseline local
    la última versión aprobada y sus snapshots.
  - Desde ese momento no puede restaurarse la versión sana de ese archivo, ni automática ni manualmente, hasta
    una nueva aprobación.
  - Esto contradice RN-37.
  - Excepción: si una regla `auto_restore` coincide con la ruta en el camino del operador, el eco restaura
    implícitamente el archivo.
- **L-2 (X-1).** Cada cuarentena automática genera, además del evento `quarantined`, un evento `file_deleted`
  en estado `pending` con `action_error=file_not_found`, originado por la propia eliminación del archivo por
  el agente. Verificado por lectura de código; la afirmación cuantitativa requiere la corrida de laboratorio
  de §6.1.
- **L-3 (Q-2).** El producto no ofrece liberar, descartar ni restaurar desde un artefacto de cuarentena. Un
  falso positivo sólo se resuelve fuera del producto, como root y con `master_secret`.
- **L-4 (Q-4).** El mismo resultado físico se registra como `quarantined` (automático) o `rejected`
  (operador); filtrar por `quarantined` no muestra lo cuarentenado por el operador.
- **L-5 (U-1).** La consola ofrece Aprobar y Rechazar en eventos `alert_only`; la operación siempre termina en
  409.
- **L-6 (X-2).** Un archivo creado inmediatamente después de su directorio puede reportarse como
  `file_modified`, sin entrada de baseline, y generar eventos repetidos hasta su aprobación. Mecanismo
  verificado por lectura y observado en el ensayo A-3; sin prueba dedicada.
- Sólo para `devel`: **L-7 (D-1).** US-09 no muestra comparación binaria ni usa el visor especificado, a
  diferencia de V10.

---

## 9. Decisiones que requieren al usuario

1. **D70:** representación en la baseline (A: estado `quarantined`, recomendada; B: campo sobre `absent`) y
   aceptación de que las entradas ya vaciadas no se recuperan.
2. **D71** (confirmación): aceptar la supresión del eco y su punto ciego acotado.
3. **D72:** estado resultante de `quarantine_restore` (a: `quarantine_restored`, recomendada; b:
   `auto_restored` más `quarantine_state`); comportamiento sin versión aprobada y ante `file_deleted`;
   disponibilidad como regla, como rechazo o ambas.
4. **D73:** entidad `quarantine_resolutions` (a, recomendada) o transiciones nuevas en RN-72 (b).
5. **D74:** si liberar adopta la baseline; política `setuid`/`setgid`; eliminar el artefacto tras liberar;
   `ruleset_version` en la liberación; libro de comandos destructivos.
6. **D75** (confirmación): valores y precedencia de `quarantine_state`.
7. **D76:** sólo rótulo (recomendado) o diff incremental.
8. **Planificación:**
   - ¿Los changes 60 y 61 entran al próximo candidato, o se declaran L-1 a L-7 sobre V10?
   - ¿La numeración 60–63 y D70–D76 queda después del paquete del instalador, o se adelanta?
