# Handoff al frente de redacción — Guía de laboratorio v29

> **Para quién es este documento.** Para el agente o el equipo que redacta la tesis. Reúne todo lo
> que el frente de laboratorio entrega para cerrar el Capítulo 5 y los pasajes que la guía v29 manda
> corregir en los capítulos 1, 2, 3, 4, 7 y en el Anexo F. Cada número trae su fuente en el
> repositorio, así que se puede verificar sin pedir nada más.
>
> **Qué no es.** No es texto de la tesis listo para pegar, salvo donde se indica (fila STRIDE). No
> reemplaza la declaración de uso de IA, que redacta el equipo (§9).
>
> **Documento complementario.** `tesis/cierre/CAMBIOS_PARA_TESIS_V29.md` tiene la misma información en
> forma de bitácora técnica. Si algo de este documento parece contradecirlo, prevalece este, que es
> posterior.

---

## 0. Identidad del candidato y de la evidencia

| Ítem | Valor |
|---|---|
| Candidato del Capítulo 5 | **`v5.1-tesis`**, etiqueta anotada sobre el commit `404402a` (objeto de la etiqueta `525679c`). Publicada en `origin` |
| Rama publicada | `main` = `devel` = `ab8b8fd` (fusión fast-forward, 2026-10-03) |
| Candidato anterior, superado | `v5.0-tesis` (`feea81a`): reemplazado porque su drenaje midió 76,6 ev/s, por debajo del umbral de 95 ev/s (§4.3) |
| Agente | Idéntico byte a byte entre `v5.0-tesis` y `v5.1-tesis`; instalado en la VM desde la etiqueta, con el hash del árbol verificado |
| Backend | Árbol del contenedor = árbol de la etiqueta (`provenance_match=yes` en `env/procedencia.txt`) |
| Etiqueta de entrega | **`entrega-tesis` todavía no existe**: se crea al final (§10) |

### Paquetes de evidencia que cita el Capítulo 5

| Paquete | Contenido | Sello | SHA-256 del archivo `SHA256SUMS` | Commit |
|---|---|---|---|---|
| `tesis/cierre/evidencia/v5-eval-20261003T102313Z/` | Corrida unificada: suites, latencia y control (3 rep.), notificación (3 escenarios), resiliencia (3 rep.) | 112/112 OK | `34127ae2be63d0f5e47d52b5af14cec1c72417fcde62d6c2c953cf5f250dcc6c` | `995bdc8` |
| `tesis/cierre/evidencia/v5.1-complementarias-20261003T125747Z/` | B-5b, B-5 caso D, B-1 con strace, B-3 barrido | 59/59 OK | `725286a81563b27a5a9a6fca437d6438e827ed2386e8d1f34eea906fd34484fe` | `4ab5362` |
| `tesis/cierre/evidencia/v5.1-analisis-20261003/` | A-1 (bootstrap del P99) y cruce manifiesto × control (B-7) | — (derivado, reproducible) | — | `4ed2aa4` y este commit |
| `tesis/cierre/evidencia/diagnostico-notificacion-v5.0-vs-v5.1-20261003/` | Tasa de entrega absoluta en las dos versiones | — | — | `995bdc8` |
| `tesis/cierre/evidencia/diagnostico-drenaje-v5.0-20261003/` | Perfil por etapa del drenaje de `v5.0-tesis` (justifica la Change 70) | — | — | `ada3d4e` |

Para verificar un paquete: `cd <paquete> && sha256sum -c SHA256SUMS`.

### Entorno de medición (`v5-eval-20261003T102313Z/env/versions.txt`)

Docker 29.8.1, Docker Compose 5.5.1, Python 3.13.15 (backend y agente), PostgreSQL 18.3, n8n
2.17.8, Valkey 9.0.3 con AOF (`appendonly yes`, `appendfsync everysec`). La VM `fim-host` corre
Ubuntu 24.04 con el agente bajo systemd y la ruta vigilada `/srv/fim-watch`. Los relojes del
anfitrión y de la VM están sincronizados por chrony, con una guarda de ≤ 5 ms antes de medir. El
sumidero de notificación es Mailpit, alcanzado por SMTP real a través de n8n.

### Paquetes inválidos (citarlos sólo como trazabilidad, nunca como resultado)

| Paquete | Por qué se invalidó |
|---|---|
| `v5-eval-20261002T215744Z-replay-comandos/` | La purga del arnés borraba el cursor del stream `commands`; el agente reprocesó 209.619 comandos viejos y el P99 subió a 112 s |
| `invalidos/v5-eval-20261003T055512Z-resiliencia-sin-corte/` | La guarda de procedencia de la batería 5 corría en un subshell y la batería moría antes del corte |

Cada uno tiene un `LEEME.md` con la causa. Los dos fueron defectos del **arnés**, no del producto.

---

## 1. Resultados del Capítulo 5

Numeración de ítems según `tesis/dataset_cap5.md`. Los valores anteriores (`v4.0-tesis` o el candidato
histórico) se citan sólo para comparar.

### 1.1 Suites automatizadas (`v5-eval-…/suites/*.xml`)

| Suite | Tests | Fallos | Errores | Omitidos |
|---|---|---|---|---|
| Agente | 811 | 0 | 0 | 1 |
| Backend | 1.106 | 0 | 0 | 4 |
| Frontend | 298 | 0 | 0 | 0 |

### 1.2 Latencia de detección — Batería 3 / B-1 (`v5-eval-…/latencia/run-0N/`)

