# Cambios sugeridos para la tesis — V11

> Este documento propone redacción de reemplazo para los hallazgos que
> `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` (§13 «Tabla completa de riesgos» y §17 «Plan
> priorizado de correcciones residuales») clasifica como solucionables mediante texto, e
> incorpora evidencia producida **después** del cierre de esa auditoría. No implementa código,
> no repite ensayos y no declara aptitud productiva. No reemplaza el trabajo pendiente que la
> auditoría clasifica como no solucionable por texto (A-1, A-2, A-4, N-2, N-3, N-4, M-4, M-9,
> B-1, M-2, M-3): esos puntos permanecen fuera de alcance de este documento.

## 0. Objeto y trazabilidad

| Documento | Identidad |
|---|---|
| Auditoría base | `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md`, 12 de septiembre de 2026, calificación 7,8/10 |
| Objeto auditado por V10 | `docs/cierre/Tesis_v10_cierre_tecnico.docx`, SHA-256 `99dfbca3f8b2c807cdbf085b2387946ef4149e04bafce9226507848318c61436` |
| DOCX actual en el repositorio | `docs/cierre/Tesis_v10_cierre_tecnico.docx`, SHA-256 `2b6552de09ca1adea2b1ea11b9a8fdc7e7c175f821a9a7a3f631fb1c0fbda6ae` (difiere del auditado) |
| Render usado para extraer el texto vigente | `docs/cierre/evidencia/v10-closure-20260912T190052Z/build/render/Tesis_v10_cierre_tecnico.pdf` (174 páginas, `pdftotext -layout`) |

**Verificación de vigencia del render.** Se comparó el texto extraído del PDF contra
`word/document.xml` del DOCX actual (`2b6552de…`) para las cuatro frases más sensibles de este
documento. Las cuatro están presentes textualmente en el DOCX actual: «efectivamente ofrece
en» (§4.9), «únicamente para corrección estilística» (Declaración de originalidad), «verifica la
versión del esquema aplicada» (Anexo D) y «Tailwind CSS 4.0» (§4.6). Es decir, el DOCX actual
**ya corrigió el Anexo E** (ver §3 de este documento) pero **no corrigió** ninguno de los demás
puntos que se tratan aquí. Todo «Texto actual (V10)» citado abajo, salvo el de Anexo E, sigue
vigente en `2b6552de…` al momento de escribir este documento.

## 1. Propósito y alcance

Este documento cubre exactamente los hallazgos de §13/§17 de la auditoría V10 que son
solucionables mediante redacción, más la evidencia de validación multianfitrión y VPS
producida después del cierre de V10:

1. **A-3** (Alto) — Ausencia de ensayo multianfitrión con TLS de Valkey en despliegue, ahora
   cubierta por evidencia nueva: un ensayo de dos anfitriones con rechazos negativos y una
   aceptación de despliegue en un VPS público con un agente remoto (`a3-multihost/`, `a4-vps-acceptance-20260915T153824Z/`,
   `a4-vps-20260915T145238Z/`).
2. **N-6, N-7, N-8** (Bajos) — Anexo E, «ofrece en producción», fila 7/19 de Tabla 18, Tailwind,
   límites de US-09 en Tabla 22, cita de la prueba de skew en US-08.
3. Otras correcciones detectadas durante esta revisión: la afirmación sobre migraciones
   automáticas del backend (Anexo D), y las limitaciones de cuarentena/diff (L-1 a L-7) que deben
   declararse si no se corrigen antes de una versión final.

Quedan **fuera de alcance**: N-1 (declaración de originalidad, retirada por decisión del autor) y, por no ser solucionables mediante redacción según la propia auditoría, A-1
(hipótesis no corroborada), A-2 (concurrencia en una sola corrida), A-4 (backlog 23/8/0), N-2
(evidencia no versionada), N-3/N-4 (ensayos sobre commit anterior), M-4 (cola sin cifrar, token
SSE), M-9 (SBOM/digests), M-2/M-3/B-1 (triangulación de latencia, segundo evaluador NIST,
figuras raster).

## 2. Tabla resumen

| Hallazgo | Ubicación en V10 | Acción propuesta | Fuente principal |
|---|---|---|---|
| A-3 | §4.9 (p. 83); Tabla 20 fila 9 (p. 120); Resumen (p. 5); Abstract (p. 8); Capítulo 8 §8.1 (p. 126) | Incorporar el ensayo de dos anfitriones con mTLS/TLS de Valkey y la aceptación VPS, con sus límites explícitos | `a3-multihost/README.md`, `RUNBOOK_WSL2_MTLS.md`; `a4-vps-acceptance-20260915T153824Z/README.md` |
| N-6 | Anexo E (p. 158) | Ya corregido en el DOCX actual (`2b6552de…`); solo confirmar | `agent/deploy/fim-agent.service:20-33` |
| N-7 (Anexo E) | — | ver N-6 | — |
| N-7 («ofrece en producción») | §4.9 (p. 81) | Reformular sin afirmación de producción | — |
| N-7 (Tabla 18, fila «Falsos negativos») | Tabla 18 (p. 105-106) | Aclarar 7 (B3) + 12 (B5) = 19 | `docs/cierre/evidencia/INDICE.md` |
| N-7 (Tailwind) | §4.6 (p. 73); Tabla 5 (p. 59) | Unificar en «Tailwind CSS 4» o «4.3.1» | `frontend/package.json`, `frontend/pnpm-lock.yaml` |
| N-7 (US-09 en Tabla 22) | Tabla 22, fila US-09 (p. 168) | Agregar límites a la columna «Límites» | `docs/implementaciones/cuarentena-y-diff-arreglos.md` |
| N-8 (US-08 en Tabla 22) | Tabla 22, fila US-08 (p. 168) | Citar la prueba de rechazo por skew | `backend/tests/test_stream_ack_durability_consumer.py`, `test_consumer.py` |
| N-7 (nota Figura 9, «host monitoreado») | Nota de Figura 9 (p. 158) | Unificar terminología con «anfitrión», preservando la distinción de rol | `docs/despliegue_servidor_remoto.md` |
| Otras — migraciones | Anexo D (p. 157) | Corregir: no hay aplicación automática de migraciones | `backend/app/main.py`, `docker-compose.yml`, `backend/db/migrations/` |
| Otras — límites de cuarentena/diff | Nueva subsección | Declarar L-1 a L-7 | `docs/implementaciones/cuarentena-y-diff-arreglos-como-implementar.md` §8.3 |
| N-3, N-4 (no se cierran en V11) | §3.7 (p. 55); Nota de Tabla 18 (p. 106); Resumen (p. 5); Abstract (p. 8) | Reforzar la advertencia de procedencia de los ensayos y laboratorios; el cierre se difiere a una versión posterior | Decisión del autor, 2026-09-16 |

## 3. N-1 — Declaración de originalidad

Retirada de este documento por decisión del autor. El hallazgo N-1 de la auditoría V10 queda
registrado como pendiente de decisión del autor y no se propone texto de reemplazo aquí.

