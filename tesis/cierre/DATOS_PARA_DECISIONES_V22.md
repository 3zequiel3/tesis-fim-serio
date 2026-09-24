# Datos para las seis decisiones de la v22

Todo lo que sigue es de solo lectura: no se modificó el repositorio. Cada dato trae la evidencia y una
conclusión. Donde un comando falló o un archivo no existe, se dice.

**Dos de las seis decisiones cambian de recomendación con estos datos**, y una de ellas corrige un
error mío anterior. Están señaladas.

---

## Dato 1 — Tamaño del paquete de `7df4935` (decisión 1)

| Medición | Resultado |
|---|---|
| Tamaño total | **8,7 MB** |
| Archivos | **296** (283 visibles más 13 ocultos) |
| Archivos mayores a 50 MB | **ninguno**. El mayor es `custody/candidate.bundle`, de 2,1 MB |
| Verificación del manifiesto | **292 de 292 líneas OK** |
| SHA-256 del `SHA256SUMS` | `ab5d1ac0de3ffbeac91599239accccd326204b85c895c608f0f9aafe102ddcf7` |

**Conclusión: no hay ningún impedimento técnico.** 8,7 MB y ningún archivo cerca del límite de GitHub.
El paquete verifica íntegramente hoy. La **opción A** —versionarlo con una excepción más— es viable y
el hash para F.1 ya está calculado.

---

## Dato 2 — Excepciones del `.gitignore` (decisión 2)

**Sí existe una segunda excepción, y apunta a otro paquete.** Regla vigente en `main`:

```
63: /tesis/cierre/evidencia/a4-vps-*/
69: /tesis/cierre/evidencia/experiments-closure-*/
70: !/tesis/cierre/evidencia/experiments-closure-20260912T004612Z/
71: /tesis/cierre/evidencia/final-consolidated-*/
72: !/tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/
73: /tesis/cierre/evidencia/us02-us20-us31-*/
74: /tesis/cierre/evidencia/us03-us16-us17-us25-isolated-*/
75: /tesis/cierre/evidencia/us03-us25-playwright-*/
```

Son **dos excepciones sobre dos reglas distintas**: una para `experiments-closure-20260912T004612Z`
(candidato `7df4935`) y otra para `final-consolidated-v10-20260912T210903Z` (candidato `7a7ee50`). La
duda del pedido queda resuelta: ambas existen y ambas apuntan a paquetes que **sí** tienen archivos.

Archivos realmente presentes en `main`:

| Paquete | Archivos |
|---|---|
| `experiments-closure-20260912T004612Z` | **157** |
| `final-consolidated-v10-20260912T210903Z` | **133** |
| `a4-vps-*` | 0 |
| `us02-us20-us31-*` | 0 |
| `us03-us16-us17-us25-isolated-*` | 0 |
| `us03-us25-playwright-*` | 0 |
| Los otros tres `final-consolidated` | 0 |

### Corrección de un error mío

En `RESPUESTAS_PENDIENTES_V22.md` informé que las familias `us02-us20-us31-*` y
`us03-us16-us17-us25-*` estaban versionadas, con 59 y 24 archivos. **Es falso.** Esos archivos existen,
pero **anidados dentro** del paquete consolidado:

```
final-consolidated-v10-20260912T210903Z/e2e/e2e-us02-us20-us31/
final-consolidated-v10-20260912T210903Z/e2e/e2e-us03-us16-us17-us25/
```

Mi conteo usó una búsqueda por subcadena que capturó esas rutas anidadas. Los paquetes **sueltos** sí
están excluidos.

**La noticia buena**: la evidencia E2E que la tesis cita **está publicada igual**, dentro del paquete
consolidado. Conviene decirlo así en el Anexo F, porque «excluido» a secas sugiere que no se puede
verificar, y sí se puede.

---

## Dato 3 — Sistema operativo y núcleo del equipo físico el 19/08/2026 (decisión 3)

### 3.1 La incoherencia de fechas, explicada

| Evidencia | Fecha |
|---|---|
| Creación de `/lost+found` | 2026-06-19 04:52:38 -03 |
| Primera entrada del historial de apt | 2026-04-23 |

El historial de apt es **anterior al sistema de archivos**, de modo que esos registros vienen de una
instalación previa y se conservaron. Para lo que se está preguntando no cambia nada: las entradas de
agosto son posteriores al 19/06 y pertenecen a esta instalación.

(`tune2fs -l` habría dado la fecha exacta de creación del sistema de archivos, pero requiere
privilegios que no estaban disponibles sin contraseña. La marca de `/lost+found` es el sustituto
habitual y coincide con la secuencia de núcleos.)

### 3.2 Edición instalada

`ubuntu-desktop` 1.570.3 instalado. **`ubuntu-server` no está instalado.** Sesión `ubuntu:GNOME`.

