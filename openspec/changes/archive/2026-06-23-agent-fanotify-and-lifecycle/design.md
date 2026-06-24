## Context

El agente FIM corre como servicio systemd con `CAP_SYS_ADMIN`, sin servidor HTTP (RN-108/D8): se comunica con el backend exclusivamente por Valkey Streams, salvo el bootstrap mTLS inicial (`httpx` síncrono a `/agents/bootstrap`). Esta change agrupa una mejora de capacidad (detección multi-evento, D12) y cuatro correcciones de robustez/ciclo de vida (G3, G4, F2, F3) que comparten los mismos archivos del agente y se benefician de una sola pasada de planificación.

Estado actual relevante (verificado en código):
- `detector.py::_mark_paths` marca solo `FAN_CLOSE_WRITE`; `DetectedChange.event_type` solo distingue `file_modified`/`file_absent`.
- `__main__.py::_shutdown` setea `shutdown_flag` (consumido por el heartbeat) pero NO llama `publisher.set_shutdown(True)`. El heartbeat ya lee `shutdown_flag.is_set()` directamente — ver Riesgos.
- `state.py::save_state` escribe `{ruleset_version, last_stream_command_id}`; `rules.py::RulesCache._persist` escribe `{ruleset_version, rules}`. Ambos truncan: el último en escribir gana y borra los campos del otro (F2 confirmado).
- `decision.py::_auto_restore` (L130) y `commands.py::handle_restore_file` (L291) fallan con `no_baseline_content` si `entry.content_b64 is None`, sin mirar `entry.snapshots` (F3 confirmado).
- `bootstrap.py` ya tiene la maquinaria de verificación de cert (CA firma, CN, clave pública) y `is_bootstrapped` ya lee `not_valid_after_utc`. Reutilizable para G3.
- `httpx` ya es dependencia del agente.

Decisiones canónicas que enmarcan la change: D12/RN-110 (máscaras y léxico `operation_type`), D13/RN-111 (renovación de cert), D8/RN-108 (sin HTTP server). Todas cerradas en los appendices "Decisiones de implementación" (2026-06-23). No hay suposiciones abiertas.

## Goals / Non-Goals

**Goals:**
- Detectar borrado, creación y movimiento de archivos vigilados, emitiendo `operation_type` con el léxico canónico.
- Eliminar la race que corrompe `state.json` mediante un único punto de escritura no destructivo.
- Hacer que la restauración (automática y por comando) use snapshots cuando el contenido activo es `None`.
- Propagar `shutdown=true` al heartbeat durante el drenaje.
- Renovar el certificado mTLS proactivamente, con degradación tolerante a fallos.

**Non-Goals:**
- Implementar el endpoint backend `POST /agents/renew` (change futura).
- Cambiar el modelo de transporte (sigue Valkey Streams + bootstrap HTTPS puntual).
- Modificar el esquema de baseline cifrado o la rotación de claves.
- Reescribir el modelo de snapshots de baseline (se consume el existente: lista FIFO, gzip en no-activos).

## Decisions

### D-C26-1: Máscara combinada en un solo mark + dispatch por bits del evento
Agregar `FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE` a la máscara de `_mark_paths` (y a `reload_paths`/`reload_watch_paths` para consistencia). En `_read_loop` se captura el tipo de evento (los flags de `ev`) además del path; `_process_event` despacha:
- `FAN_DELETE`/`FAN_MOVED_FROM` → `operation_type="file_deleted"`, sin hash, `mark_absent(path)`.
- `FAN_CREATE`/`FAN_MOVED_TO` → `operation_type="file_created"`, hash + `write_entry(path)`.
- `FAN_CLOSE_WRITE` → lógica actual (`file_modified`/`file_absent`).

`FanotifyEvent` gana un campo con la máscara/tipo de evento. `DetectedChange.event_type` se renombra conceptualmente a `operation_type` en el payload (el campo `event_type` actual ya transporta `file_modified`/`file_absent`; se mapea a `operation_type` en `to_event_data()` para no romper el consumer, que ya trata payloads sin el campo como `file_modified`).
*Alternativa descartada*: `FAN_REPORT_DFID_NAME`/`FAN_REPORT_FID` para resolución de path por fid — descartada por D12 (pyfanotify resuelve `ev.path` internamente).

### D-C26-2: `AgentState` como único escritor de `state.json`
`save_state` pasa a ser no destructivo: serializa los tres campos (`ruleset_version`, `last_stream_command_id`, `rules`) desde `AgentState`. `AgentState` gana un campo `rules: list` que refleja las reglas activas. `RulesCache._persist` deja de abrir `state.json`: actualiza `state.rules` + `state.ruleset_version` y llama `save_state(state)`. Esto colapsa los dos escritores en uno y elimina la race sin locking adicional (ambos corren en el mismo event loop, D8).
*Alternativa descartada*: read-modify-write en cada escritor (leer JSON, mergear, escribir). Funciona pero deja dos puntos de escritura y dos oportunidades de divergencia; el punto único es más simple y testeable.

