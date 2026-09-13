# A-3 — Ensayo multianfitrión con mTLS y TLS de Valkey

Paquete de evidencia del ensayo A-3: verificación del FIM sobre **dos equipos físicos** distintos, conectados por
LAN doméstica, con mTLS agente–backend y TLS con certificado de cliente en Valkey. Ejecutado el 2026-09-12. El
equipo monitoreado es una **segunda PC física** con **Ubuntu 26.04.1 LTS instalado en disco** (host Linux de metal
desnudo): no es una máquina virtual ni WSL2. Registro completo, paso a paso, en `RUNBOOK_WSL2_MTLS.md` (el nombre
del archivo se conserva por trazabilidad con referencias anteriores; ver la nota al inicio de ese archivo).

## Anfitriones

| Rol | Equipo | Detalle |
|---|---|---|
| Servidor central | Laptop, `192.168.1.43` | Docker Compose: backend, Valkey (TLS + certificado de cliente), PostgreSQL, frontend. Conectada por Wi-Fi |
| Monitoreado | Segunda PC física, `192.168.1.36` | Ubuntu 26.04.1 LTS instalado en disco (metal desnudo, no VM); agente FIM nativo `a3-pc-ubuntu` vía `systemd`, en un venv Python 3.13 (el sistema trae Python 3.14, no compatible con las dependencias del agente; ver runbook) |

**Sobre WSL2:** el plan original monitoreaba la PC con Ubuntu sobre WSL2. WSL2 pasó su punto de control, pero se
descartó antes de instalar el agente y se reemplazó por Ubuntu nativo instalado en disco en la misma PC física,
para poder afirmar "anfitrión Linux de metal desnudo" y eliminar la VM de Hyper-V, el reloj heredado de Windows y
la red espejo. El registro de WSL2 se conserva en el runbook como intento preliminar descartado; no se usó para el
ensayo. Detalle: runbook, sección "Cambio de plataforma del anfitrión monitoreado".

## Qué se puede afirmar

Ensayo sobre dos equipos físicos conectados por LAN; agente nativo en un host Linux de metal desnudo (Ubuntu
26.04.1 LTS instalado en disco en una segunda PC física, sin virtualización); mTLS agente–backend y TLS con
certificado de cliente en Valkey verificados, incluidos los rechazos negativos (V1–V4, B1–B3, E1–E2) y capturas de
tráfico en ambos extremos sin cadenas del protocolo en claro.

## Qué no se puede afirmar

Despliegue productivo, alta disponibilidad, red WAN o Internet, ni rendimiento extrapolable. Es un único agente
sobre una LAN doméstica con la laptop por Wi-Fi: la prueba de 100 modificaciones (Fase 5, paso 4) no es una
medición de rendimiento extrapolable. La búsqueda de cadenas en las capturas (Fase 6, paso D) es por coincidencia
literal de bytes; no descarta codificaciones alternativas.

## Resultados por punto de control

| Punto de control | Veredicto | Runbook |
|---|---|---|
| 1 — Preparar Ubuntu (WSL2, plan preliminar descartado) | PASA | "Punto de control 1" |
| 2 — Preparar la laptop | PARCIAL | "Punto de control 2" |
| 1 (nativo) — Preparar Ubuntu en disco | PASA, con bloqueo en Python (resuelto) | "Punto de control 1 (nativo)" |
| 3 — Servidor central con TLS en Valkey | PASA (3.0–3.7) | "Punto de control 3" |
| 4 — Instalación, registro y bootstrap del agente | PASA | "Punto de control 4" |
| 5 — Pruebas positivas y corte del backend | PASA (pasos 1 a 5) | "Punto de control 5" |
| 6 — Pruebas negativas y capturas | PASA (V1–V4, B1–B3, E1–E2 y capturas) | "Punto de control 6" |
| 7 — Cierre | PASA | "Punto de control 7" (sección 7.6) |

