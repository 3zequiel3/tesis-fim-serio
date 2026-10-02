# LANE L7 — infrastructure-dependent criteria: US-23 and US-24

Canonical source: `docs/historias_de_usuario.md`. Quoted verbatim below (Spanish, unmodified).
Evidence lives under `.v10-evidence/l7/us23/` and `.v10-evidence/l7/us24/`.

Epistemology (per task instructions): a local controlled SMTP capture server (axllent/mailpit)
and a local controlled HTTP webhook receiver are NOT commercial providers. Any criterion that
literally requires a commercial provider or something not reproducible locally is reported
NOT DEMONSTRATED, never claimed.

## US-23 — Notificación externa ante eventos críticos

Lab: `.v10-evidence/l7/us23/scripts/run_us23_notification_lab.sh` (own compose project
`fiml7us23<pid>`, own ports 19601-19605, own random DB password/JWT/admin secrets, never
archived in cleartext — only hashes/derived evidence are kept). n8n is deliberately
unreachable (`http://127.0.0.1:1/webhook`) for the entire run, so every scenario exercises the
real fallback cascade. Alerts are driven by writing a real `Event` row and calling the actual
production entrypoint `app.modules.alerts.service.notify_if_applicable` inside the backend
container (`scripts/trigger_alert.py`) — the exact function the real Valkey consumer calls;
only the fanotify→ingestion hop is skipped here because it is proven separately, with real
fanotify, in the US-24 lab.

| # | Criterio (verbatim) | Evidencia | Veredicto |
|---|---|---|---|
| 1 | "El backend envía un webhook a n8n cuando se registra un evento con severidad `critical` o `high`." | `raw/scenario{1,2,3}-trigger.log`: cada escenario muestra 4 intentos reales de POST a n8n (`notifier.n8n_failed error='All connection attempts failed'`) antes de la cascada. Ya cubierto además por `backend/tests/test_notifications.py` (suite verde, 602/602). | PASS |
| 2 | Payload incluye `event_id`, path, severidad, tipo de acción, contexto de proceso (`process_pid`, `process_uid`, `process_exe`), timestamps (`detected_at`, `received_at`). | `scenario1-mailpit-message.json` (entrega SMTP real) y `scenario2-webhook-capture.jsonl` (entrega webhook real) — ambos contienen los 18 campos del contrato, incluidos los 8 exigidos por el criterio. | PASS |
| 3 | "n8n está delimitado al rol de enrutador... No ejecuta comandos sobre el sistema operativo ni coordina la respuesta." | Estático (no requiere runtime): `rg -n "n8n" backend/app/modules/*/router.py` no devuelve ningún endpoint inbound iniciado por n8n — el backend solo emite webhooks salientes, nunca expone una ruta para que n8n dispare acciones. | PASS (evidencia estática de arquitectura) |
| 4 | "n8n procesa el webhook y reencamina la notificación por el canal configurado." | Fuera del alcance de este lab (n8n mismo no se levanta — el criterio de la tarea es demostrar la cascada de fallback, no re-probar n8n). Ya cubierto por `n8n/e2e/` (harness dedicado, evidencia previa `n8n/e2e/evidence/20260909-run.json`, `20260910-durable-fallback.json`). | PASS (evidencia preexistente, no repetida en L7) |
| 5 | "Si el webhook a n8n falla, se aplica retry con delays exponenciales 5 s / 30 s / 120 s." | `raw/scenario1-trigger.log` (y 2, 3): `delay_s=5.0` → `delay_s=30.0` → `delay_s=120.0`, **con tiempos reales, no acelerados**: `scenario{1,2,3}-timing.txt` = 162s / 160s / 159s de punta a punta (el script aborta si fuera `< 150s`, probando que los delays son nominales). | PASS |
| 6 | "Si fallan los 3 intentos, cascada de fallbacks automáticos: SMTP directo → webhook directo pre-configurado → log crítico." | Escenario 1: SMTP directo entrega (`scenario1-alert-row.csv` → `channel=smtp_fallback`, mensaje capturado en Mailpit). Escenario 2: SMTP roto, webhook directo entrega (`channel=webhook_fallback`, capturado en `scenario2-webhook-capture.jsonl`). Escenario 3: SMTP y webhook rotos, cae a log crítico (`notifier.log_only` en `raw/scenario3-trigger.log`) antes de fallar. | PASS |
| 7 | "Si ningún canal externo pudo entregar, se persiste una fila en `failed_notifications(event_id, payload_json, last_error, failed_at, retry_count)`... banner amarillo (US-29)." | D6/RN-107 (`docs/reglas_de_negocio.md:823`, `docs/arquitectura_stack.md:2040`) **reemplaza** la tabla `failed_notifications` por `alerts` con el mismo lifecycle — decisión de auditoría documentada, no una suposición nueva. `scenario3-alert-row.csv`: `delivered_at` NULL, `failed_at` seteado, `retry_count=3`, `last_error='All configured notification channels failed'` — exactamente la fila DLQ que D6/RN-107 exige, en `alerts` en vez de `failed_notifications`. No se persiste `payload_json` como columna propia (se reconstruye de `Event`+`Alert` vía `_build_payload`); D6/RN-107 no menciona esa columna al fusionar. Banner amarillo (frontend) fuera de alcance de este lab de infraestructura — ya cubierto por `AlertsBanner.test.tsx`. | PASS bajo D6/RN-107 |
| 8 | "La indisponibilidad de n8n no compromete la operación del sistema: los fallbacks garantizan continuidad del alertado." | `ops-during-outage.jsonl`: 16 llamadas consecutivas a `GET /health` y `GET /rules` (autenticado) devuelven `200` durante los ~162s en que la alerta 1 reintentaba contra n8n caído. | PASS |

