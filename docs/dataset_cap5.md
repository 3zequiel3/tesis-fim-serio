# Dataset del Capítulo 5 — 55 valores

**Corrida oficial del 2026-08-19.** Un renglón por ítem, con el valor y la fuente.

| Metadato | Valor |
|---|---|
| Commit (ítem 51) | `77f0c53e9c5dac28f9b36e56e09bcdb8b214ba1c` — árbol limpio (`git status --porcelain` vacío) |
| Artefactos crudos | `resultados/` (35 archivos) |
| Topología | **CO-RESIDENTE** — agente en contenedor sobre el mismo host que el backend |
| Estado | **55 de 55 producidos.** Dos salvedades, en «Salvedades» al final |

> **Salvedad de topología, obligatoria en el Cap. 5.** Valkey corre en el mismo host, sin latencia
> de red. Los ítems 1-7, 44 y 46 son una **cota inferior**. Con 12 ms de mediana contra 9 minutos
> del control, la conclusión de la Tabla 15 resiste cualquier RTT razonable, pero el número debe
> presentarse como cota, no como latencia de despliegue distribuido.

---

## Tabla 11 — Latencia de detección (Batería 3, §5.2)

Definición: `received_at − detected_at`. Agregado con **pandas 3.0.5** sobre `bateria3_latencias.csv`.

| # | Dato | Valor |
|---|---|---|
| 1 | Media aritmética (ms) | **10,879** |
| 2 | Mediana (ms) | **12,176** |
| 3 | Desvío estándar (ms) | **3,699** (muestral, `ddof=1` — declararlo) |
| 4 | Valor mínimo (ms) | **3,021** |
| 5 | Valor máximo (ms) | **19,802** |
| 6 | Percentil 95 (ms) | **16,319** |
| 7 | **Percentil 99 (ms)** — umbral < 1.000 | **17,274 → CUMPLE** (factor 58) |
| 8 | Eventos medidos (n) | **493** |
| 9 | Eventos perdidos (n) | **7** (manifiesto 500 − ítem 8) |
| 10 | Rechazos por `clock_skew` (n) | **0** |

**Sobre el ítem 10.** Es un cero verificado, no un cero por validación ausente: se comprobó en el
backend en ejecución que `_handle_message` valida `sent_at` con `_CLOCK_SKEW_S = 300`, y que
`rejected_events_audit` está vacía por completo. La distinción importa porque el plan advierte que
ambos ceros se ven idénticos en la planilla.

**Sobre el ítem 9.** El número es correcto. La *explicación* del mecanismo no está probada — ver
«Salvedades».

Parámetros del generador (ítem 54): `seed=20260819`, `rate=0.278 ev/s`, `count=500`,
`mix=20/70/10`, `revert=25 %`, `burst=25 %/3`, `ephemeral=10 %`, `critical=15 %`.

---

## Tabla 12 — Tiempo de notificación (Batería 4, §5.3)

Intervalo: recepción del evento por el backend → emisión exitosa del webhook. **No** incluye la
entrega en n8n ni en el canal final. Camino feliz, primer intento.

| Escenario | # media | Media (ms) | # P50 | P50 (ms) | # P95 | P95 (ms) | # P99 | **P99 (ms)** | Umbral < 5.000 |
|---|---|---|---|---|---|---|---|---|---|
| Secuencial (n=60) | 11 | **47,6** | 14 | **49,2** | 17 | **55,8** | 20 | **63,4** | CUMPLE |
| 50 concurrentes (n=99) | 12 | **50,1** | 15 | **48,7** | 18 | **69,8** | 21 | **80,7** | CUMPLE |
| 100 concurrentes (n=170) | 13 | **45,6** | 16 | **44,3** | 19 | **66,7** | 22 | **85,5** | CUMPLE |

Los tres escenarios cumplen con dos órdenes de magnitud de margen. La media **no se degrada** al
subir la concurrencia (45,6 ms a 100 concurrentes contra 47,6 ms secuencial).

**Condición de la corrida:** `N8N_WEBHOOK_URL` apuntando a un receptor propio
(`scripts/receptor_webhook.py`), no a n8n. Es lo que corresponde a la definición del intervalo,
pero implica que **esta corrida no ejercita la escalera de reintentos ni el DLQ**, porque el
receptor siempre responde 200.

---

## Tabla 13 — Cobertura de automatización del triage (Batería 6, §5.4)

| # | Dato | Valor |
|---|---|---|
| 23 | Clasificación de las 13 tareas NIST SP 800-61r2 | **11 / 13 = 84,6 %** — umbral ≥ 80 % → **CUMPLE** |

