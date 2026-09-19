# Datos para la V15 — Nivel 1 del plan de corrección V14 → V15

**Base:** `Plan_de_Correccion_V14_a_V15.md`, nivel 1 (puntos 1.1 a 1.5), que el plan identifica como el
conjunto que cierra las condiciones puramente documentales.
**Fecha de relevamiento:** 19 de septiembre de 2026.
**Método:** cada dato se verificó contra el árbol del repositorio en la rama `devel` o contra las
páginas de manual instaladas en el equipo. No hay ninguna cifra tomada de memoria ni de una versión
anterior del documento.

---

## 1.1 Banderas de fanotify y versión mínima de kernel

### Banderas que el agente aplica realmente

Relevadas sobre el código, no sobre la documentación previa.

**Inicialización** — `agent/detector.py:454-455` pasa `FAN_CLASS_NOTIF | FAN_CLOEXEC`, y
`agent/_fanotify.py:136` **fuerza además** `FAN_REPORT_DFID_NAME` en toda inicialización
(`flags |= FAN_REPORT_DFID_NAME`), que a su vez es sinónimo de `FAN_REPORT_DIR_FID | FAN_REPORT_NAME`
(`agent/_fanotify.py:40`).

**Marca** — `agent/detector.py:475` usa `FAN_MARK_ADD | FAN_MARK_FILESYSTEM`; las exclusiones
(`:516-519`) agregan `FAN_MARK_IGNORED_MASK | FAN_MARK_IGNORED_SURV_MODIFY`; el reinicio de marcas
(`:528`) usa `FAN_MARK_FLUSH | FAN_MARK_FILESYSTEM`.

**Máscara de eventos** — `agent/detector.py:465-471` y `:507-513`:
`FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE`.

### Versión de introducción de cada bandera

Verificado contra `man 2 fanotify_init` y `man 2 fanotify_mark` instalados en el equipo de trabajo.
Las banderas sin anotación de versión en la página de manual pertenecen a la interfaz original, que
se introdujo en Linux 2.6.37.

| Bandera | Dónde se usa | Introducida en |
|---|---|---|
| `FAN_CLASS_NOTIF` | init, `detector.py:455` | 2.6.37 (interfaz original) |
| `FAN_CLOEXEC` | init, `detector.py:455` | 2.6.37 (interfaz original) |
| `FAN_REPORT_DIR_FID` | init, forzada en `_fanotify.py:136` | **5.9** |
| `FAN_REPORT_NAME` | init, forzada en `_fanotify.py:136` | **5.9** |
| `FAN_REPORT_DFID_NAME` | sinónimo de las dos anteriores | **5.9** |
| `FAN_MARK_ADD` | mark, `detector.py:475` | 2.6.37 (interfaz original) |
| `FAN_MARK_FILESYSTEM` | mark, `detector.py:475` | 4.20 |
| `FAN_MARK_IGNORED_MASK` | exclusiones, `detector.py:518` | 2.6.37 (interfaz original) |
| `FAN_MARK_IGNORED_SURV_MODIFY` | exclusiones, `detector.py:519` | 2.6.37 (interfaz original) |
| `FAN_MARK_FLUSH` | reinicio, `detector.py:528` | 2.6.37 (interfaz original) |
| `FAN_CLOSE_WRITE` | máscara, `detector.py:466` | 2.6.37 (interfaz original) |
| `FAN_CREATE` | máscara, `detector.py:470` | **5.1** |
| `FAN_DELETE` | máscara, `detector.py:467` | **5.1** |
| `FAN_MOVED_FROM` | máscara, `detector.py:468` | **5.1** |
| `FAN_MOVED_TO` | máscara, `detector.py:469` | **5.1** |

### Afirmación que reemplaza a la reserva

El máximo de la columna es **5.9**, y lo determinan `FAN_REPORT_DIR_FID` y `FAN_REPORT_NAME`, que el
agente no puede evitar porque `_fanotify.py:136` las aplica en toda inicialización. Son las que
permiten reconstruir la ruta a partir del identificador del directorio padre más el nombre de la
entrada, que es el mecanismo del que depende la resolución de rutas en modo FID (D46/RN-140).

Texto propuesto, para reemplazar la oración de resguardo:

> La versión mínima de núcleo requerida es **Linux 5.9**, determinada por las banderas
> `FAN_REPORT_DIR_FID` y `FAN_REPORT_NAME` —agrupadas bajo el sinónimo `FAN_REPORT_DFID_NAME`— que
> el agente aplica en toda inicialización del grupo de notificación (`agent/_fanotify.py:136`) y de
> las que depende la reconstrucción de rutas en modo FID. Las banderas de marca sobre sistema de
> archivos completo requieren 4.20 y los eventos de entrada de directorio requieren 5.1, de modo que
> ambas quedan cubiertas por la cota anterior.

**Lo que esta sección NO cierra.** El punto 1.1 del plan pide además, si es viable, un ensayo sobre
un núcleo 5.9 exacto. No se ejecutó. El laboratorio disponible corre 6.8.0 en el anfitrión
monitoreado y 7.0.0 en el servidor central (`docs/cierre/evidencia/oficial-cap5-20260917T223823Z/metadata/entorno.txt`).
La cota 5.9 queda determinada **documentalmente**, por la interfaz que el código exige, y no
ensayada en el borde. Corresponde declararlo con esas palabras y no dejar la reserva anterior.

---

## 1.2 Punto exacto de registro de `detected_at`

### Lo que dice el código

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
2. Cada evento crudo se resuelve a una ruta y se devuelve como `FanEvent`, una tupla que **no tiene
   marca temporal** (`agent/_fanotify.py:90-93`, `:260`).
3. El detector filtra por desbordamiento, ruta nula y alcance, y recién entonces construye
   `FanotifyEvent` estampando la hora (`detector.py:610`).
4. El evento se encola hacia el bucle de eventos (`detector.py:613`), donde después se calcula el hash.

### Afirmación que reemplaza a la imprecisión

> `detected_at` se registra en el hilo lector del agente, en el instante en que el evento del núcleo
> ya fue leído del descriptor de fanotify y su ruta resuelta, e inmediatamente antes de encolarlo
> para su procesamiento (`agent/detector.py:610`). No es la hora en que el núcleo generó el evento
> —fanotify no la provee— ni la hora en que se calcula el hash, que ocurre después. El intervalo
> medido como latencia de detección comprende, por lo tanto, desde ese instante hasta la recepción
> en el backend, y excluye el tiempo que el evento permaneció en la cola del núcleo.

Esa última oración importa: es una **subestimación declarada** de la latencia real, y conviene
decirlo en esos términos en lugar de dejarlo como amenaza a la validez sin resolver.

---

## 1.3 Estado de versionado de los paquetes de evidencia

### Lo que hoy está en el repositorio

`git ls-files docs/cierre/evidencia/` devuelve **166 archivos versionados**, que cubren entre otros
`20260909-coverage-run3`, `absence-20260910T051102Z`, `absence-20260910T052521Z-r2`, la serie
`drenaje-20260910-*` con sus corridas inválidas, y `v10-closure-20260912T190052Z/a3-multihost`.

### Lo que falta y por qué

Los dos paquetes que el plan nombra están excluidos por reglas **explícitas** de `.gitignore`, no por
olvido:

| Paquete | Candidato | Regla que lo excluye |
|---|---|---|
| `final-consolidated-*` | `7a7ee50` | `.gitignore:64` |
| `experiments-closure-*` | `7df4935` | `.gitignore:63` |

Las reglas viven bajo el comentario «Artefactos locales de laboratorio y de cierre todavía no
consolidados» (`.gitignore:54`). Junto a ellas se excluyen también `a4-vps-*` (`:62`),
`us02-us20-us31-*` (`:65`) y `us03-us16-us17-us25-isolated-*` (`:66`).

### Paquete nuevo, listo para versionar

`docs/cierre/evidencia/oficial-cap5-20260917T223823Z/` **no está alcanzado por ninguna regla de
exclusión** y hoy figura como no rastreado. Contiene **69 archivos** con `SHA256SUMS` verificado
69/69, e incluye las Baterías 3, 5 y 7 sobre el candidato `v1.0-tesis`, el diagnóstico causal de
detección, la inferencia pareada y el acta de las corridas puestas en cuarentena. Agregarlo al
repositorio es un `git add` y cierra la parte sustantiva de 1.3 para la corrida que la V15 va a
describir.

### Decisión que hay que tomar y declarar

Versionar los dos paquetes históricos exige **quitar** las reglas `:63` y `:64`. Si se decide no
hacerlo, el Anexo F debe decir textualmente que están excluidos por regla del repositorio y cuál es
el motivo, en lugar de dejar la ausencia sin explicación. El plan admite las dos salidas; lo que no
admite es el silencio.

