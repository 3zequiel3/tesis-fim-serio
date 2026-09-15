# Cuarentena y diff de contenido — diagnóstico y arreglos propuestos

> Documento de exploración. No implementa nada. Todo cambio de código derivado debe pasar por un change OPSX
> (CLAUDE.md). Estado verificado sobre `devel` (`2f84d60`) y contrastado con el candidato V10 `integration/v10`
> (`7a7ee50`). Las citas `archivo:línea` corresponden a `devel` salvo indicación contraria.

## 1. Objetivo y alcance

Diagnosticar el comportamiento real de la cuarentena y del visor de diferencias (US-09, US-12, RN-34 a RN-37) y
proponer arreglos independientes del change de despliegue (`vps-deployment-readiness`) y del instalador unificado
(`instalador-unificado-y-token-de-union.md`).

Fuera de alcance: rediseñar el motor de reglas, cambiar la criptografía de la cuarentena (HKDF `quarantine-v1`,
AES-256-GCM) o su formato `.fimq`.

## 2. Estado actual (verificado)

### 2.1 Diff de contenido

| Aspecto | Comportamiento | Evidencia |
|---|---|---|
| Cuándo se genera | Solo en `file_modified`; `file_created`, `file_deleted` y `file_absent` llevan `diff_text=None` | `agent/detector.py:895-924`, `:824`, `:719`, `:898` |
| Contra qué compara | Contenido activo de la baseline cifrada (`content_b64`), leído antes de mutarla | `agent/detector.py:684`, `:902-924`; `agent/baseline.py:76` |
| Límites | UTF-8 estricto, sin controles, ≤ 1 MiB; symlinks nunca | `agent/detector.py:34`, `:180-218`, `:920-923` |
| Backend | Revalida patch unificado seguro, trunca a 1 MiB con marcador, persiste en `events.diff_text` | `backend/app/modules/events/service.py:34-76`, `:270`, `:341`; `models.py:52` |
| Exposición | Solo `GET /events/{id}` (admin); el listado no lo incluye; redacción en logs y `payload_dump` | `events/router.py:68-72`, `:138-151`; `core/logging.py:58-61`; `events/consumer.py:104-123` |
| Visor en `devel` | `<pre>` con el patch crudo; sin modo binario, sin detección automática; `react-diff-viewer-continued` declarado pero no importado | `frontend/src/components/ui/DiffViewer.tsx:1-29`; `pages/EventDetail.tsx:242-251`; `package.json:22` |
| Visor en `7a7ee50` | `react-diff-viewer-continued` por fragmento, comparación de hashes y hex dump (256 bytes por lado), detección automática, migración 016 | `integration/v10`: `DiffViewer.tsx:39-69`, `:112-196`; carril `lanes/l6/CRITERIOS.md` |
| Pruebas | Unitarias e integración de componente; ninguna E2E de archivo real → diff renderizado | `agent/tests/test_detector_diff.py`; `backend/tests/test_event_service.py:180-320`; sin coincidencias en `frontend/e2e/` |

Observación del usuario (consola `devel`, 2026-09-15): un archivo recién creado muestra «Diff textual no disponible
para este evento» y la modificación posterior del mismo archivo muestra el patch en texto plano. Ambos casos
coinciden con el código de `devel`; el modo binario no está desplegado en esa rama.

### 2.2 Cuarentena

**Dos caminos con resultado distinto:**

| | Regla con `action: quarantine` (automática) | Operador: «Rechazar → Cuarentena» (US-12) |
|---|---|---|
| Disparo | `DecisionEngine.evaluate_and_act` | `POST /actions/reject` con `action=quarantine` sobre un evento `pending` |
| Estado del evento | `quarantined` (`events/service.py:135-153`) | `rejected` (`actions/service.py:283-301`, `:292`) |
| En disco | Archivo cifrado en `/var/lib/fim-agent/quarantine/*.fimq` y `unlink` del origen | Igual, vía comando `quarantine_file` (`agent/commands.py:421-505`) |
| Ruta original | Vacía | Vacía |
| Baseline local | **Reemplazada por `absent`, sin contenido ni snapshots** (`agent/detector.py:849`, `:987`; `agent/baseline.py:385-400`) | Sin cambios (el handler no toca la baseline) |