### 3.3 El núcleo del 19/08 — RECUPERADO

**El journal sí conserva esa fecha.** El arranque `b6eb964d398d464aa1a05c0543b486de` abarca del
2026-08-18 10:55:48 al 2026-08-27 03:14:58, de modo que el 19/08 cae dentro. Su primera línea:

```
ago 18 10:55:48 Eze-Linux kernel: Linux version 7.0.0-29-generic (buildd@lcy02-amd64-113)
(x86_64-linux-gnu-gcc (Ubuntu 15.2.0-16ubuntu1) 15.2.0, GNU ld (GNU Binutils for Ubuntu) 2.46)
#29-Ubuntu SMP PREEMPT_DYNAMIC Fri Jul 17 20:52:35 UTC 2026 (Ubuntu 7.0.0-29.29-generic 7.0.12)
```

**Núcleo del 19/08: `7.0.0-29-generic`.**

Y confirma la versión del sistema por una vía independiente: el compilador que lo construyó es
**GCC 15.2.0 de Ubuntu 26.04**. Ubuntu 24.04 entrega GCC 13.

El sistema de archivos de ese arranque es el mismo de hoy:
`EXT4-fs (nvme0n1p2): mounted filesystem fd0d852c-ce75-463c-b32e-0a9e840360e8`.

### 3.4 Secuencia de núcleos instalados

| Fecha | Núcleo |
|---|---|
| 2026-06-27 | 7.0.0-27 |
| 2026-07-21 | 7.0.0-28 |
| **2026-08-09** | **7.0.0-29** |
| 2026-08-22 | 7.0.0-30 |

El `-29` se instaló el 09/08 y el `-30` recién el 22/08, o sea **después** de la batería. Coincide
exactamente con lo que informa el journal.

### 3.5 Y ninguna traza de 24.04

| Comprobación | Resultado |
|---|---|
| Sufijos `ubuntu0.24.04` en todo el historial | **0** |
| Sufijos `ubuntu0.26.04` | 22 |
| Ejecuciones de `do-release-upgrade` | **ninguna** |

### Conclusión

**La recomendación del pedido era la opción A, y con estos datos conviene mejorarla.** El núcleo ya no
es un dato perdido: se recuperó. La frase de §3.7 puede afirmar, con respaldo:

> El servidor central ejecuta **Ubuntu 26.04.1 LTS**, edición de escritorio. Durante la batería del
> 19 de agosto de 2026 tenía cargado el núcleo **7.0.0-29-generic** sobre un sistema de archivos ext4
> en `/dev/nvme0n1p2`, según el registro del sistema correspondiente a ese arranque.

El «no se conserva» deja de ser necesario. Sigue siendo correcto declarar el error de la versión
anterior, como pide la opción A.

---

## Dato 4 — Manual de AIDE en la versión 0.16.2 (decisión 4)

**4.1 La etiqueta existe** en el repositorio oficial `github.com/aide/aide`:
`refs/tags/v0.16.2`, commit `463797d6164997f746b472f451e9cb4bbebf3a05`.

**4.2 El manual está dentro de la etiqueta.** Documentación presente en ese árbol (76 archivos en
total):

```
doc/manual.html
doc/aide.1.in
doc/aide.conf.5.in
doc/aide.conf.in
```

URL directa y estable:
`https://raw.githubusercontent.com/aide/aide/v0.16.2/doc/manual.html`

**4.4 Respaldo de lo que la tesis afirma**, citas textuales del manual en esa etiqueta:

| Afirmación de la tesis | Cita del manual |
|---|---|
| Verificación contra una base local | «AIDE now reads the database and compares it to the files found on the disk.» |
| Modelo de instantánea como patrón de comparación | «This first AIDE database is a snapshot of the system in it's normal state and the yardstick by which all subsequent updates and changes will be measured.» |

| Ausencia de detección reactiva | Recuento sobre el texto completo del manual |
|---|---|
| `inotify` | 0 menciones |
| `fanotify` | 0 menciones |
| `real-time` / `real time` | 0 menciones |
| `continuous` | 0 menciones |
| `event-driven` | 0 menciones |

**Una salvedad metodológica que conviene respetar**: la ausencia de menciones es evidencia de que el
manual no documenta detección reactiva, no prueba de que el programa no la tenga. La afirmación
defendible es «el manual no documenta ningún mecanismo de notificación del núcleo ni operación
continua», no «AIDE carece de detección reactiva». La segunda formulación es más fuerte de lo que la
fuente sostiene. El manual menciona «daemon» tres veces, en contextos que no se verificaron uno por
uno, así que conviene no construir la negación sobre un recuento.

**Conclusión: la opción B es viable.** La etiqueta contiene el manual, su contenido es fijo y por lo
tanto APA 7 no exige fecha de recuperación. Resuelve a la vez la marca de la fecha y la observación de
la auditoría V6 sobre el espejo no oficial.

