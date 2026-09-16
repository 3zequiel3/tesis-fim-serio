## Context

El contrato entre el decision engine del agente y la ingesta del backend está cortado en un punto exacto y verificable. El agente enriquece el payload del evento con el resultado de su decisión:

- `agent/decision.py:61` evalúa `action = self._rules.evaluate(change.path)`, con vocabulario cerrado `auto_restore | quarantine | manual_review | alert_only` y default `alert_only` (RN-06, `agent/rules.py:62-74`).
- `agent/decision.py:65` escribe `payload["action"] = action`.
- `agent/decision.py:80` escribe `payload["action_failed"] = True` **solo** en la rama `except _ActionFailed`. La ruta de éxito nunca escribe la clave, así que todo consumidor debe leerla con `.get("action_failed", False)` — el propio detector ya lo hace así (`agent/detector.py:499`, `582`, `687`).

Ese payload llega intacto al backend: `_build_payload` hace `**event_data` sin allowlist (`agent/publisher.py:139-148`) y firma el dict completo con HMAC; el consumer valida firma y schema y pasa el payload entero a `ingest_event` (`backend/app/modules/events/consumer.py:241`, `281-289`). Del otro lado, `ingest_event` lee `event_data.get("status", "pending")` (`service.py:141`) — una clave que el agente nunca emite — y el constructor `Event(...)` (`service.py:169-188`) lee ~10 claves y descarta silenciosamente `action`, `action_failed`, `event_type`, `operation_type`, `hash_expected` y `diff_text`.

Consecuencia medible: `EventStatus.auto_restored`, `EventStatus.quarantined` y `EventStatus.alert_only` (`models.py:10-17`) son inalcanzables. Toda fila de `events` nace `pending`. `resolved_at` y `resolved_by` (`models.py:49-50`, ambas nullable) nunca se setean en la ingesta.

Restricciones que enmarcan el diseño:

- **D3 — sin Alembic**: las migraciones son SQL crudo idempotente en `backend/db/migrations/`, numeradas `NNN_descripcion.sql`, aplicadas a mano con `psql $DATABASE_URL -f`. No hay runner automatizado; las bases nuevas se crean con `SQLModel.metadata.create_all()`. La última es `006_add_event_severity.sql`.
- **D35/RN-129** fija la tabla de derivación, la semántica de `action_failed`, la regla de `resolved_at`/`resolved_by`, la limpieza del léxico y las excepciones. Este diseño no la reinterpreta: la implementa.
- **RN-71**: todo valor de estado en código, schemas, JSON y logs va en snake_case minúsculas.
- El frontend no tiene un componente `Badge` compartido: los badges son `<span>` inline y el mapa `STATUS_CLASSES` está triplicado (`EventsTable.tsx:10-19`, `EventDetail.tsx:247-263`, `EventTimeline.tsx:70-80`). El único patrón compartido y testeado es el mapper puro `frontend/src/utils/ackStatus.ts` + `ackStatus.test.ts`.

## Goals / Non-Goals

**Goals:**

- Hacer alcanzables los tres estados terminales de origen agente, derivándolos en el backend desde datos que el agente ya publica.
- Preservar la información de un intento de remediación fallido en una columna propia (`action_failed`) en vez de perderla al colapsar todo a `pending`.
- Cerrar el vector por el cual un agente comprometido podría dictar el `EventStatus` de una fila.
- Dejar `event_type` con su vocabulario declarado, sin contaminación del resultado de la acción.
- Cubrir el hueco de testing que permitió que este bug existiera: tests que atraviesan el límite real agente→backend, no payloads a mano.

**Non-Goals:**

- Persistir `diff_text`, `operation_type` o `hash_expected` — descartados hoy por el mismo constructor, pero son otra change.
- Arreglar la unit de systemd cuyo `ProtectSystem=strict` hace fallar físicamente el auto_restore — otra change.
- Introducir filtros, ordenamiento o índices nuevos por `action_failed` en la API de eventos.
- Refactorizar la triplicación de `STATUS_CLASSES` en el frontend.
- Cambiar `VALID_TRANSITIONS` o la máquina de estados de RN-72. Esta change afecta el estado **de creación**, no las transiciones.

## Decisions

### D-1 — La derivación vive en el backend, en una función pura, y el `status` del payload se elimina

