## Why

La auditoría multi-agente del 2026-06-23 (`docs/audit_bugs.md`) encontró 8 bugs de severidad ALTA, 4 de ellos en el agente FIM. Estos 4 (H1–H4) comprometen garantías de durabilidad, integridad y seguridad que el sistema ya documenta como reglas cerradas: la cola offline borra el evento equivocado bajo presión (viola FIFO), el journal pierde acciones pendientes al reiniciar (rompe la rehidratación), el bootstrap acepta un certificado de un MITM como ancla de confianza para todo el mTLS futuro, y la actualización de baseline destruye el contenido cifrado que las restauraciones necesitan. Son fallos silenciosos: el agente loguea normalidad mientras pierde datos o confía en material no verificado. Esta change los remedia sin introducir features ni suposiciones nuevas — cada fix hace cumplir una regla ya cerrada.

## What Changes

- **H1 — Cola FIFO**: el nombre de archivo de la cola pasa a usar el timestamp zero-padded a 16 dígitos (`{detected_at_ms:016d}_{event_id}.json`). El sort lexicográfico de `_json_files` queda cronológicamente correcto y `drop-oldest` borra el evento más viejo, no el más nuevo. Migración tolerante de nombres legacy sin pad ya presentes en disco.
- **H2 — Journal durable e íntegro**: la escritura del journal pasa a ser atómica (tmp → fsync → `os.replace`, mismo patrón que `queue.py`) y cada entrada lleva un HMAC-SHA256 calculado con el `shared_secret`. La lectura verifica el HMAC; entradas truncadas o manipuladas se descartan como corruptas. La rehidratación de acciones pendientes al reiniciar deja de perder o confiar en entradas inválidas.
- **H3 — Bootstrap verificado**: antes de persistir el material recibido del backend, el agente verifica criptográficamente (1) que el cert chainee a la CA recibida —firma **Ed25519**, consistente con el `bootstrap.py` real, NO RSA/PKCS1v15—, (2) que el CN del cert sea el `agent_id` esperado, y (3) que la clave pública del cert coincida con la clave privada local. Cualquier fallo aborta con `RuntimeError` y no escribe nada. Cierra el MITM en el canal pre-mTLS.
- **H4 — Merge de baseline**: `update_from_command` lee el entry existente con `read_entry` y mergea — preserva `snapshots` y `content_b64`, actualiza solo `hash`, `status` y metadata derivada del comando. Un `restore_file` posterior a un `baseline_update` deja de fallar con `no_baseline_content`.
- Tests de regresión para cada fix (sort-FIFO con timestamps de distinta longitud, drop-oldest, journal truncado, journal con HMAC inválido, cert con CN inválido, cert no firmado por la CA, preservación de `snapshots` y `content_b64`).

No hay cambios **BREAKING** de contrato externo: los streams Valkey, el formato de comandos y los endpoints del backend no cambian. El único cambio de formato es interno al agente (nombre de archivo de cola y shape de entrada del journal), con migración tolerante.

## Capabilities

### New Capabilities
- `agent-queue-durability`: garantías de orden FIFO y política drop-oldest de la cola offline del agente bajo nombres de archivo con timestamps de longitud variable (H1).
- `agent-journal-integrity`: durabilidad (escritura atómica) e integridad (HMAC) del journal transaccional de acciones, incluida la rehidratación segura de pendientes al reiniciar (H2).
- `agent-bootstrap-verification`: verificación criptográfica del certificado y la CA recibidos durante el bootstrap antes de confiar en ellos como ancla de mTLS (H3).
- `agent-baseline-merge`: preservación del contenido cifrado (`snapshots`, `content_b64`) del baseline local al aplicar comandos `baseline_update` del backend (H4).

### Modified Capabilities
<!-- Ninguna. openspec/specs/ está vacío (las changes previas no archivaron specs en main); no hay capabilities establecidas cuyos REQUISITOS se modifiquen. Cada fix se captura como New Capability con el comportamiento correcto. -->

## Impact

- **Archivos del agente**:
  - `agent/queue.py` — H1: zero-pad del timestamp en `enqueue`; migración/orden tolerante en `_json_files`.
  - `agent/journal.py` — H2: escritura atómica + campo `hmac` en `JournalEntry`; inyección de `shared_secret` en `JournalManager`; verificación en `_read`/`load_pending`.
  - `agent/bootstrap.py` — H3: verificación cert→CA (Ed25519), CN, y match de clave pública antes de `_write_file`.
  - `agent/baseline.py` — H4: merge con `read_entry` en `update_from_command`.
  - `agent/__main__.py` — wiring: pasar `shared_secret` al construir `JournalManager` (H2).
- **Dependencias**: `cryptography==44.0.2` ya está pinneado en `agent/requirements.txt`; no se agregan dependencias nuevas. El `shared_secret` ya se carga vía `load_shared_secret` (reutilizado de `agent/streams.py`).
- **Reglas cubiertas**: RN-16, RN-17, RN-30 (H4), RN-39, RN-84 (H1), RN-78, RN-79 (H3), RN-83 (H2).
- **Decisiones aplicadas**: D8 (sin HTTP en el agente — toda comunicación sigue por streams; el bootstrap es el único POST y se mantiene como tal con verificación local del material).
- **DAG**: depende de C21 (`agent-critical-fixes`, commit `d3b2005`, ya aplicado) porque H1–H4 conviven con los archivos ya parcheados por C21. Sin dependencias del DAG pendientes.
- **Sin impacto en backend, frontend ni infra.** No cambia el protocolo de streams ni el contrato de comandos.
