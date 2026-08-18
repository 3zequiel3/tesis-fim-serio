## Context

El transporte agente↔backend está construido como un camino feliz con dos extremos que se contradicen. El agente borra un archivo de cola **solo** al recibir `event_ack` (`agent/publisher.py:319-326`, `agent/queue.py:112`) y republica cada 60 s todo lo que no tenga ack (`agent/publisher.py:366-378`). El backend rechaza sin responder (`backend/app/modules/events/consumer.py:331-353`) y evalúa una ventana de 5 minutos sobre `detected_at` (`:207`), que es el timestamp del hecho y no el del envío. Las dos mitades son razonables por separado y catastróficas juntas: un evento rechazado gira para siempre, y la cola offline de 100 MB — diseñada para sobrevivir una caída del backend — se vuelve inentregable en bloque en cuanto el corte pasa de cinco minutos.

D37 / RN-131 (appendix "Decisiones de implementación — Abril 2026" de `docs/reglas_de_negocio.md:1187-1216`) cierra el contrato: `sent_at` como base de la ventana, respuesta tipada con una matriz de tres comportamientos, backpressure que nunca destruye un evento, límite de reintentos con descarte local, y outbox para los comandos de decisión. Este design resuelve el **cómo** dentro de ese contrato, y nombra explícitamente los puntos donde el contrato dejaba libertad.

Restricciones que el diseño no puede violar:

- **Sin servidor HTTP en el agente** (RN-108, D8): todo viaja por Valkey Streams.
- **Backend single-instance** (RN-76): el rate limiter vive en memoria y no se comparte.
- **Léxico snake_case minúsculas** (RN-71) para todo motivo, tipo de mensaje y clave JSON.
- **Migraciones D3**: SQL idempotente en `backend/db/migrations/`, sin Alembic, aplicación manual. La más alta existente es la `009`.
- **Tolerancia hacia adelante en ambas direcciones** es la convención asentada del proyecto (D33, D35, D36): campo desconocido se ignora, valor desconocido se guarda, ausencia se trata como el comportamiento anterior.

## Goals / Non-Goals

**Goals**

- Que la cola offline drene después de un corte de cualquier duración, sin debilitar la protección contra replay que RN-90 buscaba.
- Que todo evento reciba exactamente una de tres respuestas — ack, nack terminal, nack con backpressure — o ninguna cuando responder sería inseguro, y que en los cuatro casos el evento tenga un destino final acotado.
- Que un evento excedido por rate limit **sobreviva**: se retiene, no se descarta.
- Que ningún evento pueda reintentarse indefinidamente, ni siquiera cuando el backend calla.
- Que deje de existir el estado "evento terminal, comando no emitido".

**Non-Goals**

- **No** se persiste `sent_at` en la tabla `events`. Es metadata de transporte, no del hecho; para una investigación forense de un rechazo por skew, el `payload_dump` de `rejected_events_audit` ya trae el JSON crudo completo.
- **No** se instala retención para `rejected_events_audit`. Esta change corta el crecimiento en el origen (el livelock); la política de retención es trabajo aparte.
- **No** se persiste el rate limit en Valkey ni se comparte entre instancias. RN-76 fija backend single-instance.
- **No** se emite alerta ante rate limit. RN-88 la prometía y nunca existió; D37 la reemplaza por backpressure, que es una respuesta y no una notificación.
- **No** se toca el contrato de `command_ack` (D30/RN-124) ni el `ack_status` de `PublishedCommand`. Son ortogonales al `status` de outbox y no se fusionan.

## Decisions

### D-1 — `sent_at` va dentro del payload firmado, y por eso la firma se calcula al publicar, no al encolar

`sent_at` tiene que estar cubierto por el HMAC. Si quedara afuera del canonical JSON, un tercero que capture un mensaje podría re-sellarlo con la hora actual y reproducirlo — exactamente el ataque que RN-90 existe para frenar, y el único que realmente cubría. Está adentro.

La consecuencia es estructural: **la firma deja de ser una propiedad del evento almacenado y pasa a ser una propiedad del envío**. Hoy `_build_payload` (`agent/publisher.py:143-152`) firma y encola el payload firmado, y `_drain_queue` (`:160-174`) reenvía la firma guardada. Con `sent_at` re-sellado en cada republicación, esa firma queda inválida en el segundo envío.

