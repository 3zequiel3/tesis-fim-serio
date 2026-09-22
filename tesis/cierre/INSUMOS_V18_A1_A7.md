# Insumos para la v18 — ítems A1 a A7

> **Alcance.** Recolección de datos, solo lectura, sobre el repositorio
> `tesis-fim-serio`, rama `devel`, `HEAD = 0d4b954b0d6dd591c33d66ddd516fa13c41b75dc`
> (`2026-09-22 12:23:00 -0300`). No se modificó ningún archivo del proyecto fuera de
> este documento.
>
> **Regla aplicada.** Cuando un dato no se conservó o no existe, se lo declara como tal
> de forma explícita. No se sustituye ningún dato histórico por el valor actual de la
> máquina, no se infiere y no se reconstruye. Cada dato lleva su procedencia: archivo,
> commit, línea o comando con su salida literal.
>
> **Contexto de rutas.** El material de tesis se movió de `docs/` a `tesis/` en el commit
> `fa3f27b` (`2026-09-19 13:23:40 -0300`, *refactor(repo): separate thesis material from
> project documentation*). Los changes archivados bajo `openspec/changes/archive/` y los
> documentos de cierre anteriores conservan las rutas viejas a propósito, de modo que las
> citas internas a `docs/cierre/...` y `docs/trazabilidad_us_tests.md` que aparecen
> reproducidas más abajo corresponden hoy a `tesis/cierre/...` y
> `tesis/trazabilidad_us_tests.md`.

## Identificación de la «batería histórica»

Antes de responder A1–A4 conviene fijar el objeto, porque el corpus usa el término en dos
sentidos que conviene no mezclar.

- **Corrida oficial histórica**: la ejecución de laboratorio del 2026-08-19 sobre el commit
  `77f0c53e9c5dac28f9b36e56e09bcdb8b214ba1c`. Es la que produjo las Baterías 2 a 8 del
  Capítulo 5.
- **Batería histórica de resiliencia**: la Batería 5 de esa misma corrida (desconexión del
  backend, 3.000 operaciones generadas, 2.988 eventos encolados y entregados, drenaje en
  153 s).

Procedencia del vínculo commit ↔ corrida:

```
$ git log -1 --date=iso --pretty='%h %ad %s' 77f0c53e
77f0c53 2026-08-19 10:19:35 -0300 docs(cap5): actualiza la matriz de trazabilidad tras cerrar brechas
```

`tesis/dataset_cap5.md`, líneas 1-10:

```
# Dataset del Capítulo 5 — 55 valores

**Corrida oficial del 2026-08-19.** Un renglón por ítem, con el valor y la fuente.

| Metadato | Valor |
|---|---|
| Commit (ítem 51) | `77f0c53e9c5dac28f9b36e56e09bcdb8b214ba1c` — árbol limpio (`git status --porcelain` vacío) |
| Artefactos crudos | `resultados/` (35 archivos) |
| Topología | **CO-RESIDENTE** — agente en contenedor sobre el mismo host que el backend |
```

`tesis/cierre/INFORME_CIERRE_TECNICO.md`, línea 20:

```
| Corrida histórica | `77f0c53e9c5dac28f9b36e56e09bcdb8b214ba1c` | Baterías originales. `resultados/entorno.txt` informa un archivo sin commit y `resultados/RESULTADOS.md` dice árbol limpio: contradicción histórica no resoluble. |
```

---

## A1 — Núcleo y sistema de archivos del anfitrión de la batería histórica

### Respuesta

**No se conservó.** Ni la salida de `uname -r` del anfitrión donde corrió la batería del
2026-08-19, ni el tipo de sistema de archivos del directorio monitoreado en esa corrida,
existen en el repositorio. El único artefacto que los habría contenido —
`resultados/entorno.txt` — nunca se versionó y no está presente en el árbol de trabajo.
De él sobrevive únicamente su hash SHA-256 registrado en el índice de evidencia.

### Procedencia

El protocolo de reproducción manda capturar esos datos en `entorno.txt`.
`tesis/cierre/REPRODUCIR.md`, líneas 18-35:

```
## 2. Registrar host, kernel, filesystem y reloj

{
  date --utc --iso-8601=seconds
  timedatectl status
  uname -a
  cat /etc/os-release
  findmnt -T . -o TARGET,SOURCE,FSTYPE,OPTIONS
  lscpu
  free -h
  python3 --version
  docker version
  docker compose version
  node --version
  pnpm --version
} > "$EVIDENCE_DIR/entorno.txt"
```

El archivo de la corrida histórica figura en el índice de evidencia solo por su hash.
`tesis/cierre/evidencia/INDICE.md`, líneas 7-11:

```
Los archivos bajo `resultados/` están ignorados por Git y deben conservarse sin sobrescritura.

| Archivo | Uso | SHA-256 | Precaución |
|---|---|---|---|
| `resultados/entorno.txt` | Entorno/commit histórico | `3d9f689d0a63805d214545cb8968af7355788a25473fc13555ba1f4fae9bc915` | Revisar host/rutas. |
```

Verificación de que `resultados/` nunca entró a Git y no está en disco:

```
$ git log --all --oneline -- 'resultados/*'
(sin salida)

$ git log --all --pretty=format: --name-only | rg '^resultados/' | sort -u
(sin salida)

$ eza -la resultados
"resultados": No such file or directory (os error 2)

$ rg -n "resultados" .gitignore
47:tesis/resultados/
48:resultados/
```

### Valores de la máquina actual — NO corresponden a esa corrida

Se los incluye únicamente para dejar constancia de que se verificó, y **no deben usarse
como dato de la batería histórica**:

```
$ uname -r
7.0.0-31-generic

$ uname -a
Linux Eze-Linux 7.0.0-31-generic #31-Ubuntu SMP PREEMPT_DYNAMIC Sat Aug  1 04:26:38 UTC 2026 x86_64 GNU/Linux

$ findmnt -no FSTYPE -T .
ext4

$ df -T .
S.ficheros     Tipo bloques de 1K    Usados Disponibles Uso% Montado en
/dev/nvme0n1p2 ext4     243937628 157766064    73707388  69% /
```

Esta salida es del 2026-09-22, un mes y tres días después de la corrida. **No hay ningún
registro en el repositorio que permita afirmar que el núcleo de la corrida del 2026-08-19
era este mismo**, ni que el anfitrión fuera esta misma máquina. La corrida fue
CO-RESIDENTE (agente en contenedor sobre el mismo host que el backend), pero la identidad
del host no quedó registrada en ningún archivo versionado.

### Datos de núcleo y filesystem que sí se conservaron, de OTRAS corridas

Se listan para que nadie los confunda con los de A1:

| Corrida | Fecha | Núcleo | Filesystem | Archivo |
|---|---|---|---|---|
| Corrida causal B9 (`absence-...-r2`) | 2026-09-10 | `Linux 7.0.0-31-generic x86_64 GNU/Linux` | `/dev/nvme0n1p2 ext4 rw,relatime` (magic `ef53`) | `tesis/cierre/evidencia/absence-20260910T052521Z-r2/environment.txt`, líneas 5-7 |
| Drenaje Runs 1-4 | 2026-09-10 | `"kernel": "7.0.0-31-generic"` | no registrado en el JSON | `tesis/cierre/evidencia/drenaje-20260910-run{1,3,4-unit1}/environment.json` |
| Corrida oficial Cap. 5 (candidato `v1.0-tesis`) | 2026-09-17 | servidor central `7.0.0-31-generic`; anfitrión monitoreado (VM) `6.8.0-139-generic` | no registrado | `tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/metadata/entorno.txt` |

