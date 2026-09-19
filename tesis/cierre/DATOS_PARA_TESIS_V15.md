# Datos para la V15 — Nivel 1 completo del plan de corrección V14 → V15

**Base:** `Plan_de_Correccion_V14_a_V15.md`, informe de auditoría de seguimiento (quinta iteración)
sobre la V14, 19 de septiembre de 2026.
**Alcance:** los cinco puntos del Nivel 1, que el plan identifica como el conjunto que cierra las
condiciones puramente documentales y que corresponde a un dictamen de 9/10.
**Método:** cada dato se verificó contra el árbol del repositorio en la rama `devel` o contra las
páginas de manual instaladas en el equipo. Ninguna cifra viene de memoria ni de una versión anterior.

> **Las rutas del repositorio cambiaron el 19 de septiembre** (commit `76d70ad`). El material de
> tesis se movió de `docs/` a `tesis/`. Este documento ya usa las rutas nuevas. La V15 tiene que
> reescribir las suyas en la misma pasada que aplique estas correcciones: la V14 cita 67 veces
> `docs/cierre`, 8 veces `docs/trazabilidad_us_tests.md` y 3 veces `resultados/entorno.txt`, y las
> tres familias cambiaron de lugar. El detalle está en `tesis/MIGRACION_DOCS_A_TESIS.md`.

---

## 1.1 Banderas de fanotify y versión mínima de kernel

### Banderas que el agente aplica realmente

**Inicialización** — `agent/detector.py:454-455` pasa `FAN_CLASS_NOTIF | FAN_CLOEXEC`, y
`agent/_fanotify.py:136` **fuerza además** `FAN_REPORT_DFID_NAME` en toda inicialización
(`flags |= FAN_REPORT_DFID_NAME`), que es sinónimo de `FAN_REPORT_DIR_FID | FAN_REPORT_NAME`
(`agent/_fanotify.py:40`).

**Marca** — `agent/detector.py:475` usa `FAN_MARK_ADD | FAN_MARK_FILESYSTEM`; las exclusiones
(`:516-519`) agregan `FAN_MARK_IGNORED_MASK | FAN_MARK_IGNORED_SURV_MODIFY`; el reinicio de marcas
(`:528`) usa `FAN_MARK_FLUSH | FAN_MARK_FILESYSTEM`.

**Máscara de eventos** — `agent/detector.py:465-471` y `:507-513`:
`FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE`.

### Versión de introducción de cada bandera

Verificado contra `man 2 fanotify_init` y `man 2 fanotify_mark` instalados en el equipo de trabajo.
Las banderas sin anotación de versión pertenecen a la interfaz original, introducida en Linux 2.6.37.

| Bandera | Dónde se usa | Introducida en |
|---|---|---|
| `FAN_CLASS_NOTIF` | init, `detector.py:455` | 2.6.37 |
| `FAN_CLOEXEC` | init, `detector.py:455` | 2.6.37 |
| `FAN_REPORT_DIR_FID` | init, forzada en `_fanotify.py:136` | **5.9** |
| `FAN_REPORT_NAME` | init, forzada en `_fanotify.py:136` | **5.9** |
| `FAN_REPORT_DFID_NAME` | sinónimo de las dos anteriores | **5.9** |
| `FAN_MARK_ADD` | mark, `detector.py:475` | 2.6.37 |
| `FAN_MARK_FILESYSTEM` | mark, `detector.py:475` | 4.20 |
| `FAN_MARK_IGNORED_MASK` | exclusiones, `detector.py:518` | 2.6.37 |
| `FAN_MARK_IGNORED_SURV_MODIFY` | exclusiones, `detector.py:519` | 2.6.37 |
| `FAN_MARK_FLUSH` | reinicio, `detector.py:528` | 2.6.37 |
| `FAN_CLOSE_WRITE` | máscara, `detector.py:466` | 2.6.37 |
| `FAN_CREATE` | máscara, `detector.py:470` | **5.1** |
| `FAN_DELETE` | máscara, `detector.py:467` | **5.1** |
| `FAN_MOVED_FROM` | máscara, `detector.py:468` | **5.1** |
| `FAN_MOVED_TO` | máscara, `detector.py:469` | **5.1** |

