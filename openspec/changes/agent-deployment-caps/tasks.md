## 1. Funciones puras del agente (base — todo lo demás las consume)

- [x] 1.1 Crear `agent/preflight.py` con `classify_path_writability(path, *, statvfs_fn=os.statvfs, access_fn=os.access, exists_fn=os.path.exists) -> str`, vocabulario cerrado `writable | read_only_mount | permission_denied | missing` (RN-71). Orden de evaluación normativo: `missing` → `read_only_mount` (`f_flag & os.ST_RDONLY`) → `permission_denied` (`access_fn(path, os.W_OK)` falso) → `writable`. Si el path es un archivo regular, evaluar su directorio padre. Los tres probes inyectables — es lo que hace testeable sin root.
- [x] 1.2 En el mismo módulo, `run_preflight(watch_paths, **probes) -> dict[str, str]` y la clase `PreflightRegistry` con `update(mapping)`, `set_config_persisted(bool)` y `snapshot() -> dict`. Objeto explícito, NO variable de módulo: el heartbeat y `handle_update_config` lo comparten y los tests lo instancian aislado.
- [x] 1.3 Crear `agent/deployment.py` con `read_watch_paths(config_path) -> list[str]` (PyYAML, ya es dependencia) y `render_watchpaths_dropin(watch_paths) -> str`. Emitir **una línea `ReadWritePaths=` por path**, entrecomillada; incluir siempre `/etc/fim-agent`; NO repetir `/var/lib/fim-agent` ni `/var/log/fim-agent` y NO emitir una línea `ReadWritePaths=` vacía (el drop-in es aditivo, un reset borraría los del unit base).
- [x] 1.4 En `render_watchpaths_dropin`, **levantar excepción** (nunca filtrar en silencio) ante un path no absoluto, con `..`, con salto de línea, con comilla doble o con barra invertida. Normalizar con `os.path.normpath`, NO con `realpath` (no seguir symlinks, D33/RN-127). `config.yaml` lo reescribe `update_config` con paths que vienen del backend: el generador es superficie de inyección de directivas de systemd.
- [x] 1.5 Agregar el entrypoint `python -m agent.deployment --config <path> --output <path>` que escribe el drop-in y sale distinto de cero ante un path rechazado.
- [x] 1.6 En `agent/decision.py`, agregar `parse_baseline_mode(value: str | None) -> int | None` — acepta `'0o644'` (forma que produce `oct()` en `agent/baseline.py:293`) y el octal desnudo `'644'`; devuelve `None` ante cualquier otra cosa. Preserva los bits setuid/setgid/sticky (`S_IMODE` cubre 0o7777).
- [x] 1.7 En `agent/decision.py`, agregar `action_error_from_oserror(exc: OSError, *, fallback: str) -> str`: `errno.EROFS` → `read_only_mount`; `errno.EACCES` / `errno.EPERM` → `permission_denied`; resto → `fallback`.

## 2. Unit systemd y drop-in (`agent/deploy/`)

- [x] 2.1 En `agent/deploy/fim-agent.service:18-19`, extender `AmbientCapabilities` y `CapabilityBoundingSet` a `CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN`. Actualizar el comentario de `:14-17` explicando el uso concreto de cada una (ver la tabla de D-1 del design). Las tres nuevas van en **ambas** directivas: una ambient capability ausente del bounding set se descarta en silencio.
- [x] 2.2 Conservar `ProtectSystem=strict` (`:22`), `NoNewPrivileges=true` (`:23`), `PrivateTmp=true` (`:24`) y `ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent` (`:25`) tal cual. NO agregar `ProtectHome` ni ningún otro hardening no mandado por D36.
- [x] 2.3 Agregar `EnvironmentFile=-/etc/fim-agent/env` (con guion — el archivo es opcional porque el secreto de bootstrap es de un solo uso y se borra tras el primer arranque).
- [x] 2.4 Agregar `RestartPreventExitStatus=78` junto a `Restart=on-failure` (`:28`), con un comentario que nombre `EX_CONFIG`.
- [x] 2.5 Crear `agent/deploy/env.example` con `FIM_BOOTSTRAP_SECRET=` comentado y la nota de que se borra tras el primer arranque exitoso.

## 3. `agent/install.sh`