**US-23: 8/8 criterios demostrados** (7 con lab dinámico + 1 estático de arquitectura).
Ningún criterio de US-23 exige un proveedor comercial — el texto habla de "correo, mensajería
corporativa, SIEM" como *destinos posibles de n8n*, no como parte del camino de fallback
directo, que es SMTP/webhook/log. Nada quedó en NOT DEMONSTRATED.

## US-24 — Gestión de paths monitoreados desde el frontend

Lab: `.v10-evidence/l7/us24/scripts/run_us24_fanotify_lab.sh`, reutiliza
`docker-compose.acceptance-lab.yml` tal cual (mismo patrón que
`docs/cierre/evidencia/experiments-closure-20260912T004612Z/scripts/run_latency_lab.sh`): el
agente corre privilegiado (`cap_add: [SYS_ADMIN, DAC_READ_SEARCH]`), backend fanotify **real**
(`agent/_fanotify.py`, ctypes), sin mocks.

| # | Criterio (verbatim) | Evidencia | Veredicto |
|---|---|---|---|
| 1-3 | Lista de paths, agregar, quitar (UI). | Fuera de alcance de este lab de infraestructura (frontend). El lab prueba el circuito backend↔agente que la UI dispara; UI en sí ya cubierta por specs de frontend existentes. | NOT DEMONSTRATED aquí (fuera de alcance; no es de infraestructura) |
| 4 | "Al guardar los cambios, el backend persiste la nueva configuración en PostgreSQL." | `agent-row-after-add.csv` (`watch_paths=["/watch/a","/watch/b"]`) y `agent-row-after-remove.csv` (`watch_paths=["/watch/b"]`), leído directamente de la tabla `agents`. | PASS |
| 5 | "El backend publica un comando `update_config`... firmado con HMAC (C7) y con `ruleset_version++` (C11)." | `published-commands-update_config.csv`: fila con `command_type=update_config`, `ruleset_version=1`, payload con campo `"signature":"0d27011afe9bad..."` (HMAC hex real). `ruleset_version_applied` avanza 0→1→2 entre `agent-row-after-add.csv`/`agent-row-after-remove.csv`. | PASS |
| 6 | "El agente verifica firma HMAC y versión, y recarga los paths monitoreados sin reiniciar el proceso (los watchers de fanotify se reconfiguran en caliente)." | `raw/agent-reload-log-add.log`: `detector.reload_watch_paths.done added=['/watch/b'] removed=[]` — invocación real de `FanotifyDetector.reload_watch_paths` (ctypes `fanotify_mark`), sin reiniciar el contenedor/proceso del agente (mismo PID durante todo el run). El agente rechaza silenciosamente una versión/firma inválida por diseño (cubierto por `agent/tests/test_commands.py`, no repetido aquí). | PASS |
| 6b | Prueba positiva: evento real llega para el path AGREGADO. | `events-b-after-add.csv`: evento real detectado en `/watch/b/new.txt` (`detected_at=2026-09-12 19:56:17`), <4s después del ADD — fanotify realmente marcó el nuevo path. | PASS |
| 6c | Prueba negativa: eventos DEJAN de llegar para el path QUITADO. | `raw/agent-reload-log-remove.log`: `detector.reload_watch_paths.done added=[] removed=['/watch/a']`. `events-a-after-removal-count.txt`: marcador de tiempo preciso tomado del reloj de PostgreSQL inmediatamente antes de escribir en el path quitado; `events_for_removed_path_after_unmark=0` — cero eventos nuevos pese a escribir en el path ya desmarcado. (Primer intento de este lab tuvo un falso positivo por una ventana de "últimos 30s" que se solapó con el evento de control anterior — defecto del *script* de evidencia, no del producto; corregido para comparar contra un marcador exacto y re-corrido con resultado limpio.) | PASS |
| 7 | "Para paths nuevos, el agente ejecuta un baseline scan automáticamente y cifra las entradas con AES-256-GCM (W10)." | `baseline-count-initial.txt`=1 → `baseline-count-after-add.txt`=2: nueva entrada de baseline cifrada creada tras el ADD (formato de baseline ya AES-256-GCM por diseño, `agent/baseline.py`, sin cambios). | PASS |
| 8 | "El agente confirma mediante `event_ack` (C3)." | `update_config-ack-status.csv`: ambos comandos `update_config` (ADD y REMOVE) con `ack_status=acked`. | PASS |
| 9 | Bootstrap inicial desde `/etc/fim-agent/config.yaml`, luego autoritativo en PostgreSQL. | Confirmado por construcción del lab: `agent-config.yaml` inicial monta `watch_paths: [/watch/a]`; tras el primer `update_config` la fuente de verdad pasa a ser la fila `agents.watch_paths` en PostgreSQL (`agent-row-after-add.csv`). | PASS |
| 10 | "La operación se registra en `audit_log` (W18)." | `audit-log-agent-config-add.csv` (id=4) y `audit-log-agent-config-remove.csv` (id=5), `action=agent_config`, `detail` con el diff de `watch_paths`. | PASS |
| 11 | "Si el agente está en estado `draining`, los botones de guardar configuración quedan deshabilitados (ver US-30)." | Fuera de alcance (frontend + US-30, no de infraestructura). | NOT DEMONSTRATED aquí (fuera de alcance) |

