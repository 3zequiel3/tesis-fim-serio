## Context

El agente se despliega como servicio systemd nativo (RN-108: no puede correr en un contenedor porque `fanotify` requiere `CAP_SYS_ADMIN`). El unit que el repo entrega está en `agent/deploy/fim-agent.service` y lo instala `agent/install.sh`. Los hechos verificados que enmarcan el diseño:

- `fim-agent.service:18-19` — `AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH`, idéntico `CapabilityBoundingSet`.
- `fim-agent.service:22,25` — `ProtectSystem=strict` con `ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent`.
- `config.yaml.example:42-47` — `watch_paths` por defecto: `/etc`, `/bin`, `/sbin`, `/usr/bin`, `/usr/sbin`. Ninguno está en `ReadWritePaths`.
- Sitios de escritura que fallan: `decision.py:172-176` (`open(tmp,"wb")` + `os.replace`), `decision.py:194` (`shutil.move`), `commands.py:336-338` y `:422` (handlers manuales), `commands.py:514-525` (`update_config` reescribiendo `/etc/fim-agent/config.yaml`).
- `decision.py:79-84` — ante `_ActionFailed`, el payload publicado recibe **solo** `action_failed = True`; la razón (`exc.error`) va exclusivamente al journal local vía `mark_failed`. El backend nunca la ve.
- `baseline.py:293-295` — la entry guarda `mode` (string `oct(S_IMODE)`), `uid` y `gid`. **Nadie los lee jamás**: `os.chown` no aparece en ningún archivo de `agent/`, y `baseline.py:572-573` solo los arrastra a la entry siguiente.
- `install.sh:73-78` — `chown -R fim-agent:fim-agent` sobre `/var/lib/fim-agent`, `/var/log/fim-agent`, `/etc/fim-agent` y `/opt/fim-agent`.
- `__main__.py:150-157` — sin certificado válido exige `FIM_BOOTSTRAP_SECRET` y hace `sys.exit(1)`. El unit no declara `EnvironmentFile=` ni `Environment=`, y tiene `Restart=on-failure` (`:28`).
- `commands.py:526-527` — el fallo al persistir `config.yaml` es un `log.warning` mudo; el ack sigue siendo `ok=true` y `config.watch_paths` en memoria se actualiza igual (`:530`), así que el estado persistido diverge del runtime en silencio.
- `heartbeat.py:78-94` — el payload lleva 10 claves. `streams.py:19-22` (`canonical_json`) firma **todas** las claves salvo `signature`, ordenadas: agregar una clave es seguro para la firma.
- `heartbeat_consumer.py:66-109` — sin schema ni allowlist; lee `agent_id`, `queue_pressure` y `shutdown` e ignora el resto. `Agent.watch_paths` ya es `sa_column=Column(JSON)` (`agents/models.py:27`): el precedente de columna JSON existe en el mismo modelo.
- `agents/service.py:103-111` — `_agent_to_response` es el único punto de serialización, usado por `list_agents` y `get_agent`.
- `AgentCard.tsx:178-182` — los `watch_paths` se renderizan como una lista plana de strings, sin ningún indicador por path.

Restricciones normativas:

- **D36 / RN-130** (`docs/reglas_de_negocio.md:1165-1185`) fija el contrato completo, incluidas las alternativas descartadas (`ProtectSystem=full`). Este diseño lo implementa; no lo reinterpreta ni relitiga sus rechazos.
- **D3 — sin Alembic**: migraciones SQL crudo idempotente en `backend/db/migrations/`, numeradas `NNN_descripcion.sql`, aplicadas a mano con `psql`. La última es `007_add_event_action_failed.sql`.
- **D35 / RN-129** (C40) ya introdujo `Event.action_failed`; esta change compone con él, no lo toca.
- **D18 / RN-116**: la remediación fuera de todo `watch_path` sigue prohibida. Esta change no amplía el containment.
- **RN-71**: snake_case minúsculas para todo valor de estado en código, schemas, JSON y logs.

## Goals / Non-Goals

**Goals:**

- Que `auto_restore` y `quarantine` sean físicamente ejecutables en el despliegue que el repo entrega, levantando **las dos** barreras.
- Que una restauración exitosa devuelva el archivo a su estado anterior **completo** — contenido, modo, dueño y grupo — y no solo su contenido.
- Que un `watch_path` no remediable sea un hecho visible y diagnosticable, no un fallo descubierto al intentar remediar.
- Que el operador pueda distinguir un problema de despliegue de un problema de datos mirando el evento.
- Que el unit que se entrega pueda arrancar en una instalación limpia y falle de forma legible cuando está mal configurado.
- Que el usuario del servicio deje de ser dueño del código que systemd va a ejecutar con `CAP_SYS_ADMIN`.

**Non-Goals:**