## 4. A-3 — Ensayo multianfitrión con mTLS/TLS de Valkey y A-4 — Aceptación en VPS

### 4.1 Qué cambia respecto de V10

Al momento del cierre de la auditoría V10 (12 de septiembre de 2026), el carril multianfitrión
constaba solo del plan `lanes/l9/` (basado en WSL2, no ejecutado tal como estaba escrito). Con
posterioridad al cierre de esa auditoría se generaron dos paquetes de evidencia nuevos:

1. **`a3-multihost/`** (dentro de `docs/cierre/evidencia/v10-closure-20260912T190052Z/`,
   ejecutado y documentado el 2026-09-12, con timestamp de carpeta posterior al de la
   auditoría): ensayo real sobre dos equipos físicos con mTLS agente-backend y TLS con
   certificado de cliente en Valkey.
2. **`a4-vps-acceptance-20260915T153824Z/`** y su carpeta hermana
   **`a4-vps-20260915T145238Z/`** (2026-09-14/15): aceptación del grupo 12 del change
   `vps-deployment-readiness` contra un servidor VPS público real.

Ninguno de los dos valida el candidato consolidado V10 (`7a7ee50`): ambos corrieron sobre la
rama `devel`, no sobre la rama `integration-v10` que fijó el candidato consolidado. Por eso esta sección no reclasifica A-3 como cerrado;
lo actualiza para reflejar que ya existe una validación real, acotada, de dos anfitriones con TLS
de Valkey, distinta de —y no equivalente a— una validación multianfitrión productiva.

### 4.2 A-3 — Ensayo de dos anfitriones (`a3-multihost/`)

**Hardware y código.** El ensayo usó dos equipos físicos conectados por LAN doméstica: una
laptop (`192.168.1.43`) que corrió el stack Docker Compose completo (backend, Valkey con TLS
y certificado de cliente, PostgreSQL, frontend), y una segunda PC física (`192.168.1.36`) con
**Ubuntu 26.04.1 LTS instalado en disco** (host Linux de metal desnudo, kernel `7.0.0-31-generic`,
sin virtualización), con el agente FIM nativo bajo `systemd` en un entorno virtual Python 3.13 (el
Python de sistema de esa PC es 3.14, incompatible con las dependencias del agente). El plan
original contemplaba monitorear esa PC vía WSL2; WSL2 se descartó **antes** de instalar el
agente y se reemplazó por Ubuntu nativo en disco, precisamente para poder afirmar un
anfitrión Linux de metal desnudo sin la VM de Hyper-V, el reloj heredado de Windows ni la red
espejo. El nombre del archivo `RUNBOOK_WSL2_MTLS.md` se conserva por trazabilidad con el
plan preliminar; el registro de WSL2 en ese archivo es un intento descartado, no el ensayo
ejecutado.

El código evaluado fue la línea de desarrollo `devel` a la fecha del ensayo, con las correcciones
citadas: HEAD inicial `223f85c`, más los arreglos `f9a536a` (listener TLS 1.3 dedicado al
bootstrap en el puerto 8444, D52/RN-146), `f552aa6` (Authority Key Identifier ausente en el
certificado de Valkey) y `656b101` (preflight de escritura con falso `permission_denied` por
`os.access` sin `effective_ids=True`). Este ensayo **no** corrió sobre el candidato consolidado
V10 `7a7ee50`.

**Qué se puede afirmar.** Sobre dos equipos físicos conectados por LAN: mTLS agente-backend y
TLS con certificado de cliente en Valkey verificados, incluidos los rechazos negativos
(controles V1-V4, B1-B3, E1-E2, 9/9 aprobados) y capturas de tráfico en ambos extremos sin
cadenas del protocolo en claro (0 coincidencias de `event_id`, rutas, `diff_text` ni el marcador
de redacción, con control positivo de presencia real en el backend).

**Qué no se puede afirmar.** Despliegue productivo, alta disponibilidad, red WAN/Internet, ni
rendimiento extrapolable: es un único agente sobre LAN doméstica con la laptop por Wi-Fi. No
incluyó n8n (n8n estaba degradado durante A-3), por lo que no hay ensayo de notificación
multianfitrión. La latencia observada mezcla el reloj de dos equipos sin corrección de offset.

**Hallazgos corregidos durante el ensayo:** el bootstrap sin canal TLS (D52/RN-146, commit
`f9a536a`), el certificado de Valkey sin Authority Key Identifier (commit `f552aa6`), y el falso
`permission_denied` del preflight de escritura (commit `656b101`).

**Hallazgos abiertos que deben declararse como limitaciones:**

- `process_exe` llega vacío en los eventos generados durante el ensayo (Fase 5, paso 1).
- Los eventos `file_created` llegan con `diff_text` vacío: el contenido inicial de un archivo
  nuevo no viaja en el evento.
- Un archivo creado 2 s después de crear su directorio se informó como `file_modified` en
  lugar de `file_created`.
- El stream `commands`, compartido por todos los agentes, tenía **38 794 mensajes** históricos
  de agentes de laboratorio anteriores; un agente nuevo los recorre íntegros al arrancar, lo que
  generó más de 22 000 líneas de `detector.out_of_scope_drop` y `publisher.command_signature_invalid`
  en el journal durante los primeros 20 s. El rechazo de esos comandos ajenos es correcto; el
  registro como advertencia genera ruido operativo.
- Persisten aproximadamente **65 eventos `detector.out_of_scope_drop` por minuto**, causados
  por que la marca fanotify usa `FAN_MARK_FILESYSTEM` sobre el filesystem raíz de la PC y ese
  filesystem es compartido con el directorio vigilado, por lo que se omite la máscara de
  exclusión y cualquier escritura ajena de otro proceso del escritorio genera un evento
  descartado por el filtro de alcance.
- El listener mTLS del backend (puerto 8443) no envía una alerta TLS legible al rechazar una
  conexión: corta con `unexpected eof`/`errno=104` en lugar de una alerta TLS explícita, a
  diferencia de Valkey.
- **`install.sh` re-ejecutado anidaba el código** (`cp -r` copiaba el árbol dentro de sí mismo en
  una segunda instalación) — este hallazgo, abierto durante A-3 (2026-09-12), **ya no se
  reprodujo en A-4** (ver §4.3): la tarea 12.5 de A-4 confirma explícitamente que la reinstalación
  «no anida `/opt/fim-agent/agent/agent`». La corrección exacta que cerró este punto entre A-3 y
  A-4 no aparece como un hallazgo numerado propio en el índice 14.1-14.7 de A-4; es plausible
  que haya quedado resuelta junto con el endurecimiento de `install.sh` del commit `b644d3a`,
  pero esa atribución puntual no está confirmada de forma explícita en las fuentes disponibles
  `[CONFIRMAR POR EL AUTOR]`.

### 4.3 A-4 — Aceptación de despliegue en un VPS público