### Texto propuesto, para reemplazar la oración de resguardo

> La versión mínima de núcleo requerida es **Linux 5.9**, determinada por las banderas
> `FAN_REPORT_DIR_FID` y `FAN_REPORT_NAME` —agrupadas bajo el sinónimo `FAN_REPORT_DFID_NAME`— que el
> agente aplica en toda inicialización del grupo de notificación (`agent/_fanotify.py:136`) y de las
> que depende la reconstrucción de rutas en modo FID (D46/RN-140). Las marcas sobre sistema de
> archivos completo requieren 4.20 y los eventos de entrada de directorio requieren 5.1, de modo que
> ambas quedan cubiertas por la cota anterior.

### Versiones de núcleo sobre las que sí se ensayó

Tomadas de `tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/metadata/entorno.txt`, el manifiesto
de entorno del paquete de evidencia:

| Anfitrión | Sistema operativo | Núcleo |
|---|---|---|
| Servidor central | Ubuntu 26.04.1 LTS | **7.0.0-31-generic** |
| Anfitrión monitoreado | Ubuntu 24.04.5 LTS | **6.8.0-139-generic** |

El agente —que es el único componente que usa fanotify— corrió sobre **6.8.0**. El servidor central
no ejecuta fanotify, de modo que su versión de núcleo es contexto del entorno y no un dato de
compatibilidad del agente.

### Cómo cierra el punto 1.1

La reserva se cierra con tres afirmaciones juntas, no con una sola:

1. **La cota es 5.9**, y la determinan `FAN_REPORT_DIR_FID` y `FAN_REPORT_NAME` (tabla anterior).
2. **Se ensayó sobre 6.8.0**, por encima de la cota.
3. **El borde de 5.9 no se ensayó**, y la cota queda establecida por la interfaz que el código exige,
   no por un experimento en esa versión.

Las tres tienen que estar. Enunciar solo la primera deja la cota sin respaldo empírico y sin decirlo;
enunciar solo la segunda deja sin explicar de dónde sale el 5.9. El punto 1.1 del plan admite
explícitamente la tercera como alternativa al ensayo —«si no es viable, decirlo explícitamente y dar
la razón»—, pero exige que se diga, no que se omita.

**Razón por la que no fue viable:** ningún anfitrión del laboratorio corre esa versión, y conseguirla
exige construir o arrancar un núcleo 5.9 de línea principal en una máquina virtual dedicada, lo que
excede el alcance de la corrección documental.

### Dato adicional, por si se quiere usar

El agente **no verifica la versión del núcleo al arrancar**. `agent/preflight.py` existe y hace otras
comprobaciones, pero no hay ninguna lectura de `os.uname().release` ni comparación contra una versión
mínima en todo `agent/`. Es decir: la cota está documentada pero **el producto no la hace cumplir**.
Sobre un núcleo anterior a 5.9 el agente arranca y falla más adelante, cuando `fanotify_init` rechaza
las banderas, con un error que no menciona la versión del núcleo.

Es un dato verificable y honesto que puede incorporarse como limitación, y la corrección natural
—validar la versión en el preflight y abortar con un mensaje explícito— es trabajo futuro concreto y
acotado, mucho más defendible que «habría que probarlo en 5.9».

---

## 1.2 Punto exacto de registro de `detected_at`

`detected_at` se toma de `FanotifyEvent.timestamp` (`agent/detector.py:866`, `:971`, `:1115`), y ese
campo se asigna en un único lugar:

```
agent/detector.py:605-611
    fan_event = FanotifyEvent(
        path=ev.path,
        pid=ev.pid,
        uid=_get_uid(ev.pid),
        exe=_get_exe(ev.pid),
        timestamp=datetime.now(timezone.utc).isoformat(),
        mask=getattr(ev, "mask", 0),
    )
```

La secuencia, en el hilo lector del detector:

1. `os.read` sobre el descriptor de fanotify devuelve el lote de eventos crudos (`agent/_fanotify.py:188`).
2. Cada evento se resuelve a una ruta y se devuelve como `FanEvent`, una tupla que **no tiene marca
   temporal** (`agent/_fanotify.py:90-93`, `:260`).