---

## 1.4 Figuras vectoriales

**No existe fuente editable de ninguna figura.** Se buscó en todo el repositorio por extensión
`svg`, `drawio`, `mmd`, `puml`, `dot` y `excalidraw`: no hay coincidencias. Las **10 figuras** del
documento son PNG sin original.

Esto significa que la primera rama del punto 1.4 —«si existe fuente, regenerarla»— no es aplicable, y
que rige la segunda: **redibujar desde cero** las dos figuras más citadas, que son la de arquitectura
general y la del flujo del agente. El plan es explícito en que no hace falta recuperar el archivo
original, sino producir una figura equivalente en contenido.

Es la única acción del nivel 1 que **no puede resolverse con datos**: requiere redibujar. Queda fuera
del alcance de este documento y se señala como la que el plan marca de mayor visibilidad ante el
tribunal a menor costo relativo.

Mientras tanto, la nota genérica repetida desde la V11 debe reemplazarse por una constancia
específica de esta entrega: que se verificó la inexistencia de fuente editable en el repositorio, con
el criterio de búsqueda usado, y qué se decidió en consecuencia.

---

## 1.5 Registro de cambios por observación

El plan pide una tabla que diga, punto por punto, qué observación de qué informe se abordó y cuál se
dejó pendiente a propósito. Esta es la estructura, con las filas que ya se pueden completar:

| Observación | Informe que la origina | Estado en V15 | Evidencia o motivo |
|---|---|---|---|
| Banderas de fanotify sin cota cerrada | §1.7 / §2.6 | **Cerrada documentalmente** | Cota 5.9 determinada por `FAN_REPORT_DIR_FID` y `FAN_REPORT_NAME`; sin ensayo en el borde, declarado |
| Punto de registro de `detected_at` | §6.4 | **Cerrada** | `agent/detector.py:610`, hilo lector, antes de encolar |
| Paquetes de evidencia sin versionar | Anexo F | **Parcial** | Paquete nuevo de 69 archivos listo; los dos históricos siguen excluidos por `.gitignore:63-64` |
| Figuras rasterizadas | N-4 | **Pendiente deliberada** | No existe fuente editable; requiere redibujar, no recuperar |
| Densidad de oración | N-3 | **Cerrada en V13** | 147 oraciones de más de 40 palabras, 6,15 % del total, contra un objetivo de 12 % |
| Declaración de uso de IA | — | **Cerrada en V12** | Declaración de originalidad y §9.3 unificadas |

Las filas restantes salen del informe de la quinta iteración, que no está en este repositorio.

---

## Nota sobre el nivel 2: dos de sus puntos ya están resueltos

El plan ubica 2.1 y 2.2 en «el 10 hipotético», bajo el supuesto de que exigen trabajo de laboratorio
que no existe. Ese supuesto quedó desactualizado el 18 de septiembre.

**2.1, corrida unificada sobre un único candidato.** Se congeló `v1.0-tesis` (`7a906c2`), se
reconstruyó la imagen del backend desde ese commit y se verificó la procedencia comparando el hash
agregado de todo `app/**/*.py` entre el contenedor y el árbol. Sobre ese candidato corrieron las
Baterías 3, 5 y 7 y las suites de agente, backend y frontend. El paquete está sellado con
`SHA256SUMS`. Falta incorporar las Baterías 2, 8 y 9, que hoy provienen de otros commits.

**2.2, causa de las ausencias.** Se repitió la Batería 3 completa con la instrumentación causal del
propio agente (`agent/experiment_trace.py`). Resultado: 513 eventos recibidos del núcleo para 500
operaciones, 481 clasificados como cambio y **31 suprimidos, todos con causa registrada**
(`matches_active_baseline`). Las 19 operaciones sin evento persistido se explican **19 de 19** por
una supresión con causa, y en las 19 el hash que registró el agente coincide con el que registró el
generador. Es exactamente el resultado que el punto 2.2 pide: una corrida nueva donde toda operación
sin evento tiene causa registrada. Las ausencias históricas quedan como antecedente documentado, que
es lo máximo que el plan admite para ellas.

Evidencia de ambos puntos: `docs/cierre/evidencia/oficial-cap5-20260917T223823Z/`, con actas en
`diagnostico-deteccion/RESULTADO.md`, `control/RESULTADO.md` y `control/MCNEMAR.md`.

Corresponde que la V15 los reporte como cerrados y no como trabajo futuro.
