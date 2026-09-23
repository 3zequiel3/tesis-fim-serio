# Insumos para la v18 — ítems A8, A9, A10, B1, B2 y B3

Recolección de datos, solo lectura, sobre el repositorio `tesis-fim-serio`, rama `devel`,
commit de cabecera `0d4b954`. Los ítems A1 a A7 los cubre otro agente y no se tocan acá.

Regla aplicada en todo el documento: cuando un dato **no se conservó**, **no existe** o **no consta
en el repositorio**, eso es lo que se informa. No se reconstruye, no se aproxima y no se sustituye un
dato histórico por el actual.

Nota de rutas: el material de tesis se movió de `docs/` a `tesis/` en el commit `76d70ad`. Varios
documentos de cierre y los changes archivados conservan rutas viejas (`docs/cierre/...`) a propósito;
cuando se cita una de esas rutas literales se aclara su equivalente actual.

---

## A8 — Pendientes heredados de la v16

### A8.1 — Persistencia de Valkey: NO HAY CONFIGURACIÓN DE PERSISTENCIA

**Dato: el repositorio no configura RDB, AOF ni `appendfsync` en ningún archivo.** No existe
`valkey.conf`. El servicio corre con la configuración por defecto de la imagen
`valkey/valkey:9.0.3`, sobre un volumen nombrado `valkey_data:/data`.

Búsqueda de directivas de persistencia en los dos compose citados:

```
$ rg -n -i 'appendonly|appendfsync|\bsave\b|--save|rdb|aof' docker-compose.yml docker-compose.tls.yml
EXIT=1
```

(`EXIT=1` de `rg` significa cero coincidencias.)

Búsqueda de un archivo de configuración de Valkey:

```
$ fd -H -t f 'docker-compose.*\.ya?ml|valkey.*\.conf' .
./docker-compose.acceptance-lab.yml
./docker-compose.tls.yml
./docker-compose.us02-us20-us31-lab.yml
./docker-compose.yml
./n8n/docker-compose.e2e.yml
./tesis/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/docker-compose.a3.yml
```

No aparece ningún `valkey.conf` en el repositorio.

Servicio completo tal como está declarado, `docker-compose.yml:75-87`:

```yaml
  valkey:
    image: valkey/valkey:9.0.3
    restart: unless-stopped
    volumes:
      - valkey_data:/data
    networks:
      - fim_internal
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 5s
```

El override de TLS, `docker-compose.tls.yml:48-68`, sí define un `command` explícito — y ese
`command` **tampoco** trae directivas de persistencia; solo TLS:

```yaml
  valkey:
    volumes:
      - valkey_data:/data
      - valkey_tls:/certs:ro
    ...
    command: >
      valkey-server
      --port 0
      --tls-port 6380
      --tls-cert-file /certs/valkey.pem
      --tls-key-file /certs/valkey-key.pem
      --tls-ca-cert-file /certs/ca.pem
      --tls-auth-clients yes
```

**Hallazgo relevante para el informe.** La documentación canónica afirma una persistencia que la
configuración no implementa. `docs/arquitectura_stack.md:1565`, tabla de limitaciones conocidas:

> | 4 | **Valkey con persistencia AOF periódica** — un crash puede perder los últimos ms de escrituras | Cola local del agente actúa como buffer antes de la confirmación `XACK + event_ack` del backend (C3), que es la que autoriza la eliminación local. |

Esa es la única mención de AOF en todo el repositorio, y es una afirmación de la prosa, no una
directiva de configuración. La spec de infraestructura tampoco exige persistencia de Valkey:
`openspec/specs/infra-compose/spec.md:120` («Requirement: Volúmenes nombrados para persistencia»)
enumera `pg_data`, `n8n_data` y `backend_certs`, y no menciona `valkey_data` ni política de volcado.

Conclusión para el informe: la mitigación real de la pérdida en un crash es la cola local del agente
más el protocolo ACK (C3), no la persistencia de Valkey. El texto que atribuya AOF a la
configuración desplegada no tiene respaldo en el repositorio.

### A8.2 — Test de desfase de reloj en la ingesta

**Dato:**

```
backend/tests/test_consumer.py::test_reject_clock_skew
```

```
$ rg -n 'def test_.*skew' backend/tests/ agent/tests/
backend/tests/test_consumer.py:303:def test_reject_clock_skew(mem_engine, agent, shared_secret) -> None:
backend/tests/test_c31_backend_event_correctness.py:647:def test_fix08_unparseable_detected_at_rejected_as_clock_skew(mem_engine):
backend/tests/test_stream_ack_durability_consumer.py:297:def test_response_matrix_clock_skew_terminal_nack(mem_engine, agent, shared_secret) -> None:
```

Cuerpo del test principal, `backend/tests/test_consumer.py:303-319`:

```python
def test_reject_clock_skew(mem_engine, agent, shared_secret) -> None:
    from app.core.streams import SCHEMA_VERSION, sign_payload
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    payload = { ... "detected_at": old_time, ... }
    payload["signature"] = sign_payload(shared_secret, payload)
    mock_client = _run_handle(mem_engine, payload)
    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert any(r.reason == RejectionReason.clock_skew for r in rejections)
```

Código bajo prueba (la ventana de W13 se evalúa en dos puntos del consumer de ingesta):

```
$ rg -n '_CLOCK_SKEW_S|CLOCK_SKEW' backend/app/
backend/app/modules/events/consumer.py:82:_CLOCK_SKEW_S = 300  # 5 minutos
backend/app/modules/events/consumer.py:396:        if abs((received_at - sent_at).total_seconds()) > _CLOCK_SKEW_S:
backend/app/modules/events/consumer.py:411:        if abs((received_at - detected_at).total_seconds()) > _CLOCK_SKEW_S:
```

Los otros dos tests son complementarios y también de ingesta: uno cubre la respuesta tipada de
rechazo (`test_response_matrix_clock_skew_terminal_nack`) y el otro el caso de `detected_at`
no parseable (`test_fix08_unparseable_detected_at_rejected_as_clock_skew`). Si el informe necesita
un único nombre, el canónico es el primero.

### A8.3 — Firmas del agente: una de las dos referencias NO corresponde al commit `7a7ee50`

**Los cuatro nombres coinciden con el código.** Verificados directamente contra el árbol de
`7a7ee50`, no contra la rama actual:

```
$ for c in FAN_CLASS_NOTIF FAN_CLOEXEC FAN_REPORT_DFID_NAME FAN_MARK_FILESYSTEM; do
    git show 7a7ee50:agent/_fanotify.py | rg -n "\b$c\b"; done

34:FAN_CLASS_NOTIF = 0x00000000
35:FAN_CLOEXEC = 0x00000001
40:FAN_REPORT_DFID_NAME = FAN_REPORT_DIR_FID | FAN_REPORT_NAME  # 0xC00
136:    flags |= FAN_REPORT_DFID_NAME
49:FAN_MARK_FILESYSTEM = 0x00000100
```

**`agent/_fanotify.py:136` ES correcta en `7a7ee50`.**

```
$ git show 7a7ee50:agent/_fanotify.py | sed -n '132,137p'
   132	def init(flags: int, o_flags: int = os.O_RDONLY | _O_CLOEXEC) -> int:
   133	    """Envuelve fanotify_init(2). Fuerza reporte DFID_NAME para eventos de dir."""
   134	    if _libc is None or not hasattr(_libc, "fanotify_init"):
   135	        raise OSError("fanotify no disponible en esta plataforma")
   136	    flags |= FAN_REPORT_DFID_NAME
   137	    fd = _libc.fanotify_init(ctypes.c_uint(flags), ctypes.c_uint(o_flags))
```

