# Plan de medición — Capítulo 5

**Alcance: los 55 ítems se miden desde cero en una corrida oficial.** Los valores existentes en
[`docs/valores_planillas_cap5.md`](valores_planillas_cap5.md) quedan como referencia de orden de
magnitud y validación del mecanismo, **no** como resultado oficial: fallan en duración (8 min vs.
30), topología (agente co-residente) y método de agregación (SQL en vez de pandas).

Documento de handoff para el equipo de desarrollo. Un renglón por ítem, con el método exacto.

Estado de auditoría de lo que ya existe: [`docs/entrega_valores_cap5.md`](entrega_valores_cap5.md).

---

## 0. Precondiciones — bloquean la corrida oficial

Ninguna batería debe ejecutarse hasta cerrar estos siete puntos.

| # | Precondición | Por qué bloquea | Dónde |
|---|---|---|---|
| P1 | ~~**Parametrizar el rate limit de ingesta vía `Settings`**~~ — **hecha** | Estaba hardcodeado en `_RateLimiter()` con `limit=100, window_s=60.0`; estrangulaba la Batería 4 y hacía infalsable el ítem 43. Ahora sale de `RATE_LIMIT_INGEST_EVENTS` / `RATE_LIMIT_INGEST_WINDOW_SECONDS` (defaults 100 / 60.0 = comportamiento previo) | `backend/app/core/config.py` · `backend/app/modules/events/consumer.py` · `docker-compose.yml` · `.env.example` |
| P2 | ~~**Escribir el generador de carga con `--seed` y `--rate`**~~ — **hecha** | Sin él el ítem 54 era irreproducible y ninguna batería repetible. `--seed`, `--rate`, `--count`, `--mix` y `--dir` son obligatorios; loguea su configuración completa al arrancar y emite el manifiesto con el timestamp real de cada cambio. Incluye a propósito los tres patrones ciegos para el escáner periódico (revertido, colapsado, efímero) que el ítem 49 necesita para medir algo real | `scripts/generador_carga.py` · `scripts/README.md` |
| P3 | ~~**Escribir el script del grupo de control (cron 15 min)**~~ — **hecha** | Ítems 45, 47, 49, 50 ya tienen fuente empírica: escáner por hashing SHA-256 cada 900 s, corrible por cron (`--print-cron`), por `--loop` o bajo demanda. El cruce contra el manifiesto lo hace `analisis_control.py` y produce 45, 47, 49 y 50 | `scripts/control_hashing.py` · `scripts/analisis_control.py` |
| P4 | **Cerrar `stream-ack-durability` (0/109 tasks)** | Es el ACK del stream: si cambia después de medir, invalida 9, 38, 39, 40, 41 | `openspec/changes/stream-ack-durability/` |
| P5 | ~~**Arreglar los tests de backend en rojo**~~ — **hecha** | Contra base de datos limpia eran **5** (no 6: `lastfailed` arrastraba uno viejo). Ninguno era un defecto de producción: 4 tests con expectativas obsoletas y 1 test con FK faltante. Ver "Nota P5" abajo — el rojo de `test_notifications.py` NO era la fachada de n8n, pero la fachada sigue en pie | `backend/tests/{test_auth,test_c31_backend_event_correctness,test_notifications}.py` |
| P6 | ~~**Configurar reglas de severidad `high`/`critical`**~~ — **hecha** | Solo esos niveles generan `Alert` (RN-52). El sembrado es reproducible e idempotente vía la API REST (mismo camino que la UI, dispara `rule_sync`): `/watch/*` → `high` y `/watch/critico/*` → `critical`, ambas con acción `alert_only` para no inyectar cambios ajenos al manifiesto | `scripts/seed-reglas-lab.sh` · `backend/app/modules/alerts/service.py:96` |
| P7 | **Definir formalmente "tiempo de recuperación" (ítem 43)** | Con 3.000 eventos y rate limit vigente el drenaje tarda ~30 min. El umbral < 30 s no se puede cumplir ni refutar tal como está redactado | appendix de decisiones |

**Además, antes de arrancar:** commitear los archivos untracked y crear el tag de la corrida
(ítem 51 exige un árbol limpio y un identificador estable).

### Nota P5 — qué eran los 5 rojos

Medido siempre contra **base de datos nueva** (la suite no es hermética: `create_all` deja columnas
de una versión de modelos y la corrida siguiente las hereda, produciendo rojos fantasma).

