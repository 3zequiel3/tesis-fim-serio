# Entrega de valores — Capítulo 5 (55 ítems)

Documento de handoff para el equipo de desarrollo. Un renglón por ítem de la lista solicitada.
Auditoría realizada el **2026-08-18** sobre HEAD `b8b2511e31bb360e4383e8f2a69ba0b814c993ec`.

Fuente de los valores existentes: [`docs/valores_planillas_cap5.md`](valores_planillas_cap5.md)
(corrida local del 2026-07-02, commits `f1e8681` + `746ac5e`).

## Leyenda de estados

| Estado | Significado |
|---|---|
| ✅ **LISTO** | Valor asentable tal cual, sin reservas |
| ⚠️ **PROVISORIO** | Hay número real medido, pero la corrida no cumple los parámetros del protocolo §3.7 |
| 🔧 **SIN CORRIDA** | El arnés existe y funciona, falta ejecutarlo contra el laboratorio |
| ❌ **FALTA** | No existe el dato, ni la herramienta para producirlo |

## Resumen

| Estado | Ítems | Cantidad |
|---|---|---|
| ✅ LISTO | 23, 40, 42, 51, 53 | **5** |
| ⚠️ PROVISORIO | 1–10, 36–39, 41, 44, 46, 48, 52 | **19** |
| 🔧 SIN CORRIDA | 24–35 | **12** |
| ❌ FALTA | 11–22, 43, 45, 47, 49, 50, 54, 55 | **19** |
| | **Total** | **55** |

---

## Tabla 11 — Latencia de detección (Batería 3, §5.2)

Definición instrumentada: `received_at − detected_at`.
`agent/detector.py:371` estampa `detected_at` · `backend/app/modules/events/consumer.py:158` estampa `received_at`.

| # | Dato | Valor | Estado |
|---|---|---|---|
| 1 | Media aritmética | **13,15 ms** | ⚠️ PROVISORIO |
| 2 | Mediana | **13,92 ms** | ⚠️ PROVISORIO |
| 3 | Desvío estándar | **3,93 ms** | ⚠️ PROVISORIO |
| 4 | Mínimo | **3,28 ms** | ⚠️ PROVISORIO |
| 5 | Máximo | **43,43 ms** | ⚠️ PROVISORIO |
| 6 | Percentil 95 | **17,54 ms** | ⚠️ PROVISORIO |
| 7 | **Percentil 99** (indicador principal) | **19,60 ms** — umbral 1.000 ms, margen ~51× | ⚠️ PROVISORIO |
| 8 | Eventos medidos (n) | **500** (20 % creación · 70 % modificación · 10 % borrado) | ⚠️ PROVISORIO |
| 9 | Eventos perdidos (n) | **0** (500/500 entregados, 0 `rate_limited`) | ⚠️ PROVISORIO |
| 10 | Rechazos por `clock_skew` (n) | **0** | ⚠️ PROVISORIO |

**Por qué son provisorios — tres reservas que hay que cerrar:**

1. **Duración**: la muestra n=500 se generó en ~8 min paceada bajo el rate limit. El protocolo §3.7 pide **30 min sostenidos**. La distribución no debería cambiar, pero el valor no es el que el protocolo declara.
2. **Topología**: agente en contenedor Docker sobre el mismo host, comunicación por Valkey local. Un despliegue con **agente remoto sobre red** agregaría latencia de red no capturada.
3. **Método**: el Cap. 5 declara que los percentiles se calculan **con pandas**. Se calcularon con `percentile_cont` de PostgreSQL. Hay que corregir la redacción del capítulo o rehacer la agregación con pandas.

Ítem 9 y 10 dependen además de `stream-ack-durability` (0/109 tasks) — ver Bloqueantes.

---

## Tabla 12 — Tiempo de notificación (Batería 4, §5.3)

Intervalo: recepción del evento por backend → emisión exitosa del webhook. **No** incluye entrega en n8n/canal final. Solo camino feliz / primer intento.

