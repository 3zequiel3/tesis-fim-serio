# scripts/ — arnés de medición del Capítulo 5

Estos scripts **no son código de producto**: son el arnés experimental que produce
los archivos crudos exigidos por el Anexo F. El plan que los especifica es
[`docs/plan_medicion_cap5.md`](../docs/plan_medicion_cap5.md); la auditoría de qué
existe y qué falta está en [`docs/entrega_valores_cap5.md`](../docs/entrega_valores_cap5.md).

Ninguno requiere root ni dependencias externas: solo Python 3 de la stdlib
(y `curl` + `python3` en los de bash, igual que `setup-agent.sh`).

| Script | Precondición | Ítems que alimenta |
|---|---|---|
| [`generador_carga.py`](generador_carga.py) | **P2** | 9, 37, 48, 54 + repetibilidad de las Baterías 3, 4, 5 y 7 |
| [`control_hashing.py`](control_hashing.py) | **P3** | 45, 47, 49, 50 |
| [`analisis_control.py`](analisis_control.py) | (cierre de P2 × P3) | 45, 47, 49, 50 |
| [`bateria_mmap.py`](bateria_mmap.py) | agente andando sobre el directorio | Tabla 17 (Batería 8) |
| [`analisis_mmap.py`](analisis_mmap.py) | (cierre de la Batería 8) | Tabla 17 (Batería 8) |
| [`seed-reglas-lab.sh`](seed-reglas-lab.sh) | **P6** | 11-22 (sin esto la Batería 4 mide cero) |
| [`setup-agent.sh`](setup-agent.sh) | — | registro del agente de test contra el backend |

> `analisis_mmap.py` es la única excepción a lo de "solo stdlib": lee la tabla `events`
> directamente y necesita `psycopg` (`pip install 'psycopg[binary]'`). Sin él sale con
> código 2 y lo avisa.

---

## Orden de ejecución de una corrida oficial

```bash
mkdir -p resultados

# 0. Laboratorio arriba y agente registrado.
docker compose --profile app up -d
scripts/setup-agent.sh <password_admin>

# P6 — reglas de severidad. Sin esto no hay Alerts y la Batería 4 mide cero.
scripts/seed-reglas-lab.sh <password_admin>

# P3 — línea de base del grupo de control. ANTES de generar carga.
python3 scripts/control_hashing.py \
  --dir fim-watch \
  --csv resultados/bateria7_control.csv \
  --state resultados/control_estado.json

# P3 — el cron corriendo durante toda la ventana (elegir cron o --loop y
# declarar en el Cap. 5 cuál se usó).
python3 scripts/control_hashing.py --dir fim-watch \
  --csv resultados/bateria7_control.csv \
  --state resultados/control_estado.json \
  --loop --interval 900 &

# P2 — Batería 3: 500 eventos, 30 minutos sostenidos, mezcla 20/70/10.
date -u --iso-8601=seconds >> resultados/cronologia_utc.txt   # ítem 52
python3 scripts/generador_carga.py \
  --dir fim-watch \
  --seed 20260818 \
  --rate 0.2778 \
  --count 500 \
  --mix 20/70/10 \
  --manifest resultados/bateria3_manifiesto.json \
  --log resultados/bateria3_generador.log            # ítem 54: archivar este log
date -u --iso-8601=seconds >> resultados/cronologia_utc.txt

# Un scan final del control para cerrar la última ventana.
python3 scripts/control_hashing.py --dir fim-watch \
  --csv resultados/bateria7_control.csv --state resultados/control_estado.json

# Batería 7 — cruce manifiesto × control (ítems 45, 47, 49, 50).
python3 scripts/analisis_control.py \
  --manifiesto resultados/bateria3_manifiesto.json \
  --control    resultados/bateria7_control.csv \
  --salida     resultados/bateria7_latencias.csv \
  --mediana-fim-ms <ítem 44> --p99-fim-ms <ítem 46>

# Batería 8 — evasión por escritura mapeada (Tabla 17). Independiente de la
# ventana de las Baterías 3/7: corre aparte, con el agente andando.
date -u --iso-8601=seconds >> resultados/cronologia_utc.txt
sudo ./scripts/bateria_mmap.py \
  --dir fim-watch --agent-prefix /watch \
  --repeticiones 10 --salida resultados/bateria8
sleep 30                                            # drenar la ingesta
python3 scripts/analisis_mmap.py \
  --jsonl  resultados/bateria8/bateria8_cambios.jsonl \
  --salida resultados/bateria8/bateria8_correlacion.csv
date -u --iso-8601=seconds >> resultados/cronologia_utc.txt
```

