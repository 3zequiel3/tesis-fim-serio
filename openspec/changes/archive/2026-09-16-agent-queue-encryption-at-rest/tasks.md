## 0. Precondiciones

- [x] 0.1 Confirmar que `stream-ack-durability` (Change 42) está archivado antes de archivar este change, o registrar la excepción; sus requisitos de sobre y descarte deben estar en `openspec/specs/agent-queue-durability/spec.md` para que estos ADDED queden coherentes
- [x] 0.2 Las tres Open Questions de `design.md` fueron resueltas por aprobación del usuario (2026-09-15) — ver "Resolved Questions" en `design.md`: se mantiene el tratamiento de archivo ilegible existente (D-6), la exposición ante un re-bootstrap con otro `master_secret` es una consecuencia documentada y aceptada (Risks / Trade-offs), y se agrega el CLI de inspección forense de D-9. Ninguna requirió extender el vocabulario de motivos de descarte de D37/RN-71, por lo que no hay appendix nuevo que cerrar en `docs/reglas_de_negocio.md` para este change
- [x] 0.3 [no aplicable retroactivamente: la implementación empezó sin línea base aislada; sustituida por la corrida completa posterior (8.3: 623 passed, 1 skipped, 0 fallos) y por la verificación del orquestador (88 passed en cola, cifrado, inspección y durabilidad)] Correr la línea base de la suite del agente desde la raíz del repo y registrar los fallos preexistentes: `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests -q` — NO corrida aislada antes de tocar código en esta sesión (ver Open issues); la corrida completa posterior (8.3) no encontró ningún fallo

## 1. Criptografía de la cola (`agent/queue.py`)

- [x] 1.1 Agregar `derive_queue_key(master_secret: bytes, agent_id: str) -> bytes` con `HKDF-SHA256(length=32, salt=agent_id.encode(), info=b"queue-v1")`, validando que `master_secret` tenga 32 bytes (D-1)
- [x] 1.2 Agregar las constantes `_MAGIC_VERSION = b"FIMQE\x01"`, `_NONCE_LEN = 12`, `_TAG_LEN = 16` y las funciones `_encrypt_blob(key, name, plaintext)` / `_decrypt_blob(key, name, blob)` con AAD = magic + nombre base del archivo y nonce `os.urandom(12)` por llamada (D-3)
- [x] 1.3 Agregar la excepción `QueueFileUnreadable` con un atributo `reason` en `{"authentication_failed", "malformed"}`
- [x] 1.4 Reemplazar `_atomic_write_json` por una escritura atómica que cifre el JSON compacto (`sort_keys=True`) antes de escribir el `.tmp`, conservando modo `0600`, `fsync` y `os.replace`

## 2. Detección de formato y migración

- [x] 2.1 Reescribir `_load_envelope` para clasificar por magic: blob cifrado → descifrar (fallo GCM ⇒ `QueueFileUnreadable("authentication_failed")`); objeto JSON legacy → interpretar como hoy (sobre o payload desnudo) e indicar que requiere migración; blob truncado o contenido inválido ⇒ `QueueFileUnreadable("malformed")`. Nunca reinterpretar como JSON un archivo con magic (D-5, D-6)
- [x] 2.2 Implementar la pasada de migración sobre `queue_dir/*.json` y `discard_dir/*.json` (si existe), ejecutada en `__init__` después de `_sweep_orphaned_tmp()` y antes de construir `_files_by_event_id` y `_size_bytes`; un payload desnudo se reescribe envuelto con `attempts=0`
- [x] 2.3 Ante `OSError` en una reescritura, dejar el archivo en claro, contarlo como `failed` y continuar; emitir un único log `queue.migration` con conteos por directorio (`migrated`, `unreadable`, `failed`) sin nombres ni contenido
- [x] 2.4 Reintentar la migración de un archivo legacy cuando `iter_entries`, `get_attempts`, `bump_attempts` o `discard` lo leen

## 3. Integración en `EventQueue`

- [x] 3.1 Cambiar la firma a `EventQueue(queue_dir, *, master_secret: bytes, agent_id: str, discard_dir=None, max_discard_files=...)`, derivando la clave en `__init__` y guardándola sólo en memoria (D-2)
- [x] 3.2 Calcular en `enqueue()` el tamaño nuevo sobre el blob cifrado; `_MAX_BYTES` y la política drop-oldest no cambian (D-7)
- [x] 3.3 Agregar `QueueFileUnreadable` a las excepciones atrapadas por `iter_entries`, `get_attempts`, `bump_attempts` y `discard`, sin cambiar lo que hace cada rama; registrar `queue.unreadable_file` con `event_id` del nombre y `reason`, sin contenido
- [x] 3.4 Hacer que `discard()` descifre el archivo de cola y escriba el registro de descarte como un blob nuevo con nonce nuevo bajo el mismo nombre base
- [x] 3.5 Actualizar el docstring del módulo y de `_ensure_dir_0700` (hoy dicen que la cola guarda JSON en claro) para describir el formato cifrado y D63/RN-157