- Bajar a `ProtectSystem=full` o eliminar el hardening: rechazado explícitamente en D36.
- Resolver la limitación conocida de D36 (un `watch_path` agregado en caliente no es remediable hasta regenerar el drop-in). Se hace **visible**, no se elimina: es inherente a que el aislamiento de systemd se resuelve en el namespace de montaje al arrancar el servicio.
- Reescribir `_quarantine` para converger con `handle_quarantine_file`, ni corregir la verificación tautológica de hash post-restauración (`decision.py:184-186`). Son follow-ups nombrados en la proposal.
- Agregar `ProtectHome=true` u otro hardening no mandado por D36. La corrección documental va del unit real hacia los docs, no al revés.
- Filtros, ordenamiento o índices nuevos por `action_error` en la API de eventos.
- Cualquier cambio al contrato del `event_ack` que C36 acaba de asentar.

## Decisions

### D-1 — Tres capabilities más, cada una con un uso concreto, y ninguna de más

`AmbientCapabilities` y `CapabilityBoundingSet` pasan a `CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN`. Cada una se justifica por un syscall específico del camino de remediación:

| Capability | Habilita | Sitio |
|---|---|---|
| `CAP_DAC_OVERRIDE` | crear el tmp en un directorio propiedad de `root` (escritura sobre el **directorio** padre), el `rename` del `os.replace`, y el `unlink` del origen en `shutil.move` | `decision.py:172-176`, `:194` |
| `CAP_FOWNER` | `fchmod` sobre un archivo cuyo dueño no es el euid del proceso | restauración de `mode` |
| `CAP_CHOWN` | `fchown` a un uid/gid arbitrario | restauración de `uid`/`gid` |

`CapabilityBoundingSet` tiene que listarlas además de `AmbientCapabilities`: una ambient capability solo sobrevive si está en el conjunto *permitted*, que está acotado por el bounding set. Declararlas solo como ambient las haría descartar en silencio.

`NoNewPrivileges=true` se conserva. No interfiere: systemd fija las ambient capabilities al arrancar el proceso, y `NoNewPrivileges` bloquea la escalada por `execve` de binarios setuid/con file capabilities, no las capabilities heredadas del propio arranque.

No se agrega ninguna otra. En particular no se agrega `CAP_FSETID` (solo hace falta para preservar setgid al hacer `chmod` sobre un archivo de un grupo del que el proceso no es miembro; con `CAP_FOWNER` presente y el orden de D-6 el caso queda cubierto) ni `CAP_SETFCAP`.

### D-2 — `ReadWritePaths` derivado por drop-in aditivo, generado por un módulo Python testeable

El unit base queda **sin editar**: sigue declarando `ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent`. `install.sh` genera `/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf` con los `watch_paths` leídos de `/etc/fim-agent/config.yaml`.

Que el drop-in sea **aditivo y no reseteador** es una propiedad de systemd que conviene dejar escrita, porque no es obvia: `ReadWritePaths=` es un directive de tipo lista, y asignaciones sucesivas se acumulan; solo una asignación vacía (`ReadWritePaths=`) resetea la lista. El drop-in por lo tanto **no repite** `/var/lib/fim-agent` ni `/var/log/fim-agent` — el unit base sigue siendo la fuente de los directorios propios del agente, y el drop-in solo agrega los del operador.

El drop-in incluye **siempre `/etc/fim-agent`**, independientemente de los `watch_paths`. `update_config` persiste ahí (`commands.py:514`), y esa escritura no puede depender de que el operador haya elegido monitorear `/etc`.

La generación vive en un módulo nuevo, `agent/deployment.py`, con dos funciones puras y un entrypoint `python -m agent.deployment --config <path> --output <path>`:

- `read_watch_paths(config_path) -> list[str]` — PyYAML, ya es dependencia (`agent/requirements.txt`).
- `render_watchpaths_dropin(watch_paths) -> str` — devuelve el texto del drop-in.

Que sea Python y no `sed`/`grep` sobre el YAML no es preferencia de estilo: es la única forma de parsear el archivo con el mismo parser que lo escribe (`commands.py:523` usa `yaml.dump`), y es lo que hace el generador testeable sin root y sin systemd. `install.sh` lo invoca con el intérprete del venv, desde `/opt/fim-agent`, que es el mismo `WorkingDirectory` e importación que usa el `ExecStart`.

**Saneamiento de los paths — obligatorio, no cosmético.** `config.yaml` no es un archivo estático: `update_config` lo reescribe con `watch_paths` que llegan del backend por el stream (`commands.py:476`, `:520`). Eso convierte al generador del drop-in en una superficie de inyección de directivas de systemd. `render_watchpaths_dropin` por lo tanto:

- emite **una línea `ReadWritePaths=` por path**, con el path entre comillas dobles, en vez de una sola línea con paths separados por espacios;
- **rechaza con excepción** (no filtra en silencio) cualquier path que no sea absoluto, que contenga un salto de línea, una comilla doble o una barra invertida, o que contenga un componente `..`;
- normaliza con `os.path.normpath`, **no** con `realpath`: no se siguen symlinks, mismo criterio que D33/RN-127.