Detalle del artefacto: captura con verificación de identidad (rechaza hardlinks, symlinks como destino textual),
escritura cifrada con permisos `0400`, verificación de hash y recién entonces `os.unlink` del origen
(`agent/quarantine.py:171-198`, `:365-496`, `:588-629`). Nombre opaco `sha256(action_id‖ruta).fimq`
(`:162-169`). Retención configurable 1–365 días (30 por defecto) con mantenimiento al arrancar y cada 24 h
(`agent/config.py:27`; `agent/__main__.py:184-235`; `agent/quarantine.py:200-267`).

**Máquina de estados:** `quarantined` es terminal (`events/service.py:90-98`; RN-72). Aprobar o rechazar exige
`status = pending` (`actions/service.py:202`, `:289`) y devuelve 409 en cualquier otro estado. No existe comando,
endpoint ni botón para liberar, restaurar o inspeccionar un artefacto de cuarentena: el dispatcher del agente sólo
enruta `baseline_update`, `restore_file`, `quarantine_file`, `update_config` y `rescan_baseline`
(`agent/commands.py:106-201`), y la lectura de artefactos con contenido sólo se usa en pruebas.

**Respuestas directas:**

- ¿La cuarentena revive el archivo en una versión sana? **No.** Mueve el archivo modificado y deja la ruta vacía.
  Restaurar la versión sana es la acción `auto_restore` / `restore_file`, distinta.
- ¿Qué pasa si se aprueba desde cuarentena? **No es posible:** la API responde 409 y la consola no muestra los
  botones para `quarantined`. El único recurso ante un falso positivo es descifrar el `.fimq` como root con el
  `master_secret`, fuera de cualquier flujo del producto.

## 3. Defectos y brechas

| ID | Severidad | Descripción | Evidencia | Presente en `7a7ee50` |
|---|---|---|---|---|
| Q-1 | Alta | Tras una cuarentena automática, `mark_absent` sobrescribe la entrada con `content_b64=None` y `snapshots=[]`: se pierde la última versión aprobada y ya no puede restaurarse. Contradice RN-37 («El baseline permanece intacto») | `agent/detector.py:849`, `:987`; `agent/baseline.py:385-400`; `docs/reglas_de_negocio.md:284-288` | Sí (`agent/detector.py:1119`, `:1124`) |
| Q-2 | Alta | No existe liberación ni recuperación de cuarentena desde el producto | `agent/commands.py:106-201`; ausencia de rutas en `backend/app/modules/**/router.py` | Sí |
| Q-3 | Media | No existe «cuarentena + restauración»: el operador debe elegir entre conservar evidencia (cuarentena, ruta vacía) o recuperar el servicio (restauración, sin conservar el archivo alterado) | `agent/decision.py:219-304` | Sí |
| Q-4 | Media | El mismo resultado físico produce `quarantined` o `rejected` según el camino; filtrar por `quarantined` no muestra lo cuarentenado por el operador | `events/service.py:135-153`; `actions/service.py:292`, `:312` | Sí |
| U-1 | Media | La consola muestra Aprobar/Rechazar para `alert_only`, pero el backend sólo acepta `pending`: siempre termina en 409 | `frontend/src/pages/EventDetail.tsx:59`; `actions/service.py:202`, `:289` | Sí (`EventDetail.tsx:68`) |
| D-1 | Alta (para `devel`) | Modo binario, detección automática y `react-diff-viewer-continued` sólo existen en `integration/v10`; `devel` conserva la dependencia sin uso | §2.1 | No aplica |
| D-2 | Baja | El diff de modificaciones sucesivas sobre un archivo pendiente es acumulado contra la baseline aprobada, no incremental, y la consola no lo aclara | `agent/detector.py:684`, `:911-919`, `:989-993` | Sí |
| D-3 | Baja | Sin prueba E2E de US-09 ni de los flujos visuales de US-12 | `frontend/e2e/`; `docs/trazabilidad_us_tests.md:407-421` | Sí |
| X-1 | A confirmar | El `unlink` del origen realizado por el propio agente podría generar un evento `file_deleted` posterior; no se verificó cómo se filtra ni si altera la baseline en el camino del operador | `agent/quarantine.py:626` | Sin verificar |
| X-2 | A confirmar | Un archivo creado inmediatamente después de su directorio puede clasificarse como `file_modified` (hallazgo del ensayo A-3); consistente con la prioridad de `FAN_CLOSE_WRITE` en `_classify_event` | `agent/detector.py:662-678`; README de A-3 | Sin verificar con prueba dedicada |

