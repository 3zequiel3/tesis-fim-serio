## 1. Helper de envoltura (D86/RN-180)

- [ ] 1.1 Crear `backend/app/modules/agents/secret_wrap.py` con `AgentSecretUnwrapError(ValueError)`, el estado de módulo de la clave y las constantes `_PREFIX_V1 = "v1:"`, `_NONCE_LEN = 12`, `_SECRET_LEN = 32`, `_KEY_LEN = 32`. Docstring de módulo que cite D86/RN-180 y explique por qué la excepción hereda de `ValueError` (D-1 del design: preserva la semántica de error de los seis sitios, D37/RN-131).
- [ ] 1.2 Implementar `wrap_agent_secret(agent_id: str, secret: bytes) -> str`: valida `len(secret) == 32`, nonce de `os.urandom(12)`, `AESGCM(key).encrypt(nonce, secret, agent_id.encode("utf-8"))`, devuelve `"v1:" + base64.urlsafe_b64encode(nonce + ct).rstrip(b"=").decode()`.
- [ ] 1.3 Implementar `unwrap_agent_secret(agent_id: str, stored: str) -> bytes` según D-2: `v1:` → decodifica (restituyendo el relleno), separa nonce, descifra con AAD = `agent_id`, valida 32 bytes; sin `:` → `bytes.fromhex(stored)` (camino heredado, sin restringir largo); con `:` y otro prefijo → error. Toda falla (`binascii.Error`, `InvalidTag`, `ValueError` de `fromhex`, largo) se convierte en `AgentSecretUnwrapError` con un mensaje que **no** incluye el valor almacenado ni bytes del secreto.
- [ ] 1.4 Implementar `load_wrap_key(path: str) -> None` según D-3: causas `not_configured` (ruta vacía), `missing`, `unreadable`, `invalid_length` y `permissive_mode` (si `st_mode & 0o177`, es decir, más laxo que `0400`/`0600` — RN-180, ampliación 6); log `error` `backend.agent_secret_wrap_key.invalid` con `path` y `reason` y excepción `RuntimeError` con el mismo texto. Usar el helper sin clave cargada lanza `RuntimeError`, **no** `AgentSecretUnwrapError`.
- [ ] 1.5 Implementar `ensure_wrap_key_file(path: str) -> None` según D-4: crea con `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o400)` y `secrets.token_bytes(32)`; no hace nada si existe con 32 bytes; lanza si existe con otro largo, sin tocarlo. Crear el directorio padre si falta.
- [ ] 1.6 Implementar `wrap_legacy_agent_secrets(session) -> int` según D-6: selecciona `shared_secret_hex IS NOT NULL AND NOT LIKE 'v1:%'`, envuelve cada fila con su `agent_id`, deja intactas y loguea (`agents.secret_wrap.legacy_invalid`, con `agent_id`) las de hex inválido, un solo `commit`, log `info` `agents.secret_wrap.migrated` con `wrapped` y `skipped_invalid`.
- [ ] 1.7 No implementar ninguna función ni entrypoint que reescriba los secretos en claro: el rollback a texto plano no está soportado (RN-180, ampliación 5).
- [ ] 1.8 Verificar que `shared_secret` sigue en la lista de claves redactadas de `backend/app/core/logging.py:39` y que ningún log nuevo de este módulo emite el valor almacenado, la clave ni el secreto.

## 2. Configuración y lifespan

- [ ] 2.1 Agregar `agent_secret_wrap_key_path: str = ""` a `Settings` (`backend/app/core/config.py`, junto al bloque PKI de `:59-63`), **sin** validador: la validación vive en el lifespan (D-3). Comentario que cite D86/RN-180 y explique por qué no se valida acá (`certs-init` importa la configuración antes de que la clave exista).
- [ ] 2.2 En `backend/app/main.py`, llamar `load_wrap_key(settings.agent_secret_wrap_key_path)` como primera operación con efecto del lifespan (`:78`), antes de `init_valkey`, `ensure_ca` y `create_all`.
- [ ] 2.3 En el lifespan, después de `seed_admin()` (`:91`) y antes de crear las tareas de los consumers (`:138`), abrir una `Session(engine)` y llamar `wrap_legacy_agent_secrets(session)`.
- [ ] 2.4 Verificar leyendo el diff el orden final: carga de clave → … → `create_all` → `seed_admin` → migración de datos → consumers.

## 3. Escritura en el bootstrap

- [ ] 3.1 En `backend/app/modules/agents/service.py:79`, reemplazar `shared_secret.hex()` por `wrap_agent_secret(agent.agent_id, shared_secret)`. La respuesta (`:87`) sigue con `shared_secret.hex()` en claro. Comentario citando D86/RN-180.
- [ ] 3.2 Confirmar con `rg -n "shared_secret_hex\s*=" backend/app` que no hay otro punto de escritura de la columna.

## 4. Sitios de lectura — un único helper

