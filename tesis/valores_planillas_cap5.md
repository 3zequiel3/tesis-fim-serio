# Valores para las planillas de captura — Capítulo 5 de Tesis.pdf

Fuente: análisis del código (2026-07-02) + e2e real del agente contra el stack Docker completo.
Convención: **[ASENTAR]** = valor determinístico, se puede escribir hoy. **[MEDIR]** = debe salir
de ejecutar la batería del protocolo §3.7; se indica rango esperado y método. No asentar un
valor [MEDIR] sin la corrida real.

Offset de páginas: página impresa N = página N+13 del PDF.

---

## Decisiones previas OBLIGATORIAS (antes de ejecutar las baterías)

Tres inconsistencias protocolo ↔ implementación detectadas. Si no se resuelven, dos criterios
de aceptación son imposibles de cumplir tal como están redactados:

1. **Rate limit vs. batería 5 (CRÍTICO)**: el backend acepta 100 eventos/60 s por agente
   (`backend/app/modules/events/consumer.py:69`). El protocolo genera 10 ev/s y el drenaje
   post-reconexión re-publica 3.000 eventos de golpe → la entrega íntegra tarda ~30 minutos.
   El criterio "tiempo de recuperación < 30 s" solo es defendible si se define como
   "agente operativo con drenaje iniciado". Alternativas: parametrizar el rate limit para el
   experimento, o bajar el generador a < 1,6 ev/s. Cerrar en el appendix de decisiones.
2. **Umbral de notificación (5 s) infalsable ante reintentos**: timeout n8n 10 s
   (`alerts/notifier.py:23`) + reintentos 5/30/120 s (`alerts/service.py:47`). Definir el
   indicador sobre entregas exitosas en primer intento, con n8n sano durante la batería.
3. **Estado del proyecto**: §1.7 y §5.1 dicen "implementación pendiente"; el repo la tiene
   completa. Actualizar la redacción o presentarlo como adenda (Anexo F).

Además: solo los eventos con severidad `critical`/`high` generan Alert (RN-52,
`alerts/service.py:96`) → la batería de notificación necesita reglas high/critical configuradas,
y los 1.000 eventos deben inyectarse a ≤ 100/min por agente o repartirse entre varios agent_id.

---

## Tabla 11 — Latencia de detección (§5.2)

Definición ya instrumentada: latencia = `received_at − detected_at`
(`agent/detector.py:371` estampa en el evento fanotify; `consumer.py:158` al recibir).

Valores MEDIDOS el 2026-07-02 (corrida local: agente en contenedor Docker sobre el
mismo host, comunicación por Valkey local; un despliegue con agente remoto sobre red
agregaría latencia de red). Muestra n=500 generada en ~8 min paceada bajo el rate
limit (100 ev/60 s). La versión oficial del protocolo pide 30 min sostenidos: repetir
si se quiere el valor bajo carga temporal completa; la distribución no debería cambiar.

| Campo | Valor | Tipo |
|---|---|---|
| Eventos medidos | **500** (20% creación, 70% modif., 10% borrado) | [MEDIDO 2026-07-02] |
| Media aritmética | **13,15 ms** | [MEDIDO] |
| Mediana (P50) | **13,92 ms** | [MEDIDO] |
| Desvío estándar | **3,93 ms** | [MEDIDO] |
| Mínimo | **3,28 ms** | [MEDIDO] |
| Máximo | **43,43 ms** | [MEDIDO] |
| Percentil 95 | **17,54 ms** | [MEDIDO] |
| Percentil 99 (indicador principal) | **19,60 ms** — umbral 1.000 ms se cumple con ~51× de margen | [MEDIDO] |
| Eventos perdidos | **0** (500/500 entregados, 0 rate_limited) | [MEDIDO] |
| Rechazos por desincronización horaria | **0** | [MEDIDO] |

SQL de medición (una sola corrida cubre toda la tabla):

```sql
SELECT count(*),
       avg(extract(epoch from (received_at - detected_at))*1000)  AS media_ms,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY extract(epoch from (received_at - detected_at))*1000) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch from (received_at - detected_at))*1000) AS p95,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY extract(epoch from (received_at - detected_at))*1000) AS p99,
       stddev_samp(extract(epoch from (received_at - detected_at))*1000) AS desvio,
       min(extract(epoch from (received_at - detected_at))*1000) AS minimo,
       max(extract(epoch from (received_at - detected_at))*1000) AS maximo
FROM events
WHERE agent_id = '<agente>' AND detected_at BETWEEN '<inicio>' AND '<fin>';
```