Contenido literal de ese último archivo:

```
candidate_tag=v1.0-tesis
candidate_commit=7a906c202e417aec5f03d9a7545e216a724aca81
candidate_tree=1d5848c435a6a3a06725e9bceb57e586977e9c9a
git_status_clean=yes
--- servidor central ---
os=Ubuntu 26.04.1 LTS
kernel=7.0.0-31-generic
docker=Docker version 29.7.2
compose=5.5.0
ip=192.168.1.43
rate_limit_ingest_events=100
rate_limit_ingest_window_seconds=60
--- anfitrion monitoreado (VM) ---
os=Ubuntu 24.04.5 LTS
kernel=6.8.0-139-generic
python=Python 3.13.15
ip=10.113.87.102
agente=fim-vm (systemd, nativo)
watch_path=/srv/fim-watch
snapshot=fim-host.limpia
backend_image_rebuilt_from_candidate=yes
backend_tree_sha256_container_equals_repo=3e7160e072a79a3d721795c884f0a6ed0e7a42af835e4bd5d9979fbba32ee956
agent_publisher_sha256=0fd266bc9ab9a7e5e5a7545775c17e2ec6a971c4ebb50b254d6f7b55e4b83f08
```

Ninguno de esos tres registros corresponde a la batería del 2026-08-19.

---

## A2 — Semilla del generador de carga

### Respuesta

La semilla de la **batería histórica de resiliencia (Batería 5)** fue **`555`**.

Las semillas de las otras baterías de la misma corrida, para referencia: Batería 3
`seed=20260819`; Batería 4 `seed=4001/4050/4100`.

**La semilla no se fija en ningún archivo del código**: `--seed` es un argumento
obligatorio de línea de comandos del generador. El archivo y la línea que hacen que sea
obligatoria son `scripts/generador_carga.py:388`. El valor concreto usado en la corrida
está registrado en `tesis/dataset_cap5.md:207`.

### Procedencia

Valor de la corrida — `tesis/dataset_cap5.md`, línea 207 (ítem 54 de reproducibilidad):

```
| 54 | Semilla y parámetros del generador | B3 `seed=20260819`; B5 `seed=555`; B4 `seed=4001/4050/4100`. Configuración completa logueada al arrancar y embebida en cada manifiesto |
```

Commit que lo asentó:

```
$ git log --follow --oneline --date=short --pretty='%h %ad %s' -- tesis/dataset_cap5.md
fa3f27b 2026-09-19 refactor(repo): separate thesis material from project documentation
ab86c11 2026-08-20 docs(cap5): dataset completo de la corrida del 2026-08-19
```

`ab86c11` (`2026-08-20 15:28:35 -0300`) es el commit que introdujo el valor; `fa3f27b`
solo movió el archivo de `docs/` a `tesis/`. Confirmación independiente por pickaxe:

```
$ git log --all --oneline --date=short --pretty='%h %ad %s' -S 'seed=555'
7df4935 2026-09-11 chore: freeze corrected consolidated validation candidate
ab86c11 2026-08-20 docs(cap5): dataset completo de la corrida del 2026-08-19
```

Dónde se fija la semilla en el instrumento — `scripts/generador_carga.py`, líneas 387-389:

```
    ap.add_argument("--dir", required=True, help="Directorio vigilado en el host (ej: fim-watch)")
    ap.add_argument("--seed", required=True, type=int, help="Semilla (ítem 54). Obligatoria.")
    ap.add_argument("--rate", required=True, type=float, help="Eventos por segundo. Obligatoria.")
```

La semilla se embebe además en el manifiesto que emite el generador
(`scripts/generador_carga.py:458`, clave `"seed"`).

### Salvedad de conservación

El log de arranque del generador y el manifiesto de la Batería 5 histórica —
`resultados/bateria5_manifiesto.jsonl`, con SHA-256
`81cb339967b066a11bb03c1161fc2d00b9043711e206680f5bf90309ea0b1fbf` según
`tesis/cierre/evidencia/INDICE.md:20` — **no se conservaron en el repositorio** (misma
verificación de A1: `resultados/` nunca se versionó y no existe en disco). El valor `555`
está acreditado por el dataset asentado el día siguiente a la corrida, no por el artefacto
crudo.

---

## A3 — Procedencia de la definición de preservación (Tabla 4)

### Respuesta

**La definición de la Tabla 4 es POSTERIOR a la batería histórica de resiliencia.** Dicho
con todas las letras: el indicador de preservación se enunció como «proporción de eventos
encolados que se entregan» **después** de que la corrida del 2026-08-19 arrojara 2.988
eventos encolados sobre 3.000 operaciones generadas. El criterio vigente antes de la
batería medía la preservación **contra las operaciones generadas**, no contra los eventos
encolados.

| Hito | Fecha | Commit / artefacto | Denominador del indicador |
|---|---|---|---|
| Criterio a priori en el documento de tesis (Tabla 3 y Tabla 14 de la versión de protocolo) | 2026-06-30 | `24b339e` — `docs/Tesis.pdf`, hoy `tesis/Tesis.pdf` | **eventos generados** |
| Criterio a priori en el plan de medición (ítems 38 y 39) | vigente al 2026-08-19 | `tesis/plan_medicion_cap5.md`, última edición previa `eb850b8` (2026-08-19 10:06:46) | ítem 38 contra **generados**; ítem 39 contra encolados |
| **Ejecución de la batería** | **2026-08-19** | **`77f0c53e` (2026-08-19 10:19:35 -0300)** | — |
| Primera propuesta escrita de informar 2.988 y separar categorías | 2026-09-10 01:49:42 -0300 | `7115511` — alta de `docs/cierre/CAMBIOS_PARA_TESIS.md` | — |
| Redacción «Proporción de eventos encolados que se entregan tras la reconexión» en la Tabla 4 | archivo con fecha de modificación 2026-09-10 19:21 | `tesis/cierre/Tesis_v5_cierre_tecnico_corregida.docx` (no versionado, ignorado por `.gitignore:61`) | **eventos encolados** |

Diferencia: la definición es **22 días posterior** a la ejecución de la batería.

### Procedencia — criterio anterior a la batería

El documento de tesis versionado (`tesis/Tesis.pdf`, incorporado en `24b339e`,
`2026-06-30 12:42:11 -0300`, «Pdf de la tesis») define el indicador en su **Tabla 3**
—no Tabla 4, que en esa versión es «Stack tecnológico por componente»— así:

```
Tabla 3. Variables e indicadores experimentales

 Resiliencia offline    Porcentaje de eventos                   %          100 %
                        preservados tras desconexión del
                        backend.
```

Y su Tabla 14, planilla de captura de la Batería 5:

```
Tabla 14. Planilla de captura — Resiliencia offline

 Eventos preservados en cola local        [pendiente]           Igual a
                                                                generados

 Eventos entregados tras reconexión       [pendiente]           Igual a
                                                                generados
```

```
$ git log --follow --oneline --date=short --pretty='%h %ad %s' -- tesis/Tesis.pdf
fa3f27b 2026-09-19 refactor(repo): separate thesis material from project documentation
24b339e 2026-06-30 Pdf de la tesis
```