- [ ] 4.1 `backend/app/modules/events/consumer.py:541-544` (`_get_agent_auth`): reemplazar `bytes.fromhex(agent.shared_secret_hex)` por `unwrap_agent_secret(agent.agent_id, agent.shared_secret_hex)`; el `except ValueError: secret = None` se conserva.
- [ ] 4.2 `backend/app/modules/agents/command_ack_consumer.py:272-275` (`_get_shared_secret`): idem, conservando `except ValueError: return None`.
- [ ] 4.3 `backend/app/modules/agents/streams.py:54-56` (`_get_agent_secret`): idem, **sin** agregar `try`: la excepción debe seguir propagándose (D37/RN-131, docstring `:47-53`).
- [ ] 4.4 `backend/app/modules/actions/streams.py:106-108` (`_get_agent_secret`): idem, sin `try`.
- [ ] 4.5 `backend/app/modules/agents/heartbeat_consumer.py:119-123`: idem, conservando el `except ValueError` con su log y `return`. Conservar el nombre del log `heartbeat_consumer.invalid_secret_hex` (o renombrarlo a uno neutro y actualizar los tests que lo asserten; decidir leyendo los tests).
- [ ] 4.6 `backend/app/modules/rules/service.py:186` (`publish_rule_sync`): idem; quitar el `# type: ignore[arg-type]` si el tipo lo permite (la consulta de `:163-165` ya filtra nulos).
- [ ] 4.7 Verificar con `rg -n "fromhex" backend/app` que la única aplicación de `bytes.fromhex` sobre `shared_secret_hex` está en `secret_wrap.py`. Cualquier otra ocurrencia sobre otra columna se deja.

## 5. `certs-init` — generación de la clave

- [ ] 5.1 En `backend/app/core/certs_init.py`, agregar el paso `agent_secret_wrap_key` al final de `main()`, dentro del mismo `try`: leer `AGENT_SECRET_WRAP_KEY_PATH` (default `/secrets/agent-secret-wrap.key`), llamar `ensure_wrap_key_file`, `_chown(path, _BACKEND_UID, _BACKEND_GID)`, logs `certs_init.step.start/done`.
- [ ] 5.2 Actualizar el docstring de módulo de `certs_init.py` (`:1-19`) para nombrar el cuarto volumen (`backend_secrets`) y el paso nuevo.

## 6. Compose, scripts y entorno

- [ ] 6.1 `docker-compose.yml`: declarar el volumen `backend_secrets` (con comentario D86/RN-180 explicando por qué no es `backend_certs`: lo monta el `agent` de laboratorio en `:375`); montarlo en `certs-init` como `backend_secrets:/secrets` y en `backend` como `backend_secrets:/secrets:ro`; agregar `AGENT_SECRET_WRAP_KEY_PATH: ${AGENT_SECRET_WRAP_KEY_PATH:-/secrets/agent-secret-wrap.key}` al `environment` de ambos.
- [ ] 6.2 Verificar que ningún otro servicio de `docker-compose.yml` ni de `docker-compose.tls.yml` monta `backend_secrets` (`docker compose --profile app --profile lab config` y buscar el volumen).
- [ ] 6.3 `docker-compose.acceptance-lab.yml` y `docker-compose.us02-us20-us31-lab.yml`: sus `backend` corren sin `certs-init`. Agregar el volumen `backend_secrets`, montarlo en su `backend` y proveer la generación previa: un servicio one-shot con la imagen del backend que ejecute `ensure_wrap_key_file` (por ejemplo `python -c` o un `python -m` dedicado) con `depends_on: condition: service_completed_successfully`. El `agent` de esos compose **no** lo monta.
- [ ] 6.4 `scripts/prepare_server_env.py`: escribir `AGENT_SECRET_WRAP_KEY_PATH=/secrets/agent-secret-wrap.key` junto a las rutas de certificados en `render_env`, y mencionarla en la sección «QUÉ ESCRIBE» del docstring de módulo. El script **no** genera la clave.
- [ ] 6.5 `.env.example`: documentar `AGENT_SECRET_WRAP_KEY_PATH` con su valor canónico y un comentario que diga que el archivo lo genera `certs-init`, que perderlo invalida todos los agentes y que se respalda separado de `pg_data`.

## 7. Tests

