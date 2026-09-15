## Why

**La cola offline y el directorio de descarte del agente son la única copia persistente del contenido que todavía queda en claro.** La auditoría V10 (riesgo M-4) lo verificó en el código:

- `agent/queue.py` escribe cada evento como un sobre JSON (`{"payload": {...}, "attempts": ..., "first_attempt_at": ...}`) con `json.dumps` directo a disco. El `payload` incluye `diff_text`, la ruta monitoreada y el contexto de proceso.
- `EventQueue.discard()` copia el mismo sobre al directorio de descarte (Change 42, `stream-ack-durability`), agregando `discard_reason` y `discarded_at`, también en claro.
- Los permisos `0700` del directorio y `0600` de cada archivo limitan el acceso en el host vivo, pero no protegen el contenido ante una copia del disco, una imagen de la VM o un respaldo.
- La baseline (`derive_baseline_key`, `info=b"baseline-v1"`) y la cuarentena (`derive_quarantine_key`, `info=b"quarantine-v1"`) ya se cifran con AES-256-GCM y claves derivadas del `master_secret` (RN-50, RN-82). La cola quedó fuera de ese patrón.

La decisión D63/RN-157 cerró el qué; este change lo implementa.

## What Changes

- **Cifrado en reposo (D63/RN-157)**: todo archivo que el agente escribe en la cola offline y en el directorio de descarte se cifra con AES-256-GCM. La clave se deriva con `HKDF-SHA256(master_secret, salt=agent_id, info=b"queue-v1")`, separada por dominio de la baseline y de la cuarentena, y vive sólo en memoria. Cada escritura usa un nonce aleatorio de 12 bytes; los datos asociados ligan el contenido al nombre del archivo, de modo que un archivo renombrado o intercambiado no se autentica.
- **Migración en el lugar**: los archivos en claro preexistentes, tanto de la cola como del descarte y tanto en formato sobre como en payload desnudo, se leen una única vez al abrir la cola y se reescriben cifrados con el mismo nombre, sin script de migración separado. La lectura sigue tolerando un archivo en claro que la pasada no haya alcanzado.
- **Integridad**: un archivo que no supera la verificación GCM (byte alterado, truncado, clave distinta, nombre cambiado) se trata por el mismo camino que la cola ya aplica a un archivo ilegible: no se publica, no interrumpe el drenaje de los demás ni detiene el agente, y se registra sin contenido.
- **Orden de arranque explícito**: la cola sólo se abre después de cargar el `master_secret`, lo que ya ocurre después del bootstrap. Ninguna escritura de cola puede ocurrir sin clave.
- **Sin cambios**: nombre de archivo (`{detected_at_ms:016d}_{event_id}.json`), orden FIFO, escritura atómica, límite de 100 MB medido sobre el tamaño en disco, drop-oldest, cota del descarte, vocabulario de motivos de descarte y contrato de durabilidad de D37/RN-131. La rotación de la clave queda fuera de alcance.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `agent-queue-durability`: cifrado autenticado de los archivos de cola y descarte, migración en el lugar de archivos en claro y tratamiento de un archivo que no se autentica.
- `agent-core`: la cola offline se abre sólo después de cargar el `master_secret`.

## Impact

**Reglas y decisiones**: implementa D63/RN-157; complementa RN-50 y RN-82 (cifrado y derivación de claves del agente) y D37/RN-131 (durabilidad), sin modificarlas. Cierra la parte de cola del riesgo M-4 de la auditoría V10.

**Dependencias**: Change 42 (`stream-ack-durability`) es dueño del sobre y del directorio de descarte. Su código está implementado, pero el change todavía no está archivado (104/109 tareas) y sus requisitos de sobre y descarte viven en su delta de `agent-queue-durability`, no en la main spec. Por eso este change sólo agrega requisitos y no modifica los de Change 42. Change 42 MUST archivarse antes que este.

**Código**: `agent/queue.py` (derivación de clave, cifrado, detección de formato, migración, tratamiento de archivos que no se autentican, firma de `EventQueue`), `agent/__main__.py` (construcción de la cola con el `master_secret` ya cargado), tests en `agent/tests/` que construyen `EventQueue` (`test_queue.py`, `test_stream_ack_durability.py`, `test_reconnect_order.py` y otros) y un archivo de tests nuevo para el cifrado.

**Dependencias externas**: ninguna nueva; `cryptography` ya se usa en `agent/baseline.py` y `agent/quarantine.py`.

**Operación**: los registros del descarte dejan de poder inspeccionarse con un visor de texto. Los scripts de evidencia archivados en `docs/cierre/evidencia/` no se modifican.