El plan de medición, cuya última edición anterior a la batería es `eb850b8`
(`2026-08-19 10:06:46 -0300`, trece minutos antes del commit de la corrida), fija los mismos
objetivos. `tesis/plan_medicion_cap5.md`, líneas 345-347:

```
| 37 | Eventos generados durante la desconexión (n) | 3.000 | Manifiesto del generador |
| 38 | Eventos preservados en cola local (n) | = 37 | `ls queue/ \| wc -l` **antes** de reconectar |
| 39 | Eventos entregados tras reconexión (n) | = 38 | `COUNT(*)` en `events` de la ventana + cola drenada a 0 |
```

El ítem **38** —preservación— tenía objetivo «= 37», es decir, **igual a los generados**.
Ese es precisamente el ítem que la corrida no cumplió: 2.988 contra 3.000.
`tesis/dataset_cap5.md`, líneas 143-150:

```
| 36 | Duración real de la desconexión (s) | 300 | **326** |
| 37 | Eventos generados durante la desconexión (n) | 3.000 | **3.000** |
| 38 | Eventos preservados en cola local (n) | = 37 | **2.988** |
| 39 | Eventos entregados tras reconexión (n) | = 38 | **2.988** |
| 40 | Orden FIFO preservado | Sí | **Sí — 0 de 2.988 fuera de orden** |
| 41 | Duplicaciones detectadas (n) | 0 | **0** |
| 42 | Comandos antes que eventos encolados | Sí | **Parcial — ver abajo** |
| 43 | **Tiempo de recuperación total (s)** | < 30 | **153 → NO CUMPLE** |
```

### Procedencia — definición actual de la Tabla 4

En las versiones de cierre (v5 a v13) la tabla de variables e indicadores pasó a numerarse
**Tabla 4** y el indicador quedó redactado así:

`tesis/cierre/Tesis_v13_cierre_tecnico.docx`, fila de la Tabla 4 (texto extraído del
`word/document.xml`):

```
Preservación de eventos ante desconexión |
Proporción de eventos encolados que se entregan tras la reconexión (no mide la proporción de operaciones generadas que llegan a encolarse) |
% |
100 |
```

La misma redacción, palabra por palabra, aparece en todas las versiones de cierre
disponibles:

```
### Tesis_v5_cierre_tecnico_corregida  → línea 528
### Tesis_v6_cierre_tecnico            → línea 528
### Tesis_v7_cierre_tecnico            → línea 529
### Tesis_v8_cierre_tecnico            → línea 530
### Tesis_v9_cierre_tecnico            → línea 530
### Tesis_v10_cierre_tecnico           → línea 535
### Tesis_v12_cierre_tecnico           → línea 537
### Tesis_v13_cierre_tecnico           → línea 537
(en todos: «Proporción de eventos encolados que se entregan tras la reconexión
 (no mide la proporción de operaciones generadas que llegan a encolarse)»)
```

Fechas de modificación de esos archivos:

```
$ eza -la --time-style=long-iso tesis/cierre/*.docx
.rw-rw-r-- 1,6M ezequiel 2026-09-10 19:21 tesis/cierre/Tesis_v5_cierre_tecnico_corregida.docx
.rw-rw-r-- 1,6M ezequiel 2026-09-11 00:10 tesis/cierre/Tesis_v6_cierre_tecnico.docx
.rw-rw-r-- 1,6M ezequiel 2026-09-11 15:06 tesis/cierre/Tesis_v7_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-11 18:01 tesis/cierre/Tesis_v8_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-11 20:50 tesis/cierre/Tesis_v9_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-12 21:31 tesis/cierre/Tesis_v10_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-17 19:58 tesis/cierre/Tesis_v12_cierre_tecnico.docx
.rw-rw-r-- 1,4M ezequiel 2026-09-19 12:32 tesis/cierre/Tesis_v13_cierre_tecnico.docx
```

Ninguno de estos `.docx` está versionado (`.gitignore:61` los excluye), de modo que la
fecha de modificación del sistema de archivos es la única marca temporal disponible para
ellos. El documento de origen que menciona el registro de cambios de v5 —
`Tesis_v5_cierre_tecnico_aplicado (1).docx`, citado en
`tesis/cierre/REGISTRO_CAMBIOS_TESIS_V5.md:3`— **no está presente** en el repositorio, así
que no se puede fechar una aparición anterior a v5 con evidencia propia.

Lo que sí se puede fechar con commits es la decisión de separar las categorías, que es el
antecedente directo de la redefinición. `tesis/cierre/CAMBIOS_PARA_TESIS.md`, alta en el
commit `7115511` (`2026-09-10 01:49:42 -0300`), línea 29:

```
| Desconexión B5 | 3.000/3.000 | Histórico: 2.988/3.000. Los doce son compatibles con retorno a baseline según manifiestos; la nueva corrida demuestra ese descarte sólo para sus propios diez casos | Informar 2.988 y separar "explicación fuertemente sustentada" de "causalidad retrospectiva no demostrable" | `resultados/bateria5_manifiesto.jsonl`; evidencia causal actual |
```

```
$ git log --all --diff-filter=A --oneline --date=short --pretty='%h %ad %s' -- 'docs/cierre/CAMBIOS_PARA_TESIS.md' 'tesis/cierre/CAMBIOS_PARA_TESIS.md'
7df4935 2026-09-11 chore: freeze corrected consolidated validation candidate
7115511 2026-09-10 docs(cierre): consolidate verified technical evidence
```

La auditoría del mismo ciclo formula el punto de manera explícita.
`tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V5.md:158` (archivo no versionado, fecha de
modificación 2026-09-10 21:11):

```
| Tabla 16 | 94–95 | **Rota:** fila de precedencia comandos/eventos desplazada; "Si-" y "Si" sin tilde. El 100 % es 2.988/2.988 encolados, no 3.000/3.000 operaciones. |
```

### Cómo queda el dato para el informe

El texto vigente de la tesis lo declara sin ambages —y conviene no diluirlo en la v18.
`Tesis_v13_cierre_tecnico`, párrafo de §5.6 (línea 1423 del texto extraído):

```
El indicador de preservación de la Tabla 1, definido en el apartado 3.4 sobre los eventos
encolados, se alcanza con ese alcance y no con otro.
```

Es decir: el 100 % de preservación se sostiene sobre 2.988/2.988 encolados. Sobre el
denominador que el criterio fijado a priori usaba —3.000 operaciones generadas— el
resultado es 2.988/3.000, y **no** alcanza el umbral del 100 %.

---

## A4 — Ventana anti-replay en la batería histórica

### Respuesta

En el commit de la batería (`77f0c53e`) el control de desfase se calculaba **sobre
`sent_at`**, con repliegue a `detected_at` únicamente cuando el agente no enviaba
`sent_at`. El agente de ese mismo commit sí sella `sent_at`, de modo que la rama efectiva
en la corrida fue la de `sent_at`.

Tolerancia configurada en esa corrida: **`_CLOCK_SKEW_S = 300`** (300 s, 5 minutos),
constante fija en el código, sin parámetro de configuración.

### Archivo y línea del cálculo, en el commit de la corrida

`backend/app/modules/events/consumer.py` en `77f0c53e`:

