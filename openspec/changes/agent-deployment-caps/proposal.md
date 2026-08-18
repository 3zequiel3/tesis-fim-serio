## Why

Las acciones automáticas de remediación del agente — `auto_restore` y `quarantine`, RN-30 a RN-37 — son **físicamente inejecutables** en el despliegue que el repo entrega. No es un fallo intermitente: falla el 100% de las veces sobre los `watch_paths` por defecto documentados (`/etc`, `/bin`, `/sbin`, `/usr/bin`, `/usr/sbin`, `agent/deploy/config.yaml.example:42-47`). El decision engine, que es la contribución central de la tesis, no puede completar una sola acción en un host real.

Hay **dos barreras independientes**, y levantar una no levanta la otra:

1. **Mount de solo-lectura.** `ProtectSystem=strict` (`agent/deploy/fim-agent.service:22`) remonta la jerarquía del sistema como solo-lectura para el servicio, salvo lo declarado en `ReadWritePaths`, que hoy lista únicamente `/var/lib/fim-agent /var/log/fim-agent` (`:25`). Ninguno de los `watch_paths` está adentro. **Ninguna capability atraviesa un mount de solo-lectura**: la escritura falla con `EROFS` con total independencia de los privilegios del proceso.
2. **Chequeo DAC.** El servicio corre como `User=fim-agent` con `AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH` (`:18-19`). `CAP_DAC_READ_SEARCH` habilita lectura y búsqueda, no escritura, y `CAP_SYS_ADMIN` **no exime de los chequeos DAC**. Reemplazar un archivo cuyo dueño es `root` requiere `CAP_DAC_OVERRIDE`; restaurar modo y propiedad desde el baseline requiere además `CAP_FOWNER` y `CAP_CHOWN`.

Los puntos de escritura que hoy fallan son concretos: `agent/decision.py:172-176` (`open(tmp,"wb")` + `os.replace`), `agent/decision.py:194` (`shutil.move` a cuarentena), `agent/commands.py:336-338` y `:422` (los handlers manuales `restore_file` / `quarantine_file`), y `agent/commands.py:514-525`, donde `update_config` reescribe `/etc/fim-agent/config.yaml` y **el fallo solo se loguea como warning** (`:526-527`): el ack sigue reportando `ok=true` y la configuración en caliente revierte silenciosamente al reiniciar.

Y el unit tal como se entrega **tampoco puede arrancar en una instalación limpia**: no declara `EnvironmentFile=` ni `Environment=`, pero `agent/__main__.py:150-157` exige `FIM_BOOTSTRAP_SECRET` en el primer arranque y hace `sys.exit(1)` si falta. Con `Restart=on-failure` (`:28`), una instalación nueva entra en un loop de reinicios sin diagnóstico útil.

Por último, `agent/install.sh:73-78` hace `chown -R fim-agent:fim-agent` sobre `/opt/fim-agent` y `/etc/fim-agent`: el usuario del servicio es dueño de su propio código mientras sostiene `CAP_SYS_ADMIN`. Cualquiera que obtenga ese uid reescribe el agente y recibe privilegio equivalente a root en el siguiente reinicio.

D36 / RN-130 se cerró el 2026-08-14 en el appendix "Decisiones de implementación — Abril 2026" de [reglas_de_negocio.md](../../../docs/reglas_de_negocio.md) (líneas 1165-1185) y fija el contrato que esta change implementa, incluidas las opciones descartadas.

## What Changes