El archivo de cola pasa a guardar el payload **sin** `signature` y **sin** `sent_at`. El publicador, inmediatamente antes de cada `XADD`, estampa `sent_at = now()` y firma. Un solo punto de firma para el primer envío, el reintento y el drenaje post-reinicio.

Beneficio lateral: hoy un cambio de `shared_secret` invalida toda la cola en disco (los payloads quedan firmados con el secreto viejo). Con la firma al publicar, la cola sobrevive a una rotación de secreto.

**Alternativa descartada**: dejar `sent_at` fuera de la firma y usar un campo separado sin cubrir. Más simple, y anula el propósito de la regla.

### D-2 — La ventana se evalúa sobre `sent_at` con fallback tolerante a su ausencia; `detected_at` conserva su validación de parseabilidad pero pierde la ventana

El orden de validación (`consumer.py:171-236`) no cambia de forma; cambia el contenido del paso 4:

1. `detected_at` MUST seguir siendo parseable y normalizable a UTC-aware. Si no lo es → `clock_skew` (`clock_skew.unparseable`). Se conserva: un `detected_at` ilegible es un payload roto, y además se persiste en la columna del evento.
2. `detected_at` **deja de tener ventana**. Un evento con `detected_at` de hace seis horas es exactamente lo que produce una cola que sobrevivió un corte de seis horas.
3. Si el payload trae `sent_at`: MUST ser parseable (si no → `clock_skew`, `clock_skew.unparseable_sent_at`) y `abs(received_at - sent_at) <= 300 s` (si no → `clock_skew`, `clock_skew.out_of_range`).
4. Si el payload **no** trae `sent_at`: la ventana se evalúa sobre `detected_at`, exactamente como hoy.

El punto 4 es el que preserva la compatibilidad con un agente que todavía no fue actualizado: su comportamiento es idéntico al actual, ni mejor ni peor. Ausencia = comportamiento anterior, que es la convención de D33/D35/D36.

La ventana sigue siendo **bidireccional** (`abs`): un `sent_at` en el futuro es tan sospechoso como uno viejo.

### D-3 — `event_nack`: un tipo de mensaje nuevo en el stream `commands`, firmado, con el motivo en el léxico ya existente

Se reutiliza el stream `commands` y la forma exacta de `_publish_event_ack` (`consumer.py:358-368`). Payload:

```json
{
  "type": "event_nack",
  "event_id": "<uuid>",
  "target_agent_id": "<agent_id>",
  "reason": "invalid_schema | clock_skew | rate_limited",
  "retry_after": 37.4,
  "schema_version": 1,
  "timestamp": "<iso8601 utc>",
  "signature": "<hmac hex>"
}
```

`retry_after` (segundos, float) **solo** aparece con `reason = rate_limited`; en los demás se omite, y su ausencia es lo que hace terminal al nack. El `reason` usa los literales del enum `RejectionReason` que ya existe (`events/models.py:62-68`) — no se inventa un vocabulario paralelo.

**No se crea un stream nuevo.** El agente ya escucha `commands` con verificación HMAC y filtro `target_agent_id` centralizados en `_verify_and_parse` (`agent/publisher.py:242-258`) y `_handle_command_async` (`:308-318`). Un stream nuevo duplicaría cursor persistido, listener y verificación sin ganar nada.

**La matriz cubre también los dos desenlaces que hoy son mudos y no son rechazos.** D37 pide respuesta tipada a *todo* evento, y en `_handle_message` hay dos caminos terminales que hacen `XACK` sin responder y que no aparecen en la tabla de motivos porque ocurren después de la validación:

- `InvalidTransitionError` (`consumer.py:243-260`): dato inválido, no reintentable, ya auditado como `invalid_schema`. Recibe **nack terminal con `reason = invalid_schema`**. Es el mismo desenlace que un rechazo por schema, y sin respuesta el agente lo republicaría para siempre.
- Skip por carrera de supersesión (`consumer.py:274-277`): el evento no se persiste porque el `pending` activo del path ya lo representa. Recibe **`event_ack`**: para el agente el evento está resuelto, y es exactamente la misma semántica que el dedup.

El `SQLAlchemyError` transitorio (`:261-265`) sigue sin respuesta y sin `XACK`, por construcción: no es un desenlace, es un reintento.

### D-4 — El nack de `invalid_schema` se emite antes de verificar la firma, y por eso el agente solo actúa sobre `event_id` que están en su propia cola