Se agrega a `backend/app/modules/events/service.py` una función pura `derive_event_status(action: str | None, action_failed: bool) -> EventStatus` y se **borra** la lectura `event_data.get("status", "pending")` de `ingest_event`. La función implementa literalmente la tabla de D35/RN-129:

| `action` | `action_failed` | `status` |
|---|---|---|
| `auto_restore` | `false` | `auto_restored` |
| `quarantine` | `false` | `quarantined` |
| `alert_only` | — (indiferente) | `alert_only` |
| `manual_review` | — | `pending` |
| `auto_restore` | `true` | `pending` |
| `quarantine` | `true` | `pending` |
| ausente o desconocida | — | `pending` |

`ingest_event` la invoca con `event_data.get("action")` y `bool(event_data.get("action_failed", False))`, coherente con cómo el agente escribe la clave (solo ante fallo).

Que sea una función pura y no lógica inline en el constructor es lo que permite el test parametrizado de 7 filas sin base de datos, y lo que la hace citable desde el spec.

Que la derivación ocurra en el backend y no se acepte un `status` del agente es una decisión de **seguridad**, explícita en D35: `action` es un vocabulario cerrado de cuatro valores producidos por el motor de reglas; un `status` de escritura libre le daría a un agente comprometido la capacidad de insertar eventos ya marcados `approved` o `rejected`, evadiendo el ciclo de decisión humano (RN-25/RN-26) y su rastro de auditoría. El backend queda como única autoridad sobre `EventStatus`.

**Alternativas rechazadas:**
- *Que el agente emita `status` y el backend lo valide contra una allowlist de los tres terminales.* Mueve autoridad al borde no confiable y duplica el vocabulario en dos procesos que ya tienen que mantener sincronizado `action`. Una allowlist además no impide que un agente comprometido marque `auto_restored` un archivo que jamás restauró — pero eso también vale para `action`, con la diferencia de que `action` ya es parte del contrato existente y no expande la superficie.
- *Derivar desde `event_type`.* Imposible y peligroso: `_auto_restore` sobrescribe `event_type` con `"auto_restored"` (`decision.py:188`) pero `_quarantine` no hace nada simétrico (`decision.py:190-201`). La asimetría es exactamente el motivo por el que D35 manda derivar desde `action` + `action_failed`, y el motivo por el que esa sobrescritura se elimina.

### D-2 — Un `action` desconocido o ausente ingiere como `pending`, no rechaza el evento

Tolerancia hacia adelante, mismo criterio que D33 aplicó a `is_symlink`/`symlink_target`. Un agente de versión anterior —que no emite `action`— mantiene exactamente el comportamiento actual: todos sus eventos nacen `pending`. Un `action` desconocido (por ejemplo una acción futura) cae al mismo default en vez de tirar el evento. El caso de fallback del enum se resuelve en la propia `derive_event_status`, así que la ingesta no necesita el `try/except ValueError` que hoy rodea la coerción de `status`; ese bloque desaparece junto con la lectura del campo.

**Alternativa rechazada:** rechazar el evento con `RejectionReason.invalid_schema`. Convertiría una diferencia de versión del agente en pérdida de eventos de integridad, que es el activo que el sistema existe para no perder.

### D-3 — `action_failed` se persiste siempre, no solo cuando colapsa a `pending`

La columna `Event.action_failed: bool = False` se escribe con el valor derivado del payload en toda ingesta, independientemente del `status` resultante. Sin la columna, un `pending` producido por un `auto_restore` fallido sería indistinguible de un `pending` producido por `manual_review`, y la información de que el sistema intentó remediar y no pudo se perdería para siempre: no queda en ningún otro lado del lado backend (vive solo en el journal del agente, en el host).

Esa distinción no es cosmética. Un `pending + action_failed` significa "el archivo sigue adulterado en disco **y** la remediación automática ya falló"; tiene prioridad operativa sobre un `pending` que simplemente espera criterio humano.

**Alternativa rechazada:** un estado `auto_restore_failed` en el enum. Rompe RN-72 (habría que darle out-edges a `approved`/`rejected` y reescribir `VALID_TRANSITIONS`), rompe el filtro `pending` de la UI y del dashboard, y duplica la combinatoria: haría falta también `quarantine_failed`. `action_failed` es ortogonal al estado y se compone con él sin tocar la máquina de estados.