- **Línea 72** — definición de la tolerancia.
- **Línea 317** — cálculo sobre `sent_at` (rama efectiva).
- **Línea 332** — cálculo sobre `detected_at` (repliegue para agentes anteriores a D37).

```
$ git show 77f0c53e:backend/app/modules/events/consumer.py | rg -n -B4 -A10 "_CLOCK_SKEW_S"
68-# `sent_at` cuando el payload lo trae (sellado al publicar/republicar); si no
69-# lo trae (agente anterior a D37) se evalúa sobre `detected_at`, comportamiento
70-# previo íntegro. `detected_at` en sí mismo dejó de tener ventana: es verdad
71-# forense, no señal de replay.
72:_CLOCK_SKEW_S = 300  # 5 minutos
--
313-                client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump,
314-                shared_secret=shared_secret,
315-            )
316-            return
317:        if abs((received_at - sent_at).total_seconds()) > _CLOCK_SKEW_S:
318-            log.warning(
319-                "consumer.clock_skew.out_of_range",
...
328-    else:
329-        # Ausencia = comportamiento anterior (D33/D35/D36): agente sin actualizar
330-        # a D37 todavía. La ventana se evalúa sobre detected_at, tal como antes.
331-        log.debug("consumer.clock_skew.sent_at_absent_fallback", event_id=event_id, agent_id=agent_id)
332:        if abs((received_at - detected_at).total_seconds()) > _CLOCK_SKEW_S:
```

Encabezado del mismo archivo en ese commit, líneas 11-13:

```
     sent_at (fallback
     a detected_at)      → clock_skew (RN-90, enmendada por D37/RN-131); distingue
                            unparseable / unparseable_sent_at / out_of_range
```

El agente de ese commit sella `sent_at` antes de cada publicación:

```
$ git show 77f0c53e:agent/publisher.py | rg -n "sent_at"
229:        Sella sent_at con la hora UTC actual y firma sobre el canonical JSON
230:        que incluye ese sent_at, para que quede cubierto por el HMAC. Se
233:        stamped = {**payload, "sent_at": datetime.now(timezone.utc).isoformat()}
```

### Verificación de fechas contra el antecedente conocido

```
$ git log -1 --date=iso --pretty='%h %ad %s' 44dfe72
44dfe72 2026-06-12 01:14:43 -0300 change 6 y 7 completos, 8 falta archive

$ git log -1 --date=iso --pretty='%h %ad %s' 46f6073
46f6073 2026-08-18 19:05:19 -0300 feat(events): ventana de skew sobre sent_at y respuesta tipada al agente

$ git log -1 --date=iso --pretty='%h %ad %s' 77f0c53e
77f0c53 2026-08-19 10:19:35 -0300 docs(cap5): actualiza la matriz de trazabilidad tras cerrar brechas
```

El antecedente se confirma y, a la vez, se acota:

- `_CLOCK_SKEW_S = 300` existe desde `44dfe72` (2026-06-12): **correcto**.
- `46f6073` introdujo la evaluación sobre `sent_at` el **2026-08-18 19:05:19 -0300**, es
  decir **quince horas y catorce minutos antes** del commit de la batería. Por lo tanto,
  `46f6073` es **ancestro** de la corrida, y la corrida **ya llevaba** la ventana sobre
  `sent_at`. No corresponde describirla como una corrida hecha sobre `detected_at`.

El propio texto de la tesis lo registra así. `Tesis_v13_cierre_tecnico`, §5.6 (línea 1423
del texto extraído):

```
La versión de aquella corrida ya incorporaba la ventana sobre sent_at: el consumidor de
eventos declara una tolerancia de trescientos segundos (_CLOCK_SKEW_S = 300,
backend/app/modules/events/consumer.py, línea 72 del commit 77f0c53e). La evaluación del
desfase sobre sent_at fue introducida por el commit 46f6073, del 18 de agosto de 2026,
ancestro de aquella corrida.
```

### Dato asociado que sí se conservó

La corrida registró **0 rechazos del backend** (`tesis/dataset_cap5.md:152`: «Cero
descartes locales y cero rechazos del backend»), consistente con una ventana evaluada
sobre `sent_at`: la permanencia en cola de los eventos más antiguos superó los 326 s
—por encima de la tolerancia de 300 s— sin producir rechazos, porque el desfase medido
es el de tránsito entre transmisión e ingesta, no el de permanencia en cola.

---

## A5 — «Mediana de 9,5 ms» del apartado 5.9 (mapeo de memoria)

### Respuesta

El valor **existe y está respaldado por una tabla agregada versionada**, con **n = 10**.
La **planilla o log crudo del que sale NO se conservó en el repositorio**: los artefactos
de la Batería 8 quedaron bajo `resultados/bateria8/`, ignorado por Git, y nunca se
versionaron. Sobrevive únicamente el resumen (n, mínimo, mediana, máximo).

### El dato y su n

`tesis/informe/Tabla 17-datos.md`:

```
| Caso | n | mín | mediana | máx |
|---|---|---|---|---|
| A | 10 | 0,9 ms | 9,5 ms | 10,1 ms |
| B | 10 | 1,0 ms | 5,5 ms | 9,9 ms |
| C | 10 | 0,4 ms | 0,7 ms | 1,2 ms |
```

La mediana de 9,5 ms corresponde al **Caso A** (mmap con `close(fd)` previo a la
escritura), con **n = 10 repeticiones**.

### Texto del apartado 5.9

El apartado 5.9 no existe en `tesis/Tesis.pdf` (borrador de 92 páginas que llega hasta
§5.8). Sí existe en las versiones de cierre. Texto literal en
`tesis/cierre/evidencia/v10-closure-20260912T190052Z/build/render/Tesis_v10_cierre_tecnico.pdf`,
§5.9 «Protocolo de caracterización del mapeo de memoria»:

```
La secuencia in-process del caso A —escritura sobre el mapeo, sincronización y liberación
del mapeo, sin llamadas al sistema de por medio— ocurre en microsegundos. El procesamiento
del evento, en cambio, se completó con una mediana de 9,5 ms. Por lo tanto, la modificación
ya se encontraba aplicada cuando el agente calculó el hash.
```

La Tabla 19 de esas versiones («Resultados — Caracterización del mapeo de memoria»)
presenta solo la matriz de detección por caso (10/10 modificaciones efectivas, 10 eventos
emitidos, 10/10 detección); **la cifra de 9,5 ms aparece únicamente en el párrafo de
prosa, no itemizada en la tabla**.

### Procedencia del número en el repositorio

```
$ git log --all --follow --oneline -- "tesis/informe/Tabla 17-datos.md"
fa3f27b refactor(repo): separate thesis material from project documentation
7df4935 chore: freeze corrected consolidated validation candidate
ae7353e docs(informe): Tabla 17 — resultado de la Bateria 8, la evasion no se observo
8c943c2 docs(pki): D48/RN-142 — ventana de gracia para renovar un certificado vencido

$ git log --all --oneline -S "9,5 ms" -- "tesis/informe/Tabla 17-datos.md" "docs/informe/Tabla 17-datos.md"
7df4935 chore: freeze corrected consolidated validation candidate
ae7353e docs(informe): Tabla 17 — resultado de la Bateria 8, la evasion no se observo
```

El número entró al repositorio en **`ae7353e`** (`2026-09-01 20:23:00 -0300`).

### Declaración explícita sobre el dato crudo