## Métricas clave

| Métrica | Valor | Fuente |
|---|---|---|
| Detección → recepción (base del backend), creación/modificación/borrado básicos (paso 1) | 20 ms / 22 ms / 12 ms | Fase 5, paso 1 |
| Sincronización de regla (`rule_sync`) hasta aplicada en la PC | 8 ms (01:41:07.043 → 01:41:07.051) | Fase 5, paso 2 |
| Aprobación → confirmación de `baseline_update` en la PC | 36 ms | Fase 5, paso 2 |
| Rechazo con restauración → confirmación en la PC | 28 ms | Fase 5, paso 3 |
| 100 modificaciones: publicación → confirmación (journal PC) | n=100/100, mín 6,1 ms, mediana 17,4 ms, p95 23,1 ms, máx 43,8 ms | Fase 5, paso 4 |
| 100 modificaciones: detección → recepción (base backend, reloj de dos equipos) | n=100, mín 6,7 ms, mediana 26,1 ms, p95 199,5 ms, máx 291,7 ms | Fase 5, paso 4 |
| Corte de backend (120 s): eventos 2 a 10, detección → recepción | 114,9 a 123,0 s | Fase 5, paso 5 |
| Corte de backend: re-publicaciones / confirmaciones / descartes | 11 / 10 / 0 | Fase 5, paso 5 |
| Pruebas Valkey (V1–V4) y backend mTLS (B1–B3, E1–E2), incluidos los controles positivos V3 y B3 | 9/9 PASA | Fase 6, pasos A y B |
| Captura laptop, ronda 1 / ronda 2 | 413 paquetes (0 descartados) / 297 paquetes | Fase 6, paso D |
| Captura PC, ronda 1 / ronda 2 | 220 paquetes / 135 paquetes (0 descartados) | Fase 6, paso D |
| Cadenas estructurales buscadas en capturas (`event_id`, rutas, `diff_text`, marcador) | 0 coincidencias en ambos extremos, con control positivo de presencia real en el backend | Fase 6, paso D |

## Hallazgos

### Corregidos durante el ensayo

- **D52/RN-146 — bootstrap sin canal TLS:** el listener TLS dedicado al bootstrap (puerto 8444) se agregó antes de
  la Fase 4. Commit `f9a536a`. Ver runbook: "Hallazgo previo a la Fase 4" y "Corrección del bootstrap".
- **Certificado de Valkey sin Authority Key Identifier:** el certificado del servidor Valkey no tenía la extensión
  AKI, rechazado en modo estricto por Python 3.13. Commit `f552aa6`. Ver runbook: "Fase 3 — intento 1" (falla) y
  "Fase 3 — intento 2" (corrección).
- **Preflight de escritura con falso `permission_denied`:** `os.access` sin `effective_ids=True` descarta las
  capabilities efectivas para un uid no root. Commit `656b101`. Ver runbook: "Hallazgo en la Fase 4 — el preflight
  de escritura da falso `permission_denied`" y su despliegue posterior.
- **L8 — identidad del backend ante Valkey:** resuelto por configuración (certificado de cliente propio del
  backend, `CN=fim-backend-valkey`), sin cambios de código; no generó commit. Archivos:
  `emitir_cert_cliente_backend_valkey.py`, `docker-compose.a3.yml`. Ver runbook: "Fase 3", tabla "Decisiones de
  esta fase".

### Hallazgos abiertos, no corregidos

- **`install.sh` re-ejecutado anida el código:** `cp -r` copia el árbol dentro de sí mismo en una segunda
  instalación en lugar de reemplazarlo. Ver runbook: "Hallazgo en la Fase 4 — re-ejecutar `install.sh` no
  actualiza el código del agente".
- **Ruido del stream `commands` compartido:** un agente nuevo recorre el historial completo del stream y registra
  `command_signature_invalid` por cada comando ajeno, además de una escritura de `state.json` por mensaje. Ver
  runbook: "Hallazgo en la Fase 4 — avalancha de comandos ajenos al primer arranque".