Las Baterías 3 y 7 **deben correr sobre la misma carga y la misma ventana
temporal**. Si el control no ve exactamente los mismos cambios que la
plataforma, la Tabla 15 no compara nada.

La Batería 8 es la excepción: no comparte carga con ninguna otra, genera sus
propios archivos y se correlaciona sola. Su corte de validez es interno (el caso
C como testigo), así que **si `analisis_mmap.py` devuelve 1, la corrida se
descarta y se repite** — no se reporta la Tabla 17 con un testigo caído.

---

## `generador_carga.py` — P2

Genera cambios de filesystem controlados sobre el directorio vigilado
(`fim-watch/` en el host → `/watch` en el contenedor del agente) y emite el
**manifiesto**, que es el minuendo del ítem 9 (`eventos perdidos = manifiesto −
eventos recibidos`) y la fuente del timestamp real de modificación para la
latencia del grupo de control.

`--seed`, `--rate`, `--count`, `--mix` y `--dir` son **obligatorios a propósito**:
un default oculto es exactamente lo que vuelve irreproducible al ítem 54. La
configuración completa se imprime al arrancar, se escribe en `--log` y queda
embebida en el manifiesto.

### Los tres patrones ciegos para el escáner periódico

Sin ellos el ítem 49 da un empate artificial y el argumento más fuerte de la
tesis se evapora. El generador los produce a propósito:

| Patrón | Flag | Qué ve el cron | Qué ve la plataforma FIM |
|---|---|---|---|
| `revertido` | `--revert-frac` (0.20) | nada: el hash volvió a su valor previo dentro de la ventana | 2 eventos |
| `colapsado` | `--burst-frac` (0.20), `--burst-size` (5) | 1 cambio | N eventos |
| `efimero` | `--ephemeral-frac` (0.20) | nada: el archivo nació y murió entre dos scans | 2 eventos |

La columna `deteccion_control_esperada` del manifiesto registra esa *intención de
diseño*. La verificación empírica la hace `analisis_control.py` contra el CSV
real del control: no se asume, se mide.

### Otras corridas

```bash
# Batería 5 — 3.000 eventos durante el corte de 300 s (ítem 37).
python3 scripts/generador_carga.py --dir fim-watch --seed 20260818 \
  --rate 10 --count 3000 --mix 20/70/10 \
  --manifest resultados/bateria5_manifiesto.json \
  --log resultados/bateria5_generador.log

# Batería 4 — poblar el subdirectorio de severidad critical.
python3 scripts/generador_carga.py --dir fim-watch --seed 20260818 \
  --rate 1 --count 200 --mix 20/70/10 \
  --critical-subdir critico --critical-frac 0.25 \
  --manifest resultados/bateria4_manifiesto.json \
  --log resultados/bateria4_generador.log

# Inspeccionar el plan sin tocar el filesystem.
python3 scripts/generador_carga.py --dir fim-watch --seed 20260818 \
  --rate 0.2778 --count 500 --mix 20/70/10 --dry-run --log ''
```

### Salidas

* `--manifest` → JSON con `config`, `plan`, `resumen` y una entrada por cambio
  (`seq`, `operacion`, `patron`, `ruta_agente`, `ts_utc`, `ts_epoch`,
  `hash_antes`, `hash_despues`, `deteccion_control_esperada`, `error`).