Hay una asimetría inevitable en el orden de validación. `clock_skew` se evalúa **después** del HMAC: ese nack está autenticado de punta a punta. `invalid_schema` en el paso 1 se evalúa **antes** de conocer el secreto, y el nack requiere el secreto para firmarse.

Resolución: cuando el motivo es `invalid_schema`, el consumer intenta resolver el `shared_secret` del `agent_id` declarado y firma el nack **si el agente existe**; si no existe, el caso colapsa en `unknown_agent` y no se responde nada.

Esto abre una superficie acotada: un tercero sin el secreto puede publicar un payload con un `agent_id` válido y un `schema_version` roto, y provocar que el backend emita un `event_nack` **firmado correctamente** hacia el agente legítimo, con un `event_id` elegido por el atacante. La contención es normativa y va en el agente:

> El agente MUST ignorar todo `event_ack` y `event_nack` cuyo `event_id` no corresponda a un evento presente en su cola local.

Con esa regla, el peor caso es un log. La regla es barata y vale para ambos tipos de respuesta; hoy `event_ack` no la tiene y `_queue.remove()` sobre un id inexistente ya es un no-op, así que se explicita más que se agrega.

El paso 5 (`event_id` vacío) también produce `invalid_schema`, pero corre **después** del HMAC: sin `event_id` no hay a qué dirigir el nack, así que ese caso no produce respuesta y caduca por el límite de reintentos. Se documenta como el único `invalid_schema` mudo.

### D-5 — `retry_after` se deriva del rate limiter, no es una constante

`_RateLimiter` (`consumer.py:69-88`) mantiene un `deque[float]` de timestamps por `agent_id` con ventana de 60 s. El tiempo hasta que se libere un cupo es `window_s - (now - timestamps[0])`, acotado inferiormente a un mínimo pequeño para que el agente no entre en busy-loop ante un valor cero o negativo por carrera.

El rate limiter expone un método explícito para eso; el consumer no manosea el `deque` desde afuera. Un `retry_after` fijo de 60 s sería aceptable pero castiga de más a un agente que estaba al borde y ya casi tiene cupo.

El agente **no confía ciegamente** en el valor: lo acota a un techo (60 s por defecto) para que un backend con un bug o comprometido no pueda silenciar a un agente durante horas con un `retry_after` enorme. Es un mensaje firmado, pero la firma prueba origen, no sensatez.

### D-6 — Backpressure global por agente, no por evento, y `publish()` sigue encolando siempre

El backpressure es un estado del publicador: `_paused_until` (reloj monotónico). Ante un `event_nack` con `reason = rate_limited`, el publicador fija `_paused_until = now + min(retry_after, techo)`. Mientras esté vigente:

- `publish()` **sigue encolando en disco** — este es el punto que no se puede romper. La detección no se suspende; lo que se suspende es el envío. El evento entra a la cola y ahí espera.
- `_xadd` no se ejecuta: ni el envío inicial, ni el reintento de `_retry_loop`, ni el drenaje de `_drain_queue`.
- El evento que recibió el nack **no consume un intento**. Un nack de rate limit no es un fallo del evento; es una instrucción de esperar. Contarlo acercaría al techo de descarte a los eventos que el sistema explícitamente decidió conservar.

Es por agente y no por evento porque el rate limit del backend es por `agent_id`: si un evento no tiene presupuesto, ninguno lo tiene. Reintentar los otros sería generar rechazos garantizados.

El límite de recursos sigue siendo el drop-oldest de 100 MB (RN-40/RN-84), sin cambios. Una tormenta sostenida más allá de eso pierde los eventos más viejos, que es el comportamiento ya especificado y aceptado.

### D-7 — El contador de intentos vive en el archivo de cola, en un sobre, con lectura tolerante del formato anterior

`Publisher._pending` es un `dict` en memoria. Se pierde en cada reinicio del agente, y al arrancar `_drain_queue` republica toda la cola desde cero. Un contador en RAM no acota nada: un evento que el backend nunca contesta sobrevive indefinidamente a base de reinicios. El contador tiene que ser durable.

El archivo de cola pasa de guardar el payload desnudo a guardar un sobre:

```json
{
  "payload": { "event_id": "...", "detected_at": "...", "schema_version": 1, "...": "..." },
  "attempts": 3,
  "first_attempt_at": "<iso8601 utc>"
}
```