- **Ruido de `FAN_MARK_FILESYSTEM`:** al compartir filesystem con `/srv/fim-watch`, se omite la máscara de
  exclusión y cualquier escritura ajena en ese filesystem genera un `detector.out_of_scope_drop`. Mismo hallazgo
  que el anterior, sección "Confirmación posterior".
- **El listener 8443 no envía una alerta TLS legible al rechazar:** a diferencia de Valkey, el backend corta la
  conexión (`unexpected eof` / `errno=104`) sin alerta TLS explícita. Ver runbook: "Fase 6 — paso B: detalle de
  B1/B2 y certificado vencido".
- **Tipo de evento de un archivo nuevo:** un archivo creado 2 s después de crear su directorio se informó como
  `file_modified` en lugar de `file_created`. Ver runbook: observación al final de "Fase 5 — paso 2".
- **Los eventos `file_created` llegan con `diff_text` vacío:** el contenido inicial de un archivo nuevo no viaja en
  el evento. Ver runbook: "Fase 6 — paso D: captura de tráfico — ronda 1" (fila del marcador, no concluyente).
- **`process_exe` llega vacío en los eventos:** ver runbook, Fase 5, paso 1.
- **Sobrescritura de evidencia por `aplicar_firewall_a3.sh`:** el script reutilizaba los mismos nombres de archivo
  entre corridas; corregido con nombres con timestamp (ver `fase3/07-firewall-quitado-20260912T232139.txt`). Ver
  runbook: "Fase 3 — paso 3.7", nota "archivos sobrescritos".
- **Desvío de specs de OpenSpec:** `openspec/specs/{backend-agents,agent-bootstrap,backend-pki,infra-compose}`
  describen el comportamiento anterior al bootstrap TLS y no se editaron a mano (guardia de integridad). Ver
  runbook: "Corrección del bootstrap", nota "Desvío de specs".

## Índice de evidencia

- `fase3/` — Fase 3 (servidor central con TLS en Valkey): certificados, configuración, estados del firewall,
  intentos 1 y 2.
- `fase3b/` — verificación del listener de bootstrap TLS (8444) tras su corrección.
- `fase4/` — instalación, registro y bootstrap del agente en la PC.
- `fase5/` — pruebas positivas: eventos básicos, regla `manual_review`, aprobación, rechazo con restauración, 100
  modificaciones, corte del backend y drenaje.
- `fase6/` — pruebas negativas y capturas de tráfico del lado de la laptop (rondas 1 y 2).
- `fase6-pc/` — pruebas negativas, capturas y certificados públicos de prueba copiados desde la PC.
- `fase7/` — evidencia de cierre: stack en texto plano y restauración de IP por DHCP en la laptop.
- `aplicar_firewall_a3.sh` — aplica y quita, en la laptop, las reglas `DOCKER-USER` que restringen 6380/8443/8444
  a la IP de la PC.
- `docker-compose.a3.yml` — override de Compose del ensayo: publica 6380 y configura `VALKEY_URL` con el
  certificado de cliente del backend.
- `emitir_cert_cliente_backend_valkey.py` — emite el certificado de cliente del backend hacia Valkey (carril L8).
- `registrar_agente_a3.sh` — registra el agente de la PC en el backend (`POST /agents/register`) desde la laptop.

**Relación con `lanes/l9/`:** `../lanes/l9/RUNBOOK_PHASES_3_7.md` y `../lanes/l9/README.md` son un plan anterior,
basado en WSL2, para las Fases 3–7, que no se ejecutó tal como está escrito. El procedimiento efectivamente
ejecutado y sus resultados son los de este paquete (`a3-multihost/`).

## Cómo verificar el paquete

```bash
cd docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost
sha256sum -c SHA256SUMS
```