| # | Dato | Valor | Estado |
|---|---|---|---|
| 11 | Media — secuencial | *(estimado ~40–90 ms)* | ❌ FALTA |
| 12 | Media — 50 concurrentes | *(estimado ~100–300 ms)* | ❌ FALTA |
| 13 | Media — 100 concurrentes | *(estimado ~200–500 ms)* | ❌ FALTA |
| 14 | P50 — secuencial | — | ❌ FALTA |
| 15 | P50 — 50 concurrentes | — | ❌ FALTA |
| 16 | P50 — 100 concurrentes | — | ❌ FALTA |
| 17 | P95 — secuencial | — | ❌ FALTA |
| 18 | P95 — 50 concurrentes | — | ❌ FALTA |
| 19 | P95 — 100 concurrentes | — | ❌ FALTA |
| 20 | P99 — secuencial (umbral < 5.000 ms) | *(estimado ~200–800 ms)* | ❌ FALTA |
| 21 | P99 — 50 concurrentes (umbral < 5.000 ms) | *(estimado ~500–2.000 ms)* | ❌ FALTA |
| 22 | P99 — 100 concurrentes (umbral < 5.000 ms) | *(estimado ~1.000–3.000 ms)* | ❌ FALTA |

**Tabla más vacía de las seis: 12 de 12 celdas sin medir.** Los valores en cursiva son proyecciones del análisis de código, **no medidas** — no asentar.

Instrumentación que SÍ existe para producirlos:
- `backend/app/modules/alerts/models.py:28` — `Alert.delivered_at`
- `backend/app/modules/alerts/service.py:91,154` — logs `notify.alert_created` / `notify.delivered`
- `n8n/workflows/{slack,email,ticketing}_alert.json`

Falta: generador de concurrencia (50 y 100 simultáneos) y agregador de percentiles.

**Precondición**: solo eventos `critical`/`high` generan `Alert` (RN-52, `alerts/service.py:96`). Sin reglas high/critical preconfiguradas, esta batería mide **cero**.

---

## Tabla 13 — Cobertura de automatización del triage (Batería 6, §5.4)

| # | Dato | Valor | Estado |
|---|---|---|---|
| 23 | Clasificación de las 13 tareas NIST SP 800-61r2 | **11 / 13 = 84,6 %** — umbral ≥ 80 % → **CUMPLE** | ✅ LISTO |

Único ítem cerrado al 100 %. No depende de infraestructura.

| N | Tarea NIST | ¿Automatizada? | Evidencia |
|---|---|---|---|
| 1 | Recepción del evento con metadatos | ✅ Sí | `consumer.py:157-277`; pid/uid/exe en `detector.py:366-373` |
| 2 | Cálculo del hash actualizado | ✅ Sí | `detector.py:122-146` |
| 3 | Comparación contra baseline vigente | ✅ Sí | `detector.py:433-434,595` |
| 4 | Identificación del tipo de cambio | ✅ Sí | `detector.py:411-427` |
| 5 | Consulta de reglas aplicables | ✅ Sí | `agent/rules.py:62-74` |
| 6 | Asignación de severidad | ✅ Sí | `alerts/service.py:60-77` |
| 7 | Selección de acción automática | ✅ Sí | `rules.py:62-74` (4 niveles, default `alert_only`) |
| 8 | Ejecución de la acción automática | ✅ Sí | `agent/decision.py:52-93,158-201` |
| 9 | Registro y auditoría | ✅ Sí | ingesta + `RejectedEventAudit` |
| 10 | Actualización de eventos previos (`superseded`) | ✅ Sí | cadena `parent_event_id`, verificada en e2e |
| 11 | Notificación según severidad | ✅ Sí | `alerts/service.py:82-123` + cascada de fallbacks |
| 12 | Discriminación autorizado vs. sospechoso | ❌ Humano | flujo approve/reject — **por diseño** |
| 13 | Decisión de escalamiento | ❌ Humano | **por diseño** |

Las dos tareas no automatizadas lo son **por decisión de diseño**, no por limitación. Es un argumento de defensa, no una carencia.

---

## Tabla 16-bis — Resultado de la batería automatizada (§5.5)

Fuente exigida: salida directa de `pytest` **contra el laboratorio**, no contra el entorno de desarrollo.

| # | Dato | Valor | Estado |
|---|---|---|---|
| 24 | Agente — casos ejecutados | *(dev: 389 nodeids)* | 🔧 SIN CORRIDA |
| 25 | Agente — aprobados | *(dev: 389, `lastfailed` vacío)* | 🔧 SIN CORRIDA |
| 26 | Agente — omitidos | — | 🔧 SIN CORRIDA |
| 27 | Agente — fallidos | *(dev: 0)* | 🔧 SIN CORRIDA |
| 28 | Backend — casos ejecutados | *(dev: 396 nodeids)* | 🔧 SIN CORRIDA |
| 29 | Backend — aprobados | — | 🔧 SIN CORRIDA |
| 30 | Backend — omitidos | — | 🔧 SIN CORRIDA |
| 31 | Backend — fallidos | *(dev: **6 en rojo**)* | 🔧 SIN CORRIDA |
| 32 | Total — casos ejecutados | *(nominal 785)* | 🔧 SIN CORRIDA |
| 33 | Total — aprobados | — | 🔧 SIN CORRIDA |
| 34 | Total — omitidos | — | 🔧 SIN CORRIDA |
| 35 | Total — fallidos | — | 🔧 SIN CORRIDA |