Generador: `--rate 0.2778 --count 500 --mix 20/70/10 --critical-frac 0.2`, unos 30 minutos por
repetición. Semillas 20261001, 20261002 y 20261003. Latencia = `received_at − detected_at`.

| Repetición | Eventos recibidos | Media | P50 | P95 | P99 | Mín | Máx | Negativos |
|---|---|---|---|---|---|---|---|---|
| run-01 | 500 | 28,73 ms | 29,44 ms | 34,01 ms | 40,58 ms | 11,58 ms | 139,91 ms | 0 |
| run-02 | 495 | 29,70 ms | 31,21 ms | 35,51 ms | 39,53 ms | 12,68 ms | 142,48 ms | 0 |
| run-03 | 499 | 32,83 ms | 33,94 ms | 40,02 ms | 42,19 ms | 15,91 ms | 137,66 ms | 0 |
| **Combinado** | **1.494** | 30,42 ms | **31,00 ms** (ítem 44) | 37,84 ms | **41,73 ms** (ítem 46) | 11,58 ms | 142,48 ms | 0 |

**A-1. P99 con IC95 por bootstrap** (`scripts/p99_bootstrap.py`, 10.000 remuestreos, semilla 20261001,
percentil con interpolación lineal; salida en `v5.1-analisis-20261003/a1_p99_bootstrap.tsv`):

| Serie | n | P99 | IC95 |
|---|---|---|---|
| run-01 | 500 | 40,578 ms | [36,843; 135,106] ms |
| run-02 | 495 | 39,529 ms | [37,159; 40,468] ms |
| run-03 | 499 | 42,192 ms | [41,488; 42,933] ms |
| **Combinado** | **1.494** | **41,732 ms** | **[40,531; 42,323] ms** |

**Cómo redactarlo (§3.6 y §5):**
- Informar el P99 combinado con su IC95 **y** las tres repeticiones por separado.
- El IC95 de run-01 llega a 135 ms porque, con n = 500, el P99 queda determinado por unas 5
  observaciones extremas, y run-01 tiene pocas muestras cercanas a 140 ms. Declarar en §3.6 que el
  bootstrap del P99 con n ≈ 500 es aproximado por esa razón.

**Denominador: eventos esperados según la semántica del producto, no 500.**
- El patrón `revertido` del generador modifica un archivo y, 3,6 s después, lo devuelve exactamente a
  su contenido aprobado.
- El agente descarta esa vuelta con `decision_suppressed / matches_active_baseline` (D14/RN-112:
  volver al contenido aprobado no es un cambio).
- Cada faltante se verificó caso por caso con la traza causal del agente
  (`diagnostico/traza_lat_run-0N.jsonl`): todos son reversiones a la línea base y **ninguno es una
  detección perdida**.

Ítem 48 (eventos perdidos por la plataforma): **0 detecciones perdidas**. Los 0, 5 y 1 faltantes son
supresiones por diseño. Así deben informarse; no corresponde informar «6 de 1.500 perdidos».

**Comparación:** P99 de `v4.0-tesis` ≈ 46,3 ms; de `v5.0-tesis`, 40,5 a 46,0 ms; de `v5.1-tesis`,
39,5 a 42,2 ms. La mediana bajó unos 8 ms respecto de `v5.0-tesis` (de 37,5 a 29,4 ms en run-01),
coherente con la ingesta por lote más liviana de la Change 70.

### 1.3 Grupo de control por escaneo periódico — Batería 7 / B-2 (`v5-eval-…/control/run-0N/`, análisis en `v5.1-analisis-20261003/control_run-0N.txt`)

El control corre `control_hashing.py --loop --interval 900` (escaneo recursivo de `/srv/fim-watch`
cada 15 min). La fase se deriva de la semilla, `random.Random(seed).randrange(900)`: 243, 164 y 28 s.
Toma la línea base inmediatamente y espera la fase antes del primer escaneo periódico. Usa un CSV
nuevo por corrida y ventana idéntica a la latencia. Cruce con `scripts/analisis_control.py`,
criterio `primer_cambio`.

| Ítem | run-01 | run-02 | run-03 |
|---|---|---|---|
| Cambios reales (manifiesto) | 500 | 500 | 500 |
| Detecciones del control | 72 | 98 | 94 |
| 45 — Mediana de latencia del control | 514.159,9 ms (≈ 8,6 min) | 477.666,4 ms (≈ 8,0 min) | 537.865,7 ms (≈ 9,0 min) |
| 47 — P99 de latencia del control | 897.475,8 ms (≈ 15,0 min) | 896.997,4 ms | 894.526,8 ms |
| Media / desvío (ddof=1) | 495.241,5 / 290.251,3 ms | 492.259,0 / 287.948,0 ms | 499.585,5 / 280.729,8 ms |
| Mín / máx | 8.324,9 / 897.529,3 ms | 4.267,2 / 897.070,3 ms | 5.070,7 / 897.875,2 ms |
| 49 — Eventos perdidos por el control | **428/500 (85,6 %)** | **402/500 (80,4 %)** | **406/500 (81,2 %)** |
| — por colapso / no detección | 179 / 249 | 252 / 150 | 278 / 128 |
| — por patrón: simple / colapsado / revertido / efímero | 271 / 70 / 67 / 20 | 246 / 70 / 66 / 20 | 249 / 68 / 69 / 20 |
| 50 — Factor de mejora (mediana control ÷ mediana FIM) | 17.464,1× | 15.305,4× | 15.848,9× |
| — Factor sobre el P99 | 22.117,3× | 22.692,1× | 21.201,3× |

