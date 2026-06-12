## Context

El agente FIM (Changes 05/06) ya tiene config tipada (`AgentConfig`/`StorageConfig`), logging JSON sanitizado, estado persistente y bootstrap mTLS. El bootstrap escribe `secrets/master_secret` (raw 32 bytes, `0400`) y `secrets/shared_secret`. El directorio `baseline/` existe con permisos `0700` (creado por `install.sh`, agent-core).

Falta el motor que materializa el "estado sano": capturar, cifrar y verificar el contenido de cada archivo monitoreado. Sin él, el detector (Change 09) no tiene contra qué comparar y el decision engine (Change 10) no tiene de dónde restaurar.

Restricciones canónicas (reglas de negocio + arquitectura_stack):
- Cifrado **AES-256-GCM**, clave `HKDF-SHA256(ikm=master_secret, salt=AGENT_ID, info="baseline-v1")` (RN-82, W10).
- Nonce GCM de 96 bits único por archivo (RN-82).
- El baseline guarda el **archivo completo cifrado**, no solo el hash (arquitectura_stack: "Requisito clave").
- La etiqueta GCM reemplaza el HMAC sobre plaintext: integridad y confidencialidad en una operación (RN-19, RN-50).
- Snapshots: máx 3/archivo FIFO, gzip del no-activo, dedup por hash (RN-47, RN-48, RN-49).
- Estados `present | absent`, `hash: null` cuando `absent` (RN-66, léxico snake_case RN-71).
- Permisos `0600` archivos, `0700` directorio, `0400` master_secret (RN-20).
- Sin servidor HTTP: el módulo expone una API in-process, no endpoints (D8, RN-108).

## Goals / Non-Goals

**Goals:**
- Derivar la clave AES-256 de baseline de forma determinística desde `master_secret` + `agent_id`.
- Persistir cada entrada de baseline cifrada con AES-256-GCM, con metadata e integridad verificable.
- Ejecutar un init scan sobre `watch_paths` en el primer arranque y para paths nuevos sin baseline.
- Soportar snapshots versionados (máx 3, FIFO, gzip del no-activo, dedup por hash).
- Soportar el estado `absent`.
- Detectar alteración del ciphertext en disco al leer y señalar un incidente de integridad (sin devolver datos corruptos).
- Exponer una API in-process limpia consumible por detector y decision engine.

**Non-Goals:**
- Publicar eventos/incidentes por Valkey (eso es Change 08; aquí el incidente se **retorna/señala** al caller).
- Detección de cambios en tiempo real con fanotify (Change 09).
- Lógica de decisión approve/reject/auto_restore (Change 10).
- Sincronización de `baseline_update` desde backend (Change 08+).
- Diffs forenses de texto (capacidad separada del snapshot; este change cubre el snapshot completo cifrado, no el diff).

## Decisions

### D1 — Derivación de clave: HKDF-SHA256 con `master_secret` como IKM
`baseline_key = HKDF-SHA256(ikm=master_secret_bytes, salt=agent_id.encode(), info=b"baseline-v1", length=32)`, usando `cryptography.hazmat.primitives.kdf.hkdf.HKDF`. El `agent_id` como salt liga la clave a la identidad del host; el `info` versionado (`baseline-v1`) permite rotar el esquema sin cambiar el master_secret. La clave se deriva una vez al iniciar el motor y se mantiene solo en memoria.
*Alternativas:* clave directa = master_secret (rechazada: no versiona ni separa propósitos — el mismo master_secret podría reusarse para otra cosa); PBKDF2 (rechazado: el master_secret ya es 32 bytes de alta entropía, no una password, HKDF es el primitivo correcto).

### D2 — Formato de entrada en disco: un archivo binario por entrada, nombre = hash del path
Cada entrada vive en un único archivo `baseline/<sha256(path_utf8)>.bin`. Nombrar por hash del path (no por el path crudo) evita problemas con `/`, longitud y caracteres especiales, y da nombres de longitud fija. El archivo es el blob cifrado AES-GCM; su plaintext es un JSON con la metadata + el contenido del archivo (base64). Layout binario:

```
[1 byte version=0x01][12 bytes nonce][ciphertext incl. 16-byte GCM tag]
```

El plaintext cifrado (antes de GCM) es JSON:
```json
{
  "path": "/etc/passwd",
  "status": "present",
  "hash": "<sha256-hex del contenido claro>",
  "size": 1234,
  "mode": "0644",
  "uid": 0, "gid": 0,
  "mtime": "<iso8601>",
  "captured_at": "<iso8601>",
  "snapshots": [ {"hash":..., "captured_at":..., "gzip": true/false, "content_b64": "..."} ],
  "content_b64": "<contenido activo, sin gzip>"
}
```
El `path` se incluye dentro del plaintext autenticado para que la etiqueta GCM también proteja contra swapping de archivos (mover el blob de un path a otro). Un archivo sidecar de índice **no** se usa: el listado se resuelve recorriendo `baseline/*.bin` y descifrando (aceptable para el volumen de un host).
*Alternativas:* metadata en JSON plano + contenido cifrado aparte (rechazado: la metadata quedaría sin cifrar, filtra paths e información de inventario); SQLite cifrado (rechazado: dependencia extra y complejidad, no justificada para el volumen esperado).