3. El detector filtra por desbordamiento, ruta nula y alcance, y recién entonces construye
   `FanotifyEvent` estampando la hora (`detector.py:610`).
4. El evento se encola hacia el bucle de eventos (`detector.py:613`); el hash se calcula después.

### Texto propuesto

> `detected_at` se registra en el hilo lector del agente, en el instante en que el evento del núcleo
> ya fue leído del descriptor de fanotify y su ruta resuelta, e inmediatamente antes de encolarlo
> para su procesamiento (`agent/detector.py:610`). No es la hora en que el núcleo generó el evento
> —fanotify no la provee— ni la hora en que se calcula el hash, que ocurre después. El intervalo
> medido como latencia de detección comprende, por lo tanto, desde ese instante hasta la recepción en
> el backend, y **excluye el tiempo que el evento permaneció en la cola del núcleo**, de modo que
> constituye una cota inferior de la latencia real.

Esa última cláusula conviene enunciarla así: una subestimación declarada es un resultado; una
imprecisión sin resolver es una amenaza a la validez.

---

## 1.3 Versionado de los paquetes de evidencia

### Estado actual, después del commit `76d70ad`

`git ls-files tesis/cierre/evidencia` devuelve **236 archivos versionados**, de los cuales **70
corresponden al paquete `oficial-cap5-20260917T223823Z`**, que se incorporó al repositorio en esa
misma migración. El paquete trae `SHA256SUMS` verificado 69/69 sobre sus archivos de contenido e
incluye las Baterías 3, 5 y 7 sobre el candidato `v1.0-tesis`, el diagnóstico causal de detección, la
inferencia pareada de McNemar y el acta de las corridas puestas en cuarentena.

### Los dos paquetes que el plan reclamaba ya están versionados

Las reglas de `.gitignore` se acotaron con una excepción por paquete, de modo que los dos que la
tesis cita como origen de sus resultados entran al repositorio y el resto de la serie sigue fuera:

| Paquete | Candidato | Archivos | Custodia |
|---|---|---|---|
| `experiments-closure-20260912T004612Z` | `7df4935` | 155 | `SHA256SUMS` verificado **155/155** |
| `final-consolidated-v10-20260912T210903Z` | `7a7ee50` | 130 | `SHA256SUMS` verificado **130/130** |

Con esto, quien clone el repositorio puede verificar los resultados que el documento atribuye a esos
dos candidatos, que es lo que el punto 1.3 y el §4.5 piden.

### Declaración para el Anexo F sobre lo que sigue excluido

Texto propuesto, para incorporar donde el Anexo F enumera los paquetes:

> Del conjunto de corridas de consolidación de septiembre de 2026 se versionan las dos que sustentan
> resultados citados en este trabajo: `experiments-closure-20260912T004612Z`, correspondiente a los
> ensayos sobre el candidato `7df4935`, y `final-consolidated-v10-20260912T210903Z`, correspondiente
> al candidato `7a7ee50`. Ambas incluyen su manifiesto de custodia y verifican íntegramente.
>
> Las restantes corridas de esa serie quedan fuera del repositorio por regla explícita: dos intentos
> que no completaron (`final-consolidated-v10-20260912T205729Z-attempt1-failed` y
> `final-consolidated-v10-20260912T210821Z-aborted-dirty-worktree`, este último interrumpido al
> detectarse el árbol de trabajo sucio) y dos consolidaciones previas superadas por las anteriores
> (`final-consolidated-20260911T214511Z` y `final-consolidated-fixed-20260911T225314Z`). Ninguna
> sustenta un resultado del documento. Su exclusión es una decisión de higiene del repositorio y no
> una omisión: se deja constancia de su existencia porque forman parte del registro de cómo se llegó
> a la corrida consolidada, y sus manifiestos quedan disponibles a pedido.

Además siguen excluidos, por la misma regla y con el mismo criterio, los paquetes `a4-vps-*`,
`us02-us20-us31-*` y `us03-us16-us17-us25-isolated-*`.