**Cambio respecto del texto anterior:**
- El ítem 50 histórico era 45.421,7× con una sola réplica determinista. Ahora hay **tres réplicas con
  fase aleatoria**, y el factor queda entre 15.305× y 17.464× sobre la mediana.
- La guía v29 (L-12) pide justamente esto: que el control deje de ser una réplica determinista.
  Informar el rango o la media de las tres réplicas y declarar qué métrica usa el cociente.
- La pérdida del control (80 a 86 %) es del mismo orden que la histórica (79,0 %).

### 1.4 Notificación — Batería 4 / B-3 (`v5-eval-…/notificacion/`)

Un publicador sintético inyecta 1.000 eventos firmados por escenario contra Mailpit vía n8n. El límite
de ingesta es el del producto (1,6667 tokens/s, ráfaga de 3.000), con **0 eventos `rate_limited`** en
los tres escenarios. Se registran dos intervalos: `ms_aceptacion = channel_accepted_at − received_at`
(el intervalo del protocolo) y `ms_entrega = delivered_at − received_at`.

| Escenario | Intervalo | n | Media | P50 | P95 | P99 | Máx |
|---|---|---|---|---|---|---|---|
| secuencial (conc. 1) | aceptación | 1.000 | 16.193,6 ms | 16.245,5 ms | 28.643,2 ms | 29.469,4 ms | 29.703,9 ms |
| secuencial | entrega | 1.000 | 16.201,5 ms | 16.250,6 ms | 28.645,4 ms | 29.472,7 ms | 29.705,4 ms |
| conc. 50 | aceptación | 1.000 | 16.108,5 ms | 16.184,7 ms | 28.611,6 ms | 29.640,6 ms | 29.834,1 ms |
| conc. 50 | entrega | 1.000 | 16.114,6 ms | 16.187,7 ms | 28.614,3 ms | 29.642,4 ms | 29.836,5 ms |
| conc. 100 | aceptación | 1.000 | 16.209,1 ms | 16.389,5 ms | 28.543,3 ms | 29.534,6 ms | 29.704,3 ms |
| conc. 100 | entrega | 1.000 | 16.215,4 ms | 16.392,4 ms | 28.545,4 ms | 29.536,7 ms | 29.705,7 ms |

**Interpretación obligatoria (si no, la tabla se lee mal):**
1. **Es drenaje de cola, no latencia de una notificación aislada.** Los 1.000 eventos entran en
   menos de 2 s, y el P99 mide cuánto tarda en vaciarse esa cola.
2. **El P99 subió de unos 23 s (`v5.0-tesis`) a unos 29,5 s (`v5.1-tesis`), y no es una regresión.**
   Se midió con timestamps absolutos, el mismo laboratorio y sólo la imagen del backend cambiada
   (`diagnostico-notificacion-v5.0-vs-v5.1-20261003/LEEME.md`):

   | Imagen | Absorción de los 1.000 eventos | Primer `received_at` → último `delivered_at` | Tasa de entrega |
   |---|---|---|---|
   | `v5.0-tesis` | 12,79 s | 36,16 s | 27,7 notif/s |
   | `v5.1-tesis` | 5,16 s / 5,92 s | 36,55 s / 34,70 s | 27,4 / 28,8 notif/s |

   La entrega tiene la misma tasa en las dos versiones, unas 28 notif/s. El intervalo arranca en
   `received_at`; con la ingesta más rápida los eventos se reciben antes y la espera en la cola
   queda dentro del intervalo. **Comparar candidatos por la tasa de entrega, no por el P99.**
3. **El límite está aguas abajo (n8n → SMTP).** B-3 lo confirma (§1.8): subir la concurrencia de
   entregas de 8 a 64 no mejora nada.
4. Mailpit retiene sólo 500 mensajes; el conteo de entregas sale de la base (`alerts.delivered_at`).

### 1.5 Resiliencia: corte de Valkey de 5 minutos — Batería 5 / B-4 (`v5-eval-…/resiliencia/run-0N/`)

Valkey se detiene, el agente sigue generando 3.000 cambios durante 5 min y los encola, Valkey se
restaura y se mide el drenaje. El backend no se recrea durante el corte: Id, `StartedAt` y
`RestartCount` son iguales antes y después en las tres repeticiones.

| Métrica | run-01 | run-02 | run-03 |
|---|---|---|---|
| Eventos encolados al final del generador | 2.998 | 2.998 | 2.997 |
| Eventos persistidos / únicos / duplicados | 2.998 / 2.998 / 0 | 2.998 / 2.998 / 0 | 2.997 / 2.997 / 0 |
| Descartados por el agente | 0 | 0 | 0 |
| **A-2: fuera de orden** (`scripts/fuera_de_orden.py`) | **0** (0,0 %) | **0** | **0** |
| Regresiones adyacentes | 0 | 0 | 0 |
| **A-3: reconexión del agente** (t0 → primer `xadd`) | 0,001 s | 0,629 s | 0,871 s |
| **A-3: tramo sin consumo** (primer `xadd` → primer `received_at`) | 0,692 s | 0,756 s | 0,010 s |
| **A-3: consumo** (primer → último `received_at`) | 25,584 s | 23,948 s | 25,511 s |
| **A-3: drenaje total** | 26,277 s | 25,334 s | 26,392 s |
| **Caudal de consumo** (`consumption_ev_s`) | **117,2 ev/s** | **125,2 ev/s** | **117,5 ev/s** |
| Backend reiniciado durante el corte | no | no | no |