**Los datos crudos de la Batería 8 no existen en el repositorio.** El propio archivo lo
declara:

```
Los artefactos crudos (`bateria8_cambios.jsonl`, `bateria8_manifiesto.json`,
`bateria8_correlacion.csv`) quedan en `resultados/bateria8/`, que está en `.gitignore`
como todas las corridas. Por eso los números viven acá, en un archivo trackeado.
```

Verificación:

```
$ git log --all --oneline -- 'resultados/bateria8*' 'resultados/bateria8'
(sin salida)

$ git rev-list --all | while read c; do git ls-tree -r --name-only "$c" | grep -q '^resultados/' && echo "FOUND in $c"; done
(sin salida — ningún árbol de commit de toda la historia contiene una ruta resultados/)
```

`tesis/cierre/evidencia/INDICE.md` conserva sus hashes, no sus bytes:

```
| `resultados/bateria8/bateria8_manifiesto.json` | Casos `mmap` | `b1ffe6f0a92aa463774d13ff083c60093845e846d4522f251b35f5bebdbc0629` | Revisar IDs. |
| `resultados/bateria8/bateria8_correlacion.csv` | 30 correlaciones `mmap` | `c27f39285852e5ad3ee5b12f209d0d4217739b61841a33e32cd50898e7fdc060` | Revisar rutas. |
```

En síntesis: la mediana y su n **existen** y son citables desde
`tesis/informe/Tabla 17-datos.md`; **la planilla de origen no se conservó** y, por lo
tanto, la mediana no es recomputable desde el repositorio.

---

## A6 — RN-131 frente a un catálogo de 128 reglas

### Respuesta

- **Ruta del catálogo:** `docs/reglas_de_negocio.md`. No se movió a `tesis/` en `fa3f27b`;
  sigue siendo documentación de proyecto, no material de tesis.
- **Recuento actual:** **170 reglas** — `RN-01` a `RN-169` sin huecos, **más** `RN-37a`.
- **Explicación de la numeración:** no hay huecos, no hay reglas retiradas. El catálogo
  simplemente **se amplió** muy por encima de 128. La única irregularidad es `RN-37a`, una
  sub-regla con sufijo intercalada junto a RN-37 para no renumerar el resto; es aditiva,
  no un hueco.
- **RN-131 existe** y es vigente.
- **«128 reglas» es una cifra caduca** que la propia auditoría ya había marcado como
  errónea.

### Procedencia del recuento

Criterio de conteo: una regla «existe» solo si tiene encabezado markdown propio
(`### RN-XX: …` o `#### Dnn / RN-XX: …`). Las menciones en prosa no cuentan.

```
$ rg -n "^#{1,6}.*RN-[0-9]+[a-z]?:" docs/reglas_de_negocio.md | rg -o "RN-[0-9]+[a-z]?(?=:)" --pcre2 | sort -u
→ 170 identificadores distintos: RN-01 … RN-169, más RN-37a

$ rg -n "^#{1,6}.*RN-[0-9]+[a-z]?:" docs/reglas_de_negocio.md | rg -o "RN-[0-9]+[a-z]?(?=:)" --pcre2 | sort | uniq -d
(sin salida — ningún número está definido dos veces)

$ diff <(seq 1 169) <numeros_encontrados_sin_ceros>
(sin salida — todo entero de 1 a 169 tiene exactamente un encabezado)
```

**Números faltantes en el rango 1..169: ninguno.**

### RN-131 — encabezado literal

`docs/reglas_de_negocio.md`, línea 1207:

```
#### D37 / RN-131: Durabilidad del transporte — ack tipado, ventana de skew sobre `sent_at` y outbox de comandos
```

Es la misma decisión que sostiene el comportamiento documentado en A4. Se usa además en
código: `agent/publisher.py`, `agent/config.py`, `agent/install.sh`,
`agent/deploy/config.yaml.example`, `docs/arquitectura_stack.md:2564`.

```
$ git log --oneline --date=short -S "RN-131" -- docs/reglas_de_negocio.md
b8b2511 docs(decisiones): cierra D37/RN-131 y propone stream-ack-durability   (2026-08-18)
```

RN-131 se introdujo en `b8b2511` (`2026-08-18 18:33:02 -0300`), el día anterior a la
batería histórica.

### Regla de mayor número y commit que la introdujo

`RN-169` (`D75 / RN-169`) es la más reciente. Se incorporó en **`fa3f27b`**
(`2026-09-19 13:23:40 -0300`): ese commit, además del movimiento `docs/` → `tesis/`,
agregó la sección completa de D75/RN-169 a `docs/reglas_de_negocio.md`
(hunk `@@ -2418,6 +2418,65 @@`).

### De dónde sale «128 reglas» y qué otras cifras circulan

| Cifra | Dónde aparece | Estado |
|---|---|---|
| **~108** (`RN-01 a RN-108`) | `CLAUDE.md`, línea 23 | Caduca. La parte «16 dominios» sí sigue siendo correcta |
| **126** | `tesis/defensa_guion_10min.md`, líneas 74, 76, 86, 88 | Caduca |
| **128** | Anexos C/D de la tesis V11 (pp. 58, 91, 165-166), señalada por la auditoría | Caduca, y ya marcada como error |
| **170** (169 + RN-37a) | `docs/reglas_de_negocio.md` al HEAD actual | Vigente |

La auditoría V11 ya lo había levantado como hallazgo **N-11** (severidad Baja, estado
«Nuevo»/abierto), en `tesis/cierre/AUDITORIA_V11_DEVOLUCION.html`:

```
N-11 · Bajo · Nuevo · Anexo C/D y 128 reglas no coinciden con 7a7ee50 (pp. 58, 91, 165-166)
     · Evidencia que lo cerraría: Corregir contra modelos y compose
```

Es decir: ya en el candidato `7a7ee50` (2026-09-12) el catálogo llegaba a RN-145 mientras
el texto seguía diciendo 128. La corrección quedó pendiente (acción A2 de esa misma
auditoría) y sigue sin aplicarse.

**Cifra a usar en la v18: 170 reglas de negocio (RN-01 a RN-169, incluida RN-37a), en 16
dominios, catalogadas en `docs/reglas_de_negocio.md`.** Y conviene dejar dicho que
`CLAUDE.md:23` y `tesis/defensa_guion_10min.md` arrastran cifras distintas y también
caducas.

---

## A7 — Recuento de historias y criterios

### A7.1 — Ruta exacta y vigente de la matriz de trazabilidad

Hay **dos** documentos vigentes y complementarios; conviene no confundirlos:

| Documento | Ruta vigente | Ruta anterior a `fa3f27b` | Qué contiene |
|---|---|---|---|
| Matriz de trazabilidad de cierre | **`tesis/cierre/MATRIZ_TRAZABILIDAD.md`** | `docs/cierre/MATRIZ_TRAZABILIDAD.md` | Una fila por historia, con criterio, implementación, prueba, evidencia y estado; tabla de «Ajustes de criterio declarados»; reconciliación de conteos |
| Anexo de trazabilidad historia ↔ test | **`tesis/trazabilidad_us_tests.md`** | `docs/trazabilidad_us_tests.md` | Detalle por criterio y por test (`§5.NN` por historia) |

Historia del archivo principal:

```
$ git log --follow --oneline --date=iso --pretty='%h %ad %s' -- tesis/cierre/MATRIZ_TRAZABILIDAD.md
fa3f27b 2026-09-19 13:23:40 -0300 refactor(repo): separate thesis material from project documentation
66e5484 2026-09-17 17:13:53 -0300 docs(cierre): close the backlog to 31/0/0 and declare criterion adjustments
94fc455 2026-09-15 17:02:40 -0300 docs(traceability): update story coverage after the partial stories change
f8a2b10 2026-09-10 15:40:03 -0300 docs(closure): update partial story evidence
11eca72 2026-09-10 15:17:09 -0300 docs(cierre): record encrypted quarantine controls
0ab8298 2026-09-10 15:03:29 -0300 docs(cierre): align verified fixes and run 4 results
864b672 2026-09-10 14:49:33 -0300 docs(cierre): record verified run 4 drain result
f69e450 2026-09-10 13:44:56 -0300 docs(experiments): record absence and drainage evidence
7115511 2026-09-10 01:49:42 -0300 docs(cierre): consolidate verified technical evidence
```

Importante: todas las citas internas del corpus de cierre a `docs/cierre/MATRIZ_TRAZABILIDAD.md`
y `docs/trazabilidad_us_tests.md` **siguen escritas con la ruta vieja** y hay que reescribirlas
en la v18. `tesis/MIGRACION_DOCS_A_TESIS.md:64` inventaria el trabajo pendiente: 8 citas a
`docs/trazabilidad_us_tests.md` y 3 a `resultados/entorno.txt`.

### A7.2 — Commit de la matriz que respalda el recuento 23/8/0 del candidato `7a7ee50`

**No existe una versión de `MATRIZ_TRAZABILIDAD.md` que produzca 23/8/0.** Ese recuento no
sale de la matriz: sale de la **Tabla 22 del documento de tesis del candidato consolidado
V10**, recompuesta de forma independiente por la auditoría externa. La matriz solo lo
**registra** como conteo histórico ajeno.

Procedencia — `tesis/cierre/MATRIZ_TRAZABILIDAD.md`, línea 169:

```
| **23 / 8 / 0** | Tabla 22 del candidato consolidado V10, recompuesta de forma independiente por la auditoría externa | rama `integration/v10`, commit `7a7ee50`, 2026-09-12 | Midió el candidato V10 **antes** del Change 55. Sus 8 parciales eran US-01, US-05, US-11, US-12, US-21, US-23, US-27, US-29 |
```

`tesis/cierre/CIERRE_CONSOLIDADO.md`, línea 166:

```
| Tabla 22 del candidato consolidado V10 (`7a7ee50`), recompuesta por AUDITORIA_INTEGRAL_TESIS_V10.md §3.E | rama `integration/v10`, 2026-09-12 | **23** | **8** | 0 | Verificado de forma independiente por la auditoría, con reserva propia: "en el peor caso, el recuento defendible sería 22-23 completas" (riesgos N-4, N-8) |
```

`tesis/cierre/CIERRE_CONSOLIDADO.md`, línea 229 — origen nominal de las ocho parciales:

```
La propia auditoría recompone independientemente la Tabla 22 del candidato V10 y confirma
**23 completas + 8 parciales + 0 sin cobertura = 31**, con dos reservas explícitas: US-08
(riesgo N-8, ver §11) y US-24 (riesgo N-4: los criterios dinámicos 4–10 se probaron en la
cabeza de carril `37fee44`, no en `7a7ee50` mismo). Las 8 historias parciales del candidato
V10 son: **US-01, US-05, US-11, US-12, US-21, US-23, US-27, US-29**
(`AUDITORIA_INTEGRAL_TESIS_V10_METRICAS.json`, campo `partial_ids`).
```

El commit de referencia del candidato es:

```
$ git log -1 --date=iso --pretty='%h %ad %s' 7a7ee50
7a7ee50 2026-09-12 18:08:21 -0300 test(e2e): reuse the US-25 rule when the combined run hits the US-15 duplicate check
```

Y el commit de la matriz que **documenta** (no que produce) ese 23/8/0 es **`66e5484`**
(`2026-09-17 17:13:53 -0300`, *docs(cierre): close the backlog to 31/0/0 and declare
criterion adjustments*), que es el que agregó tanto la tabla de reconciliación de conteos
como la sección «Ajustes de criterio declarados».

> **Salvedad obligatoria.** El archivo `AUDITORIA_INTEGRAL_TESIS_V10_METRICAS.json`, que es
> la fuente nominal de `partial_ids`, **no está versionado** en el repositorio
> (`.gitignore:59` excluye `/tesis/cierre/AUDITORIA_INTEGRAL_TESIS_V*`). La lista de las
> ocho historias está acreditada por las dos citas de arriba, no por el JSON original.

### A7.3 — ¿Alguna de las 8 parciales está implementada con el criterio ORIGINAL?

**Sí: exactamente una — US-21.** Y solo una.

Cruzando las ocho parciales del candidato V10 contra la tabla «Ajustes de criterio
declarados» de `tesis/cierre/MATRIZ_TRAZABILIDAD.md` (líneas 59-90):

| Historia (parcial en `7a7ee50`) | ¿Depende de un ajuste de criterio? | ¿Ese ajuste es `cc73c2d`? | ¿Cuenta con criterio original? |
|---|---|---|---|
| US-01 | Sí — D70/RN-164, texto de la ruta de redirect | **Sí** | No |
| US-05 | Sí — D6/RN-107 (reescritura de RN-102), banner amarillo sin umbral | **Sí** | No |
| US-11 | Sí — D71/RN-165 (ratifica D2), hash del evento aprobado | No (`sin commit propio de texto`, 2026-09-17) | No |
| US-12 | Sí — D66/RN-160, `ruleset_version` fuera de los comandos de acción | **Sí** (D66/RN-160 se agregó en `cc73c2d`, a `docs/reglas_de_negocio.md`) | No |
| **US-21** | **No** | **No** | **Sí** |
| US-23 | Sí — D6/RN-107, fila en fallo terminal | **Sí** | No |
| US-27 | Sí — D70/RN-164, texto de la ruta de redirect | **Sí** | No |
| US-29 | Sí — D6/RN-107 y D70/RN-164, condición del banner y ruta del link | **Sí** | No |

La matriz lo dice de forma directa (`tesis/cierre/MATRIZ_TRAZABILIDAD.md`, líneas 59-69):

```
## Ajustes de criterio declarados

Siete historias cuentan como `COMPLETA` porque su texto canónico en `docs/historias_de_usuario.md`
fue ajustado para leerse conforme a una decisión de arquitectura o de negocio, no porque el código se
haya adaptado al texto original. `cc73c2d` (2026-09-15) hizo la mayoría de estos ajustes sin declarar
en ese momento qué decisión los respaldaba; las decisiones D66/RN-160, D70/RN-164 y D71/RN-165
formalizan esa relación de forma retroactiva. [...] US-07 y US-21 **no** figuran acá: cerraron en
este mismo corte por cambio de código (D72/RN-166 y el selector de siete estados), no por ajuste de
criterio.
```

Y en el conteo estricto (`tesis/cierre/MATRIZ_TRAZABILIDAD.md`, líneas 95-99):

