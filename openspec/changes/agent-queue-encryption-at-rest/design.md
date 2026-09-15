## Context

`agent/queue.py` implementa la cola offline durable (RN-38 a RN-41, RN-84) y, desde Change 42, el directorio de descarte (D37/RN-131). Estado actual verificado en el código:

- `_atomic_write_json()` serializa el sobre con `json.dumps(..., sort_keys=True)` y lo escribe por `.tmp` + `fsync` + `os.replace`, con modo `0600`.
- `_load_envelope()` hace `json.loads(path.read_bytes())` y envuelve un payload desnudo (formato anterior a Change 42) con `attempts=0`.
- Los lectores (`iter_entries`, `get_attempts`, `bump_attempts`, `discard`) atrapan `(json.JSONDecodeError, OSError)`: un archivo ilegible se saltea en la iteración, cuenta como cero intentos y no se reescribe. Nunca entra en `_pending` del publisher, así que no se publica ni se descarta; sólo sale por drop-oldest.
- `enqueue()` calcula el tamaño nuevo con `len(json)` y el índice de tamaño con `st_size`. `_MAX_BYTES` = 100 MB.
- El directorio de descarte sólo se escribe (`discard`) y se poda por cantidad (`_apply_discard_drop_oldest`); ningún componente del agente lee su contenido.

Patrón de cifrado ya vigente en el agente:

- `agent/baseline.py:134-141` `derive_baseline_key()`: `HKDF(SHA256, length=32, salt=agent_id, info=b"baseline-v1")`; blob `[0x01][nonce 12][ciphertext+tag]`, sin AAD.
- `agent/quarantine.py:96-105` `derive_quarantine_key()`: igual con `info=b"quarantine-v1"`, valida que `master_secret` tenga 32 bytes; blob con magic `b"FIMQ\x01"`, que también usa como AAD.

Disponibilidad del `master_secret`, verificada en `agent/__main__.py`:

1. Si `bootstrap.is_bootstrapped(certs_dir)` es falso, se ejecuta `bootstrap.run()`, que escribe `secrets/master_secret` (modo `0400`) sólo después de verificar el certificado.
2. `load_master_secret()` (línea 224) lo lee y falla con `FileNotFoundError` o `ValueError` si falta o no mide 32 bytes. El error no se atrapa y el proceso termina.
3. `EventQueue(...)` se construye recién en la línea 293, después de la baseline y la cuarentena. Es el único punto de construcción fuera de los tests; ningún script del repositorio fuera de `docs/cierre/evidencia/` instancia la cola.

Conclusión: hoy ninguna escritura de cola ocurre antes del bootstrap ni sin `master_secret`. Este change convierte esa propiedad circunstancial en un requisito.

## Goals / Non-Goals

**Goals:**

- Ningún archivo de `queue/` ni del descarte contiene `diff_text`, rutas ni contexto de proceso legibles sin el `master_secret` del agente.
- Una cola o un descarte en claro preexistentes quedan cifrados después de un arranque, sin paso manual ni pérdida de eventos.
- Un archivo alterado no se publica ni detiene el agente.
- La suite de durabilidad de la cola y del transporte (Change 42) sigue verde sin relajar ninguna aserción de comportamiento.

**Non-Goals:**

- Rotación de la clave de cola o del `master_secret` (excluida por D63).
- Cifrado del journal, del `state.json` o de los logs.
- Herramienta de inspección de registros del descarte para el operador (ver Open Questions).
- Cambiar el destino de un archivo corrupto: mover a descarte, borrar o alertar (ver Open Questions).
- Cambiar el formato del nombre de archivo, el presupuesto de 100 MB, la cota del descarte o el vocabulario de motivos de descarte.

## Decisions

### D-1. Clave: `HKDF-SHA256(master_secret, salt=agent_id, info=b"queue-v1")`