**Cómo redactarlo:**
- **Usar el caudal de consumo, no `throughput_ev_s`.** El log de la batería también trae
  `drain_duration_s` de unos 45,8 s y `throughput_ev_s` de unos 65,5. Esos dos números incluyen el
  intervalo de sondeo del propio arnés: los últimos ~20 s pasan entre el último `received_at` y el
  instante en que el arnés comprueba que la cola quedó vacía. El dato correcto es la ventana de
  consumo de A-3. Las tres repeticiones superan el umbral de 95 ev/s fijado en D87/RN-181.
- **Fuera de orden: 0 en las tres repeticiones; en `v4.0-tesis` run-03 hubo 359.** Lo corrigió la
  Change 61, con FIFO estricto tras la reconexión. La definición de A-2 cuenta un evento si su
  `detected_at` es menor que el máximo ya recibido. Con esa misma definición, el script reproduce los
  359 sobre `v2-eval-20260923T215624Z/resiliencia/run-03/eventos.csv`; si la tesis define «fuera de
  orden» de otra forma, alinear el texto a esta.
- **L-9a, el tramo de ~33 s sin consumo.** En `v4.0-tesis` el tramo sin consumo duraba unos 33 s;
  ahora dura menos de 1 s. La causa estaba en el **arnés**: `lab/bateria5.sh` restauraba con
  `up -d valkey backend` usando un conjunto de archivos compose distinto del que había levantado el
  backend, y eso lo recreaba a mitad del corte. Corregido; la recreación ahora invalida la repetición.
  B-4 lo confirma con el Id del contenedor y el `RestartCount` sin cambios. **En §5.5 informar que la
  causa fue el arnés y que, con el arnés corregido, el tramo desaparece.**

### 1.6 B-5b: reconciliación al arrancar (`v5.1-complementarias-…/b5b_reconciliacion/`)

Con 10 archivos en la línea base, se detiene el agente, se modifican 4, se borran 3, se borran y
recrean con bytes idénticos otros 3, y se arranca el agente. Diez repeticiones.

| Resultado | Valor |
|---|---|
| Repeticiones conformes | **10/10** |
| Por repetición | 4 `file_modified` + 3 `file_deleted`, todos con `detected_offline=true` |
| Archivos recreados idénticos | 0 eventos (correcto: el contenido coincide con la línea base) |
| Eventos espurios | 0 |
| Journal del agente | `baseline.reconcile.complete` deleted=3 modified=4 unchanged=3 errors=0 |

Sostiene el hallazgo L-3 (§3.1).

### 1.7 B-5 caso D: escritura por `mmap` con demora después de `close(fd)` (`v5.1-complementarias-…/b5_mmap_casoD/`)

Secuencia: abrir, mapear, cerrar el fd, esperar d ms, escribir sobre el mapeo, `msync` y `munmap`.
Diez repeticiones por demora; testigo C (escritura convencional) 10/10.

| d | Detectados | `evento_sin_cambio` | `sin_evento` | `detected_at` − inicio: mín / mediana / máx |
|---|---|---|---|---|
| C (testigo) | 10/10 | 0 | 0 | 0,8 / 1,0 / 1,3 ms |
| 0 ms | 10/10 | 0 | 0 | 12,1 / 13,8 / 15,5 ms |
| 5 ms | 10/10 | 0 | 0 | 10,0 / 17,9 / 21,1 ms |
| 10 ms | 10/10 | 0 | 0 | 13,7 / 23,2 / 26,6 ms |
| 20 ms | 10/10 | 0 | 0 | 24,4 / 33,7 / 34,0 ms |
| 50 ms | 10/10 | 0 | 0 | 54,5 / 63,2 / 64,7 ms |
| 100 ms | 10/10 | 0 | 0 | 105,3 / 114,1 / 116,8 ms |
| 500 ms | 10/10 | 0 | 0 | 506,7 / 512,6 / 517,0 ms |

**70/70 detectados, con `hash_detected` igual al contenido final. No se midió ninguna ventana de
evasión.** El `detected_at` sigue a la escritura sobre el mapeo, no al `close(fd)`. Ver la
corrección de §1.7 y §2.6 en §3.3.

### 1.8 B-1 con strace: generador instrumentado (`v5.1-complementarias-…/b1_strace/`)

125 operaciones (25 creaciones y 100 modificaciones a 10/s), semilla 20261001; 1.036 líneas de strace
(`-f -ttt -T -yy -e trace=close,openat,write`).

| Resultado | Valor |
|---|---|
| Patrón por modificación | exactamente 1 `openat`, 1 `write` y 1 `close` en 100/100; creaciones, también 25/25 |
| Escrituras cortas | 0 (el retorno coincide con los bytes del manifiesto) |
| `close` después de `open` | mediana de 0,84 ms, máximo de 1,31 ms |
| Eventos en la base | 100 `file_modified` + 25 `file_created` = 125, ninguna operación sin evento |

### 1.9 B-3: barrido de `notify_max_concurrent_deliveries` (`v5.1-complementarias-…/b3_barrido/`)

100 notificaciones por valor, concurrencia del publicador 100. Valores de `ms_aceptacion`:

| Límite | Media | P50 | P95 | P99 | Máx |
|---|---|---|---|---|---|
| 8 | 2.225,1 ms | 2.221,5 ms | 3.778,0 ms | 3.831,8 ms | 3.837,1 ms |
| 16 | 2.318,6 ms | 2.325,8 ms | 3.698,0 ms | 3.819,0 ms | 3.824,6 ms |
| 32 (valor del producto) | 2.540,7 ms | 2.599,0 ms | 3.747,1 ms | 3.817,3 ms | 3.892,4 ms |
| 64 | 2.791,3 ms | 2.546,0 ms | 3.718,3 ms | 3.751,8 ms | 3.758,1 ms |

Subir el límite no mejora nada: el P99 queda en unos 3,8 s con los cuatro valores y la media incluso
sube. El factor que acota la cadena está aguas abajo (n8n → SMTP), coherente con las ~28 notif/s de
§1.4. `ms_entrega` supera a `ms_aceptacion` en 4 a 5 ms de media.

### 1.10 A-4: sellado

Ver la tabla de paquetes en §0. Los dos paquetes de medición verifican completos con
`sha256sum -c SHA256SUMS`: 112/112 y 59/59.

---

## 2. Defectos del producto corregidos (§4 y §7.6)

Changes OPSX aplicadas, verificadas y archivadas con la integridad de specs comprobada antes y
después de cada archivo; al cierre, 58 specs y 448 requisitos. Las decisiones viven en los appendices
de `docs/arquitectura_stack.md` (D79–D88) y `docs/reglas_de_negocio.md` (RN-173–RN-182).

| Guía | Change | Qué se corrigió | Decisión |
|---|---|---|---|
| L-2 | 61 `agent-publisher-fifo-reconnect` | FIFO estricto tras la reconexión: cola separada de eventos nunca transmitidos, la pasada se corta ante el primer error, sondeo de 0,5 s con atraso, el replay de `rehydrate` va detrás del backlog. Explica los 359 fuera de orden de `v4.0-tesis`; ahora son 0 (§1.5) | D79/RN-173 |
| L-3 | 62 `agent-offline-reconcile-on-start` | Reconciliación de la línea base contra el disco al arrancar: reporta lo modificado, borrado o creado con el agente detenido, marcado `detected_offline: true` (§3.1) | D80/RN-174 |
| L-4 | 63 `agent-restore-verify-from-disk` | La verificación posterior a la restauración relee el disco (`O_NOFOLLOW`) en **ambos** caminos, automático y del operador; antes comparaba el buffer consigo mismo. Se retira el residual §1 | D81/RN-175 |
| L-5 a, b, d | 64 `quarantine-baseline-preservation` | La cuarentena conserva la versión aprobada (estado de línea base `quarantined`), suprime su propio eco y tiene una sola implementación. Se retira el residual §9 | D82/RN-176 |
| L-5 c | 65 `quarantine-release-command` | Comando firmado de liberación con modos `restore_original` (= aprobar), `restore_baseline` y `discard`; endpoint auditado y botón en el detalle del evento | D83/RN-177 |
| L-6 | 66 `backend-schema-migrations-registry` | Registro `schema_migrations`, `scripts/migrar.py`, y el backend se niega a arrancar ante migraciones pendientes | D84/RN-178 |
| L-7 | 67 `ingest-token-bucket-rate-limit` | Límite de ingesta como token bucket por agente: 100 ev/min sostenidos, ráfaga de 3.000 (cubre el replay de la batería 5). Las baterías corren con los valores del producto | D85/RN-179 |
| L-8 | 68 `agent-secret-wrap-at-rest` | El secreto HMAC de cada agente se guarda cifrado en reposo con AES-256-GCM (`v1:`, AAD = `agent_id`); la clave vive fuera de la base, en el volumen `backend_secrets` | D86/RN-180 |
| L-9 | 69 `ingest-drain-resilience-and-throughput` | Timeouts del cliente Valkey, recuperación de `NOGROUP` (eventos y `command_ack`), AOF, caché de autenticación y ACK por lote | D87/RN-181 |
| L-9 | 70 `ingest-batched-persistence` | Reapertura del drenaje (§4.3). Fase A: un único cliente HTTP de larga vida para las entregas a n8n, con TLS verificado y el contexto construido una sola vez. Fase B: una transacción y un COMMIT por lote del consumidor, que preserva FIFO, la cadena `superseded`, la ausencia de duplicados y una alerta por evento | D87/RN-181 (ampliación 2026-10-03) |

**Decisiones de producto del equipo** (para §4 y la Tabla 8):
- La máquina de estados de eventos **no cambia** (RN-11, RN-12, RN-72): un rechazo con cuarentena
  sigue en `rejected`, y la cuarentena se expone como el campo derivado `quarantine_state`
  (`none | quarantined | released | discarded`). Esto reemplaza la alternativa de la guía L-5(d) de
  mover el rechazo a `quarantined`.
- Liberar con `restore_original` **equivale a aprobar** el contenido cuarentenado.
- L-10 se descarta: **se ratifica RN-94** (`audit_log` no se depura nunca), D88/RN-182.

---

## 3. Texto nuevo o corregido por sección

### 3.1 Hallazgo L-3: §2.6 o §4.3 (diseño) y §5 (resultado)

Responde a la pregunta obvia del tribunal: «¿qué pasa si alguien detiene el agente, modifica un archivo
y lo vuelve a arrancar?».
- **Antes:** nada. El cambio quedaba invisible, porque el agente sólo veía eventos del kernel con él
  corriendo.