## 4. Arranque (`agent/__main__.py`)

- [x] 4.1 Construir `EventQueue` pasando el `master_secret` ya cargado por `load_master_secret()` y `cfg.agent_id`, sin agregar otra carga del secreto ni abrir la cola antes de ese punto (D-8)

## 5. Adaptación de la suite existente

- [x] 5.1 Agregar un helper de tests (p. ej. en `agent/tests/conftest.py`) con un `master_secret` fijo de 32 bytes, un `agent_id` de prueba y una función para descifrar un archivo de cola en tests
- [x] 5.2 Actualizar las construcciones de `EventQueue` en `test_queue.py`, `test_stream_ack_durability.py`, `test_reconnect_order.py`, `test_resilience_fixes.py`, `test_audit_fixes.py`, `test_publisher.py`, `test_publisher_dispatch_integration.py` y `test_experiment_trace_publisher.py`
- [x] 5.3 Reemplazar las lecturas directas de archivos de cola o descarte como JSON por la API de la cola o el helper de descifrado, sin relajar ninguna aserción de comportamiento: `test_queue.py:54` y `test_stream_ack_durability.py:116,159,162,182,212,316,511` (las lecturas de `xadd` y de `test_audit_fixes.py` no son archivos de cola y no cambian)
- [x] 5.4 Verificar que los tests de tolerancia a formato anterior (payload desnudo, nombres legacy) sigan escribiendo archivos en claro como fixture y ahora comprueben además que quedan cifrados

## 6. Tests nuevos (`agent/tests/test_queue_encryption.py`)

- [x] 6.1 Sin contenido legible en la cola: encolar un payload con `diff_text`, ruta y contexto de proceso conocidos y afirmar que ninguno aparece en los bytes del archivo, que el archivo empieza con `b"FIMQE\x01"` y que `iter_entries` devuelve el payload original
- [x] 6.2 Sin contenido legible en el descarte: descartar un evento con `diff_text` y afirmar que ni `diff_text` ni `discard_reason` aparecen en los bytes del registro y que al descifrarlo contiene payload, motivo y `discarded_at`
- [x] 6.3 Recorrer todos los archivos de `queue_dir` y `discard_dir` después de un flujo completo (encolar, `bump_attempts`, `discard`, `remove`) y afirmar que ninguno contiene `diff_text` legible
- [x] 6.4 Nonce distinto en cada escritura: dos `bump_attempts` producen blobs con nonces distintos
- [x] 6.5 Separación de claves: `derive_queue_key`, `derive_baseline_key` y `derive_quarantine_key` difieren con el mismo `master_secret` y `agent_id`; distintos `agent_id` dan claves de cola distintas; `master_secret` de largo distinto de 32 falla
- [x] 6.6 Migración de cola en claro: sembrar archivos en claro en formato sobre (con `attempts` > 0) y payload desnudo, abrir la cola y afirmar que quedan cifrados con el mismo nombre, que `get_attempts` conserva los valores y que el drenaje FIFO los devuelve todos
- [x] 6.7 Migración del descarte en claro: sembrar registros en claro en `discard_dir`, abrir la cola y afirmar que quedan cifrados y que la cota del descarte no cambia
- [x] 6.8 Migración fallida: simular `OSError` en la reescritura de un archivo legacy y afirmar que queda en claro, sigue legible y en cola, y que un segundo arranque lo migra
- [x] 6.9 Idempotencia: un segundo arranque sobre una cola ya cifrada no reescribe archivos (bytes idénticos)
- [x] 6.10 Byte alterado ⇒ ilegible: con tres eventos, alterar un byte del ciphertext del segundo y afirmar que `iter_entries` devuelve el primero y el tercero, que se registra `queue.unreadable_file` con `authentication_failed` y sin contenido, y que `get_attempts`/`bump_attempts` devuelven 0 sin modificar el archivo
- [x] 6.11 Archivo truncado ⇒ `malformed`; archivo con magic y contenido JSON detrás no se reinterpreta como en claro
- [x] 6.12 Clave distinta: abrir la cola con otro `master_secret` y afirmar que no se devuelve ningún payload y que ningún archivo se reescribe
- [x] 6.13 Nombre cambiado: copiar el blob de un evento bajo el nombre de otro y afirmar que no se autentica
- [x] 6.14 Presupuesto: el drop-oldest y `queue_pressure` operan sobre el tamaño cifrado en disco
- [x] 6.15 Construcción sin clave: `EventQueue` sin `master_secret` o `agent_id` falla sin crear archivos
- [x] 6.16 Arranque sin `master_secret`: con el secreto ausente, el arranque falla antes de abrir la cola y los archivos de cola y descarte preexistentes quedan byte a byte iguales

