## Context

**Estado actual — escritura.** `bootstrap_agent` (`backend/app/modules/agents/service.py:53-91`)
genera `shared_secret = secrets.token_bytes(32)` (`:76`), lo persiste como
`agent.shared_secret_hex = shared_secret.hex()` (`:79`) en la misma transacción que nullea
`bootstrap_secret_hash` (`:80-82`) y lo devuelve al agente en `AgentBootstrapResponse`
(`:84-89`). Es el **único** punto de escritura del secreto en `backend/app/`.

**Estado actual — lectura.** Seis sitios reconstruyen los bytes con `bytes.fromhex` directo sobre la
columna, con tres semánticas de error distintas (ver tabla del proposal). La diferencia es
deliberada y está documentada en los docstrings: `agents/streams.py:47-53` y
`actions/streams.py:95-100` dicen que el caller **no** debe capturar la excepción para que la
transacción del outbox se revierta (D37/RN-131); `events/consumer.py:536-547` y
`command_ack_consumer.py:269-277` la convierten en `None` porque un rechazo con NACK necesita
seguir adelante; `heartbeat_consumer.py:119-125` la convierte en log y descarte;
`rules/service.py:186` lleva `# type: ignore[arg-type]` porque la consulta de `:163-165` ya filtra
`shared_secret_hex IS NOT NULL`.

**Estado actual — clave y despliegue.** `cryptography==44.0.2` está fijada
(`backend/requirements.txt:12`) y ya se usa para la PKI (`backend/app/core/pki.py:17-21`).
`certs-init` (`backend/app/core/certs_init.py:69-160`) corre como root, escribe material en tres
volúmenes y fija el dueño por archivo con `_chown` (`:57-66`); el backend corre como uid `10001`
(`certs_init.py:39-43`). `certs-init` importa `app.core.config` transitivamente y por eso recibe
`DATABASE_URL`, `VALKEY_URL` y `JWT_SECRET_CURRENT` sin usarlos (`docker-compose.yml:195-201`):
cualquier validación agregada a `Settings` corre también en `certs-init`. El lifespan
(`backend/app/main.py:78-91`) llama `ensure_ca` → `create_all` → `seed_admin` y después arranca los
consumers (`:138-145`).

**El volumen `backend_certs` no está aislado.** Lo montan `certs-init` (`docker-compose.yml:213`),
`backend` (`:293`) y el contenedor `agent` de laboratorio (`:375`, `:ro`), que corre como root con
`SYS_ADMIN`. Lo mismo en `docker-compose.acceptance-lab.yml:68,94` y
`docker-compose.us02-us20-us31-lab.yml:68,103`. Un archivo `0400` ahí no está «montado sólo en el
backend».

**Revocación.** `AgentStatus.revoked` (`agents/models.py:17`) se consulta en
`events/consumer.py:350`, `heartbeat_consumer.py:114` y `agents/router.py:100`, pero ningún código lo
asigna. Esta change no agrega caché; Change 69 agregará uno con TTL de 5 s sobre `_get_agent_auth`,
consistente con RN-180 («un caché en memoria SHALL tener sólo TTL»).

**Decisión normativa que gobierna esta change** — cerrada, no se re-decide acá: D86/RN-180
(`docs/arquitectura_stack.md:2726`, `docs/reglas_de_negocio.md:2767`), incluida su ampliación del
2026-10-02 (`9e15858`, «Ampliación» de RN-180), que cierra los puntos 1–7 de §Resolved Questions.

## Goals / Non-Goals

**Goals:**

- Que una copia de la base sin el volumen `backend_secrets` no permita firmar como ningún agente ni
  hacia ningún agente.
- Que un valor copiado de la fila de un agente a la de otro no sea utilizable (AAD = `agent_id`).
- Que los seis sitios de lectura pasen por un único helper sin cambiar su semántica de error.
- Que una base existente quede sin secretos en claro tras el primer arranque, sin intervención manual.
- Que un backend sin clave falle al arrancar con un mensaje que diga qué falta y dónde.
- Que la suite existente siga pasando sin reescribir las fixtures que construyen `Agent` con hex.

**Non-Goals:**

- **Rotación de la clave de envoltura.** Límite declarado (RN-180, ampliación 1): el prefijo `v1:`
  queda reservado para una versión futura; no hay re-envoltura con una clave nueva ni convivencia de
  dos claves.