Un rechazo aborta la generación con un mensaje claro e `install.sh` falla (`set -euo pipefail`), en vez de instalar un drop-in truncado que dejaría paths sin cobertura sin que nadie se entere.

**Reordenamiento de `install.sh`.** Hoy el paso 8.5 instala el unit y hace `daemon-reload` + `enable`, y recién el 8.6 copia el config. La generación del drop-in necesita el config presente y tiene que preceder al `daemon-reload`. El orden pasa a: unit → config → drop-in → `daemon-reload` → `enable`.

**Alcance real del hardening que queda, dicho sin adornos.** Con los `watch_paths` por defecto, `/etc`, `/bin`, `/sbin`, `/usr/bin` y `/usr/sbin` quedan escribibles para el servicio. Lo que sigue en solo-lectura bajo `ProtectSystem=strict` es todo lo demás: `/usr/lib`, `/usr/share`, `/boot`, `/srv`, `/home`, `/root` y `/opt` — incluido el propio código del agente. Como dice D36, el valor de `ProtectSystem=strict` acá no es contener a un atacante que ya controle el proceso, sino acotar el radio de un **defecto** del agente. Esa sigue siendo una propiedad valiosa y por eso se conserva.

### D-3 — Preflight no invasivo: `statvfs` para el mount, `access` para el DAC

El preflight clasifica cada `watch_path` en un vocabulario cerrado (RN-71): `writable`, `read_only_mount`, `permission_denied`, `missing`.

**Se descarta la sonda de escritura real** — crear y borrar un archivo temporal dentro del `watch_path` — aunque sería la prueba más fiel. Escribiría dentro de un directorio monitoreado y **generaría eventos fanotify del propio agente** (`file_created` + `file_deleted` en `/etc`) en cada arranque y en cada recarga de configuración. El agente solo autoexcluye `/var/lib/fim-agent/**` (RN-68). Un preflight que ensucia el flujo de eventos que el sistema existe para producir no es aceptable.

La clasificación usa dos syscalls sin efectos secundarios, y cada uno mide exactamente una de las dos barreras:

1. `os.statvfs(path).f_flag & os.ST_RDONLY` → la barrera de **mount** (`ProtectSystem` / `ReadWritePaths`). Refleja las flags del mount tal como se ven en el namespace del proceso, que es justo donde `ProtectSystem=strict` opera.
2. `os.access(path, os.W_OK)` → la barrera **DAC**. `access(2)` chequea con uid/gid reales, y el kernel conserva las capabilities efectivas cuando el uid real coincide con el euid — que es el caso del servicio, que nunca hace `setuid`. Por eso `os.access` sí refleja el efecto de `CAP_DAC_OVERRIDE` y no da un falso negativo permanente. Es la asunción más delicada del diseño y está en el checklist de verificación en host real (D-12, punto 2).

El orden de evaluación importa y es deliberado: `missing` → `read_only_mount` → `permission_denied` → `writable`. Un mount de solo-lectura hace que `access(W_OK)` también dé falso; la causa útil para el operador en ese caso es la del mount ("falta el drop-in"), no la de permisos ("faltan capabilities"). Reportar la segunda lo mandaría a corregir lo que no está roto.

Se chequea el **directorio**, no el archivo: remediar un archivo requiere escritura sobre su directorio padre (crear el tmp, hacer el rename), no sobre el archivo. Si un `watch_path` apunta a un archivo suelto, se evalúa su directorio padre.

La función es pura con probes inyectables:

```
classify_path_writability(path, *, statvfs_fn=os.statvfs, access_fn=os.access, exists_fn=os.path.exists) -> str
```

Los cuatro estados se cubren con tests sin root inyectando los tres probes. Vive en `agent/preflight.py`, separado de `agent/deployment.py`: uno es lógica de runtime, el otro de instalación, y mezclarlos obligaría a importar PyYAML en el camino caliente.

### D-4 — La degradación es solo-detección y nunca detiene al agente

El preflight corre en `__main__.py` después de `load_config` (`:148`) y antes de `engine.init_scan(cfg.watch_paths)` (`:174`), para que el primer heartbeat ya lo lleve. **Nunca llama a `sys.exit`.** Un path degradado produce un `log.warning` por path más un `log.info` de resumen, y el agente sigue arrancando y monitoreando.

Esto es la aplicación literal de D36: *"la detección es la función primaria; la remediación es una capacidad adicional que puede estar ausente sin invalidar el servicio"*. Un agente que se niega a arrancar porque `/usr/bin` no es escribible deja de detectar, que es exactamente el resultado que no se quiere.

El resultado se guarda en un `PreflightRegistry` — un objeto pequeño con `update(mapping)` y `snapshot() -> dict[str, str]` — que se construye en `main()`, se pasa al `HeartbeatPublisher` y se pasa al dispatcher de comandos para que `handle_update_config` lo actualice. Objeto explícito y no variable de módulo: es lo que permite testear el heartbeat y el handler sin estado global compartido entre tests.