```
**Conteo estricto — historias completas cuyo texto canónico no fue ajustado: 24 / 31.** Se calcula
restando del 31/0/0 las siete historias con al menos una fila en "Ajustes de criterio declarados":
US-01, US-05, US-11, US-12, US-23, US-27 y US-29. US-07 y US-21 **no** se restan: cerraron por cambio
de código sobre un texto canónico que no cambió (el selector de siete estados y D72/RN-166
respectivamente), no por un ajuste de criterio.
```

Contenido literal de `cc73c2d`, para que se vea exactamente a qué historias tocó:

```
$ git show --stat cc73c2d
commit cc73c2d64267bb60269b23908979d40c06d20976
Date:   Tue Sep 15 17:02:40 2026 -0300

    docs(decisions): add D66 and align stories and roadmap with the audit fixes

 CHANGES.md                   | 22 ++++++++++++----------
 docs/arquitectura_stack.md   |  1 +
 docs/historias_de_usuario.md | 14 +++++++-------
 docs/reglas_de_negocio.md    | 26 ++++++++++++++++++++++++--
```

```
$ git show cc73c2d -- docs/historias_de_usuario.md
-- [ ] ... el frontend redirige a `/account/change-password` (W20, detalle en US-27).      ← US-01
+- [ ] ... el frontend redirige a `/change-password` (W20, detalle en US-27).
-- [ ] Si hay notificaciones externas fallidas (`failed_notifications` con `retry_count >= 3`), ...  ← US-05
+- [ ] Si hay notificaciones externas en fallo terminal (`alerts` con `delivered_at IS NULL AND failed_at IS NOT NULL`, D6/RN-102), ...
-- [ ] Si ningún canal externo pudo entregar, se persiste una fila en `failed_notifications(...)` (W11) ...  ← US-23
+- [ ] Si ningún canal externo pudo entregar, la fila de `alerts` queda en fallo terminal ... (W11, tabla unificada por D6/RN-107) ...
-- [ ] El frontend redirige forzosamente a `/account/change-password` ...                  ← US-27
+- [ ] El frontend redirige forzosamente a `/change-password` ...
-- [ ] Cuando la tabla `failed_notifications` tiene al menos 1 fila con `retry_count >= 3`, ...      ← US-29
-- [ ] El banner incluye un link que abre la vista `/notifications/failed`.
+- [ ] Cuando `alerts` tiene al menos 1 fila en fallo terminal (...), ...
+- [ ] El banner incluye un link que abre la vista `/alerts/failed`.
```

```
$ git show cc73c2d -- docs/reglas_de_negocio.md | rg '^\+' | rg -i 'D66|RN-160'
+#### D66 / RN-160: Los comandos de acción sobre eventos no llevan `ruleset_version`
```

**Las reclasificaciones que dependen del criterio ajustado no cuentan, y son siete de las
ocho: US-01, US-05, US-11, US-12, US-23, US-27 y US-29.** Seis de ellas (US-01, US-05,
US-12, US-23, US-27, US-29) dependen directamente de `cc73c2d`. US-11 depende de otro
ajuste —D71/RN-165, del 2026-09-17, sin commit propio de texto— pero es igualmente un
ajuste de criterio y tampoco cuenta como cumplimiento del criterio original.

### A7.4 — US-21: prueba por criterio y ejecución sobre el candidato final

US-21 cerró **por cambio de código sobre un texto canónico que no se modificó**. El
sub-criterio que la mantenía parcial era el banner de presión de cola de W3: la historia y
W3 pedían un **flag booleano**, y el agente emitía un float 0..1. La solución fue alinear
el código, no el texto.

`tesis/cierre/MATRIZ_TRAZABILIDAD.md`, línea 47 (fila de US-21), extracto:

```
**Cerrada por cambio de código (D72/RN-166, Change 57, grupos 2 a 4).** El décimo sub-criterio
ya no diverge: el agente calcula `queue_pressure_high` (booleano, `true` al superar 0,8 de una
sola lectura del ratio, `agent/queue.py::QUEUE_PRESSURE_HIGH_THRESHOLD`) y lo publica junto al
float `queue_pressure` sin cambios (`agent/heartbeat.py::_publish`). [...]
Los diez sub-criterios canónicos tienen implementación y aserción; no es un ajuste de criterio,
el texto de W3 no cambió, el código se alineó a él
```

Implementación: commit **`2d07cb2`** (`2026-09-17 16:53:55 -0300`, *feat(agents): add
queue_pressure_high flag and close remaining backlog test gaps*), migración
`021_add_agent_queue_pressure_high.sql`, `agent/heartbeat.py:110`.

#### Pruebas por criterio y su ejecución sobre el candidato congelado

El candidato final congelado es **`v1.0-tesis` = `7a906c202e417aec5f03d9a7545e216a724aca81`**
(`2026-09-17 18:30:53 -0300`), y sus suites están en
`tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/suites/`. Procedencia:

```
$ bat --plain tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/suites/procedencia.txt
candidate_commit=7a906c202e417aec5f03d9a7545e216a724aca81
candidate_tag=v1.0-tesis
agent_tree_matches_candidate=yes
frontend_tree_matches_candidate=no
backend_run_from=detached worktree at 7a906c2
postgres=postgres:18.3 on 127.0.0.1:55440 (isolated, not the lab database)
valkey=valkey/valkey:9.0.3 on 127.0.0.1:55441 (isolated, plaintext)
```

Resultado literal de cada caso, extraído de los JUnit de ese paquete (ningún `<failure>`
ni `<error>` en ninguno):

**Agente — `suites/agente.xml`:**

```
<testcase classname="tests.test_heartbeat_queue_pressure_high" name="test_pressure_above_threshold_flag_true" time="0.002" />
<testcase classname="tests.test_heartbeat_queue_pressure_high" name="test_pressure_well_below_threshold_flag_false" time="0.001" />
<testcase classname="tests.test_heartbeat_queue_pressure_high" name="test_pressure_exactly_at_threshold_flag_false" time="0.001" />
<testcase classname="tests.test_heartbeat_queue_pressure_high" name="test_flag_is_bool_not_int" time="0.001" />
<testcase classname="tests.test_heartbeat_queue_pressure_high" name="test_signature_verifies_over_payload_with_new_key" time="0.001" />
```

**Backend — `suites/backend.xml`:**

```
<testcase classname="tests.test_agent_mgmt"        name="test_agents_expose_queue_pressure_high" time="0.126" />
<testcase classname="tests.test_heartbeat_consumer" name="test_queue_pressure_high_persisted" time="0.126" />
<testcase classname="tests.test_heartbeat_consumer" name="test_queue_pressure_high_absent_does_not_reset" time="0.133" />
<testcase classname="tests.test_heartbeat_consumer" name="test_queue_pressure_high_non_bool_ignored[1]" time="0.128" />
<testcase classname="tests.test_heartbeat_consumer" name="test_queue_pressure_high_non_bool_ignored[0]" time="0.123" />
<testcase classname="tests.test_heartbeat_consumer" name="test_queue_pressure_high_non_bool_ignored[true]" time="0.157" />
<testcase classname="tests.test_heartbeat_consumer" name="test_queue_pressure_high_never_reported_reads_as_null" time="0.100" />
```

**Frontend — `suites/frontend.xml`:**

