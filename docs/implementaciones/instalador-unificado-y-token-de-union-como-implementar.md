# Instalador unificado y token de unión — cómo implementarlo

> Documento de exploración (sin implementación). Complementa
> `docs/implementaciones/instalador-unificado-y-token-de-union.md` (en adelante, «el documento
> fuente»), que define **qué** construir. Este documento define **cómo**: verificación del documento
> fuente contra el código, descomposición en changes de OPSX, decisiones a cerrar antes de
> `/opsx:propose`, diseño técnico, deltas de specs, pruebas, revisión de seguridad, orden y efecto en
> la tesis.
>
> No es documentación canónica. Las entradas D/RN de §3 son **borradores**: no están escritas en
> `docs/reglas_de_negocio.md` ni en `docs/arquitectura_stack.md`. Los números de change de §2 son
> **propuestas**: `CHANGES.md` no se modificó.
>
> Estado leído: rama `devel`, 2026-09-15. `vps-deployment-readiness` se trata como contexto de solo
> lectura (otra sesión la está cerrando).

## 0. Resumen

- El documento fuente es correcto en lo esencial, pero tiene **tres errores con consecuencias de
  diseño**:
  1. `AgentStatus` **ya tiene** un estado de baja, `revoked`
     (`backend/app/modules/agents/models.py:12-17`). Los consumers ya lo aplican (D26/RN-122); lo que
     falta es quién lo escriba.
  2. Las migraciones **no se aplican al arrancar**: el lifespan sólo corre `create_all`
     (`backend/app/main.py:82`) y los SQL de `backend/db/migrations/` se aplican a mano. Una
     actualización con reversión necesita primero un ejecutor de migraciones.
  3. El descubrimiento de la CA «leyendo la cadena del handshake» no está garantizado. Es más robusto
     un endpoint que sirva `ca.pem` y verificar su huella fijada en el token.
- Los puertos de agente pueden parametrizarse **sólo del lado del host** (`"${AGENT_MTLS_PORT:-8443}:8443"`)
  sin tocar `pki.py` ni `main.py`. El cambio es mucho más chico que el que propone el documento fuente.
- Descomposición propuesta: **siete changes obligatorios (53 a 59) y tres opcionales (60 a 62)**.
- **Primera entrega recomendada**: la **53 — `agent-decommission-and-revocation`**. No depende del
  instalador ni de que `vps-deployment-readiness` esté archivado, y cierra una divergencia real entre
  spec y código.
- Hay **diez decisiones** que cerrar (D63 a D72, con tres más para los changes opcionales). **Siete
  necesitan que decida el usuario.**

---

## 1. Verificación del documento fuente

### 1.1 Estado de `vps-deployment-readiness` hoy

- `openspec list --json`: **72/78 tareas**. El documento fuente leyó 64–68/78.
- Las seis tareas pendientes son todas del grupo 13, que es sólo validación: `openspec validate`,
  `check_spec_integrity.py`, suites completas y commits
  (`openspec/changes/vps-deployment-readiness/tasks.md:117-121`). La implementación funcional está
  terminada.
- Desde la lectura del documento fuente se agregaron los hallazgos 14.1–14.8 de la aceptación en VPS
  (`tasks.md:106-113`) y la evidencia A-4
  (`tesis/cierre/evidencia/a4-vps-acceptance-20260915T153824Z`, `tasks.md:100`). Afectan a esta
  propuesta así:
  - **14.3**: reinstalar un agente enrolado ya no exige el secreto
    (`agent/installer.py:189` `is_already_enrolled`, `:212` `secret_required`). Esto cubre la fila
    `repair` del agente en la matriz §4.11.3 del documento fuente.
  - **14.5**: el provisioning de n8n pasó al entrypoint del contenedor `n8n`. Cambiar canales de n8n
    **recrea el contenedor**, así que no pueden ser «configuración en caliente» (ver D72).
  - **3.4**: los puertos publicados quedaron **fijados por test**:
    `scripts/tests/test_compose_topology.py` afirma «consola + 8443 + 8444 + 6380» (`tasks.md:25`).
    Parametrizarlos modifica un requisito que introduce este mismo change (delta
    `openspec/changes/vps-deployment-readiness/specs/infra-compose/spec.md:37`). **Hay que esperar a
    que se archive.**
- Hay otro change activo que el documento fuente no menciona: **50 — `backend-agent-cert-renewal`**
  (1/26 tareas en OpenSpec). Toca `agents/router.py`, `agents/service.py` y `core/pki.py`, igual que
  esta propuesta.
  - Parte de su código ya está en el árbol: `POST /agents/renew` (`backend/app/modules/agents/router.py:62-105`)
    e `issue_certificate_for_public_key` (`backend/app/core/pki.py:555`).
  - `CHANGES.md:1080` ya registra la coordinación 50↔52. Toda change de este documento que toque esos
    archivos debe declararla también.

### 1.2 Afirmaciones verificadas

| # | Afirmación del documento fuente | Veredicto | Evidencia actual |
|---|---|---|---|
| 1 | 8443/8444/6380 fijos en compose, `pki.py`, `main.py` e instalador | **Confirmada** | `docker-compose.yml:295-296`; `docker-compose.tls.yml:51,55`; `backend/app/core/pki.py:643` (`port: int = 8443`), `:698` (`port: int = 8444`); `backend/app/main.py:85-95` sin `port=`; `agent/installer.py:149-156` (`derive_urls`), `:58-61` (`SCOPE_CHECK_PORTS`). Matiz: ahora están además fijados por test y spec (§1.1). |
| 2 | No existen `AGENT_MTLS_PORT`, `AGENT_BOOTSTRAP_PORT`, `VALKEY_TLS_PORT` | **Confirmada** | Sin coincidencias en `backend/app/core/config.py`, `docker-compose.yml` ni `docker-compose.tls.yml`. |
| 3 | Secreto de bootstrap de un solo uso y sin TTL | **Confirmada** | `backend/app/modules/agents/service.py:80` (`bootstrap_secret_hash = None`); `Agent` sin columna de expiración (`models.py:20-44`). No existe ningún concepto de token de unión en `backend/`. |
| 4 | `revoked_certificates` sin escritor | **Confirmada en producción** | Ningún código de `backend/app` instancia `RevokedCertificate`; sólo un fixture de test (`backend/tests/test_agent_cert_renewal.py:114`). `is_revoked` (`pki.py:612-621`) sólo se usa en `/agents/renew` (`router.py:85`). |
| 5 | «`AgentStatus` no tiene un estado de baja (`models.py:24`)» | **Incorrecta** | El enum (`models.py:12-17`) incluye `revoked`, agregado por `backend/db/migrations/001_add_agent_status_revoked.sql`. `models.py:24` es la columna `status`, no el enum. Ver §1.3. |
| 6 | El router sólo expone `register`, `/config` y `/rescan` | **Desactualizada** | También `POST /agents/renew` (`router.py:62`, montado en `mtls_app`, `main.py:47-48`), `POST /agents/bootstrap` (`router.py:118`, en `bootstrap_app`, `main.py:50-51`), `GET /agents` (`:133`) y `GET /agents/{agent_id}` (`:143`). |
| 7 | No existe desinstalación | **Confirmada** | Sin coincidencias de `uninstall` en `agent/install.sh`, `agent/installer.py`, `scripts/` ni `docs/despliegue_servidor_remoto.md`. |
| 8 | SMTP y n8n se leen de `settings` | **Confirmada** | `config.py:91` (`n8n_webhook_url`), `:102` (`n8n_health_url`), `:104-109` (`smtp_*`), `:119-120`. Los consumidores leen `settings.*` directamente: `backend/app/modules/alerts/service.py:222,311,315`; `backend/app/core/health.py:153,183,206`. No existe `system_settings`. |
| 9 | El webhook por agente `dead` sólo existe en `integration/v10` | **Confirmada** | `_sweep_offline` (`backend/app/modules/agents/heartbeat_consumer.py:164-196`) sólo cambia el estado (`:191`) y registra un log (`:194`), sin llamadas a n8n. |
| 10 | «Las migraciones se aplican al arrancar el backend» (§4.11.7, paso 3) | **Incorrecta** | El lifespan corre `SQLModel.metadata.create_all(engine)` (`main.py:82`). Eso crea tablas nuevas, pero no altera enums ni columnas. Los SQL `001`–`014` se aplican con `psql` a mano (encabezado de `001_add_agent_status_revoked.sql`). No hay ejecutor en compose ni en la imagen. Convención «sin Alembic» (D29 en `docs/reglas_de_negocio.md`, apoyada en D3). |
| 11 | D62/RN-156 es la última decisión cerrada | **Confirmada** | `docs/reglas_de_negocio.md:1993`; `docs/arquitectura_stack.md:2685`. Siguiente libre: **D63/RN-157**. |
| 12 | Change 53, dependiente de 52 y 06 | **Incompleta** | 52 es el último número (`CHANGES.md:1080`). Faltan la coordinación con 50 y las dependencias de frontend y outbox (§2). |
| 13 | La unidad tiene `Restart=on-failure` / `RestartSec=5s` (`fim-agent.service:48`) | **Confirmada, con línea corrida** | `agent/deploy/fim-agent.service:48` (`Restart`), `:49` (`RestartSec`), sin `StartLimit*`. Agrega `RestartPreventExitStatus=78` (`:56`). |
| 14 | Tabla de residuos del agente | **Incompleta** | Falta `/var/lib/fim-agent/discarded/`, que también crea `agent/install.sh` en el bucle de directorios, después de `useradd` (`:126-132`). |
| 15 | Citas de la guía de despliegue | **Líneas corridas** | Tras 14.8, las reglas `iptables` están en `docs/despliegue_servidor_remoto.md:189-194` (antes `:136-145`); el `up -d` en `:146` (antes `:107`); el registro en §6 (`:203`); la instalación en §7 (`:227`); la reinstalación en §9 (`:274`, antes `:218-238`); la renovación del certificado de la consola en §11 (`:328-335`, antes `:240-247`). |
| 16 | Citas de `scripts/prepare_server_env.py` | **Líneas corridas** | Puertos de consola en `:290-291` (antes `:287-288`); rechazo de `.env` existente en `:313` (antes `:310-312`); `O_EXCL` en `:254-263`; SMTP vacío en `:373-380` (antes `:370-377`); `derive_cors_origins` en `:158`. |

### 1.3 Hallazgos que el documento fuente no recoge

1. **Ya hay una revocación a nivel aplicación, y está normada.**
   - La regla es **D26/RN-122** (`docs/reglas_de_negocio.md:1040-1052`).
   - Se aplica en el consumer de eventos (`backend/app/modules/events/consumer.py:299-304`, resuelto
     en `_get_agent_auth`, `:473-488`), en el de heartbeats (`heartbeat_consumer.py:93-96`) y en la
     renovación (`router.py:83-84`).
   - El barrido `offline`→`dead` sólo selecciona `online`/`draining`/`offline`
     (`heartbeat_consumer.py:176-190`), así que **un agente `revoked` nunca pasa a `dead`**.
   - El frontend ya conoce el estado: `frontend/src/api/agents.ts:5`, `frontend/src/api/dashboard.ts:64`,
     `frontend/src/components/ui/AgentCard.tsx:20`, `frontend/src/pages/Dashboard.tsx:31,39`.
   - **No hay ningún escritor de `status = revoked` en producción.** La pregunta 7 del documento fuente
     (§8) está parcialmente cerrada por D26.
2. **Spec y código divergen en la revocación.** La main spec `backend-pki`, requisito «Certificate
   revocation check» (`openspec/specs/backend-pki/spec.md:30-39`), exige verificarla «en cada
   handshake mTLS». El código no lo hace (`pki.py:638-690` sólo usa `CERT_REQUIRED`), y D26 lo declara
   como limitación conocida. La change de baja tiene que **modificar** ese requisito, no sólo agregar
   escritura.
3. **El backend no guarda el serial de los certificados que emite.**
   - `bootstrap_agent` emite (`service.py:67`) y `renew_certificate` emite (`router.py:100-105`),
     pero ninguno persiste el serial.
   - `RevokedCertificate.serial_number` es `str` y `is_revoked` compara con `str(serial)`
     (`pki.py:619`).
   - Para revocar «el certificado del agente» hace falta un registro de emisiones. Si no, sólo queda
     `status = revoked`.
4. **`audit_log.user_id` es `NOT NULL` con FK a `users.id`** (`backend/app/modules/audit/models.py:14`).
   Una baja iniciada por el propio agente, o por `register-agent.sh` (que no autentica a un
   administrador, `scripts/register-agent.sh:8-9`), no tiene usuario. Ver D65.