- **Rollback a texto plano.** No se provee (RN-180, ampliación 5): volver a una imagen anterior exige
  re-bootstrap de todos los agentes.
- **Revocación de agentes.** Asignar `AgentStatus.revoked` es otra funcionalidad, fuera del alcance
  de D86.
- **Proteger contra el compromiso del host o del proceso backend.** Quien lee la memoria del backend o
  el volumen `backend_secrets` obtiene la clave; la envoltura mitiga la exfiltración **de la base**
  (volcados, backups, réplicas), no más.
- **Envolver `master_secret`.** El backend no lo persiste (`service.py:77`, sólo viaja en la
  respuesta), así que no hay nada que envolver.
- **Renombrar la columna `shared_secret_hex`.** Sería una migración de esquema y tocaría 21 archivos
  de tests sin ganancia de seguridad.
- **Caché del secreto desenvuelto.** Lo agrega Change 69.

## Decisions

### D-1: Helper en `backend/app/modules/agents/secret_wrap.py`, con excepción que hereda de `ValueError`

Funciones públicas: `wrap_agent_secret(agent_id, secret: bytes) -> str`,
`unwrap_agent_secret(agent_id, stored: str) -> bytes`, `load_wrap_key(path) -> None`,
`ensure_wrap_key_file(path) -> None` (usada por `certs-init`) y
`wrap_legacy_agent_secrets(session) -> int` (la migración). Excepción
`AgentSecretUnwrapError(ValueError)`.

Heredar de `ValueError` es lo que hace que el reemplazo sea mecánico: los tres sitios que hoy
capturan `ValueError` siguen capturando, los tres que propagan siguen propagando. Se descartó una
excepción propia sin herencia: obligaría a tocar los `except` de cuatro módulos y a decidir de nuevo,
en cada uno, una semántica que D37/RN-131 ya fijó.

Se ubica en `modules/agents/` y no en `core/` porque es lógica del dominio del agente (el AAD es el
`agent_id`); `events`, `actions` y `rules` ya importan `app.modules.agents.models`, así que no se
introduce ningún acoplamiento nuevo.

### D-2: Formato `v1:` + base64url sin relleno de `nonce(12) ‖ ciphertext(32) ‖ tag(16)`

`AESGCM(key).encrypt(nonce, secret, agent_id.encode())` devuelve `ciphertext ‖ tag`; se antepone el
nonce. 60 bytes → 80 caracteres base64url; con el prefijo, 83. La columna es `VARCHAR` sin longitud
(`agents/models.py:39`, `str | None` en SQLModel), así que no hace falta migración de esquema.

- **Por qué base64url y no hex:** el hex duplicaría el largo (123 caracteres) sin ganancia; base64url
  no contiene `:`, de modo que el prefijo se separa con un único `split(":", 1)`.
- **Detección del formato:** `stored.startswith("v1:")` → envuelto; sin `:` → hex heredado; con `:` y
  otro prefijo → `AgentSecretUnwrapError`. El alfabeto hex no contiene `:`, así que la detección no es
  ambigua.
- **Validación de salida:** el resultado desenvuelto MUST tener 32 bytes; otro largo es error. El hex
  heredado **no** se restringe a 64 caracteres, para no cambiar el comportamiento de `bytes.fromhex`
  de hoy sobre datos existentes.

### D-3: Clave cargada una vez en el lifespan, antes de tocar la base; nunca en `Settings`

`load_wrap_key(settings.agent_secret_wrap_key_path)` es la **primera** operación con efecto del
lifespan, antes de `ensure_ca` y de `create_all`. Guarda la clave en un estado de módulo; usar el
helper sin clave cargada lanza `RuntimeError` (error de programación, no de datos, por eso **no**
hereda de `ValueError` y no se confunde con una firma inválida).

Causas de falla con nombre estable en el log `backend.agent_secret_wrap_key.invalid`:
`not_configured`, `missing`, `unreadable`, `invalid_length`, `permissive_mode`. El contenido del archivo nunca se loguea.

La validación no va en un `field_validator` de `Settings` porque `certs-init` importa la
configuración (`docker-compose.yml:195-198`) **antes** de que exista la clave que él mismo genera.