**Entorno.** Servidor central: VPS de HostGator, Ubuntu 22.04.5, kernel 6.8, 1 vCPU, 1,9 GiB
RAM, Docker 29.7.2, Compose v5.5.0, IP pública `129.121.57.46`, sin firewall de host (solo
fail2ban para SSH). Host monitoreado: la PC del operador, Ubuntu 26.04, kernel 7.0, systemd
259, Python de sistema 3.14.4 (agente con Python 3.13.14). Código: rama `devel`, commit
`2f84d60` al iniciar, con los arreglos de los hallazgos llegados en el rango `ed286d9..277a458`.
Fechas: 2026-09-14 y 2026-09-15. Tampoco corrió sobre el candidato consolidado `7a7ee50`.

**Resultados por tarea (grupo 12 del change `vps-deployment-readiness`):** las seis tareas (12.1
a 12.6) resultaron **PASA**, cinco de ellas con hallazgos abiertos durante la propia corrida que
se corrigieron antes de sellar la evidencia (grupo 14, commits `b644d3a`, `a071534`, `67ddfde`,
`16a2e3c`, `b0865c6`): validación de la versión de Python en `install.sh`, resolución de rutas
relativas de `--ca-cert`/`--bootstrap-secret-file`, secreto de bootstrap opcional en reinstalación
de un agente ya enrolado, aviso y CLI auditado para `ADMIN_PASSWORD` ignorado en
silencio, re-provisioning de n8n dentro del propio entrypoint del contenedor, orígenes CORS
generados con ambos esquemas al cambiar a `self_signed`, y corrección del cuerpo vacío del
correo de alerta.

**Qué se puede afirmar:** un servidor central con Docker Compose corriendo en un VPS público
real acepta el registro y bootstrap de un agente remoto por los puertos 8444/6380, entrega
eventos visibles en la consola, sirve la consola por HTTP/HTTPS según el modo configurado, y
entrega una alerta real por email vía Gmail después de una reinstalación del agente que no
anidó su código.

**Qué no se puede afirmar:** que dos `POST` con el mismo `event_id` produzcan un único ticket
(no verificado en este entorno: el VPS no tiene un sistema de tickets controlado; esa propiedad
sigue cubierta solo por la verificación aislada del grupo 8 del change, no por esta corrida).
Tampoco alta disponibilidad, ni que los arreglos 14.5 y 14.7 —reverificados en un proyecto
Docker aislado, no en el VPS— se sostengan en infraestructura real sin una reverificación
adicional pendiente y documentada aparte para no alterar el `SHA256SUMS` de esta carpeta.

**Nota sobre unificación de rama.** El 2026-09-15 los commits del candidato V10 (carriles L1-L8
y L10, backlog y el arreglo E2E; el carril L9 se excluyó como superado) se integraron en
`devel` y se subieron (`devel` en `925dab5`). La regresión completa sobre esa rama aprobó:
agente 597 + 1 omitida, backend 754/754 con `TEST_VALKEY_TLS=1`, frontend 197/197,
comprobación de tipos y build correctos, OpenSpec 44 especificaciones/249 requisitos. Esta
regresión **no** es un candidato consolidado congelado con custodia equivalente al de V10; una
nueva validación consolidada con custodia sigue pendiente. Si corresponde citar esta
unificación en la tesis, y con qué alcance, se deja `[CONFIRMAR POR EL AUTOR]`; en ningún
caso debe presentarse como reemplazo de un paquete consolidado con custodia.

### 4.4 Texto propuesto — §4.9 (agregado al final de la sección, antes de §4.10)

> «Con posterioridad a la validación consolidada del candidato `7a7ee50`, se ejecutó un ensayo
> sobre dos equipos físicos conectados por red local doméstica —una laptop con el servidor
> central en Docker Compose y una segunda PC con Ubuntu 26.04.1 LTS instalado en disco como
> host monitoreado, sin virtualización— sobre la línea de desarrollo `devel` a la fecha del
> ensayo, con las correcciones citadas en el Anexo F. El ensayo verificó mTLS agente-backend y
> TLS con certificado de cliente en Valkey, incluidos los rechazos negativos y la ausencia de
> cadenas del protocolo en claro en capturas de tráfico de ambos extremos. No incluyó n8n, no
> corrió sobre el candidato `7a7ee50`, y su alcance de red se limita a una LAN doméstica: ese
> ensayo, por sí solo, no acredita despliegue productivo, alta disponibilidad, operación sobre
> redes de área amplia ni rendimiento extrapolable. Quedaron abiertos, entre otros, la atribución vacía de `process_exe`, la ausencia
> de `diff_text` en la creación de archivos, y un volumen de mensajes históricos del stream
> `commands` que genera ruido de journal al primer arranque de un agente nuevo. Por separado,
> se aceptó el despliegue del servidor central en un proveedor de VPS público real, con registro,
> bootstrap e ingesta de eventos de un agente remoto, y entrega de una alerta real por correo
> electrónico. En esa corrida el agente, alojado en otro equipo, abrió el transporte cifrado
> `valkeys://` contra la dirección pública del servidor con verificación de nombre y sin entradas
> en el archivo de anfitriones, mientras los puertos internos permanecieron cerrados desde fuera;
> el transporte Valkey con TLS queda así acreditado también sobre Internet. Tampoco esta corrida
> usó el candidato `7a7ee50`, ni repitió sobre esa topología los rechazos negativos del ensayo
> anterior, ni acredita operación con múltiples agentes concurrentes, alta disponibilidad o
> rendimiento: el servidor dispone de una sola CPU virtual.»

### 4.5 Texto propuesto — Tabla 20, fila 9 (columna «Resultado» y «Limitación»)

**Resultado** (agregar a continuación del texto vigente):

> «[...] mTLS agente-backend verificado en evaluación local controlada; cliente mTLS
> backend-Valkey verificado contra un contenedor local; HMAC y cifrado local evaluados en
> pruebas dirigidas. Con posterioridad, un ensayo sobre dos anfitriones físicos verificó el mismo
> mTLS agente-backend y TLS con certificado de cliente en Valkey sobre una LAN doméstica,
> incluidos rechazos negativos y ausencia de cadenas en claro en capturas de tráfico.»

**Limitación** (agregar):

> «[...] La corrida histórica, Run 4 y los E2E usaron Valkey sin TLS. El ensayo de dos anfitriones
> acredita TLS de Valkey y mTLS agente-backend sobre LAN doméstica, con rechazos negativos
> (certificado ausente, autoridad ajena, certificado vencido y nombre no coincidente) y capturas
> sin cadenas en claro. La aceptación en un VPS público acredita además el mismo transporte
> sobre Internet: el agente, en otro equipo, se conectó a `valkeys://` contra la dirección pública
> con verificación de nombre y sin entradas en `/etc/hosts`, mientras los puertos internos
> permanecieron cerrados desde fuera. No se acreditan los rechazos negativos repetidos sobre esa
> topología, la operación con múltiples agentes concurrentes, la alta disponibilidad, el
> rendimiento —el VPS dispone de una CPU virtual— ni la aptitud productiva; ninguno de los dos
> ensayos corrió sobre el candidato `7a7ee50`. La clave maestra permanece en el anfitrión.»