**Resuelto (2026-07-02)**: la detección de creación/borrado/renombrado ya funciona. Se reemplazó
pyfanotify por un backend fanotify propio en modo FID (`agent/_fanotify.py`, ctypes/glibc); la
corrida de 500 eventos incluyó creación, modificación y borrado, todos detectados. Ver abajo.

---

## Tabla 12 — Tiempo de notificación (§5.3)

Definición: `consumer.event_persisted` → `notify.delivered` (logs estructurados), o
`alert.delivered_at − event.received_at` en SQL. Solo camino feliz / primer intento.

| Escenario | Media | P99 | Tipo |
|---|---|---|---|
| Secuencial (1 concurrente) | ~40–90 ms | ~200–800 ms | [MEDIR] |
| Moderada (50 concurrentes) | ~100–300 ms | ~500–2.000 ms | [MEDIR] |
| Alta (100 concurrentes) | ~200–500 ms | ~1.000–3.000 ms | [MEDIR] |

Umbral 5.000 ms alcanzable en los tres escenarios. Riesgo de cola pesada en el escenario alto:
`notify_if_applicable` abre sesiones DB síncronas dentro del event loop
(`alerts/service.py:92-172`) — documentar o corregir antes de la batería.

---

## Tabla 13 — Cobertura de automatización del triage (§5.4) — [ASENTAR HOY, COMPLETA]

Valores determinísticos verificados en código. **11 de 13 = 84,6 % ≥ 80 % → CUMPLE.**

| N | Tarea | ¿Automatizada? | Evidencia |
|---|---|---|---|
| 1 | Recepción del evento con metadatos | Sí | `consumer.py:157-277`; pid/uid/exe en `detector.py:366-373` |
| 2 | Cálculo del hash actualizado | Sí | `detector.py:122-146` |
| 3 | Comparación contra baseline vigente | Sí | `detector.py:433-434,595` |
| 4 | Identificación del tipo de cambio | Sí | `detector.py:411-427` |
| 5 | Consulta de reglas aplicables | Sí | `agent/rules.py:62-74` |
| 6 | Asignación de severidad | Sí | `alerts/service.py:60-77` |
| 7 | Selección de acción automática | Sí | `rules.py:62-74` (4 niveles, default `alert_only`) |
| 8 | Ejecución de la acción automática | Sí | `agent/decision.py:52-93,158-201` |
| 9 | Registro y auditoría | Sí | ingesta + `RejectedEventAudit` |
| 10 | Actualización de eventos previos (superseded) | Sí | cadena `parent_event_id` — verificada en e2e real |
| 11 | Notificación según severidad | Sí | `alerts/service.py:82-123` + cascada de fallbacks |
| 12 | Discriminación autorizado vs. sospechoso | No (humano) | flujo approve/reject — por diseño |
| 13 | Decisión de escalamiento | No (humano) | por diseño |

---

## Tabla 14 — Resiliencia offline (§5.6)

E2E real (versión reducida, 2026-07-02): corte de Valkey de 22 s, 3 eventos generados offline
→ 3 encolados con prefijo epoch-ms, 3 entregados en orden FIFO al reconectar, 0 duplicados,
heartbeat recuperado en < 1 s, drenaje completado ~41 s después (cadencia de reintento).