* El mismo archivo con extensión `.jsonl` se escribe incrementalmente, para no
  perder una corrida de 30 minutos ante una interrupción. SIGINT/SIGTERM
  vuelcan igual el JSON completo.
* `--log` → el log de configuración y progreso que exige el ítem 54.

### Detalles que importan al medir

* La cadencia es fija (`1/rate`), sin jitter: se prioriza reproducibilidad.
  Con la misma semilla, dos corridas producen el mismo plan y el mismo contenido
  byte a byte.
* Cada cambio se escribe con un solo `open/write/close` para no multiplicar
  eventos fanotify por operación lógica.
* Los subdirectorios se crean **antes** de arrancar el reloj, para no inyectar
  eventos de directorio dentro de la ventana medida.
* El generador solo toca archivos con su propio prefijo (`--prefix`, default
  `gen`). Los residuos de corridas viejas de `fim-watch/` (creados como root
  desde el contenedor) no se tocan, pero conviene limpiar el directorio antes:
  `sudo rm -f fim-watch/* ` dejando el `.gitkeep`.
* `ruta_agente` (`/watch/...`) es la clave de join contra `events.path` y contra
  el CSV del control. Ajustable con `--agent-prefix`.

---

## `control_hashing.py` — P3

El grupo de control: el sustituto experimental del enfoque clásico tipo
AIDE/Tripwire. Cada 15 minutos (900 s) hashea el directorio vigilado y compara
contra el hash de la corrida anterior.

Hasta ahora el Cap. 5 llenaba esa columna con `E[Uniform(0, 900 s)] = 450 s`, la
esperanza matemática de un script que nunca se escribió, y la presentaba como
comparación experimental. Este script es lo que cierra esa brecha.

```bash
# Scan bajo demanda. El PRIMERO es la línea de base y no emite filas:
# correrlo antes de arrancar el generador.
python3 scripts/control_hashing.py --dir fim-watch \
  --csv resultados/bateria7_control.csv --state resultados/control_estado.json

# Modo loop en primer plano, sin tocar crontab.
python3 scripts/control_hashing.py --dir fim-watch \
  --csv resultados/bateria7_control.csv --state resultados/control_estado.json \
  --loop --interval 900

# Entrada de crontab lista para pegar en `crontab -e`.
python3 scripts/control_hashing.py --print-cron --dir fim-watch \
  --csv resultados/bateria7_control.csv --state resultados/control_estado.json
```

La entrada de cron que genera es:

```cron
*/15 * * * * cd /ruta/al/repo && /usr/bin/python3 scripts/control_hashing.py \
  --dir fim-watch --csv resultados/bateria7_control.csv \
  --state resultados/control_estado.json --agent-prefix /watch \
  >> resultados/control_cron.log 2>&1
```

`--state` es el equivalente a la base de datos de AIDE; `--reset` reinicia la
serie. `bateria7_control.csv` acumula una fila por cambio detectado con
`scan_id, ts_scan_utc, ts_scan_epoch, ts_scan_previo_epoch, operacion,
ruta_host, ruta_agente, hash_antes, hash_despues, bytes, motivo`.

### Criterio de comparación — declararlo en el capítulo

Por default compara **solo el contenido** (SHA-256), el mismo criterio de
integridad que usa la plataforma FIM contra su baseline. `--incluir-metadatos`
agrega tamaño / mtime / modo. La diferencia tiene consecuencias sobre el ítem 49:

* solo hash → una modificación revertida dentro de la ventana es invisible;
* con mtime → la reversión se detecta, pero N cambios sucesivos al mismo archivo
  **siguen colapsando en 1**. La ceguera estructural del muestreo periódico no
  desaparece, se reduce.

---

## `analisis_control.py` — cierre de la Batería 7

Cruza el manifiesto (P2) con el CSV del control (P3) por `ruta_agente` y produce
los ítems 45, 47, 49 y 50.

```bash
python3 scripts/analisis_control.py \
  --manifiesto resultados/bateria3_manifiesto.json \
  --control    resultados/bateria7_control.csv \
  --salida     resultados/bateria7_latencias.csv \
  --criterio   primer_cambio \
  --mediana-fim-ms 13.92 --p99-fim-ms 19.60
```