La tabla F.1 debe actualizarse con las rutas nuevas bajo `tesis/` y con los hashes de los tres
paquetes incorporados: los dos anteriores más `oficial-cap5-20260917T223823Z`.

---

## 1.4 Figuras vectoriales

**La V14 embebe 11 medios y los 11 son PNG.** No hay un solo vectorial.

**No existe fuente editable de ninguna figura.** Se buscó en todo el repositorio por extensión `svg`,
`drawio`, `mmd`, `puml`, `dot` y `excalidraw`: sin coincidencias.

Esto descarta la primera rama del punto 1.4 —«si existe fuente, regenerarla»— y deja vigente la
segunda: **redibujar desde cero** las dos figuras más citadas, la de arquitectura general y la del
flujo del agente. El plan es explícito en que no hace falta recuperar el archivo original, sino
producir una figura equivalente en contenido.

Es **la única acción del Nivel 1 que no se resuelve con datos**: requiere dibujar. Queda fuera del
alcance de este documento.

Mientras tanto, la nota genérica repetida desde la V11 debe reemplazarse por una constancia
específica de esta entrega: que se verificó la inexistencia de fuente editable, con qué criterio de
búsqueda, y qué se decidió en consecuencia.

---

## 1.5 Registro de cambios por observación

| Observación | Origen | Estado en V15 | Evidencia o motivo |
|---|---|---|---|
| Banderas de fanotify sin cota cerrada | §1.7 / §2.6 | **Cerrada documentalmente** | Cota 5.9 por `FAN_REPORT_DIR_FID` y `FAN_REPORT_NAME`; sin ensayo en el borde, declarado |
| Punto de registro de `detected_at` | §6.4 | **Cerrada** | `agent/detector.py:610`, hilo lector, antes de encolar |
| Paquetes de evidencia sin versionar | Anexo F | **Parcial** | 236 archivos versionados, 70 del paquete nuevo; los dos históricos siguen excluidos por `.gitignore:64-65` |
| Figuras rasterizadas | N-4 | **Pendiente deliberada** | 11 de 11 medios son PNG y no existe fuente editable; requiere redibujar |
| Densidad de oración | N-3 | **Cerrada en V13** | 147 oraciones de más de 40 palabras, 6,15 %, contra un objetivo de 12 % |
| Declaración de uso de IA | — | **Cerrada en V12** | Declaración de originalidad y §9.3 unificadas |
| Inferencia pareada nunca ejecutada | §3.6, auditorías V5 a V14 | **Cerrada** | McNemar χ²(1) = 386,5409, p = 4,69 × 10⁻⁸⁶, diferencia pareada 0,8040, IC 95 % de Newcombe [0,7618, 0,8377] |

---

## Nivel 2: dos de sus cuatro puntos ya están resueltos

El plan ubica 2.1 y 2.2 en «el 10 hipotético», bajo el supuesto de que exigen trabajo de laboratorio
que no existe. Ese supuesto venció el 18 de septiembre.

**2.1 — corrida unificada sobre un único candidato.** Se congeló `v1.0-tesis` (`7a906c2`), se
reconstruyó la imagen del backend desde ese commit y se verificó la procedencia comparando el hash
agregado de todo `app/**/*.py` entre contenedor y árbol de trabajo. Sobre ese candidato corrieron las
Baterías 3, 5 y 7. **Falta**: incorporar las Baterías 2, 8 y 9, que hoy provienen de otros commits, y
cerrar la corrida de suites, cuyo arnés todavía produce artefactos que no reflejan la realidad.

**2.2 — causa de las ausencias.** Se repitió la Batería 3 completa con la instrumentación causal del
propio agente (`agent/experiment_trace.py`). Resultado: 513 eventos recibidos del núcleo para 500
operaciones, 481 clasificados como cambio y **31 suprimidos, todos con causa registrada**
(`matches_active_baseline`). Las 19 operaciones sin evento persistido se explican **19 de 19** por una
supresión con causa, y en las 19 el hash que registró el agente coincide con el que registró el
generador. Es exactamente lo que el punto 2.2 pide: una corrida nueva donde toda operación sin evento
tiene causa registrada. Las ausencias históricas quedan como antecedente documentado, que es el
máximo que el plan admite para ellas.

