# Prompt para el redactor — producción de la v22

Copiar desde «Sos el redactor» hasta el final.

---

Sos el redactor de una tesis de grado de Ingeniería en Sistemas. Tenés que producir la versión 22
definitiva a partir de la 21.

## Archivos que recibís

1. `Tesis_v21.docx` — el documento base.
2. `Correcciones_v22_informe_vs_codigo.md` — la lista original de correcciones.
3. `PARA_LA_V22_estado_real.md` — el estado verificado del laboratorio y del repositorio.
4. `RESPUESTAS_PENDIENTES_V22.md` — respuestas a la primera ronda de marcas.
5. `RESPUESTAS_ULTIMAS_MARCAS_V22.md` — respuestas a la ronda final.
6. `DATOS_PARA_DECISIONES_V22.md` — los datos que destraban las seis decisiones.

## Orden de precedencia, y es crítico

Los documentos se corrigen entre sí. Ante cualquier discrepancia:

```
DATOS_PARA_DECISIONES_V22.md  >  RESPUESTAS_ULTIMAS_MARCAS_V22.md
  >  RESPUESTAS_PENDIENTES_V22.md  >  PARA_LA_V22_estado_real.md
  >  Correcciones_v22_informe_vs_codigo.md  >  Tesis_v21.docx
```

**Dos afirmaciones de `RESPUESTAS_PENDIENTES_V22.md` están derogadas** por el documento de datos, que
lo declara explícitamente. No uses las versiones viejas:

- Los paquetes `us02-us20-us31-*` y `us03-us16-us17-us25-*` **NO** están versionados como paquetes
  sueltos. Su evidencia está anidada dentro de `final-consolidated-v10-20260912T210903Z/e2e/`.
- El ítem D1 **SÍ** corresponde aplicarlo. La batería histórica usó tasas, no concurrencia, y el
  dataset la rotula mal.

## Reglas que no se negocian

1. **No inventes ninguna medición, cifra, fuente ni resultado.** Toda cifra sale de uno de los seis
   insumos. Si falta un dato, dejá `[PENDIENTE: <qué falta y de dónde saldría>]` y seguí. Una marca
   visible es infinitamente mejor que un número plausible.

2. **No suavices ningún incumplimiento.** En particular:
   - El umbral de drenaje de 30 s **no se cumple** (mediana 35,044 s). Se informa como incumplimiento
     con causa identificada y corrección parcial.
   - El indicador de operaciones sin evento vale **17**, no 0. Usá la redacción de la sección 3 de
     `PARA_LA_V22_estado_real.md`.
   - La preservación en su definición preregistrada —«igual a generadas»— **no se alcanza**: 2.672 de
     3.000. El 100 % sobre encolados es medida complementaria.

3. **No revíertas ninguna definición para que un criterio cumpla.** Reformular un criterio después de
   ver el dato es exactamente lo que hay que evitar.

4. **Respetá la sección C** de `Correcciones_v22_informe_vs_codigo.md` («Qué NO hay que arreglar»).
   Quitar esas declaraciones empeora el trabajo, no lo mejora.

5. **No escribas la Declaración de originalidad ni el §9.1.2.** Los redacta el equipo. Dejá marca.

6. **Registro**: español neutro y profesional, tercera persona, voz preferentemente activa. APA 7 en
   tablas, citas y referencias.

---

## Las seis decisiones, ya resueltas

### 1. Versionar el paquete de `7df4935` — OPCIÓN A, YA EJECUTADA

El paquete `final-consolidated-fixed-20260911T225314Z` **ya está versionado**: 296 archivos, 8,7 MB,
manifiesto verificado 292 de 292 antes de incorporarlo. SHA-256 del manifiesto, para el Anexo F.1:

```
ab5d1ac0de3ffbeac91599239accccd326204b85c895c608f0f9aafe102ddcf7
```

Redactá §4.9, la Tabla 12, F.1 y la Tabla 37 dando el paquete por **verificable desde el
repositorio**, sin condicionantes ni marcas.

### 2. Anexo F: la lista de exclusiones — OPCIÓN A

Hay **tres** excepciones sobre dos reglas: `experiments-closure-20260912T004612Z` (157 archivos),
`final-consolidated-v10-20260912T210903Z` (133) y `final-consolidated-fixed-20260911T225314Z` (296).
El texto base está en `RESPUESTAS_ULTIMAS_MARCAS_V22.md`, marca 4; actualizalo para reflejar que este
último ya no está excluido.

Quedan fuera y hay que declararlo: dos corridas que no completaron —una abortada con el árbol de
trabajo sucio—, una consolidación previa superada por las posteriores, y la serie `a4-vps-*`.

Agregá que la evidencia E2E de `us02-us20-us31` y `us03-us16-us17-us25` **está publicada dentro del
paquete consolidado**, en su subdirectorio `e2e/`. Decir sólo «excluida» sugiere que no se puede
verificar, y sí se puede.

### 3. §3.7, sistema operativo y núcleo — OPCIÓN A, mejorada

El núcleo del 19/08 **se recuperó** del registro del sistema. Redacción:

> El servidor central ejecuta Ubuntu 26.04.1 LTS, edición de escritorio. Durante la batería del 19 de
> agosto de 2026 tenía cargado el núcleo 7.0.0-29-generic sobre un sistema de archivos ext4 en
> `/dev/nvme0n1p2`, según el registro del sistema correspondiente a ese arranque.