| Test | Diagnóstico | Corrección |
|---|---|---|
| `test_auth.py::test_refresh_con_token_revocado_retorna_401` | Test previo a la ventana de gracia del refresh. El `MagicMock` de Valkey nunca configuraba `.get()`, así que devolvía un mock *truthy* y la gracia parecía siempre activa → 200 | El fixture ahora devuelve `None` en `.get()` (comportamiento real de Valkey ante clave ausente). Se agregó el test del camino de gracia, que no existía |
| `test_c31...::test_fix04_pagination_sql` | El test inserta eventos directo en Postgres sin crear el agente; `events.agent_id` tiene FK a `agents.agent_id` | El test crea el `Agent` antes de insertar |
| `test_c31...::test_fix05_compact_chain_retains_newest` | SQL crudo contra la tabla `event`; la tabla es `events` (`Event.__tablename__`) | Nombre de tabla corregido |
| `test_notifications.py::test_notify_event_retry_3x_then_log_only` | Expectativa **anterior a D23/RN-120**: asumía "log_only siempre entrega". D23 hizo que, con un primario configurado que falla, la cascada devuelva `(False, None)` y la alerta caiga en la DLQ | Reescritos para afirmar la semántica vigente (DLQ, `retry_count == 3`, `log_only` como piso de logueo en los 4 intentos). C31 había agregado los tests nuevos (`test_fix01_*`) sin actualizar estos |
| `test_notifications.py::test_log_only_always_delivers` | Ídem | Ídem |

**No** estaban relacionados con la fachada de notificaciones — pero la fachada **sigue vigente y es
un hallazgo aparte**: `N8N_WEBHOOK_URL` apunta a `http://n8n:5678/healthz` (`docker-compose.yml`),
que responde 200, así que `send_n8n()` retorna `True` y **toda** alerta queda `delivered` con
`channel=n8n` sin que se entregue nada. Consecuencia para el Cap. 5: los ítems 11-22 de la
Batería 4 medirían el tiempo hasta un `GET /healthz`, no hasta una notificación; y la DLQ nunca se
ejerce porque el primer canal "tiene éxito" siempre. Cerrar el Change 13
(`integration-n8n-notifications`) o apuntar la variable a un webhook real antes de medir.

## 0.1 Definición de la topología oficial

Decisión pendiente que afecta a **todos** los ítems de latencia: la corrida del 2026-07-02 tuvo al
agente en contenedor sobre el mismo host que el backend (Valkey local, sin latencia de red).
Definir y asentar si la corrida oficial usa esa topología o **agente remoto sobre red** — y
declararlo explícitamente en el Cap. 5. No dejarlo implícito.

## 0.2 Instrumentación ya disponible

| Qué mide | Dónde |
|---|---|
| `detected_at` (estampado en el evento fanotify) | `agent/detector.py:371` |
| `received_at` (estampado al recibir) | `backend/app/modules/events/consumer.py:158` |
| Columnas `detected_at` / `received_at` | `backend/app/modules/events/models.py:55-56` |
| Tabla `rejected_events_audit` + enum `clock_skew` | `backend/app/modules/events/models.py:63,72` · lógica en `consumer.py:195-213` (`_CLOCK_SKEW_S = 300`) |
| `Alert.delivered_at` | `backend/app/modules/alerts/models.py:28` |
| Logs `notify.alert_created` / `notify.delivered` | `backend/app/modules/alerts/service.py:91,154` |
| Prioridad comandos > eventos (RN-109) | `agent/publisher.py:75-79` |
| Cola local en disco del agente | directorio `queue/` del agente |
| Entorno de laboratorio | `docker-compose.yml` (perfil `app`) · `scripts/setup-agent.sh` |
| Directorio vigilado (superficie del generador) | `fim-watch/` → `/watch` en el contenedor |
| Workflows de notificación | `n8n/workflows/{slack,email,ticketing}_alert.json` |

> Las consultas SQL de este documento usan los nombres de columna verificados (`detected_at`,
> `received_at`, `agent_id`, `event_id`). Los **joins** entre `alerts` y `events` están marcados
> como *a validar contra el esquema* — confirmar el nombre de la FK antes de correr.

---

## Batería 3 — Latencia de detección → ítems 1-10 (+ 44, 46, 48)