### D-4 — Fallo de acción ⇒ `pending`, nunca terminal

Cuando la acción automática falla, el archivo permanece adulterado: el incidente **no** está resuelto. Cerrarlo como terminal (`auto_restored` con una marca de fallo) dejaría un archivo comprometido sin ningún actor capaz de intervenir desde la interfaz, porque los estados terminales no tienen out-edges en `VALID_TRANSITIONS` (`spec` de `backend-event-consumer`, `service.py`) y por lo tanto no admiten approve ni reject. Volver a `pending` devuelve el incidente a la cola del operador con ambas acciones disponibles.

`alert_only` es el único caso donde `action_failed` es indiferente: no ejecuta acción física, así que no tiene nada que fallar; la fila de la tabla se implementa con un `—` real (no se consulta `action_failed`) para que un `action_failed` espurio no degrade un `alert_only` legítimo a `pending`.

### D-5 — `resolved_at = received_at`, `resolved_by = NULL` para terminales de origen agente

Los tres estados terminales se persisten con `resolved_at = received_at` (el mismo timestamp que ya recibe `ingest_event` como argumento, originado en `consumer.py:158`) y `resolved_by = NULL`. La combinación `resolved_by IS NULL AND resolved_at IS NOT NULL` es la firma de una resolución automática del agente, sin operador humano — distinguible de un approve/reject, que siempre setea `resolved_by`. La traza de qué se hizo vive en el journal del agente y en el propio `action` del evento.

Se usa `received_at` y no `detected_at` ni `datetime.now()`: `received_at` es el instante en que el backend tomó conocimiento y es el que ya se persiste en la fila, lo que mantiene `resolved_at >= detected_at` y hace la ingesta determinista y testeable (sin reloj de pared dentro de la función).

Los eventos que quedan `pending` (incluidos los de acción fallida) **no** setean `resolved_at`/`resolved_by`: siguen abiertos.

### D-6 — La cadena superseded no cambia; un evento terminal también supersede

D35 lo dice explícitamente y el diseño lo preserva sin tocar el código: la lógica de supersesión (`service.py:147-167`) corre **antes** de construir el `Event` y solo consulta el `pending` activo del path, sin mirar el estado del evento entrante. Un evento entrante terminal supersede al `pending` previo igual que uno `pending`.

La consecuencia interesante es la inversa y también se preserva: como `get_pending_event_for_path` solo encuentra `pending`, un evento terminal nunca es superseded después. Es correcto — un `auto_restored` es un hecho consumado, no un pendiente que otro evento pueda desplazar.

Vale distinguir dos cosas que se parecen y no lo son: `validate_transition(pending, alert_only)` sigue lanzando `InvalidTransitionError`, porque un evento ya persistido como `pending` no puede *transicionar* a `alert_only`. Esta change asigna `alert_only` en la **creación** de la fila, que no pasa por `validate_transition`. La máquina de estados de RN-72 queda intacta.

### D-7 — La limpieza de `event_type` es la eliminación de una línea, y hay que auditar la ruta de rehidratación

Se borra `payload["event_type"] = "auto_restored"` (`agent/decision.py:188`, última sentencia de `_auto_restore`). No se agrega nada simétrico en `_quarantine`: el resultado de la acción viaja en `action`/`action_failed` y `event_type` conserva el tipo de operación de filesystem (`file_modified | file_absent | file_deleted | file_created`, `agent/detector.py:66`).

Hay un consumidor de ese valor: `agent/detector.py:729` hace `enriched_payload.get("event_type", event_type)` para logging, y hoy observa el valor contaminado. Tras la limpieza loguea el tipo real, que es lo correcto.

La ruta de rehidratación del journal (`agent/decision.py:95-154`) arma su payload a mano (dict literal en `102-117`, con `event_type` hardcodeado a `"file_modified"`), setea `action` en `116`, `action_failed = True` en `128` y `action = "alert_only"` en `139`. Como llama a `_auto_restore` en `121`, hoy también sufre la sobrescritura. Al eliminarla, esa ruta produce un payload consistente con la misma derivación sin cambios adicionales — pero debe verificarse con un test, no por inspección: es el camino que se ejerce después de un crash del agente y no tiene cobertura de contrato.