- **Capabilities**: `AmbientCapabilities` y `CapabilityBoundingSet` incorporan `CAP_DAC_OVERRIDE`, `CAP_FOWNER` y `CAP_CHOWN`. La expansión marginal de privilegio es baja — el servicio ya tiene `CAP_SYS_ADMIN`, equivalente a root en la práctica.
- **`ProtectSystem=strict` se conserva**, con `ReadWritePaths` **derivado**: `install.sh` lee los `watch_paths` de `/etc/fim-agent/config.yaml` y emite un drop-in en `/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf`, dejando el unit base sin editar. El drop-in incluye siempre `/etc/fim-agent`, porque `update_config` persiste ahí y esa escritura no depende de que el operador haya elegido monitorear `/etc`.
- **Preflight de escritura** al arrancar y en cada `update_config`, con vocabulario cerrado de resultado (`writable`, `read_only_mount`, `permission_denied`, `missing`). Un path no escribible **no detiene al agente ni interrumpe el monitoreo**: se marca solo-detección, se loguea y se reporta en el heartbeat. La detección es la función primaria; la remediación es una capacidad adicional que puede faltar sin invalidar el servicio. El preflight es no invasivo (`statvfs` + `access`), sin escribir archivos sonda dentro de un `watch_path` — eso generaría eventos fanotify del propio agente.
- **Causa de fallo distinguible**: `_ActionFailed` gana un vocabulario estable de razones y esa razón viaja en el payload del evento (`action_error`), se persiste en una columna nueva `Event.action_error` y se expone en la UI. Hoy la razón muere en el journal del host (`agent/decision.py:84`) y el backend solo ve un booleano. Compone con `Event.action_failed` (D35/RN-129, C40) sin alterarlo.
- **La restauración preserva modo, uid y gid** desde la entry del baseline. `agent/baseline.py:293-295` ya los guarda y **nadie los lee nunca** (`os.chown` no aparece en todo el agente). Sin esto, habilitar las capabilities convierte un feature roto en una **vulnerabilidad**: un `auto_restore` "exitoso" dejaría `/usr/bin/<binario>` con dueño `fim-agent` y modo por umask, entregando a ese uid la capacidad de reescribir un binario del sistema. Si la entry no trae metadata, la restauración **no se completa**.
- **`install.sh` deja de darle al usuario del servicio la propiedad de su código**: `/opt/fim-agent` y `/etc/fim-agent` quedan `root`, legibles por el grupo `fim-agent`; solo `/var/lib/fim-agent` y `/var/log/fim-agent` pertenecen al usuario del servicio.
- **`EnvironmentFile=-/etc/fim-agent/env`** (con guion, tolerante a ausencia — el secreto de bootstrap es de un solo uso y se borra después) y un código de salida de configuración dedicado (`78`) más `RestartPreventExitStatus=78`, para que una instalación mal configurada falle una vez con un mensaje claro en lugar de girar en el loop de `Restart=on-failure`.
- **Documentación canónica**: se corrigen RN-51 (`docs/reglas_de_negocio.md:378-382`), el unit de ejemplo de `docs/arquitectura_stack.md:183-209`, la fila de limitaciones técnicas de `docs/flujo_de_usuario.md:790`, y la sección de despliegue de `docs/operations.md:153-227`, que además está desfasada por otros tres motivos: documenta `pyfanotify` (el agente usa un backend propio sobre syscalls crudas, `agent/_fanotify.py`, ver `agent/requirements.txt`), `User=root`, `ProtectSystem=full` y un `ExecStart ... -m agent.bootstrap.main` que no existe.

## Capabilities

### New Capabilities

- `agent-deployment`: contrato del despliegue systemd nativo — capabilities requeridas y su justificación, `ProtectSystem=strict` con `ReadWritePaths` derivado por drop-in, `EnvironmentFile`, política de reinicio con código de salida de configuración, y las reglas de propiedad y permisos que `install.sh` debe aplicar.
- `agent-write-preflight`: verificación de capacidad de escritura por `watch_path` al arrancar y en cada recarga de configuración; vocabulario de clasificación; degradación a solo-detección sin interrumpir el monitoreo; reporte en el heartbeat.

### Modified Capabilities

- `agent-decision-engine`: `_auto_restore` restaura modo/uid/gid desde la entry del baseline antes de publicar el archivo en su path final, y falla si esa metadata falta; las razones de `_ActionFailed` pasan a un vocabulario cerrado que distingue barrera de despliegue (`read_only_mount`, `permission_denied`) de problema de datos (`no_baseline_content`, `no_restorable_content`), y esa razón viaja en el payload del evento.
- `agent-config-commands`: `update_config` reejecuta el preflight sobre el nuevo conjunto de paths y deja de tragarse en silencio el fallo de persistencia de `config.yaml`.
- `backend-event-consumer`: la ingesta persiste `action_error` del payload con tolerancia hacia adelante (valor desconocido se guarda tal cual, no invalida el evento).
- `backend-events-api`: `Event` gana la columna `action_error: str | None` con migración idempotente; `EventOut` la expone.
- `backend-agent-management`: el consumer de heartbeat persiste el estado de escritura por `watch_path` en el modelo `Agent`; `GET /agents` y `GET /agents/{id}` lo exponen.
- `frontend-agents`: la lista de `watch_paths` de `AgentCard` distingue un path remediable de uno solo-detección, con la causa.
- `frontend-events`: el detalle del evento muestra la causa del fallo de remediación en prosa, calificando al indicador de `action_failed` que introdujo C40.