Además, `agent/_fanotify.py` no cambió entre `7a7ee50` y `HEAD`, así que la referencia es válida en
ambos árboles:

```
$ git diff --stat 7a7ee50 HEAD -- agent/_fanotify.py agent/detector.py
 agent/detector.py | 38 ++++++++++++++++++++++++++++++++++++--
 1 file changed, 36 insertions(+), 2 deletions(-)
```

(`agent/_fanotify.py` no aparece: es idéntico.)

**`agent/detector.py:610` NO corresponde a `7a7ee50`. La línea correcta en ese commit es `588`.**

La referencia `detector.py:610` proviene de `tesis/cierre/DATOS_PARA_TESIS_V15.md:135` y `:142`,
donde designa el punto en que el detector estampa la hora del `FanotifyEvent` — es decir, el origen
de `detected_at`, no una bandera de fanotify. En la rama actual esa línea es 610; en `7a7ee50` es
588:

```
$ git show 7a7ee50:agent/detector.py | rg -n 'timestamp=datetime\.now'
588:                    timestamp=datetime.now(timezone.utc).isoformat(),

$ rg -n 'timestamp=datetime\.now' agent/detector.py      # HEAD
610:                    timestamp=datetime.now(timezone.utc).isoformat(),
```

Lo que efectivamente está en la línea 610 de `7a7ee50` es prosa de docstring, no código:

```
$ git show 7a7ee50:agent/detector.py | sed -n '604,613p'
   604	    def _try_enqueue(self, fan_event: FanotifyEvent) -> None:
   605	        """Intenta encolar un evento; si la cola está llena incrementa el contador de drops.
   606	
   607	        US-30: si el detector está en modo drenaje (`set_draining(True)`), el
   608	        evento se descarta sin encolarse — el agente ya dejó de aceptar
   609	        eventos nuevos. `getattr` con default False: detectores construidos
   610	        vía `FanotifyDetector.__new__` en tests preexistentes que no
   611	        inicializan `_draining` deben seguir comportándose como antes.
   612	        """
   613	        if getattr(self, "_draining", False):
```

**Líneas correctas en `7a7ee50` para cada bandera**, por si el informe las necesita:

| Bandera | Definición (`agent/_fanotify.py` @ `7a7ee50`) | Uso (`agent/detector.py` @ `7a7ee50`) |
|---|---|---|
| `FAN_CLASS_NOTIF` | 34 | 454 |
| `FAN_CLOEXEC` | 35 | 454 |
| `FAN_REPORT_DFID_NAME` | 40 (definición), 136 (forzada en `init`) | — (la fuerza el enlace, no el detector) |
| `FAN_MARK_FILESYSTEM` | 49 | 474, 516, 527, 1268, 1281 |

```
$ git show 7a7ee50:agent/detector.py | rg -n 'FAN_CLASS_NOTIF|FAN_CLOEXEC|FAN_MARK_FILESYSTEM'
454:                _fan_mod.FAN_CLASS_NOTIF | _fan_mod.FAN_CLOEXEC
474:                _fan_mod.FAN_MARK_ADD | _fan_mod.FAN_MARK_FILESYSTEM,
481:        # FAN_MARK_FILESYSTEM aplica la máscara de IGNORADOS a TODO el superblock.
516:            | _fan_mod.FAN_MARK_FILESYSTEM
527:            _fan_mod.FAN_MARK_FLUSH | _fan_mod.FAN_MARK_FILESYSTEM,
1268:                    _fan_mod.FAN_MARK_REMOVE | _fan_mod.FAN_MARK_FILESYSTEM,
1281:                    _fan_mod.FAN_MARK_ADD | _fan_mod.FAN_MARK_FILESYSTEM,
```

Consistencia con el documento entregado: la V13 ya usa las líneas correctas para las banderas. El
apartado 1.6 del `.docx` (párrafo 248 del texto extraído) dice «FAN_CLASS_NOTIF y FAN_CLOEXEC,
agent/detector.py, línea 454», «FAN_REPORT_DFID_NAME, agent/_fanotify.py, línea 136» y «líneas 474,
515 a 518, 527, 1268 y 1281». La referencia problemática es únicamente `detector.py:610`, que
aparece en `DATOS_PARA_TESIS_V15.md` para otro fin (el punto de registro de `detected_at`) y que,
proyectada sobre `7a7ee50`, debe leerse **588**.

### A8.4 — Códigos C1…C11 y W2…W13

**Dato: están todos definidos en el repositorio.** Son los «criterios canónicos» del appendix de
auditoría de abril de 2026. Su lugar principal es
`docs/historias_de_usuario.md`, sección `## Appendix: Decisiones de auditoría — Abril 2026`
(`docs/historias_de_usuario.md:597`). La única excepción es **C4**, que no está en ese appendix y se
define en los otros dos documentos canónicos.

```
$ rg -n '^#{2,5} (C[0-9]+|W[0-9]+):' docs/historias_de_usuario.md
603:#### C1: Léxico canónico en minúsculas
610:#### C2: Máquina de estados explícita
614:#### C3: Protocolo ACK Valkey
618:#### C5: Optimistic locking sobre Event
622:#### C10: Rechazo sobre baseline `absent` = no-op con warning
626:#### C11: `ruleset_version` monotónico
632:#### C6: Bootstrap mTLS con CA propia
636:#### C7: HMAC-SHA256 en comandos backend → agente
640:#### C8: Gestión de JWT
644:#### C9: Parámetros Argon2id fijos
648:#### W10: Cifrado de baseline en disco
654:#### W2: Journal pre-acción
658:#### W3: Cola offline con límite y política
662:#### W4: Orden al reconectar
666:#### W5: Rate limiting
670:#### W6: Logging y retention
674:#### W11: Retry de webhook n8n + DLQ + fallbacks
678:#### W12: Endpoint de salud por componente + UI
682:#### W13: Timestamps dobles con anti-replay
686:#### W14: `schema_version` en mensajes
690:#### W16: Heartbeat y estado de agente
694:#### W17: Graceful shutdown
698:#### W18: Tabla `audit_log` separada
704:#### W1: Filtro default oculta `superseded`
708:#### W7: Headers HTTP
712:#### W8: DiffViewer seguro
716:#### W9: Almacenamiento de tokens en cliente
720:#### W15: Bulk actions + paginación
724:#### W20: Seed admin con cambio de password forzado

$ rg -n '^#### C4' docs/arquitectura_stack.md docs/reglas_de_negocio.md
docs/arquitectura_stack.md:1822:#### C4: Backend single-instance
docs/reglas_de_negocio.md:583:#### C4 / RN-76: Backend single-instance (no HA)
```

Tabla de significado (transcripción literal del campo **Decisión** de cada entrada):