5. **Cancelar comandos pendientes no es trivial.**
   - `PublishedCommand` tiene dos estados ortogonales: `status` (`pending|published`) y `ack_status`
     (`pending|acked|failed|timeout`) (`backend/app/modules/rules/models.py:89,94`), con
     `target_agent_id` (`:85`).
   - El despachador publica los `pending` (`backend/app/modules/rules/service.py:188-207`) y el
     barrido de timeouts cierra los `ack_status=pending` (`command_ack_consumer.py:329`).
   - «Purgar los comandos» de un agente dado de baja toca la derivación del estado de los eventos con
     acciones en curso (change 40, `event-status-contract`).
6. **La instalación del agente ya tiene un arnés de integración reutilizable.**
   - `agent/tests/integration/test_install_sh_container.py` corre el `install.sh` real como root en un
     contenedor descartable, con un *shim* de `systemctl`
     (`agent/tests/integration/docker/systemctl`, `docker/Dockerfile`), en once escenarios (`:148-382`).
   - Es la base natural para probar la desinstalación sin residuos. No hace falta partir de un
     contenedor con systemd real.
7. **Observación fuera de alcance.** El texto de la change 50 en `CHANGES.md` (bloque
   `:1021-1048`) describe una «ventana de gracia de 30 días» y el paso a `CERT_OPTIONAL`. La D48/RN-142
   vigente dice lo contrario: `CERT_REQUIRED`, sin gracia (`docs/reglas_de_negocio.md:1680-1682`), y
   el código coincide con D48. No afecta esta propuesta, pero conviene corregir el roadmap.

---

## 2. Descomposición en changes de OPSX

### 2.1 Convenciones de `CHANGES.md`

- Tabla resumen con columnas `| # | Change ID | Capa | Hito | Depende de |`. Los changes posteriores
  al 20 usan en `Hito` una etiqueta de origen, por ejemplo `— (auditoría 2026-06-26)`.
- Cada entrada va con el formato `### Change NN — \`nombre\``. La primera línea es
  `**Capa**: … · **Depende de**: NN (\`nombre\`) · **Coordina con**: … · **Origen**: … · **Decisiones**: DNN/RN-NNN`.
- Le siguen los bloques `> **Nota**`, `Capacidades:`, `Reglas:`, `> **Diseño**` y `**Done**`
  (ejemplos en `CHANGES.md:1021` y `:1080`).
- Último número: **52**.

### 2.2 Changes propuestos

| # | Change ID | Capa | Depende de | Coordina con | Tamaño estimado | ¿Antes de archivar 52? |
|---|---|---|---|---|---|---|
| 53 | `agent-decommission-and-revocation` | backend + frontend + base | 06, 14, 19, 36, 42 | 50 (`router.py`, `pki.py`, delta `backend-pki`) | 24–28 tareas | **Sí**: propose y apply. Archivar después de 52 (ambos aportan delta a `backend-pki` y `backend-agents`). |
| 54 | `agent-port-parameterization` | infra + agente + scripts | 52 | — | 12–16 tareas | **No**: modifica requisitos que 52 introduce (`infra-compose`, `remote-deployment`, `agent-core`) y el test de topología. |
| 55 | `agent-join-tokens` | backend + agente + frontend + base | 52, 54, 53 | 50 (`bootstrap_app`, `router.py`) | 32–38 tareas | Propose sí; **apply no**: extiende el contrato del instalador D56 que 52 todavía valida. |
| 56 | `agent-lifecycle-commands` | agente + backend | 52, 53 | 55 (reconfigurar con token) | 24–28 tareas | **No**: reestructura `agent/install.sh`. |
| 57 | `server-unified-installer` | scripts + infra | 52, 54, 55 | 56 | 26–30 tareas | **No**. |
| 58 | `server-upgrade-backup-and-uninstall` | scripts + infra + backend | 57, 53 | — | 28–32 tareas | **No**. |
| 59 | `console-runtime-settings` | backend + frontend + base | 15, 19, 46, 48 | 52 (`config.py`, ya estable) | 26–30 tareas | Propose sí; apply recomendado después, para no mezclar el candidato de validación de 52. |
| 60 *(opcional)* | `console-letsencrypt-mode` | infra + frontend | 57, 52 | — | 16–20 tareas | No. Reabre un Non-Goal de 52 (`design.md:28`). |
| 61 *(opcional)* | `console-subpath` | frontend + backend + infra | 52 | 60 | 18–22 tareas | No. |
| 62 *(opcional)* | `server-web-setup` | scripts | 57 | — | 14–18 tareas | No. |

Capa y dependencias en formato de tabla resumen:

```
| 53 | `agent-decommission-and-revocation` | backend + frontend | — (despliegue y ciclo de vida) | 06, 14, 19, 36, 42 |
| 54 | `agent-port-parameterization`       | infra + agente     | — (despliegue y ciclo de vida) | 52 |
| 55 | `agent-join-tokens`                 | cross              | — (despliegue y ciclo de vida) | 52, 53, 54 |
| 56 | `agent-lifecycle-commands`          | agente + backend   | — (despliegue y ciclo de vida) | 52, 53 |
| 57 | `server-unified-installer`          | scripts + infra    | — (despliegue y ciclo de vida) | 52, 54, 55 |
| 58 | `server-upgrade-backup-and-uninstall` | scripts + infra + backend | — (despliegue y ciclo de vida) | 53, 57 |
| 59 | `console-runtime-settings`          | backend + frontend | — (despliegue y ciclo de vida) | 15, 19, 46, 48 |
| 60 | `console-letsencrypt-mode` (opcional) | infra + frontend | — (opcional) | 52, 57 |
| 61 | `console-subpath` (opcional)        | cross              | — (opcional) | 52 |
| 62 | `server-web-setup` (opcional)       | scripts            | — (opcional) | 57 |
```

### 2.3 Grafo

```
   06 ─┐ 14 ─┐ 19 ─┐ 36 ─┐ 42 ─┐          15 ─ 19 ─ 46 ─ 48
       └─────┴─────┴─────┴─────┴──► 53                  │
                                   │  │                  ▼
   52 (vps-deployment-readiness) ──┼──┼──► 54            59
     │  (archivar primero)         │  │     │
     │                             │  ▼     ▼
     ├──────────────────────────► 56     55 ◄── 53
     │                             │      │
     └──────────────────────────► 57 ◄────┘ (usa 54 y 55)
                                   │
                                   ▼
                                   58 ◄── 53
                                   │
                  opcionales:  60 ◄┘   61 ◄── 52   62 ◄── 57
```

### 2.4 Por qué se divide así (y no como en §9 del documento fuente)

- **P1+P2+P3+P4 (puertos + token backend/agente/UI)** se separan en **54** y **55**. El 54 es chico y
  mecánico, y su riesgo es de topología. El 55 introduce credenciales de un solo uso y merece su propia
  auditoría. Unirlos haría que un defecto de compose bloquee la revisión de seguridad del token.
- **P11 (baja y revocación)** pasa a ser la **53** y va primero. Es la única pieza que:
  - no depende del instalador;
  - cierra una divergencia spec↔código (`backend-pki`);
  - es condición de la desinstalación del agente (56) y del servidor (58).
- **P12 y P13** se reparten por host: **56** (agente) y **58** (servidor). Comparten principios (D69,
  D71) pero no código: bash + systemd en un caso, Docker + Postgres en el otro.
- **La configuración en caliente (59)** es independiente del instalador. Mezclarla con el ciclo de
  vida acoplaría la re-corrida de la batería de notificaciones con la de despliegue.

---

## 3. Decisiones a cerrar antes de `/opsx:propose`

Formato: el de las entradas vigentes de `docs/reglas_de_negocio.md`, con **Descripción / Motivo /
Condición / Resultado / Excepciones / Reglas afectadas** (ejemplo: D62/RN-156, `:1993-2019`). Cada una
tiene su contraparte técnica de una fila en `docs/arquitectura_stack.md`, en la tabla de
`:2685-2693`.

Al escribirlas hay que actualizar también:

- la fila del índice `RN-104 a RN-156` (`docs/reglas_de_negocio.md:32`);
- la lista de fechas del appendix (`:787`).

**Requiere decisión del usuario** marca las entradas con alternativas reales. Las demás tienen una
recomendación que puede aprobarse tal cual.

### D63 / RN-157: La baja de un agente reutiliza el estado `revoked` — **requiere decisión del usuario**

**Descripción:** Dar de baja un agente (desde la consola o desde su desinstalador) SHALL fijar
`Agent.status = revoked`. No se agrega un valor `decommissioned` a `AgentStatus`. El motivo se
registra en `RevokedCertificate.reason` y en `audit_log`, con el vocabulario `decommissioned` (baja
administrativa), `uninstalled` (baja iniciada por el agente) o `compromised` (sospecha de compromiso).
El historial de eventos, baseline y auditoría del agente se conserva.

**Motivo:** `revoked` ya existe en la base (migración `001`), en la spec `backend-agents`
(`openspec/specs/backend-agents/spec.md:61-90`), en los tres puntos de aplicación del backend y en los
tipos y colores del frontend (§1.3). Un valor nuevo exigiría:

- `ALTER TYPE agentstatus ADD VALUE`, que `create_all` no aplica (§1.2 #10);
- modificar los tres consumers para rechazar dos estados en lugar de uno;
- actualizar `frontend/src/api/agents.ts:5`, `frontend/src/api/dashboard.ts:64`,
  `frontend/src/components/ui/AgentCard.tsx:17-20` y `frontend/src/pages/Dashboard.tsx:28-39`.

Cada uno de esos puntos es un lugar donde olvidar el estado nuevo reabre la ingesta de un agente dado
de baja.

**Alternativa:** agregar `decommissioned` para distinguir en la UI «retirado» de «comprometido».
Costo: los cambios de arriba más un test de no-regresión por consumer. Beneficio: sólo presentación,
y `reason` ya lo cubre.

**Condición:** Toda transición a baja.

**Resultado:** Un agente dado de baja no publica eventos ni heartbeats con efecto, no pasa a `dead`
(`heartbeat_consumer.py:176-190`), no renueva (`router.py:83-84`) y aparece como `revoked` con su
motivo.

**Excepciones:** Re-enrolar un `agent_id` dado de baja se rige por D66.

**Reglas afectadas:** precisa D26/RN-122 (le da un escritor); no modifica RN-78.

### D64 / RN-158: Alcance de la revocación por canal — **requiere decisión del usuario**

**Descripción:** La baja SHALL:

- (a) insertar en `revoked_certificates` el serial de todo certificado emitido y no vencido para ese
  `agent_id` (requiere el registro de emisiones de §4.1);
- (b) hacer que **toda** ruta de `mtls_app` (8443) verifique, a nivel aplicación, estado del agente y
  serial no revocado mediante una dependencia común;
- (c) en Valkey (6380), mantener la revocación **a nivel aplicación** de D26/RN-122.

**Motivo:** Uvicorn con `ssl_cert_reqs=CERT_REQUIRED` (`pki.py:638-690`) no consulta una CRL durante el
handshake, y el stack no tiene OCSP ni CRL (Non-Goal de 52, `design.md:29`). En 6380, Valkey sólo
valida que la cadena termine en la CA (`docker-compose.tls.yml:55-59`, `--tls-auth-clients yes`).

**Brecha residual que se documenta:** un agente con certificado vigente y dado de baja **todavía puede
conectarse a Valkey**, hasta el vencimiento natural (90 días, RN-78). Con esa conexión puede:

- **leer** el stream compartido `commands` (`backend/app/core/streams.py:19`). Los comandos van
  firmados con HMAC pero no cifrados, y el filtro por `target_agent_id` lo aplica el propio agente
  (`agent/commands.py:127-131`), así que se exponen rutas y `event_id` de otros agentes;
- **escribir** mensajes, que se descartan en ingesta con el costo de CPU acotado por
  `rate_limit_ingest_events` (`config.py:83`).

**Alternativas para 6380:**

| Opción | Cierra lectura de `commands` | Costo | Nota |
|---|---|---|---|
| A. Aplicación (D26), documentar | No | Nulo | Recomendada para este ciclo |
| B. Usuario ACL de Valkey por agente, mapeado desde el CN del certificado | Sí (permisos de stream por usuario) | Alto: ACL por agente, alta y baja de usuarios en Valkey en cada enrolamiento y baja, `commands` por agente | **Verificar en un spike** si Valkey 9.0.3 mapea el certificado de cliente a un usuario ACL antes de considerarla |
| C. Streams de comandos por agente (`commands:<agent_id>`) + ACL | Sí | Alto: cambia el contrato D5, el cursor de comandos y el outbox | Fuera de alcance |
| D. Certificados de vida corta (p. ej. 7 días) | Acota la ventana | Medio: más renovaciones; depende de la change 50 | Complementaria |

**Condición:** Toda baja.

**Resultado:** 8443 rechaza al agente dado de baja con `403` (aplicación, no handshake). 6380 descarta
sus mensajes. La brecha de lectura queda declarada en la limitación de D26.

**Excepciones:** Ninguna.

**Reglas afectadas:** modifica la redacción del requisito «Certificate revocation check» de
`backend-pki`, alineándolo con D26; precisa RN-78.

### D65 / RN-159: Auditoría de acciones sin usuario humano — **requiere decisión del usuario**

**Descripción:** `audit_log` SHALL admitir entradas cuyo actor no es un usuario de la consola: el
agente, la CLI del servidor o el instalador. Se propone `user_id` nullable y una columna nueva
`actor TEXT NOT NULL DEFAULT 'user'`, con valores `user`, `agent:<agent_id>`, `cli` e
`installer`. Migración SQL idempotente.

**Motivo:** `AuditLog.user_id` es `NOT NULL` con FK (`audit/models.py:14`) y todas las altas lo
completan (`backend/app/core/audit.py:6-13`; `backend/app/modules/agents/service.py:174,241`). La baja
por mTLS, el acuñado desde `register-agent.sh` y la baja masiva del desinstalador del servidor no
tienen usuario.

**Alternativa:** un usuario de sistema sembrado (`system`, rol sin login). Costo: una fila falsa en
`users` que la UI de gestión de usuarios muestra y que un reset de contraseña podría activar. Se
desaconseja.

**Condición:** Toda escritura de auditoría.

**Resultado:** Toda acción de ciclo de vida queda auditada con un actor verificable.

**Excepciones:** Las entradas existentes quedan con `actor='user'`.

**Reglas afectadas:** precisa RN-94 (W18).

### D66 / RN-160: Token de unión — **requiere decisión del usuario (TTL, coexistencia, re-enrolamiento)**

**Descripción:**

1. **Formato:** `fim1.<payload>.<secret>`.
   - `payload` = base64url sin relleno de JSON compacto: `{"h": host, "bp": 8444, "mp": 8443,
     "vp": 6380, "ca": "<sha256 hex del DER de la CA>", "tid": "<16 hex>"}`.
   - `secret` = 32 bytes aleatorios en base64url.
   - La huella usa la misma definición que `agent/installer.py:245` (`compute_fingerprint`) y
     `backend/app/modules/agents/cli.py:43`.
2. **Almacenamiento:** tabla `agent_join_tokens` con el secreto hasheado con Argon2id (mismo
   `PasswordHasher`, `service.py:31`).
3. **Vigencia:** TTL por defecto **1 hora**; configurable por token entre 5 minutos y 24 horas.
4. **Consumo:** un solo uso, marcado atómicamente en la misma transacción que emite el certificado.
5. **Revocación:** manual antes del consumo.
6. **Errores:** toda falla responde `401 invalid credentials`, sin distinguir la causa. La causa
   (`expired`, `revoked`, `consumed`, `bad_secret`, `unknown_tid`) se registra en `audit_log` y en el
   log estructurado.
7. **CA:** se descubre con `GET /agents/ca.pem` en el listener 8444 y se acepta sólo si su huella
   coincide con `payload.ca`.
8. **`agent_id`:** lo declara el agente en el consumo. Si el token trae `agent_id_hint`, debe coincidir.
9. **Transporte del token:** nunca como argumento ni variable de entorno; sólo por prompt oculto o
   `--join-token-file` (mismo principio que `reject_secret_argument`, `agent/installer.py:223-232`).

**Motivo:** ver §4.5 del documento fuente. La variante de §4.3 de este documento (endpoint de CA en
lugar de leer la cadena) evita depender de que el certificado servido en 8444 incluya la CA en la
cadena, cosa que hoy no está verificada.

**Puntos para el usuario:**

- **TTL**: 1 hora (recomendado; un operador con 20 hosts acuña 20 tokens desde la consola) o un valor
  mayor por defecto.
- **Coexistencia**: el camino actual (`--ca-cert`, `--ca-fingerprint`, `--bootstrap-secret-file`,
  D56/RN-150) **se conserva**. Es lo validado por A-3 y A-4; retirarlo invalidaría esa evidencia sin
  necesidad. Costo: dos ramas en `resolve_inputs` (`agent/installer.py:389`).
- **Re-enrolamiento** de un `agent_id` dado de baja:
  - (i) permitido con token nuevo, que reactiva la fila, emite certificado y `shared_secret` nuevos y
    conserva el historial;
  - (ii) prohibido, que obliga a un `agent_id` nuevo.

  Se recomienda (i) con `audit_log` explícito. Con (ii), un host reinstalado cambia de identidad y
  pierde la continuidad de su historial en la consola.

**Condición:** Todo enrolamiento por token.

**Resultado:** Un único valor copiable reemplaza CA, huella, host, puertos y secreto.

**Excepciones:** El modo servidor+agente acuña el token con la CLI in-process (D68), sin usuario (D65).

**Reglas afectadas:** extiende D56/RN-150 y D16/RN-114; no modifica D52/RN-146.

### D67 / RN-161: Puertos de agente parametrizables sólo en el mapeo del host

**Descripción:** `.env` SHALL admitir `AGENT_MTLS_PORT`, `AGENT_BOOTSTRAP_PORT` y `VALKEY_TLS_PORT`
(defaults 8443, 8444 y 6380), aplicados **sólo al puerto publicado en el host**
(`"${AGENT_MTLS_PORT:-8443}:8443"`). Dentro de la red de compose los puertos no cambian.
`prepare_server_env.py` SHALL rechazar valores fuera de 1–65535 y colisiones entre los cinco puertos
publicados. El instalador del agente y el token SHALL transportar los valores publicados.

**Motivo:**

- Parametrizar también el puerto interno, como propone §4.3 del documento fuente, obliga a tocar
  `pki.py:643,698`, `main.py:85-95`, el comando de Valkey y el `VALKEY_URL` interno, sin ningún
  beneficio: nadie fuera de la red interna ve el puerto interno.
- El SAN no depende del puerto.
- El backend sólo necesita conocer los puertos publicados para armar el token y el comando sugerido.

**Condición:** Generación de `.env`, arranque del stack e instalación del agente.

**Resultado:** Un servidor con 8443 ocupado publica el mTLS en otro puerto sin editar YAML.

**Excepciones:** Ninguna.

**Reglas afectadas:** extiende D54/RN-148; no modifica D53/RN-147.

### D68 / RN-162: Instalador unificado, modos, subcomandos y códigos de salida

**Descripción:**

- **Punto de entrada:** un `install.sh` en la raíz SHALL ofrecer los modos `server`, `all`
  (servidor + agente local) y `agent`, y los subcomandos `install`, `repair`, `upgrade`,
  `reconfigure`, `status` y `uninstall`.
- **Reparto bash/Python:**
  - bash hace sólo lo que requiere root, systemd o Docker;
  - la lógica (resolución de entradas, validación, planes de acción) vive en módulos Python puros
    testeables sin privilegios. Es la separación que ya documenta `agent/install.sh:5-11`.
- **Entradas:** flag > variable `FIM_*` > prompt, como en `agent/installer.py:82-98`. Todo secreto
  entra sólo por archivo o prompt oculto.
- **Confirmaciones:** `--yes` omite confirmaciones no destructivas y **nunca** habilita `--purge`.
- **Códigos de salida comunes:**

  | Código | Significado |
  |---|---|
  | 0 | Éxito |
  | 1 | Error de entrada o validación |
  | 2 | Uso incorrecto |
  | 3 | Verificación de alcance fallida |
  | 4 | Desinstalación local completa con baja remota fallida |
  | 5 | Falla parcial con estado inconsistente reportado |
  | 6 | Actualización fallida y revertida |
  | 7 | Actualización fallida y reversión fallida |
  | 10 | Acción destructiva rechazada por falta de confirmación |

  El 3 ya existe en `agent/install.sh:296`.
- **Modo `all`:** acuña el token con `python -m app.modules.agents.cli mint-token` dentro del
  contenedor `backend` e instala el agente contra `localhost`, que ya está en el SAN requerido
  (`pki.py:161`).

**Motivo:** G2 y G6 del documento fuente; separación de privilegios existente.

**Condición:** Toda operación de instalación.

**Resultado:** Un único punto de entrada con contrato estable para automatización.

**Excepciones:** `agent/install.sh` sin subcomando conserva el comportamiento actual (compatibilidad
con A-3, A-4 y la guía).

**Reglas afectadas:** extiende D56/RN-150 y D54/RN-148.

### D69 / RN-163: Desinstalación del agente — **requiere decisión del usuario (dato por defecto)**

**Descripción:** `agent/install.sh uninstall` SHALL, en este orden:

1. Solicitar la baja remota por mTLS (8443, `POST /agents/self/decommission`) con un timeout de 10 s.
   Si falla, continúa y termina con código 4 y el aviso de completar la baja desde la consola.
2. `systemctl stop fim-agent`, `systemctl disable fim-agent`, borrado de la unidad y del directorio de
   drop-ins, `systemctl daemon-reload` y `systemctl reset-failed fim-agent` (ignorando «unit not
   loaded»).
3. Tratar los datos según `--keep-data` o `--purge`:
   - `--purge` borra `/var/lib/fim-agent` (`baseline`, `quarantine`, `queue`, `journal`, `secrets`,
     `certs`, `discarded`) y `/var/log/fim-agent`, e informa antes cuántos artefactos hay en
     cuarentena;
   - `--keep-data` conserva ambos directorios y el usuario `fim-agent`.
4. Con `--purge`, borrar el usuario de sistema. Siempre borrar `/opt/fim-agent` y `/etc/fim-agent`.

En modo no interactivo, **uno de los dos flags es obligatorio**: sin ninguno, sale con código 2. El
borrado es lógico y así se documenta.

**Punto para el usuario:** en modo interactivo, ¿el prompt ofrece `--keep-data` como opción por
defecto (recomendado, porque la cuarentena puede ser evidencia) o no ofrece ninguna por defecto?

**Motivo:** §4.11.4 del documento fuente; residuos verificados en §1.2 #14.

**Condición:** Desinstalación del agente.

**Resultado:** `--purge` deja el host sin residuos del producto, verificable por inventario (§6.4). La
excepción es el journal de systemd, que no se puede purgar por unidad y queda documentado.

**Excepciones:** Servidor inalcanzable → código 4.

**Reglas afectadas:** complementa D63 y D64.

### D70 / RN-164: Ejecutor de migraciones y actualización con respaldo — **requiere decisión del usuario**

**Descripción:**

- Un servicio one-shot `db-migrate`, con la imagen del backend, SHALL aplicar en orden los SQL de
  `backend/db/migrations/` no registrados en una tabla `schema_migrations(version, filename, sha256,
  applied_at)` antes de que arranque `backend` (`depends_on: service_completed_successfully`, mismo
  patrón que `certs-init`).
- En una base nueva, marca como aplicadas todas las migraciones existentes después de `create_all`.
- En una base previa sin `schema_migrations`, aplica todas (los archivos `001`–`014` son idempotentes
  por convención) y las registra.
- Un checksum distinto para una versión ya aplicada aborta el arranque.
- `install.sh server upgrade` SHALL, en este orden:
  1. verificar espacio y salud;
  2. detener `backend` y `frontend` (Valkey conserva los mensajes pendientes del stream);
  3. hacer `pg_dump -Fc` de las dos bases (RN-67) y copiar los volúmenes `backend_certs`,
     `valkey_tls` y `console_tls_generated`, junto con `.env` y las etiquetas de las imágenes
     anteriores, en `/var/backups/fim/<timestamp>/` con modo `0700` y `SHA256SUMS`;
  4. construir, migrar y levantar;
  5. verificar `/health/components` y heartbeats;
  6. ante una falla, restaurar base, volúmenes e imágenes y salir con código 6 (o 7 si la reversión
     también falla).

**Punto para el usuario:** D3 cerró «`db-init` eliminado; el lifespan ejecuta `create_all`». Un
one-shot de migraciones **reintroduce** un paso de inicialización.

- Alternativa: correr el ejecutor dentro del lifespan antes de `create_all`. Costo: una migración que
  falla deja al backend en *crash loop* sin un estado de salida claro y mezcla la reversión con el
  proceso de servicio.
- Se recomienda el one-shot.

**Motivo:** §1.2 #10; G15 del documento fuente.

**Condición:** Todo arranque y toda actualización del servidor.

**Resultado:** Una actualización fallida vuelve al estado previo sin pérdida. Los eventos en tránsito
quedan en Valkey o en la cola local del agente (100 MB, `agent/queue.py:42`).

**Excepciones:** Los respaldos no se purgan con `uninstall --purge` salvo `--purge-backups` explícito.

**Reglas afectadas:** reescribe parcialmente D3; complementa D29 (convención SQL sin Alembic).

### D71 / RN-165: Desinstalación del servidor y retención — **requiere decisión del usuario**

**Descripción:** `install.sh server uninstall` SHALL:

- listar los agentes no dados de baja y ofrecer darlos de baja (CLI `decommission --all`, actor `cli`);
- ofrecer una exportación en un directorio `0700`: `pg_dump` completo más CSV de `audit_log` y
  `events`;
- con `--keep-data`, ejecutar `docker compose down` sin `-v`;
- con `--purge`:
  - exigir confirmación escrita del primer host de `FIM_PUBLIC_HOSTS`;
  - ejecutar `docker compose down -v`;
  - borrar las imágenes del proyecto (`fim-backend`, `fim-frontend`, **no** las de `postgres`,
    `valkey` ni `n8n`, que pueden compartirse) y `.env`;
  - advertir que destruir `backend_certs` destruye la CA y obliga a re-enrolar todo agente.

**Punto para el usuario:** ¿`--purge` **exige** una exportación previa, o sólo la ofrece?

- Se recomienda exigir `--export-dir <ruta>` o `--no-export` escrito explícitamente. Así la
  destrucción de registros (Ley 25.326, política de retención del Capítulo 9) es siempre una elección
  consciente, pero no bloquea entornos de laboratorio.

**Motivo:** §4.11.6 del documento fuente.

**Condición:** Desinstalación del servidor.

**Resultado:** No existe una purga silenciosa de evidencia.

**Excepciones:** El instalador no aplica reglas de firewall (D68 sólo las imprime), así que no hay
reglas que borrar; se imprime un recordatorio.

**Reglas afectadas:** complementa RN-94.

### D72 / RN-166: Configuración en caliente persistida — **requiere decisión del usuario**

**Descripción:**

- Una tabla `system_settings(key PK, value_json, is_secret, updated_at, updated_by_user_id)` SHALL
  almacenar SMTP (`host`, `port`, `user`, `password`, `from`, `to`, `starttls`, `ssl`),
  `webhook_fallback_url` y `n8n_webhook_url`.
- Los valores secretos se cifran con AES-GCM usando `SETTINGS_ENCRYPTION_KEY`, generada por
  `prepare_server_env.py` con `generate_hex_secret` (`:106`).
- **Precedencia: base de datos > `.env` > default del código**, por clave. Borrar una clave desde la
  consola vuelve al valor de `.env`.
- Cada cambio se audita nombrando las claves cambiadas, nunca sus valores.
- Quedan **fuera**:
  - los canales y credenciales de n8n: viven en el contenedor `n8n` y cambiarlos lo recrea (D58
    revisada, hallazgo 14.5);
  - el owner de n8n;
  - todo secreto interno (`JWT_*`, `DB_PASSWORD`, la CA).

**Punto para el usuario:** la precedencia.

- Alternativa: `.env` > base de datos, donde la consola sólo edita lo que `.env` deja vacío. Costo: un
  valor editado en la consola puede quedar sin efecto sin aviso, a menos que la UI muestre «bloqueado
  por `.env`».
- Se recomienda base de datos > `.env` con indicación de origen en la UI.

**Motivo:** G16 del documento fuente.

**Condición:** Toda lectura de configuración de notificaciones.

**Resultado:** SMTP editable sin reinicio.

**Excepciones:** Si `SETTINGS_ENCRYPTION_KEY` falta, los secretos no pueden guardarse desde la consola
(`409`) y se usa `.env`.

**Reglas afectadas:** precisa D43/RN-137.

### Decisiones sólo si se aprueban los opcionales

- **D73 / RN-167 — Modo `letsencrypt` (HTTP-01).** Reabre explícitamente el Non-Goal de
  `vps-deployment-readiness/design.md:28`.
  - Requiere que el host publique el 80 exacto (`CONSOLE_HTTP_PORT=80`).
  - Usa un sidecar certbot con webroot compartido.
  - DNS-01 queda fuera de alcance.
  - **Requiere decisión del usuario.**
- **D74 / RN-168 — Consola bajo sub-path.**
  - `CONSOLE_BASE_PATH` se aplica en tiempo de ejecución (inyección de `<base href>` por el
    entrypoint) y no en build, para no reconstruir la imagen por despliegue.
  - La cookie de refresh pasa a `Path=<base>/auth/refresh`: invalida las sesiones activas una vez.
  - **Requiere decisión del usuario sobre si el caso de uso existe.**
- **D75 / RN-169 — Página web de configuración.**
  - Sólo en modo servidor, con bind `127.0.0.1`, token de un solo uso y timeout de 15 minutos.
  - Nunca accede a Docker.
  - Se declara que D8/RN-108 (`docs/reglas_de_negocio.md:875`) no aplica porque rige sobre el agente.

---

## 4. Diseño técnico por change

### 4.1 Change 53 — `agent-decommission-and-revocation`

**Base de datos — migración `015`** (siguiente libre tras `014_add_alert_delivery_state.sql`; si otra
change archiva antes, se renumera):

```sql
-- 015_add_agent_certificates_and_audit_actor.sql (idempotente)
CREATE TABLE IF NOT EXISTS agent_certificates (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    serial_number TEXT NOT NULL UNIQUE,
    not_valid_after TIMESTAMPTZ NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL CHECK (source IN ('bootstrap', 'renew'))
);
CREATE INDEX IF NOT EXISTS ix_agent_certificates_agent_id ON agent_certificates(agent_id);
ALTER TABLE audit_log ALTER COLUMN user_id DROP NOT NULL;              -- D65
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor TEXT NOT NULL DEFAULT 'user';
```

**Modelos** (`backend/app/modules/agents/models.py`):

- `AgentCertificate` (tabla), después de `RevokedCertificate` (`:47-54`).
- `AgentDecommissionRequest(BaseModel)`, con `reason: Literal["decommissioned", "compromised"]` y
  `confirm_agent_id: str`.
- `AgentSelfDecommissionRequest(BaseModel)`, con `agent_id: str`.
- `AuditLog` (`backend/app/modules/audit/models.py:10-19`): `user_id: int | None` y `actor: str`.

**Servicio** (`backend/app/modules/agents/service.py`):

- `_record_issued_certificate(session, agent_id, cert_pem, source)`: parsea el PEM y agrega un
  `AgentCertificate` **en la misma transacción** que la emisión. Se llama desde:
  - `bootstrap_agent`, antes del `commit` de `:81`;
  - `renew_certificate` (`router.py:100-105`). Hoy no hace commit: requiere agregar la sesión de
    escritura. **Coordinar con la change 50.**
- `decommission_agent(session, agent_id, *, actor, user_id, reason) -> Agent`, en una sola transacción:
  1. `404` si no existe. Si ya está `revoked`, devuelve la fila (idempotente, sin nueva auditoría).
  2. `agent.status = AgentStatus.revoked`.
  3. Por cada `AgentCertificate` con `not_valid_after > now()`, un `RevokedCertificate(agent_id,
     serial_number, reason)`.
  4. Comandos: `PublishedCommand` con `target_agent_id == agent_id` y `status == "pending"` pasan a
     `status = "cancelled"`; los `published` con `ack_status == "pending"` pasan a
     `ack_status = "cancelled"`. **Requiere** que `publish_pending_commands` (`rules/service.py:188-207`)
     sólo publique `pending` (ya lo hace) y que la derivación de estado de eventos (change 40) trate
     `cancelled` igual que `timeout`. Validar contra `event-status-contract` en el design.
  5. `AuditLog(action="agent_decommissioned", actor=..., user_id=..., detail=json{agent_id, reason,
     revoked_serials})`.
- **No** se borra `shared_secret_hex`. Borrarlo haría que el consumer clasifique los mensajes como
  `unknown_agent` (`events/consumer.py:293-297`) **antes** de ver `revoked`, y los registre en
  `rejected_events_audit` en vez de descartarlos.

**Autenticación mTLS común** (`backend/app/modules/agents/router.py`):

- Extraer de `renew_certificate` (`:62-86`) una dependencia
  `require_agent_peer(request, session) -> AgentPeer(agent_id, cert)`. Valida: certificado presente,
  `validate_client_certificate` (`pki.py:597-609`), un solo CN, agente existente y no `revoked`, y
  serial no revocado (`is_revoked`, `pki.py:612`). Las fallas devuelven `403`, igual que
  `_renewal_forbidden`.
- `renew_certificate` pasa a usarla. Conserva su propia verificación de CN contra el cuerpo
  (`:79-80`).
- **Coordinar con la change 50**, que es dueña de esa función.

**Endpoints:**

| Método y ruta | App | Auth | Request | Response |
|---|---|---|---|---|
| `POST /agents/{agent_id}/decommission` | `app` (8000 detrás de `/api/`) | `require_admin` (`backend/app/core/deps.py:81`) | `AgentDecommissionRequest`; `confirm_agent_id` debe coincidir con el path (`422` si no) | `200 AgentResponse` |
| `POST /agents/self/decommission` | `mtls_app` (8443) | `require_agent_peer`; la identidad sale del CN, nunca del cuerpo | `AgentSelfDecommissionRequest` (el `agent_id` debe coincidir con el CN, `403` si no) | `200 {"agent_id", "status": "revoked"}` |

`mtls_app` (`main.py:47-48`) monta un segundo router, `agent_self_router`. Toda ruta nueva de
`mtls_app` declara `require_agent_peer` (test de no-regresión que recorre `mtls_app.routes`).

**CLI** (`backend/app/modules/agents/cli.py:90-104`): subcomando `decommission --agent-id <id> |
--all --reason decommissioned`, con `actor="cli"`. Lo usa la change 58.

**Heartbeat:** sin cambios. `_sweep_offline` ya excluye `revoked` (`heartbeat_consumer.py:176-190`).
Se agrega un test que lo fija.

**Frontend:**

- `frontend/src/api/agents.ts`: `decommissionAgent(id, body)`, después de `triggerRescan` (`:59`).
- `frontend/src/hooks/useAgents.ts`: `useDecommissionAgent()`, mismo patrón que
  `useUpdateAgentConfig` (`:23`); invalida `['agents']`.
- `frontend/src/components/ui/DecommissionAgentModal.tsx`: sobre `ModalDialog`
  (`frontend/src/components/ui/ModalDialog.tsx:20`). Pide tipear el `agent_id`, ofrece el selector de
  motivo y advierte la irreversibilidad y el re-enrolamiento con token nuevo (D66).
- `frontend/src/components/ui/AgentCard.tsx`: botón «Dar de baja», oculto si `status === 'revoked'`.
- `frontend/src/pages/Agents.tsx`: estado del modal, mismo patrón que `rescanModal` (`:14-17`), y
  filtro «Ocultar dados de baja».
- No hace falta gating por rol en el sidebar: `/agents` ya es sólo para admin por la API. El sidebar no
  filtra por rol (`frontend/src/components/layout/Sidebar.tsx:10-15`); se mantiene la convención.

### 4.2 Change 54 — `agent-port-parameterization`

| Archivo | Cambio |
|---|---|
| `docker-compose.yml:295-296` | `"${AGENT_MTLS_PORT:-8443}:8443"`, `"${AGENT_BOOTSTRAP_PORT:-8444}:8444"`; pasar las tres variables a `backend.environment` (sólo para el token y la CLI). |
| `docker-compose.tls.yml:51` | `"${VALKEY_TLS_PORT:-6380}:6380"`. **No** tocar `--tls-port 6380` (`:55`) ni el `VALKEY_URL` interno. |
| `.env.example` | Las tres variables, con la aclaración «puerto publicado en el host; el contenedor sigue escuchando en el default». |
| `backend/app/core/config.py` | `agent_mtls_public_port: int = 8443`, `agent_bootstrap_public_port: int = 8444`, `valkey_tls_public_port: int = 6380`, cerca de `fim_public_hosts`. |
| `backend/app/modules/agents/cli.py:54-87` | El comando sugerido incluye `--agent-bootstrap-port` / `--valkey-port` si difieren del default. |
| `scripts/prepare_server_env.py` | Flags en `build_parser` (`:284`, junto a `:290-291`); `validate_published_ports(ports: dict[str, int]) -> None` (rango y colisión, lanza `ServerEnvError`, `:62`); `render_env` (`:197`) escribe las tres claves; `render_firewall_summary(ports) -> str` (pura), impresa al final de `run` (`:308`) con los mismos seis comandos de `docs/despliegue_servidor_remoto.md:189-194`. |
| `agent/installer.py` | `derive_urls(host, *, bootstrap_port=8444, mtls_port=8443, valkey_port=6380)` (`:149`); `SCOPE_CHECK_PORTS` (`:58-61`) pasa a `scope_check_ports(bootstrap_port, valkey_port) -> tuple[tuple[int, bool], ...]`; `run_scope_check` (`:576-584`) recibe los puertos; `_build_arg_parser` (`:597-623`) agrega `--agent-bootstrap-port`, `--agent-mtls-port`, `--valkey-port` con `FIM_AGENT_BOOTSTRAP_PORT`, etc., resueltos por `_get_value` (`:82-98`); la rama `check` de `main` (`:627`) los usa. |
| `agent/install.sh` | Sin cambios: reenvía `"$@"` (`:90`). |
| `docs/despliegue_servidor_remoto.md` §2, §5 y §7 | Documentar las variables y los flags. |

`CORS_ALLOWED_ORIGINS` no cambia (D59 sólo usa los puertos de la consola).

### 4.3 Change 55 — `agent-join-tokens`

**Base de datos — migración `016`:**

```sql
CREATE TABLE IF NOT EXISTS agent_join_tokens (
    token_id TEXT PRIMARY KEY,                 -- 16 hex (8 bytes), no 8 caracteres: evita colisiones
    secret_hash TEXT NOT NULL,                 -- Argon2id
    host TEXT NOT NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id),
    actor TEXT NOT NULL DEFAULT 'user',        -- D65
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NULL,
    consumed_by_agent_id TEXT NULL,
    revoked_at TIMESTAMPTZ NULL,
    agent_id_hint TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_agent_join_tokens_pending
    ON agent_join_tokens(expires_at) WHERE consumed_at IS NULL AND revoked_at IS NULL;
```

**Códec puro, duplicado a propósito en los dos lados con un contrato compartido:**

- `backend/app/modules/agents/join_token.py` y `agent/join_token.py`, con `encode(payload, secret) -> str`,
  `decode(token) -> JoinToken(payload, token_id, secret)` y `JoinTokenError`.
- Validaciones: prefijo `fim1`, tres segmentos, base64url estricto, JSON con claves exactas, puertos en
  rango, huella de 64 hex, largo total ≤ 512 bytes.
- Fixture de contrato `contracts/agent-join-token.v1.json` (el directorio `contracts/` ya existe), con
  casos válidos e inválidos. Un test en cada lado lo consume, siguiendo la lección de la change 50
  (`CHANGES.md:1021-1048`) sobre contratos sin aserciones compartidas.

**Servicio** (`backend/app/modules/agents/service.py`):

- `mint_join_token(session, *, host, ttl_seconds, agent_id_hint, user_id, actor) -> MintedJoinToken(token, token_id, expires_at)`:
  - valida que `host` pertenezca a `FIM_PUBLIC_HOSTS ∪ {localhost}` (`cli._public_hosts`, `:50`) y
    que el TTL esté en el rango de D66;
  - arma el payload con `settings.*_public_port` (change 54) y `compute_ca_fingerprint` (`cli.py:43`,
    que conviene mover a `core/pki.py` para no importar la CLI desde el servicio);
  - hashea, inserta y audita `join_token_minted` sin el secreto.
- `list_join_tokens(session, *, include_inactive=False)`.
- `revoke_join_token(session, token_id, *, user_id)`: `409` si ya fue consumido; idempotente si ya
  estaba revocado.
- `bootstrap_agent_with_join_token(req, session, *, ca_cert_path, ca_key_path) -> AgentBootstrapResponse`:
  1. `SELECT ... FOR UPDATE` sobre `token_id`. Si no existe, se hace de todos modos un `_ph.verify`
     contra un hash ficticio, para igualar el tiempo de respuesta, y se devuelve `401`.
  2. Verificar `revoked_at`, `consumed_at` y `expires_at` **antes** del hash (el tiempo constante sólo
     importa para tokens vivos); `_ph.verify(secret_hash, req.join_secret)`.
  3. `agent_id_hint` coincide con `req.agent_id`, si está presente.
  4. `_validate_csr(req.csr_pem, req.agent_id)` (`service.py:258`).
  5. Fila `Agent`: si no existe, se crea en `offline`. Si existe `revoked` y D66 = (i), pasa a
     `offline`, se limpia `last_heartbeat` y se guarda un `shared_secret` nuevo. Si existe en otro
     estado, `409`.
  6. `issue_certificate` (`pki.py:513`), `_record_issued_certificate(..., "bootstrap")` (change 53),
     `consumed_at = now()`, `consumed_by_agent_id`, auditoría y un único `commit`.

**Endpoints:**

| Método y ruta | App | Auth | Request | Response |
|---|---|---|---|---|
| `POST /agents/join-tokens` | `app` | `require_admin` | `{"host": str, "ttl_seconds": int = 3600, "agent_id_hint": str \| None}` | `201 {"token": str, "token_id": str, "expires_at": datetime, "install_command": str}` con `Cache-Control: no-store` |
| `GET /agents/join-tokens` | `app` | `require_admin` | `?include_inactive=bool` | `200 [{"token_id", "host", "created_at", "expires_at", "consumed_at", "consumed_by_agent_id", "revoked_at", "agent_id_hint", "created_by"}]` (nunca el hash) |
| `POST /agents/join-tokens/{token_id}/revoke` | `app` | `require_admin` | — | `204` |
| `GET /agents/ca.pem` | `bootstrap_app` (8444) | ninguna; limitado por IP | — | `200 application/x-pem-file` (el contenido de `settings.ca_cert_path`) |
| `POST /agents/join` | `bootstrap_app` (8444) | token | `{"token_id": str, "join_secret": str, "agent_id": str, "csr_pem": str}` | `200 AgentBootstrapResponse` (`models.py:75`) |

- Rutas nuevas y separadas en lugar de extender `AgentBootstrapRequest` (`models.py:69`): el camino
  legado queda byte a byte igual y la spec de cada uno es independiente.
- **Limitación por IP** en `/agents/join` y `/agents/ca.pem`: reutilizar el patrón de Valkey de
  `backend/app/core/rate_limit.py:37` con clave `join:<ip>`.

**CLI:** `python -m app.modules.agents.cli mint-token --host <h> [--ttl 3600] [--agent-id-hint <id>]
[--output-file <ruta>]`, con `actor="cli"`. `--output-file` escribe el token con `O_CREAT|O_EXCL` y
modo `0600`, mismo patrón que `write_env_exclusive` (`scripts/prepare_server_env.py:254-263`). Sin ese
flag, lo imprime **una vez**. `scripts/register-agent.sh` suma `--join-token`, que invoca
`mint-token` en lugar de `register` y no exporta `fim-ca.pem`.

**Agente, instalación** (`agent/installer.py`):

- `reject_secret_argument` (`:223-232`) también rechaza `--join-token` y `--join-token=`.
- `_build_arg_parser` suma `--join-token-file`.
- `resolve_join_token(path, non_interactive) -> JoinToken`: mismo patrón que
  `resolve_bootstrap_secret` (`:160`), con prompt oculto `getpass`.
- `fetch_and_pin_ca(host, bootstrap_port, expected_fp, *, timeout=10) -> bytes`:
  - `httpx.get(f"https://{bracket_host(host)}:{bp}/agents/ca.pem", verify=False, follow_redirects=False)`;
  - cuerpo acotado a 16 KiB;
  - verificación con `verify_ca_pem(pem_bytes, expected_fp)`, que se extrae de `load_and_verify_ca`
    (`:250-273`): `BasicConstraints.ca` y `compute_fingerprint` (`:245`);
  - con huella distinta, `InstallerError` con ambas huellas, **sin escribir nada**.
  - `verify=False` es aceptable **sólo** porque la autenticidad la da la huella, no el canal.
- `resolve_inputs` (`:389`): si hay token, `server_host`, puertos y huella salen del payload; la CA
  sale de `fetch_and_pin_ca`; `bootstrap_secret = None`; se agrega `join_credentials = f"{tid}.{secret}"`.
  Si no hay token, se usa el camino actual.
- `apply_config` (`:440-484`) escribe `/etc/fim-agent/env` con `FIM_JOIN_CREDENTIALS=...`, en lugar de
  `FIM_BOOTSTRAP_SECRET`, con `0600 root:root` (`:470`).
- `secret_required` (`:212`): con token siempre es verdadero, con `--reconfigure` implícito (§4.9 del
  documento fuente).

**Agente, primer arranque:**

- `agent/__main__.py:204` lee `FIM_JOIN_CREDENTIALS` si existe y, si no, `FIM_BOOTSTRAP_SECRET`.
- `agent/bootstrap.py` suma `run_with_join_credentials(config, credentials)`: igual que `run` (`:134`),
  pero con `POST {backend_url}/agents/join` y el cuerpo nuevo.
- El consumo sigue ocurriendo en el primer arranque del servicio, no en el instalador. Así se conserva
  la separación de privilegios y la clave privada no pasa por el proceso del instalador.
- Riesgo de TTL: `install.sh` habilita e inicia el servicio inmediatamente después de `check`
  (`agent/install.sh:300-312`), así que el consumo ocurre segundos después.

**`agent/install.sh`:** en el bucle de reescritura de rutas relativas (`:90` en adelante), agregar
`--join-token-file` con el mismo tratamiento que `--bootstrap-secret-file`.

**Frontend:**

- `frontend/src/api/agents.ts`: `mintJoinToken`, `listJoinTokens` y `revokeJoinToken`.
- `frontend/src/hooks/useJoinTokens.ts`: `useJoinTokens()` (query `['agents', 'join-tokens']`),
  `useMintJoinToken()` y `useRevokeJoinToken()`. La mutación **no** escribe el token en la caché de
  TanStack Query: queda sólo en el estado local del modal.
- `frontend/src/components/ui/AddAgentModal.tsx` (sobre `ModalDialog`):
  - selector de host (de `FIM_PUBLIC_HOSTS`, expuestos por un campo nuevo en la respuesta de
    `GET /agents/join-tokens` o por `GET /agents/join-tokens/options`), TTL y `agent_id_hint`;
  - al acuñar, muestra el comando `sudo bash agent/install.sh --join-token-file ./fim-token`, las
    instrucciones para crear el archivo y el token en un `<textarea readOnly>`;
  - botón «Copiar» con `navigator.clipboard.writeText` y **fallback** de selección manual, porque la
    API del portapapeles exige contexto seguro y no está disponible con `CONSOLE_TLS_MODE=off` sobre
    una IP;
  - al cerrar, limpia el estado. Nunca emite un `toast` con el token.
- `frontend/src/components/ui/JoinTokensTable.tsx`: tokens pendientes con acción «Revocar».
- `frontend/src/pages/Agents.tsx`: botón «Agregar agente» y tabla.

### 4.4 Change 56 — `agent-lifecycle-commands`

**Estructura:**

```
agent/install.sh                 # dispatcher bash (root)
  ├─ sin subcomando / install    → cmd_install (cuerpo actual, sin cambios)
  ├─ repair                      → cmd_install --repair  (no reemplaza config; regenera drop-in; fija permisos)
  ├─ upgrade                     → cmd_install con reversión: conserva agent.previous hasta is-active
  ├─ reconfigure                 → cmd_install --reconfigure
  ├─ status                      → python -m agent.lifecycle status
  └─ uninstall                   → python -m agent.lifecycle plan-uninstall  (JSON de acciones)
                                   python -m agent.installer decommission   (mTLS, best-effort)
                                   ejecución bash de las acciones systemd/fs
agent/lifecycle.py               # puro: planes, inventario, códigos de salida
```

- **Compatibilidad:** si `$1` empieza con `--` o está vacío, se trata como `install`. Así, A-3, A-4 y
  la guía (§7 y §9, `docs/despliegue_servidor_remoto.md:227,274`) siguen funcionando.

**`agent/lifecycle.py` (sin privilegios, testeable):**

- `EXIT_*` con las constantes de D68.
- `Paths` (dataclass con las constantes de `agent/install.sh:39-51` más `/var/lib/fim-agent` y
  `/var/log/fim-agent`), inyectable en tests.
- `plan_uninstall(paths, *, keep_data: bool, purge: bool) -> list[Action]`. `Action` es
  `(kind: Literal["systemctl", "rm_file", "rm_tree", "userdel"], target: str, ignore_missing: bool)`.
  Orden fijo de D69. `keep_data` y `purge` a la vez → `ValueError`.
- `inventory_residues(paths) -> dict[str, bool]`, que usan `status` y el test de residuos.
- `count_quarantine_artifacts(path) -> int`.
- `status_report(paths, *, run_scope: bool) -> dict`: unidad activa y habilitada (vía los resultados de
  `systemctl` que le pasa bash), `is_already_enrolled` (`agent/installer.py:189`),
  `not_valid_after` del certificado del agente, `agent_id` y `backend_url` de `config.yaml`, y
  opcionalmente `run_scope_check`.

**`agent/installer.py decommission`:**

- Lee `config.yaml` (`mtls_backend_url`, `agent_id`) y las rutas del certificado y la clave en
  `/var/lib/fim-agent/certs` (`agent/bootstrap.py:34-36`).
- Hace `httpx.post(f"{mtls_backend_url}/agents/self/decommission", cert=(cert, key),
  verify=ca_path, timeout=10)`.
- Resultados: `0` si responde 200, `4` ante error de red o `403`. Nunca bloquea la desinstalación
  local.

**Secuencia bash de `uninstall`:**

```bash
python -m agent.lifecycle plan-uninstall --purge > "$PLAN"   # valida flags (exit 2/10)
"${VENV_DIR}/bin/python" -m agent.installer decommission || REMOTE_STATUS=$?
systemctl stop fim-agent 2>/dev/null || true
systemctl disable fim-agent 2>/dev/null || true
rm -f "${SYSTEMD_UNIT}"; rm -rf "${SYSTEMD_DROPIN_DIR}"
systemctl daemon-reload
systemctl reset-failed fim-agent 2>/dev/null || true
# datos según plan; con --purge: rm -rf /var/lib/fim-agent /var/log/fim-agent; userdel fim-agent
rm -rf "${AGENT_DEST}" /etc/fim-agent
exit "${REMOTE_STATUS:-0}"   # 4 si la baja remota falló
```

- El venv se borra al final. `plan-uninstall` y `decommission` corren **antes** de borrar
  `/opt/fim-agent`.
- **Idempotencia:** en un host sin instalación, `uninstall` informa «nothing to remove» y sale con 0.

**`upgrade` con reversión local:**

- `agent/install.sh:210-214` hoy borra `agent.previous` de inmediato. En `upgrade` se conserva hasta que
  `systemctl is-active fim-agent` dé 0 durante 30 s después del `restart` (`:309`).
- Si no llega a activo, restaura `agent.previous`, ejecuta `systemctl restart` y sale con 6.

**Shim de test** (`agent/tests/integration/docker/systemctl`): hoy `disable` sale con 0 sin estado.
Hay que agregar un archivo `.enabled` para `enable`/`disable`, `is-enabled` y `reset-failed` (sale 0 y
lo registra), para poder afirmar el orden y el estado final.

### 4.5 Change 57 — `server-unified-installer`

**Estructura:**

```
install.sh                         # raíz; bash delgado
  ├─ (sin args, TTY)               → selector 1/2/3
  ├─ server <sub> [flags]          → python3 scripts/install_server.py <sub> [flags]
  ├─ all <sub> [flags]             → server <sub>, luego (install) acuñado + agent/install.sh
  └─ agent <sub> [flags]           → exec bash agent/install.sh <sub> [flags]
scripts/install_server.py          # stdlib; funciones puras + main con subparsers
scripts/prepare_server_env.py      # se reutiliza como biblioteca (no se duplica)
```

**`scripts/install_server.py`, funciones:**

- `resolve_answers(args, env, prompt) -> ServerAnswers` (dataclass). Campos:
  - `admin_username`, `admin_email`, `admin_password` (sólo por `--admin-password-file` o prompt con
    confirmación; hoy se genera en `prepare_server_env.py:348`);
  - `public_hosts`, `console_tls_mode`, los cinco puertos;
  - SMTP opcional (`--smtp-password-file`).
- `validate_answers(a)`: reutiliza `parse_public_hosts` (`prepare_server_env.py:79`) y
  `validate_published_ports` (change 54).
- `build_env_values(a) -> dict[str, str]`: reutiliza `generate_hex_secret` y `generate_password`
  (`:106-110`), `hash_n8n_owner_password` (`:116`) y `derive_cors_origins` (`:158`). Escribe con
  `render_env` (`:197`) + `write_env_exclusive` (`:254`).
- `compose_argv(files, profiles, *verb) -> list[str]`, con los mismos archivos que
  `scripts/register-agent.sh:22`.
- `wait_healthy(url="http://127.0.0.1:8000/health/components", timeout_s=300) -> HealthReport`. 8000
  está publicado sólo en loopback (`docker-compose.yml:297`).
- `render_firewall_summary(ports)` (change 54).
- Subcomandos:
  - `install`: si `.env` existe, sale con 1 sugiriendo `upgrade` o `repair`, mismo criterio que
    `prepare_server_env.py:313`.
  - `repair`: `up -d` sin `--build`, verificación de salud, ejecución de `certs-init` (idempotente,
    D61) e informe.
  - `status`: `docker compose ps --format json`, salud, volúmenes y conteo de agentes por estado vía
    `docker compose exec -T backend python -m app.modules.agents.cli list --json` (subcomando nuevo).
  - `reconfigure`: sólo claves de infraestructura (hosts, puertos, modo TLS), con `.env.bak-<ts>` y
    `up -d`, que recrea lo que dependa de cada variable.

**Modo `all`:**

1. `install_server.py install`.
2. `docker compose exec -T backend python -m app.modules.agents.cli mint-token --host localhost
   --ttl 900 --output-file /certs/.join-<rand>`. Hay que escribir en un volumen legible por root del
   host. **Alternativa más simple:** capturar stdout de `exec -T` directamente a un archivo del host
   creado con `umask 077` en `mktemp -d`. Se recomienda esta última: evita dejar el token en un
   volumen.
3. `bash agent/install.sh --non-interactive --join-token-file <archivo> --agent-id "$(hostname)"
   --watch-path <...>`.
4. `shred -u` del archivo (o `rm`, con la nota de §7).

**SMTP «enviar prueba»:** CLI nueva `python -m app.modules.alerts.cli smtp-test --to <addr>`, que
reutiliza `send_smtp` (`backend/app/modules/alerts/notifier.py:55`). Corre después de `wait_healthy`.
Una falla es una advertencia, no aborta la instalación.

### 4.6 Change 58 — `server-upgrade-backup-and-uninstall`

**Ejecutor de migraciones** (`backend/app/core/migrations.py`, nuevo):

- `discover(dir) -> list[Migration(version, filename, sha256, sql)]`: orden por prefijo numérico;
  duplicados → error.
- `apply_pending(engine, migrations) -> list[str]`:
  - `CREATE TABLE IF NOT EXISTS schema_migrations(...)`;
  - modo baseline si no existe la tabla `agents`: ejecuta `create_all` y registra todo;
  - checksum distinto → `MigrationChecksumError`;
  - cada archivo en su propia transacción. `ALTER TYPE ... ADD VALUE` se admite dentro de una
    transacción desde PG 12, pero el valor nuevo no puede usarse en la misma; ninguna migración
    existente lo hace.
- `__main__`: `python -m app.core.migrations apply|status`.
- `docker-compose.yml`: servicio `db-migrate` (imagen del backend, `depends_on: db: service_healthy`);
  `backend.depends_on.db-migrate: service_completed_successfully`.
- `main.py:82` conserva `create_all` para desarrollo sin compose.

**`install_server.py upgrade`:**

| Paso | Operación | Falla → |
|---|---|---|
| 1 | `shutil.disk_usage(backup_root)` ≥ 2 × (`SELECT pg_database_size` de ambas bases) + tamaño de volúmenes; `wait_healthy` | exit 1, sin cambios |
| 2 | `docker compose stop backend frontend` | exit 5 |
| 3 | `umask 077`; `mkdir -m 0700 /var/backups/fim/<ts>`; `docker compose exec -T db pg_dump -U "$DB_USER" -Fc <db>` redirigido a archivos `0600` (una vez por base, RN-67); `docker run --rm -v <proyecto>_backend_certs:/src:ro -v <dir>:/dst alpine tar czf /dst/backend_certs.tgz -C /src .` (también `valkey_tls` y `console_tls_generated`); copia de `.env`; `docker image tag fim-backend:dev fim-backend:pre-<ts>` (ídem frontend); `SHA256SUMS` | `up -d backend frontend` y exit 5 |
| 4 | `docker compose build`; `up -d` (corre `db-migrate`) | ir a 6 |
| 5 | `wait_healthy`; agentes online ≥ los online antes del paso 2, dentro de `--heartbeat-timeout` (default 120 s), vía CLI `list --json` | ir a 6 |
| 6 | Reversión: `stop backend frontend`; `pg_restore --clean --if-exists -d <db>` de cada volcado; restauración de volúmenes (`tar xzf` sobre volumen vacío); `docker image tag fim-backend:pre-<ts> fim-backend:dev`; `up -d --no-build` | exit 6 si queda sano; 7 si no |

El paso 3 corre con `backend` detenido: el volcado es consistente y no hay ingesta entre el respaldo y
una eventual reversión. Los mensajes quedan en el stream `events` de Valkey (volumen `valkey_data`).

**`install_server.py uninstall`:**

1. Inventario: CLI `list --json`, agentes con `status != revoked`.
2. `--decommission-all`, o prompt: CLI `decommission --all` (change 53).
3. Exportación: `pg_dump -Fc` y `psql -c "\copy (SELECT * FROM audit_log) TO STDOUT WITH CSV HEADER"`
   (ídem `events`) dentro de `db`, con salida redirigida a `--export-dir`. Si `--purge` se usa sin
   `--export-dir` ni `--no-export`, sale con 10 (D71).
4. `--keep-data`: `docker compose --profile app --profile lab down`.
5. `--purge`:
   - confirmación escrita (TTY), o `--confirm-host <host>` sin TTY;
   - `docker compose --profile app --profile lab down -v`;
   - `docker image rm fim-backend:dev fim-frontend:dev` (y las etiquetas `pre-*` sólo con
     `--purge-backups`);
   - borrado de `.env`;
   - recordatorio de firewall y aviso sobre la CA.

### 4.7 Change 59 — `console-runtime-settings`

**Módulo nuevo** `backend/app/modules/settings/` con `models.py`, `schemas.py`, `service.py`,
`router.py` y `crypto.py`, siguiendo la estructura por dominio de `CLAUDE.md`.

- **Migración `017`:** tabla `system_settings` (D72).
- **`crypto.py`:**
  - `encrypt(value: str, key: bytes) -> str` y `decrypt(token: str, key: bytes) -> str`;
  - AES-GCM de `cryptography`, nonce de 12 bytes, formato `v1:<b64 nonce>:<b64 ct>`, AAD = nombre de
    la clave (impide mover un secreto cifrado a otra clave).
- **`service.py`:**
  - `get_notification_settings(session) -> NotificationSettings` (Pydantic) con precedencia
    base > `.env` > default y campo `source: dict[str, Literal["db", "env", "default"]]`;
  - caché en proceso invalidada por `update_notification_settings`. Es válida porque el backend es
    single-instance (RN-76).
  - `update_notification_settings(session, patch, *, user_id)`: `None` borra la clave; audita
    `settings_updated` con `detail={"keys": [...]}`.
- **Puntos de lectura a reemplazar:** `alerts/service.py:222,235,261-262,311,315` y
  `core/health.py:153,183,206`. `send_smtp(payload, cfg)` (`notifier.py:55`) ya recibe `cfg`: se pasa
  el objeto resuelto en lugar de `settings`.

**Endpoints:**

| Método y ruta | Auth | Request | Response |
|---|---|---|---|
| `GET /settings/notifications` | `require_admin` | — | `200 {smtp: {host, port, user, from, to, starttls, ssl, password_set: bool}, webhook_fallback_url, n8n_webhook_url, source: {...}}`; el secreto nunca vuelve |
| `PUT /settings/notifications` | `require_admin` | parcial; `smtp.password: str \| null` | `200` (igual que GET) |
| `POST /settings/notifications/smtp-test` | `require_admin` + `check_api_rate_limit` (`rate_limit.py:56`) | `{"to": EmailStr}` | `202 {"delivered": bool, "error": str \| null}` |

**Frontend:**

- `frontend/src/pages/Settings.tsx`; ruta `/settings` en `frontend/src/App.tsx`, después de `:61`;
  ítem «Configuración» en `Sidebar.tsx:10-15`.
- `frontend/src/api/settings.ts`, `frontend/src/hooks/useSettings.ts` y
  `frontend/src/components/ui/NotificationSettingsForm.tsx`.
- El formulario muestra el origen de cada valor. El campo de contraseña es de sólo escritura
  (placeholder «configurada» si `password_set`).

### 4.8 Changes opcionales (esquema)

- **60 `console-letsencrypt-mode`:**
  - `config.py:64` agrega `letsencrypt`;
  - `frontend/docker-entrypoint.d/40-fim-console-tls.sh:48-83` agrega el caso `letsencrypt`, que usa
    la plantilla HTTPS sobre `/etc/letsencrypt/live/<dominio>/`;
  - `frontend/nginx/console-http.conf` agrega `location /.well-known/acme-challenge/ { root
    /var/www/acme; }` **antes** de la redirección a 443;
  - servicio `certbot` en un perfil `acme`, con volúmenes `acme_webroot` y `console_tls_letsencrypt`
    y un bucle `certbot renew` cada 12 h;
  - recarga: un bucle en el contenedor `frontend` que corre `nginx -s reload` cada 6 h. Evita dar el
    socket de Docker a certbot.
- **61 `console-subpath`:**
  - `CONSOLE_BASE_PATH`; Vite con `base: './'` (`frontend/vite.config.ts:7`);
  - el entrypoint inyecta `<base href>` y `window.__FIM_BASE__`;
  - `BrowserRouter basename` en `App.tsx`; `apiClient` con `baseURL` derivado;
  - plantillas nginx con prefijo (`common-locations.conf:6-34`);
  - `_set_refresh_cookie` (`backend/app/modules/auth/router.py:54-78`) usa `path=f"{base}/auth/refresh"`.
- **62 `server-web-setup`:**
  - `scripts/web_setup.py` sobre `http.server` de la stdlib, en `127.0.0.1:0`;
  - token `secrets.token_urlsafe(32)` en la URL, comparado con `hmac.compare_digest` y usado también
    como anti-CSRF del formulario;
  - timeout de inactividad de 15 minutos;
  - entrega las respuestas a `install_server.py` por un pipe (stdout JSON) y termina. No escribe
    `.env` ni ejecuta Docker.

---

## 5. Capacidades y deltas de specs

Todos los deltas se crean con `/opsx:propose` (CLI) y se archivan con `openspec archive`. Antes y
después de cada archive: `python3 scripts/check_spec_integrity.py` (D47/RN-141). Ningún directorio
bajo `openspec/changes/archive/` se escribe a mano.

Las capacidades `remote-deployment` y los requisitos del instalador en `agent-core` todavía **no
existen en las main specs**: sólo están en los deltas de 52
(`openspec/changes/vps-deployment-readiness/specs/remote-deployment/spec.md:3,36,57`;
`.../agent-core/spec.md:3-127`). **Todo change que los modifique requiere que 52 esté archivado.**

| Change | Capacidad | Tipo | Requisitos |
|---|---|---|---|
| 53 | `backend-agents` | ADDED | «Admin decommissions an agent», «Agent requests its own decommission over mTLS», «Issued agent certificates are recorded» |
| 53 | `backend-pki` | MODIFIED | «Certificate revocation check» (verificación a nivel aplicación en toda ruta de 8443; declara la brecha de 6380, D26/D64) |
| 53 | `backend-agent-management` | ADDED | «Decommission cancels pending commands for the agent» |
| 53 | `frontend-agents` | ADDED | «Admin can decommission an agent with typed confirmation» |
| 53 | `domain-models` | ADDED | «AuditLog admits non-user actors» (D65) |
| 54 | `infra-compose` | MODIFIED | «Red interna y exposición de puertos (RN-76, RN-78)» (post-52) |
| 54 | `remote-deployment` | MODIFIED | «Script de preparación del `.env` del servidor (D54/RN-148)» |
| 54 | `agent-core` | MODIFIED | «Instalador parametrizable con prompts para valores faltantes (D56/RN-150)», «Verificación de alcance antes de habilitar el servicio (D56/RN-150)» |
| 55 | **`agent-join-tokens`** (nueva) | ADDED | «Admin mints a single-use join token», «Join tokens expire and can be revoked», «Join token consumption is atomic and single-use», «CA is discovered and pinned by fingerprint», «Join token format is versioned and shared by contract» |
| 55 | `agent-core` | ADDED + MODIFIED | ADDED «Instalación por token de unión»; MODIFIED «El secreto de bootstrap nunca se acepta como argumento (D56/RN-150)» (extiende a `--join-token`) |
| 55 | `agent-bootstrap` | MODIFIED | «bootstrap_secret read from environment variable» (acepta `FIM_JOIN_CREDENTIALS`) |
| 55 | `frontend-agents` | ADDED | «Admin can add an agent from the console», «Admin can list and revoke pending join tokens» |
| 55 | `remote-deployment` | MODIFIED | «Registro de agente en un único paso del lado del servidor (D56/RN-150)» |
| 56 | `agent-core` | ADDED + MODIFIED | ADDED «Desinstalación del agente con baja remota best-effort», «Subcomandos status, repair y upgrade con reversión»; MODIFIED «Install script creates isolated Python environment» (dispatcher con compatibilidad) |
| 57 | **`server-installer`** (nueva) | ADDED | «Punto de entrada único con modos», «Preguntas de primer inicio y modo no interactivo», «Modo servidor+agente con acuñado in-process», «Resumen de firewall impreso, no aplicado», «Códigos de salida del instalador» |
| 58 | `server-installer` | ADDED | «Actualización con respaldo y reversión», «Desinstalación del servidor con exportación y purga confirmada» |
| 58 | `infra-compose` | ADDED | «Servicio one-shot de migraciones (`db-migrate`)» |
| 58 | `backend-core` | MODIFIED | el requisito de lifespan con `create_all` (identificar el nombre exacto en `openspec/specs/backend-core/spec.md` al proponer) |
| 59 | **`backend-runtime-settings`** (nueva) | ADDED | «Notification settings persisted with explicit precedence», «Secret settings encrypted at rest», «Settings changes are audited», «SMTP test action» |
| 59 | `backend-notifications` | MODIFIED | los requisitos que leen SMTP y webhook de variables de entorno (identificar al proponer) |
| 59 | **`frontend-settings`** (nueva) | ADDED | «Admin edits notification settings with source indication» |
| 60 | `backend-pki` / `infra-compose` / `frontend-shell` | MODIFIED/ADDED | modo `letsencrypt` |
| 61 | `frontend-shell`, `backend-auth` | MODIFIED | sub-path y `Path` de la cookie |
| 62 | `server-installer` | ADDED | «Asistente web efímero en loopback» |

Justificación de las capacidades nuevas:

- **`agent-join-tokens`**: el acuñado y la revocación de credenciales de un solo uso es un dominio
  distinto de la gestión operacional de agentes ya enrolados (`backend-agents`,
  `backend-agent-management`).
- **`server-installer`**: el ciclo de vida del servidor no encaja en `remote-deployment`, que describe
  un despliegue manual guiado.
- **`backend-runtime-settings`**: no existe ninguna spec de configuración persistida.

---

## 6. Estrategia de pruebas

### 6.1 Por change

| Change | Unitarias (pytest / vitest) | Integración | E2E / real |
|---|---|---|---|
| 53 | `backend/tests/test_agent_decommission.py` con los fixtures de `backend/tests/test_agent_mgmt.py`: transición idempotente, serials revocados, comandos cancelados, auditoría con actor, `confirm_agent_id` distinto → 422, no-admin → 403; `test_mtls_routes_require_agent_peer` recorre `mtls_app.routes`; `test_revoked_agent_never_goes_dead` sobre `_sweep_offline`. Vitest: `DecommissionAgentModal.test.tsx` (confirmación tipeada), `AgentCard.test.tsx` (botón oculto si `revoked`). | Listener mTLS real (patrón de `backend/tests/test_agent_cert_renewal.py`): certificado de un agente dado de baja → `403` en `/agents/renew` y `/agents/self/decommission`; consumer con Valkey de pruebas: evento y heartbeat de un agente `revoked` descartados (log `consumer.agent_revoked.discard`). | Playwright en el lab aislado (`frontend/playwright.isolated-lab.config.ts`, nuevo test en `frontend/e2e/us-isolated-lab.spec.ts`, mismo estilo que `:245`): dar de baja el agente real del lab, verificar el estado `revoked` y que un cambio posterior no crea eventos. |
| 54 | `scripts/tests/test_prepare_server_env.py`: rango y colisión; `test_compose_topology.py` parametrizado con `.env` de puertos no default (el mapeo host cambia y el contenedor no); `agent/tests/test_installer.py`: `derive_urls` y `scope_check_ports` con puertos no default. | `docker compose config --format json` con los tres valores; `test_install_sh_container.py`: `openssl s_server` en puertos no default. | — |
| 55 | Códec en ambos lados contra `contracts/agent-join-token.v1.json`; servicio: expirado, revocado, consumido, hint distinto, hash incorrecto → 401 idéntico; consumo concurrente (dos sesiones, sólo una gana); `fetch_and_pin_ca` con huella distinta → error sin escritura (sin red, respuesta simulada con `httpx.MockTransport`); rechazo de `--join-token`. Vitest: `AddAgentModal` (token no queda en la caché, fallback de copiado sin `navigator.clipboard`). | Contenedor de instalación: servidor HTTPS de pruebas que sirve una CA legítima y otra sustituida (la segunda aborta con exit 1 y sin `/etc/fim-agent/env`); backend real con listener 8444: `POST /agents/join` válido → certificado verificable con `agent/bootstrap.py::verify_cert`; segundo uso → 401. | Playwright: acuñar → la tabla muestra el token pendiente → revocar → la tabla lo muestra revocado. **Real de dos hosts (A-5)**: ver §6.3. |
| 56 | `agent/tests/test_lifecycle.py`: orden de `plan_uninstall`, flags mutuamente excluyentes, inventario sobre `tmp_path`, `status_report`. | `test_install_sh_container.py`: `test_uninstall_purge_leaves_no_residue`, `test_uninstall_keep_data_preserves_state`, `test_uninstall_is_idempotent`, `test_uninstall_backend_unreachable_exits_4`, `test_upgrade_rolls_back_when_service_not_active` (shim que no activa), `test_legacy_invocation_without_subcommand_still_installs`. Baja remota: un servidor HTTPS mínimo con mTLS dentro del contenedor que registra la llamada. | Opcional: imagen con systemd real (`--privileged`, cgroup) para `reset-failed` real. En el ensayo de dos hosts, `uninstall --purge` sobre un host real. |
| 57 | `scripts/tests/test_install_server.py`: `resolve_answers` (precedencia, secreto sólo por archivo), `build_env_values` contra el golden de `prepare_server_env`, `render_firewall_summary`, dispatch del `install.sh` raíz con `bats` o `subprocess` sobre un `docker` falso en `PATH`. | Proyecto de compose aislado (patrón `fim-c52-it` de `tasks.md:26`): `install.sh server install --non-interactive` completo, salud `ok`, segunda ejecución → exit 1; modo `all` en una VM o contenedor con Docker-in-Docker: el agente enrola contra `localhost`. | Aceptación de un solo host (P6 del documento fuente). |
| 58 | `backend/tests/test_migrations.py`: descubrimiento, duplicados, checksum distinto, baseline sobre base vacía, aplicación sobre base previa (Postgres de pruebas); `test_install_server_upgrade_plan.py` (orden de pasos, códigos de salida). | Proyecto aislado: `upgrade` feliz (seriales de la CA intactos y datos presentes); `upgrade` con una migración `999_fail.sql` inyectada → exit 6, `pg_restore` y conteos de filas iguales a los previos; `uninstall --keep-data` → volúmenes presentes; `uninstall --purge --no-export --confirm-host` → `docker volume ls --filter label=com.docker.compose.project=<p>` vacío y sin imágenes `fim-*:dev`; `--purge` sin exportación → exit 10 sin cambios. | — |
| 59 | `crypto` (ida y vuelta, AAD cruzado falla), precedencia por clave, auditoría sin valores, `GET` sin secreto, invalidación de caché. Vitest: formulario, origen, contraseña de sólo escritura. | Backend + Mailpit (patrón de `tasks.md:112`, hallazgo 14.7): cambiar SMTP por la API y enviar una alerta real **sin reiniciar** el backend. | Playwright: editar SMTP y ejecutar «enviar prueba» contra Mailpit. |

### 6.2 Desinstalación sin residuos en contenedor descartable

Sobre el fixture `container` de `agent/tests/integration/test_install_sh_container.py`:

1. **Antes de instalar**, tomar un inventario:
   `find / -xdev \( -path /proc -o -path /sys -o -path /dev -o -path /workspace -o -path /tmp -o -path /var/log/fim-systemctl-shim.log -o -path /var/lib/fim-systemctl-shim \) -prune -o -print | sort > /tmp/before`,
   más `getent passwd fim-agent` (vacío).
2. Instalar, consumir el bootstrap simulado y generar datos en `quarantine/` y `queue/`.
3. `bash agent/install.sh uninstall --purge --non-interactive`.
4. Inventario `after` y `diff before after`. Se exige un diff vacío, salvo una lista explícita y
   comentada: `__pycache__` del repositorio montado y los archivos del shim.
5. Afirmar en `/var/log/fim-systemctl-shim.log` la secuencia `stop`, `disable`, `daemon-reload`,
   `reset-failed`, en ese orden.
6. `--keep-data`: afirmar que `/var/lib/fim-agent/**` queda byte a byte igual (hash de árbol antes y
   después) y que `/opt/fim-agent`, `/etc/fim-agent` y la unidad no existen.

### 6.3 Ensayo real de dos hosts (A-5)

- Nueva carpeta `tesis/cierre/evidencia/a5-join-token-lifecycle-<ts>/`. Nunca se modifican A-3 ni A-4.
- Misma estructura que `tesis/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md`:
  Anfitriones, Qué se puede afirmar, Qué no se puede afirmar, Resultados por punto de control, Métricas
  clave, Hallazgos, Índice de evidencia, Cómo verificar el paquete, y `SHA256SUMS`.
- Puntos de control mínimos:
  1. Acuñado desde la consola del servidor.
  2. Instalación del agente con `--join-token-file`, **sin copiar `fim-ca.pem`**. Se registra el
     número de pasos manuales frente a A-3.
  3. Evento visible en la consola.
  4. Reuso del token → 401.
  5. Token con huella alterada → aborta sin escritura.
  6. `uninstall --purge` en el host monitoreado → agente `revoked` en la consola, sin transición a
     `dead`, inventario sin residuos.
  7. Desde el host monitoreado, con el certificado viejo: `/agents/renew` → 403; `XADD` a `events`
     aceptado por Valkey pero descartado en ingesta (**se documenta la brecha de D64**).
  8. Con 58: `upgrade` con reversión forzada.

---

## 7. Revisión de seguridad del diseño

| Riesgo | Vector | Mitigación en el diseño | Residual |
|---|---|---|---|
| **Fuga del token** | Historial de shell, `ps`, `/proc/<pid>/cmdline`, variables de entorno heredadas | Sólo `--join-token-file` o prompt oculto; rechazo explícito de `--join-token` (extensión de `agent/installer.py:223-232`); `install.sh` nunca lee el contenido (sólo reescribe la ruta, `:90` en adelante) | El archivo del token queda en disco hasta que el operador lo borra; el instalador sugiere borrarlo al terminar y lo borra en modo `all` |
| Fuga en la consola | Caché de TanStack Query, `toast`, logs del navegador, proxies | Token sólo en estado local del modal, `Cache-Control: no-store`, sin `toast`; el backend nunca lo registra (structlog sanitizado) y lo audita sin secreto | Portapapeles del sistema del administrador |
| Fuga en `/etc/fim-agent/env` | `FIM_JOIN_CREDENTIALS` persiste tras el consumo | Un solo uso (sin valor tras el consumo); `0600 root:root` (`installer.py:470`); `repair` y `status` lo detectan y ofrecen vaciarlo | Igual que hoy con `FIM_BOOTSTRAP_SECRET` |
| **Replay** | Reuso del secreto consumido | `SELECT ... FOR UPDATE` + `consumed_at` en la misma transacción que la emisión; test de concurrencia | Ninguno conocido |
| Fuerza bruta | Enumerar `tid` o adivinar `secret` | `tid` de 8 bytes sin valor de autorización; `secret` de 256 bits; límite por IP en `/agents/join`; misma respuesta 401 para toda causa | — |
| Oráculo de tiempo | Distinguir `tid` inexistente de secreto incorrecto | `_ph.verify` contra un hash ficticio cuando no existe el `tid` | Diferencias menores entre expirado y vivo (no revelan el secreto) |
| **Anclaje de huella: canal del token comprometido** | El payload no está firmado: quien altera el token en tránsito cambia host **y** huella a la vez | Precondición declarada: el canal por el que viaja el token debe preservar integridad (mismo supuesto que `kubeadm join`); el TTL corto acota la ventana | No es mitigable sin un secreto previo compartido; se documenta |
| Anclaje: objeto equivocado | Hashear el certificado hoja en lugar de la CA, o PEM en lugar de DER | Definición única (SHA-256 del DER de la CA) compartida por `agent/installer.py:245`, `backend/app/modules/agents/cli.py:43` y el fixture de contrato | — |
| Anclaje: `verify=False` | Redirecciones, cuerpo gigante | `follow_redirects=False`, límite de 16 KiB, sólo `/agents/ca.pem`, y la huella se verifica antes de cualquier escritura o envío del CSR | — |
| Anclaje: rotación de CA | Tokens emitidos antes de una rotación | Fuera de alcance (Non-Goal de 52, `design.md:29`); la huella distinta aborta con mensaje claro | — |
| **Suplantación de la baja (consola)** | CSRF, clic accidental | La API usa bearer en el encabezado (`backend/app/core/deps.py:26`, `OAuth2PasswordBearer`), así que no hay CSRF; confirmación tipeada del `agent_id`; auditoría | Administrador comprometido (fuera de alcance, RN-94 lo registra) |
| Suplantación de la baja (mTLS) | Dar de baja otro agente cambiando el cuerpo | Identidad desde el CN del certificado presentado, nunca del cuerpo (misma lección IDOR que la change 50, `CHANGES.md:1021-1048`) | Quien robe el certificado de un agente puede darlo de baja: es una denegación de servicio que falla cerrada y queda auditada, y el atacante ya tenía capacidad equivalente |
| **Brechas de revocación** | Certificado vigente de un agente dado de baja contra 6380 | Descarte en ingesta (D26); ACL de Valkey evaluada en spike (D64) | **Lectura del stream `commands`** hasta el vencimiento (≤ 90 días): rutas y `event_id` de otros agentes |
| Brechas de revocación | Handshake en 8443 | Dependencia `require_agent_peer` obligatoria en toda ruta de `mtls_app`, con test que recorre las rutas | El handshake TLS completa y el rechazo es HTTP 403 |
| Brechas de revocación | Serial no registrado (certificados emitidos antes de la change 53) | `status = revoked` bloquea igual; `agent_certificates` sólo cubre emisiones posteriores | Los certificados previos no quedan en `revoked_certificates` (se documenta; vencen naturalmente) |
| **Secretos en argumentos y logs del servidor** | `docker compose exec ... mint-token`, `pg_dump` | El token sale por stdout redirigido a un archivo `0600` y nunca a la terminal en modo `all`; `pg_dump` usa las credenciales ya presentes en el entorno del contenedor `db`, sin `PGPASSWORD` en la línea de comando; `install_server.py` nunca usa `set -x` ni imprime valores de `.env` | Root del host puede leer `/proc/<pid>/environ` (igual que hoy) |
| **Irreversibilidad de la purga** | `--purge` destruye la CA y la evidencia | Confirmación escrita del host; `--yes` nunca la habilita; exportación exigida o renuncia escrita (D71); aviso de re-enrolamiento; los respaldos no se borran sin `--purge-backups` | Borrado lógico, sin garantía física en SSD o sistemas con journaling (se documenta) |
| **Permisos de respaldo** | Volcados con hashes de contraseñas, `N8N_ENCRYPTION_KEY`, **clave privada de la CA** | `umask 077`, directorio `0700` root, archivos `0600`, fuera del árbol del repositorio (`/var/backups/fim/`) para evitar un `git add`, `SHA256SUMS` para detectar alteración | Sin cifrado del respaldo (se deja como mejora: `age` o `gpg` con clave del operador) |
| Asistente web (opcional) | Token en la URL (historial, `Referer`), exposición de red | `127.0.0.1` exclusivamente, un solo uso, `Referrer-Policy: no-referrer`, timeout de 15 minutos, sin acceso a Docker | Otro usuario local del servidor puede alcanzar el puerto de loopback (no tiene el token) |

---

## 8. Orden sugerido e hitos

```
H0  (ahora)            cerrar D63–D65 ─► /opsx:propose 53 ─► apply 53 ─► esperar archive 52 ─► archive 53
H1  (tras archive 52)  cerrar D66–D67 ─► 54 ─► 55 ─► ensayo A-5 (puntos 1–5)
H2                     cerrar D68–D69 ─► 56 ─► ensayo A-5 (puntos 6–7)
H3                     cerrar D70–D71 ─► 57 ─► 58 ─► ensayo A-5 (punto 8)
H4  (paralelo a H1–H3) cerrar D72 ─► 59
Opcional               D73–D75 ─► 60 / 61 / 62
```

**Primera entrega de valor mínima: change 53.**

- **Valor:** cierra G13 y G14, alinea la spec `backend-pki` con el código y es prerrequisito de toda
  desinstalación.
- **Tamaño:** unas 25 tareas, sin instalador ni infraestructura.
- **Riesgo de conflicto:** bajo con 52, porque su implementación está terminada y sólo aporta deltas
  distintos a `backend-agents` y `backend-pki`. Medio con 50: hay que coordinar la extracción de
  `require_agent_peer` desde `renew_certificate`.
- **Evidencia:** unitarias + integración mTLS + un test del lab aislado. No invalida A-3 ni A-4 porque
  no toca el bootstrap.

La segunda entrega con más valor visible es la **55**, que es la que elimina el ida y vuelta manual.
Depende de 54 y del archive de 52.

---

## 9. Impacto en la tesis

- **Candidato vigente:** el consolidado auditado en V10 es `7a7ee50`, con suites PASS
  (`tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md:41`), más la aceptación A-4 de 52
  (`tesis/cierre/evidencia/a4-vps-acceptance-20260915T153824Z`).
- **Todo cambio de código de este documento exige un candidato consolidado nuevo**, con las mismas
  capas que V10 (agente, backend con TLS de Valkey, frontend, scripts, E2E y OpenSpec) y custodia
  íntegra, antes de citarlo en la tesis.
- Los ensayos existentes (A-3, A-4, baterías del Capítulo 5) siguen valiendo **para el código que
  midieron**. No se reescriben: se agregan paquetes nuevos.

| Alcance implementado | Qué se puede afirmar | Qué no se puede afirmar | Re-validación necesaria |
|---|---|---|---|
| Ninguno (recomendación del documento fuente) | Lo actual: despliegue multi-host con registro por script (A-3, A-4) | Enrolamiento con un solo valor, baja, desinstalación | Ninguna; todo va al Capítulo 8 |
| 53 | «Un administrador da de baja un agente; su certificado queda registrado como revocado; sus mensajes se descartan y no dispara alertas de vida» | Revocación a nivel TLS; aislamiento del stream `commands` frente a un certificado revocado | Candidato nuevo; test del lab aislado; **no** re-correr baterías del Capítulo 5 (no toca detección ni ingesta de eventos válidos) |
| 53 + 54 + 55 | Además: «Un agente se enrola con un token de un solo uso, con expiración y revocación, anclando la CA por huella sin copiar archivos» | Integridad del canal por el que viaja el token (supuesto declarado) | Candidato nuevo + ensayo A-5 de dos hosts. A-3 sigue valiendo para el camino legado, que se conserva |
| + 56 | Además: «Desinstalación del agente sin residuos, verificada en contenedor y en host real» | Borrado físico seguro | A-5 puntos 6–7 |
| + 57 + 58 | Además: «Instalación de servidor desde un único punto de entrada y actualización con reversión automática verificada» | Alta disponibilidad (RN-76) | A-5 punto 8 + prueba de reversión en proyecto aislado |
| + 59 | Además: «Configuración de notificaciones editable sin reinicio, auditada y cifrada en reposo» | Canales de n8n en caliente | **Re-correr la batería de notificaciones** (toca `alerts/service.py`) |

**Qué queda en el Capítulo 8 si no se implementa.** La auditoría V10 ya valida ese capítulo con
pendientes como multianfitrión y SMTP (`AUDITORIA_INTEGRAL_TESIS_V10.md:209`). Se agregan:

- enrolamiento por token con anclaje de CA;
- UI de alta de agentes (Non-Goal deliberado de 52, `design.md:27`);
- baja con revocación efectiva en 6380 (ACL de Valkey o streams por agente, D64 B/C);
- desinstalación del agente y del servidor;
- actualización con respaldo y ejecutor de migraciones;
- configuración en caliente;
- Let's Encrypt (Non-Goal de 52, `design.md:28`);
- sub-path;
- asistente web.

**Recomendación:** si el calendario de cierre sólo admite una change, la **53** es la que más fortalece
la narrativa. Corrige una afirmación de spec que hoy no se cumple (`backend-pki`, «Certificate
revocation check») y no toca el flujo validado por A-3 y A-4. El resto conviene presentarlo como
trabajo futuro con este documento como diseño ya verificado contra el código.

---

## Archivos relevantes

- `docs/implementaciones/instalador-unificado-y-token-de-union.md` (documento fuente)
- `openspec/changes/vps-deployment-readiness/{design.md,tasks.md,specs/}` (solo lectura)
- `openspec/changes/backend-agent-cert-renewal/proposal.md`
- `CHANGES.md` (`:1021`, `:1080`, `:1103`)
- `docs/reglas_de_negocio.md` (`:32`, `:787`, `:875`, `:1040`, `:1678`, `:1860`, `:1993`)
- `docs/arquitectura_stack.md` (`:2623`, `:2685`)
- `backend/app/modules/agents/{models.py,service.py,router.py,cli.py,heartbeat_consumer.py,streams.py}`
- `backend/app/modules/events/consumer.py`, `backend/app/modules/rules/{models.py,service.py}`
- `backend/app/core/{pki.py,config.py,deps.py,audit.py,rate_limit.py,streams.py}`, `backend/app/main.py`
- `backend/app/modules/audit/models.py`, `backend/app/modules/alerts/{service.py,notifier.py}`, `backend/app/core/health.py`
- `backend/db/migrations/`
- `agent/{install.sh,installer.py,bootstrap.py,__main__.py,commands.py,queue.py}`, `agent/deploy/fim-agent.service`
- `agent/tests/integration/{test_install_sh_container.py,docker/}`
- `scripts/{prepare_server_env.py,register-agent.sh}`, `scripts/tests/test_compose_topology.py`
- `docker-compose.yml`, `docker-compose.tls.yml`
- `frontend/src/{api/agents.ts,hooks/useAgents.ts,pages/Agents.tsx,App.tsx}`, `frontend/src/components/ui/{ModalDialog.tsx,AgentCard.tsx}`, `frontend/src/components/layout/Sidebar.tsx`
- `frontend/playwright.isolated-lab.config.ts`, `frontend/e2e/us-isolated-lab.spec.ts`
- `docs/despliegue_servidor_remoto.md`
- `tesis/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md`, `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md`