Corrida REDUCIDA medida el 2026-07-02 (corte de Valkey ~24 s, 30 eventos): valida el
mecanismo al 100 %. Los parámetros oficiales del protocolo (300 s / 3.000 eventos)
siguen pendientes de una corrida completa — que con el rate limit actual tarda ~30 min
en drenar (ver decisión previa #1). La corrida reducida no dio pérdidas ni duplicados.

| Campo | Valor | Tipo |
|---|---|---|
| Duración de la desconexión | **300 s** (medido: ~24 s en la reducida) | [ASENTAR] parámetro / [MEDIDO reducida] |
| Eventos generados durante la desconexión | **3.000** (medido: 30 en la reducida) | [ASENTAR] parámetro / [MEDIDO reducida] |
| Eventos preservados en cola local | **30 / 30** en la reducida (3.000 esperado en la completa) | [MEDIDO 2026-07-02] — `ls queue/ \| wc -l` = 30 |
| Eventos entregados tras reconexión | **30 (100 %)** en la reducida | [MEDIDO] — 30 filas en DB, cola drenada a 0 |
| Orden FIFO preservado | **Sí** — `off_01 → off_30` por `detected_at` | [MEDIDO] |
| Duplicaciones detectadas | **0** — 30 filas, 30 `event_id` distintos | [MEDIDO] — `GROUP BY event_id HAVING count(*)>1` vacío |
| Comandos procesados antes que eventos encolados | **Sí** | [ASENTAR] — forzado por código: `publisher.py:75-79` (RN-109) |
| Tiempo de recuperación total | agente reconectó + drenó (heartbeat `online`); drenaje completo por cadencia de reintento (~30–40 s en la reducida) | [MEDIDO reducida] — requiere la redefinición de la decisión previa #1 para la métrica formal |

---

## Tabla 15 — Comparación vs. grupo de control (cron 15 min) (§5.7)

| Campo | Plataforma FIM | Script cron | Factor de mejora | Tipo |
|---|---|---|---|---|
| Mediana de latencia | ~10–25 ms | ~450.000 ms (esperanza de Uniform(0, 900 s)) | ~10⁴ | [MEDIR ambos] |
| Latencia P99 | ~150–400 ms | ~891.000 ms (0,99 × 900 s) | ~10³–10⁴ | [MEDIR ambos] |
| Eventos perdidos | 0 esperado | > 0 esperable (cambios revertidos dentro de la ventana son invisibles; N cambios al mismo archivo colapsan en 1) | — | [MEDIR ambos] |
| Baseline separada y cifrada | Sí | No | — | [ASENTAR] |
| Notificación con fallbacks | Sí | No | — | [ASENTAR] |
| Trazabilidad de auditoría | Sí | No | — | [ASENTAR] |

---

## Tabla 16 — Síntesis de criterios de aceptación (§5.8 / Tabla 1)

| Criterio | Umbral | Resultado esperado | Tipo |
|---|---|---|---|
| Latencia de detección P99 | < 1.000 ms | **19,60 ms → CUMPLE** (medido n=500) | [MEDIDO 2026-07-02] |
| Notificación P99 secuencial | < 5.000 ms | ~200–800 ms → CUMPLE | [MEDIR] |
| Notificación P99, 100 concurrentes | < 5.000 ms | ~1.000–3.000 ms → CUMPLE | [MEDIR] |
| Cobertura de triage | ≥ 80 % | **84,6 % → CUMPLE** | [ASENTAR HOY] |
| Casos funcionales | 31/31 | a ejecutar (batería 2) | [MEDIR] |
| Resiliencia offline | 100 % | **100 % en corrida reducida** (30/30, FIFO, 0 dup) → CUMPLE; completa 3.000 pendiente | [MEDIDO reducida 2026-07-02] |
| Tiempo de recuperación | < 30 s | cumplible SOLO con la redefinición (decisión previa #1) | [MEDIR] |
| Falsos negativos | 0 | 0 esperado | [MEDIR] |

---

## Bloqueante técnico previo a las baterías — RESUELTO (2026-07-02)

El detector no arrancaba contra pyfanotify==0.3.0 real (usaba `pyfanotify.init/mark/read`, que no
existen a nivel módulo). **Resuelto**: se implementó un backend fanotify propio en modo FID
(`agent/_fanotify.py`, ctypes/glibc con `FAN_REPORT_DFID_NAME` + `open_by_handle_at`), que sí
soporta FAN_CREATE/FAN_DELETE/FAN_MOVED_* (los que en modo fd daban EINVAL). Verificado
end-to-end: agente en contenedor Docker (`CAP_SYS_ADMIN` + `CAP_DAC_READ_SEARCH`) detectando
creación/modificación/borrado reales, 500/500 eventos entregados. Commit `f1e8681` (backend
fanotify) + `746ac5e` (fix de ceguera silenciosa de la exclusión FILESYSTEM). El protocolo
completo ya se puede ejecutar.