`enqueue` escribe el sobre; la lectura **detecta el formato**: si el dict cargado no tiene la clave `payload`, es un archivo del formato anterior y se envuelve con `attempts = 0`. Sin migración, sin script, sin perder una cola existente — mismo criterio con el que `agent-queue-durability` ya tolera nombres de archivo legacy.

El nombre del archivo (`{detected_at_ms:016d}_{event_id}.json`) **no cambia**: el orden FIFO, el `remove(event_id)` y el cálculo de `queue_pressure` siguen funcionando igual.

Se reescribe el sobre (atómico, `tmp` + `os.replace`, como hoy) al incrementar `attempts`. El costo es una reescritura por intento por evento, con un intento cada 60 s: despreciable frente a los 100 MB de presupuesto.

**Alternativa descartada**: archivo sidecar `{ms}_{event_id}.meta.json`. Duplica los archivos, agrega un modo de huérfano nuevo (meta sin payload y viceversa) y obliga a tocar `_json_files`, `_total_bytes` y `_sweep_orphaned_tmp`.

### D-8 — El descarte es un directorio hermano de la cola, con motivo, y un contador acumulativo en el heartbeat

Superado el techo de intentos, el evento **sale de la cola** y entra a `storage.discard_dir` (default `/var/lib/fim-agent/discarded`), con el mismo esquema de nombre y un sobre que agrega `discard_reason` y `discarded_at`. Motivos, en léxico cerrado (RN-71):

| Motivo | Cuándo |
|---|---|
| `max_attempts_exceeded` | se agotaron los intentos sin recibir ninguna respuesta |
| `invalid_schema` | `event_nack` terminal con ese motivo |
| `clock_skew` | `event_nack` terminal con ese motivo |

Los dos últimos son el "se registra localmente" que pide D37 para el nack terminal: el evento se borra de la cola **y queda archivado en disco con la razón**, en lugar de evaporarse.

El directorio de descarte **no** entra en el presupuesto de 100 MB de la cola ni en `queue_pressure`: son cosas distintas y mezclarlas haría que un descarte disparara drop-oldest de eventos vivos. Su cota es un `max_files` con drop-oldest propio, para que no crezca sin límite en un host con problemas persistentes.

El heartbeat gana `discarded_events`: contador **acumulativo desde el arranque del proceso**, igual que `n_drops` del detector (`agent/heartbeat.py`, `agent/detector.py`). El backend lo persiste en `Agent.discarded_events` (migración `010`, columna nullable con default) y la tarjeta del agente lo muestra junto a la presión de cola.

Que un evento de integridad se descarte es un hecho grave, y hoy sería invisible: el agente lo borraría en silencio y nadie del lado del operador se enteraría. Un contador que nadie puede ver no es observabilidad.

### D-9 — No se bumpea `SCHEMA_VERSION`, y hacerlo en el futuro pasa a exigir orden de despliegue backend-primero

`check_schema_version` acepta `v <= SCHEMA_VERSION` (`backend/app/core/streams.py:47-52`). Un agente en `schema_version=2` contra un backend en `1` cae en `invalid_schema` — que a partir de esta change es un **nack terminal**, es decir, el agente borra el evento. Bumpear la versión junto con este cambio convertiría una ventana de despliegue en pérdida de datos, precisamente lo que la change existe para eliminar.

No hace falta bumpear: `sent_at` es aditivo y opcional (D-2 define el fallback), y `event_nack` es un `type` nuevo que el agente viejo descarta en silencio — `_handle_command_async` (`agent/publisher.py:318-364`) es una cadena de `if/elif` sin rama `else`, así que un tipo desconocido es un no-op. RN-91 ya manda ignorar campos desconocidos.

Matriz de la ventana de despliegue rodante:

| Combinación | Comportamiento |
|---|---|
| backend nuevo + agente nuevo | contrato completo de D37 |
| backend nuevo + agente viejo | sin `sent_at` → ventana sobre `detected_at` (comportamiento actual). El agente ignora los `event_nack` y sigue reintentando indefinidamente ante un rechazo terminal: **igual que hoy, ninguna regresión** |
| backend viejo + agente nuevo | `sent_at` se ignora como campo desconocido; el agente no recibe ningún nack, así que los rechazos caducan por techo de intentos y terminan en el directorio de descarte con `max_attempts_exceeded`. Peor que el estado final, mejor que el livelock actual, y **acotado** |
| ambos viejos | estado actual |