| Código | Ruta:línea | Significado |
|---|---|---|
| C1 | `docs/historias_de_usuario.md:603` | Léxico canónico en minúsculas: todos los valores de estado (`pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`) en snake_case minúscula. |
| C2 | `docs/historias_de_usuario.md:610` | Máquina de estados explícita: tabla canónica de transiciones permitidas; las no listadas se rechazan con HTTP 409 a nivel de service. |
| C3 | `docs/historias_de_usuario.md:614` | Protocolo ACK Valkey: consumer group `fim-backend`, `XACK` y `event_ack` en el stream `commands`. El agente borra la entrada local solo al recibir `event_ack`. |
| C4 | `docs/arquitectura_stack.md:1822` y `docs/reglas_de_negocio.md:583` | Backend single-instance (no HA), RN-76. |
| C5 | `docs/historias_de_usuario.md:618` | Optimistic locking sobre `Event`: columna `version`; UPDATE condicionado; 0 filas ⇒ HTTP 409. |
| C6 | `docs/historias_de_usuario.md:632` | Bootstrap mTLS con CA propia: pre-registro `(agent_id, bootstrap_secret)`, CSR firmado con HMAC, cert válido 90 días, rotación 15 días antes de expirar. |
| C7 | `docs/historias_de_usuario.md:636` | HMAC-SHA256 en comandos backend → agente: `signature = HMAC-SHA256(shared_secret, canonical_json(payload))`. |
| C8 | `docs/historias_de_usuario.md:640` | Gestión de JWT: access 15 min, refresh 7 días con rotación, blacklist en Valkey, multi-key signing. |
| C9 | `docs/historias_de_usuario.md:644` | Parámetros Argon2id fijos: `time_cost=3, memory_cost=65536, parallelism=4`. |
| C10 | `docs/historias_de_usuario.md:622` | Rechazo sobre baseline `absent` = no-op con warning: no se envía comando al agente. |
| C11 | `docs/historias_de_usuario.md:626` | `ruleset_version` monotónico en todo comando al agente; el agente descarta versiones menores a la última aplicada. |
| W2 | `docs/historias_de_usuario.md:654` | Journal pre-acción en `/var/lib/fim-agent/journal/{event_id}.json`, con rehidratación al arranque. |
| W3 | `docs/historias_de_usuario.md:658` | Cola offline con límite 100 MB, política drop-oldest, `queue_pressure: true` al 80 %. |
| W4 | `docs/historias_de_usuario.md:662` | Orden al reconectar: primero los comandos pendientes, después los eventos encolados. |
| W5 | `docs/historias_de_usuario.md:666` | Rate limiting: login 5/15 min por `(username + IP)`; API 100 req/min por usuario; stream 100 eventos/min por agente. |
| W6 | `docs/historias_de_usuario.md:670` | Logging y retention: `structlog` JSON, middleware `sanitize_logs`, retención 30 días, prohibido loguear diffs. |
| W7 | `docs/historias_de_usuario.md:708` | Headers HTTP: CSP, HSTS, `X-Frame-Options: DENY`, validación de `Origin`, cookies `SameSite=Strict`. |
| W8 | `docs/historias_de_usuario.md:712` | DiffViewer seguro: `react-diff-viewer-continued` con escapado activo; prohibido `dangerouslySetInnerHTML`. |
| W9 | `docs/historias_de_usuario.md:716` | Almacenamiento de tokens en cliente: access en memoria (Zustand); refresh en cookie `httpOnly`+`Secure`+`SameSite=Strict`+`Path=/auth/refresh`. |
| W10 | `docs/historias_de_usuario.md:648` | Cifrado de baseline en disco: AES-256-GCM con clave derivada `HKDF-SHA256(master_secret, salt=AGENT_ID, info="baseline-v1")`. |
| W11 | `docs/historias_de_usuario.md:674` | Retry de webhook n8n + DLQ + fallbacks: 3 intentos (5 s / 30 s / 120 s), cascada n8n → SMTP → webhook → log crítico. |
| W12 | `docs/historias_de_usuario.md:678` | Endpoint de salud por componente + UI: `GET /health/components` cada 10 s, banner rojo persistente. |
| W13 | `docs/historias_de_usuario.md:682` | Timestamps dobles con anti-replay: `detected_at` + `received_at`; si la diferencia supera 5 minutos se rechaza con código `clock_skew`. |

Notas para quien redacte:

- El rango pedido C1…C11 está completo, pero **no es contiguo dentro de un solo archivo**: C4 vive
  en los otros dos documentos canónicos, porque es una decisión de arquitectura (single-instance) y
  no un criterio de historia de usuario.
- El rango W2…W13 está completo. Las entradas W7, W8 y W9 están en la subsección `### Frontend` del
  mismo appendix, más abajo que W10…W18.
- La serie W llega hasta W20 y **no existe W19**: `rg -n '\bW19\b' docs/ CHANGES.md` no devuelve
  nada. Si el informe enumera «W1 a W20», corresponde aclarar esa ausencia.

---

## A9 — Uso de herramientas de IA

**La declaración la redactan y la firman los autores.** Lo que sigue es únicamente la evidencia
verificable en el repositorio sobre qué herramientas se usaron y dónde se incorporó texto propuesto
por IA. No se propone ni se redacta texto de declaración.

### A9.1 — Qué herramienta está nombrada, y dónde

La única herramienta nombrada explícitamente en el repositorio es **Claude** (Anthropic), en dos
formas:

1. Como autor de marcas de cambio y comentarios del DOCX de la revisión V11. Citado en
   `tesis/cierre/REGISTRO_CAMBIOS_TESIS_V12.md:529-531`:

   > Revisión editorial de la V11 con redacción de reemplazo: `REGISTRO_REVISION_V11.md:5` en
   > `versiones/v11/` — «**Revisión editorial:** asistida por IA (Claude). Las marcas de cambio y
   > los comentarios del DOCX figuran bajo el autor «Claude (revisión V11)».»

   **Ese archivo fuente no se conservó en el repositorio.** `fd -I -H 'REGISTRO_REVISION' .` no
   devuelve nada; el directorio `versiones/v11/` tampoco existe. La cita sobrevive solo de segunda
   mano, dentro del registro de cambios V12.

2. Como huella en el script de ensamblado del documento V10:

   ```
   $ rg -n -i 'claude' tesis/cierre/evidencia/v10-closure-20260912T190052Z/build/step_editorial.py
   7:SCRATCH = '/tmp/claude-1000/-home-ezequiel-Facultad-tesis-tesis-fim-serio/299b0b2b-fc75-4cd3-8adb-b7d8e9d1bfd3/scratchpad'
   ```

No hay ninguna mención de ChatGPT, Copilot, Gemini u otra herramienta en el repositorio.
`CHANGES.md` **no menciona herramientas de IA en ninguna línea**:

```
$ rg -n -i 'inteligencia artificial|herramienta[s]? de IA|asistid[oa] por IA|Claude|ChatGPT|Copilot|LLM' CHANGES.md
(sin salida)
```

### A9.2 — En qué planos consta el uso, según la evidencia preservada

Las auditorías V10 y V11 levantaron el mismo hallazgo (N-1) y lo fundaron en artefactos concretos.
Los artefactos **sí existen**; el archivo de la revisión V11 no.

`tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md:379` (fila N-1 de la tabla de hallazgos):

> N-1 | Alto | Declaración de uso de IA incompleta frente a la evidencia: afirma uso «únicamente
> para corrección estilística» y contribuciones limitadas a «producción textual», mientras los
> paquetes preservan implementación, pruebas, laboratorios y ensamblado del DOCX ejecutados por
> agentes automatizados. […] Evidencia: `lanes/l4/CRITERIOS.md` («no lanzados por este agente», «el
> orquestador»); `lanes/l7/CRITERIOS.md` («per task instructions»); `build/step_editorial.py` (ruta
> de sesión de asistente) y `build/build_v10.py` (reescritura automatizada).

Verificación de que esos artefactos existen y dicen lo que la auditoría cita:

```
$ rg -n -i 'no lanzados por este agente|orquestador' tesis/cierre/evidencia/v10-closure-20260912T190052Z/lanes/l4/CRITERIOS.md
50:`pytest` ajenos (no lanzados por este agente) ejecutándose concurrentemente contra el mismo puerto/DB
60:aislada y siguen en pie para que el orquestador los remueva o los reutilice.

$ rg -n -i 'per task instructions' tesis/cierre/evidencia/v10-closure-20260912T190052Z/lanes/l7/CRITERIOS.md
6:Epistemology (per task instructions): a local controlled SMTP capture server (axllent/mailpit)

$ fd -I -H 'build_v10.py|step_editorial.py' .
./tesis/cierre/evidencia/v10-closure-20260912T190052Z/build/build_v10.py
./tesis/cierre/evidencia/v10-closure-20260912T190052Z/build/step_editorial.py
```

**Advertencia de disponibilidad.** Esos artefactos están en el disco pero **no están versionados en
git**: del paquete `v10-closure-20260912T190052Z/` solo se versionó el subdirectorio `a3-multihost/`.

```
$ git ls-files tesis/cierre/evidencia/v10-closure-20260912T190052Z | wc -l
66
$ fd -I -H -t f . tesis/cierre/evidencia/v10-closure-20260912T190052Z | wc -l
422
```

(`.gitignore:76-77`: `/tesis/cierre/evidencia/v10-closure-20260912T190052Z/*` con la excepción
`!/tesis/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/`.) Es decir: los 356 archivos
que sostienen el hallazgo N-1, incluidos los `lanes/*/CRITERIOS.md` y `build/`, existen únicamente
en la copia local. Si la entrega se hace desde el repositorio, esa evidencia no viaja.

### A9.3 — Historia de la decisión, versión por versión

| Versión | Estado de la declaración | Procedencia |
|---|---|---|
| V10 | La declaración limitaba el uso a «corrección estilística» y a «producción textual». Auditoría abre N-1 (severidad alta). | `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md:45`, `:379` |
| V11 | El autor decide **no** corregirla. La auditoría V11 la evalúa igual e informa nota con y sin ese factor. | `tesis/cierre/PROMPT_AUDITORIA_V11.md:82-84`; `tesis/cierre/CAMBIOS_PARA_TESIS_V11.md:45` («N-1 […] retirada por decisión del autor»), `:742` |
| V11 (auditoría) | El hallazgo se agrava: la propia revisión V11 fue asistida por IA. Costo medido: 0,0167 de nota bruta, que cruza el umbral de redondeo a 8,0. | `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V11.md:237`, `:397`, `:448`, `:507`, `:530-531` |
| V12 | Se redacta el reemplazo de la declaración y de §9.3, **marcado como pendiente de confirmación del autor**. | `tesis/cierre/REGISTRO_CAMBIOS_TESIS_V12.md:493-531` |
| V13 (vigente) | Incorporada. | `tesis/cierre/Tesis_v13_cierre_tecnico.docx` |
| V15 (datos) | Registrada como cerrada. | `tesis/cierre/DATOS_PARA_TESIS_V15.md:232`: «Declaración de uso de IA \| — \| **Cerrada en V12** \| Declaración de originalidad y §9.3 unificadas» |

El encabezado del bloque de redacción propuesta en V12, literal
(`tesis/cierre/REGISTRO_CAMBIOS_TESIS_V12.md:495-497`):

> **PENDIENTE DE CONFIRMACIÓN DEL AUTOR.** Es una declaración jurada sobre el propio proceso de
> trabajo. La redacción que sigue se ciñe a lo que la evidencia del proyecto documenta, pero la
> redacción final la decide el autor.

### A9.4 — Texto vigente en el `.docx` más reciente

Documento más reciente por fecha de modificación:

```
$ eza -l --time-style=long-iso --sort=modified tesis/cierre/*.docx
.rw-rw-r-- 1,6M ezequiel 2026-09-10 19:21 tesis/cierre/Tesis_v5_cierre_tecnico_corregida.docx
.rw-rw-r-- 1,6M ezequiel 2026-09-11 00:10 tesis/cierre/Tesis_v6_cierre_tecnico.docx
.rw-rw-r-- 1,6M ezequiel 2026-09-11 15:06 tesis/cierre/Tesis_v7_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-11 18:01 tesis/cierre/Tesis_v8_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-11 20:50 tesis/cierre/Tesis_v9_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-12 21:31 tesis/cierre/Tesis_v10_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-17 19:58 tesis/cierre/Tesis_v12_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-19 12:32 tesis/cierre/Tesis_v13_cierre_tecnico.docx
```

`Tesis_v13_cierre_tecnico.docx` (19 de septiembre de 2026), cuya portada dice «Versión final V13 —
19 de septiembre de 2026». **No existe un `.docx` de V14 a V17 en el repositorio.** Los `.docx` y
los `AUDITORIA_INTEGRAL_*` / `REGISTRO_CAMBIOS_*` están fuera de git (`.gitignore:59-62`).

**Declaración de originalidad, segundo párrafo, texto literal de la V13** (extraído de
`word/document.xml`):

> Los autores declaran haber utilizado herramientas de inteligencia artificial generativa como
> soporte durante el desarrollo del trabajo, en tres funciones: la búsqueda y verificación de
> información en documentación técnica y normativa; la asistencia en la implementación del código,
> de las pruebas automatizadas y de los laboratorios de verificación, cuyos resultados los autores
> contrastaron contra la evidencia conservada; y las correcciones de redacción, consistencia y
> organización expositiva, incluida la revisión editorial de la versión anterior. La identificación
> del problema, la hipótesis, los objetivos, las decisiones de arquitectura, el protocolo
> experimental, la interpretación de los resultados y las conclusiones fueron decididos por los
> autores, quienes revisaron y aprobaron cada aporte y asumen la responsabilidad plena por el
> contenido.

Firmantes declarados en la misma página: **Ezequiel González** y **Nicolás Castro**.

**§9.3 «Uso de herramientas de inteligencia artificial», texto literal de la V13** (párrafos 1626 a
1628 del texto extraído):

> **9.3 Uso de herramientas de inteligencia artificial**
>
> En concordancia con los lineamientos éticos emergentes sobre el uso de inteligencia artificial en
> la producción académica, los autores declaran que el presente trabajo se realizó con el soporte de
> herramientas de inteligencia artificial generativa, en tres funciones. La primera es la búsqueda y
> verificación de información en documentación técnica y normativa, cuyas fuentes se citan en el
> Capítulo 11. La segunda es la asistencia en la implementación del código del agente, del backend y
> del frontend, de sus pruebas automatizadas y de los laboratorios de verificación. Los carriles de
> evidencia del cierre conservan, en el archivo CRITERIOS.md de cada carril, la correspondencia
> entre cada criterio canónico, su implementación y la prueba que lo verifica. Los autores
> contrastaron cada aporte contra esa evidencia. La tercera son las correcciones de redacción,
> consistencia y organización expositiva, incluida la revisión editorial de la versión anterior de
> este documento.
>
> Fueron decididas por los autores la identificación del problema de investigación, la formulación de
> la hipótesis y de los objetivos, y las decisiones de arquitectura y de diseño técnico. Lo fueron
> también la selección del stack tecnológico, la definición del protocolo experimental, la
> interpretación de los resultados, la determinación de qué se declara alcanzado y qué no, y la
> planificación del trabajo futuro. Cada aporte de las herramientas fue revisado por ellos,
> contrastado contra el código y la evidencia conservada, y aceptado o rechazado en consecuencia.
> Los autores asumen la responsabilidad plena y exclusiva por el contenido del presente documento,
> incluidos los errores que pudiera contener.