### D3 — Nonce de 96 bits aleatorio por escritura
Cada escritura genera un nonce nuevo con `os.urandom(12)`. Como cada archivo de baseline se reescribe completo en cada update (no se hace cifrado incremental), no hay reuso de nonce con la misma clave sobre datos distintos. El nonce se prependa al ciphertext (D2). 96 bits aleatorios con reescritura completa mantiene la probabilidad de colisión despreciable para el volumen de un host.
*Alternativa:* nonce contador persistido (rechazado: requiere estado adicional sincronizado y es frágil ante restauración de backups del disco; aleatorio es más simple y seguro aquí).

### D4 — Snapshots dentro de la misma entrada cifrada
Los snapshots (máx 3 FIFO) viven en el array `snapshots` del JSON plaintext de la entrada, no como archivos separados. El snapshot activo (más reciente) se guarda sin gzip para acceso rápido; los no-activos se comprimen con gzip antes de entrar al JSON (`content_b64` = base64(gzip(content)), `gzip: true`) (RN-48). Antes de agregar un snapshot se compara su hash con el del último snapshot; si coincide, no se agrega (dedup, RN-49). Al superar 3, se descarta el más antiguo (FIFO, RN-47). Todo el conjunto se re-cifra al persistir.
*Alternativa:* snapshots como archivos `baseline/<hash>.snap.N.bin` independientes (rechazado: multiplica operaciones de cifrado y archivos; mantenerlos en una entrada atómica simplifica el FIFO y la consistencia).

### D5 — Verificación al leer = intentar descifrar; fallo de tag → incidente
`read_entry`/`verify_entry` intentan `AESGCM.decrypt`. Si lanza `InvalidTag`, el contenido fue alterado en disco: el método NO devuelve datos, registra un log de seguridad y **retorna/lanza una señal de incidente de integridad** (objeto `BaselineIntegrityError` con `path` y razón) para que el caller (Change 08+) lo publique por Valkey. El motor no publica nada por sí mismo (D8).
*Alternativa:* hash separado del ciphertext (rechazado: redundante, la etiqueta GCM ya autentica; RN-19/RN-50 explícitamente reemplazan el HMAC por la garantía integrada de GCM).

### D6 — Escrituras atómicas con permisos desde la creación
Patrón: `fd = os.open(tmp, O_CREAT|O_WRONLY|O_TRUNC, 0o600)` → escribir → `os.fsync` → `os.close` → `os.replace(tmp, final)`. Crear con `0o600` desde el `open` evita la ventana en que el archivo existe con permisos laxos. El directorio `baseline/` ya es `0700` (agent-core); el motor verifica/asegura `0700` al iniciar. El `tmp` vive en el mismo directorio que el destino para que `os.replace` sea atómico (mismo filesystem).

### D7 — API in-process del módulo `agent/baseline.py`
Clase `BaselineEngine(config, master_secret_bytes)` con métodos: `init_scan(watch_paths) -> ScanReport`, `write_entry(path) -> BaselineEntry`, `read_entry(path) -> BaselineEntry | None`, `verify_entry(path) -> bool` (raise `BaselineIntegrityError` en fallo de tag), `add_snapshot(path) -> bool`, `mark_absent(path)`, `list_entries() -> list[str]`. Sin servidor HTTP (D8). El `master_secret` se lee una vez desde `secrets/master_secret` y se pasa al constructor; nunca se loguea (queda cubierto por el sanitizador de `agent/logging.py`).

## Risks / Trade-offs

- **Archivos grandes en el baseline** → el contenido completo cifrado en memoria puede ser costoso para archivos muy grandes. *Mitigación:* el baseline apunta a archivos críticos/config (típicamente pequeños); se documenta un límite de tamaño configurable y los archivos que lo excedan se registran solo por hash+metadata con `content_b64: null` y un flag, sin romper el scan. (Se resuelve en Open Questions con un default.)
- **Listado por escaneo de directorio** → `list_entries` descifra para mapear hash→path. *Mitigación:* aceptable para el volumen de un host; si crece, se puede agregar un índice cifrado más adelante sin cambiar el formato de entrada.
- **Reescritura completa por update** → cada cambio re-cifra toda la entrada (incluye snapshots). *Mitigación:* el costo es proporcional al tamaño del archivo monitoreado, no a todo el baseline; aceptable y mantiene atomicidad y no-reuso de nonce.
- **Pérdida del master_secret** (rotación de cert, reinstalación) → el baseline cifrado se vuelve ilegible. *Mitigación:* fuera de scope de este change; el flujo de rescan (`rescan_baseline`, agent-core) regenera el baseline; documentar que rotar el master_secret invalida el baseline existente.
- **Permisos incorrectos heredados** → si `install.sh` no corrió, el directorio podría no ser `0700`. *Mitigación:* el motor verifica y corrige (`os.chmod`) `baseline/` a `0700` al iniciar, y falla ruidosamente si no puede.

## Open Questions

- **Límite de tamaño por archivo en el baseline**: se propone un default de `max_file_bytes = 10 MiB`; archivos por encima se registran con `content_b64: null` (solo hash+metadata, sin restauración posible) y un flag `oversize: true`. Confirmar el valor con el usuario o cerrarlo en el appendix de decisiones si se quiere un número canónico. **No bloquea la implementación** — se asume 10 MiB salvo indicación contraria.
- **gzip level**: se asume `gzip` nivel 6 (default de stdlib) para snapshots no-activos. Detalle de implementación, no requiere decisión formal.
