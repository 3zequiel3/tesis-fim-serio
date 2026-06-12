## 1. Cripto: derivación de clave y cifrado AES-GCM

- [x] 1.1 Crear `agent/baseline.py` con la función `derive_baseline_key(master_secret: bytes, agent_id: str) -> bytes` usando `HKDF-SHA256(ikm=master_secret, salt=agent_id.encode(), info=b"baseline-v1", length=32)` (RN-82)
- [x] 1.2 Implementar `load_master_secret(secrets_dir) -> bytes` que lea `secrets/master_secret`, valide que son exactamente 32 bytes y falle con error claro si no existe o tiene tamaño incorrecto
- [x] 1.3 Implementar `_encrypt(key, plaintext_json: bytes) -> bytes` con AES-256-GCM: nonce `os.urandom(12)`, layout `[0x01][nonce(12)][ciphertext+tag]` (RN-19, RN-50, RN-82)
- [x] 1.4 Implementar `_decrypt(key, blob: bytes) -> bytes` que parsee el layout, valide la versión y descifre; al fallar la etiqueta GCM (`InvalidTag`) lanzar `BaselineIntegrityError(path)` (RN-19, RN-50)
- [x] 1.5 Incluir el `path` dentro del plaintext autenticado para que GCM proteja contra swapping de entradas (design D2)

## 2. Persistencia atómica y permisos

- [x] 2.1 Implementar `_atomic_write(final_path, data: bytes)` con `os.open(tmp, O_CREAT|O_WRONLY|O_TRUNC, 0o600)` → write → `os.fsync` → `os.close` → `os.replace(tmp, final)`, con `tmp` en el mismo directorio (RN-20, design D6)
- [x] 2.2 Implementar `_entry_path(path: str) -> Path` que nombre el archivo como `baseline/<sha256(path)>.bin` (design D2)
- [x] 2.3 Al iniciar el motor, verificar y asegurar permisos `0700` en `baseline/`; fallar ruidosamente si no se puede (RN-20)

## 3. Modelo de entrada y estados

- [x] 3.1 Definir el dataclass/modelo `BaselineEntry` (path, status, hash, size, mode, uid, gid, mtime, captured_at, snapshots, content_b64) serializable a JSON
- [x] 3.2 Implementar `write_entry(path) -> BaselineEntry`: stat + lectura + SHA-256 + serialización + cifrado + escritura atómica, con `status: present` (RN-15)
- [x] 3.3 Implementar `read_entry(path) -> BaselineEntry | None`: descifrar y deserializar; `None` si no existe; propagar `BaselineIntegrityError` si el tag falla (RN-50)
- [x] 3.4 Implementar `mark_absent(path)`: persistir entrada con `status: absent`, `hash: null`, sin contenido (RN-66)
- [x] 3.5 Implementar `list_entries() -> list[str]`: recorrer `baseline/*.bin`, descifrar y devolver los paths registrados (design D2)
- [x] 3.6 Aplicar límite de tamaño `max_file_bytes` (default 10 MiB): archivos por encima se registran con `content_b64: null` y flag `oversize: true` (design Open Questions)

## 4. Snapshots versionados

- [x] 4.1 Implementar `add_snapshot(path) -> bool`: comparar hash actual con el del último snapshot; si coincide, no agregar (dedup, RN-49)
- [x] 4.2 Aplicar FIFO de máx 3 snapshots: al superar 3, descartar el más antiguo antes de agregar (RN-47)
- [x] 4.3 Comprimir con gzip los snapshots no-activos (`content_b64 = base64(gzip(content))`, `gzip: true`) y mantener el activo sin comprimir (RN-48)

## 5. Init scan y verificación

- [x] 5.1 Implementar `init_scan(watch_paths) -> ScanReport`: recorrer paths, escanear solo archivos regulares sin baseline previo, generar entradas `present` cifradas; idempotente en reinicios (RN-15)
- [x] 5.2 Implementar `verify_entry(path) -> bool`: intentar descifrar; True si íntegra, raise `BaselineIntegrityError` si el tag falla; loguear incidente de seguridad sin publicarlo (D8, RN-50)
- [x] 5.3 Exponer la clase `BaselineEngine(config, master_secret_bytes)` con la API in-process (init_scan, write_entry, read_entry, verify_entry, add_snapshot, mark_absent, list_entries) sin servidor HTTP (D8)

## 6. Wiring en el agente

- [x] 6.1 En `agent/__main__.py`, tras el bootstrap exitoso, instanciar `BaselineEngine` cargando `master_secret` y disparar `init_scan(cfg.watch_paths)` en el primer arranque
- [x] 6.2 Loguear el resultado del scan (cantidad de entradas, paths oversize) con structlog, asegurando que `master_secret` y la clave derivada queden redactados por el sanitizador de `agent/logging.py`

## 7. Tests

- [x] 7.1 Test: derivación determinística (misma clave) y separación por `agent_id` distinto (RN-82)
- [x] 7.2 Test: round-trip cifrado/descifrado preserva contenido y el SHA-256 coincide (criterio Done)
- [x] 7.3 Test: alterar un byte del blob cifrado hace fallar el descifrado y lanza `BaselineIntegrityError` (criterio Done, RN-19/RN-50)
- [x] 7.4 Test: cada escritura usa un nonce distinto (RN-82)
- [x] 7.5 Test: GCM detecta swapping de entrada entre paths (design D2)
- [x] 7.6 Test: init scan genera entradas `present` con permisos `0600` y directorio `0700`; es idempotente en reinicio (RN-15, RN-20)
- [x] 7.7 Test: `mark_absent` produce `status: absent`, `hash: null`, sin contenido (RN-66)
- [x] 7.8 Test: snapshots — dedup por hash, FIFO de 3, gzip del no-activo y activo sin comprimir (RN-47, RN-48, RN-49)
- [x] 7.9 Test: `master_secret` ausente o de tamaño incorrecto falla con error claro (RN-82)

## 8. Validación final

- [x] 8.1 Ejecutar la suite de tests del agente y confirmar que pasa
- [x] 8.2 Validar el criterio Done del Change 07: scan inicial genera archivos cifrados; descifrado produce el mismo hash; alteración del cifrado falla
- [x] 8.3 Ejecutar `openspec validate agent-baseline-engine` y resolver cualquier inconsistencia