### 4.6 Texto propuesto — Resumen y Abstract

**Resumen** (agregar antes de la última oración del párrafo de resultados, «La evidencia no
acredita...»):

> «Un ensayo posterior sobre dos equipos físicos verificó mTLS agente-backend y TLS con
> certificado de cliente en Valkey en una red local doméstica, y un despliegue del servidor
> central en un servidor VPS público aceptó el registro, el bootstrap y la ingesta de eventos de
> un agente remoto. Ninguno de los dos ensayos corrió sobre el candidato consolidado
> `7a7ee50`. La aceptación en el VPS verifica el transporte cifrado sobre Internet, pero ninguno
> acredita operación con múltiples agentes concurrentes, alta disponibilidad, rendimiento ni
> aptitud productiva.»

**Abstract** (equivalente en inglés, mismo punto de inserción):

> «A subsequent trial across two physical hosts verified mutual TLS between agent and backend
> and TLS with client certificate for Valkey over a home local network, and a deployment of the
> central server on a public VPS accepted registration, bootstrap and event ingestion from a
> remote agent, over the public Internet and without host-file entries. Neither trial ran on the
> consolidated candidate `7a7ee50`, nor do they establish operation with multiple concurrent
> agents, high availability, performance, or production readiness.»

### 4.7 Texto propuesto — Capítulo 8, §8.1 (ajuste de lo ya cerrado)

**Texto actual (V10):**

> «Permanecen fuera de la evidencia la identificación completa de un código deontológico
> institucional, la entrega SMTP real, **el transporte Valkey con TLS**, la concurrencia extremo a
> extremo con n8n y canal final, **la validación multianfitrión** y la aptitud productiva.»

**Texto propuesto (V11):**

> «Permanecen fuera de la evidencia la identificación completa de un código deontológico
> institucional, la entrega SMTP real, la concurrencia extremo a extremo con n8n y canal final, y
> la aptitud productiva. El transporte Valkey con TLS y una validación de dos anfitriones cuentan
> ahora con un ensayo de dos anfitriones —con rechazos negativos y capturas de tráfico— y con
> una aceptación de despliegue en un VPS público, donde un agente remoto operó sobre Internet
> con el mismo transporte cifrado. Permanecen fuera de la evidencia la operación con múltiples
> agentes concurrentes, la alta disponibilidad, el rendimiento en esa topología y la repetición de
> los rechazos negativos sobre el despliegue público.»

### Fuentes (§4)

- `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md` (completo)
- `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/RUNBOOK_WSL2_MTLS.md`
  (líneas 41-44, 313-320, 450, 487, 657-714, 785)
- `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/README.md` (completo)
- `docs/cierre/evidencia/a4-vps-20260915T145238Z/` (sin `README.md`; solo artefactos
  `a4-12.*.txt` y capturas `19.png`/`20.png`)
- `.gitignore` líneas 62-69 (confirma que `a4-vps-*` está ignorado por git y que
  `v10-closure-20260912T190052Z/a3-multihost/` está explícitamente exceptuado del ignore)
- `git log --oneline -- agent/install.sh agent/installer.py` (commit `b644d3a`)
- `openspec/changes/archive/2026-09-15-vps-deployment-readiness/tasks.md` (78/78 tareas
  completadas; el change ya está archivado bajo esa carpeta, no pendiente como podría sugerir
  una lectura de `openspec list` posterior al archivado)

### Límites (§4)

- Ninguno de los dos paquetes (`a3-multihost/`, `a4-vps-acceptance-20260915T153824Z/`) valida
  el candidato consolidado V10 `7a7ee50`; ambos corrieron sobre `devel`. No debe presentarse
  ninguno de los dos como validación del candidato consolidado.
- `a4-vps-20260915T145238Z/` y `a4-vps-acceptance-20260915T153824Z/` están fuera de control
  de versiones (`.gitignore`): un tercero que clone el repositorio no puede verificarlos sin que el
  autor los adjunte por separado. `a4-vps-acceptance-20260915T153824Z/` tiene `SHA256SUMS`
  propio; `a4-vps-20260915T145238Z/` no tiene `SHA256SUMS` ni `README.md`.
  `a3-multihost/` sí está versionado en git (excepción explícita en `.gitignore`) y tiene su propio
  `SHA256SUMS`.
- La atribución exacta del cierre del hallazgo de anidamiento de `install.sh` entre A-3 y A-4 no
  está confirmada en una fuente explícita — se marca `[CONFIRMAR POR EL AUTOR]` en el texto
  de §4.2.
- Si corresponde citar la unificación de `devel` (commit `925dab5`) como antecedente adicional,
  y con qué alcance, se marca `[CONFIRMAR POR EL AUTOR]` en §4.3; su evidencia
  (`port2/summary.json`) es local, fuera del repositorio.

## 5. N-6 — Anexo E (capacidades del agente)

### Estado

**Ya corregido en el DOCX actual.** El texto vigente en `docs/cierre/Tesis_v10_cierre_tecnico.docx`
(SHA-256 `2b6552de…`), verificado tanto en el render PDF como directamente en
`word/document.xml`, dice (Anexo E, p. 158):

> «AmbientCapabilities y CapabilityBoundingSet declaran cinco capacidades del núcleo.
> CAP_SYS_ADMIN permite inicializar fanotify y marcar sistemas de archivos completos.
> CAP_DAC_READ_SEARCH permite resolver identificadores mediante open_by_handle_at.
> CAP_DAC_OVERRIDE permite crear temporales, renombrar y mover archivos en directorios de
> root durante la restauración y la cuarentena. CAP_FOWNER y CAP_CHOWN permiten
> restaurar permisos, propietario y grupo desde la baseline. Las tres últimas responden a la
> remediación automática, no a la detección, y amplían la superficie de privilegio del proceso. La
> unidad no fija límites de memoria ni de CPU, ni directivas como ProtectHome o
> MemoryDenyWriteExecute.»

Esto coincide con las cinco capacidades y sus justificaciones declaradas en
`agent/deploy/fim-agent.service:20-33`:

```
#  - CAP_SYS_ADMIN: fanotify_init + marcar filesystems completos.
#  - CAP_DAC_READ_SEARCH: open_by_handle_at(2), usado para resolver el path de los
#    eventos en modo FID (creación/borrado/renombrado y objetos ya inexistentes).
#  - CAP_DAC_OVERRIDE: crear el tmp en un directorio root-owned, el rename de
#    os.replace, y el unlink del origen en shutil.move (agent/decision.py).
#  - CAP_FOWNER: fchmod sobre un archivo cuyo dueño no es el euid del proceso
#    (restauración de mode desde el baseline).
#  - CAP_CHOWN: fchown a un uid/gid arbitrario (restauración de uid/gid).
AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN
```

Y también con las demás directivas de endurecimiento reales del unit (`ProtectSystem=strict`,
`NoNewPrivileges=true`, `PrivateTmp=true`, `ReadWritePaths=/var/lib/fim-agent
/var/log/fim-agent`, mas el drop-in `10-watchpaths.conf` que agrega rutas monitoreadas).

