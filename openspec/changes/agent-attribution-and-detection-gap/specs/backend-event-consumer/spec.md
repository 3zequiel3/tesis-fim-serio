## MODIFIED Requirements

### Requirement: Cadena superseded en ingesta con optimistic locking y re-consulta ante race

Cuando el consumer ingesta un evento válido **con ruta** para un path que ya tiene un evento con `status=pending`, el sistema SHALL: (1) marcar el evento pending anterior como `superseded` usando `UPDATE events SET status='superseded', version=version+1 WHERE id=? AND version=? AND status='pending'`; (2) si la UPDATE afecta 0 filas (carrera), re-consultar si todavía existe un pending activo para el mismo path (D25, RN-121): si hay pending → logear warning y abortar la creación del nuevo evento (skip legítimo); si NO hay pending → insertar el nuevo evento como pending independiente sin `parent_event_id`; (3) crear el nuevo evento con `parent_event_id` apuntando al ID del anterior. Si no existe evento `pending` para el path, el nuevo evento se crea sin `parent_event_id` (RN-21–23, RN-77).

Un evento con `path` **nulo** SHALL NOT participar de este mecanismo (D51/RN-145). Cuando el payload
no trae ruta, `ingest_event` MUST NOT invocar `get_pending_event_for_path` y MUST crear el evento con
`parent_event_id = None`. La ingesta MUST NOT degradar un `path` ausente a cadena vacía: ese `""` es
una clave de supersesión válida, de modo que **todos** los eventos sin ruta se supersederían entre sí
como si hablaran del mismo archivo, y cada uno borraría al anterior de la vista del operador —
exactamente el registro que D50/RN-144 existe para preservar.