- [x] 3.1 Reordenar: unit (8.5) → config (8.6) → generación del drop-in → `systemctl daemon-reload` → `systemctl enable`. Hoy el `daemon-reload` corre antes de que exista el config, y el drop-in lo necesita.
- [x] 3.2 Generar el drop-in: `mkdir -p /etc/systemd/system/fim-agent.service.d` y ejecutar el módulo con el intérprete del venv desde `/opt/fim-agent` (mismo `WorkingDirectory` e importación que el `ExecStart`), con salida a `10-watchpaths.conf`. Con `set -euo pipefail`, un path rechazado aborta la instalación — es lo buscado.
- [x] 3.3 Instalar `env.example` en `/etc/fim-agent/env` **solo si no existe**, con `0600 root:root` (systemd lo lee como root antes de bajar privilegios; el usuario del servicio no necesita leerlo).
- [x] 3.4 Reemplazar el `chown -R fim-agent` de `:73-78` por: `/opt/fim-agent` → `root:root` `0755` (venv ejecutable); `/etc/fim-agent` → `root:fim-agent` `0750`; `/etc/fim-agent/config.yaml` → `root:fim-agent` `0640`; `/etc/fim-agent/env` → `root:root` `0600`; `/var/lib/fim-agent` y `/var/log/fim-agent` → `fim-agent:fim-agent` con los modos de RN-51 (sin cambios).
- [x] 3.5 Verificar que una segunda corrida del script no pisa un `config.yaml` editado ni cambia el estado final de propiedad y permisos.

## 4. Preflight en el runtime del agente

- [x] 4.1 En `agent/__main__.py`, instanciar el `PreflightRegistry` y correr el preflight después de `load_config` (`:148`) y antes de `engine.init_scan(cfg.watch_paths)` (`:174`), para que el primer heartbeat ya lo lleve.
- [x] 4.2 Loguear un `warning` por path degradado (con `path` y clasificación como campos estructurados) más un `info` de resumen. **Nunca `sys.exit`** por resultado del preflight, cualquiera sea la clasificación: la detección es la función primaria (D36).
- [x] 4.3 Pasar el registry al `HeartbeatPublisher` (`:255-258`) y al dispatcher de comandos, de modo que `handle_update_config` pueda actualizarlo.
- [x] 4.4 En `agent/heartbeat.py:78-94`, agregar `watch_path_status` (mapa completo path → clasificación, no solo los degradados) y la clave de estado de persistencia de configuración. No tocar la firma: `canonical_json` (`agent/streams.py:19-22`) firma el dict completo ordenado, sin allowlist.

## 5. Restauración con metadata (`agent/decision.py`)

- [x] 5.1 Reescribir el bloque de escritura de `_auto_restore` (`:172-176`) con la secuencia: `os.open(tmp, O_CREAT|O_WRONLY|O_EXCL, 0o600)` → write → `os.fsync(fd)` → `os.fchown(fd, uid, gid)` → `os.fchmod(fd, mode)` → close → `os.replace(tmp, path)`. El tmp sigue creándose en el directorio del destino (condición para que el replace sea rename atómico).
- [x] 5.2 **`fchown` antes de `fchmod`, en ese orden, obligatorio.** `chown(2)` limpia los bits setuid/setgid; invertirlo produciría una restauración que reporta éxito y deja un binario setuid sin su bit. Dejar un comentario en el código que lo diga, porque es el tipo de línea que un refactor reordena sin pensarlo.
- [x] 5.3 Usar las variantes por descriptor (`fchown`/`fchmod`) y no las de path: eliminan el TOCTOU sobre el tmp y garantizan que el archivo nunca existe en su path final con propiedad equivocada.
- [x] 5.4 Si `entry.mode`, `entry.uid` o `entry.gid` son `None`, o si `parse_baseline_mode` devuelve `None`: abortar con `_ActionFailed("no_baseline_metadata")`, borrar el tmp y dejar el archivo original **intacto**. El caso es real — `mark_absent` (`agent/baseline.py:351-360`) produce las tres en `None`.
- [x] 5.5 Reemplazar `raise _ActionFailed(f"write_failed: {exc}")` (`:182`) por `action_error_from_oserror(exc, fallback="write_failed")`. Mover el errno y el mensaje del SO a campos estructurados del log — hoy el path del archivo se interpola en un string que ahora se publica.
- [x] 5.6 Hacer lo mismo en `_quarantine` (`:197-198`) con `fallback="move_failed"`. NO tocar el resto de `_quarantine` (la divergencia con `handle_quarantine_file` es follow-up, no de esta change).
- [x] 5.7 En el `except _ActionFailed` de `evaluate_and_act` (`:79-84`), agregar `payload["action_error"] = exc.error` junto al `action_failed = True` existente. **No escribir la clave en la ruta de éxito** — mismo criterio que `action_failed`, para que todo consumidor lea con `.get(...)`.
- [x] 5.8 Verificar que la ruta `rehydrate` (`:95-154`) propaga `action_error` con la misma semántica cuando reintenta una acción y falla.
- [x] 5.9 **No** consultar el preflight antes de ejecutar la acción. El preflight es la vista de reporte; el errno del intento es la verdad de ese intento. Gatear con estado cacheado rechazaría sin intentar un path que se volvió escribible.