**Consecuencia que se documenta explícitamente**: como `invalid_schema` pasa a ser terminal, un bump futuro de `SCHEMA_VERSION` **exige desplegar el backend antes que los agentes**, sin excepción. Antes de esta change ese orden era una buena práctica; ahora es un requisito, y su violación cuesta eventos. Se registra en `docs/arquitectura_stack.md` junto al contrato de mensajes. Ver "Open Questions" — hay una alternativa que lo evitaría y que D37 no contempla.

### D-10 — Los comandos usan el outbox que ya existe: fila `pending` en la transacción del evento, despachador genérico

No se inventa mecanismo. `PublishedCommand` ya tiene la columna `status` (`"pending" | "published"`) y `publish_pending_commands` (`rules/service.py:188-229`) ya es **genérica**: barre todas las filas `pending` en orden de `id`, hace `XADD` del payload ya firmado y persistido, marca `published` con commit por fila, y ante `ValkeyError` corta el barrido sin perder nada. `outbox_publisher_task` ya la corre periódicamente desde el lifespan (`main.py:75`). Lo único que falta es que las filas de los comandos de decisión nazcan `pending` en vez de `published`.

El cambio en `actions/streams.py` y `agents/streams.py` es de forma, no de mecanismo:

- Firmar el payload y serializarlo, **igual que hoy**.
- Insertar `PublishedCommand` con `status="pending"`, `published_at=None`, `payload=data` — conservando `command_id`, `event_id` y `ack_status="pending"` (D30/RN-124 intacto).
- **No** hacer `XADD` ni `session.commit()` propio.

Y en `actions/service.py` / `agents/service.py` la llamada al publicador se mueve de después del `db.commit()` a **antes**, dentro de la misma transacción que la mutación. Eso invierte el orden que `backend-approve-reject` fijaba como normativo (FIX-02: "publicar solo post-commit"), y la inversión es correcta: FIX-02 protegía contra que el agente recibiera un comando de una transacción que después se revirtiera. Con el outbox esa protección la da la **atomicidad**, y mejor: la fila del comando vive o muere con el evento. Si la transacción se revierte, la fila del comando se revierte con ella y no hay nada que publicar. Si comitea, el comando está garantizado en el outbox y el despachador lo entrega.

Se conserva un `publish_pending_commands` inmediato best-effort post-commit para no agregar la latencia del poller al camino feliz — es el mismo patrón que `publish_rule_sync` ya usa.

Efecto sobre `_get_agent_secret`: hoy su `ValueError` se traga con `log.error` + `return` (`actions/streams.py:109-110`, `:164-165`, `:208-209`) mientras el endpoint responde `200`. Dentro de la transacción, esa excepción **debe propagarse**: revierte la mutación del evento y el endpoint responde un error. Un agente sin `shared_secret` es un estado imposible de operar, y fallar ruidosamente es estrictamente mejor que dejar un evento terminal con un comando fantasma.

### D-11 — Qué se puede probar sin infraestructura, y dónde está el límite

La mayor parte del contrato es lógica pura y se prueba con dobles:

- Ventana de skew sobre `sent_at`, fallback por ausencia, y las dos sub-clases de `clock_skew`: entradas al consumer con un cliente Valkey falso que colecciona los `XADD`.
- Matriz de respuestas completa: seis motivos, tres comportamientos, verificando **también los casos mudos** — que ante `invalid_signature` y `unknown_agent` el stream `commands` quede sin escribir es una aserción tan importante como las positivas.
- `retry_after` derivado del rate limiter: manipulando el reloj del limiter.
- Backpressure, techo de intentos y descarte: el publicador con un cliente falso y un reloj inyectado.
- Sobre de cola y tolerancia al formato anterior: filesystem real en `tmp_path`, sin privilegios.
- Firma al publicar: verificar que dos publicaciones del mismo `event_id` producen `sent_at` distintos y **ambas firmas válidas**.
- Outbox: que la fila nace `pending` en la misma transacción, que un `ValkeyError` deja el evento terminal **y** el comando pendiente, y que el despachador lo entrega después.

Lo que **no** se puede probar sin un entorno completo: el drenaje real de una cola de 100 MB después de un corte largo contra Postgres y Valkey de verdad, y el comportamiento del backpressure bajo una tormenta sostenida. Van como checklist de verificación manual en `tasks.md`, nombradas, en lugar de taparse con un mock que siempre pasa.

## Risks / Trade-offs