## 4. Arreglos propuestos

### 4.1 A1 — Cuarentena sin pérdida de la baseline (Q-1)

Alinear el código con RN-37. Tras cuarentenar, conservar `content_b64`, `hash`, metadatos y `snapshots` de la última
versión aprobada. Representar la ausencia física con un estado propio de la entrada (por ejemplo
`status="quarantined"` o un campo `absent_since`/`quarantine_artifact`) en lugar de `absent`, de modo que:

- `select_restorable_content` siga devolviendo la versión sana;
- un nuevo `file_created` en la misma ruta se compare contra esa versión y genere diff;
- la reconciliación de baseline no confunda «cuarentenado» con «debe no existir».

Pruebas: cuarentena automática de `file_modified` y de `file_created` → la entrada conserva contenido y snapshots;
`restore_file` posterior recupera la versión aprobada byte a byte; migración de entradas ya marcadas `absent` por
cuarentenas previas (no recuperables: documentarlo).

### 4.2 A2 — Acción «cuarentena y restaurar» (Q-3)

Nueva opción de regla y de rechazo que ejecute, en una sola operación registrada en el journal: captura cifrada del
archivo alterado → restauración de la versión aprobada en la ruta → verificación de hash → `event_ack`. Si falla la
restauración, el artefacto de cuarentena se conserva y el evento informa `action_failed` con el motivo.

Decisión de negocio requerida (nueva D/RN): nombre de la acción (`quarantine_restore`), estado resultante del evento
(`quarantined` con indicador de restauración o un estado nuevo) y su lugar en la tabla RN-72.

### 4.3 A3 — Liberación y descarte de cuarentena (Q-2)

Acciones de administrador sobre un evento con artefacto de cuarentena:

| Acción | Efecto en el agente | Efecto en la baseline | Registro |
|---|---|---|---|
| Liberar (aceptar el cambio) | Descifra el artefacto, verifica hash e identidad de ruta, lo reubica en la ruta original sin sobrescribir contenido existente | Adopta el hash liberado como nueva versión aprobada (equivalente a `baseline_update`) | `audit_log`, `event_ack` |
| Restaurar versión sana | `restore_file` desde la baseline (requiere A1) | Sin cambios | `audit_log`, `event_ack` |
| Descartar | Elimina el artefacto antes de la retención | Sin cambios | `audit_log`, `event_ack` |

Diseño a decidir:

- **Estado del evento.** RN-72 define `quarantined` como terminal. Opciones: (a) mantenerlo terminal y registrar la
  resolución en una entidad nueva `quarantine_resolutions` enlazada al evento; (b) agregar transiciones
  `quarantined → approved | rejected`, modificando RN-72 con una decisión explícita. La opción (a) no altera
  criterios existentes.
- **Comandos.** `quarantine_release` y `quarantine_discard` firmados con HMAC (C7) y con `ruleset_version` (C11),
  confirmados por `event_ack` (C3), con journal previo (W2).
- **Consola.** Botones sólo para administradores en eventos con artefacto; confirmación explícita; la liberación
  muestra hash, tamaño y diff si el contenido es texto, sin descargar el archivo al navegador por defecto.
- **Riesgo.** Liberar reintroduce contenido potencialmente malicioso: exigir confirmación reforzada y auditoría.

### 4.4 A4 — Visibilidad unificada (Q-4) y botones correctos (U-1)

- Exponer en `EventOut`/`EventDetailOut` un campo derivado (`quarantine_state`: `none | quarantined | released |
  discarded`) calculado a partir del comando `quarantine_file` y su `event_ack`, y permitir filtrarlo, sin cambiar
  los estados canónicos.