Los números en cursiva salen de `.pytest_cache/v/cache/nodeids` — **no son salida de pytest** y son de entorno dev. No asentar.

**Dos problemas antes de poder llenar esta tabla:**

1. **6 tests de backend en rojo** (`backend/.pytest_cache/v/cache/lastfailed`), entre ellos `test_notifications.py::test_notify_event_retry_3x_then_log_only` — que es exactamente el dominio de la Batería 4.
2. **No existe mapeo test ↔ historia de usuario.** Hay 31 historias (`docs/historias_de_usuario.md`, US-01…US-31) y 785 tests, y **ningún test cita una US** — están indexados por change (C22/C31/C32) y por RN. La afirmación **"31 de 31 historias"** no es derivable automáticamente: requiere una matriz de trazabilidad manual.

Suites: `agent/tests/` (35 archivos) · `backend/tests/` + `backend/pyproject.toml` (`[tool.pytest.ini_options]`, timeout 60).

---

## Tabla 14 — Resiliencia offline (Batería 5, §5.6)

| # | Dato | Objetivo | Medido (corrida reducida 2026-07-02) | Estado |
|---|---|---|---|---|
| 36 | Duración real de la desconexión | 300 s | **~24 s** | ⚠️ PROVISORIO |
| 37 | Eventos generados durante la desconexión | 3.000 | **30** | ⚠️ PROVISORIO |
| 38 | Eventos preservados en cola local | = 37 | **30 / 30** (`ls queue/ \| wc -l`) | ⚠️ PROVISORIO |
| 39 | Eventos entregados tras reconexión | = 38 | **30 (100 %)** — cola drenada a 0 | ⚠️ PROVISORIO |
| 40 | Orden FIFO preservado | Sí | **Sí** — `off_01 → off_30` por `detected_at` | ✅ LISTO |
| 41 | Duplicaciones detectadas | 0 | **0** — 30 filas, 30 `event_id` distintos | ⚠️ PROVISORIO |
| 42 | Comandos procesados antes que eventos encolados | Sí | **Sí** | ✅ LISTO |
| 43 | Tiempo de recuperación total | **< 30 s** | ~30–40 s de drenaje en la reducida | ❌ **BLOQUEADO** |

**Ítems 40 y 42 son ✅ porque son determinísticos**: 42 está forzado por código (`agent/publisher.py:75-79`, RN-109) y 40 es una propiedad estructural de la cola, no un valor que dependa de la escala.

**Ítem 43 no está "faltando" — está bloqueado.** Con el rate limit actual (100 ev/60 s), drenar 3.000 eventos tarda **~30 minutos**. El criterio "< 30 s" tal como está redactado **no se puede cumplir ni refutar**. Requiere una de estas tres decisiones, asentada en el appendix:

- **(a)** Parametrizar el rate limit para el experimento *(requiere código de backend)*.
- **(b)** Redefinir el indicador como *"agente operativo con drenaje iniciado"*.
- **(c)** Bajar el generador a < 1,6 ev/s.

---

## Tabla 15 — Comparación experimental vs. control (§5.7)

| # | Dato | Valor | Estado |
|---|---|---|---|
| 44 | Mediana de latencia — Plataforma FIM | **13,92 ms** (derivado del ítem 2) | ⚠️ PROVISORIO |
| 45 | Mediana de latencia — Script cron | *450.000 ms* — **cálculo teórico**: E[Uniform(0, 900 s)] | ❌ FALTA |
| 46 | Latencia P99 — Plataforma FIM | **19,60 ms** (derivado del ítem 7) | ⚠️ PROVISORIO |
| 47 | Latencia P99 — Script cron | *891.000 ms* — **cálculo teórico**: 0,99 × 900 s | ❌ FALTA |
| 48 | Eventos perdidos — Plataforma FIM | **0** (derivado del ítem 9) | ⚠️ PROVISORIO |
| 49 | Eventos perdidos — Script cron | *"> 0 esperable"* — sin número | ❌ FALTA |
| 50 | Factor de mejora (calculado) | *"~10³–10⁴"* — orden de magnitud, no un factor | ❌ FALTA |