## Impact

- **Despliegue (agente)**: `agent/deploy/fim-agent.service` (capabilities, `EnvironmentFile`, `RestartPreventExitStatus`), `agent/install.sh` (propiedad, generación del drop-in, reordenamiento de `daemon-reload`), nuevo `agent/deploy/env.example`.
- **Agente (código)**: nuevo `agent/preflight.py` (clasificación pura e inyectable), nuevo `agent/deployment.py` (render del drop-in + entrypoint `-m`), `agent/decision.py` (restauración de metadata, vocabulario de razones, `payload["action_error"]`), `agent/commands.py` (preflight en `update_config`, fallo de persistencia visible; los handlers manuales heredan el mapeo de errno), `agent/heartbeat.py` (clave `watch_path_status`), `agent/__main__.py` (preflight en el arranque, código de salida 78).
- **Backend**: `backend/app/modules/events/models.py` + `router.py` + `service.py` (`action_error`), `backend/app/modules/agents/models.py` + `heartbeat_consumer.py` + `service.py` (`watch_path_status`, columna JSON siguiendo el precedente de `Agent.watch_paths`), migraciones `008_add_event_action_error.sql` y `009_add_agent_watch_path_status.sql` en `backend/db/migrations/` (D3, sin Alembic, aplicación manual por `psql`).
- **Frontend**: `frontend/src/api/agents.ts`, `frontend/src/components/ui/AgentCard.tsx`, `frontend/src/api/events.ts`, `frontend/src/pages/EventDetail.tsx`, y mappers puros nuevos siguiendo el patrón de `frontend/src/utils/ackStatus.ts`.
- **Docs**: `docs/reglas_de_negocio.md` (RN-51), `docs/arquitectura_stack.md`, `docs/flujo_de_usuario.md`, `docs/operations.md`.
- **Migración de BD**: sí, dos, aditivas y nullable. Sin breaking change de API HTTP.
- **Dependencias del DAG**: 40 (`event-status-contract`) — esta change compone con `Event.action_failed` y numera sus migraciones a partir de la `007`.
- **Reglas cubiertas**: RN-30 a RN-37, RN-51, RN-71, RN-92, RN-93, RN-108, RN-116, RN-130. **Decisiones aplicadas**: D36 (D3 para la convención de migración, D35 como base sobre la que compone, D18 como límite de containment que no se amplía).
- **Roadmap**: change 41 en [CHANGES.md](../../../CHANGES.md).
- **Verificación residual manual**: hay partes que **no se pueden probar sin root ni sin systemd** — que las ambient capabilities se otorguen, que `statvfs` reporte `ST_RDONLY` dentro del namespace de `ProtectSystem=strict`, que `os.chown` funcione, y el `install.sh` de punta a punta. Esas se nombran explícitamente como checklist de verificación en host real en `tasks.md` en lugar de taparse con un mock que siempre pasa.

**Fuera de scope** (no traerlos acá):

- La derivación `event_type`/`status`, ya resuelta en `event-status-contract`.
- Durabilidad de ack/outbox del stream, n8n, tooling de migraciones, hardening de auth, el barrido de integridad, `FAN_ATTRIB`, el trabajo de `O_NOFOLLOW`.
- **Follow-ups identificados pero no implementados** (deben abrir su propia change):
  - `agent/decision.py:184-186` verifica el hash **del buffer en memoria** (`_hash_bytes(content)`) contra el hash esperado del mismo buffer, no relee el archivo del disco. Es una tautología: siempre pasa. Una verificación post-restauración real tendría que releer el path.
  - Las dos implementaciones de cuarentena divergen: `agent/decision.py:188-199` no aplica `chmod` y nombra el destino `{event_id}_{basename}`; `agent/commands.py:412-428` aplica `0400` y nombra `{basename}.{timestamp}`.
  - `agent/install.sh:50` hace `cp -r "${AGENT_SRC}" "${AGENT_DEST}/agent"`, que en una segunda ejecución anida `/opt/fim-agent/agent/agent` en lugar de sobrescribir — el script se declara idempotente y en ese punto no lo es.