**Parámetros del protocolo §3.7**: 500 modificaciones, 30 minutos sostenidos.
**Definición**: latencia = `received_at − detected_at`.
**Agregación**: **pandas** — el Cap. 5 lo declara explícitamente. No usar `percentile_cont`.

### Procedimiento

1. Levantar el laboratorio limpio y anotar `date -u` de inicio (ítem 52).
2. Correr el generador (P2) con seed fijo: 500 eventos, mezcla 20 % creación / 70 % modificación / 10 % borrado, sostenido 30 min. **Guardar el manifiesto de lo generado** — es el minuendo del ítem 9.
3. Exportar a CSV crudo y agregar con pandas.

```sql
-- Export crudo. NO agregar en SQL: el Cap. 5 exige pandas.
COPY (
  SELECT event_id,
         detected_at,
         received_at,
         EXTRACT(EPOCH FROM (received_at - detected_at)) * 1000 AS latencia_ms
  FROM events
  WHERE agent_id = '<agente>'
    AND detected_at BETWEEN '<inicio_utc>' AND '<fin_utc>'
  ORDER BY detected_at
) TO '/tmp/bateria3_latencias.csv' WITH CSV HEADER;
```

```python
import pandas as pd
df = pd.read_csv("bateria3_latencias.csv")
s = df["latencia_ms"]
print({
    "1_media":   s.mean(),
    "2_mediana": s.median(),
    "3_desvio":  s.std(),        # ddof=1 (muestral) — declararlo en el Cap. 5
    "4_minimo":  s.min(),
    "5_maximo":  s.max(),
    "6_p95":     s.quantile(0.95),
    "7_p99":     s.quantile(0.99),
    "8_n":       len(s),
})
```

### Ítems

| # | Dato | Método exacto |
|---|---|---|
| 1 | Media aritmética (ms) | `Series.mean()` sobre el CSV |
| 2 | Mediana (ms) | `Series.median()` |
| 3 | Desvío estándar (ms) | `Series.std()` — **declarar si es muestral (ddof=1) o poblacional** |
| 4 | Valor mínimo (ms) | `Series.min()` |
| 5 | Valor máximo (ms) | `Series.max()` |
| 6 | Percentil 95 (ms) | `Series.quantile(0.95)` — **declarar el método de interpolación** |
| 7 | **Percentil 99 (ms)** — indicador principal, umbral < 1.000 | `Series.quantile(0.99)` |
| 8 | Eventos medidos (n) | `COUNT(*)` de la ventana / `len(df)` — deben coincidir |
| 9 | Eventos perdidos (n) | **manifiesto del generador − ítem 8**. Requiere que el generador emita el manifiesto (P2) |
| 10 | Rechazos por `clock_skew` (n) | ver query abajo |

```sql
SELECT count(*) AS rechazos_clock_skew
FROM rejected_events_audit
WHERE reason = 'clock_skew'
  AND agent_id = '<agente>'
  AND created_at BETWEEN '<inicio_utc>' AND '<fin_utc>';
-- Nota: la ventana de tolerancia es de 5 min (_CLOCK_SKEW_S = 300, consumer.py:195-213).
-- Si da 0, confirmar que NTP estaba sincronizado — un 0 por "reloj perfecto" y un 0 por
-- "la validación nunca se ejecutó" se ven idénticos en la planilla.
```

> **Esta misma corrida produce los ítems 44, 46 y 48** (columna "Plataforma FIM" de la Tabla 15).
> No hace falta una corrida aparte: 44 = ítem 2, 46 = ítem 7, 48 = ítem 9.

---

## Batería 4 — Tiempo de notificación → ítems 11-22

**Intervalo**: recepción del evento por el backend → **emisión exitosa del webhook**.
**No incluye** la entrega en n8n ni en el canal final.
**Solo camino feliz / primer intento** — los reintentos (5/30/120 s) harían infalsable el umbral de 5 s.

**Precondición dura (P6)**: sin reglas `high`/`critical` configuradas, esta batería mide cero.
Sembrarlas con `scripts/seed-reglas-lab.sh <password_admin>` (idempotente, vía la API REST).

### Procedimiento

Tres escenarios, tres corridas separadas: **secuencial (1) · 50 concurrentes · 100 concurrentes**.
Con el rate limit vigente (100 ev/60 s por agente), el escenario de 100 concurrentes se estrangula
solo → **P1 es obligatorio**, o repartir la carga entre múltiples `agent_id`.

