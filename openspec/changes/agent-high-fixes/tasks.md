## 1. H1 — Cola FIFO (`agent/queue.py`)

- [x] 1.1 En `enqueue`, cambiar el nombre de archivo a `f"{detected_at_ms:016d}_{event_id}.json"` (y el `.tmp` correspondiente) — zero-pad a 16 dígitos.
- [x] 1.2 En `_json_files`, ordenar por timestamp numérico extraído del prefijo: `sorted(self._dir.glob("*.json"), key=lambda f: int(f.stem.split("_", 1)[0]))`, tolerando nombres legacy sin pad y padded mezclados.
- [x] 1.3 Confirmar que `remove(event_id)` sigue correcto (split en el primer `_`, UUID sin underscore) — sin cambios funcionales, solo verificar.
- [x] 1.4 Tests: (a) `_json_files` ordena cronológicamente con timestamps de 12 y 13 dígitos; (b) `drop-oldest` bajo presión borra el evento más viejo, no el más nuevo; (c) orden correcto con mezcla legacy/padded; (d) `iter_fifo` devuelve oldest-first.

## 2. H2 — Journal durable e íntegro (`agent/journal.py`, `agent/__main__.py`)

- [x] 2.1 Agregar campo `hmac: str | None = None` al dataclass `JournalEntry`.
- [x] 2.2 Cambiar `JournalManager.__init__` para recibir `shared_secret: bytes` además de `journal_dir`.
- [x] 2.3 Implementar helper de canonical encoding: serializar el entry SIN `hmac` con `json.dumps(..., sort_keys=True, separators=(",",":"))`.
- [x] 2.4 En `_write`: calcular `hmac.new(shared_secret, canonical_bytes, hashlib.sha256).hexdigest()`, setear `entry.hmac`, y persistir el JSON completo de forma atómica (tmp → `fsync` → `os.replace`, patrón de `queue.py:82-94`, con limpieza del `.tmp` en `except`).
- [x] 2.5 En `_read`: separar el `hmac` almacenado, recalcular sobre el resto con el mismo canonical encoding, comparar con `hmac.compare_digest`; mismatch o ausencia → log warning + `return None`.
- [x] 2.6 En `load_pending`: aplicar la misma verificación de HMAC; entradas truncadas/inválidas se skip-ean con warning.
- [x] 2.7 En `__main__.py`, cargar el `shared_secret` vía `load_shared_secret(cfg.storage.secrets_dir)` y pasarlo a `JournalManager(...)`; fallar temprano si el secreto falta.
- [x] 2.8 Tests: (a) entrada con HMAC válido se lee OK; (b) entrada con contenido modificado (HMAC inválido) se descarta; (c) entrada truncada (simulando muerte de proceso) se descarta en `load_pending`; (d) entrada escrita atómicamente sobrevive y se rehidrata; (e) wiring: `JournalManager` recibe el secreto correcto.

## 3. H3 — Verificación de bootstrap (`agent/bootstrap.py`)

- [x] 3.1 Tras `resp.json()` y antes de cualquier `_write_file`, parsear `cert = x509.load_pem_x509_certificate(data["cert_pem"].encode())` y `ca_cert = x509.load_pem_x509_certificate(data["ca_cert_pem"].encode())`.
- [x] 3.2 Verificación de cadena Ed25519: `ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes)` (sin padding ni hash algorithm); `InvalidSignature` → `RuntimeError` con detalle.
- [x] 3.3 Verificación de CN: `cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == config.agent_id`; mismatch → `RuntimeError`.
- [x] 3.4 Verificación de clave pública: comparar `cert.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)` vs `private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)`; mismatch → `RuntimeError`.
- [x] 3.5 Solo escribir cert/CA/secrets si las 3 verificaciones pasan; mover los `_write_file` después del bloque de verificación.
- [x] 3.6 Tests: (a) cert con CN incorrecto → `RuntimeError`, nada se persiste; (b) cert no firmado por la CA recibida → `RuntimeError`; (c) cert cuya clave pública no coincide con la local → `RuntimeError`; (d) material válido (cadena+CN+clave OK) se persiste correctamente.

## 4. H4 — Merge de baseline (`agent/baseline.py`)

- [x] 4.1 En `update_from_command`, leer `existing = self.read_entry(path)` al inicio.
- [x] 4.2 Si `existing` no es `None`, construir el nuevo `BaselineEntry` preservando `snapshots=existing.snapshots`, `content_b64=existing.content_b64` y los metadatos (`size/mode/uid/gid/mtime`) del entry existente; actualizar solo `hash`, `status` y `captured_at`.
- [x] 4.3 Si `existing` es `None`, mantener el comportamiento actual (entry nuevo con content vacío).
- [x] 4.4 Re-cifrar con nuevo nonce GCM y `_atomic_write` como hoy.
- [x] 4.5 Tests: (a) `update_from_command` preserva `snapshots` existentes; (b) preserva `content_b64` existente (un `restore_file` posterior no falla con `no_baseline_content`); (c) sin entry previo crea entry nuevo con content vacío; (d) re-delivery del mismo comando es idempotente y no corrompe el content.

## 5. Verificación y cierre

- [x] 5.1 Correr la suite de tests del agente; confirmar que los nuevos tests de regresión (H1–H4) pasan y no hay regresiones en los tests existentes.
- [x] 5.2 Confirmar que no se introdujeron dependencias nuevas (`cryptography==44.0.2` ya pinneado) ni cambios en backend/frontend/infra ni en el protocolo de streams.
- [ ] 5.3 Commit con conventional commits, sin Co-Authored-By (ej. `fix(agent): resolve 4 high-severity bugs in queue, journal, bootstrap, baseline (C23)`).