Un efecto lateral que vale nombrar: hoy un `watch_path` inexistente se acepta de punta a punta sin ningún reporte. `baseline.run_scan` loguea `baseline.run_scan.path_missing` y sigue (`baseline.py:494-496`), `init_scan` hace lo mismo (`:434-436`), `detector.reload_watch_paths` no levanta, y `handle_update_config` responde `ok=true`. El estado `missing` del preflight es la primera vez que ese caso se hace visible en la interfaz.

### D-5 — El estado por path viaja en el heartbeat y aterriza en una columna JSON de `Agent`

El payload del heartbeat gana la clave `watch_path_status`: un objeto `{path: estado}` con el vocabulario de D-3. Agregar una clave es seguro para la firma porque `canonical_json` (`streams.py:19-22`) firma el dict completo ordenado, sin allowlist por clave, en ambos extremos.

Del lado backend, `_handle_heartbeat` (`heartbeat_consumer.py:66-109`) lee la clave nueva y la persiste en `Agent.watch_path_status`, columna JSON siguiendo el precedente exacto de `Agent.watch_paths` (`agents/models.py:27`, `sa_column=Column(JSON)`). Tolerancia hacia adelante en las dos direcciones:

- Clave ausente (agente de versión anterior) → la columna **no se toca**. No se borra el último estado conocido por un heartbeat que simplemente no lo trae.
- Valor que no es un objeto de strings → se ignora con `log.warning`, sin rechazar el heartbeat. Un heartbeat malformado no debe hacer que el agente aparezca offline.

`_agent_to_response` (`agents/service.py:103-111`) es el único punto de serialización, así que `GET /agents` y `GET /agents/{id}` lo exponen con un solo cambio.

**Alternativa rechazada:** un endpoint `GET /agents/{id}/preflight`. Duplica un canal que ya llega cada 10 s y agrega superficie HTTP sin resolver nada nuevo.

**Alternativa rechazada:** mandar solo los paths degradados para ahorrar bytes. La ausencia de un path sería ambigua — ¿escribible, o agente viejo que no reporta? Se manda el mapa completo; con los 5 paths por defecto son ~200 bytes cada 10 s, despreciable frente al resto del payload.

### D-6 — La restauración preserva modo, uid y gid: `fchown` antes de `fchmod`, ambos antes de `os.replace`

Esta es la decisión que convierte a las capabilities en algo seguro de otorgar. Hoy `_auto_restore` escribe el tmp y hace `os.replace` (`decision.py:172-176`). El tmp se crea con dueño `fim-agent` y modo por umask. Si se agregan las capabilities **sin** esta parte, un `auto_restore` "exitoso" sobre `/usr/bin/<binario>` lo dejaría propiedad de `fim-agent` con modo `0644`: el feature roto se convierte en una **vulnerabilidad**, porque cualquiera con ese uid pasa a poder reescribir un binario del sistema. Restaurar la metadata no es un extra de completitud, es la condición para que el resto sea aceptable.

Secuencia exacta:

1. `fd = os.open(tmp, O_CREAT | O_WRONLY | O_EXCL, 0o600)` — modo inicial restrictivo, y `O_EXCL` para no reutilizar un tmp huérfano de un intento previo (hoy `open(tmp,"wb")` lo truncaría y seguiría).
2. escribir el contenido, `flush`, `os.fsync(fd)`.
3. `os.fchown(fd, uid, gid)`.
4. `os.fchmod(fd, mode)`.
5. cerrar, `os.replace(tmp, path)`.

**El orden `chown` antes de `chmod` es obligatorio y es el detalle destructivo de todo el diseño.** En Linux, `chown(2)` sobre un archivo con los bits setuid/setgid **los limpia**. `baseline.py:293` guarda `oct(stat.S_IMODE(st.st_mode))`, y `S_IMODE` cubre los 0o7777 — o sea que setuid, setgid y sticky **sí** están en el baseline. Invertir el orden produciría una restauración que reporta éxito y deja `/usr/bin/sudo` sin su bit setuid: el sistema queda roto de una forma que nadie atribuiría al FIM.

Se usan las variantes por descriptor (`fchown`/`fchmod`) y no las de path: eliminan el TOCTOU sobre el path del tmp y garantizan que **el archivo nunca existe en su path final con propiedad equivocada**, porque toda la metadata se aplica antes del `os.replace`, que es atómico. El tmp sigue creándose en el mismo directorio que el destino (ya es el caso: `path + ".fim_restore_tmp"`), condición necesaria para que el `replace` sea un rename y no una copia cross-device.

**Metadata ausente ⇒ la restauración falla, no se completa a medias.** Si `entry.mode`, `entry.uid` o `entry.gid` son `None`, o si `mode` no parsea, se aborta con razón `no_baseline_metadata`, se borra el tmp y **el archivo original queda intacto**. El caso es real: `mark_absent` produce entries con los tres en `None` (`baseline.py:351-360`). Publicar un archivo del sistema con dueño `fim-agent` y modo por umask es peor que no restaurar; un fallo visible es preferible a una restauración que degrada la postura de seguridad del host.