Dos fuentes posibles, usar la primera y validar con la segunda:

```sql
-- Fuente A (SQL). Validar el nombre de la FK alerts→events contra el esquema.
COPY (
  SELECT a.id,
         EXTRACT(EPOCH FROM (a.delivered_at - e.received_at)) * 1000 AS notif_ms
  FROM alerts a
  JOIN events e ON e.id = a.event_id          -- <-- A VALIDAR
  WHERE a.delivered_at IS NOT NULL
    AND e.received_at BETWEEN '<inicio_utc>' AND '<fin_utc>'
) TO '/tmp/bateria4_<escenario>.csv' WITH CSV HEADER;
```

```
# Fuente B (logs estructurados) — correlacionar por event_id:
#   consumer.event_persisted   (recepción)
#   notify.delivered           (alerts/service.py:154, emisión exitosa)
```

Agregar con pandas, mismo script que la Batería 3.

### Ítems

| # | Dato | Escenario | Método |
|---|---|---|---|
| 11 | Media (ms) | secuencial | `mean()` sobre `notif_ms` |
| 12 | Media (ms) | 50 concurrentes | ídem |
| 13 | Media (ms) | 100 concurrentes | ídem |
| 14 | P50 (ms) | secuencial | `quantile(0.50)` |
| 15 | P50 (ms) | 50 concurrentes | ídem |
| 16 | P50 (ms) | 100 concurrentes | ídem |
| 17 | P95 (ms) | secuencial | `quantile(0.95)` |
| 18 | P95 (ms) | 50 concurrentes | ídem |
| 19 | P95 (ms) | 100 concurrentes | ídem |
| 20 | **P99 (ms)** — umbral < 5.000 | secuencial | `quantile(0.99)` |
| 21 | **P99 (ms)** — umbral < 5.000 | 50 concurrentes | ídem |
| 22 | **P99 (ms)** — umbral < 5.000 | 100 concurrentes | ídem |

> **Riesgo a vigilar en el escenario de 100 concurrentes**: `notify_if_applicable` abre sesiones DB
> síncronas dentro del event loop (`backend/app/modules/alerts/service.py:92-172`). Puede generar
> una cola pesada que distorsione los ítems 13, 16, 19 y 22. Corregirlo antes, o documentarlo
> como limitación conocida en el Cap. 5.

---

## Batería 6 — Cobertura de automatización del triage → ítem 23

**No depende de infraestructura.** Análisis cualitativo con evidencia en código.
Se puede cerrar hoy, en paralelo con todo lo demás.

| # | Dato | Método |
|---|---|---|
| 23 | Clasificación de las 13 tareas NIST SP 800-61r2 | Checkbox por tarea: *Automatizada* / *Requiere humano*, cada una con evidencia `archivo:línea`. Criterio de aceptación: **≥ 80 %** |

Entregable: tabla de 13 filas con las columnas *N · Tarea · ¿Automatizada? · Evidencia*.
La clasificación vigente y su evidencia están en [`docs/entrega_valores_cap5.md`](entrega_valores_cap5.md).

> Las tareas 12 (discriminación autorizado vs. sospechoso) y 13 (decisión de escalamiento) no están
> automatizadas **por decisión de diseño** — el flujo approve/reject es deliberadamente humano.
> Redactarlo así en el Cap. 5: es un argumento, no una carencia.

---

## Batería 2 — Suite automatizada → ítems 24-35

**Fuente exigida**: salida directa de `pytest` **contra el laboratorio**, no contra desarrollo.
No usar `.pytest_cache` — no es salida de pytest y es de entorno dev.

### Procedimiento

```bash
# Levantar el laboratorio (Postgres + Valkey reales) y correr AHÍ.
# --junitxml da los conteos estructurados; el .xml se archiva como evidencia.

pytest agent/tests/   --junitxml=resultados/bateria2_agente.xml  -v
pytest backend/tests/ --junitxml=resultados/bateria2_backend.xml -v
```

Los conteos salen del atributo `<testsuite>` del XML: `tests`, `failures`, `errors`, `skipped`.
**Aprobados = `tests − failures − errors − skipped`.**