Comando de extracción usado (`python3`, sin dependencias; el DOCX usa el prefijo de namespace `ns0`,
no `w`, así que un recorte por `</w:p>` devuelve todo el documento en una sola línea):

```python
import zipfile, re, html
z = zipfile.ZipFile('tesis/cierre/Tesis_v13_cierre_tecnico.docx')
x = z.read('word/document.xml').decode('utf-8').replace('</ns0:p>', '\n')
t = html.unescape(re.sub(r'<[^>]+>', '', x))   # 1989 párrafos
```

### A9.5 — Lo que el informe debe tener en cuenta

- El texto vigente de la V13 declara tres funciones (búsqueda/verificación, implementación de código
  y pruebas, corrección de redacción incluida la revisión editorial de la versión anterior). **No
  menciona el ensamblado programático del documento**, que es uno de los cuatro planos que la
  auditoría V10 identificó y que `build/build_v10.py` y `build/step_editorial.py` documentan. Si la
  v18 quiere cerrar N-1 sin residuo, ese es el plano que falta nombrar.
- La evidencia que sostiene el plano «implementación y pruebas» (`lanes/*/CRITERIOS.md`) está fuera
  de git. §9.3 la invoca explícitamente («Los carriles de evidencia del cierre conservan, en el
  archivo CRITERIOS.md de cada carril…»), así que el paquete debe acompañar la entrega o la
  referencia queda sin respaldo verificable para el tribunal.
- `REGISTRO_REVISION_V11.md` — la fuente primaria de la frase «asistida por IA (Claude)» — **no se
  conservó**. Solo sobrevive citada dentro de `REGISTRO_CAMBIOS_TESIS_V12.md`.

---

## A10 — Encuadre normativo: NO CONSTA EN EL REPOSITORIO

**Dato: el repositorio no contiene ninguna referencia al plan de estudios (ni 2003 Ord. 987 ni 2024
Ord. 2018), ni al reglamento de Trabajo Final de la UTN FRM, ni a requisitos institucionales de
extensión, formato, estilo bibliográfico obligatorio, límite de resumen o video. Lo tienen que
aportar los autores.**

No se buscó en internet y no se supone nada.

Búsqueda en todo el repositorio, excluyendo binarios:

```
$ rg -n -i --no-heading -g '!*.zip' -g '!*.pdf' -g '!*.docx' \
    'Ordenanza|Ord\. ?987|Ord\. ?2018|plan de estudios|Reglamento de Trabajo Final|reglamento.*TFI|extensión máxima|estilo bibliográfico|límite de resumen|palabras clave.*máximo' .
./tesis/cierre/PROMPT_AUDITORIA_V16.md:40:ordenanza aplicable, citala con su número, y derivá de ahí los requisitos formales y de contenido que
```

La única coincidencia es el propio prompt de auditoría **pidiendo** el dato, no aportándolo.
Contexto literal, `tesis/cierre/PROMPT_AUDITORIA_V16.md:35-40`:

> **Reglamento institucional.** El marco que rige la aprobación de este trabajo es la normativa de la
> UTN, Facultad Regional Mendoza, sobre Trabajo Final de la Tecnicatura. Identificá la resolución u
> ordenanza aplicable, citala con su número, y derivá de ahí los requisitos formales y de contenido
> que correspondan. Si no podés acceder al texto, decilo y no supongas su contenido.

El mismo prompt ya anticipa que esta imposibilidad es en sí misma un hallazgo
(`tesis/cierre/PROMPT_AUDITORIA_V16.md:56-57`):

> Si alguno de estos tres marcos no se puede establecer con fuente, esa imposibilidad es en sí misma
> un hallazgo y va en el informe.

Búsqueda dentro del documento entregado (`Tesis_v13_cierre_tecnico.docx`): tampoco consta. Las dos
únicas coincidencias de «plan de estudios» son sustantivas, no normativas:

- Párrafo 194 (§1.4, relevancia): «Tercero, integra competencias del plan de estudios: Python, React
  y TypeScript, bases de datos, integración de sistemas y seguridad aplicada.»
- Párrafo 1496 (§8, conclusiones): «El enfrentamiento con un problema real de ciberseguridad demandó
  habilidades no explícitamente cubiertas por el plan de estudios, pero características de la
  práctica profesional.»

Ninguna de las dos cita una ordenanza, un número de plan ni un año.

Lo único **autodeclarado** sobre formato bibliográfico es APA 7, en la propia declaración de
originalidad:

> Las fuentes bibliográficas, estándares técnicos y publicaciones consultadas han sido citadas
> conforme al sistema de referenciación APA en su séptima edición.

Es una elección de los autores, no un requisito institucional acreditado: el repositorio no contiene
ningún documento de la facultad que imponga APA 7 ni que imponga otro estilo.

Lo que sí está sistematizado en el documento es el **marco normativo argentino de ciberseguridad y
datos personales** (Ley 25.326, Ley 26.388, Resoluciones AAIP 47/2018 y 126/2024, Resolución
44/2023, Decisión Administrativa 641/2021, DNU 941/2025, Disposición 1/2026 del CNC). Eso es otra
cosa: es el objeto de estudio del Capítulo 2 y del §9.4, no el encuadre reglamentario de la carrera.
No debe confundirse una cosa con la otra en el informe.

**Qué tienen que aportar los autores, para que el ítem quede cerrado:**

1. Número y año de la ordenanza del plan de estudios bajo el que cursan (2003 Ord. 987 o 2024 Ord.
   2018) y confirmación de cuál rige su cohorte.
2. El reglamento de Trabajo Final de la UTN FRM vigente (resolución u ordenanza, con número).
3. De ahí se derivan, y no antes: extensión, formato de página, estilo bibliográfico exigido, límite
   de palabras del resumen y si corresponde entregar un video.

---

## B1 — Tabla pareada del grupo de control

### B1.1 — La tabla que existe, y a qué corrida corresponde

**Existe una sola tabla pareada en el repositorio.** Es
`tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/tabla_pareada.csv`.

```
$ head -3 tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/tabla_pareada.csv
seq,patron,operacion,ruta_agente,fim,control
1,simple,create,/srv/fim-watch/critico/gen_00001.txt,1,0
2,simple,delete,/srv/fim-watch/critico/gen_00001.txt,1,0

$ wc -l tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/tabla_pareada.csv
501 tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/tabla_pareada.csv
```

Análisis de columnas y dominios (501 líneas = 1 encabezado + **500 filas de datos**):

```
$ python3 -c "
import csv
r=list(csv.DictReader(open('tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/tabla_pareada.csv')))
print('fields', list(r[0].keys())); print('rows', len(r))
for k in r[0]:
    v={row[k] for row in r}
    if len(v)<=8: print(k, sorted(v))
"
fields ['seq', 'patron', 'operacion', 'ruta_agente', 'fim', 'control']
rows 500
patron ['colapsado', 'efimero', 'revertido', 'simple']
operacion ['create', 'delete', 'modify']
fim ['0', '1']
control ['0', '1']
```

**Correspondencia con lo pedido:**