El parseo del modo es una función pura, `parse_baseline_mode(value: str | None) -> int | None`, que acepta tanto la forma con prefijo (`'0o644'`, que es lo que produce `oct()`) como un octal desnudo, y devuelve `None` ante cualquier otra cosa. Testeable sin root.

**Asimetría documentada:** `select_restorable_content` (`baseline.py:177-198`) puede devolver contenido de un *snapshot*, mientras que modo/uid/gid vienen siempre de la *entry* — `Snapshot` no los guarda. O sea que se restaura contenido de un momento y metadata de otro. Es la mejor aproximación disponible (la metadata de la entry es la última observada) y queda escrito para que no se descubra como sorpresa.

La cuarentena no cambia en este aspecto: el archivo se retira del sistema, no se reintegra, y su metadata en el directorio de cuarentena no tiene el mismo significado. Las dos implementaciones divergentes de cuarentena quedan como follow-up.

### D-7 — Vocabulario cerrado de razones de fallo, y el errno se clasifica en el sitio del intento

`_ActionFailed` pasa a llevar razones de un vocabulario cerrado en snake_case (RN-71):

`read_only_mount` · `permission_denied` · `no_baseline_content` · `no_restorable_content` · `no_baseline_metadata` · `file_not_found` · `hash_mismatch_after_restore` · `write_failed` · `move_failed`

Los dos primeros son la contribución de esta change y son exactamente lo que D36 pide poder distinguir de `no_baseline_content` / `no_restorable_content`: barrera de despliegue contra problema de datos.

El mapeo es una función pura, `action_error_from_oserror(exc: OSError, *, fallback: str) -> str`: `errno.EROFS` → `read_only_mount`; `errno.EACCES` y `errno.EPERM` → `permission_denied`; cualquier otro → el `fallback` del sitio (`write_failed` en la restauración, `move_failed` en la cuarentena). Se construye un `OSError(errno.EROFS, ...)` a mano en el test; no hace falta un mount de solo-lectura.

Como efecto colateral, desaparece la interpolación cruda de hoy: `f"write_failed: {exc}"` (`decision.py:182`) mete el mensaje del sistema operativo — que incluye el path del archivo — en un string que ahora se va a publicar. El valor publicado pasa a ser estable y sin interpolación; el detalle (errno, mensaje) va a campos estructurados del log, donde ya vivía.

**La acción no consulta el preflight.** El preflight es la vista de *reporte* (heartbeat, UI); el mapeo de errno en el sitio del intento es la verdad de *ese* intento. Gatear la acción con un preflight cacheado introduciría un fallo por estado obsoleto: un path que se volvió escribible entre el arranque y el evento sería rechazado sin siquiera intentarlo. Se intenta siempre y se clasifica el error real. Las dos vistas pueden discrepar transitoriamente, y está bien: significan cosas distintas.

La razón viaja en `payload["action_error"]`, al lado del `payload["action_failed"] = True` que ya existe (`decision.py:80`). En la ruta de éxito la clave **no se escribe**, mismo criterio que `action_failed`, de modo que todo consumidor lee con `.get(...)`. El journal sigue recibiendo la razón por `mark_failed`, ahora con el mismo vocabulario.

Los handlers manuales de `commands.py` usan el mismo mapeo. Ahí la razón ya llegaba al backend por otro camino — el ack (`command_ack_consumer.py:187` → `PublishedCommand.error`) — así que alinear el vocabulario hace que las dos rutas hablen los mismos literales en lugar de dos dialectos.

### D-8 — `Event.action_error`: columna nullable, tolerancia hacia adelante, sin enum en la BD

Migración `008_add_event_action_error.sql`, molde de la `007`:

```sql
ALTER TABLE events ADD COLUMN IF NOT EXISTS action_error VARCHAR(64);
```

Nullable, sin default, sin índice — no hay endpoint ni filtro que lo consulte, y sería un índice sobre una columna de baja cardinalidad sin consulta que lo justifique. La ingesta lee `event_data.get("action_error")`, lo trunca a 64 caracteres y lo persiste tal cual.

**No se valida contra un enum en la base ni en el ingest.** El vocabulario evoluciona del lado del agente; una restricción de BD convertiría un agente más nuevo que el backend en pérdida de eventos de integridad, que es el activo que el sistema existe para no perder. Mismo criterio de tolerancia hacia adelante que D-2 de C40 y que D33. La UI mapea los valores conocidos a prosa y muestra el crudo como fallback, así que un valor futuro se degrada a "menos legible", nunca a "evento perdido".

Migración gemela `009_add_agent_watch_path_status.sql` para `agents.watch_path_status JSONB`, también nullable.

