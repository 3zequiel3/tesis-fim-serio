## Why

El secreto HMAC que autentica cada mensaje entre el backend y un agente —eventos, heartbeats, ACKs y
comandos firmados— se guarda **en claro** en la base. `Agent.shared_secret_hex`
(`backend/app/modules/agents/models.py:39`) es un `str` sin protección alguna; `bootstrap_agent` lo
escribe como `shared_secret.hex()` (`backend/app/modules/agents/service.py:79`) y seis sitios lo
reconstruyen con `bytes.fromhex` directo sobre la columna:

| Sitio | Líneas | Semántica de error actual |
|---|---|---|
| `backend/app/modules/events/consumer.py` (`_get_agent_auth`) | `:541-544` | `ValueError` → `secret = None` |
| `backend/app/modules/agents/command_ack_consumer.py` (`_get_shared_secret`) | `:272-275` | `ValueError` → `None` |
| `backend/app/modules/agents/streams.py` (`_get_agent_secret`) | `:54-56` | se propaga (revierte la transacción, D37/RN-131) |
| `backend/app/modules/actions/streams.py` (`_get_agent_secret`) | `:106-108` | se propaga (revierte la transacción, D37/RN-131) |
| `backend/app/modules/agents/heartbeat_consumer.py` | `:119-123` | `ValueError` → log `invalid_secret_hex` y descarte |
| `backend/app/modules/rules/service.py` (`publish_rule_sync`) | `:186` | se propaga |

Quien obtiene una copia de la base —un volcado de `pg_dump`, un backup, una réplica de lectura, un
volumen `pg_data` extraído— obtiene la capacidad de **firmar como cualquier agente** y de **firmar
comandos hacia cualquier agente** (`rule_sync`, `baseline_update`, restauraciones), sin tocar el
backend ni la PKI. El riesgo no figura en la tabla STRIDE de la tesis. Y no hay mitigación por
revocación: `AgentStatus.revoked` (`models.py:17`) existe en el enum y se consulta
(`events/consumer.py:350`, `heartbeat_consumer.py:114`, `agents/router.py:100`), pero **ningún
código lo asigna**, de modo que un secreto filtrado no tiene forma de invalidarse desde el producto.

Origen: guía de laboratorio de la tesis v29 (ítems L-2…L-9), verificada contra `devel` `b3751b8`;
base para el candidato `v5.0-tesis`. La decisión que gobierna esta change ya está cerrada:
**D86/RN-180** (`docs/arquitectura_stack.md:2726`, `docs/reglas_de_negocio.md:2767`), con su
ampliación del 2026-10-02 (`9e15858`), que cierra los siete puntos que surgieron al diseñarla:
sin rotación de clave, pérdida de clave ⇒ re-bootstrap, volumen `backend_secrets` propio, migración
al arrancar fuera de D84/RN-178, sin rollback a texto plano, permisos laxos impiden el arranque y la
fila STRIDE se entrega a la Tabla 3 de la tesis. No queda ninguna suposición abierta.

## What Changes

- **Envoltura AES-GCM en reposo (D86/RN-180).** El valor persistido pasa a `v1:<base64url(nonce ‖
  ciphertext ‖ tag)>`, cifrado con AES-256-GCM, nonce aleatorio de 12 bytes por escritura y
  **AAD = `agent_id`**: un valor copiado de la fila de un agente a la de otro no descifra. Se usa
  `cryptography==44.0.2`, ya fijada en `backend/requirements.txt:12`; no se agrega dependencia.
- **Clave de envoltura fuera de la base.** Archivo de 32 bytes aleatorios generado por `certs-init`
  (idempotente: crea si falta, **nunca** sobrescribe), modo `0400`, dueño `10001`, en un volumen
  nombrado **nuevo** (`backend_secrets`) montado sólo en `certs-init` (escritura) y `backend` (sólo
  lectura). No va en `backend_certs` porque ese volumen se monta también en el contenedor de agente
  de laboratorio (`docker-compose.yml:375`, `docker-compose.acceptance-lab.yml:94`,
  `docker-compose.us02-us20-us31-lab.yml:103`), lo que violaría «montado sólo en el backend».
- **Un único helper de lectura.** `unwrap_agent_secret(agent_id, stored) -> bytes` reemplaza los seis
  `bytes.fromhex`. Su excepción hereda de `ValueError`, así que **ninguno de los seis sitios cambia
  su semántica de error**: los que hoy capturan siguen capturando, los que hoy propagan siguen
  propagando.