- **`invalid_schema` terminal endurece el despliegue.** Mitigación: D-9 lo documenta como requisito de orden (backend primero) en `arquitectura_stack.md`, y esta change no bumpea la versión. Riesgo residual: un despliegue futuro que ignore la nota. Ver Open Questions.
- **El nack de `invalid_schema` pre-HMAC es inducible por un tercero.** Mitigación: D-4 — el agente ignora respuestas para `event_id` que no están en su cola. Costo del ataque para el atacante: un log en el agente.
- **La firma al publicar cambia la semántica del archivo de cola.** Un archivo de cola ya no es un mensaje listo para enviar. Mitigación: la firma se concentra en un único punto del publicador; nada más lee el archivo para enviarlo.
- **El backpressure global frena eventos que sí tendrían cupo.** Es intencional: el presupuesto es por `agent_id`, así que "tendrían cupo" es falso por construcción. El costo real es latencia de detección durante una tormenta, y la alternativa (seguir enviando y coleccionar rechazos) es peor.
- **El techo de intentos puede descartar un evento legítimo** si el backend estuvo mudo lo suficiente. Mitigación: el techo se cuenta en intentos, cada intento está a 60 s, y el default se elige para cubrir varias horas de silencio. Y `unknown_agent` — el caso mudo más probable — significa que el agente no está registrado: sus eventos no tienen destino de todos modos.
- **Los eventos descartados quedan en disco sin que nadie los recolecte.** Mitigación: cota por cantidad con drop-oldest propio. Sigue siendo un directorio que crece en un host con problemas persistentes; es deliberado, porque el contenido es evidencia.
- **Extender el outbox a `update_config` y `rescan_baseline` va más allá de la enumeración literal de D37.** Marcado en el proposal y acá; es reversible sin tocar el mecanismo.
- **Se invierte la normativa "publicar post-commit" de `backend-approve-reject`.** El delta spec la reemplaza de forma explícita en lugar de dejar dos reglas contradictorias en el spec principal.

## Migration Plan

1. **Backend primero.** Acepta `sent_at` cuando viene, mantiene el fallback cuando no, y empieza a emitir `event_nack`. Un agente viejo ignora el tipo nuevo: sin regresión.
2. **Migración `010`** (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, nullable con default): aditiva, sin lock relevante, sin downtime.
3. **Agentes después**, uno a uno. Al arrancar, un agente actualizado lee su cola existente en formato anterior mediante la tolerancia de D-7, la envuelve con `attempts = 0`, y drena con `sent_at` re-sellado. **La cola atascada de una instalación existente drena sola en el primer arranque con la versión nueva** — que es el resultado que justifica la change.
4. **Rollback**: revertir el agente solo. La cola vuelve al formato anterior con la misma tolerancia invertida (un agente viejo leyendo un sobre falla al leer el archivo — ver Open Questions). Revertir el backend deja al agente nuevo sin nacks, con caducidad por techo de intentos: degradado, acotado.

## Open Questions

1. **Valores por defecto de los tres parámetros nuevos.** El diseño propone: techo de reintentos `20` (~20 min de silencio a 60 s por intento), techo de `retry_after` aceptado `60 s`, cota del directorio de descarte `1000` archivos. D37 no fija ninguno. Si la defensa de la tesis necesita números justificados con más detalle, corresponde cerrarlos en el appendix antes de `/opsx:apply`.
2. **Rollback del formato de cola.** La tolerancia de D-7 es unidireccional: el agente nuevo lee lo viejo, el agente viejo **no** lee el sobre (`payload["event_id"]` levantaría `KeyError` en `enqueue`, y `iter_fifo` devolvería sobres que `_xadd` publicaría malformados). Un rollback del agente con cola no vacía requiere vaciar el directorio de cola a mano. ¿Se acepta como procedimiento documentado, o se pide un formato que el agente viejo también tolere?
3. **`invalid_schema` por versión demasiado nueva vs. por payload roto.** Son condiciones distintas: la primera es transitoria (el backend se va a actualizar) y la segunda es permanente. Tratarlas igual — como manda la matriz de D37 — es lo que obliga al orden de despliegue de D-9. Distinguirlas (nack terminal solo para el payload roto, sin respuesta para la versión adelantada) eliminaría el requisito, pero **es una decisión nueva y no está cerrada en el appendix**. Se implementa la matriz tal como D37 la fija; se deja anotado.
4. **Alcance del outbox**: ¿los cinco comandos, o los tres que D37 enumera? Ver la desviación explícita del proposal.