**Atribución.** Cada detección corresponde a un archivo y a un intervalo
`(scan_previo, scan]`. Puede haber N cambios reales del manifiesto dentro de ese
intervalo para el mismo archivo y el cron ve uno solo: eso es el colapso.

* `--criterio primer_cambio` (default): la detección se atribuye al primer cambio
  del intervalo, el instante en que el archivo dejó de coincidir con el último
  estado conocido como bueno. Es la lectura de seguridad.
* `--criterio ultimo_cambio`: cota inferior de la latencia. **Reportar cuál se usó.**

Los cambios sin atribución son la pérdida del ítem 49, desglosada por causa
(`colapsado`, `no_detectado`, `fuera_de_ventana`) y por patrón del generador.

**Percentiles**: interpolación lineal, idéntica al default de
`pandas.Series.quantile(q)`, y desvío muestral (`ddof=1`). No requiere pandas.
Si el capítulo exige la agregación oficial con pandas, `bateria7_latencias.csv`
trae una fila por latencia lista para `pd.read_csv(...)["latencia_ms"]`.

---

## `bateria_mmap.py` + `analisis_mmap.py` — Batería 8

Miden la limitación de `fanotify(7)` que el agente no puede cubrir: las escrituras
aplicadas a través de un mapeo compartido (`mmap`/`msync`/`munmap`). La máscara del
agente es `FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE`
(`agent/detector.py:294-298`) — `FAN_MODIFY` está definido en `agent/_fanotify.py:55`
pero nunca se usa. La detección de contenido se dispara al cerrar un descriptor
abierto para escritura, y el hash se computa **en ese instante**.

Tres casos, 10 repeticiones cada uno por defecto:

| Caso | Orden de operaciones | Eventos emitidos | Detección (medida 2026-09-01) |
|---|---|---|---|
| A | `open → mmap → close(fd) → escribir → msync → munmap` | 1 (`CLOSE_WRITE`) | **10/10 — la evasión NO se observó** |
| B | `open → mmap → escribir → msync → munmap → close(fd)` | 1 | 1 |
| C | `open/write/close` convencional, sin mapeo | 1 | 1 |

> **Resultado de la corrida del 2026-09-01: la evasión NO se observó.** El caso A fue
> detectado 10/10, con `hash_detected` igual al contenido **posterior** a la modificación y
> cero operaciones en `evento_sin_cambio`. Los números y la interpretación completa están en
> [`resultados/RESULTADOS.md`](../resultados/RESULTADOS.md), sección «Batería 8».
>
> **El mecanismo no es el que la hipótesis suponía.** La premisa era correcta: el
> `CLOSE_WRITE` se emite antes de la escritura sobre el mapeo, y el agente no tiene forma de
> enterarse de esa escritura. Pero el agente **no hashea en el instante del evento**: el
> `close(fd)` solo encola (`call_soon_threadsafe` → `asyncio.Queue`, `agent/detector.py:400`)
> y el hash se computa después, en `_process_event`. Con una mediana de 9,5 ms entre la
> operación y el evento persistido, la escritura in-process del caso A —sin syscalls de por
> medio, microsegundos— ya está en la página cuando el agente abre el archivo. **El agente
> detecta por hashear tarde, no por haber visto la escritura.**
>
> **Esto acota la limitación, no la cierra.** La ventana de evasión existe y es estrecha, del
> orden de los 10 ms de la latencia de detección. Un adversario que introduzca una demora
> mayor a esa latencia entre el `close(fd)` y la escritura sobre el mapeo debería seguir
> evadiendo. **Esa variante no se midió.**

**El caso B es lo que hace valer el resultado**: aísla que lo que está en juego es el orden
entre el cierre del descriptor y las escrituras sobre el mapeo, no `mmap` en sí. Sin B el
hallazgo sería "mmap no se detecta"; con B es un mecanismo caracterizado, que es lo que pide
el bloque E de la auditoría.