Función pública `derive_queue_key(master_secret: bytes, agent_id: str) -> bytes` en `agent/queue.py`, idéntica en forma a `derive_quarantine_key()`: valida 32 bytes de entrada, `length=32`, `salt=agent_id.encode()`. La clave derivada vive sólo en el atributo de la instancia; nunca se escribe ni se loguea.

- **Por qué `salt=agent_id`**: D63 fija `info`; la sal replica el patrón de las dos derivaciones existentes, de modo que dos agentes con el mismo `master_secret` no comparten clave de cola.
- **Alternativa descartada**: reutilizar la clave de baseline o de cuarentena. Rompe la separación por dominio que D63 exige y hace que un blob de un almacén pueda probarse en otro.
- **Alternativa descartada**: helper criptográfico común para los tres almacenes. Refactoriza baseline y cuarentena, que no están en alcance; los formatos de blob difieren y la duplicación es de ocho líneas.

### D-2. `EventQueue` recibe `master_secret` y `agent_id` como argumentos obligatorios

Nueva firma: `EventQueue(queue_dir, *, master_secret: bytes, agent_id: str, discard_dir=None, max_discard_files=...)`. La cola deriva la clave en `__init__`, igual que `QuarantineStore`.

- **Por qué obligatorios y sin modo en claro**: un parámetro opcional con fallback a texto plano reabriría M-4 ante cualquier error de cableado. Un `EventQueue` sin clave no puede existir.
- **Alternativa descartada**: inyectar la clave ya derivada. Desacopla más, pero deja la etiqueta `queue-v1` fuera del módulo dueño del formato y diverge del patrón de `QuarantineStore`.
- **Costo**: todos los tests que construyen `EventQueue` cambian. Se agrega un helper de tests con un `master_secret` fijo de 32 bytes, de modo que el cambio en cada llamada es mecánico.

### D-3. Formato del blob y datos asociados

```
[magic+versión 6 bytes = b"FIMQE\x01"][nonce 12 bytes][ciphertext + tag GCM 16 bytes]
AAD = b"FIMQE\x01" + nombre_de_archivo.encode("utf-8")
```

- El plaintext es exactamente el JSON que hoy se escribe (`sort_keys=True`, separadores compactos), así que la semántica del sobre de Change 42 no cambia.
- `nombre_de_archivo` es el nombre base (`{detected_at_ms:016d}_{event_id}.json`, o el nombre legacy sin padding), no la ruta absoluta. Así la AAD es estable ante un cambio de `queue_dir` en la configuración y liga el contenido a su `event_id` y a su posición FIFO: un archivo renombrado o intercambiado con otro falla la autenticación.
- `discard()` descifra el archivo de cola y escribe en el descarte un blob nuevo, con nonce nuevo, bajo el mismo nombre base. No hay copia de ciphertext entre directorios.
- **Magic distinto de la cuarentena** (`FIMQ\x01`): evita que un archivo de un almacén se confunda con el de otro al diagnosticar, y el primer byte (`F`) no puede ser el inicio de un JSON (`{`), lo que vuelve la detección de formato inequívoca.
- **Nonce**: `os.urandom(12)` en cada escritura, incluidas la reescritura de `bump_attempts`, la migración y el descarte. Nunca se reutiliza un nonce con la misma clave.
- **Alternativa descartada**: AAD con la ruta absoluta. Un cambio de `queue_dir` volvería ilegible toda la cola.
- **Alternativa descartada**: sin AAD, como la baseline. Permite intercambiar el contenido de dos eventos sin que GCM lo detecte.

### D-4. Los nombres de archivo no cambian, incluida la extensión `.json`

- El orden FIFO, el índice `_files_by_event_id`, la tolerancia de nombres legacy, `_sweep_orphaned_tmp`, la AAD de D-3 y la migración en el lugar dependen del nombre. Los scripts de evidencia archivados cuentan `queue_dir.glob("*.json")`.
- **Trade-off aceptado**: la extensión deja de describir el contenido. Cambiarla (`.enc`) obligaría a indexar y ordenar dos extensiones durante la migración y a renombrar, lo que invalida la AAD ligada al nombre.

