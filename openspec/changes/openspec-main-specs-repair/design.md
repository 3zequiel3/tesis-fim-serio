## Context

Los artefactos de `openspec/specs/` son el registro normativo del proyecto: lo que el sistema debe hacer, aprobado y archivado change por change. Hoy ese registro está dañado por dos defectos con una causa común — varios archives escribieron la main spec copiando el delta verbatim en lugar de mergearlo.

Medido sobre el repositorio:

- **29 specs** con estructura inválida → **110 requisitos invisibles** para `validate`, `list` y `archive`.
- **8 capabilities** con **44 requisitos borrados**, recuperables desde los deltas archivados.
- `openspec validate --specs`: **9 passed, 31 failed** de 40.

La restricción central del diseño es que **la fuente de verdad para la recuperación son los deltas archivados**, no la memoria ni la inferencia. Todo requisito restituido debe poder señalarse a un archivo bajo `openspec/changes/archive/`.

## Goals / Non-Goals

**Goals:**

- Que las 40 specs pasen `openspec validate --specs`.
- Que los 44 requisitos borrados vuelvan, con su texto histórico y sin reescritura.
- Que ningún requisito hoy presente se pierda durante la reparación.
- Que un archive futuro mal hecho falle de inmediato en vez de dañar en silencio.

**Non-Goals:**

- Redactar requisitos nuevos o mejorar la redacción de los recuperados.
- Completar los `## Purpose` con texto de diseño.
- Reconciliar spec contra código: si un requisito recuperado ya no describe lo implementado, se registra como hallazgo, no se edita acá.
- Recuperar lo que nunca dejó rastro en el archivo.

## Decisions

### D-1. La reconstrucción aplica los deltas en orden cronológico de archive

El nombre del directorio de archive empieza con `YYYY-MM-DD`, así que el orden es determinable sin heurística. Para cada capability se recorren sus deltas de más viejo a más nuevo aplicando la semántica de cada bloque: `ADDED` agrega, `MODIFIED` reemplaza el requisito con el mismo header, `REMOVED` lo saca, `RENAMED` lo renombra.

**Alternativa descartada**: tomar la unión de todos los requisitos vistos alguna vez. Es más simple y está mal — resucitaría requisitos legítimamente eliminados y restituiría versiones viejas de requisitos que después se modificaron. La unión sirve como **verificación** (¿falta algo?), no como reconstrucción.

**Dato que habilita esto**: no existe ningún `## RENAMED Requirements` en el archivo actual, y los `## REMOVED` son pocos y explícitos. La reconstrucción es tratable.

### D-2. Cada capability se repara y se revisa individualmente, no en lote

Un script que recorra las 29 y aplique el patrón produciría un diff de miles de líneas que nadie va a leer, y el modo de falla de esta reparación es exactamente ese: pasa `validate` habiendo perdido contenido.

Las **21 del caso simple** admiten transform mecánico porque el cambio es de dos líneas de encabezado y el contenido no se toca — ahí la verificación por conteo alcanza. Las **8 con pérdida** se revisan a mano, una por una, comparando contra sus deltas.

### D-3. `agent-decision-engine` es el caso que exige criterio

Es la única con `## MODIFIED Requirements` en la main spec y sin título. La tocaron tres changes archivados, y perdió 5 requisitos. Reconstruirla es aplicar D-1 sobre esos tres en orden. Si al hacerlo aparece una ambigüedad genuina —dos deltas que modifican el mismo requisito de formas incompatibles sin que el orden lo resuelva—, corresponde **detenerse y preguntar**, no elegir una interpretación y seguir.

### D-4. El `## Purpose` recuperado dice de dónde salió

Los archives correctos generan `TBD - created by archiving change <name>`. Las specs reparadas llevan una marca equivalente que nombra este change y el motivo. Nunca un Purpose redactado como si fuera decisión de diseño: un lector futuro no debe poder confundir texto de reparación con intención original.

### D-5. La guarda de regresión verifica tres invariantes, no una

Sólo validar estructura dejaría pasar el defecto 2, que es el grave. La guarda afirma, por cada spec:

1. No contiene encabezados de delta (`## ADDED|MODIFIED|REMOVED|RENAMED Requirements`).
2. Tiene título, `## Purpose` y `## Requirements`.
3. **Su conjunto de requisitos incluye todo lo que sus deltas archivados agregaron y no removieron explícitamente.**

La tercera es la que hubiera atajado los 44 borrados el día que ocurrieron.

## Risks / Trade-offs

**[Riesgo] Restituir una versión vieja de un requisito modificado después.**
→ D-1 lo evita aplicando en orden cronológico. Se refuerza revisando a mano el diff de las 8 con pérdida.

**[Riesgo] La reparación pasa `validate` habiendo perdido contenido.** Es el modo de falla más probable y el más silencioso.
→ Conteo por archivo antes/después, más la tercera invariante de la guarda. Nunca una aserción agregada sobre el total: un archivo que pierde 3 y otro que gana 3 se cancelan en un total.

**[Riesgo] Requisitos perdidos sin rastro en el archivo** — de changes nunca archivados o previos a OpenSpec.
→ No son recuperables. Se declaran como tales en el reporte final en vez de simular un corpus completo.

**[Trade-off] 29 archivos en un solo change** produce un diff grande.
→ Se acepta porque el defecto es uno solo y partirlo dejaría el repositorio en un estado mixto por más tiempo. Se compensa con commits por clase de daño: las 21 mecánicas en uno, las 8 con pérdida en commits individuales revisables.

## Migration Plan

1. Guarda de regresión primero, **en rojo**: es la especificación ejecutable de lo que hay que arreglar y evita el circuito de escribir el test después de la reparación, cuando ya sabés qué querés que diga.
2. Las 21 del caso simple, transform mecánico, un commit.
3. Las 7 sin `## Requirements`, un commit.
4. Las 8 con pérdida, un commit por capability, cada uno con su diff revisado.
5. `openspec validate --specs` en 40/40 y la guarda en verde.

**Rollback**: revertir commits. No hay estado externo, ni migración, ni código ejecutable involucrado.

## Open Questions

1. **¿El capítulo de arquitectura de la tesis cita estas specs como evidencia del contrato del agente?** Si lo hace, hoy la cita apunta a archivos vaciados y hay que revisarla. Excede este change pero conviene resolverlo antes de la defensa.
2. **¿Algún requisito recuperado ya no describe lo implementado?** Es posible que el código haya evolucionado durante el período en que la spec estaba oculta y nadie podía contrastarla. Este change los restituye tal cual; reconciliar spec↔código es trabajo aparte.
3. **¿Se corrige la causa raíz en el propio tooling?** La guarda detecta el daño después del hecho. Que `openspec archive` no pueda producirlo sería mejor, pero implica tocar el CLI, que es dependencia externa del proyecto.