- `EventDetail`: `canApprove` sólo para `pending`. Prueba de componente para cada estado y prueba de contrato que
  confirme 409 fuera de `pending`.

### 4.5 A5 — Visor de diferencias en `devel` (D-1, D-2, D-3)

- Portar a `devel` el trabajo del carril L6 validado en `7a7ee50` (commit `1b62905` y la migración 016) o, mejor,
  resolver la estrategia de integración de `integration/v10` en `devel` para no mantener dos implementaciones.
- Rotular el diff en la consola: «Cambios respecto de la última versión aprobada». Un diff incremental entre eventos
  de una cadena requeriría conservar el contenido de cada versión pendiente, lo que amplía la superficie de datos
  sensibles (Tabla 21); se propone no implementarlo y sólo aclarar la semántica.
- Prueba E2E en el laboratorio aislado: modificación real de un archivo de texto y de uno binario → detalle del evento
  con el modo correcto.

## 5. Impacto

- **Agente:** `agent/detector.py`, `agent/baseline.py` (estado de entrada y migración), `agent/decision.py` (A2),
  `agent/commands.py` y `agent/quarantine.py` (A3: lectura con contenido, reubicación segura).
- **Backend:** `actions/{router,service,schemas,streams}.py`, `events/{service,router}.py`, migración para
  `quarantine_resolutions` o para `quarantine_state`, pruebas de contrato.
- **Frontend:** `EventDetail.tsx`, `DiffViewer.tsx`, `BulkActionBar.tsx`, filtros de eventos.
- **Documentación canónica:** RN-37 (aclarar la representación de la ausencia), nuevas D/RN para A2 y A3, RN-72 sólo
  si se elige la opción (b); US-12 y US-09 sin cambio de criterios.
- **OpenSpec:** capabilities de agente (decisión, baseline, cuarentena, comandos), backend de acciones y eventos,
  frontend de eventos.

Change sugerido: `quarantine-recovery-and-diff-fixes`, independiente de `vps-deployment-readiness`. A1 y U-1 son
correcciones acotadas que pueden adelantarse en un change propio si se prioriza el cierre de la tesis.

## 6. Decisiones para el usuario

1. ¿A1 y U-1 se corrigen antes del próximo candidato de la tesis, o todo el paquete queda como trabajo futuro?
2. Estado del evento tras liberar/descartar: entidad separada (a) o nuevas transiciones de RN-72 (b).
3. ¿Se incorpora la acción «cuarentena y restaurar» (A2) como opción por defecto del rechazo?
4. Estrategia para `devel` frente a `integration/v10`: portar L6 o integrar la rama completa.

## 7. Impacto en la tesis

Q-1 y U-1 afectan al candidato V10 (`7a7ee50`) y deberían declararse como limitaciones si no se corrigen: la tesis
describe la cuarentena como conservación de evidencia sin modificar la baseline (RN-37), y el código automático no lo
cumple. Corregirlos implica un candidato nuevo y repetir la validación consolidada. A2, A3 y la E2E de US-09 encajan
como trabajo futuro del Capítulo 8.

## 8. Escenarios de verificación manual

1. **Q-1:** aprobar un archivo de texto; crear una regla `quarantine` sobre su ruta; modificarlo; confirmar que la
   ruta queda vacía, que existe un `.fimq` y que un `restore_file` posterior falla por falta de contenido restaurable.
2. **Q-4:** cuarentena automática sobre A y «Rechazar → Cuarentena» sobre B; comparar estados (`quarantined` frente a
   `rejected`) y artefactos.
3. **Aprobar desde cuarentena:** `POST /actions/approve` con el `event_id` y la `version` de un evento `quarantined`
   → 409.
4. **U-1:** abrir un evento `alert_only`, pulsar Aprobar → 409.
5. **D-1:** modificar un binario vigilado en `devel` → «Diff textual no disponible»; repetir en `7a7ee50` → hashes y hex
   dump.
6. **D-2:** modificar tres veces un archivo pendiente → el tercer diff muestra el acumulado desde la versión aprobada.
7. **X-1:** tras «Rechazar → Cuarentena», revisar si aparece un `file_deleted` para la misma ruta y el estado de su
   entrada de baseline.