- **Ahora (Change 62):** al arrancar, el agente reconcilia la línea base contra el disco y reporta
  cada diferencia con `detected_offline: true`.
- **Resultado medido:** B-5b, 10/10 (§1.6).
- **Límite que se mantiene:** hay una ventana entre la reconciliación y la instalación de las marcas
  de fanotify; un archivo de más de 10 MiB sin modificación aprobada se reporta de nuevo en cada
  reinicio.

### 3.2 L-9a: §5.5

Ver §1.5. El tramo de unos 33 s sin consumo fue un defecto del arnés, que recreaba el backend a mitad
del corte, y no del producto. Con el arnés corregido el tramo queda por debajo de 1 s.

### 3.3 §1.7 y §2.6: la limitación por `mmap`

La tesis presenta como limitación potencial de evasión una escritura sobre un mapeo hecha después de
`close(fd)`. El caso D no la reproduce con ninguna demora hasta 500 ms: 70/70 detectados (§1.7). Una
explicación probable, que **no se verificó en el código del kernel en este trabajo**: el mapeo
mantiene su propia referencia al archivo, así que el `close(fd)` no es el último cierre y
`FS_CLOSE_WRITE` se emite en el `munmap`, posterior a la escritura. Coincide con que `detected_at`
siga a d. Hay dos formas de redactarlo; elegir una:

1. **Retirar la limitación como hallazgo medido** e informar la cota: «0 evasiones en 70 intentos con
   d ≤ 500 ms».
2. **Restringirla** a un proceso que escribe sobre el mapeo y **no** hace `munmap` (por ejemplo, un
   proceso de larga vida que deja el mapeo abierto). Ese escenario **no se midió** y así debe
   declararse.

### 3.4 Tablas 24 y 25 y §4.2: retención (RN-94)

- `audit_log` **no se depura nunca** (RN-94, ratificado en D88/RN-182). La guía v29 proponía depurarlo
  (L-10); el equipo decidió no hacerlo.
- `rejected_events_audit` **sí se depura**: los registros de más de 90 días los borra una tarea
  periódica. La implementación está en `purge_rejected_events_audit`
  (`backend/app/modules/events/service.py:767`) y el plazo en `rejected_events_retention_days`
  (`backend/app/core/config.py:174`, valor por defecto 90), D65/RN-159.
- **La Tabla 24 dice que no se encontró depuración automática de `rejected_events_audit`, y eso es
  falso**: corregirlo y alinear la Tabla 25 y §4.2.

### 3.5 Tabla 3 (STRIDE): fila nueva, texto listo para pegar

| Campo | Contenido |
|---|---|
| **Categoría STRIDE** | Divulgación de información (I) |
| **Activo** | Secreto compartido HMAC de cada agente (`agents.shared_secret_hex`) |
| **Amenaza** | La exfiltración de la base de datos (volcado de `pg_dump`, respaldo, réplica de lectura o volumen `pg_data` extraído) permite a un atacante firmar mensajes como cualquier agente (eventos, heartbeats, ACKs) y firmar comandos hacia cualquier agente (`rule_sync`, `baseline_update`, restauraciones), sin tocar el backend ni la PKI. Antes de D86 el secreto se guardaba en claro y no existía revocación asignable (`AgentStatus.revoked` se consulta pero ningún código lo asigna), de modo que un secreto filtrado no podía invalidarse desde el producto. |
| **Mitigación** | El secreto se persiste cifrado con AES-256-GCM (formato `v1:`, nonce aleatorio de 12 bytes por escritura) con el `agent_id` como dato asociado autenticado, de modo que un valor copiado de la fila de un agente a la de otro no descifra. La clave de envoltura (32 bytes) vive fuera de la base, en el volumen nombrado `backend_secrets`: la genera `certs-init` (único generador, nunca sobrescribe), modo `0400`, dueño del usuario del backend; la montan sólo `certs-init` (escritura) y el backend (sólo lectura). El backend no arranca si la clave falta, es ilegible, no mide 32 bytes o tiene permisos más laxos que `0400`/`0600`. Los secretos existentes se envuelven en el primer arranque, sin intervención manual (D86/RN-180). |
| **Límites declarados** | (1) No protege contra el compromiso del host ni del proceso del backend: quien lee la memoria del backend o el volumen `backend_secrets` obtiene la clave. (2) No protege contra un respaldo conjunto de la base y de la clave: `backend_secrets` debe respaldarse por separado de `pg_data`. (3) Sin rotación de la clave de envoltura (el prefijo `v1:` queda reservado para una versión futura). (4) Sin revocación de agentes: asignar `AgentStatus.revoked` queda fuera de D86. (5) La pérdida de la clave obliga a re-bootstrapear todos los agentes; no hay vuelta atrás a una imagen anterior sin re-bootstrap (no se provee reescritura a texto plano). |
| **Referencias** | D86/RN-180 (`docs/arquitectura_stack.md`, `docs/reglas_de_negocio.md`), Change 68 `agent-secret-wrap-at-rest`, procedimiento operativo en `docs/despliegue_servidor_remoto.md` §12 |

Fuente: `openspec/changes/archive/2026-10-02-agent-secret-wrap-at-rest/stride-handoff.md`.

### 3.6 §3.6: método estadístico

- El bootstrap del P99 con n ≈ 500 es aproximado: depende de unas 5 observaciones extremas. Por eso se
  informan el combinado y cada repetición (§1.2).
- El grupo de control tiene ahora tres réplicas con fase aleatoria derivada de la semilla (L-12), así
  que el factor de mejora es un rango y no un valor único (§1.3).