> **Debilidad de defensa directa.** Los ítems 45, 47 y 49 no son mediciones: son la matemática de un script cron que **nunca se escribió**. `rg 'cron|grupo de control'` sobre el repo da cero implementación. Tal como está, la Tabla 15 contrapone mediciones reales contra un modelo analítico, y la presenta como *comparación experimental*.
>
> Dos salidas honestas: **(1)** escribir el script de control y medirlo de verdad, o **(2)** declarar explícitamente en el Cap. 5 que la columna de control es una **cota analítica**, no empírica, y renombrar la tabla en consecuencia.

Filas cualitativas de la misma tabla, ya cerradas: baseline separada y cifrada (Sí/No), notificación con fallbacks (Sí/No), trazabilidad de auditoría (Sí/No).

---

## Metadatos de reproducibilidad (Anexo F)

| # | Dato | Valor | Estado |
|---|---|---|---|
| 51 | Hash/tag del commit de la corrida | HEAD = `b8b2511e31bb360e4383e8f2a69ba0b814c993ec` (2026-08-18T18:33-03:00) | ✅ LISTO ⚠️ |
| 52 | Fecha y hora UTC de cada batería | Solo la fecha `2026-07-02` — **sin hora, sin UTC explícito** | ⚠️ PROVISORIO |
| 53 | Versiones efectivas desplegadas | **Coinciden con lo declarado** — ver tabla abajo | ✅ LISTO |
| 54 | Semilla / parámetros del generador de carga | — **no existe generador versionado** | ❌ FALTA |
| 55 | Archivos crudos: `.pcap` + trazas `strace` | — cero coincidencias de `tcpdump\|strace\|pcap` en el repo | ❌ FALTA |

**Ítem 51 — tres reservas antes de citarlo:**
- No hay **ningún tag** en el repo (`git tag` vacío).
- El **commit medido ≠ HEAD**: los valores de Tablas 11 y 14 se midieron sobre `f1e8681` + `746ac5e`.
- El árbol **no está limpio**: `docs/valores_planillas_cap5.md` y `docs/defensa_guion_10min.md` están untracked.

→ Antes de la corrida oficial: commitear pendientes y crear un tag (`v1.0-tesis`).

**Ítem 53 — verificado y coincidente:**

| Componente | Declarado (§3.7 / Anexo D) | Desplegado | ¿Coincide? |
|---|---|---|---|
| PostgreSQL | 18.3 — `docs/arquitectura_stack.md:41,1688` | `postgres:18.3` — `docker-compose.yml:35` | ✅ |
| Valkey | 9.0.3 — `docs/arquitectura_stack.md:43,1689` | `valkey/valkey:9.0.3` — `docker-compose.yml:65` | ✅ |
| n8n | 2.16.1 — `docs/arquitectura_stack.md:44,1690` | `n8nio/n8n:2.16.1` — `docker-compose.yml:85` | ✅ |

*Inconsistencia menor a limpiar*: `docs/arquitectura_stack.md:1513,1536` muestra un compose de ejemplo con `postgres:18` / `valkey:9.0` sin patch version.

**Ítem 54** — los archivos `fim-watch/c_51..c_100`, `m_16..m_35`, `off_01..off_30` son residuo de una generación **manual/ad-hoc**, y `fim-watch/*` está gitignoreado (`.gitignore:44-45`). Sin generador versionado con seed, este ítem es **irreproducible por definición**.

**Ítem 55 — no falta solo la herramienta, el diseño lo dificulta.** Todo el canal agente→backend va por **Valkey Streams sobre mTLS**. Un `.pcap` crudo sin material de claves **no verifica nada**. Requiere capturar en el loopback del contenedor Valkey (pre-TLS) o instrumentar con `SSLKEYLOGFILE`.

---

## Bloqueantes, ordenados por severidad

### 🔴 1. Rate limit de ingesta hardcodeado
`backend/app/modules/events/consumer.py:90` instancia `_RateLimiter()` con los defaults del constructor (`limit=100, window_s=60.0`, línea 69) — **no lee de `Settings`**. `backend/app/core/config.py:50-53` solo parametriza el rate limit de login/API HTTP, no el de ingesta por agente.

