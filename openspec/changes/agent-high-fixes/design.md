## Context

La auditoría de bugs (`docs/audit_bugs.md`, 2026-06-23) listó 4 ALTOS en el agente FIM (H1–H4). Los 4 archivos afectados ya existen y fueron parcheados parcialmente por C21 (`agent-critical-fixes`, commit `d3b2005`). Esta change es de remediación pura: no agrega features ni introduce suposiciones nuevas. Cada fix hace cumplir una regla ya cerrada.

Estado actual confirmado leyendo el código:
- `agent/queue.py`: escritura atómica ya correcta (`os.replace` + `fsync`, líneas 82-94); el bug está solo en el nombre de archivo sin zero-pad (líneas 80-81) y el `sorted()` lexicográfico en `_json_files` (línea 45).
- `agent/journal.py`: `_write` usa `write_text` directo (línea 99), sin atomicidad ni HMAC; `JournalManager.__init__` solo recibe `journal_dir`; `JournalEntry` no tiene campo `hmac`.
- `agent/bootstrap.py`: usa **Ed25519** (`Ed25519PrivateKey`, línea 23), POST con `verify=False` (línea 108), y persiste el material recibido sin verificación (líneas 123-126); `is_bootstrapped` solo chequea expiración.
- `agent/baseline.py`: `update_from_command` (líneas 439-478) construye `BaselineEntry` con `snapshots=[]` y `content_b64=None`, sobreescribiendo. Existe `read_entry(path) -> BaselineEntry | None` (línea 274) reutilizable para el merge.
- `agent/streams.py` expone `load_shared_secret(secrets_dir)`, ya usado por `commands.py`.

Restricciones: Python 3.13, asyncio, `cryptography==44.0.2` ya pinneado. Sin servidor HTTP en el agente (D8) — el bootstrap es el único POST y se mantiene; el fix es verificación local del material recibido, no un cambio de transporte.

## Goals / Non-Goals

**Goals:**
- Que la cola offline respete FIFO y drop-oldest correctamente bajo timestamps de longitud variable (H1).
- Que el journal sobreviva muertes de proceso (atomicidad) y detecte manipulación (HMAC), sin perder la rehidratación de pendientes (H2).
- Que el agente no confíe en material de bootstrap no verificado criptográficamente (H3).
- Que `baseline_update` no destruya el contenido cifrado necesario para restauraciones (H4).
- Cobertura de regresión por cada bug.

**Non-Goals:**
- No se reescribe el formato del journal ni de la cola más allá de lo necesario (campo `hmac` y zero-pad).
- No se cambia el transporte de bootstrap (sigue siendo POST pre-mTLS; D8 intacto).
- No se tocan los otros ALTOS (H5–H8 son del backend, fuera de scope).
- No se introduce rotación de claves ni cambios en el esquema de derivación HKDF (eso es C07, ya cerrado).
- No se migra activamente el formato legacy de la cola: la tolerancia es de lectura/orden, no un rewrite masivo en disco.

## Decisions

### D-H1: Zero-pad a 16 dígitos + sort robusto en `_json_files`

**Decisión**: el nombre de archivo pasa a `f"{detected_at_ms:016d}_{event_id}.json"`. 16 dígitos cubren epoch-ms hasta el año ~2286 (`9_999_999_999_999_999` ms), con margen amplísimo. Adicionalmente, `_json_files` ordena con `key=lambda f: f.name` tras normalizar, pero como la fuente de verdad del orden es el prefijo numérico, se mantiene `sorted(...)` sobre nombres ya padded.

**Por qué 16 y no `key=int(stem.split('_')[0])`**: el zero-pad hace el sort lexicográfico correcto *por construcción* y deja los nombres ordenables por cualquier herramienta (ls, glob, debugging manual), no solo por el código Python. Es la solución más robusta y auto-documentada. La alternativa de `key=lambda` funciona pero deja los nombres en disco desordenados visualmente y depende de que *todo* call-site use la misma key.

**Tolerancia de legacy**: archivos viejos sin pad (12-13 dígitos) pueden coexistir tras un upgrade in-place. Para que el orden mixto sea correcto, `_json_files` usará una key que extrae el timestamp numérico del prefijo (`int(f.stem.split("_", 1)[0])`) en lugar de confiar puramente en el orden lexicográfico de strings de distinta longitud. Así el sort es correcto para nombres padded, no-padded, y mezclados, sin requerir un rename masivo. `remove(event_id)` no cambia: ya hace `split("_", 1)` y compara `parts[1]`, y el UUID v4 no tiene underscore.

**Alternativa descartada**: rename masivo de todos los archivos legacy al arrancar. Más I/O, riesgo de fallo a mitad, innecesario si la key de sort tolera ambos formatos.