---

## Dato 5 — Declaración de originalidad

Sin datos que buscar en el código. Lo resuelve el equipo contra el reglamento de Trabajo Final de la
UTN-FRM.

---

## Dato 6 — Publicador de la batería de notificación el 19/08 (decisión 6)

**6.1 En el commit `77f0c53e` no existía ningún publicador de la batería 4.** El repositorio tenía
seis scripts en total:

```
scripts/README.md
scripts/analisis_control.py
scripts/control_hashing.py
scripts/generador_carga.py
scripts/seed-reglas-lab.sh
scripts/setup-agent.sh
```

**6.2 El generador de carga de esa fecha trabaja por TASA, no por concurrencia.** `generador_carga.py`
en ese commit (blob `f4fd77f4`, 643 líneas):

```python
ap.add_argument("--rate", required=True, type=float, help="Eventos por segundo. Obligatoria.")
...
interval = 1.0 / args.rate
```

Y su propia documentación interna lo dice: «La cadencia es fija (1/rate), no jitterada: se prioriza
reproducibilidad.»

**6.3 El semáforo pertenece al publicador actual**, `bateria4_publicador.py`, que vive en el
laboratorio (`~/fim-lab/`) y **no está versionado**. Usa `asyncio.Semaphore(CONC)` sobre un `gather`,
es decir publicaciones simultáneas en vuelo.

**6.5 El informe de cierre ya había zanjado esto**, en `INFORME_CIERRE_TECNICO.md`:

> | Tasas B4 | 1/50/100 operaciones/s | **No fueron concurrencias simultáneas 1/10/100.** |

**6.6 Y el dataset lo rotula mal.** `tesis/dataset_cap5.md`, Tabla 12:

```
| Secuencial (n=60)       | ... |
| 50 concurrentes (n=99)  | ... |
| 100 concurrentes (n=170)| ... |
```

### Conclusión — CORRIGE UNA RECOMENDACIÓN MÍA ANTERIOR

Son **dos mecanismos distintos para dos baterías distintas**, y hay que mantenerlos separados:

| Batería | Mecanismo | Rótulo correcto |
|---|---|---|
| Histórica, 19/08, candidato `77f0c53e` | Generador por tasa, cadencia fija `1/rate` | **tasas de 1, 50 y 100 op/s** |
| Actual, candidato `v4.0-tesis` | Publicador con semáforo sobre `gather` | **hasta 1, 50 y 100 publicaciones simultáneas** |

Por lo tanto:

1. **§5.3 y la Tabla 23, que describen la batería histórica, están CORRECTAS con «tasas».** No hay que
   tocarlas. Es la opción A del pedido, resuelta en el sentido de «no corresponde corregir».
2. **La Tabla 28, de la batería actual, está correcta con «concurrencia».**
3. **El ítem D1 SÍ corresponde aplicarlo**: `dataset_cap5.md` rotula «50 concurrentes» y «100
   concurrentes» una batería que fue por tasa, y el propio informe de cierre lo desmiente.

En `RESPUESTAS_PENDIENTES_V22.md` yo había dicho lo contrario —que D1 debía invertirse—. **Estaba
mal**: verifiqué el publicador actual y extendí su mecanismo hacia atrás, a una batería que se corrió
con otra herramienta. El dato que lo corrige es que en `77f0c53e` ese publicador todavía no existía.

**6.4 El archivo sin commitear de esa corrida no se puede identificar.**
`tesis/resultados/entorno.txt` consigna «1 archivos sin commitear» pero **no lo nombra**, y ese archivo
no está versionado. No se puede determinar si era el generador. Declararlo así.

---

## Resumen para las seis decisiones

| # | Recomendación del pedido | Qué dicen los datos |
|---|---|---|
| 1 | A — versionarlo | **Confirmada.** 8,7 MB, sin archivos grandes, manifiesto verifica 292/292, hash calculado |
| 2 | A — verificar y escribir | **Confirmada.** Hay dos excepciones, sobre dos reglas distintas, y ambas apuntan a paquetes con archivos |
| 3 | A — redacción actual | **Confirmada y mejorable.** El núcleo del 19/08 se recuperó: `7.0.0-29-generic`. El «no se conserva» ya no hace falta |
| 4 | B — citar la etiqueta v0.16.2 | **Confirmada.** La etiqueta existe y contiene `doc/manual.html`. Con una salvedad sobre cómo redactar la ausencia de detección reactiva |
| 5 | C — anexo con registro de uso de IA | Sin datos de código. Lo decide el equipo |
| 6 | A — verificar y corregir | **Verificada, con resultado inverso al que yo había sugerido.** «Tasas» es correcto para la batería histórica; D1 sí corresponde aplicarlo |