| Columna pedida | Columna real | Observación |
|---|---|---|
| `op_id` | `seq` | Entero 1…500. |
| `path` | `ruta_agente` | Ruta vista por el agente (`/srv/fim-watch/critico/...`). |
| `op_type` | `operacion` | `create`, `delete`, `modify`. |
| `pattern` | `patron` | Valores en **masculino**: `simple`, `colapsado`, `efimero`, `revertido` — no `colapsada`, `efimera`, `revertida`. Cuatro patrones, como se pide. |
| `fim_detected` | `fim` | `0`/`1`. |
| `cron_detected` | `control` | `0`/`1`. |

Es decir: la tabla tiene exactamente la información pedida, con nombres de columna distintos y el
género de los patrones invertido respecto del enunciado. No hace falta ninguna columna nueva.

**A qué corrida corresponde: NO es la batería histórica.** Corresponde a la corrida del 2026-09-18
sobre el candidato `v1.0-tesis`, dentro del paquete `oficial-cap5-20260917T223823Z`. Evidencia
directa del propio paquete:

```
$ head -c 200 tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/control_estado.json
{"scan_id": 4, "ts_scan_epoch": 1789700175.8448896, "ts_scan_utc": "2026-09-18T02:56:15.844890+00:00", "dir": "/srv/fim-watch", ...
```

Y la procedencia declarada en `.../control/MCNEMAR.md`:

> Script: `scripts/analisis_mcnemar.py` (no external dependencies).
>
> ```
> python3 scripts/analisis_mcnemar.py \
>   --manifiesto bateria3/bateria3_manifiesto.json \
>   --eventos    bateria3/eventos_backend.csv \
>   --control    control/bateria7_latencias.csv \
>   --salida     control/tabla_pareada.csv
> ```
>
> Each of the generator's 500 operations is one paired observation. Both arms observe exactly the
> same operations, on the same host, in the same window: Battery 3 and Battery 7 ran together, as
> `docs/plan_medicion_cap5.md:689-690` requires. Nothing is matched across runs.

Resultados de esa tabla, tal como los reporta `MCNEMAR.md`:

| | Control detectó | Control no detectó | Total |
|---|---|---|---|
| **FIM detectó** | 71 | 409 | 480 |
| **FIM no detectó** | 7 | 13 | 20 |
| **Total** | 78 | 422 | 500 |

Tasa FIM 0,9600 (480/500); tasa control 0,1560 (78/500); diferencia pareada 0,8040; intervalo de
Newcombe 95 % (método 10) [0,7618; 0,8377]; pares discordantes b = 409, c = 7.

Las rutas son `/srv/fim-watch/critico/...`, propias del laboratorio de septiembre. La batería
histórica usó `/watch/...` (ver B1.2). Eso confirma, por sí solo, que esta tabla no es la histórica.

### B1.2 — Tabla pareada de la batería histórica: NO EXISTE

**No existe ninguna tabla pareada de la batería histórica en el repositorio.**

```
$ fd -H -t f 'pareada|paired' .
./tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/tabla_pareada.csv

$ rg -l -n 'tabla_pareada' .
./tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/control/MCNEMAR.md
./tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/SHA256SUMS
```

Una sola tabla, la de septiembre. `scripts/analisis_mcnemar.py` nunca se corrió sobre los datos
históricos: no hay artefacto de salida.

Esto es coherente con lo que el propio `MCNEMAR.md` dice sobre por qué se construyó esa tabla:

> Section 3.6 of the thesis specifies this procedure, and the audits recorded that it had never been
> executed: the paired table was missing, so the comparison rested on two separate marginal counts,
> which support no inference about the paired difference.

**Los insumos históricos sí se conservaron** (aunque fuera de git, ver «Lo que no pude
determinar»). Están en `tesis/resultados/`, con fecha 2026-08-19:

```
$ head -2 tesis/resultados/bateria3_manifiesto.jsonl
{"seq": 1, "operacion": "create", "patron": "simple", "grupo": null, "ruta_host": ".../fim-watch/gen_00001.txt", "ruta_relativa": "gen_00001.txt", "ruta_agente": "/watch/gen_00001.txt", "ts_utc": "2026-08-19T15:28:23.896092+00:00", "ts_epoch": 1787153303.8960917, ..., "deteccion_control_esperada": "visible", "error": null}
$ wc -l tesis/resultados/bateria3_manifiesto.jsonl
500 tesis/resultados/bateria3_manifiesto.jsonl

$ head -1 tesis/resultados/bateria7_latencias.csv
scan_id,ruta_agente,operacion_control,operacion_manifiesto,patron_manifiesto,seq_manifiesto,ts_cambio_epoch,ts_cambio_utc,ts_deteccion_epoch,ts_deteccion_utc,latencia_ms
$ wc -l tesis/resultados/bateria7_latencias.csv
106 tesis/resultados/bateria7_latencias.csv

$ eza -l --time-style=long-iso tesis/resultados/bateria7_*.csv
.rw-rw-r-- 27k ezequiel 2026-08-19 12:59 tesis/resultados/bateria7_control.csv
.rw-rw-r-- 17k ezequiel 2026-08-19 13:46 tesis/resultados/bateria7_latencias.csv
```

Es decir: B3 (manifiesto de 500 operaciones, 2026-08-19 15:28 UTC) y B7 (grupo de control,
primer escaneo 2026-08-19 15:29 UTC) corrieron en la misma ventana y sobre las mismas operaciones,
igual que en septiembre. Los insumos para armar la tabla pareada histórica están.
**Pero la tabla no existe como artefacto, y este documento no la produce**: generarla sería una
corrida de análisis nueva, no un dato recolectado.

Marginales históricos conservados, `tesis/resultados/RESULTADOS.md:39-47`:

```
## Batería 7 — Grupo de control (44-50)
| ítem | dato | Plataforma FIM | Script cron |
|---|---|---|---|
| 44/45 | mediana | 12,18 ms | 553.054 ms (9,2 min) |
| 46/47 | P99 | 17,27 ms | 897.371 ms (15,0 min) |
| 48/49 | perdidos | 7 de 500 (1,4 %) | **395 de 500 (79,0 %)** |
| 50 | **factor de mejora** | | **45.422×** |

Desglose de la pérdida del cron: 293 por colapso de cambios sucesivos, 102 por no detección.
```

Son exactamente los «dos recuentos marginales separados» que `MCNEMAR.md` describe como
insuficientes para inferencia pareada. Si la v18 necesita la tabla pareada histórica, hay que
correr `scripts/analisis_mcnemar.py` sobre `tesis/resultados/bateria3_manifiesto.jsonl` y
`tesis/resultados/bateria7_latencias.csv`, y esa sería una corrida nueva que debe declararse como
tal.

---

## B2 — Datos de origen de la reagregación de latencia (Tabla 12a)

### B2.1 — El CSV de las 493 observaciones: EXISTE, pero NO trae la marca posterior a la operación

El archivo que contiene las 493 observaciones con `received_at` es
`tesis/resultados/bateria3_latencias.csv` (2026-08-19):

```
$ head -3 tesis/resultados/bateria3_latencias.csv
event_id,path,detected_at,received_at,latencia_ms
ab0df463-9aa2-4b5e-8643-4c32214319c0,/watch/gen_00001.txt,2026-08-19 15:28:23.896636,2026-08-19 15:28:23.909084,12.448000
2b30287d-15eb-4520-81c5-8d202b3f74ee,/watch/gen_00001.txt,2026-08-19 15:28:27.493912,2026-08-19 15:28:27.498879,4.967000

$ wc -l tesis/resultados/bateria3_latencias.csv
494 tesis/resultados/bateria3_latencias.csv
```

494 líneas = 1 encabezado + **493 filas**, que coinciden con el `n=493` de la Tabla 12a.