- Denominador de la latencia: eventos esperados según la semántica del producto (§1.2).

---

## 4. Para §7.6: discusión y límites

### 4.1 Límites declarados que quedan en pie (como límites definitivos, no como pendientes)

1. **Stream `commands` sin retención.** Ningún `XADD` del backend fija `MAXLEN` y nada recorta el
   stream, que en el laboratorio acumuló 209.619 entradas. Un agente que arranca sin `state.json`,
   por reinstalación o pérdida del estado, lo reprocesa completo desde `0-0`, como prescribe RN-109.
   En la corrida abortada eso saturó la publicación y llevó el P99 a 112 s
   (`v5-eval-20261002T215744Z-replay-comandos/LEEME.md`).
2. **Compactación y clave foránea de alertas.** La compactación de cadenas `superseded` (RN-98) puede
   borrar un evento que tiene alerta, y `alerts.event_id` no tiene `ON DELETE`. Una ruta con más de 10
   eventos reemplazados cuyo evento más antiguo tiene alerta queda trabada con
   `ForeignKeyViolation`. La reproducción está en
   `openspec/changes/archive/2026-10-03-ingest-batched-persistence/follow-ups.md`. Las baterías no lo
   disparan (unos 5 cambios por ruta).
3. Sin rotación de la clave de envoltura; la pérdida de la clave obliga a re-bootstrapear todos los
   agentes.
4. Sin vuelta atrás del agente sin limpiar las entradas `quarantined`; los artefactos de cuarentena
   anteriores a la Change 64 no se pueden liberar.
5. Ventana entre la reconciliación y la instalación de las marcas de fanotify.
6. Los archivos de más de 10 MiB sin modificación aprobada se reportan de nuevo en cada reinicio.
7. Un archivo recreado con el contenido aprobado pero con otros permisos no se reporta: el detector
   compara hashes.
8. `mmap` sin `munmap` en un proceso de larga vida: no medido (§3.3).

### 4.2 Hallazgos de operación

- **AOF de Valkey.** Activar AOF sobre un volumen que sólo tiene `dump.rdb`, en Valkey 9.0.3, **no
  carga el snapshot** y se pierden el stream y el grupo de consumidores. La migración segura es
  `CONFIG SET appendonly yes` en el servidor viejo, esperar a que termine la reescritura y recién
  entonces recrear el contenedor. Así se aplicó en el laboratorio (`XLEN` conservado) y está
  documentado en el design de la Change 69.
- **Bases existentes y el registro de migraciones (Change 66).** Hay que correr una sola vez
  `migrar.py --marcar-hasta 22` y después `migrar.py`; si no, el backend nuevo no arranca.

### 4.3 La reapertura del drenaje: un ejemplo de «medir antes de optimizar»

Vale la pena contarlo en §7.6 porque muestra el método:
1. La Change 69 estimó unos 145 ev/s con un banco que reemplazaba la cadena de notificación por un
   stub (191,5 ev/s), y por eso descartó el INSERT agrupado.
2. En el laboratorio, `v5.0-tesis` midió **76,6 ev/s**, por debajo del umbral de 95 acordado de
   antemano.
3. El perfil por etapa ubicó el 98 % del tiempo en la ingesta (12,3 ms por evento), y el backlog del
   stream mostró que el cuello estaba en el backend
   (`diagnostico-drenaje-v5.0-20261003/`).
4. **La primera hipótesis, el COMMIT por evento, quedó refutada por medición:** con
   `synchronous_commit=off` el caudal no cambió. La causa medida era un cliente HTTP, con su
   contexto TLS, creado en cada entrega de notificación.
5. Banco con la notificación real: 62,0 ev/s de base, 86,0 con la fase A (aún bajo el umbral) y
   175–179 con A+B. En el laboratorio, sobre `v5.1-tesis`: **117 a 125 ev/s** (§1.5).
6. La mejora en el laboratorio (×1,5 a ×1,6) es mucho menor que en el banco (×2,9). Ahora el límite
   de punta a punta es la entrega de notificaciones, unas 28 notif/s (§1.4).

### 4.4 Defectos del arnés encontrados al medir (todos en `lab/`, ninguno en el producto)

1. La purga borraba `state.json` y con él el cursor del stream `commands` (`0880567`).
2. El publicador de la batería 4 leía el secreto del agente como hexadecimal, pero desde la Change 68
   está cifrado (`c9e2dde`).
3. El resumen de notificación reutilizaba el nombre de la variable del directorio y fallaba después
   del primer escenario (`4a46d10`).
4. La guarda de procedencia de la batería 5 corría dentro de un pipe y después dentro de `$(...)`; las
   dos cosas abren un subshell, así que la variable no llegaba y la batería moría antes del corte sin
   escribir nada (`41bf3e7`, `37f1c1a`).
5. `lab/bateria5.sh` recreaba el backend a mitad del corte (L-9a, §1.5).

---

## 5. Cambios de redacción ya conocidos (de la v26)

- **D1, `tesis/dataset_cap5.md`, Tabla 12.** Los escenarios se rotulan 1, 50 y 100 op/s, no «50
  concurrentes» y «100 concurrentes». Ya aplicado en el repositorio.
- **D2, `scripts/README.md`.** La semilla 20260818 es sólo de ejemplo. Ya aplicado.
- **Réplica del control (L-12).** Las semillas pasan a ser 20261001, 20261002 y 20261003; la fase del
  control se deriva de cada semilla (243, 164 y 28 s).