| N | Tarea NIST | ¿Automatizada? | Evidencia |
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
| 10 | Actualización de eventos previos (`superseded`) | Sí | cadena `parent_event_id` |
| 11 | Notificación según severidad | Sí | `alerts/service.py:82-123` + cascada |
| 12 | Discriminación autorizado vs. sospechoso | **Humano** | flujo approve/reject — **por diseño** |
| 13 | Decisión de escalamiento | **Humano** | **por diseño** |

Las dos tareas humanas lo son por decisión de diseño. Redactarlo como argumento, no como carencia.

---

## Tabla 16-bis — Resultado de la batería automatizada (§5.5)

Fuente: `--junitxml` de `pytest` contra Postgres 18.3 y Valkey 9.0.3 reales.
Aprobados = `tests − failures − errors − skipped`.

| # | Dato | Valor |
|---|---|---|
| 24 | Agente — casos ejecutados | **418** |
| 25 | Agente — aprobados | **417** |
| 26 | Agente — omitidos | **1** |
| 27 | Agente — fallidos | **0** |
| 28 | Backend — casos ejecutados | **494** |
| 29 | Backend — aprobados | **494** |
| 30 | Backend — omitidos | **0** |
| 31 | Backend — fallidos | **0** |
| 32 | Total — casos ejecutados | **912** |
| 33 | Total — aprobados | **911** |
| 34 | Total — omitidos | **1** |
| 35 | Total — fallidos | **0** |

El único omitido es legítimo y explicable: un test del agente que sólo aplica cuando fanotify **no**
está disponible.

> ### El requisito «31 de 31 historias» NO se cumple con esta evidencia
>
> Los conteos de arriba miden **tests**, no **historias**. La matriz de trazabilidad
> (`docs/trazabilidad_us_tests.md`) mapea las 31 historias contra la suite y da:
>
> **2 `completa` · 28 `parcial` · 1 `sin cobertura`.**
>
> Lo defendible con esta evidencia es: *«las 31 historias tienen implementación, y 28 tienen al
> menos un test que asserta parte de sus criterios»*. **No** «31 de 31 cubiertas». La historia sin
> cobertura es **US-09** (visor de diff), y no por falta de test: **la funcionalidad no existe** —
> el panel fue removido de `EventDetail.tsx` y `DiffViewer.tsx` es código muerto.
>
> El sesgo es estructural, no accidental: la suite es densa donde el sistema es riesgoso (máquina de
> estados, HMAC, outbox, cola offline, cifrado del baseline) y nula donde es visual.

**Salvedad del entorno:** los servicios de respaldo son los del laboratorio, pero el intérprete de
pytest corrió en el host contra ellos (el compose no publica puertos). Declararlo.

---

## Tabla 14 — Resiliencia offline (Batería 5, §5.6)

| # | Dato | Objetivo | Valor |
|---|---|---|---|
| 36 | Duración real de la desconexión (s) | 300 | **326** |
| 37 | Eventos generados durante la desconexión (n) | 3.000 | **3.000** |
| 38 | Eventos preservados en cola local (n) | = 37 | **2.988** |
| 39 | Eventos entregados tras reconexión (n) | = 38 | **2.988** |
| 40 | Orden FIFO preservado | Sí | **Sí — 0 de 2.988 fuera de orden** |
| 41 | Duplicaciones detectadas (n) | 0 | **0** |
| 42 | Comandos antes que eventos encolados | Sí | **Parcial — ver abajo** |
| 43 | **Tiempo de recuperación total (s)** | < 30 | **153 → NO CUMPLE** |

Cero descartes locales y cero rechazos del backend. El ítem 40 se verificó comparando el rango de
`detected_at` contra el de `received_at`: coinciden en los 2.988.

**Ítem 43 — no cumple, y hay que reportarlo así.** Drenar 2.988 eventos tardó 153 s con el rate
limit ya elevado a 100.000/min (D38/RN-132 exige declarar el valor efectivo). El umbral de 30 s
exigiría sostener 100 eventos por segundo. Es un resultado honesto; lo que ya no ocurre es que el
criterio sea infalsable, que era el problema original.

**Ítem 42 — parcialmente demostrado.** El ciclo funciona de punta a punta: con 199 eventos
encolados, la aprobación emitió el comando `baseline_update`, el agente lo **ejecutó y lo ackeó**, y
los 200 eventos del corte se entregaron. Lo que no quedó aislado es la *precedencia* de RN-109
(`agent/publisher.py:75-79`): el drenaje termina en segundos y la carrera no es observable sin
instrumentar el agente.

> **Hallazgo de disponibilidad, más grave que el ítem.** No se puede aprobar durante el corte:
> con Valkey caído, **toda request autenticada devuelve 500**, con traceback en
> `app/core/deps.py:54 get_current_user` → `ConnectionError` al consultar la blacklist del token.
> Valkey es dependencia dura de toda la superficie autenticada, y falla con 500, ni siquiera con un
> 503. El fallo es al menos atómico: nada quedó a medias.
>
> Para una tesis que presume resiliencia offline **del agente**, que el operador no pueda ni
> loguearse cuando Valkey se cae es una asimetría que conviene anticipar.