**Sus columnas son `event_id, path, detected_at, received_at, latencia_ms`. La marca posterior a la
operación NO está en este archivo.** La `latencia_ms` que trae es la del tramo histórico
`received_at − detected_at` (17,274 ms de P99, Tabla 12), no la de la reagregación.

La marca posterior a la operación vive en el otro archivo, `tesis/resultados/bateria3_manifiesto.jsonl`
(500 registros), en los campos `ts_utc` / `ts_epoch`, que el generador estampa **después** de
ejecutar la operación. `scripts/generador_carga.py:597-614`:

```python
        ahora = time.time()
        programado = inicio_epoch + idx * interval
        registro = {
            "seq": idx + 1,
            "operacion": op.op,
            "patron": op.pattern,
            ...
            "ts_utc": iso_utc(ahora),
            "ts_epoch": ahora,
            "ts_programado_epoch": programado,
            "desvio_ms": (ahora - programado) * 1000.0,
            ...
        }
```

Es decir: **el CSV único de 493 filas con la marca posterior a la operación y `received_at` en la
misma fila no existe.** Existen los dos insumos, en dos archivos distintos y con dos claves de
cruce distintas (`ruta_agente`/`seq` en el manifiesto, `path`/`event_id` en las latencias).

### B2.2 — El script de reagregación: NO SE CONSERVÓ

**No existe un script de reagregación en el repositorio.** Ninguno de los siete scripts de análisis
lee `bateria3_latencias.csv` para recalcular percentiles desde la marca del manifiesto:

```
$ rg -l -n 'bateria3_latencias|marca post' scripts/
scripts/analisis_control.py
scripts/analisis_mcnemar.py
scripts/README.md
```

`analisis_control.py` y `analisis_mcnemar.py` son de la batería de control (B7) y de la inferencia
pareada; ninguno produce la Tabla 12a. No hay ningún artefacto en el repositorio que contenga los
valores 11,316 / 12,639 / 16,798 / 17,745 calculados:

```
$ rg -n '17,745|17.745|11,316|11.316' scripts/
(sin salida)
```

La procedencia que los documentos de cierre le atribuyen a la Tabla 12a apunta al **generador**, no
a un script de reagregación. `tesis/cierre/RESULTADOS_VERIFICADOS.md:26`:

> | Latencia Tabla 1 | P99 <1.000 ms | El informe usó el tramo más corto `received_at-detected_at`:
> 17,274 ms | Reagregación `received_at-marca post-operación`: n=493, media 11,316, P50 12,639, P95
> 16,798, P99 **17,745 ms** | No es corrida nueva; la marca post-operación no prueba el instante
> físico exacto | CUMPLE | `scripts/generador_carga.py:579-619`, manifiesto y latencias B3 |

Las líneas 579-619 de `generador_carga.py` son el bloque que **escribe** la marca (transcrito
arriba). No calculan ningún percentil. La cita identifica el origen del dato, no el artefacto de
cálculo.

### B2.3 — Esto ya era un hallazgo abierto de las auditorías

No es un descubrimiento de esta recolección: tres auditorías consecutivas registraron la ausencia
del artefacto de cálculo.

- `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V6.md:127`: «Tabla 12a | Mantiene 17,745 ms, n=493, como
  reagregación de un intervalo distinto. **No contiene artefacto de cálculo.**»
- `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V7.md:113`: «12a | Reagregación n=493 y P99 17,745 ms, **sin
  artefacto de cálculo dentro del DOCX.**»
- `tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md:109`: «**No verificado por esta auditoría:** el
  cálculo de 17,745 ms.»

Y la propia nota de la Tabla 12a en el documento V13 lo declara como pendiente (párrafo 934 del
texto extraído):

> **La reagregación debe acompañarse de su script y datos de origen.**

El documento pide el script. El script no está.

### B2.4 — Resumen del ítem

| Pieza pedida | Estado | Ruta |
|---|---|---|
| CSV de 493 observaciones con `received_at` | **Existe** | `tesis/resultados/bateria3_latencias.csv` (columnas `event_id,path,detected_at,received_at,latencia_ms`) |
| Marca posterior a la operación | **Existe, en otro archivo** | `tesis/resultados/bateria3_manifiesto.jsonl`, campos `ts_utc` / `ts_epoch` (500 registros) |
| CSV único con marca post-operación **y** `received_at` en la misma fila | **No existe** | — |
| Script de reagregación que produzca 11,316 / 12,639 / 16,798 / 17,745 | **No se conservó** | — |

---

## B3 — Paquetes de evidencia de los candidatos `7a7ee50` y `7df4935`

### B3.0 — Nombre del archivo de custodia: `SHA256SUMS`, no `MANIFEST.sha256`

**Confirmado: este proyecto nunca usó `MANIFEST.sha256`.** El archivo de custodia se llama
`SHA256SUMS` en todos los paquetes, está en la raíz de cada uno y es directamente consumible por
`sha256sum -c`. Algunos paquetes traen además un `MANIFEST.json` (metadatos del ensayo, no hashes) y
un `verify-custody.sh`; el paquete de `7a7ee50` trae los tres. La verificación de integridad se hace
con `sha256sum -c SHA256SUMS` desde la raíz del paquete, porque las rutas del manifiesto son
relativas a esa raíz.

### B3.1 — Candidato `7a7ee50` (consolidado vigente)

**Ruta:** `tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/`

Identificación del candidato:

```
$ head tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/metadata/candidate-commit.txt
7a7ee5011d9234023687687ed95a7cdda9437711
```

**Versionado en git: SÍ, completo.** `.gitignore:71-72` ignora `final-consolidated-*` y luego exime
este paquete concreto (`!/tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/`).

```
$ git ls-files tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z | wc -l
133
$ fd -I -H -t f . tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z | wc -l
133
```

**133 archivos en disco, los 133 versionados.** Contenido de primer nivel:

```
$ ls tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z
POSTRUN_NOTE.md  SHA256SUMS  coverage  custody  e2e  junit  logs  metadata  results.json  verify-custody.sh
```

**Integridad: VERIFICA.**

```
$ cd tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z && sha256sum -c SHA256SUMS
...
./metadata/tool-versions.txt: OK
./metadata/valkey-container-id.txt: OK
./POSTRUN_NOTE.md: OK
./results.json: OK
./verify-custody.sh: OK
EXIT=0
```

**130 entradas, 130 OK, 0 FAILED.** (Las tres entradas que el manifiesto no cubre son el propio
`SHA256SUMS` y dos `SHA256SUMS` anidados de los subpaquetes E2E, que tienen su propia verificación:
`e2e/e2e-us02-us20-us31/SHA256SUMS` y `e2e/e2e-us03-us16-us17-us25/SHA256SUMS`.)

### B3.2 — Candidato `7df4935`: son DOS paquetes, con estado de versionado distinto

Este es el punto que conviene no simplificar. El candidato `7df4935` tiene un paquete de ensayos
posteriores y un paquete de suite consolidada, y **solo el primero está versionado**.

**(a) Ensayos de cierre — `tesis/cierre/evidencia/experiments-closure-20260912T004612Z/`**

```
$ head tesis/cierre/evidencia/experiments-closure-20260912T004612Z/metadata/candidate-commit.txt
7df4935f769a2e393a5e6a6330df605c77592e52
```

Cubre concurrencia de notificaciones, repetición del drenaje Run 4 y latencia con `strace` — los
tres ensayos que el documento atribuye a `7df4935` (§§5.2.1, 5.3.1, 5.6.1).