Frontend: mapper puro `frontend/src/utils/actionError.ts` con el contrato de `getAckStatusMeta` (`utils/ackStatus.ts` es el único patrón del repo testeado de forma aislada). La causa se muestra en el **detalle** del evento, calificando al indicador de `action_failed` que introdujo C40; la tabla no cambia. Ahí `action_failed` ya comunica el hecho, y la causa es información de segundo nivel que no justifica otra columna en una tabla ya densa.

### D-9 — `update_config` reejecuta el preflight y deja de tragarse el fallo de persistencia

Tras `detector.reload_watch_paths` y el scan de los paths nuevos, `handle_update_config` reejecuta el preflight sobre el conjunto nuevo y actualiza el `PreflightRegistry`. Eso es lo que hace **visible** la limitación conocida de D36: un path agregado desde la interfaz queda monitoreado pero no remediable hasta que se regenere el drop-in y se haga `daemon-reload` en el anfitrión. El operador lo ve como `read_only_mount` en la tarjeta del agente dentro del siguiente heartbeat (≤10 s), en lugar de descubrirlo semanas después cuando una remediación falla.

El fallo al persistir `config.yaml` (`commands.py:526-527`) deja de ser un `log.warning` mudo: pasa a `log.error` y se refleja en el registro que viaja en el heartbeat, con una clave propia (`config_persisted: bool`). El caso `not os.path.exists(config_path)` (`:517`), que hoy es un no-op sin siquiera un warning, se registra igual.

**El `ok` del ack no cambia.** La recarga en caliente efectivamente ocurrió — fanotify recargado, baseline escaneado, `config.watch_paths` actualizado en memoria — y el contrato del `event_ack` lo acaba de asentar C36. Convertirlo en `ok=false` cambiaría el significado de un ack ya establecido y podría disparar reintentos del backend sobre un comando que en su mayor parte tuvo efecto. El canal correcto para "corriendo pero degradado" es el heartbeat, que es justamente el mecanismo que esta change introduce y que ya se lee cada 10 s.

**Alternativa rechazada:** agregar un tercer estado al ack (`ok` / `partial` / `error`). Toca un contrato recién cerrado, obliga a cambiar el consumer y el modelo `PublishedCommand`, y duplica un canal de reporte que ya existe.

### D-10 — El unit tiene que poder arrancar, y fallar una sola vez cuando está mal configurado

Dos cambios chicos y complementarios:

**`EnvironmentFile=-/etc/fim-agent/env`**, con el guion adelante: el archivo es *opcional*. El secreto de bootstrap es de un solo uso (spec `backend-agents`, "Bootstrap secret is single-use") y conviene borrarlo tras el primer arranque; con el guion, su ausencia posterior no impide arrancar. `install.sh` instala `agent/deploy/env.example` en `/etc/fim-agent/env` **solo si no existe**, con `0600 root:root` — alcanza y sobra, porque systemd lee el `EnvironmentFile` como root antes de bajar privilegios; el usuario del servicio no necesita poder leerlo.

**Código de salida de configuración `78`** (`EX_CONFIG` de `sysexits.h`) más `RestartPreventExitStatus=78` en el unit. Los tres `sys.exit(1)` de configuración del arranque — secreto de bootstrap ausente (`__main__.py:156`), `shared_secret` ausente (`:170`) y los de `load_config` (`config.py:59-61`, `:70-72`) — pasan a `78`. Hoy cualquiera de esos deja el unit girando cada 5 s por `Restart=on-failure`, escupiendo el mismo error para siempre; con esto el unit queda en `failed` con un mensaje único y legible en el journal. `Restart=on-failure` se conserva para los fallos genuinamente transitorios (Valkey caído, red, etc.), que es para lo que sirve.

**Alternativa rechazada:** `Type=notify` con `sd_notify`. Agrega dependencia o un socket a mano y no resuelve el problema real, que es distinguir "mal configurado" de "falló".

### D-11 — Propiedad: las capabilities viven en el proceso, no en el uid

`install.sh` pasa a aplicar:

| Ruta | Dueño | Modo |
|---|---|---|
| `/opt/fim-agent` | `root:root` | `0755` (venv ejecutable) |
| `/etc/fim-agent` | `root:fim-agent` | `0750` |
| `/etc/fim-agent/config.yaml` | `root:fim-agent` | `0640` (el agente lo lee por grupo) |
| `/etc/fim-agent/env` | `root:root` | `0600` |
| `/var/lib/fim-agent/**` | `fim-agent:fim-agent` | `0700` (sin cambios, RN-51) |
| `/var/log/fim-agent` | `fim-agent:fim-agent` | `0750` (sin cambios) |