**No se requiere ninguna edición adicional para N-6.** Se recomienda únicamente que, al
generar la próxima versión (V11) del PDF/DOCX para una nueva auditoría, se conserve este
párrafo del Anexo E sin reintroducir la afirmación «únicamente CAP_SYS_ADMIN».

### Fuentes

- `agent/deploy/fim-agent.service` líneas 20-33
- `docs/cierre/Tesis_v10_cierre_tecnico.docx` → `word/document.xml` (extracción directa)
- `docs/cierre/evidencia/v10-closure-20260912T190052Z/build/render/Tesis_v10_cierre_tecnico.pdf`, p. 158

## 6. N-7 — Residuos editoriales puntuales

### 6.1 «Efectivamente ofrece en producción» (§4.9, p. 81)

**Texto actual (V10):**

> «El costo de la decisión es explícito: la batería del backend requiere un entorno con Docker
> disponible y su tiempo de ejecución se mide en minutos antes que en milisegundos. **El
> beneficio es que las propiedades verificadas son las que el sistema efectivamente ofrece en
> producción.** La batería del agente, en cambio, sí opera sin infraestructura [...]»

**Texto propuesto (V11):**

> «El costo de la decisión es explícito: la batería del backend requiere un entorno con Docker
> disponible y su tiempo de ejecución se mide en minutos antes que en milisegundos. El
> beneficio es que las propiedades verificadas son las mismas propiedades concurrentes y
> transaccionales que el sistema ejerce en su operación normal, y no solo la interfaz de los
> servicios de respaldo. La batería del agente, en cambio, sí opera sin infraestructura [...]»

**Fuente:** `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` fila N-7 (§13); extracción PDF, p. 81.
**Límite:** es una corrección puramente editorial; no cambia el alcance de lo verificado.

### 6.2 Tabla 18, fila «Falsos negativos» (p. 105-106)

**Texto actual (V10):**

> «Falsos negativos (n) — 7 operaciones sin evento, causa no establecida — 0 — Histórico
> indeterminado. Corrida causal nueva: 50 eventos y 10 descartes legítimos; no reclasifica los 19
> históricos.»

La fila consigna «7» y el resto de la tesis remite a «los 19 históricos» sin que la propia fila
explique la relación entre ambos números.

**Texto propuesto (V11)** (columna «Estado», agregar):

> «[...] Histórico indeterminado: 7 operaciones sin evento de la batería de detección (B3, filas de
> secuencia 193, 196, 209, 270, 323, 364 y 369) más 12 operaciones sin evento de la batería de
> desconexión (B5, ver fila "Preservación de eventos ante desconexión" de esta misma tabla)
> suman las 19 ausencias históricas citadas en el resto del documento. Corrida causal nueva: 50
> eventos y 10 descartes legítimos; no reclasifica ninguna de las 19.»

**Fuentes:** `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` fila N-7 (§13); extracción PDF,
p. 105-106; `docs/cierre/evidencia/INDICE.md` («Operaciones históricas sin evento» — B3: 193,
196, 209, 270, 323, 364, 369; B5: 185, 276, 291, 380, 982, 1243, 1299, 1311, 1705, 1957, 2078, 2767).
**Límite:** aclara la aritmética; no reconstruye la causalidad de los 19 casos, que sigue
indeterminada.

### 6.3 Tailwind CSS: «4.0» (§4.6) frente a «4.3.1» (Tabla 5)

**Verificación read-only:** `frontend/package.json` declara `"tailwindcss": "^4.0.0"` y
`"@tailwindcss/vite": "^4.0.0"` (rango de dependencia); `frontend/pnpm-lock.yaml` resuelve
`tailwindcss@4.3.1` (versión efectivamente instalada). Ambas cifras son ciertas para lo que
describen —rango declarado versus versión resuelta—, pero su coexistencia sin aclaración
constituye la discrepancia que señala la auditoría (Tabla 5, nota; N-7).

**Texto actual (V10), §4.6 (p. 73):**

> «La aplicación frontend se implementa como Single Page Application en React 19 con
> TypeScript, empaquetada con Vite, con estilos **Tailwind CSS 4.0** bajo integración nativa
> mediante @tailwindcss/vite.»

**Texto propuesto (V11):**

> «La aplicación frontend se implementa como Single Page Application en React 19 con
> TypeScript, empaquetada con Vite, con estilos **Tailwind CSS 4** (versión resuelta 4.3.1, Tabla 5)
> bajo integración nativa mediante @tailwindcss/vite.»

**Fuentes:** `frontend/package.json` líneas 30, 41; `frontend/pnpm-lock.yaml` líneas 1758, 3475;
extracción PDF, p. 59 y 79.
**Límite:** ninguno; es una unificación editorial respaldada por el lockfile.

### 6.4 US-09 sin límites en Tabla 22 (p. 168)

**Texto actual (V10)**, fila US-09, columna «Límites»:

> «—. Todos los criterios canónicos cuentan con evidencia dentro del alcance indicado.»

Esto contradice —por omisión, no por afirmación— los límites que el propio documento declara
en otras secciones (§4.6, §9.1, Tablas 21a/21b) y que la implementación en el repositorio
confirma: texto UTF-8 estricto acotado a 1 MiB; hex dump acotado a 256 bytes por lado; sin diff
para symlinks, altas, bajas ni archivos sobredimensionados; el diff se calcula acumulado contra
la última baseline aprobada, no de forma incremental entre eventos sucesivos; y no existe
prueba E2E que recorra la cadena completa desde un archivo real modificado hasta el diff
efectivamente renderizado en la consola.

**Texto propuesto (V11)**, columna «Límites»:

> «Texto UTF-8 acotado a 1 MiB; hex dump acotado a 256 bytes por lado; sin diff para symlinks,
> altas, bajas ni archivos sobredimensionados (ver §4.6, §9.1, Tablas 21a/21b). El diff persistido
> es acumulado contra la última baseline aprobada, no incremental entre eventos sucesivos de
> una misma cadena. No existe prueba E2E que recorra la cadena completa desde un archivo real
> modificado hasta el diff renderizado en la consola.»

**Fuentes:** `docs/implementaciones/cuarentena-y-diff-arreglos.md` §2.1 (tabla de estado, filas
«Límites», «Visor en `7a7ee50`», «Pruebas»); `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md`
fila N-7 (§13); extracción PDF, p. 168.
**Límite:** esta corrección solo agrega los límites ya declarados en otras secciones a la fila de la
matriz de backlog; no reabre la clasificación COMPLETA de US-09.

### 6.5 US-08: cita de la prueba de rechazo por skew (p. 168)

**Contexto.** La clasificación COMPLETA de US-08 en Tabla 22 se apoya, para el criterio W13
(«timestamps dobles [...] validados contra clock skew de 5 minutos»), en la evidencia de la lane
`l4` (`docs/cierre/evidencia/v10-closure-20260912T190052Z/lanes/l4/CRITERIOS.md`, criterio 3),
que dice explícitamente:

> «Validación de clock skew (W13) es de ingesta, no de esta vista — ya cubierta fuera de esta
> lane (`test_event_listing_contract.py::test_get_event_by_id_returns_full_detail` verifica
> orden/formato de ambos timestamps)»

Es decir, la prueba citada por esa lane verifica el **formato** de los timestamps en la vista de
detalle, no el **rechazo** de un evento por desfasaje de reloj. La prueba de rechazo real existe,
pero en otro archivo, fuera de esta lane:

- `backend/tests/test_consumer.py::test_reject_clock_skew` — construye un evento con
  `detected_at` dos horas en el pasado y verifica `assert any(r.reason ==
  RejectionReason.clock_skew for r in rejections)`.
- `backend/tests/test_stream_ack_durability_consumer.py::test_sent_at_at_301s_is_rejected` —
  docstring «El otro lado de la frontera: 301 s fuera de la ventana → clock_skew», sobre la
  ventana de skew acotada a `sent_at` (D37/RN-131, el mismo fundamento que Tabla 22 cita para
  aceptar el criterio W13 de US-08).

**Texto actual (V10)**, fila US-08, columna «Límites»:

> «—. Todos los criterios canónicos cuentan con evidencia dentro del alcance indicado.»

**Texto propuesto (V11)**, columna «Límites»:

> «El criterio W13 (validación contra clock skew) se acepta por la enmienda D37/RN-131 (ventana
> sobre `sent_at`); la prueba de rechazo efectivo es de la capa de ingesta, no de esta vista:
> `backend/tests/test_stream_ack_durability_consumer.py::test_sent_at_at_301s_is_rejected` y
> `backend/tests/test_consumer.py::test_reject_clock_skew`. La vista de detalle solo muestra los
> dos timestamps ya persistidos; no ejecuta la validación de skew por sí misma.»

**Fuentes:** `docs/cierre/evidencia/v10-closure-20260912T190052Z/lanes/l4/CRITERIOS.md`
(criterio 3); `backend/tests/test_consumer.py` líneas 303-319; `backend/tests/test_stream_ack_durability_consumer.py`
líneas 5-8, 205-218; `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` fila N-8 (§13); extracción
PDF, p. 168.
**Límite:** esta corrección cita la prueba de rechazo correcta; no cambia que la vista de detalle
en sí misma no valida el skew, ni reabre la clasificación COMPLETA de US-08.

### 6.6 Nota de Figura 9: «host monitoreado» (p. 158)

La fila N-7 de la auditoría (§13) también cita, entre los residuos editoriales, la nota de
Figura 9. El texto vigente de esa nota (p. 158) dice, en su primera oración:

> «El agente se despliega como servicio nativo de systemd en el **host monitoreado**; la baseline
> restaurable permanece cifrada localmente en /var/lib/fim-agent/baseline/. [...]»

El resto del documento —incluida la política terminológica de §10.1— usa «anfitrión» para el
mismo concepto (por ejemplo, en la propia Tabla 20 fila 9 y en la Limitación que este documento
propone en §4.5). «Host monitoreado» no es, sin embargo, un simple sinónimo introducido por
descuido: es el nombre de rol que usa la guía operativa `docs/despliegue_servidor_remoto.md`
(«Operador del host monitoreado», §encabezado; sección 7 «Instalación del agente en el host
monitoreado»), posterior a la mayor parte del cuerpo de la tesis, para distinguir la máquina que
corre el agente de la que corre el servidor central. Reemplazarlo sin más por «anfitrión» en esa
nota perdería esa distinción de rol si la tesis llega a incorporar la guía de despliegue remoto
(§4 de este documento).

**Texto propuesto (V11):**

> «El agente se despliega como servicio nativo de systemd en el anfitrión monitoreado (el host
> cuyo filesystem se vigila, distinto del servidor central); la baseline restaurable permanece
> cifrada localmente en /var/lib/fim-agent/baseline/. [...]»

**Fuentes:** extracción PDF, p. 158 (nota de Figura 9); `docs/despliegue_servidor_remoto.md` §1
y §7 (uso canónico de «host monitoreado» como rol, no como sinónimo suelto de «anfitrión»);
`docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` fila N-7 (§13).

**Límite:** `[CONFIRMAR POR EL AUTOR]` si la tesis adopta formalmente «host monitoreado» como
término de rol (alineado con la guía de despliegue remoto) en lugar de unificarlo con
«anfitrión»; el texto propuesto arriba es una unificación mínima que conserva ambas ideas, pero
no es la única corrección editorial posible.

## 7. Otras correcciones detectadas

### 7.1 Migraciones automáticas del backend (Anexo D, p. 157)

**Texto actual (V10):**

> «El servicio backend ejecuta la imagen construida del backend; en su rutina de arranque
> (lifespan de FastAPI) **verifica la versión del esquema aplicada contra las migraciones
> numeradas y aplica las pendientes antes de aceptar tráfico**; la creación inicial de las tablas se
> practica mediante scripts SQL en el primer arranque de PostgreSQL, conforme al apartado 4.5
> y siembra el usuario administrador inicial con flag de cambio forzado de contraseña, antes de
> aceptar tráfico.»

**Verificación read-only.** `backend/app/main.py` (función `lifespan`) solo ejecuta
`SQLModel.metadata.create_all(engine)` seguido de `seed_admin()`; no hay código que lea,
compare ni aplique los archivos de `backend/db/migrations/*.sql` (16 archivos, `001_...sql` a
`016_...sql`) en el arranque. `docker-compose.yml` monta `./db/init:/docker-entrypoint-initdb.d:ro`,
que la imagen oficial de PostgreSQL ejecuta **solo en el primer arranque** de un volumen
nuevo; ese directorio no es `backend/db/migrations/`. `docs/cierre/REPRODUCIR.md` §5 ya
documenta la aplicación de esas migraciones como un paso **manual** («Aplicar migraciones
desde una instalación limpia», con un bucle explícito de `psql` sobre cada archivo), consistente
con que el backend no las aplica por sí mismo.

**Texto propuesto (V11):**

> «El servicio backend ejecuta la imagen construida del backend; en su rutina de arranque
> (lifespan de FastAPI) crea las tablas declaradas por los modelos si no existen
> (`SQLModel.metadata.create_all`) y siembra el usuario administrador inicial con flag de cambio
> forzado de contraseña, antes de aceptar tráfico. La evolución posterior del esquema se
> gobierna mediante los archivos numerados y versionados de `backend/db/migrations/`, que se
> aplican de forma manual y no automática en el arranque del backend; la creación inicial de las
> tablas de la base de datos `fim_n8n` se practica mediante scripts SQL en el primer arranque de
> PostgreSQL, conforme al apartado 4.5.»

**Fuentes:** `backend/app/main.py` líneas 3-10, 75-89; `docker-compose.yml` líneas 41-60;
`backend/db/migrations/001_add_agent_status_revoked.sql` a `016_add_event_binary_diff_metadata.sql`;
`docs/cierre/REPRODUCIR.md` §5.
**Límite:** esta corrección describe el comportamiento real del código; no evalúa si sería
deseable automatizar la aplicación de migraciones, lo que quedaría como trabajo futuro si se
decide abordarlo.