### D-8 — Migración `007_add_event_action_failed.sql`, backfill por `DEFAULT`

Siguiendo el molde exacto de `005_add_event_symlink_metadata.sql` y `006_add_event_severity.sql`: encabezado con el número, la decisión (D35/RN-129) y el change, nota de idempotencia y la línea de aplicación manual por `psql`. El cuerpo es una sentencia:

```sql
ALTER TABLE events ADD COLUMN IF NOT EXISTS action_failed BOOLEAN NOT NULL DEFAULT FALSE;
```

El backfill de las filas preexistentes a `false` lo hace el propio `NOT NULL DEFAULT FALSE` de Postgres, sin `UPDATE` separado. Es semánticamente correcto: ninguna fila existente pudo haber sido producida por una acción fallida, porque hasta esta change el backend jamás leyó `action_failed`.

**Sin índice.** No hay endpoint ni filtro por `action_failed` en scope, y agregarlo sería un índice sobre una booleana de baja cardinalidad sin consulta que lo use. `006` sí creó `ix_events_severity` porque C38 introdujo filtrado por severidad.

### D-9 — Frontend: un mapper puro compartido, siguiendo `ackStatus.ts`

Se agrega `frontend/src/utils/actionFailed.ts` exportando `getActionFailedMeta(actionFailed: boolean): { label: string; className: string } | null`, que retorna `null` cuando es `false`. Es el mismo contrato de `getAckStatusMeta` (`frontend/src/utils/ackStatus.ts`), que es el único patrón del repo testeado de forma aislada (`ackStatus.test.ts`) y evita una cuarta copia de un mapa de clases en el frontend.

El badge se renderiza **siempre que `action_failed` sea true**, sin acoplarlo a `status === 'pending'`. En la práctica el conjunto es casi el mismo (por D-4, `auto_restore`/`quarantine` fallidos ya son `pending`, y `alert_only` no ejecuta acción física), pero desacoplarlo evita que una combinación futura quede invisible.

Paleta: `bg-red-950 text-red-300 border border-red-800`, label `'Remediación fallida'`, siguiendo el registro en prosa castellana de las labels de `ackStatus.ts` (`'Ejecución: falló'`). El rojo es deliberado — comunica la prioridad operativa que D35 le atribuye. La restricción de diseño es que no debe confundirse con el badge de estado `rejected` (`bg-red-900 text-red-300`) ni con el ack `failed` (`bg-red-950 text-red-400`); en la tabla no compiten porque el ack vive en su propia columna `Ejecución` (`EventsTable.tsx:79`), y el borde más el label distinguen del `rejected`.

Ubicación: adyacente al badge de estado, porque **califica** al estado. En `EventsTable.tsx`, en la celda de estado. En `EventDetail.tsx`, en la fila de badges del header (`líneas 89-93`), después de `<StatusBadge/>`.

### D-10 — Los tests tienen que cruzar el límite de contrato, no simularlo

Este bug sobrevivió a una suite extensa por una razón concreta y reproducible: los tests de ingesta construyen el payload a mano con exactamente las claves que `ingest_event` lee (`backend/tests/test_event_service.py:118` es un dict de 4 claves). Un test así no puede detectar una clave que el agente emite y el backend ignora, porque el test nunca la emite.

El test central de esta change es paramétrico sobre las 7 filas de la tabla y construye el payload con los objetos reales del agente: un `DetectedChange` real → `to_event_data()` real → `DecisionEngine.evaluate_and_act` real → `ingest_event` real, afirmando el `status` y el `action_failed` persistidos. `test_event_service.py:155-197` y `200-250` ya establecieron el precedente de importar `agent.detector` desde los tests del backend (insertan `repo_root` en `sys.path`); se sigue ese patrón.

El punto delicado es que `evaluate_and_act` **ejecuta la acción física**. Para las filas de éxito hay que darle un `tmp_path` con baseline real; para las filas de fallo hay que provocar un `_ActionFailed` genuino (por ejemplo un destino no escribible), no parchear el flag. Parchear `payload["action_failed"] = True` a mano reintroduciría exactamente el vicio que este test existe para eliminar.