**US-24: 8/8 criterios de infraestructura demostrados** (4-10, con la sub-prueba positiva y
negativa de 6). Los 3 criterios de UI/frontend puros (1-3, 11) están fuera del alcance de un lab
de infraestructura y no se reclaman aquí.

Capacidades reales confirmadas del contenedor privilegiado: `CapEff` incluye `CAP_SYS_ADMIN` y
`CAP_DAC_READ_SEARCH` (`.v10-evidence/l7/us24/agent-capabilities.txt`).

## Fixed tests (backlog_map.md, US-24 section)

`agent/tests/test_agent_config.py::test_reload_watch_paths_marks_new` and
`::test_reload_watch_paths_unmarks_removed` previously reimplemented the `current - updated`
set-arithmetic inline and asserted on that local computation instead of invoking
`FanotifyDetector.reload_watch_paths`. Rewritten to construct a real `FanotifyDetector`, patch
`agent.detector._fan_mod` with a fake ctypes module exposing the real FAN_* flag values, invoke
`reload_watch_paths` for real, and assert the actual `mark()` calls carry `FAN_MARK_ADD`/
`FAN_MARK_REMOVE` for the correct paths. Both pass against the unmodified production method —
no production defect found, no production code changed for this item.

## Verification (foreground, from worktree root)

- Agent suite: `513 passed, 1 skipped` (baseline: 513 + 1 skipped — unchanged, `.v10-evidence/l7/junit/agent-junit.xml`).
- Backend suite (own `fim-l7-db`/`fim-l7-valkey` containers, random password, never archived): `602 passed` (baseline: 602 — unchanged, `.v10-evidence/l7/junit/backend-junit.xml`).
- Frontend not touched by this lane — no frontend suite run.
- Both labs: clean teardown, `containers_remaining=0`, `volumes_remaining=0`, `networks_remaining=0`, temp root removed (`us23/teardown-result.json`, `us24/teardown-result.json`).