### D-C26-3: Helper de selección de snapshot restaurable compartido
Extraer una función pura que, dada una `BaselineEntry`, devuelva `(content_bytes, expected_hash)` del mejor origen restaurable: primero `content_b64` activo; si es `None`, el snapshot más reciente con `content_b64` no nulo (descomprimiendo si `gzip=True`). Si no hay ninguno → `None`. Tanto `decision._auto_restore` como `commands.handle_restore_file` la consumen y, ante `None`, fallan con `no_restorable_content`. Se ubica en `baseline.py` (dueño del modelo de snapshots) para evitar dependencia cruzada decision↔commands.
*Alternativa descartada*: duplicar la lógica en ambos sitios — viola DRY y arriesga divergencia de comportamiento entre auto y manual restore.

### D-C26-4: `set_shutdown` en el handler + heartbeat lee el publisher
El handler `_shutdown` llama `publisher.set_shutdown(True)` antes de `_drain_then_stop`. Como el heartbeat hoy lee `shutdown_flag` (un `asyncio.Event` separado) y no el publisher, se unifica la fuente: el heartbeat lee `publisher.shutdown` (ya expuesto como property). Esto cumple el item del usuario (llamar `set_shutdown(True)` en el handler) y elimina la duplicación entre `shutdown_flag` y `publisher._shutdown`.
*Alternativa descartada*: seguir con `shutdown_flag` y solo agregar `set_shutdown` — dejaría dos señales de shutdown redundantes; consolidar en el publisher es más limpio.

### D-C26-5: Renovación de cert con `httpx.AsyncClient` mTLS, función extraída de bootstrap
Se extrae de `bootstrap.py` una función reutilizable de verificación de cert (CA firma + CN + clave pública). `_cert_renewal_loop` en `__main__.py`:
1. `asyncio.sleep` interrumpible por `stop_event` cada `cert_renewal_check_interval_h`.
2. Lee `not_valid_after_utc` del cert actual; si vence en ≤ 15 días, llama `POST /agents/renew` con `httpx.AsyncClient(cert=(cert_pem, key_pem), verify=ca_pem)` — sin `bootstrap_secret`.
3. Verifica el cert de respuesta con la función extraída; si pasa, persiste con `_atomic_write` (patrón ya usado en bootstrap, permisos `0600`).
4. Cualquier fallo → `log.warning` + continuar.

Se usa `AsyncClient` (no el `httpx.post` síncrono del bootstrap) para no bloquear el event loop (D8). El bootstrap inicial sigue síncrono porque corre antes del loop.
*Alternativa descartada*: tarea systemd/cron externa — rompería el modelo self-contained del agente y duplicaría el manejo de certs.

## Risks / Trade-offs

- **Doblez de señal de shutdown (`shutdown_flag` vs `publisher._shutdown`)** → Mitigación: consolidar en `publisher.shutdown` (D-C26-4); `shutdown_flag` se mantiene solo si algún consumidor externo lo requiere, si no se elimina. Verificar en apply que ningún otro consumidor dependa de `shutdown_flag`.
- **`AgentState` gana `rules` y `RulesCache` deja de ser dueño del archivo** → Mitigación: `RulesCache` sigue siendo la fuente de verdad en memoria de las reglas; solo delega la *escritura*. Test de regresión: rule_sync seguido de comando de stream no pierde reglas ni cursor.
- **Eventos `FAN_CREATE`/`FAN_MOVED_TO` pueden duplicar con `FAN_CLOSE_WRITE`** (crear + escribir + cerrar dispara varios) → Mitigación: la deduplicación por hash existente descarta no-cambios; `file_created` y un `file_modified` subsiguiente del mismo path encadenan vía `parent_event_id`. Aceptable: refleja la secuencia real de operaciones.
- **`ev.path is None` bajo carga** → Mitigación: descarte explícito con warning (spec), nunca toca baseline.
- **Renovación con backend sin endpoint (404)** → Mitigación: degradación tolerante (warning + retry); el cert expira solo si el backend nunca implementa `/agents/renew`, y entonces el error TLS terminal lo refleja el dashboard (RN-111).
- **Persistencia atómica del cert durante reconexión Valkey** → Mitigación: las conexiones Valkey vivas no se reinician; el cert nuevo se usa recién en la próxima reconexión (comportamiento esperado por D13).

## Migration Plan

Sin migración de datos (no hay Alembic ni cambios de esquema persistido). El nuevo campo `rules` en `state.json` se agrega de forma compatible: `load_state` resuelve `rules: []` si falta. Despliegue: reemplazar binarios del agente y reiniciar el servicio systemd; el primer `save_state` reescribe `state.json` con los tres campos. Rollback: revertir a la versión previa del agente; `state.json` con el campo extra `rules` es ignorado por la versión vieja sin fallar (campos desconocidos se descartan al cargar).

## Open Questions

- Ninguna que bloquee implementación. El contrato exacto del request/response de `POST /agents/renew` (nombres de campos JSON) se asume simétrico al de `/agents/bootstrap` (`cert_pem`, `ca_cert_pem`); se confirmará contra la spec del endpoint cuando se implemente en el backend. La degradación tolerante a fallos absorbe cualquier desajuste hasta entonces.