Complementan: un test que ejerce la ruta `rehydrate` (D-7), un test de idempotencia de la migración copiando el molde de `test_event_severity.py:201-223` (ejecuta el `.sql` dos veces), un test de que `EventOut` expone `action_failed`, y un vitest del mapper según `ackStatus.test.ts`.

## Risks / Trade-offs

- **[Los dos tests cross-boundary existentes van a fallar tras el cambio]** → `test_event_service.py:155-197` y `200-250` construyen payloads con el agente real y hoy asumen `status = pending`. Con un `action` presente van a producir estados terminales. No es un falso positivo: es la señal de que la derivación funciona. Deben actualizarse deliberadamente, afirmando el estado derivado, no relajando el assert.
- **[`action_failed = true` es hoy la ruta común, no el borde]** → por el `ProtectSystem=strict` de la unit de systemd (fuera de scope), el auto_restore falla físicamente en un host real. En la demo la rama que se va a ejercitar es `pending + action_failed`, no `auto_restored`. Esto es un argumento **a favor** del orden: sin esta change ese fallo es invisible; con ella queda visible y priorizado en la UI. Pero implica que la demostración de `auto_restored` end-to-end queda bloqueada hasta que aterrice la change de systemd, y conviene decirlo en la defensa en vez de que aparezca como un vacío.
- **[La migración se aplica a mano y nadie la corre automáticamente]** → convención D3 asumida del proyecto: no hay runner, y una base existente sin `007` aplicada va a fallar al leer `Event.action_failed`. Mitigación: el encabezado del `.sql` lleva la línea `psql` exacta, la tarea de cierre lo recuerda explícitamente, y el test de idempotencia garantiza que re-aplicarla es seguro. Las bases nuevas la obtienen gratis vía `create_all()`.
- **[Derivar en el backend no impide que un agente comprometido mienta]** → un agente comprometido puede emitir `action: "auto_restore"` sin haber restaurado nada, y el evento nacerá `auto_restored`. Esta change **reduce** la superficie (cierra la inyección directa de `approved`/`rejected`, que son los estados con consecuencias de auditoría), no la elimina. La confianza en `action` ya es parte del modelo de amenaza vigente, mediada por HMAC y mTLS; no se expande.
- **[Un `pending` con `action_failed` puede leerse como "el sistema no hizo nada"]** → si el badge no comunica bien, el operador puede tratarlo como un pendiente ordinario y perder la señal de que la remediación ya se intentó y falló. Mitigación: label en prosa explícita (`'Remediación fallida'`) en vez del valor crudo del campo, y paleta roja.
- **[Se pierde la marca de la acción en `event_type`]** → cualquier consumidor que hoy dependa de leer `"auto_restored"` en `event_type` deja de verlo. El único encontrado es el log de `agent/detector.py:729`, que pasa a loguear el tipo correcto. Es la corrección buscada (RN-71), no una regresión.

## Migration Plan

1. Aplicar `007_add_event_action_failed.sql` con `psql $DATABASE_URL -f backend/db/migrations/007_add_event_action_failed.sql` sobre cada base existente (producción y test). Es idempotente; re-aplicarla no falla.
2. Desplegar el backend. A partir de ese punto los eventos entrantes con `action` derivan estado; las filas preexistentes quedan intactas con su `pending` histórico y `action_failed = false`.
3. Desplegar el agente (elimina la sobrescritura de `event_type`). El orden backend-primero es el seguro: un backend nuevo con agente viejo simplemente no recibe `action` y sigue produciendo `pending` (D-2); un agente nuevo con backend viejo es igualmente inocuo, porque el backend viejo ignora las claves.
4. Desplegar el frontend.

**Rollback**: revertir backend y frontend. La columna `action_failed` puede quedar en la base sin efecto — el código viejo no la lee y su `DEFAULT FALSE` hace que los `INSERT` del código viejo sigan siendo válidos. No hace falta un `DROP COLUMN`, y no conviene hacerlo: perdería la información de fallos ya registrados.

## Open Questions

_(ninguna — D35/RN-129 está cerrada en el appendix "Decisiones de implementación — Abril 2026" de `docs/reglas_de_negocio.md:1132-1163`, e incluye la tabla de derivación, la semántica de `action_failed`, la regla de `resolved_at`/`resolved_by`, la limpieza del léxico y las excepciones.)_