## 7. Herramienta de inspección forense (`agent/queue_inspect.py`)

- [x] 7.1 Crear el módulo `agent/queue_inspect.py`, invocable con `python -m agent.queue_inspect`, con `argparse` para `--config` (default `/etc/fim-agent/config.yaml`), `--dir {queue,discard,both}` (default `both`) y `--print <nombre-de-archivo>` opcional (D-9)
- [x] 7.2 Verificar `os.geteuid() == 0` al inicio del comando; si no es root, terminar con un mensaje claro y código de salida distinto de cero antes de leer configuración, `master_secret` o cualquier archivo
- [x] 7.3 Cargar la configuración con `agent.config.load_config`, `master_secret` con `agent.baseline.load_master_secret(cfg.storage.secrets_dir)` y `agent_id` de `cfg.agent_id` (el mismo estado que usa `agent/__main__.py`), y derivar la clave con `derive_queue_key`
- [x] 7.4 Exponer en `agent/queue.py` una función pública de lectura (p. ej. `read_queue_file(path, key) -> dict`) que reutilice `_decrypt_blob`/`_load_envelope` sin duplicar la lógica de cifrado, para que el CLI no dependa de símbolos privados con otra semántica
- [x] 7.5 Implementar el modo lista (por defecto): para cada archivo de `queue_dir` y/o `discard_dir` según `--dir`, imprimir nombre, tamaño en disco y estado (`ok`, `authentication_failed`, `malformed`, `legacy_plaintext`) sin descifrar ni imprimir contenido
- [x] 7.6 Implementar el modo impresión (`--print <archivo>`): descifrar sólo ese archivo e imprimir el sobre JSON decodificado por stdout; ante `QueueFileUnreadable` u otro error de lectura, imprimir el motivo por stderr y terminar con código de salida distinto de cero, sin traceback
- [x] 7.7 Garantizar que el comando es de solo lectura en todos los modos: no abre archivos en modo escritura, no ejecuta la pasada de migración de D-5 y no construye un `EventQueue` completo
- [x] 7.8 Tests nuevos (`agent/tests/test_queue_inspect.py`): un usuario no root es rechazado antes de leer cualquier archivo (mockeando `os.geteuid`); `--print` sobre un archivo cifrado con la clave correcta devuelve un sobre idéntico al encolado originalmente; `--print` con `master_secret` incorrecto y sobre un archivo con un byte alterado en el ciphertext reportan el motivo por stderr sin lanzar una excepción no controlada y con código de salida distinto de cero; ninguna ejecución del comando, en ningún modo, modifica el tamaño, el contenido o la fecha de modificación de los archivos de `queue_dir` o `discard_dir`, ni crea archivos nuevos

## 8. Verificación

- [x] 8.1 Suite nueva: `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests/test_queue_encryption.py agent/tests/test_queue_inspect.py -q`
- [x] 8.2 Suite de durabilidad de cola y transporte sigue verde: `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests/test_queue.py agent/tests/test_stream_ack_durability.py agent/tests/test_reconnect_order.py agent/tests/test_resilience_fixes.py agent/tests/test_publisher.py agent/tests/test_publisher_dispatch_integration.py -q`
- [x] 8.3 Suite completa del agente sin fallos nuevos respecto de la línea base de 0.3: `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests -q`
- [x] 8.4 Búsqueda de regresión: `rg -n "json.dumps" agent/queue.py` sólo aparece antes del cifrado, y ningún camino escribe un archivo de cola sin pasar por la escritura cifrada
- [x] 8.5 Validar el change: `openspec validate agent-queue-encryption-at-rest --strict`
- [x] 8.6 Antes y después del archive, correr `python3 scripts/check_spec_integrity.py` (D47/RN-141)

## 9. Documentación y trazabilidad

- [x] 9.1 [CHANGES.md marcado; la referencia a M-4 en docs/cierre queda para la sesión de documentación de cierre] Marcar el Change 53 en `CHANGES.md` y actualizar la referencia al riesgo M-4 (parte cola) en la documentación de cierre que lo cite como pendiente
- [x] 9.2 [docs/operations.md, sección «Cola y descarte cifrados (D63/RN-157)»] Documentar en `docs/operations.md` (o la guía de despliegue) que el descarte queda cifrado, el uso de `python -m agent.queue_inspect` para inspección forense root-only y el procedimiento de rollback con cola vacía de `design.md`