## 6. Handlers manuales (`agent/commands.py`)

- [x] 6.1 En `handle_restore_file` (`:322-356`), aplicar el mismo mapeo de errno y el mismo vocabulario. La razón ya llegaba al backend por el ack (`command_ack_consumer.py:187` → `PublishedCommand.error`); alinear los literales hace que las dos rutas hablen un solo dialecto. Restaurar además modo/uid/gid con la misma secuencia de la tarea 5.1 (es el mismo camino de escritura, duplicado).
- [x] 6.2 En `handle_quarantine_file` (`:411-440`), aplicar el mapeo de errno con `fallback="move_failed"`.
- [x] 6.3 En `handle_update_config`, tras `detector.reload_watch_paths` y el scan (`:504-511`), reejecutar el preflight sobre el conjunto nuevo y actualizar el registry. Esto es lo que hace visible la limitación conocida de D36 (path agregado en caliente = monitoreado pero no remediable hasta regenerar el drop-in).
- [x] 6.4 Cambiar `log.warning("commands.update_config.config_yaml_write_failed")` (`:526-527`) a `log.error` y registrar el resultado en el registry (`set_config_persisted`). Loguear también el caso `not _os.path.exists(config_path)` (`:517`), que hoy es un no-op sin ni siquiera un warning.
- [x] 6.5 **No cambiar el `ok` del ack** (`:549-552`). La recarga en caliente sí ocurrió y el contrato del `event_ack` lo asentó C36; el canal para "corriendo pero degradado" es el heartbeat. Dejarlo escrito en un comentario para que un lector futuro no lo "arregle".

## 7. Código de salida de configuración

- [x] 7.1 Cambiar a `sys.exit(78)` los tres puntos de fallo de configuración del arranque: `agent/__main__.py:156` (secreto de bootstrap ausente), `:170` (shared_secret ausente) y los de `agent/config.py:59-61` y `:70-72` (archivo ausente / validación fallida). Definir la constante en un solo lugar con el comentario `EX_CONFIG (sysexits.h)`.
- [x] 7.2 Verificar que ningún otro `sys.exit` del agente usa 78, para que `RestartPreventExitStatus` no frene un fallo transitorio.

## 8. Backend — columnas, ingesta y heartbeat