**Versionado en git: SÍ, completo** (`.gitignore:69-70`, misma mecánica de excepción).

```
$ git ls-files tesis/cierre/evidencia/experiments-closure-20260912T004612Z | wc -l
157
$ fd -I -H -t f . tesis/cierre/evidencia/experiments-closure-20260912T004612Z | wc -l
157
```

**157 archivos, los 157 versionados. Integridad: VERIFICA.**

```
$ cd tesis/cierre/evidencia/experiments-closure-20260912T004612Z && sha256sum -c SHA256SUMS
...
scripts/latency_generator.py: OK
scripts/run_drain_once.sh: OK
scripts/run_latency_lab.sh: OK
scripts/sanitize_logs.py: OK
scripts/verify_experiments.py: OK
EXIT=0
```

**155 entradas, 155 OK, 0 FAILED.** Este paquete trae además `MANIFEST.json` (metadatos del ensayo)
y `RESULTS.json`.

**(b) Suite consolidada — `tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z/`**

```
$ head -1 tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z/metadata/temporary-commit.txt
commit 7df4935f769a2e393a5e6a6330df605c77592e52
```

**Versionado en git: NO.** Cae bajo `.gitignore:71` (`/tesis/cierre/evidencia/final-consolidated-*/`)
y no tiene excepción; la única exención es la del paquete de `7a7ee50`.

```
$ git ls-files tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z | wc -l
0
$ fd -I -H -t f . tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z | wc -l
296
```

**296 archivos en disco, 0 versionados. Integridad: VERIFICA** (sobre la copia local).

```
$ cd tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z && sha256sum -c SHA256SUMS
292 OK, 0 FAILED
```

Este es el paquete que sostiene las cifras de suite de `7df4935` que el documento cita (agente
507 aprobadas / 1 omitida con 78,93 % de líneas; backend 599/599 con 90,69 %; frontend 128/128 con
57,97 %). Si la entrega se arma desde el repositorio, **no viaja**.

### B3.3 — Resumen del ítem

| Candidato | Paquete | Archivos | Versionado en git | Custodia | `sha256sum -c` |
|---|---|---|---|---|---|
| `7a7ee50` | `tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/` | 133 | **Sí, 133/133** | `SHA256SUMS` (130 entradas) + `verify-custody.sh` | **130 OK, 0 FAILED** |
| `7df4935` | `tesis/cierre/evidencia/experiments-closure-20260912T004612Z/` | 157 | **Sí, 157/157** | `SHA256SUMS` (155 entradas) + `MANIFEST.json` | **155 OK, 0 FAILED** |
| `7df4935` | `tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z/` | 296 | **No, 0/296** | `SHA256SUMS` (292 entradas) | **292 OK, 0 FAILED** |

Para contexto, otros paquetes con candidato identificado que aparecieron en el barrido:

```
$ for d in tesis/cierre/evidencia/*/; do f=$(fd -I -H -t f 'candidate-commit.txt|temporary-commit.txt' "$d" -d 3 | head -1);
    [ -n "$f" ] && echo "$d -> $(head -c 45 "$f")"; done

tesis/cierre/evidencia/experiments-closure-20260912T004612Z/  -> 7df4935f769a2e393a5e6a6330df605c77592e52
tesis/cierre/evidencia/final-consolidated-20260911T214511Z/   -> commit 6e81ccf95f8da644b74b41a499d3414a08
tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z/ -> commit 7df4935f769a2e393a5e6a6330df605
tesis/cierre/evidencia/final-consolidated-v10-20260912T205729Z-attempt1-failed/ -> d35fb9c98072eb7249534c23f337ae7e0738a500
tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/ -> 7a7ee5011d9234023687687ed95a7cdda9437711
```

El paquete `...-attempt1-failed` (candidato `d35fb9c`) es el primer intento fallido del E2E de US-25
que el documento menciona en §4.9; tampoco está versionado.

---

## Lo que no pude determinar y por qué

1. **El encuadre normativo institucional (A10) en su totalidad.** No consta en el repositorio: no
   hay número de ordenanza del plan de estudios, no hay reglamento de Trabajo Final de la UTN FRM, y
   por lo tanto no hay requisitos derivados de extensión, formato, estilo bibliográfico obligatorio,
   límite de resumen ni video. No busqué en internet y no supuse contenido, por instrucción
   explícita. **Lo tienen que aportar los autores.**

2. **La causa por la que `DATOS_PARA_TESIS_V15.md` cita `agent/detector.py:610`.** Pude determinar
   que esa línea es correcta en la rama actual y que en `7a7ee50` la línea equivalente es la 588,
   pero no pude determinar si el documento fue redactado contra la rama actual por error o si hubo
   una decisión deliberada de citar el estado vigente. El documento no lo dice.

3. **El artefacto de cálculo de la Tabla 12a (B2).** No se conservó. Pude identificar los dos
   insumos y el bloque del generador que estampa la marca, pero no existe el script que produjo
   11,316 / 12,639 / 16,798 / 17,745 ms, y por lo tanto no pude verificar esos valores. Tres
   auditorías (V6, V7, V10) ya habían registrado esa misma ausencia.

4. **`REGISTRO_REVISION_V11.md` (A9).** El archivo que contiene la frase primaria «Revisión
   editorial: asistida por IA (Claude)» no se conservó: ni el archivo ni el directorio
   `versiones/v11/` existen en el repositorio. La frase sobrevive únicamente citada dentro de
   `REGISTRO_CAMBIOS_TESIS_V12.md:529-531`. No pude verificar su texto original.

5. **Qué versiones de tesis existen entre V13 y V18.** El `.docx` más reciente es
   `Tesis_v13_cierre_tecnico.docx` (2026-09-19). No hay `.docx` de V14, V15, V16 ni V17 en el
   repositorio, y tampoco `REGISTRO_CAMBIOS_TESIS_V14..V17.md` (solo existen V5, V12 y V13). No pude
   determinar si esas versiones existen fuera del repositorio o si la numeración salta.

6. **La tabla pareada de la batería histórica (B1).** No existe. Los insumos para construirla sí se
   conservaron (`tesis/resultados/bateria3_manifiesto.jsonl` y `tesis/resultados/bateria7_latencias.csv`,
   ambos del 2026-08-19, misma ventana), pero construirla sería ejecutar un análisis nuevo, cosa que
   excede una tarea de recolección y que además habría que declarar como corrida nueva en el informe.

7. **Disponibilidad real de tres cuerpos de evidencia si la entrega se arma desde git.** Pude
   determinar que están fuera de git, pero no qué medio de entrega piensa usar el equipo. Los tres:
   - `tesis/resultados/` completo (insumos históricos B3/B4/B5/B7/B8, incluidos los de B2 y los de la
     tabla pareada histórica) — `.gitignore:47`.
   - `tesis/cierre/evidencia/v10-closure-20260912T190052Z/` salvo `a3-multihost/`: 356 de 422
     archivos, incluidos los `lanes/*/CRITERIOS.md` y `build/` que §9.3 invoca — `.gitignore:76-77`.
   - `tesis/cierre/evidencia/final-consolidated-fixed-20260911T225314Z/` completo (296 archivos, la
     suite consolidada de `7df4935`) — `.gitignore:71`.
   - Además, todos los `.docx`, los `AUDITORIA_INTEGRAL_TESIS_V*` y los `REGISTRO_CAMBIOS_TESIS_V*`
     — `.gitignore:59-62`.