### D-5. Detección de formato y migración en el lugar

`_load_envelope(path)` pasa a devolver el sobre y a clasificar el archivo:

| Primeros bytes | Tratamiento |
|---|---|
| `b"FIMQE\x01"` | descifrar con AAD; si GCM falla → `QueueFileUnreadable` |
| JSON válido (objeto) | archivo legacy en claro: se interpreta como hoy (sobre o payload desnudo) y se marca para reescritura |
| otra cosa, truncado o JSON inválido | `QueueFileUnreadable` |

Migración:

1. En `EventQueue.__init__`, después de `_sweep_orphaned_tmp()` y **antes** de construir los índices de nombre y tamaño, una pasada recorre `queue_dir/*.json` y `discard_dir/*.json` (este último sólo si existe). Cada archivo legacy en claro se reescribe cifrado con `_atomic_write` (tmp + fsync + `os.replace`) bajo el mismo nombre. Un payload desnudo se reescribe ya envuelto con `attempts=0` y `first_attempt_at=None`, que es exactamente como se lee hoy.
2. Los índices se construyen después de la pasada, de modo que `_size_bytes` refleja el tamaño cifrado.
3. La pasada emite un único log agregado (`queue.migration`: `migrated`, `unreadable`, `failed`, por directorio) sin nombres de archivo ni contenido.
4. Si una reescritura falla con `OSError`, el archivo queda en claro y legible; cualquier lectura posterior lo vuelve a intentar migrar, y la próxima pasada de arranque también. Nada se pierde.

- **Por qué en el arranque y no sólo al leer**: ningún componente lee el descarte, así que una migración puramente perezosa lo dejaría en claro indefinidamente, y el criterio de done exige que ningún archivo del descarte contenga `diff_text` legible. En la cola, un evento nunca leído también quedaría en claro hasta su drenaje.
- **Por qué además al leer**: cubre el archivo que la pasada no pudo reescribir sin agregar un camino de error nuevo.
- **Costo**: la pasada lee y reescribe una vez cada archivo legacy. Con el techo de 100 MB es un costo acotado y ocurre sólo en el primer arranque posterior al despliegue; en arranques siguientes sólo lee los primeros 6 bytes de cada archivo.
- **Alternativa descartada**: script de migración separado. D63 lo excluye explícitamente.

### D-6. Un archivo que no se autentica sigue el camino existente de archivo ilegible

`QueueFileUnreadable` se agrega a la tupla de excepciones que ya atrapan `iter_entries`, `get_attempts`, `bump_attempts` y `discard`, sin cambiar lo que hace cada rama:

- `iter_entries` lo saltea y registra `queue.unreadable_file` con `event_id` (tomado del nombre) y `reason` (`authentication_failed` | `malformed`), nunca con contenido ni ruta de `watch_paths`;
- `get_attempts` y `bump_attempts` devuelven `0` sin reescribir;
- el archivo no entra en `_pending`, no se publica y no detiene el agente; sigue contando para el presupuesto y sale por drop-oldest.

Es el tratamiento que Change 42 dejó implementado para un archivo ilegible y el que D63 referencia como "corrupto según D37". Este change no inventa un destino nuevo; si ese destino debe cambiar, es una decisión abierta (ver Open Questions).

- **Nunca se interpreta un archivo que falla GCM como legacy en claro**: la clasificación depende del magic, no de "falló el descifrado, probemos JSON". De lo contrario un atacante con escritura sobre el directorio podría plantar un sobre en claro que se publicaría firmado por el agente.

### D-7. Presupuesto de 100 MB sobre bytes en disco

`enqueue()` calcula `new_size` como el tamaño del blob cifrado (`len(json) + 6 + 12 + 16`). `_MAX_BYTES` no cambia y sigue midiendo lo que ocupa la cola en disco, que es la semántica de RN-84. La sobrecarga fija de 34 bytes por archivo reduce marginalmente la cantidad de eventos que entran en 100 MB; es irrelevante frente al tamaño típico de un sobre con `diff_text`.