```
<testcase classname="src/components/ui/AgentCard.test.tsx" name="AgentCard — banner de presión de cola alta (US-21/W3, D72/RN-166) > queue_pressure_high: true muestra el banner de alerta específico del agente" time="0.021819824">
<testcase classname="src/components/ui/AgentCard.test.tsx" name="AgentCard — banner de presión de cola alta (US-21/W3, D72/RN-166) > el flag decide aunque el ratio diga otra cosa: ratio 0.95 con flag false no muestra el banner y la barra dice 95%" time="0.014666691">
<testcase classname="src/components/ui/AgentCard.test.tsx" name="AgentCard — banner de presión de cola alta (US-21/W3, D72/RN-166) > el flag en verdadero muestra el banner con cualquier ratio: 0.5 con flag true" time="0.029390068">
<testcase classname="src/components/ui/AgentCard.test.tsx" name="AgentCard — banner de presión de cola alta (US-21/W3, D72/RN-166) > un agente anterior a la clave (queue_pressure_high null/ausente) no muestra el banner ni rompe la tarjeta" time="0.013327679">
```

Totales de esas suites, según
`tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/suites/RESULTADO.md`:

```
| Suite | Tests | Failures | Errors | Skipped |
|---|---|---|---|---|
| Agent | 642 | **0** | 0 | 1 |
| Backend | 839 | **8** | 0 | 4 |
| Frontend | 260 | **0** | 0 | 0 |
```

Los ocho fallos del backend son de arnés (`OSError: [Errno 98] ... bind on address
('0.0.0.0', 8443): address already in use` en los tests que levantan el ciclo de vida real
con `TestClient`), y ninguno de ellos es de los tests de US-21 listados arriba.

#### Salvedades obligatorias sobre US-21

1. **US-21 NO estaba cerrada en `7a7ee50`.** En el candidato consolidado V10 seguía
   parcial, y por la misma divergencia. `tesis/cierre/MATRIZ_TRAZABILIDAD.md:151`:
   `| US-21 | Completa | **Parcial** | El heartbeat emite un float 0..1, no el flag booleano
   que exigen el criterio y W3; el texto canónico no fue corregido | lanes/l5/CRITERIOS.md:54;
   agent/queue.py:600 |`. El cierre ocurrió cinco días después, en `2d07cb2`.
2. **El corte 31/0/0 no está sobre un candidato con custodia.** `tesis/cierre/CIERRE_CONSOLIDADO.md`
   deja registrado que el corte sobre `devel` «no corresponde a un candidato consolidado con
   custodia». El paquete `oficial-cap5-20260917T223823Z` sí congela `v1.0-tesis` (`7a906c2`),
   posterior a `2d07cb2`, y es el que respalda la ejecución citada arriba.
3. **`frontend_tree_matches_candidate=no`** en la procedencia de ese paquete. Las cuatro
   aserciones de `AgentCard.test.tsx` corrieron sobre un árbol de frontend que la propia
   procedencia declara no idéntico al del candidato. Los siete tests de agente y backend sí
   corrieron contra árboles que coinciden con el candidato (`agent_tree_matches_candidate=yes`,
   `backend_run_from=detached worktree at 7a906c2`).

---

## Lo que no pude determinar y por qué

1. **A1 — `uname -r` del anfitrión de la batería histórica.** *No se conservó.* El archivo
   que lo contenía, `resultados/entorno.txt`, nunca se versionó (`.gitignore:47-48`), no
   está en el árbol de trabajo y de él solo sobrevive el hash
   `3d9f689d0a63805d214545cb8968af7355788a25473fc13555ba1f4fae9bc915`
   (`tesis/cierre/evidencia/INDICE.md:11`). No hay ninguna otra fuente en el repositorio
   que registre el núcleo de esa corrida.

2. **A1 — tipo de sistema de archivos del directorio monitoreado en la batería histórica.**
   *No se conservó.* Mismo archivo, mismo motivo. El `ext4` que figura en el corpus
   corresponde a la corrida causal del 2026-09-10 y al ensayo A-3, no a la del 2026-08-19.

3. **A1 — identidad del anfitrión de la batería histórica.** *No se conservó.* La topología
   está declarada (CO-RESIDENTE), pero no el host. Por lo tanto **no se puede establecer si
   el núcleo cambió** entre el 2026-08-19 y hoy: no hay con qué comparar. La coincidencia
   del `7.0.0-31-generic` actual con el de las corridas de septiembre no prueba nada sobre
   agosto.

4. **A2 — log de arranque y manifiesto crudos del generador en la Batería 5 histórica.**
   *No se conservaron.* `resultados/bateria5_manifiesto.jsonl` solo existe como hash. El
   valor `seed=555` está acreditado por `tesis/dataset_cap5.md:207`, asentado el día
   siguiente a la corrida en `ab86c11`, no por el artefacto crudo.

5. **A3 — commit exacto en que se redactó la definición de la Tabla 4.** *No existe tal
   commit.* Los documentos de tesis `.docx` de cierre (v5 a v13) están excluidos por
   `.gitignore:61` y nunca se versionaron; su única marca temporal es la fecha de
   modificación del sistema de archivos. Además, el documento de origen que cita el
   registro de cambios de v5 —`Tesis_v5_cierre_tecnico_aplicado (1).docx`— no está en el
   repositorio, de modo que **no se puede descartar que la redacción existiera antes del
   2026-09-10 19:21**. Lo que sí queda probado con commits es que el criterio **anterior a
   la batería** (`24b339e`, 2026-06-30, y `tesis/plan_medicion_cap5.md` al 2026-08-19)
   medía la preservación contra las operaciones **generadas**, y que la separación
   explícita de categorías se propuso por primera vez en `7115511`, el 2026-09-10 — en
   ambos casos, **después** de la batería del 2026-08-19.

6. **A3 — marcas UTC de inicio y fin de la Batería 5.** *No se conservaron.*
   `resultados/cronologia_utc.txt` (hash
   `5fdc3a37bdd728b97847c4e88f22ab2107694c5486482a21cda87947c0105cfc`) tampoco se versionó.
   La única fecha acreditable de la corrida es la del día, 2026-08-19, y el commit
   `77f0c53e`.

7. **A5 — datos crudos de la Batería 8 (`mmap`).** *No existen en el repositorio.*
   `resultados/bateria8/{bateria8_cambios.jsonl, bateria8_manifiesto.json,
   bateria8_correlacion.csv}` nunca entraron a ningún árbol de commit. La mediana de 9,5 ms
   y su n = 10 sobreviven únicamente como resumen agregado en
   `tesis/informe/Tabla 17-datos.md`, y **no son recomputables** desde el repositorio.

8. **A7 — `AUDITORIA_INTEGRAL_TESIS_V10_METRICAS.json`.** *No está versionado*
   (`.gitignore:59`). Es la fuente nominal del campo `partial_ids` que nombra las ocho
   historias parciales del candidato V10. La lista queda acreditada por dos documentos de
   cierre que la reproducen (`CIERRE_CONSOLIDADO.md:229` y `MATRIZ_TRAZABILIDAD.md:169`),
   no por el JSON original.

9. **A7 — ejecución de los tests de US-21 sobre `7a7ee50`.** *No existe.* Los tests que
   cierran US-21 se escribieron en `2d07cb2` (2026-09-17), cinco días posterior al
   candidato `7a7ee50` (2026-09-12). La ejecución que sí existe es sobre `v1.0-tesis`
   (`7a906c2`), y está sujeta a la salvedad `frontend_tree_matches_candidate=no` para las
   cuatro aserciones de frontend.