### Por qué contar eventos no alcanza

La hipótesis previa a la corrida era que en el caso A el agente emitiría el `CLOSE_WRITE` con
el hash **todavía íntegro**, y que contar eventos a secas daría un falso "detectado". La
medición mostró que el hash llega modificado, así que ese falso positivo no se materializó.

El criterio de comparación por hash **se mantiene igual de necesario**: es lo único que
distingue "hubo evento" de "se detectó la modificación", y es lo que permitió afirmar que la
detección fue real y no un artefacto de conteo. Si en una corrida futura —con la demora que
esta batería no midió— apareciera el `evento_sin_cambio`, el correlacionador ya lo clasifica.

Por eso `analisis_mmap.py` no cuenta: exige que `hash_detected` del evento coincida con
`hash_despues` del manifiesto, y clasifica cada operación en tres estados:

- `detectada` — hay evento y el hash es el modificado.
- `evento_sin_cambio` — **hay evento pero con el hash previo. Esta es la evasión.**
- `sin_evento` — no hubo evento.

La Tabla 17 lleva "Eventos emitidos" y "Detección" en columnas separadas justamente
para mostrar esa aparente contradicción.

### Corte de validez — no lo saltees

**El caso C es el testigo.** Si no detecta 10/10, `analisis_mmap.py` devuelve código 1
y avisa que la corrida no vale. Un cero en el caso A no prueba evasión mientras el
testigo no dé 100 %: prueba que el agente no estaba mirando el directorio.
**No reportar la Tabla 17 si ese chequeo falla.**

### Uso

```bash
# 1. Batería contra el laboratorio, con el agente andando.
#    No hace falta sudo: el script crea sus propios archivos en fim-watch/ y el
#    agente los lee como root desde el contenedor.
./scripts/bateria_mmap.py \
    --dir fim-watch --agent-prefix /watch \
    --repeticiones 10 --salida ./resultados/bateria8

# 2. Esperar ~30 s a que drene la ingesta.

# 3. Cruce contra la tabla events.
#    OJO: el servicio `db` del compose NO publica el puerto 5432 al host. Apuntar a
#    localhost te conecta a cualquier otro Postgres que escuche ahí y falla la auth.
#    Usar la IP del contenedor:
#      DBIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' \
#             tesis-fim-serio-db-1 | awk '{print $1}')
export DATABASE_URL="postgresql://fim:${DB_PASSWORD}@${DBIP}:5432/fim"
python3 scripts/analisis_mmap.py \
    --jsonl resultados/bateria8/bateria8_cambios.jsonl \
    --salida resultados/bateria8/bateria8_correlacion.csv

# Inspeccionar el plan sin tocar el filesystem.
./scripts/bateria_mmap.py --dir fim-watch --dry-run
```

`--espera-baseline` (default 5 s) es el margen para que el agente incorpore el archivo
recién creado a la baseline antes de mutarlo; `--espera-evento` (default 5 s) separa
operaciones para que la correlación por ventana temporal no se solape.

### Qué NO cubre

Todos los casos hacen `msync` antes de `munmap`. **No** se ejercita "escribir sobre el
mapeo → `munmap` sin `msync`" ni "escribir → salir del proceso sin `munmap`". No
invalida el resultado —`read(2)` ve las escrituras `MAP_SHARED` por el page cache
independientemente de `msync`, que solo afecta durabilidad en disco— pero no se puede
reportar que se cubrió esa variante.

### Cómo reportarlo

**"Consistente en las N repeticiones"**, nunca "determinística". El desenlace del caso A
depende de una carrera entre la secuencia in-process y el pipeline cross-thread del
agente (`agent/detector.py:265,400-406,769-778`), y esta batería no mide ese margen.

> **Los 7 falsos negativos del Cap. 5 no se explican por esto.**
> `generador_carga.py:339-345` escribe con un solo `open/write/close` y no hay `mmap` en
> ningún lado del repo. Ver `docs/dataset_cap5.md`, sección "Salvedades", punto 1.

---