### D-8. Construcción en `__main__.py`

`EventQueue` recibe el `master_secret` ya cargado en la línea 224 y `cfg.agent_id`. No se agrega ninguna carga nueva del secreto ni ningún camino que abra la cola antes del bootstrap.

## Risks / Trade-offs

- [Re-bootstrap que entrega un `master_secret` distinto] → toda la cola y el descarte previos dejan de autenticarse y se tratan como ilegibles: no se publican y salen por drop-oldest. Es la misma exposición que ya tienen baseline y cuarentena. Ver Open Questions.
- [Operador pierde la inspección directa del descarte] → los registros siguen existiendo, contabilizados en `discarded_events` del heartbeat; su lectura requiere el `master_secret`. Ver Open Questions.
- [Un archivo que no se autentica ocupa presupuesto hasta que drop-oldest lo alcanza] → comportamiento idéntico al actual para archivos ilegibles; queda visible por el log `queue.unreadable_file`.
- [Crash durante la migración] → la escritura atómica garantiza que el archivo es el claro completo o el cifrado completo; el `.tmp` huérfano se barre en el arranque siguiente, que reintenta la migración.
- [Costo de CPU del cifrado en el camino caliente] → AES-GCM sobre sobres de kilobytes es despreciable frente al `fsync` que ya se hace por escritura. El índice de Change 42 sigue evitando relecturas de directorio.
- [Tests que leen archivos de cola como JSON] → se reemplazan por lecturas mediante la API de la cola o un helper de descifrado de tests; ninguna aserción de comportamiento se relaja.

## Migration Plan

1. Desplegar la nueva versión del agente (`install.sh` reemplaza el código; D56/RN-150).
2. En el primer arranque, la pasada de D-5 cifra la cola y el descarte existentes antes de que el publisher drene. El log `queue.migration` registra los conteos.
3. **Rollback**: una versión anterior del agente no sabe leer el formato cifrado; `_load_envelope` fallaría con `JSONDecodeError`, los saltearía y no los publicaría. Por lo tanto, un rollback con eventos pendientes en cola los deja sin publicar hasta volver a la versión nueva. Antes de revertir, esperar a que `queue_size` del heartbeat llegue a 0.

## Open Questions

1. **Destino final de un archivo que no se autentica.** D63 dice "se trata como corrupto según D37", pero el texto de D37/RN-131 no define un tratamiento de archivos corruptos: su vocabulario cerrado de motivos de descarte es `max_attempts_exceeded`, `invalid_schema`, `clock_skew`. Este diseño aplica el comportamiento ya implementado para archivos ilegibles (saltear, no publicar, salir por drop-oldest, log). Si se quiere moverlo al descarte con un motivo nuevo (p. ej. `unreadable`), borrarlo o emitir una alerta, eso extiende el vocabulario de D37/RN-71 y MUST cerrarse primero en el appendix de `docs/reglas_de_negocio.md`.
2. **Cola previa a un re-bootstrap con otro `master_secret`.** `bootstrap.run()` reescribe `secrets/master_secret` cuando `is_bootstrapped()` es falso, lo que incluye un certificado vencido. No se verificó si el backend entrega el mismo `master_secret` a un agente ya registrado. Si puede cambiar, falta decidir si los eventos pendientes se aceptan como perdidos (igual que la baseline) o si el bootstrap debe drenar o preservar la clave anterior. La rotación de clave está fuera de alcance por D63, pero este caso no es una rotación deliberada.
3. **Inspección forense del descarte.** Con D37 un operador podía leer el motivo y el payload de un evento descartado directamente en el host. D63 no define una herramienta de lectura. Falta decidir si se agrega un comando local de solo lectura (con los mismos requisitos de privilegios que el acceso a `secrets/`) o si la inspección queda fuera del producto.