### 7.2 Limitaciones de cuarentena y diff a declarar (L-1 a L-7)

`docs/implementaciones/cuarentena-y-diff-arreglos-como-implementar.md` §8.3 («Limitaciones a
declarar si Q-1 y U-1 no se corrigen») enumera siete limitaciones verificadas por lectura de
código sobre `devel` (commit `2f84d60`) y contrastadas contra el candidato V10 (`7a7ee50`).
**L-7 ya no aplica**: el modo binario, la detección automática y `react-diff-viewer-continued`,
ausentes en `devel` al momento de ese documento, ya están presentes en `devel` en el commit
`1c68e79` («feat(events): binary diff mode and react-diff-viewer-continued for US-09»),
verificado directamente en `frontend/src/components/ui/DiffViewer.tsx` y
`frontend/src/pages/EventDetail.tsx` del HEAD actual. Las demás (L-1 a L-6) no tienen, en las
fuentes revisadas para este documento, evidencia de que se hayan corregido; se listan a
continuación como limitaciones a declarar, salvo que se corrijan antes de cerrar V11
`[CONFIRMAR POR EL AUTOR]`.

- **L-1 (Q-1, ampliado por X-1).** Tras una cuarentena, tanto automática como iniciada por el
  operador, el agente borra de su baseline local la última versión aprobada y sus snapshots.
  Desde ese momento no puede restaurarse la versión sana de ese archivo, ni automática ni
  manualmente, hasta una nueva aprobación. Esto contradice RN-37. Excepción: si una regla
  `auto_restore` coincide con la ruta en el camino del operador, el eco restaura implícitamente el
  archivo.
- **L-2 (X-1).** Cada cuarentena automática genera, además del evento `quarantined`, un evento
  `file_deleted` en estado `pending` con `action_error=file_not_found`, originado por la propia
  eliminación del archivo por el agente. Verificado por lectura de código; la afirmación
  cuantitativa requiere una corrida de laboratorio dedicada.
- **L-3 (Q-2).** El producto no ofrece liberar, descartar ni restaurar desde un artefacto de
  cuarentena. Un falso positivo solo se resuelve fuera del producto, como root y con
  `master_secret`.
- **L-4 (Q-4).** El mismo resultado físico se registra como `quarantined` (automático) o
  `rejected` (operador); filtrar por `quarantined` no muestra lo cuarentenado por el operador.
- **L-5 (U-1).** La consola ofrece Aprobar y Rechazar en eventos `alert_only`; la operación
  siempre termina en 409.
- **L-6 (X-2).** Un archivo creado inmediatamente después de su directorio puede reportarse
  como `file_modified`, sin entrada de baseline, y generar eventos repetidos hasta su
  aprobación. Mecanismo verificado por lectura y observado en el ensayo A-3; sin prueba
  dedicada.

**Fuentes:** `docs/implementaciones/cuarentena-y-diff-arreglos-como-implementar.md` §8.2-8.3
(líneas 997-1032); `docs/implementaciones/cuarentena-y-diff-arreglos.md` §3 (tabla de defectos);
`git log --oneline -- frontend/src/components/ui/DiffViewer.tsx` (commit `1c68e79`).
**Límite:** L-1 a L-6 se listan tal como los documenta la exploración citada, que es un documento
de diagnóstico, no de implementación (declara explícitamente «no implementa nada»); ninguna
corrección de código se aplicó como parte de este documento.

### 7.3 N-3 y N-4 — advertencia reforzada, sin cierre en esta versión

**Decisión del autor (2026-09-16):** V11 **no** cierra N-3 ni N-4. Los tres ensayos de cierre
(concurrencia, drenaje y latencia con inicio externo) y los laboratorios de US-23 y US-24 se
repetirán sobre un candidato congelado posterior, una vez archivados los changes en curso que
modifican las rutas medidas —en particular el cifrado de la cola local del agente, que afecta
directamente al drenaje—. Ese cierre corresponde a una versión posterior del informe, no a V11.

En consecuencia, V11 sólo refuerza la advertencia de procedencia. El escritor **no debe**
presentar esos resultados como medidos sobre el candidato vigente ni atenuar la advertencia
existente.

**Texto ya presente en V10 que se conserva (§3.7, p. 55):**

> «Esos ensayos no se repitieron sobre el candidato vigente 7a7ee50; sus resultados describen el
> candidato 7df4935.»

**Agregado propuesto — Nota de la Tabla 18 (p. 106), al final de la nota vigente:**

> «Las filas de concurrencia, drenaje repetido y latencia con inicio externo proceden de ensayos
> ejecutados sobre el candidato 7df4935. El candidato posterior modificó las rutas de drenaje, de
> cola y de transporte Valkey, de modo que esos valores no describen su comportamiento y no se
> reejecutaron para esta versión. La evidencia por criterio de US-23 y US-24 proviene, del mismo
> modo, de laboratorios ejecutados en cabezas de carril y no en el paquete consolidado.»

**Agregado propuesto — Resumen y Abstract**, una oración al final del párrafo de resultados:

> «Los ensayos de concurrencia, drenaje y latencia describen el candidato 7df4935 y no fueron
> reejecutados sobre versiones posteriores.»

> «The concurrency, drain and latency experiments describe candidate 7df4935 and were not
> re-executed on later versions.»

**Límites.** Esta redacción no cierra N-3 ni N-4: los mantiene declarados con precisión, que es la
alternativa mínima que la propia auditoría admite («reforzar la advertencia en Resumen y Tabla
18», fila N-3). El cierre exige reejecutar los ensayos y los laboratorios sobre un candidato
congelado y publicar su paquete de evidencia.

### 7.4 Ajuste de criterios canónicos del 2026-09-15 — declaración obligatoria

**Hecho verificado.** El commit `cc73c2d` (2026-09-15, 17:02) modificó el texto de cinco criterios
de aceptación en `docs/historias_de_usuario.md`, alineándolos con la implementación vigente:

| Historia | Texto anterior | Texto vigente | Respaldo |
|---|---|---|---|
| US-01, US-27 | redirige a `/account/change-password` | redirige a `/change-password` | **Sin decisión previa registrada**: no hay mención de la ruta en `reglas_de_negocio.md` ni en `arquitectura_stack.md` |
| US-05, US-29 | banner ante `failed_notifications` con `retry_count >= 3` | banner ante `alerts` en fallo terminal (`delivered_at IS NULL AND failed_at IS NOT NULL`), sin umbral | D6/RN-102 y D6/RN-107, anteriores al ajuste |
| US-23 | fila en `failed_notifications(event_id, payload_json, last_error, failed_at, retry_count)` | fila de `alerts` en fallo terminal con `failed_at`, `last_error` y `retry_count` | D6/RN-107, anterior al ajuste |
| US-29 | enlace a `/notifications/failed` | enlace a `/alerts/failed` | Consecuencia del anterior |