---

## 6. Reproducibilidad (para el Anexo F)

- El arnés está versionado en `lab/`. Reemplazar en la tesis **toda** mención a `~/fim-lab` por `lab/`.
- La corrida unificada se lanza con `TAG=v5.1-tesis bash lab/corrida_unificada.sh`. Sus guardas
  abortan en estos casos:
  - procedencia: HEAD no desciende de la etiqueta, o `agent/`, `backend/`, `frontend/` o `n8n/`
    difieren de ella;
  - esquema: `migrar.py --verificar` falla;
  - relojes: desvío mayor a 5 ms;
  - sumidero: Mailpit no responde;
  - línea base no purgada;
  - límite de ingesta distinto al del producto;
  - AOF desactivado.
- Análisis: `scripts/p99_bootstrap.py` (A-1), `scripts/fuera_de_orden.py` (A-2),
  `scripts/descomponer_drenaje.py` (A-3), `scripts/analisis_control.py` (B-7) y
  `scripts/analisis_mmap.py` (B-5).

---

## 7. Anexo F: correcciones puntuales

1. **Registro de uso de IA.** `tesis/cierre/REGISTRO_USO_IA.md` no existe y **no se crea**. El
   inventario de hechos es `tesis/cierre/INSUMO_REGISTRO_USO_IA.md`; el Anexo F cita ese archivo, y
   la declaración la redacta el equipo (§9).
2. **`VERIFICACION_CITAS.md`.** No existe en ninguna rama ni hay un documento equivalente: **retirar
   la mención**.
3. **Paquetes citados que estaban fuera del repositorio** (`v10-closure-*/{backlog,lanes,m8,m9}`,
   `us02-us20-us31-*`, `us03-us16-us17-us25-isolated-*`): ahora están versionados (`1eb8681`).
4. **`tesis/resultados/`** sigue fuera del repositorio a propósito, porque se archiva junto con las
   planillas. Toda cita como ruta del repositorio (por ejemplo `tesis/resultados/entorno.txt`) debe
   pasar a citar la planilla.
5. **`scripts/verify_experiments.py`** no existe en el repositorio: retirar la cita o reemplazarla por
   el script vigente.
6. **Falsos positivos del verificador de rutas** contra la v26 (`docs/18`,
   `docs/concepts/tracing-policy/selectors`, `agent/baseline`): son fragmentos de URLs o de texto, no
   rutas. Reformularlos para que el verificador no los tome como rutas, o confirmar que no lo son al
   correr la verificación final.
7. **Citar sólo la etiqueta `entrega-tesis`** (§10), nunca `devel` ni un hash suelto.

---

## 8. Lista de verificación para el redactor

- [ ] Cap. 5: valores de §1.2 a §1.9 con sus fuentes; en latencia, el denominador «eventos esperados»
      (§1.2).
- [ ] Cap. 5: el P99 de notificación como drenaje de cola, comparado por tasa de entrega (§1.4).
- [ ] Cap. 5: la resiliencia con el caudal de consumo de A-3, **no** con `throughput_ev_s` (§1.5).
- [ ] Cap. 5: el factor de mejora del control como rango de tres réplicas (§1.3).
- [ ] §5.5: L-9a como defecto del arnés (§3.2).
- [ ] §2.6/§4.3 y §5: el hallazgo L-3 (§3.1).
- [ ] §1.7 y §2.6: la limitación `mmap`, retirada o restringida (§3.3).
- [ ] Tablas 24 y 25 y §4.2: retención (§3.4).
- [ ] Tabla 3: la fila STRIDE (§3.5).
- [ ] §3.6: el método estadístico (§3.6).
- [ ] §4 y §7.6: defectos corregidos (§2), límites (§4.1), hallazgos de operación (§4.2) y la
      reapertura del drenaje (§4.3).
- [ ] Anexo F: los siete puntos de §7.
- [ ] Declaración de uso de IA, redactada por el equipo (§9).
- [ ] Verificación de rutas en cero y etiqueta `entrega-tesis` (§10).

---

## 9. Declaración sobre el uso de IA

La redacta el equipo: una declaración sobre el uso de IA escrita por una IA no se sostiene ante la
primera pregunta del tribunal. El inventario de hechos (qué hizo la IA, sobre qué artefacto y cómo se
verifica) está en `tesis/cierre/INSUMO_REGISTRO_USO_IA.md`. Las sesiones de laboratorio de octubre de
2026 suman estos hechos para el inventario:
- la implementación asistida de las Changes 61 a 70 vía OPSX, con verificación independiente de la
  Change 70;
- la ejecución y el análisis de las baterías sobre `v5.0-tesis` y `v5.1-tesis`;
- la corrección de los defectos del arnés de §4.4.

Todo quedó en commits identificables de `main`.

---

## 10. Cierre: etiqueta `entrega-tesis`

Cuando exista el `.docx` definitivo:

```bash
python3 scripts/verificar_rutas_tesis.py Tesis_vNN.docx main     # iterar hasta 0 faltantes
git tag -a entrega-tesis -m "Versión entregada de la tesis" main
python3 scripts/verificar_rutas_tesis.py Tesis_vNN.docx entrega-tesis   # debe dar 0 faltantes
git push origin entrega-tesis
```

El Anexo F cita sólo `entrega-tesis`. La etiqueta se crea **después** de las correcciones de texto,
para que apunte al árbol que la tesis efectivamente cita.