#### Scenario: Nuevo evento en path con pending existente genera cadena
- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=pending`
- **AND** llega un nuevo evento válido para `path='/etc/hosts'`
- **THEN** `event_A.status` pasa a `superseded` y `event_A.version` incrementa en 1
- **AND** se crea `event_B` con `parent_event_id = event_A.id`

#### Scenario: Nuevo evento en path sin pending — no genera cadena
- **WHEN** no existe evento `pending` para `path='/etc/passwd'`
- **AND** llega un nuevo evento válido para `path='/etc/passwd'`
- **THEN** se crea el evento con `parent_event_id = None`

#### Scenario: Carrera en superseded — pending resuelto concurrentemente — nuevo evento insertado
- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **AND** la re-consulta de pending para el path retorna None (el pending fue resuelto concurrentemente por un approve/reject)
- **THEN** el consumer inserta el nuevo evento como pending independiente (sin `parent_event_id`)
- **AND** ejecuta `XACK` sobre la entrada

#### Scenario: Carrera en superseded — pending todavía existe — consumer aborta
- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **AND** la re-consulta de pending para el path retorna un evento pending activo
- **THEN** el consumer no crea el nuevo evento (skip legítimo)
- **AND** ejecuta `XACK` sobre la entrada
- **AND** emite un log de warning

#### Scenario: Un evento sin ruta no busca pending ni supersede
- **WHEN** llega un evento válido cuyo payload no trae `path`
- **THEN** no se ejecuta ninguna consulta de pending por ruta
- **AND** el evento se crea con `path = NULL` y `parent_event_id = None`

#### Scenario: Dos eventos sin ruta coexisten sin supersederse
- **WHEN** se ingestan dos eventos `detection_gap` consecutivos, ambos sin `path`
- **THEN** ambos existen en la tabla `events` como registros independientes
- **AND** ninguno tiene `status = superseded`

### Requirement: Compactación de cadena — retiene los más recientes

Inmediatamente después de marcar un evento como `superseded` y crear el nuevo evento, el sistema SHALL contar los eventos `superseded` para el mismo path. Si el conteo supera 10, SHALL eliminar los `superseded` más **antiguos** hasta que la cadena tenga exactamente 10, excluyendo del borrado los que tengan `id` referenciado en `audit_log.target_id` con `target_type='event'`. El borrado SHALL ejecutarse ordenando los candidatos por `created_at` **ascendente** (más antiguos primero), de modo que se descarten los eventos más viejos y se retengan los más recientes. Combinado con la FK `ON DELETE SET NULL` sobre `parent_event_id`, la operación MUST completar sin `IntegrityError` incluso en cadenas largas (C9). La eliminación SHALL ocurrir en la misma transacción de base de datos que la creación del nuevo evento (RN-98).

La compactación SHALL operar únicamente sobre eventos **con ruta**. Cuando el evento ingestado no
tiene `path`, `ingest_event` MUST NOT invocar `compact_chain` (D51/RN-145). La condición ya se
satisface por construcción —`compact_chain` sólo se invoca cuando hubo supersesión, y un evento sin
ruta nunca supersede—, pero se declara explícitamente para que un refactor futuro no la pierda: un
`compact_chain` sobre ruta nula borraría eventos de brecha de detección al alcanzar el umbral de 10.

#### Scenario: Cadena bajo 10 no desencadena compactación
- **WHEN** existen 8 eventos `superseded` para un path y se marca el 9no
- **THEN** no se elimina ningún evento

#### Scenario: Cadena llega a 11 — se compacta a 10 eliminando el más antiguo
- **WHEN** existen 10 eventos `superseded` para un path y se marca el 11mo
- **THEN** se elimina el `superseded` más antiguo (menor `created_at`) que no esté referenciado en `audit_log`
- **AND** la cadena queda con exactamente 10 eventos `superseded`

#### Scenario: Compactación de cadena larga no viola la FK
- **WHEN** se compacta una cadena donde los eventos a borrar son `parent_event_id` de otros eventos de la cadena
- **THEN** el borrado completa sin `IntegrityError`
- **AND** `ingest_event` no aborta su transacción ni pierde el nuevo evento

#### Scenario: Compactación respeta referencias en audit_log
- **WHEN** el `superseded` candidato a borrar tiene su `id` en `audit_log.target_id`
- **THEN** no se elimina ese evento
- **AND** se elimina el siguiente candidato más antiguo que no esté referenciado

#### Scenario: La ingesta de un evento sin ruta no invoca la compactación
- **WHEN** se ingesta un evento cuyo payload no trae `path`
- **THEN** `compact_chain` no se ejecuta
- **AND** ningún evento preexistente se elimina

## ADDED Requirements

### Requirement: La ingesta persiste event_type y preserva el path nulo

`ingest_event` SHALL persistir el campo `event_type` que el agente ya emite en todo payload
(`file_created`, `file_modified`, `file_deleted`, `file_absent`, `detection_gap`), en minúsculas
snake_case conforme a RN-71 (D51/RN-145). Hasta esta change el backend descartaba ese campo: no es
un dato nuevo, es dejar de perder uno existente.

El valor SHALL persistirse **sin validación contra enum**, con el mismo criterio de tolerancia hacia
adelante que `action` y `action_error` (D33, D36/RN-130): un valor desconocido emitido por un agente
más nuevo se guarda tal cual en vez de rechazar el evento. Rechazarlo convertiría «el agente va
adelantado del backend» en pérdida de eventos de integridad. Un payload sin `event_type` —agente
anterior a esta change— SHALL ingerir igual, tomando el default del modelo.

`ingest_event` SHALL leer el path como `event_data.get("path")`, **sin valor por defecto**, y
persistirlo tal cual, incluido el nulo. La ingesta MUST NOT sustituir un `path` ausente por cadena
vacía ni por ningún otro valor sintético.

#### Scenario: event_type del payload llega a la columna
- **WHEN** se ingesta un evento cuyo payload trae `event_type="file_deleted"`
- **THEN** la fila creada en `events` tiene `event_type = 'file_deleted'`

#### Scenario: Un event_type desconocido se persiste sin rechazar el evento
- **WHEN** se ingesta un evento cuyo payload trae `event_type="some_future_type"`
- **THEN** el evento se persiste con ese valor literal
- **AND** no se registra ningún rechazo en `rejected_events_audit`

#### Scenario: Un payload sin event_type ingiere con el default
- **WHEN** se ingesta un evento cuyo payload no trae la clave `event_type`
- **THEN** el evento se persiste con el default del modelo y sin error

#### Scenario: Un path ausente se persiste como NULL, no como cadena vacía
- **WHEN** se ingesta un evento cuyo payload no trae la clave `path`
- **THEN** la fila creada tiene `path IS NULL`
- **AND** no tiene `path = ''`

### Requirement: Severidad fija high para eventos sin ruta

El backend SHALL seguir siendo la única autoridad sobre `severity` y SHALL seguir calculándola al
ingerir (D34/RN-128): el valor que el agente proponga se ignora. La lógica vigente
(`determine_severity_for_path`, D-C15-01) deriva la severidad de las reglas cuyo patrón matchea el
path, con `low` como default sin matches.

Un evento **sin ruta** SHALL recibir severidad `high` de forma fija, **sin consultar el ruleset**
(D51/RN-145). Sin esta excepción caería en `low` por no matchear ninguna regla, que es lo contrario
de lo que significa una pérdida de cobertura. La excepción SHALL dispararse por **ausencia de ruta**,
no por tipo de evento, de modo que un tipo futuro sin ruta herede el tratamiento correcto sin tocar
el código.

La severidad asignada SHALL ser `high` y no `critical`: una brecha de detección es una pérdida de
garantía, no una violación de integridad confirmada, y reservar `critical` para lo confirmado
mantiene informativa a la severidad máxima.

#### Scenario: Un evento sin ruta recibe severidad high
- **WHEN** se ingesta un evento cuyo payload no trae `path`
- **THEN** la fila creada tiene `severity = 'high'`

#### Scenario: El ruleset no se consulta para un evento sin ruta
- **WHEN** se ingesta un evento sin `path` con un ruleset cargado
- **THEN** no se ejecuta `determine_severity_for_path` para ese evento

#### Scenario: Un evento con ruta conserva el cálculo por reglas
- **WHEN** se ingesta un evento con `path='/etc/shadow'` y existe una regla `critical` que lo matchea
- **THEN** la fila creada tiene `severity = 'critical'`

#### Scenario: La severidad propuesta por el agente se sigue ignorando
- **WHEN** se ingesta un evento sin `path` cuyo payload propone `severity="low"`
- **THEN** la fila creada tiene `severity = 'high'`

### Requirement: Un evento sin ruta entra como alert_only y se resuelve sin operador

El sistema SHALL tratar un evento sin ruta que llega con `action: "alert_only"` como terminal de origen agente: `resolved_at = received_at` y `resolved_by = NULL`, identificando una resolución automática sin operador humano (D35/RN-129). La acción llega ya resuelta por el agente, de modo que `derive_event_status("alert_only", False)` retorna `EventStatus.alert_only` sin lógica adicional.

El backend MUST NOT derivar un estado distinto por el hecho de que el evento no tenga ruta: la
ausencia de ruta gobierna la supersesión y la severidad, no la máquina de estados.

#### Scenario: Un detection_gap ingresa en estado alert_only
- **WHEN** se ingesta un evento con `event_type="detection_gap"`, sin `path` y con `action="alert_only"`
- **THEN** la fila creada tiene `status = 'alert_only'`
- **AND** `resolved_at = received_at` y `resolved_by IS NULL`

#### Scenario: Un evento sin ruta con acción desconocida sigue la regla general
- **WHEN** se ingesta un evento sin `path` cuyo payload no trae `action`
- **THEN** el estado derivado es `pending`, igual que para cualquier evento con acción ausente (tolerancia hacia adelante, D33)