- [x] 8.1 Agregar `action_error: str | None = Field(default=None, max_length=64)` al modelo `Event` (`backend/app/modules/events/models.py`), junto a `action_failed`.
- [x] 8.2 Crear `backend/db/migrations/008_add_event_action_error.sql` con `ALTER TABLE events ADD COLUMN IF NOT EXISTS action_error VARCHAR(64);`. Encabezado con el molde de `007_add_event_action_failed.sql`: número, decisión (D36/RN-130) y change, nota de idempotencia, línea `psql` exacta. Sin índice, sin backfill (nullable).
- [x] 8.3 En `ingest_event`, leer `event_data.get("action_error")`, truncar a 64 y persistirlo. **Sin validación contra enum** ni en la ingesta ni en la BD: tolerancia hacia adelante, mismo criterio que el `action` desconocido de C40 y que D33. Un valor desconocido se guarda tal cual; ausente → `NULL`.
- [x] 8.4 Verificar que `action_error` no influye en la derivación de status ni en la supersesión — es puramente explicativo.
- [x] 8.5 Agregar `action_error: str | None = None` a `EventOut` (`backend/app/modules/events/router.py`), aditivo, sin filtro ni parámetro de query nuevo.
- [x] 8.6 Agregar `watch_path_status` como columna JSON nullable al modelo `Agent` (`backend/app/modules/agents/models.py`), siguiendo el precedente de `watch_paths` (`:27`, `sa_column=Column(JSON)`).
- [x] 8.7 Crear `backend/db/migrations/009_add_agent_watch_path_status.sql`, idempotente, nullable, mismo molde de encabezado.
- [x] 8.8 En `_handle_heartbeat` (`backend/app/modules/agents/heartbeat_consumer.py:66-109`), leer `watch_path_status` y persistirlo. Clave **ausente** → no tocar la columna (un agente viejo no borra el último estado conocido). Valor que no es un mapa de strings → ignorar con `log.warning` y procesar el heartbeat igual: un campo malformado nunca debe hacer que el agente aparezca offline.
- [x] 8.9 Exponer el campo en `AgentResponse` y `AgentListResponse` vía `_agent_to_response` (`backend/app/modules/agents/service.py:103-111`), que es el único choke point de serialización de ambos endpoints.

## 9. Frontend

- [x] 9.1 Agregar `action_error?: string | null` al tipo de evento en `frontend/src/api/events.ts`, con el comentario que nombra decisión y change siguiendo la convención del archivo (`// D36/RN-130 (C41): ...`).
- [x] 9.2 Crear `frontend/src/utils/actionError.ts` con `getActionErrorMeta(cause: string | null | undefined)` que devuelve `{ label, className }` o `null`, con el contrato de `getAckStatusMeta` (`utils/ackStatus.ts`). Prosa en castellano para los valores conocidos; **fallback al literal crudo** para un valor desconocido, nunca ocultarlo.
- [x] 9.3 En `frontend/src/pages/EventDetail.tsx`, mostrar la causa junto al indicador de `action_failed` que agregó C40. **No tocar `EventsTable.tsx`**: la causa es información de segundo nivel y la tabla ya está densa.
- [x] 9.4 Agregar `watch_path_status?: Record<string, string> | null` al tipo `Agent` en `frontend/src/api/agents.ts`.
- [x] 9.5 Crear `frontend/src/utils/watchPathStatus.ts` con el mismo contrato de mapper puro, con prosa que comunique que el path **sigue monitoreado** (solo-detección), y estilos distintos de los de un agente `offline`.
- [x] 9.6 En `frontend/src/components/ui/AgentCard.tsx:178-182`, renderizar el indicador por path en modo lectura. Si el agente no reporta mapa (agente viejo o sin heartbeat aún), renderizar la lista **como hoy**, sin indicador — no defaultear a ninguno de los dos estados.

## 10. Tests — puros, sin root ni filesystem

- [x] 10.1 `agent/tests/test_preflight.py`: `classify_path_writability` con `statvfs_fn`/`access_fn`/`exists_fn` inyectados. Los cuatro estados y, explícitamente, la precedencia de `read_only_mount` sobre `permission_denied` cuando ambos probes fallan.
- [x] 10.2 `parse_baseline_mode`: `'0o644'`, `'644'`, `None`, basura, y que preserva setuid/setgid/sticky (`'0o4755'`).
- [x] 10.3 `action_error_from_oserror` con `OSError(errno.EROFS, ...)` y `OSError(errno.EACCES, ...)` construidos a mano — no hace falta un mount de solo-lectura.
- [x] 10.4 `agent/tests/test_deployment_dropin.py`: forma del texto renderizado, `/etc/fim-agent` siempre presente, una línea por path, entrecomillado, ausencia de `/var/lib/fim-agent` y de línea `ReadWritePaths=` vacía, y **rechazo** de path relativo, con `..`, con salto de línea, con comilla doble y con barra invertida.
- [x] 10.5 `read_watch_paths` sobre un YAML escrito en `tmp_path`, incluido el caso de archivo sin la clave.
- [x] 10.6 Serialización de `watch_path_status` y del estado de persistencia en el payload del heartbeat, siguiendo el patrón de `agent/tests/test_shutdown_heartbeat.py:51-60` (config `MagicMock`, llamada directa al builder).

## 11. Tests — filesystem real, sin root