Permisos: si `st_mode & 0o177` (más laxo que `0400`/`0600`), el arranque aborta con la causa
`permissive_mode` (RN-180, ampliación 6). `0600` se acepta además de `0400` porque un operador puede
necesitar recrear el archivo a mano; ningún bit de grupo, otros ni ejecución se tolera.

### D-4: Generación sólo en `certs-init`, exclusiva, nunca sobrescribe

`ensure_wrap_key_file(path)`: si no existe → `os.open(path, O_WRONLY | O_CREAT | O_EXCL, 0o400)` +
`secrets.token_bytes(32)` + `_chown(path, 10001, 10001)`; si existe con 32 bytes → no hace nada; si
existe con otro largo → excepción, `certs-init` sale con 1. Se agrega como último paso de
`certs_init.main`, con el mismo patrón `certs_init.step.start/done` y `step="agent_secret_wrap_key"`.

El backend **no** genera la clave aunque falte. Es la diferencia con `ensure_ca`, que sí se llama en
el lifespan: una CA regenerada obliga a re-emitir certificados (recuperable); una clave de envoltura
regenerada vuelve **ilegibles todos** los secretos envueltos (no recuperable sin re-bootstrap de cada
agente). Fallar es la única respuesta segura.

### D-5: Volumen nuevo `backend_secrets`, no `backend_certs`

Ver Context. Se monta en `/secrets` en `certs-init` (rw) y `backend` (`:ro`). La variable lleva
default en el compose, `${AGENT_SECRET_WRAP_KEY_PATH:-/secrets/agent-secret-wrap.key}`, a diferencia
de `CA_KEY_PATH`: la ruta no es secreta ni varía por despliegue, y el default evita que un servidor
ya desplegado con un `.env` anterior a esta change deje de arrancar sólo por la variable faltante.
`prepare_server_env.py` la escribe igual, explícita, para que el `.env` sea autodescriptivo.

RN-180 (ampliación 3) fija que `backend_secrets` lo montan `certs-init` —único generador, que nunca
sobrescribe una clave existente— y el backend; ningún otro servicio.

### D-6: Migración de datos como reconciliación idempotente del lifespan

`wrap_legacy_agent_secrets(session)` corre después de `seed_admin` y antes de crear las tareas de los
consumers: selecciona `Agent` con `shared_secret_hex IS NOT NULL AND shared_secret_hex NOT LIKE 'v1:%'`,
envuelve cada uno con su `agent_id`, y hace **un** `commit`. Log `agents.secret_wrap.migrated` con
`wrapped` y `skipped_invalid`. Una fila con hex inválido se deja intacta y se loguea con su
`agent_id` (`agents.secret_wrap.legacy_invalid`): hoy ya es ilegible para los seis sitios, y abortar
el arranque por ella dejaría sin backend a todos los agentes sanos.

Alternativas descartadas:

- **Migración SQL numerada (`023_…sql`).** PostgreSQL no tiene la clave ni debe tenerla; un
  `pgcrypto` con la clave como parámetro la dejaría en `pg_stat_statements` y en los logs del motor.
- **Script manual (`python -m …`).** Exige un paso del operador que se puede olvidar, y entre el
  despliegue y ese paso los secretos siguen en claro. La reconciliación en el arranque garantiza el
  Done de Change 68 («ningún secreto queda en claro tras la migración») por construcción.
- **Envolver de forma perezosa al leer.** Mezcla escrituras en caminos de lectura (los consumers), y
  un agente inactivo quedaría en claro indefinidamente.

Relación con D84/RN-178 (Change 66, `schema_migrations`): ratificado por RN-180 (ampliación 4), esta
reconciliación **no** es una migración de esquema y no se registra ahí; es idempotente y no cambia la
versión de esquema esperada.

### D-7: Escritura en el bootstrap

`service.py:79` pasa a `agent.shared_secret_hex = wrap_agent_secret(agent.agent_id, shared_secret)`.
La respuesta (`:87`) sigue usando `shared_secret.hex()` en claro. Ninguna otra ruta escribe la
columna.

### D-8: Arnés de tests