### D-H2: Escritura atómica + HMAC-SHA256, `shared_secret` inyectado por constructor

**Decisión atomicidad**: `_write` replica el patrón de `queue.py:82-94` — `os.open` con `O_CREAT|O_WRONLY|O_TRUNC` a un `.tmp`, `write` + `flush` + `os.fsync`, luego `os.replace(tmp, target)`. El `.tmp` se limpia en `except`.

**Decisión HMAC**: `JournalEntry` gana un campo `hmac: str | None = None`. Al escribir: se serializa el entry SIN el campo `hmac` (canonical JSON con `sort_keys=True`, `separators=(",",":")`), se calcula `hmac.new(shared_secret, payload_bytes, hashlib.sha256).hexdigest()`, se setea en el entry, y se persiste el JSON completo (ya con `hmac`). Al leer: se separa el `hmac` almacenado, se recalcula sobre el resto con el mismo canonical encoding, y se compara con `hmac.compare_digest` (constant-time). Mismatch o parse error → log warning + `None`.

**Wiring del secreto**: `JournalManager.__init__` pasa a recibir `shared_secret: bytes`. En `__main__.py:104` se carga vía `load_shared_secret(cfg.storage.secrets_dir)` (mismo helper que usa `commands.py`) y se pasa al constructor. Si el secreto no está disponible en el momento de construcción (bootstrap aún no corrió), se decide: el journal solo se usa post-bootstrap (las acciones destructivas requieren comandos firmados que llegan tras mTLS), así que el secreto siempre existe cuando el journal se usa. Se valida en `__main__` y se falla temprano si falta.

**Por qué canonical JSON determinístico**: el HMAC debe recalcularse byte-idéntico al leer. Usar `json.dumps(..., sort_keys=True, separators=(",",":"))` garantiza serialización estable e independiente del orden de inserción de claves. Es el mismo patrón que `queue.py:67` ya usa para los payloads.

**Alternativa descartada**: firmar el archivo entero con el `hmac` incluido (firma sobre sí misma). Imposible de verificar. Por eso se excluye el campo `hmac` del contenido firmado.

### D-H3: Verificación cert→CA con Ed25519 (NO RSA/PKCS1v15)

**Decisión — corrección sobre el brief**: el `bootstrap.py` real usa **Ed25519**, no RSA. La verificación de firma Ed25519 NO lleva padding ni hash algorithm. El método correcto es:

```python
ca_pub = ca_cert.public_key()  # Ed25519PublicKey
ca_pub.verify(cert.signature, cert.tbs_certificate_bytes)  # raise InvalidSignature si falla
```

No se usa `PKCS1v15()` ni `cert.signature_hash_algorithm` (eso es RSA-only y con Ed25519 `signature_hash_algorithm` es `None`). Para robustez ante una CA que en el futuro pudiera ser RSA, se puede ramificar por tipo de clave pública, pero el camino primario y testeado es Ed25519.

Tres verificaciones, todas antes de cualquier `_write_file`:
1. **Cadena**: `ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes)`. `InvalidSignature` → `RuntimeError`.
2. **CN**: `cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == config.agent_id`. Mismatch → `RuntimeError`.
3. **Clave pública**: comparar `cert.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)` vs `private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)`. Para Ed25519 el formato `Raw/Raw` es el correcto; un fallback a `SubjectPublicKeyInfo`/`PEM` se usa si la clave no soporta Raw. Mismatch → `RuntimeError`.

Solo si las 3 pasan se escriben cert, CA y secrets. El POST sigue con `verify=False` (no se puede confiar en la CA del servidor antes de recibirla), pero el material recibido se verifica localmente — que es exactamente lo que cierra el MITM.

**Por qué orden cadena→CN→clave**: la cadena es la verificación más fuerte (prueba que la CA emitió el cert); CN y clave pública atan el cert a *esta* identidad y *esta* clave. Las tres son necesarias: la cadena sola no impide que el MITM presente un cert válido emitido por una CA falsa que él mismo controla y envía como `ca_cert_pem` — por eso CN + clave pública atan el resultado a lo que el agente realmente pidió (su `agent_id` y su CSR).

**Limitación honesta**: si el atacante controla totalmente la respuesta, puede enviar una CA falsa + cert falso que chainee y tenga el CN correcto. La defensa real contra eso es que el atacante NO conoce la `private_key` del agente: la verificación #3 (clave pública del cert == clave local) asegura que el cert corresponde al CSR que el agente generó. Un MITM no puede producir un cert cuya clave pública coincida con una privada que no tiene, salvo que el backend legítimo lo haya firmado. Esto es lo que ata la confianza al secreto local.