**Por qué debe declararse.** Las versiones anteriores del informe sostienen que las divergencias
entre el criterio canónico y la implementación **no se reinterpretan como cumplimiento**. Tres de
las historias afectadas (US-01, US-05, US-23) pasan a completas en el recuento reconciliado, y una
parte de ese cambio proviene del ajuste del texto, no sólo de código nuevo. Omitirlo dejaría al
lector sin el dato que necesita para evaluar el recuento, y la comparación con el historial del
repositorio lo expondría igual.

**Texto propuesto (V11), como nota al pie del recuento de historias (§5.5.1 y nota de la Tabla 22):**

> «Nota sobre los criterios de aceptación. El 15 de septiembre de 2026 se ajustó el texto de cinco
> criterios en el backlog canónico (US-01, US-05, US-23, US-27 y US-29) para reflejar decisiones de
> diseño ya vigentes: la unificación de la tabla de notificaciones fallidas en `alerts` (D6/RN-107)
> y la definición del banner de fallo terminal sin umbral de reintentos (D6/RN-102). El ajuste de
> la ruta del cambio forzado de contraseña, de `/account/change-password` a `/change-password`, no
> cuenta con una decisión previa registrada y se documenta aquí como alineación del texto con la
> implementación. Las reclasificaciones que dependen de ese ajuste se identifican en la tabla de
> reclasificaciones del anexo de trazabilidad; el resto se apoya en implementación y pruebas
> nuevas. Los criterios anteriores se conservan en el historial del repositorio (`cc73c2d`).»

**Alcance.** Esta nota no revierte el ajuste ni lo justifica retrospectivamente: lo declara con
fecha, commit y respaldo, distinguiendo lo que tiene decisión previa de lo que no.

### 7.5 Recuento reconciliado y filas de la Tabla 22 a modificar

**Corte vigente:** 25 COMPLETA / 6 PARCIAL / 0 = 31, sobre `devel`, commit `2475de8`
(2026-09-16), documentado en `docs/cierre/MATRIZ_TRAZABILIDAD.md` y
`docs/trazabilidad_us_tests.md`. Los cortes 3/27/1, 10/21/0, 12/19/0 y 23/8/0 se conservan como
historia.

**Cambios respecto de la Tabla 22 de V10 (23/8):**

| Fila | V10 | V11 | Fundamento |
|---|---|---|---|
| US-05 | PARCIAL | COMPLETA | Change 55, posterior a `7a7ee50` |
| US-12 | PARCIAL | COMPLETA | Change 55 (criterio C10 del modal y estado del journal) |
| US-23 | PARCIAL | COMPLETA | Payload de contexto ya emitido desde `670f3c3` (2026-08-24); faltaba acreditarlo |
| US-01 | PARCIAL | COMPLETA | Ajuste de criterio de §7.4 más las pruebas citadas en el anexo de trazabilidad. El commit `f87230a` que la matriz cita como origen de esas pruebas corresponde en realidad a «fix(auth): scope refresh cookie and link access/refresh revocation» (2026-09-13): verificar la cita antes de publicarla `[CONFIRMAR POR EL AUTOR]` |
| US-07 | COMPLETA | PARCIAL | El selector enumera 6 de los 7 estados; V10 no registró la divergencia |
| US-21 | PARCIAL | PARCIAL | Mismo fundamento: `queue_pressure` viaja como proporción, no como indicador booleano |
| US-22 | PARCIAL | PARCIAL | Cambia el fundamento: queda un único criterio sin prueba, la confirmación visual |

**Parciales del corte vigente:** US-07, US-11, US-21, US-22, US-27 y US-29, cada una con su
criterio faltante en el anexo de trazabilidad.

**Instrucción para el escritor.** La Tabla 22, su nota de recuento, el Resumen, el Abstract y los
apartados que citan «23 completas y 8 parciales» deben pasar a 25/6/0 con la fecha y el commit del
corte, conservando los recuentos anteriores como históricos.

## 8. Pendientes y marcadores

### Marcadores `[CONFIRMAR POR EL AUTOR]` introducidos en este documento

1. §4.2 — A-3: atribución exacta del commit o cambio que cerró el hallazgo de anidamiento de
   `install.sh` entre A-3 (2026-09-12) y A-4 (2026-09-14/15).
2. §4.3 — A-4: si corresponde citar la unificación de `devel` (commit `925dab5`, 2026-09-15) en
   la tesis, y con qué alcance exacto.
3. §7.2 — Limitaciones de cuarentena/diff: si L-1 a L-6 se corrigen antes de cerrar V11, en cuyo
   caso esta subsección debe actualizarse o retirarse.
4. §6.6 — Nota de Figura 9: si la tesis adopta «host monitoreado» como término de rol (alineado
   con `docs/despliegue_servidor_remoto.md`) en vez de unificarlo con «anfitrión».

### Hallazgos de §13/§17 de la auditoría V10 dejados fuera de este documento, y por qué

- **N-1** (declaración de originalidad): retirada por decisión del autor; no se propone texto.
- **A-1** (hipótesis no corroborada): no es un defecto de redacción; la auditoría pide mantenerla
  y explicitar qué criterios sí se sostienen, lo cual ya hace el texto vigente (§5.8). No requiere
  corrección de texto adicional identificada en esta revisión.
- **A-2** (concurrencia en una sola corrida exitosa): requiere repetir el ensayo (≥ 5 corridas), no
  redactar.
- **A-4** (backlog 23/8/0): requiere completar criterios de código (US-27, US-29, US-11, US-12),
  no redactar.
- **N-2** (evidencia no versionada): requiere entregar o versionar paquetes de evidencia; excede
  los archivos permitidos para esta tarea y no es una corrección de texto.
- **N-3, N-4** (ensayos sobre `7df4935`, no sobre `7a7ee50`): por decisión del autor
  (2026-09-16) **no se cierran en V11**. Se reejecutarán sobre un candidato congelado posterior,
  después de archivar los changes en curso que modifican las rutas medidas, y su cierre
  corresponde a una versión posterior del informe. V11 sólo refuerza la advertencia de
  procedencia (§7.3 de este documento). La evidencia A-3/A-4 de §4 es adicional a estos
  hallazgos, no una respuesta a ellos: tampoco corre sobre `7a7ee50`.
- **M-4** (cola local sin cifrar, token SSE en query): requiere cambios de código.
- **M-9** (SBOM/digests de imágenes base por etiqueta): requiere fijar digests y gestionar un
  depósito institucional; no es redacción.
- **M-2, M-3, B-1** (triangulación del fin de latencia, segundo evaluador NIST, figuras raster sin
  fuente editable): requieren instrumentación, un segundo evaluador o rediseño gráfico,
  respectivamente; ninguno es una corrección de texto.
- **N-5** (higiene de manifiestos secundarios): requiere regenerar manifiestos con una nota de
  ajuste; es operación sobre evidencia, no redacción de la tesis, y las carpetas de evidencia están
  fuera de los archivos permitidos para esta tarea.