- **El hex heredado sigue siendo legible.** Un valor sin prefijo se interpreta como hex, igual que
  hoy; un prefijo desconocido falla cerrado.
- **Migración de datos.** Una reconciliación idempotente del lifespan envuelve toda fila con
  `shared_secret_hex` no nulo y sin prefijo `v1:`, en una sola transacción, antes de arrancar los
  consumers. Tras el primer arranque no queda ningún secreto en claro.
- **El arranque falla de forma explícita sin clave.** Sin `AGENT_SECRET_WRAP_KEY_PATH`, con el
  archivo ausente, ilegible, de longitud distinta de 32 bytes o con permisos más laxos que
  `0400`/`0600`, el lifespan aborta con un log que
  nombra la ruta y la causa, antes de tocar la base. La validación **no** vive en `Settings`, porque
  `certs-init` importa `app.core.config` (`backend/app/core/certs_init.py`) y fallaría antes de
  poder generar la clave.
- **`prepare_server_env.py`** escribe `AGENT_SECRET_WRAP_KEY_PATH` con su valor canónico, junto a las
  demás rutas.
- **Tabla STRIDE.** No existe tabla STRIDE en `docs/`: la fila de divulgación del secreto compartido
  se redacta y se entrega al frente de redacción para la Tabla 3 de la tesis (D86/RN-180,
  ampliación 7).
- **Límites declarados.** Sin rotación de la clave (el prefijo `v1:` queda reservado); la pérdida de
  la clave obliga a re-bootstrapear todos los agentes; no hay rollback a una imagen anterior sin
  re-bootstrap.

**BREAKING (operativo, no de contrato):** el backend deja de arrancar sin el archivo de clave.
`certs-init` lo genera en el primer `up`, así que el despliegue estándar no requiere acción manual;
los compose de laboratorio que no usan `certs-init` necesitan el paso equivalente (tarea 6.3). El
contrato de la API no cambia: `AgentBootstrapResponse.shared_secret_hex`
(`agents/models.py:103`) sigue devolviendo el hex en claro al agente, por TLS (D52/RN-146).

## Capabilities

### New Capabilities

- `agent-secret-at-rest`: formato envuelto del secreto compartido, clave de envoltura (carga,
  validación, falla de arranque, generación), helper único de lectura, compatibilidad con el hex
  heredado y migración de datos.

### Modified Capabilities

- `backend-agents`: el bootstrap persiste el secreto compartido envuelto, nunca en claro; la
  respuesta al agente no cambia.
- `infra-compose`: `certs-init` genera además la clave de envoltura en el volumen `backend_secrets`,
  montado sólo en `certs-init` y `backend`.
- `remote-deployment`: el script de preparación escribe `AGENT_SECRET_WRAP_KEY_PATH`.

## Impact

**Backend** — módulo nuevo `backend/app/modules/agents/secret_wrap.py` (wrap, unwrap, carga de clave,
migración); `backend/app/modules/agents/service.py:79`; los seis sitios de lectura de la tabla de
arriba; `backend/app/main.py` (lifespan: carga de clave y migración);
`backend/app/core/config.py` (setting `agent_secret_wrap_key_path`);
`backend/app/core/certs_init.py` (generación de la clave).

**Base de datos** — sin migración de esquema: la columna sigue siendo `shared_secret_hex`
(`VARCHAR`), sólo cambia el contenido. El nombre de la columna queda engañoso; renombrarla es
alcance de otra change.

**Infraestructura** — `docker-compose.yml` (volumen `backend_secrets`, montajes en `certs-init` y
`backend`, variable `AGENT_SECRET_WRAP_KEY_PATH`), `docker-compose.acceptance-lab.yml`,
`docker-compose.us02-us20-us31-lab.yml`, `scripts/prepare_server_env.py`, `.env.example`.

**Tests** — 21 archivos de `backend/tests/` construyen `Agent(shared_secret_hex=<hex>)` directo. La
compatibilidad con el hex heredado los mantiene válidos sin editarlos; el arnés
(`backend/tests/conftest.py`) necesita una clave de prueba inicializada antes del primer uso del
helper.

**Dependencias del DAG** — ninguna previa. Change 69 (`ingest-drain-resilience-and-throughput`)
depende de ésta: su caché de `_get_agent_auth` con TTL de 5 s usa el helper.

**Resultados de la tesis** — re-medición única sobre `v5.0-tesis` (ver Change 61). Esta change no
debería mover la ingesta de forma medible (un AES-GCM de 48 bytes por lectura), pero no se declara
mejora ni neutralidad anticipada.