**El alcance de esta protección hay que decirlo con precisión, porque es fácil sobrevenderla.** El proceso del servicio tiene `CAP_DAC_OVERRIDE`, así que **puede** escribir en `/opt/fim-agent` y `/etc/fim-agent` de todas formas — de hecho `update_config` necesita escribir `config.yaml`. Lo que la propiedad `root` corta es el **otro** vector: un shell obtenido como uid `fim-agent` fuera del proceso del servicio (por otra vulnerabilidad del host, por un cron mal puesto, por lo que sea) **no tiene ambient capabilities**, y por lo tanto ya no puede reescribir el código que systemd va a ejecutar con `CAP_SYS_ADMIN` en el próximo reinicio. Las capabilities viven en el proceso que systemd arranca, no en el uid; el `chown -R` de hoy destruye exactamente esa separación y la convierte en una escalada a root de un solo paso.

El nuevo bloque de propiedad tiene que ser tan idempotente como el actual: correr `install.sh` dos veces no debe cambiar nada ni pisar un `config.yaml` ya editado por el operador.

### D-12 — Qué se puede probar sin root, qué se puede probar con filesystem real, y qué no se puede probar

La suite del agente mockea el filesystem con generosidad, así que no puede demostrar nada de esta change tal como está. El diseño se organiza para que la mayor parte sea verificable sin privilegios, y para que el resto quede **nombrado** en vez de tapado.

**Puras, sin root ni filesystem** — es para esto que D-3, D-6 y D-7 están factorizadas en funciones con probes inyectables:

- `classify_path_writability` con `statvfs_fn` / `access_fn` / `exists_fn` inyectados: los cuatro estados, y la precedencia `read_only_mount` sobre `permission_denied`.
- `parse_baseline_mode`: `'0o644'`, `'644'`, `None`, basura, y que preserva los bits setuid/setgid/sticky.
- `action_error_from_oserror`: `OSError(errno.EROFS, ...)` y `OSError(errno.EACCES, ...)` construidos a mano.
- `render_watchpaths_dropin`: forma del texto, `/etc/fim-agent` siempre presente, una línea por path, entrecomillado, y **rechazo** de path relativo, con `..`, con salto de línea, con comilla o con barra invertida.
- `read_watch_paths` sobre un YAML de `tmp_path`.
- La serialización de `watch_path_status` en el payload del heartbeat (patrón de `agent/tests/test_shutdown_heartbeat.py:51-60`).

**Con filesystem real y sin root** (`tmp_path`, cadena de fixtures de `agent/tests/test_baseline.py:36-81`):

- La restauración preserva el **modo** — `chmod` sobre archivos propios no necesita privilegio.
- `no_baseline_metadata` cuando falta `mode`/`uid`/`gid`, **y que el archivo original queda intacto**.
- `permission_denied` real: `chmod 0500` sobre el directorio padre y verificar el mapeo del errno.
- `O_EXCL`: un `.fim_restore_tmp` huérfano preexistente hace fallar el intento en vez de reutilizarse.
- **El orden `fchown` antes de `fchmod`**, con un mock que registra el orden de llamadas. Este sí es un mock legítimo: no pretende demostrar que `chown` funciona, demuestra que el orden se respeta, que es la propiedad destructiva y es exactamente lo que un mock de orden de llamadas puede probar.

**No verificable sin root ni sin systemd — checklist manual en host real, en `tasks.md`:**

1. Que systemd otorgue las cinco ambient capabilities: `grep Cap /proc/$(systemctl show -p MainPID --value fim-agent)/status` + `capsh --decode`.
2. Que `statvfs` reporte `ST_RDONLY` para un path fuera de `ReadWritePaths` **dentro del namespace del servicio** — la asunción central de D-3.
3. Que `os.chown` restaure uid/gid reales (requiere `CAP_CHOWN` de verdad).
4. Que el bit setuid sobreviva a la restauración de un binario setuid.
5. `install.sh` de punta a punta sobre un host limpio, incluidos el drop-in, un segundo `install.sh` para confirmar idempotencia, y `systemd-analyze security fim-agent.service`.

**Regla explícita para la fase de apply: está prohibido cerrar cualquiera de esos cinco con un mock que siempre pasa.** Un test que parchea `os.chown` a un no-op y luego afirma que "se llamó" demuestra que el código invoca la función, no que la restauración funcione. Esa verificación residual manual es legítima — el proyecto se despliega en hosts reales — pero tiene que estar declarada como manual, no disfrazada de cobertura automática.

## Risks / Trade-offs