**2.4 — ensayo sobre núcleo 5.9**: no ejecutado, ver 1.1.

**2.5 — densidad de oración**: cerrada en la V13, ver 1.5.

Evidencia de 2.1 y 2.2: `tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/`, con actas en
`diagnostico-deteccion/RESULTADO.md`, `control/RESULTADO.md` y `control/MCNEMAR.md`.

**Corresponde que la V15 los reporte como cerrados y no como trabajo futuro.**

---

## Dato nuevo sobre el ítem 43, que la V15 debería incorporar

El drenaje posterior a la reconexión **no está limitado por rendimiento**. Está limitado por el
`_ACK_TIMEOUT_S = 60.0` del agente (`agent/publisher.py:62`) más la cadencia de `asyncio.sleep(5)` de
su bucle de reintentos (`:613`): durante el corte los eventos quedan pendientes con su marca temporal
original y solo se republican cuando superan los 60 segundos, de modo que los generados en el último
minuto tienen que envejecer antes de salir.

La distribución de llegadas lo muestra: los primeros 15 segundos traen 1047 eventos a 69,9 por
segundo, y la cola llega **en grupos espaciados exactamente 5 segundos**. El perfilado descarta las
demás hipótesis —`bump_attempts` 1,665 ms, escritura atómica 1,687 ms, la misma escritura sin cifrado
1,655 ms, firma HMAC 0,008 ms, `XADD` sobre mTLS 0,457 ms—: la suma conocida es de unos 2,2 ms contra
21,96 ms observados por evento. La diferencia es espera, no trabajo.

Dos consecuencias que conviene enunciar:

1. **El umbral de 30 segundos es inalcanzable con el diseño de reconexión actual**, con independencia
   de la velocidad del backend. No es un problema de capacidad.
2. El cifrado del sobre en cola **no tiene costo apreciable**: 1,687 ms contra 1,655 ms sin cripto.
   El costo es el `fsync`. Es un resultado que vale la pena reportar, porque contradice la intuición
   habitual sobre el precio del cifrado en reposo.

---

# Anexo operativo — anclas exactas para quien edite el documento

Esta sección existe para que la edición sea **mecánica y verificable**, y no una búsqueda por
parecido. Cada reemplazo declara su texto ancla literal y **cuántas veces aparece en la V14**. Quien
edite debe afirmar esa cantidad antes de tocar nada: si el ancla no aparece exactamente ese número de
veces, el documento no es el esperado y hay que detenerse, no aproximar.

Conteos verificados sobre `Tesis_v14_correcciones.docx` el 19 de septiembre de 2026, sobre el texto
plano de `word/document.xml` con espacios normalizados.

## A. Lo que la V14 YA cerró — no volver a tocarlo

| Ancla | Apariciones |
|---|---|
| «esa es la versión mínima que se deriva de las banderas aquí descriptas» | 1 |
| «sujeto a la confirmación» | **0** |

La V14 **ya afirma** que 5.9 es la versión mínima derivada de las banderas, y la fórmula de resguardo
que las auditorías venían señalando **ya no existe** en el documento. El aporte del punto 1.1 de este
informe es el **respaldo verificado** de esa afirmación —la tabla de quince banderas con su versión de
introducción, tomada de las páginas de manual— y no la afirmación en sí. Corresponde incorporar la
tabla como sustento, no reescribir la conclusión.

## B. Reemplazos pendientes, con ancla literal

### B.1 Resguardo de compatibilidad (punto 1.1)

- **Ancla:** `compatibilidad final` — **1 aparición**
- **Acción:** leer la oración completa que la contiene y, si sigue condicionando la cota de núcleo,
  reemplazarla por el texto propuesto en 1.1. Si condiciona otra cosa, **no tocarla** y dejar
  constancia.

### B.2 Punto de registro de `detected_at` (punto 1.2)

Dos anclas distintas, **una aparición cada una**:

- `el documento no precisa en qué punto del agente se registra detected_at` — está en el pasaje de
  amenazas a la validez, junto a la marca del backend.