`backend/tests/conftest.py` genera una clave de 32 bytes en un archivo temporal de sesión, exporta
`AGENT_SECRET_WRAP_KEY_PATH` en el bloque de `os.environ` existente (`:111-121`) y llama a
`load_wrap_key` antes del primer test, para que los tests que ejercitan consumers o servicios sin
lifespan encuentren la clave cargada. Las 21 fixtures que construyen `Agent(shared_secret_hex=<hex>)`
no se tocan: ejercitan el camino heredado, que es exactamente lo que D86 exige preservar.

## Risks / Trade-offs

- **[Pérdida del volumen `backend_secrets`]** → todos los secretos envueltos quedan ilegibles y
  cada agente deja de autenticar; la recuperación es re-bootstrapear todos los agentes (RN-180,
  ampliación 2). Mitigación: procedimiento operativo de respaldo del volumen, **separado** de
  `pg_data`, en la guía de despliegue.
- **[Backup conjunto de base y clave]** → si el operador guarda `pg_data` y `backend_secrets` en el
  mismo destino, la mitigación desaparece para ese backup. Se declara como límite en la fila STRIDE
  entregada para la Tabla 3 y en el procedimiento de respaldo.
- **[Operador que recrea la clave con `umask` por defecto]** → quedaría `0644` y el backend no
  arrancaría. Es el comportamiento buscado (RN-180, ampliación 6); el log nombra la causa
  `permissive_mode`.
- **[Clave en memoria del proceso]** → aceptado (Non-Goals).
- **[Costo por lectura]** → un AES-GCM sobre 48 bytes por mensaje, del orden de microsegundos frente
  a los ~1,3 ms de `_get_agent_auth` medidos en D75. Change 69 agrega el caché.
- **[Fixtures de tests que asserten el hex en la columna después del bootstrap]** → cambiarán de
  resultado; se buscan con `rg` en la tarea 7.6 y se corrigen al formato `v1:`.
- **[Compose de laboratorio sin `certs-init`]** → su backend dejaría de arrancar. Mitigación: tarea
  6.3 agrega el paso de generación.
- **[Un `NOT LIKE 'v1:%'` con un hex heredado que empiece con `v1:`]** → imposible: el alfabeto hex
  no contiene `v` ni `:`.

## Migration Plan

1. Desplegar la imagen nueva. `certs-init` genera la clave en `backend_secrets` en el primer `up`.
2. El lifespan carga la clave, ejecuta `create_all` y `seed_admin`, y envuelve las filas heredadas
   antes de arrancar los consumers. Los agentes **no** se tocan: siguen firmando con el mismo secreto.
3. Verificar: `SELECT count(*) FROM agents WHERE shared_secret_hex IS NOT NULL AND shared_secret_hex
   NOT LIKE 'v1:%'` devuelve 0 (salvo filas reportadas como `legacy_invalid`).

**Rollback.** No soportado (RN-180, ampliación 5). Una imagen anterior lee la columna con
`bytes.fromhex` y falla sobre `v1:…`; volver a ella exige re-bootstrap de todos los agentes. No se
provee ningún comando que reescriba los secretos en claro: reintroduciría el riesgo que la change
elimina. Se documenta en la guía de despliegue.

## Resolved Questions

Los siete puntos que D86/RN-180 no cubría al diseñar se cerraron en la ampliación de RN-180
(`docs/reglas_de_negocio.md`, commit `9e15858`). No queda ninguna pregunta abierta.

1. **Rotación de la clave** — sin rotación en `v5.0-tesis`; `v1:` reservado; límite declarado.
2. **Pérdida de la clave** — obliga a re-bootstrapear todos los agentes; el respaldo de
   `backend_secrets` se documenta como procedimiento operativo (tarea 8.2).
3. **Fila STRIDE** — no existe tabla STRIDE en `docs/`; la fila se entrega al frente de redacción
   para la Tabla 3 de la tesis (tarea 8.1).
4. **Forma de la migración** — paso idempotente al arrancar, fuera de D84/RN-178; las filas con hex
   inválido se registran y se dejan (D-6).
5. **Rollback** — sin rollback a texto plano; volver a una imagen anterior exige re-bootstrap.
6. **Permisos laxos** — un archivo más laxo que `0400`/`0600` impide el arranque (D-3).
7. **Montaje** — `certs-init` monta `backend_secrets` y es el único generador, sin sobrescribir nunca
   (D-4, D-5).