- **[Ampliar `ReadWritePaths` a los `watch_paths` reduce mucho el alcance efectivo de `ProtectSystem=strict`]** → con la configuración por defecto, cinco directorios del sistema quedan escribibles para el servicio. Es el precio explícito de D36, que descartó `ProtectSystem=full` porque dejaría `/usr/bin` sin remediación posible, o sea sin la capacidad que motiva la herramienta. Mitigación honesta: el resto de la jerarquía sigue en solo-lectura, incluido `/opt/fim-agent` — el agente no puede reescribir su propio código ni con `CAP_DAC_OVERRIDE`... salvo que el operador ponga `/opt` en `watch_paths`, caso que el preflight hace visible pero no impide.
- **[Otorgar `CAP_DAC_OVERRIDE` y `CAP_CHOWN` amplía el radio de un defecto, no solo el de un atacante]** → el argumento de D36 —el proceso ya tiene `CAP_SYS_ADMIN`, que es root en la práctica— es correcto para el modelo de amenaza, pero incompleto para el modelo de *defectos*: hasta hoy un bug en `_auto_restore` no podía dañar el sistema porque el `EROFS` lo frenaba. Mitigaciones concretas: el containment de D18/RN-116 no se toca, la restauración usa `O_EXCL` y exige metadata completa, y el camino de escritura solo se ejerce desde el decision engine sobre paths dentro de `watch_paths`.
- **[La restauración con metadata obligatoria puede fallar sobre entries viejas]** → cualquier entry producida por `mark_absent`, o por una versión anterior sin `mode`/`uid`/`gid`, aborta con `no_baseline_metadata`. Es deliberado (D-6) y es visible en la UI gracias a D-8, pero implica que tras desplegar puede aparecer una tanda de fallos que antes ni se intentaban. Mitigación: `no_baseline_metadata` es un valor propio del vocabulario, distinguible de una barrera de despliegue, y un rescan del baseline lo resuelve.
- **[El drop-in se materializa en la instalación; los paths agregados en caliente no son remediables]** → limitación conocida de D36, inherente al namespace de montaje de systemd. Esta change la hace visible (`read_only_mount` en la tarjeta del agente) pero no la elimina. El operador tiene que volver al anfitrión a regenerar el drop-in.
- **[`os.access` reflejando capabilities depende de que uid real == euid]** → es el caso hoy y el servicio no hace `setuid`, pero es una asunción del kernel que el repo no puede demostrar. Si fuera falsa, todos los paths se reportarían `permission_denied` y el operador vería "solo-detección" en todos lados mientras la remediación funciona. Está como punto 2 del checklist manual, y el fallo sería ruidoso y evidente en la primera verificación en host.
- **[Dos migraciones manuales más, sin runner]** → convención D3 asumida. Ambas son aditivas y nullable, así que un backend nuevo contra una base sin migrar falla al leer las columnas, no al escribir. Mitigación: encabezado con la línea `psql` exacta y test de idempotencia según el molde de `backend/tests/test_event_severity.py:201-223`.
- **[El heartbeat crece linealmente con la cantidad de `watch_paths`]** → 5 paths son ~200 bytes cada 10 s; 200 paths serían ~8 KB cada 10 s por agente. No es un problema en el escenario de la tesis, pero el mapa completo no es gratis para siempre. Se acepta y se deja escrito.
- **[Un operador puede leer "solo-detección" como "el agente está roto"]** → la degradación es parcial y correcta, no una falla. Mitigación: prosa explícita en la tarjeta del agente, no el valor crudo del campo, y un estado visual distinto del de agente `offline`.

## Migration Plan

1. Aplicar las dos migraciones sobre cada base existente (producción, demo y test):
   `psql $DATABASE_URL -f backend/db/migrations/008_add_event_action_error.sql`
   `psql $DATABASE_URL -f backend/db/migrations/009_add_agent_watch_path_status.sql`
   Ambas idempotentes; re-aplicarlas no falla.
2. Desplegar el **backend** (columnas nuevas, `EventOut`, consumer de heartbeat). Tolera agentes viejos: sin `action_error` ni `watch_path_status` el comportamiento es el de hoy.
3. Desplegar el **frontend**.
4. En cada host, actualizar el **agente**: `sudo bash agent/install.sh` (reinstala el unit, regenera el drop-in, corrige la propiedad), `systemctl daemon-reload`, `systemctl restart fim-agent`.
5. Correr el checklist de verificación manual de D-12 en al menos un host real.

Backend primero es el orden seguro en las dos direcciones: un agente nuevo contra un backend viejo publica claves que el backend ignora sin romper la firma; un backend nuevo contra un agente viejo ve las claves ausentes y no toca nada.

**Rollback**: revertir el unit y el código del agente. El drop-in puede quedarse en el host sin efecto adverso — sin las capabilities, las escrituras vuelven a fallar por DAC en vez de por `EROFS`, que es exactamente el estado anterior. Las columnas quedan en la base, nullable y sin lectores. **El cambio de propiedad de `install.sh` no se revierte**: es una corrección de seguridad independiente del resto y revertirla reintroduce la escalada.

## Open Questions

_(ninguna — D36/RN-130 está cerrada en el appendix "Decisiones de implementación — Abril 2026" de `docs/reglas_de_negocio.md:1165-1185`, e incluye el set de capabilities, la conservación de `ProtectSystem=strict` con `ReadWritePaths` derivado por drop-in, la semántica del preflight y de la degradación a solo-detección, el requisito de causa de fallo distinguible, la corrección de propiedad de `install.sh`, la limitación conocida de los paths agregados en runtime y el rechazo explícito de `ProtectSystem=full`.)_