**Impacto**: ítem 43 infalsable · ítems 20–22 auto-limitados (los 100 concurrentes se estrangulan solos).
**Bloquea**: ítems 11–22, 36–39, 41, 43.

### 🔴 2. No existe generador de carga versionado
Nada en el repo genera N modificaciones con tasa y semilla controladas.
**Bloquea**: ítem 54 por definición, y la repetibilidad de **todas** las baterías (1–9, 11–22, 36–39, 44–50).

### 🔴 3. No existe el grupo de control
**Bloquea**: ítems 45, 47, 49, 50. Ver la advertencia de la Tabla 15.

### 🟠 4. `stream-ack-durability` — 0 de 109 tasks
Es el mecanismo de **ACK del stream**, del que dependen directamente los ítems 9, 38, 39, 40 y 41.

> **Medir la batería oficial antes de cerrar esta change es trabajo tirado a la basura.**

Otras changes abiertas: `agent-deployment-caps` (79/88), `backend-residual-fixes` (41/44), `event-status-contract` (31/33), `agent-scope-filter-symlink-hardening` (34/35).

### 🟠 5. Seis tests de backend en rojo
No se puede afirmar "31/31" con la suite en rojo, y las fallas incluyen `test_notifications.py` — dominio de la Batería 4.

### 🟠 6. Sin trazabilidad test ↔ historia de usuario
La afirmación "31 de 31 historias" requiere una matriz manual. No hay forma automática de derivarla hoy.

### 🟡 7. Requisito "pandas" incumplido
Los valores existentes salen de `percentile_cont` de PostgreSQL. Cosmético metodológicamente, pero el Cap. 5 lo declara y es verificable por el jurado.

### 🟡 8. `notify_if_applicable` abre sesiones DB síncronas dentro del event loop
`backend/app/modules/alerts/service.py:92-172`. Riesgo de cola pesada que **distorsionaría el escenario de 100 concurrentes** (ítems 13, 16, 19, 22).

### 🔵 9. Contradicción narrativa en la documentación
- `docs/defensa_guion_10min.md:118-122` dice *"implementación en curso"*, *"no desplegado end-to-end"*, *"fanotify no probado contra host real, está mockeado"*.
- La realidad del repo: e2e real, 500/500 eventos, fanotify FID funcionando en contenedor con capabilities.
- §1.7 y §5.1 de la tesis dicen *"implementación pendiente"*.

**El guion de defensa está ~6 semanas desactualizado respecto del repo.** Hay que actualizarlo o presentar el estado real como adenda (Anexo F).

---

## Qué se puede entregar hoy mismo, sin infraestructura

| Ítem | Acción |
|---|---|
| **23** | Copiar la tabla NIST completa. 11/13 = 84,6 % → CUMPLE, con evidencia `archivo:línea` por tarea |
| **40, 42** | Asentar "Sí". Determinísticos por código, no requieren corrida |
| **51** | `b8b2511e...` — recomendado: commitear untracked + crear tag `v1.0-tesis` **antes** de la corrida oficial |
| **53** | Tabla declarado-vs-desplegado, ya verificada como coincidente |
| **1–10** | Asentar con la etiqueta honesta: *"corrida local reducida 2026-07-02, n=500, agente co-residente"* |
| **36–39, 41** | Asentar como **corrida reducida**: 24 s / 30 eventos / 30 preservados / 30 entregados / 0 duplicados |
| **44, 46, 48** | Derivar de la Tabla 11 sin trabajo nuevo: 13,92 ms / 19,60 ms / 0 |
| **45, 47** | Defendibles **solo** si el Cap. 5 los declara explícitamente como cota analítica, no como medición |

## Qué requiere construir antes de medir

| Pieza | Desbloquea |
|---|---|
| Parametrizar el rate limit de ingesta vía `Settings` | 11–22, 43 |
| Generador de carga con semilla y tasa configurables | 54 + repetibilidad de todo |
| Script de la batería de notificación (secuencial / 50c / 100c) | 11–22 |
| Script del grupo de control (cron de hashing periódico) | 45, 47, 49, 50 |
| Agregador de percentiles con pandas | 1–7, 11–22 (y cierra el bloqueante 7) |
| Captura `tcpdump` en loopback pre-TLS + `strace` | 55 |
| Matriz de trazabilidad test ↔ US-01…US-31 | 32–35 |
| Cerrar `stream-ack-durability` | 9, 38–41 |
