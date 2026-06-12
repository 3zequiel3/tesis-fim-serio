## Why

El agente FIM ya arranca, carga config, persiste estado y completa el bootstrap mTLS (Changes 05 y 06), pero todavía no tiene noción de "estado sano" de los archivos que monitorea. Sin un baseline cifrado en disco, el detector fanotify (Change 09) no tiene contra qué comparar, y la restauración automática (Change 10) no tiene de dónde restaurar. Este change construye el motor de baseline: el scan inicial que captura el estado limpio, el cifrado autenticado AES-256-GCM en reposo, y la API interna que el resto del agente usará para leer, verificar y restaurar entradas.

## What Changes

- Nuevo módulo `agent/baseline.py` con el motor de baseline del agente.
- Derivación de clave determinística `HKDF-SHA256(ikm=master_secret, salt=AGENT_ID, info="baseline-v1")` a partir del `master_secret` (32 bytes) entregado en bootstrap (RN-82).
- Cifrado autenticado **AES-256-GCM** de cada entrada de baseline, con nonce de 96 bits único por archivo; la etiqueta GCM provee integridad sin HMAC separado (RN-19, RN-50).
- **Init scan**: en el primer arranque (o cuando se agrega un path sin baseline previo) se recorren los `watch_paths`, se calcula SHA-256 del contenido claro y se persiste el archivo completo cifrado + metadata (RN-15).
- Entradas de baseline con `status: present | absent`; `absent` registra que un archivo NO debe existir, con `hash: null` (RN-66).
- **Snapshots versionados**: máximo 3 por archivo en FIFO; el snapshot no-activo se comprime con gzip antes del cifrado; deduplicación por hash (no se guarda si el hash coincide con el último snapshot) (RN-47, RN-48, RN-49).
- **Verificación al leer**: si el descifrado/autenticación GCM falla (archivo cifrado alterado en disco), se reporta como incidente de integridad en lugar de devolver datos corruptos (RN-19, RN-50).
- Permisos restringidos: archivos cifrados `0600`, directorio `baseline/` `0700`, `master_secret` `0400` (RN-20). Escrituras atómicas (`os.open` + `os.replace`).
- API interna del módulo (sin servidor HTTP, D8) consumible por el detector y el decision engine: `write_entry`, `read_entry`, `verify_entry`, `add_snapshot`, `list_entries`, `mark_absent`.

## Capabilities

### New Capabilities
- `agent-baseline`: motor de baseline del agente FIM — derivación de clave HKDF, cifrado/descifrado AES-256-GCM por entrada, scan inicial, snapshots versionados con gzip y deduplicación, estados present/absent, verificación de integridad al leer y permisos restringidos en disco.

### Modified Capabilities
<!-- Ninguna. agent-core (Change 05) ya declara el directorio baseline/ y sus permisos; este change agrega el motor que lo usa, sin cambiar requisitos existentes de agent-core. -->

## Impact

- **Código nuevo**: `agent/baseline.py` (motor), wiring en `agent/__main__.py` para disparar el init scan tras el bootstrap.
- **Config**: usa `storage.baseline_dir` y `storage.secrets_dir` ya presentes en `AgentConfig`/`StorageConfig` (Change 05/06); sin cambios de schema de config.
- **Dependencias**: `cryptography==44.0.2` ya está en `agent/requirements.txt` (HKDF, AES-GCM); `gzip` y `hashlib` son stdlib. Sin dependencias nuevas.
- **Criptografía**: consume `master_secret` (raw 32 bytes, `0400`) que `agent/bootstrap.py` ya escribe en `secrets/master_secret`.
- **Downstream**: habilita Change 09 (detector fanotify compara contra baseline) y Change 10 (decision engine restaura desde baseline). Co-evoluciona con Change 08 para reportar el incidente de integridad por Valkey, pero este change NO depende de transporte: el reporte de incidente se expone como callback/retorno para que el caller lo publique.
- **Reglas cubiertas**: RN-15, RN-19, RN-20, RN-47, RN-48, RN-49, RN-50, RN-66, RN-82. **Decisiones**: D8 (sin HTTP en agente).