---

## Tabla 15 — Comparación experimental vs. control (§5.7)

Ambas columnas sobre la **misma carga y la misma ventana temporal**. Criterio de atribución del
control: `primer_cambio` (lectura de seguridad — la ventana de exposición empieza en el primer
cambio no detectado).

| # | Dato | Plataforma FIM | Script cron (900 s) |
|---|---|---|---|
| 44 / 45 | Mediana de latencia | **12,18 ms** | **553.054,29 ms** (9,2 min) |
| 46 / 47 | Latencia P99 | **17,27 ms** | **897.370,87 ms** (15,0 min) |
| 48 / 49 | Eventos perdidos | **7 de 500 (1,4 %)** | **395 de 500 (79,0 %)** |
| 50 | **Factor de mejora** (calculado) | | **45.421,7×** |

El ítem 50 es el cociente de las medianas (45 ÷ 44). Declarar en el Cap. 5 qué métrica usa el
cociente.

**Desglose de la pérdida del control (ítem 49):** 293 por **colapso** de cambios sucesivos sobre el
mismo archivo, 102 por **no detección**. Por patrón: 222 simples, 83 colapsados, 80 revertidos, 10
efímeros. Esto convierte la limitación del escaneo periódico en un dato con causa, no en un
argumento.

---

## Metadatos de reproducibilidad

| # | Dato | Valor |
|---|---|---|
| 51 | Commit de la corrida | `77f0c53e9c5dac28f9b36e56e09bcdb8b214ba1c`, árbol limpio |
| 52 | Fecha y hora UTC por batería | `resultados/cronologia_utc.txt` (una marca de inicio y fin por batería) |
| 53 | Versiones efectivas | **PostgreSQL 18.3**, **Valkey 9.0.3** — verificadas contra el *runtime*, coinciden con lo declarado. **n8n: no desplegado** (ver abajo) |
| 54 | Semilla y parámetros del generador | B3 `seed=20260819`; B5 `seed=555`; B4 `seed=4001/4050/4100`. Configuración completa logueada al arrancar y embebida en cada manifiesto |
| 55 | Archivos crudos de verificación cruzada | `bateria55_valkey.pcap` (662 paquetes) + `bateria55_agente.strace` |

**Ítem 53 — n8n no está desplegado.** La Batería 4 se midió contra un receptor propio, que es lo que
corresponde a la definición del intervalo. Declarar que la versión de n8n no aplica a esta corrida.

### Ítem 55 — qué evidencia la captura, en las dos direcciones

**A favor:** 248 campos `"signature"` visibles — la firma HMAC es real y viaja en **cada** mensaje.
120 campos `"sent_at"`, confirmando que el campo de D37/RN-131 está en el payload firmado en
producción. El `strace` muestra **61 llamadas a `open_by_handle_at`** y 72 líneas de fanotify:
evidencia a nivel de syscall del modo FID — que **ningún test unitario del repositorio cubre**,
porque `agent/_fanotify.py` no tiene tests.

**En contra:** el tráfico va **en claro**. Los paths (`/watch/gen_00001.txt`) son legibles en el
cable. El laboratorio corre `valkey://`, no `valkeys://` (RN-115). **Declarar que el cifrado de
transporte está implementado pero no habilitado en el entorno de medición.**

---

## Salvedades

1. **Ítem 9 — el número está, la explicación no.** Los 7 cambios sin evento están en 5 rutas y
   coinciden en cantidad con cambios cuyo hash repite uno previo. La hipótesis —una reversión al
   contenido vigente no es una violación de integridad, y el agente correctamente no reporta— es
   plausible, pero **la Batería 5 la contradice**: allí hay 210 cambios que repiten hash previo y
   sólo 12 sin evento. La distinción real sería entre «repite cualquier hash anterior» y «vuelve al
   hash que el agente tiene como vigente», y eso **no está verificado**.
   **No asentar la explicación en el Cap. 5 sin comprobarla.** El valor 7 sí es asentable.

2. **Ítem 42 — parcial.** Ver Tabla 14.

## Fuera del alcance de este dataset

Trece verificaciones manuales de las changes 40, 41 y 42 requieren un host con `root` y `systemd`:
capabilities efectivamente otorgadas, `statvfs` dentro del namespace del servicio, `chown` real,
supervivencia del bit setuid e `install.sh` de punta a punta. No son celdas del Cap. 5, pero sí
condición para afirmar que la remediación automática funciona en un despliegue real.