### D-H4: Merge en `update_from_command` vía `read_entry`

**Decisión**: leer `existing = self.read_entry(path)` al inicio. Si existe, construir el nuevo `BaselineEntry` preservando `snapshots=existing.snapshots` y `content_b64=existing.content_b64`, actualizando `hash`, `status` y `captured_at`. Si no existe, comportamiento actual (entry nuevo con content vacío). Re-cifrar con nuevo nonce GCM y `_atomic_write` como hoy.

**Por qué `read_entry` y no leer el blob crudo**: `read_entry` ya descifra y devuelve el `BaselineEntry` tipado (línea 274), incluyendo `snapshots` y `content_b64`. Reusarlo evita duplicar la lógica de descifrado y mantiene un solo punto de verdad.

**Metadata `size/mode/uid/gid/mtime`**: el comando `baseline_update` no trae esos campos (vienen `None` en el código actual). Decisión: preservar también los del entry existente si están presentes, ya que un `baseline_update` por aprobación no cambia los metadatos del archivo en disco — solo confirma el nuevo hash como baseline. Esto mantiene la coherencia del entry. Si no había entry previo, quedan `None` como hoy.

## Risks / Trade-offs

- [H1: archivos legacy sin pad en disco tras upgrade] → la key de sort extrae el timestamp numérico (`int(stem.split("_",1)[0])`), correcta para ambos formatos; no requiere migración. Test cubre orden mixto.
- [H2: cambio de firma de `JournalManager.__init__` rompe call-sites] → solo hay un constructor (`__main__.py:104`); se actualiza en la misma change. Test de wiring.
- [H2: entradas escritas por la versión anterior NO tienen HMAC] → se tratan como corruptas (HMAC ausente → descartadas). Riesgo aceptable: el journal es efímero (pending → completed/failed → delete); tras un restart post-upgrade las pending legacy se descartan en vez de rehidratarse. Mitigación: documentar en notas de upgrade que el journal debe estar vacío (sin acciones in-flight) al actualizar, o aceptar la pérdida de pendientes legacy (que es más seguro que confiar en entradas sin firmar).
- [H3: la verificación Ed25519 difiere del brief (RSA)] → resuelto con el método agnóstico al algoritmo; el camino Ed25519 es el real y testeado. Riesgo de regresión si la CA cambiara a RSA: mitigado con ramificación opcional por tipo de clave.
- [H3: MITM con CA+cert totalmente falsos] → mitigado por la verificación de clave pública (#3): el cert debe corresponder a la `private_key` local, que el atacante no posee. Es la garantía criptográfica central.
- [H4: preservar metadata `size/mode/...` del entry viejo podría quedar desactualizada] → bajo impacto: esos campos son informativos; el `hash` (que es lo que importa para integridad) sí se actualiza. Alternativa de dejarlos `None` también es válida; se elige preservar por coherencia.

## Migration Plan

1. Deploy: los 4 fixes son in-place sobre archivos existentes del agente. No hay cambios de esquema en backend ni en streams.
2. Cola (H1): los archivos existentes siguen drenándose correctamente porque la key de sort tolera ambos formatos. Los nuevos se escriben padded. No hay paso de migración explícito.
3. Journal (H2): preferentemente actualizar con el journal sin acciones in-flight (agente detenido limpio). Las pending legacy sin HMAC se descartan al arrancar (fail-safe). Documentar en notas operativas.
4. Bootstrap (H3): solo afecta a bootstraps futuros; agentes ya bootstrapeados no re-verifican (no se re-ejecuta bootstrap si `is_bootstrapped` es true). Sin impacto en agentes en producción ya registrados.
5. Baseline (H4): el fix es puramente defensivo; entries ya corrompidos por el bug previo (con `content_b64=None`) no se recuperan automáticamente — requieren un re-scan o un nuevo `baseline_update` con contenido. Documentar que tras el fix, un re-scan reconstruye los baselines dañados.
6. Rollback: revertir el commit restaura el comportamiento anterior. El campo `hmac` extra en el JSON del journal es ignorado por la versión vieja (lee con `JournalEntry(**data)` → fallaría por campo desconocido). **Nota**: rollback del journal requiere limpiar entries nuevas con `hmac` o la versión vieja las rechazaría. Bajo riesgo dado el ciclo de vida efímero del journal.

## Open Questions

- Ninguna que bloquee la implementación. Las decisiones técnicas (Ed25519 vs RSA, merge de metadata, tolerancia de legacy) están resueltas arriba y no introducen suposiciones de negocio nuevas — todas hacen cumplir reglas ya cerradas (RN-16, RN-17, RN-30, RN-39, RN-78, RN-79, RN-83, RN-84).