Seguir la cadena de fixtures de `agent/tests/test_baseline.py:36-81`. La suite del agente mockea el filesystem con generosidad y por eso no detectó nada de esto: estos tests tienen que tocar archivos de verdad.

- [x] 11.1 La restauración preserva el **modo** (`chmod` sobre archivos propios no necesita privilegio): baseline real con `mode='0o600'`, restaurar y verificar `S_IMODE` del archivo resultante.
- [x] 11.2 `no_baseline_metadata` cuando falta `uid`, `gid` o `mode`, **y que el archivo original queda intacto** y no queda ningún `.fim_restore_tmp`.
- [x] 11.3 `permission_denied` real: `chmod 0500` sobre el directorio padre del destino y verificar el mapeo del errno a la razón.
- [x] 11.4 `O_EXCL`: crear un `.fim_restore_tmp` huérfano y verificar que el intento falla en vez de truncarlo y reusarlo.
- [x] 11.5 **Orden `fchown` antes de `fchmod`**, con un mock que registra el orden de llamadas. Este mock es legítimo y hay que decir por qué en el docstring: no pretende demostrar que `chown` funciona, demuestra que el orden se respeta, que es la propiedad destructiva y es exactamente lo que un mock de orden de llamadas puede probar.
- [x] 11.6 `agent/tests/test_agent_config.py` (o archivo nuevo): `handle_update_config` reejecuta el preflight y actualiza el registry; el fallo de escritura del config lo marca en el registry y loguea a nivel error; el ack sigue siendo `ok`. Revisar antes la cobertura ya existente en `test_audit_fixes.py:250` y `test_stability_fixes.py:197,249` para no duplicar.
- [x] 11.7 Que el preflight no llama a `sys.exit` con ninguna clasificación, y que el arranque continúa con todos los paths degradados.

## 12. Tests — backend y frontend

- [x] 12.1 `action_error` se persiste tal cual; un valor desconocido no invalida el evento; ausente → `NULL`; no altera el status derivado ni la supersesión.
- [x] 12.2 Idempotencia de `008` y `009` (ejecutar cada `.sql` dos veces) y presencia de las columnas, copiando el molde de `backend/tests/test_event_severity.py:201-223`.
- [x] 12.3 `EventOut` expone `action_error` en `GET /events` y `GET /events/{id}`.
- [x] 12.4 El consumer de heartbeat persiste `watch_path_status`; clave ausente **no borra** el valor previo; valor malformado se ignora y el heartbeat se procesa igual (el agente no pasa a offline).
- [x] 12.5 `GET /agents` y `GET /agents/{id}` exponen el mapa; un agente que nunca reportó lo tiene en `null`.
- [x] 12.6 Vitest de `actionError.ts` y de `watchPathStatus.ts` siguiendo `frontend/src/utils/ackStatus.test.ts`, incluido el fallback al literal crudo.
- [x] 12.7 Correr las tres suites completas (backend, agente, frontend) y confirmar que no hay regresiones fuera de las actualizaciones deliberadas.

## 13. Verificación manual en host real (NO simulable — checklist obligatorio)

Estos cinco puntos **no se pueden probar sin root ni sin systemd**. Están declarados como verificación manual a propósito. **Prohibido cerrarlos con un mock que siempre pasa**: un test que parchea `os.chown` a un no-op y afirma que "se llamó" demuestra que el código invoca la función, no que la restauración funcione.

- [ ] 13.1 Las cinco ambient capabilities están efectivamente otorgadas: `grep Cap /proc/$(systemctl show -p MainPID --value fim-agent)/status` + `capsh --decode=<valor>`.
- [ ] 13.2 `statvfs` reporta `ST_RDONLY` para un path fuera de `ReadWritePaths` **dentro del namespace del servicio**, y no lo reporta para uno cubierto por el drop-in. Es la asunción central de D-3 del design; verificarla con `systemd-run --unit=probe --property=... ` o con un script corrido bajo el mismo unit.
- [ ] 13.3 `os.chown` restaura uid/gid reales: modificar un archivo root-owned bajo un `watch_path`, dejar que el `auto_restore` corra, y verificar con `stat` que dueño y grupo volvieron a los del baseline.
- [ ] 13.4 El bit setuid sobrevive: mismo ejercicio sobre un binario setuid de prueba, verificando que el bit sigue puesto tras la restauración.
- [ ] 13.5 `install.sh` de punta a punta sobre un host limpio: unit + config + drop-in + servicio habilitado; segunda corrida para confirmar idempotencia; `systemd-analyze security fim-agent.service` y registrar el score antes/después; y el arranque en frío sin secreto de bootstrap terminando en `failed` con exit 78 y **sin** loop de reinicios.
- [ ] 13.6 Verificación end-to-end de la demo: un `auto_restore` exitoso nace `auto_restored` (cierra el bloqueo que C40 dejó declarado), y un path no cubierto por el drop-in aparece como solo-detección en la tarjeta del agente.