- `el documento no precisa en qué punto del procesamiento del agente se registra detected_at` — está
  en el pasaje que discute el intervalo (a)→(c) y el resultado histórico de 17,274 ms.

Ambas se reemplazan por el texto de 1.2, adaptando la primera oración al contexto de cada pasaje. La
segunda, además, debe conservar la referencia al intervalo (b)→(c) y a los 17,274 ms: **ese número no
se toca**.

### B.3 Nota genérica de figuras (punto 1.4)

- **Ancla:** `al no existir fuente editable, su tipografía interna no se regeneró` — **2 apariciones**
- **Acción:** reemplazar por una constancia específica de esta entrega, que diga qué se buscó (fuentes
  `svg`, `drawio`, `mmd`, `puml`, `dot`, `excalidraw` en todo el repositorio), qué se encontró
  (ninguna; los 11 medios embebidos son PNG) y qué se decidió. **Las dos apariciones deben quedar
  distintas entre sí** si acompañan figuras distintas: repetir la misma frase genérica por sexta vez
  es exactamente lo que la auditoría viene señalando.

## C. Reescritura de rutas — obligatoria en esta versión

El repositorio se reorganizó el 19 de septiembre (commit `76d70ad`). Las tres familias de rutas que el
documento cita cambiaron de lugar:

| Prefijo viejo | Prefijo nuevo | Apariciones en V14 |
|---|---|---|
| `docs/cierre` | `tesis/cierre` | **67** |
| `docs/trazabilidad_us_tests.md` | `tesis/trazabilidad_us_tests.md` | **8** |
| `resultados/` | `tesis/resultados/` | **3** (todas `resultados/entorno.txt`) |

**Las citas al código NO cambian.** `backend/app/...`, `agent/...`, `frontend/e2e/...` y `scripts/...`
siguen siendo válidas: el código no se movió.

## D. Datos para la tabla F.1 del Anexo F

Los hashes del paquete incorporado **no se transcriben acá a propósito**: están en
`tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/SHA256SUMS`, son 69 y se toman de ahí. Copiarlos
a mano a un documento intermedio es una oportunidad de error sin ninguna ventaja.

La fila del paquete debe declarar: ruta `tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/`,
candidato `v1.0-tesis` (`7a906c2`), 69 archivos de contenido con `SHA256SUMS` verificado 69/69, y el
contenido —Baterías 3, 5 y 7, diagnóstico causal, inferencia pareada y acta de corridas en
cuarentena—.

## E. Verificación después de editar

Que quien edite ejecute y reporte, sobre el archivo generado:

1. **Anclas viejas en cero.** Las cinco anclas de la sección B deben dar 0 apariciones, salvo
   `compatibilidad final` si se decidió no tocarla, en cuyo caso debe justificarse.
2. **Rutas viejas en cero.** `docs/cierre`, `docs/trazabilidad_us_tests.md` y `resultados/` sin
   coincidencias; `tesis/cierre` con 67, `tesis/trazabilidad_us_tests.md` con 8 y
   `tesis/resultados/entorno.txt` con 3.
3. **Cada ruta nueva resuelve** a un archivo o directorio existente del repositorio.
4. **Los números no se movieron.** Verificar que 17,274 · 17,745 · 616,626 · 31,533 · 107,97 ·
   27,784 · 153 · 81,8 % · 9/11 · 5.9 y los recuentos de historias aparezcan la misma cantidad de
   veces que en la V14. Cualquier variación que no sea un número de página del índice es un error.
5. **Índice coherente**: recalcular sobre el render y editar por `<w:t>` individual, nunca el párrafo
   completo del índice.

## F. Lo que este informe NO puede aportar

- **El informe de la quinta iteración no está en este repositorio.** Las filas del registro de cambios
  que correspondan a observaciones suyas hay que tomarlas de ese informe, no de acá.
- **Las figuras hay que dibujarlas.** No hay dato que resuelva el punto 1.4.
- **El ensayo sobre núcleo 5.9 no se ejecutó.** La cota está determinada por la interfaz que el código
  exige, no por un ensayo en el borde, y así debe declararse.