| # | Dato | Método |
|---|---|---|
| 24 | Agente — casos ejecutados | `tests` del `bateria2_agente.xml` |
| 25 | Agente — aprobados | `tests − failures − errors − skipped` |
| 26 | Agente — omitidos | `skipped` |
| 27 | Agente — fallidos | `failures + errors` |
| 28 | Backend — casos ejecutados | `tests` del `bateria2_backend.xml` |
| 29 | Backend — aprobados | ídem fórmula |
| 30 | Backend — omitidos | `skipped` |
| 31 | Backend — fallidos | `failures + errors` |
| 32 | Total — casos ejecutados | 24 + 28 |
| 33 | Total — aprobados | 25 + 29 |
| 34 | Total — omitidos | 26 + 30 |
| 35 | Total — fallidos | 27 + 31 |

**Nota**: `agent/` no tiene configuración de pytest (sin `pyproject.toml` ni `pytest.ini`).
Agregarla antes de la corrida para que los conteos sean reproducibles.

### El requisito "31 de 31 historias" necesita trabajo aparte

Hay 31 historias (`docs/historias_de_usuario.md`, US-01…US-31) y ~785 tests, pero **ningún test
cita una US** — están indexados por change (C22/C31/C32) y por RN. Los conteos de arriba **no
demuestran** cobertura de historias.

Dos caminos, elegir uno antes de la corrida:

- **(a)** Marcar los tests con `@pytest.mark.us("US-07")` y derivar la cobertura del XML. Reproducible, pero hay que tocar 785 tests.
- **(b)** Matriz de trazabilidad manual US ↔ test, versionada como anexo. Más rápido, pero no se autoverifica.

---

## Batería 5 — Resiliencia offline → ítems 36-43

**Parámetros del protocolo**: 300 s de desconexión, 3.000 eventos generados durante el corte.

### Procedimiento

1. Agente `online`, cola vacía. Anotar `date -u`.
2. Cortar la conectividad con Valkey (`docker compose stop valkey`, o regla de firewall si se
   quiere un corte de red en vez de una caída de servicio — **declarar cuál se usó**).
3. Generar 3.000 eventos durante el corte (generador P2, seed registrado).
4. Contar los archivos en `queue/` **antes** de reconectar → ítem 38.
5. Reconectar. Cronometrar hasta el criterio de recuperación definido en P7 → ítem 43.
6. Verificar en DB: conteo, orden y duplicados.

| # | Dato | Objetivo | Método exacto |
|---|---|---|---|
| 36 | Duración real de la desconexión (s) | 300 | `date -u` al cortar y al reconectar. Registrar el valor **real**, no el nominal |
| 37 | Eventos generados durante la desconexión (n) | 3.000 | Manifiesto del generador |
| 38 | Eventos preservados en cola local (n) | = 37 | `ls queue/ \| wc -l` **antes** de reconectar |
| 39 | Eventos entregados tras reconexión (n) | = 38 | `COUNT(*)` en `events` de la ventana + cola drenada a 0 |
| 40 | Orden FIFO preservado (Sí/No) | Sí | Verificar monotonía del sufijo del generador ordenando por `detected_at` |
| 41 | Duplicaciones detectadas (n) | 0 | ver query abajo |
| 42 | Comandos antes que eventos encolados (Sí/No) | Sí | Encolar un comando durante el corte y verificar en el log del agente que se procesa **primero**. Forzado por `agent/publisher.py:75-79` (RN-109) |
| 43 | **Tiempo de recuperación total (s)** — umbral < 30 | < 30 | **Depende de P7.** Ver abajo |

```sql
-- Ítem 41: debe devolver 0 filas.
SELECT event_id, count(*)
FROM events
WHERE detected_at BETWEEN '<inicio_corte>' AND '<fin_drenaje>'
GROUP BY event_id
HAVING count(*) > 1;
```

### Ítem 43 — no se puede medir sin cerrar P7

Con el rate limit vigente (100 ev/60 s), drenar 3.000 eventos tarda **~30 minutos**. El umbral de
30 s no se puede cumplir **ni refutar**. Un criterio infalsable no es un criterio.

Tres opciones, hay que elegir una y asentarla en el appendix:

- **(a)** Parametrizar el rate limit para el experimento (P1) y medir el drenaje completo.
- **(b)** Redefinir el indicador como *"agente operativo con drenaje iniciado"* — mide reconexión, no drenaje.
- **(c)** Bajar el generador a < 1,6 ev/s para que 3.000 eventos entren dentro del límite.

Cualquiera es defendible. **Lo indefendible es dejar el criterio como está y reportar un número.**

---

## Batería 7 — Grupo de control → ítems 45, 47, 49, 50