- [ ] 7.1 Arnés: en `backend/tests/conftest.py`, generar una clave de 32 bytes en un archivo temporal de sesión, exportar `AGENT_SECRET_WRAP_KEY_PATH` en el bloque de `os.environ` (`:111-121`) y llamar `load_wrap_key` antes del primer test (D-8). No editar las 21 fixtures que construyen `Agent(shared_secret_hex=<hex>)`.
- [ ] 7.2 Tests unitarios de `secret_wrap` (`backend/tests/test_agent_secret_wrap.py`): ida y vuelta; dos envolturas del mismo secreto difieren; AAD distinto → `AgentSecretUnwrapError`; payload alterado → error; prefijo `v2:` → error; hex heredado de 64 caracteres → 32 bytes; hex heredado inválido → error; la excepción es instancia de `ValueError`; el mensaje no contiene el valor almacenado; helper sin clave cargada → `RuntimeError`.
- [ ] 7.3 **Secreto no queda en claro en la base:** bootstrap completo contra la base de test; leer `agents.shared_secret_hex` con SQL crudo; assertar prefijo `v1:`, que no contiene el `shared_secret_hex` de la respuesta y que el helper lo desenvuelve a los mismos bytes.
- [ ] 7.4 **El hex heredado sigue verificando:** agente con `shared_secret_hex` en hex plano; un evento, un heartbeat y un ACK de comando firmados con ese secreto verifican por los caminos reales de `events/consumer.py`, `heartbeat_consumer.py` y `command_ack_consumer.py`; un `rule_sync` y un `baseline_update` se firman sin error.
- [ ] 7.5 **La migración envuelve las filas existentes:** tres agentes con hex heredado, uno con `NULL`, uno con hex inválido; correr `wrap_legacy_agent_secrets`; assertar tres `v1:` que desenvuelven al secreto original, el `NULL` intacto, la fila inválida intacta con su log de error, `wrapped == 3`; segunda corrida → `wrapped == 0` y ningún valor cambia.
- [ ] 7.6 Buscar con `rg -n "shared_secret_hex" backend/tests` los tests que asserten el valor de la columna **después** de un bootstrap (p. ej. `test_bootstrap_tls_listener.py`) y adaptarlos al formato `v1:` vía el helper. Los que sólo la siembran con hex no se tocan.
- [ ] 7.7 **Falta la clave → el arranque falla claramente:** con `AGENT_SECRET_WRAP_KEY_PATH` apuntando a un archivo inexistente, a uno de 31 bytes y vacío, entrar al lifespan (`with TestClient(app)`) levanta `RuntimeError` antes de `create_all` (verificar con un spy o monkeypatch que `create_all` no se llamó) y el log contiene `backend.agent_secret_wrap_key.invalid` con la ruta y la causa (`missing`, `invalid_length`, `not_configured`). Usar la neutralización de listeners de D78 ya presente en el arnés.
- [ ] 7.8 **Permisos laxos impiden el arranque:** archivo de clave de 32 bytes con modo `0640` y `0644` → el lifespan levanta `RuntimeError` antes de `create_all` con causa `permissive_mode`; con `0400` y `0600` → arranca.
- [ ] 7.9 Importar `app.core.config` sin archivo de clave no falla (guarda de la restricción de D-3).
- [ ] 7.10 `certs-init`: `ensure_wrap_key_file` crea 32 bytes con modo `0400`; segunda llamada deja el archivo byte a byte idéntico; archivo existente de otro largo → excepción y archivo sin modificar; `certs_init.main()` con el paso fallando devuelve 1.
- [ ] 7.11 Bootstrap: el escenario nuevo de `backend-agents` («El secreto se persiste envuelto»).
- [ ] 7.12 `scripts/tests/test_prepare_server_env.py`: el `.env` generado contiene `AGENT_SECRET_WRAP_KEY_PATH=/secrets/agent-secret-wrap.key`.

## 8. Documentación (sólo en apply)

- [ ] 8.1 Redactar la fila STRIDE de divulgación de información del secreto compartido del agente —amenaza (exfiltración de la base permite firmar como cualquier agente y hacia cualquier agente), mitigación (AES-256-GCM con AAD = `agent_id`, clave fuera de la base en `backend_secrets`, D86/RN-180) y límites declarados (no protege contra compromiso del host ni contra un backup conjunto de base y clave; sin rotación de clave; sin revocación de agente)— y **entregarla al frente de redacción para la Tabla 3 de la tesis** (RN-180, ampliación 7). No crear una tabla STRIDE en `docs/` ni editar el documento de tesis desde esta change; dejar constancia de la entrega en el reporte de apply.
- [ ] 8.2 En la guía de despliegue de producto (spec `remote-deployment`), documentar el volumen `backend_secrets` como procedimiento operativo: qué contiene, que se respalda **separado** de `pg_data`, que su pérdida obliga a re-bootstrapear todos los agentes (RN-180, ampliación 2), que la rotación no está soportada (ampliación 1) y que volver a una imagen anterior exige re-bootstrap (ampliación 5).
- [ ] 8.3 No editar `CHANGES.md` ni los docs canónicos: las decisiones ya están cerradas en RN-180/D86 (`9e15858`).

## 9. Verificación

- [ ] 9.1 Suite completa del backend en verde (`pytest` desde `backend/`), con conteo de tests antes y después.
- [ ] 9.2 Suite de `scripts/tests/` en verde.
- [ ] 9.3 `docker compose --profile app up` sobre volúmenes vacíos: `certs-init` termina con 0, el archivo de clave existe con `0400` y dueño `10001`, el backend arranca; segundo `up` no cambia el archivo (comparar `sha256sum`).
- [ ] 9.4 Sobre una base con agentes ya bootstrapeados con la imagen anterior: tras el `up`, `SELECT count(*) FROM agents WHERE shared_secret_hex IS NOT NULL AND shared_secret_hex NOT LIKE 'v1:%'` devuelve 0, y el agente sigue publicando eventos y heartbeats sin re-bootstrap.
- [ ] 9.5 `python3 scripts/check_spec_integrity.py` pasa.
- [ ] 9.6 `openspec validate agent-secret-wrap-at-rest --strict` pasa.