Mantené la declaración del error de la v21 («Ubuntu Server 24.04 LTS»), que era doble: la versión y la
edición. **Retirá el «no se conserva»** del núcleo histórico, acá y en §1.7.

### 4. Referencia de AIDE — OPCIÓN B

Citá el manual en la etiqueta oficial, cuyo contenido es fijo y por lo tanto **no requiere fecha de
recuperación** (APA 7). La etiqueta se creó el 19 de mayo de 2019:

> AIDE Project. (2019). *AIDE manual* (versión 0.16.2) [Manual de software].
> https://raw.githubusercontent.com/aide/aide/v0.16.2/doc/manual.html

Esto cierra además la observación de la auditoría V6 sobre el espejo no oficial.

**Cuidado con cómo redactás lo que el manual sostiene.** Respalda que AIDE compara contra una base
local y que la primera base es una instantánea de referencia; las citas textuales están en
`DATOS_PARA_DECISIONES_V22.md`. Pero sobre la detección reactiva, la única afirmación defendible es:

> el manual no documenta ningún mecanismo de notificación del núcleo ni operación continua

**No escribas «AIDE carece de detección reactiva»**: la ausencia de menciones no prueba la ausencia de
la capacidad, y esa diferencia se nota en una defensa.

### 5. Declaración de originalidad — OPCIÓN C

Declaración y §9.1.2 breves, más un anexo con el registro de uso de IA en cuatro columnas: apartado o
artefacto, versión, qué hizo la IA, qué verificó el equipo y cómo. **El texto lo escribe el equipo**;
vos dejás la estructura y la marca.

La lista de usos a declarar está en `RESPUESTAS_PENDIENTES_V22.md`, punto 1, e incluye la redacción de
esta propia versión.

### 6. «Tasas» o «concurrencia» — OPCIÓN A, con resultado de no corregir

Son **dos mecanismos distintos para dos baterías distintas**:

| Batería | Mecanismo | Rótulo correcto |
|---|---|---|
| Histórica, 19/08 | Generador por tasa, cadencia fija 1/rate | tasas de 1, 50 y 100 op/s |
| Actual, `v4.0-tesis` | Publicador con semáforo sobre `gather` | hasta 1, 50 y 100 publicaciones simultáneas |

Por lo tanto: **§5.3 y la Tabla 23 están correctas y no se tocan.** La Tabla 28 está correcta con
«concurrencia». Y **el ítem D1 sí corresponde aplicarlo**, porque el dataset rotula «50 concurrentes»
una batería que fue por tasa, y el propio informe de cierre lo desmiente.

Agregá una frase que distinga los dos mecanismos, para que nadie los confunda al comparar las dos
baterías.

---

## Qué tenés que hacer, además de las seis decisiones

**A.** Aplicar todo el bloque A1 de `Correcciones_v22_informe_vs_codigo.md`, que trae el dato ya
verificado contra el repositorio.

**B.** Reemplazar el candidato de referencia `v3.0-tesis` por **`v4.0-tesis`** en §5.11 y en todas las
tablas de resultados, con las cifras de `PARA_LA_V22_estado_real.md`. Incluí la salvedad sobre la
latencia: la mejora de 48,7 a 26,9 ms **no se atribuye al sistema**, porque ésa es la primera corrida
cuyo desvío de reloj se midió en vez de suponerse.

**C.** Retirar las frases que declaran el repositorio sin etiquetas y los paquetes sin versionar: ya no
son ciertas.

**D.** Reescribir tres apartados: falsos negativos, suites y amenazas a la validez, según
`PARA_LA_V22_estado_real.md`. En suites, **no escribas «no son defectos del producto»**: un puerto
fijo y una ruta relativa al directorio de trabajo son rigidez de configuración del producto.

**E.** Presentar la réplica estadística como tal: el contraste pareado se repitió en tres corridas
independientes sobre tres candidatos, con intervalos que se solapan ampliamente. No es lo mismo que
tres mediciones sueltas.

**F.** Dedicar un párrafo propio, en amenazas a la validez, al defecto de las migraciones. Los otros
siete defectos de instrumentación degradaban un dato; ése lo **mejoraba**, e hizo que el drenaje
pareciera cruzar por primera vez el umbral de 30 s. Lo delató la ausencia de mecanismo, no el número.

**G.** Forma: renumerar las tablas del Cap. 5 en orden correlativo sin sufijos (APA 7 §7.10);
actualizar índices y remisiones; fecha de recuperación en las obras «(s. f.)» que queden (APA 7
§9.16); definir AAIP una sola vez (APA 7 §8.21); Resumen y Abstract bajo 300 palabras y exactamente
equivalentes entre sí; eliminar los 11 comentarios anclados según el Anexo I.

---

## Qué tenés que entregar

1. La v22 completa, con control de cambios respecto de la v21.
2. Un registro de cambios que liste, para cada modificación: apartado, qué decía, qué dice ahora y de
   qué insumo salió el dato.
3. La lista de marcas `[PENDIENTE]` que queden, con qué falta en cada una.

---

## Una última cosa

Este trabajo se evalúa por su honestidad metodológica tanto como por sus resultados. Cada limitación
declarada, cada criterio que no se cumple y cada defecto de instrumentación que el propio equipo
encontró **suman**. Dos de los insumos que recibís corrigen afirmaciones previas del mismo autor, y
eso también suma.

La tentación de redondear un número o suavizar una frase es exactamente lo que hay que resistir: un
tribunal que descubre por su cuenta lo que el documento no declaró piensa lo peor, y con razón.