**P3 cerrada: el script de control existe** (`scripts/control_hashing.py`). Hasta ahora los valores
de esta columna eran la esperanza matemática de un script que nunca se escribió
(`E[Uniform(0, 900 s)] = 450 s`) y el Cap. 5 la presentaba como comparación **experimental**.
Ahora sale de una medición.

### El script de control

- Corre por cron cada **15 min** (900 s) — `--print-cron` emite la entrada lista para `crontab -e`;
  también admite `--loop --interval 900` y corridas bajo demanda para probarlo.
- Hashea (SHA-256) el mismo directorio vigilado (`fim-watch/`) y compara contra el snapshot de la
  corrida previa, guardado en `--state` (el equivalente a la base de datos de AIDE).
- Registra, por cada cambio detectado, `scan_id` y el timestamp de detección, en
  `resultados/bateria7_control.csv`.
- El **primer scan es la línea de base** y no emite filas: hay que correrlo **antes** del generador.
- Se ejecuta **contra la misma carga generada**, en la misma ventana temporal, para que la
  comparación sea pareja.

**Latencia del control** = `timestamp_deteccion_cron − timestamp_modificacion_real`.
El timestamp real sale del manifiesto del generador (P2); el join por `ruta_agente` y el cálculo de
los ítems 45, 47, 49 y 50 los hace `scripts/analisis_control.py`. Ver `scripts/README.md` para el
criterio de atribución (`--criterio primer_cambio` / `ultimo_cambio`) y para la decisión de comparar
solo hash o también metadatos — **ambas hay que declararlas en el capítulo**.

### Ítems

| # | Dato | Fuente |
|---|---|---|
| 44 | Mediana de latencia — **Plataforma FIM** | = ítem 2 (Batería 3) |
| 45 | Mediana de latencia — **Script cron** | `median()` de las latencias del control |
| 46 | Latencia P99 — **Plataforma FIM** | = ítem 7 (Batería 3) |
| 47 | Latencia P99 — **Script cron** | `quantile(0.99)` del control |
| 48 | Eventos perdidos — **Plataforma FIM** | = ítem 9 (Batería 3) |
| 49 | Eventos perdidos — **Script cron** | manifiesto − detectados por el cron |
| 50 | **Factor de mejora** (calculado) | ítem 45 ÷ ítem 44. Declarar en el Cap. 5 qué métrica usa el cociente |

> **Los ítems 49 y 50 son el argumento más fuerte de la tesis.** El cron pierde eventos por
> mecanismos estructurales: los cambios revertidos dentro de la ventana de 15 min son
> **invisibles**, y N cambios sucesivos al mismo archivo **colapsan en 1**. El generador incluye
> deliberadamente ambos patrones (`--revert-frac`, `--burst-frac`) más los archivos efímeros
> (`--ephemeral-frac`), para que el ítem 49 mida algo real y no dé un empate artificial.
> `analisis_control.py` reporta la pérdida desglosada por causa (`colapsado`, `no_detectado`,
> `fuera_de_ventana`) y por patrón del generador.

Ya no hace falta la salida de emergencia de renombrar la columna a *cota analítica*: la columna
sale de una corrida real. Lo que sí hay que declarar en el Cap. 5 es el criterio de atribución y el
criterio de comparación del control (solo hash vs. hash + metadatos).

---

## Metadatos de reproducibilidad → ítems 51-55

| # | Dato | Método exacto |
|---|---|---|
| 51 | Hash/tag del commit de la corrida | `git rev-parse HEAD` **con el árbol limpio**. Crear tag (`git tag -a v1.0-tesis`) y registrarlo. Verificar con `git status --porcelain` (debe salir vacío) |
| 52 | Fecha y hora **UTC** de cada batería | `date -u --iso-8601=seconds` al inicio y al fin de **cada** batería. Una fila por batería, no una fecha global |
| 53 | Versiones efectivas desplegadas | Verificar contra el runtime, no contra el compose. Ver comandos abajo |
| 54 | Semilla / parámetros del generador | El generador (P2) debe **loguear su configuración completa** al arrancar: seed, tasa, cantidad, mezcla de operaciones, directorio destino. Archivar ese log |
| 55 | `.pcap` + trazas `strace` | Una captura por batería como mínimo. Ver abajo |

### Ítem 53 — verificar contra el runtime