## `seed-reglas-lab.sh` — P6

Solo los eventos de severidad `critical` y `high` generan una fila `Alert`
(RN-52, `backend/app/modules/alerts/service.py`). Sin reglas que hagan
`high`/`critical` a lo que pasa en el directorio vigilado, la Batería 4
(ítems 11-22) mide exactamente cero.

```bash
scripts/seed-reglas-lab.sh <password_actual_del_admin>
DRY_RUN=1 scripts/seed-reglas-lab.sh x     # ver qué haría, sin llamar a la API
```

Crea (o actualiza, es idempotente) dos reglas vía la API REST — el mismo camino
que usa la UI, así que también dispara el `rule_sync` hacia el agente:

| Patrón | Severidad | Acción |
|---|---|---|
| `/watch/*` | `high` | `alert_only` |
| `/watch/critico/*` | `critical` | `alert_only` |

El match es `fnmatch` sobre `event.path` y `*` cruza barras, así que `/watch/*`
cubre también los subdirectorios; gana la severidad más alta entre las reglas que
matchean (`SEVERITY_ORDER`, `critical = 0`), por eso las dos reglas conviven.

**Por qué `alert_only` y no `auto_restore` / `quarantine`.** La acción es
ortogonal a la severidad: RN-52 mira solo la severidad. Con `auto_restore` o
`quarantine` el agente reescribiría o movería los archivos durante la corrida,
inyectando cambios que no están en el manifiesto y arruinando los ítems 9, 45,
47 y 49. Para medir, `alert_only`. Si se quiere ejercitar la acción automática,
hacerlo en una corrida aparte declarada como tal (`ACTION=auto_restore`).

Variables de entorno: `API`, `ADMIN_USER`, `WATCH_PREFIX`, `CRITICAL_SUBDIR`,
`SEVERITY`, `ACTION`, `DRY_RUN`.

---

## Verificación de estos scripts

Corrida de humo real, ejecutada al escribirlos (directorio temporal, sin root):

```
control_hashing  scan_id=1 (baseline)  archivos=0 cambios=0
generador_carga  40 cambios @ 5 ev/s (seed 7, mezcla 20/70/10,
                 revert 0.3 / burst 0.3 / ephemeral 0.5)
control_hashing  scan_id=2..5 cada 3 s -> 5 detecciones en total
analisis_control 45 mediana = 1589,8 ms · 47 P99 = 2989,9 ms
                 49 perdidos = 35 de 40 (87,5 %)
                    colapsado 22 · no_detectado 13
```

Con `--interval 3` en lugar de 900 s el mecanismo es el mismo y la comprobación
es rápida: 40 cambios reales, 5 detecciones del cron, 35 pérdidas clasificadas
por causa. En una corrida de 500 eventos se verificó además que la mezcla sale
exacta (100/350/50), que los 35 pares revertidos vuelven al hash previo byte a
byte, que no hay modificaciones sobre archivos inexistentes y que dos corridas
con la misma semilla producen planes y contenidos idénticos.

### `bateria_mmap.py`

Corrida de humo en directorio temporal, sin agente (solo valida la instrumentación
del filesystem, no la detección):

```
bateria_mmap  2 repeticiones × 3 casos = 6 operaciones, 0 errores
              A_mmap_close_previo        modificacion_efectiva 2/2
              B_mmap_close_posterior     modificacion_efectiva 2/2
              C_escritura_convencional   modificacion_efectiva 2/2
```

Lo que confirma es lo que hace falta confirmar antes de correr contra el agente:
que la escritura sobre el mapeo **sí llega al archivo** aunque el descriptor ya
esté cerrado (caso A: `hash_antes != hash_despues` en 2/2). Si esa mutación no
ocurriera, un cero de detección en el caso A no probaría evasión — probaría que
la batería no modificó nada.

`analisis_mmap.py` sale con código 2 y un mensaje claro si falta `psycopg`, y con
código 1 si el manifiesto no tiene operaciones correlacionables (JSONL vacío o
truncado), antes de intentar escribir el CSV.