## 14. Documentación canónica

- [x] 14.1 RN-51 (`docs/reglas_de_negocio.md:378-382`): actualizar la mención a `ProtectSystem=strict`/`NoNewPrivileges`/`PrivateTmp` para reflejar el `ReadWritePaths` derivado y el set de capabilities, con referencia a D36/RN-130.
- [x] 14.2 `docs/arquitectura_stack.md:183-209`: corregir el unit de ejemplo para que coincida con el unit real (capabilities completas, `ExecStart` real, `EnvironmentFile`, `RestartPreventExitStatus`) y actualizar las viñetas explicativas de `:206-209`. La corrección va del unit real hacia el doc, no al revés: si el doc menciona `ProtectHome=true` y el unit no lo tiene, gana el unit.
- [x] 14.3 `docs/flujo_de_usuario.md:790`: actualizar la fila de limitaciones técnicas, y agregar la limitación conocida de D36 (un `watch_path` agregado en caliente queda monitoreado pero no remediable hasta regenerar el drop-in en el anfitrión).
- [x] 14.4 `docs/operations.md:153-227`: reescribir la sección de despliegue para que refleje la realidad. Está desfasada por cuatro motivos independientes: (a) dice que hace falta `pyfanotify` 0.3.0, cuando el agente usa un backend propio sobre syscalls crudas (`agent/_fanotify.py`, ver el comentario de `agent/requirements.txt`); (b) `User=root`, cuando el servicio corre como `fim-agent`; (c) `ProtectSystem=full`, cuando es `strict`; (d) `ExecStart ... -m agent.bootstrap.main`, un entrypoint que no existe (`-m agent`). El archivo de entorno documentado (`:205-227`) tampoco corresponde: `AGENT_ID`, `WATCH_PATHS`, `VALKEY_URL` y los paths de certificados viven en `config.yaml`, no en el environment; lo único que va ahí es `FIM_BOOTSTRAP_SECRET`.
- [x] 14.5 Documentar en `operations.md` el procedimiento de regeneración del drop-in tras cambiar `watch_paths` desde la interfaz, que es la contraparte operativa de la limitación conocida de D36.

## 15. Roadmap y cierre

- [x] 15.1 Agregar la fila 41 a la tabla resumen de `CHANGES.md` y su sección detallada `### Change 41 — \`agent-deployment-caps\``, declarando la dependencia de 40 (hecho en la fase de propose). Actualizar el estado al archivar, si corresponde.
- [x] 15.2 Aplicar `008` y `009` a la base de desarrollo/demo con `psql $DATABASE_URL -f ...` — no hay runner automatizado (D3).
- [ ] 15.3 Seguir el orden de despliegue del design: migraciones → backend → frontend → agente (`install.sh` + `daemon-reload` + `restart` en cada host).
- [ ] 15.4 Commits convencionales, sin atribución a IA. Slices sugeridos: (a) funciones puras del agente + tests puros, (b) unit + drop-in + `install.sh` + propiedad, (c) restauración con metadata + vocabulario de razones + tests de filesystem, (d) preflight + heartbeat, (e) backend (columnas, migraciones, ingesta, consumer), (f) frontend, (g) docs canónicas + roadmap.
- [ ] 15.5 Abrir los follow-ups identificados en la proposal como su propia change, sin implementarlos acá: la verificación tautológica de hash post-restauración (`agent/decision.py:184-186`, hashea el buffer en memoria contra sí mismo en vez de releer el disco), las dos implementaciones divergentes de cuarentena, y el `cp -r` no idempotente de `agent/install.sh:50` (una segunda corrida anida `/opt/fim-agent/agent/agent`).