```bash
docker compose exec db      psql -U <user> -c 'SELECT version();'
docker compose exec valkey  valkey-server --version
docker compose exec n8n     n8n --version
```

Contrastar con lo declarado en `docs/arquitectura_stack.md:41,43,44` y `:1688-1690`
(PostgreSQL 18.3 · Valkey 9.0.3 · n8n 2.16.1) y con `docker-compose.yml:35,65,85`.

*Limpieza — hecha*: el compose de ejemplo de `docs/arquitectura_stack.md:1513,1536` mostraba
`postgres:18` / `valkey:9.0` sin patch version; ahora dice `postgres:18.3` / `valkey/valkey:9.0.3`,
consistente con lo declarado y con `docker-compose.yml`.

### Ítem 55 — el `.pcap` requiere una decisión previa

El canal agente↔backend va por **Valkey Streams sobre mTLS**. Una captura cruda **no verifica nada**:
sale cifrada. Dos opciones:

- **(a)** Capturar en el **loopback del contenedor Valkey**, del lado descifrado.
- **(b)** Capturar en la interfaz de red exportando `SSLKEYLOGFILE` en el agente, y archivar el
  archivo de claves junto al `.pcap` para que sea descifrable en el análisis.

```bash
# Captura de red (elegir interfaz según la opción a/b)
tcpdump -i <iface> -w resultados/bateria<N>.pcap

# Traza de syscalls del agente durante la batería
strace -f -tt -p <pid_agente> -o resultados/bateria<N>.strace
```

> **`strace -f` sobre el agente degrada la latencia medida.** No correrlo durante la corrida de la
> que salen los ítems 1-7. Hacer una **corrida de verificación cruzada aparte**, declarada como tal:
> su propósito es demostrar el mecanismo, no producir los números de la Tabla 11.

---

## Orden de ejecución sugerido

| Paso | Qué | Produce | Depende de |
|---|---|---|---|
| 0 | Cerrar P1–P7, commitear, taggear | 51 | — |
| 1 | Batería 6 (cualitativa, en paralelo con todo) | 23 | nada |
| 2 | Batería 2 (suite pytest contra lab) | 24-35 | P5, P6 |
| 3 | Batería 3 (latencia, 30 min) | 1-10, 44, 46, 48 | P2 |
| 4 | Batería 7 (control, misma ventana que la 3) | 45, 47, 49, 50 | P2, P3, paso 3 |
| 5 | Batería 4 (notificación ×3 escenarios) | 11-22 | P1, P6 |
| 6 | Batería 5 (offline) | 36-43 | P1, P2, P7 |
| 7 | Corrida de verificación cruzada (pcap + strace) | 55 | pasos 3-6 |
| — | Registrar `date -u` en cada paso | 52 | — |
| — | Archivar logs del generador | 54 | P2 |
| — | Verificar versiones en runtime | 53 | — |

**Las Baterías 3 y 7 deben correr sobre la misma carga y ventana temporal.** Si el control no ve
exactamente los mismos cambios que la plataforma, la Tabla 15 no compara nada.

## Entregable esperado del equipo de desarrollo

```
resultados/
├── bateria2_agente.xml          # ítems 24-27
├── bateria2_backend.xml         # ítems 28-31
├── bateria3_latencias.csv       # ítems 1-8, 44, 46
├── bateria3_manifiesto.json     # ítems 9, 48, 54 — generador_carga.py
├── bateria3_manifiesto.jsonl    # respaldo incremental del manifiesto
├── bateria3_generador.log       # ítem 54 — configuración completa del generador
├── bateria4_secuencial.csv      # ítems 11, 14, 17, 20
├── bateria4_50c.csv             # ítems 12, 15, 18, 21
├── bateria4_100c.csv            # ítems 13, 16, 19, 22
├── bateria5_cola.txt            # ítems 36-43
├── bateria7_control.csv         # ítems 45, 47, 49 — control_hashing.py
├── bateria7_latencias.csv       # ítems 45, 47, 50 — analisis_control.py
├── control_estado.json          # snapshot del último scan del control
├── bateria<N>.pcap              # ítem 55
├── bateria<N>.strace            # ítem 55
├── entorno.txt                  # ítems 51, 53
└── cronologia_utc.txt           # ítem 52
```

Los archivos crudos se archivan junto a las planillas (exigencia del Anexo F). Las planillas se
llenan **desde** estos archivos, nunca a mano.
