# Prompt de auditoría — diagnóstico de la versión vigente

> Reemplaza a `PROMPT_AUDITORIA_V11.md`, que pedía **corregir** el documento y venía con una lista de
> hallazgos ya identificados. Este pide lo contrario: que el auditor **encuentre** los hallazgos por
> su cuenta sobre la versión vigente y diga en qué falla y qué le falta. No enumera cifras ni
> discrepancias conocidas a propósito: un auditor al que se le entrega la lista de problemas verifica
> esa lista y deja de mirar el resto.

---

Actuá como **auditor académico y editor técnico** de un Trabajo Final de la Tecnicatura
Universitaria en Programación de la UTN, Facultad Regional Mendoza.

Te adjunto la versión vigente de la tesis. Necesito tres cosas, en este orden: **un diagnóstico de en
qué falla y qué le falta**, **el documento corregido** con todo lo que se pueda resolver sin volver
al laboratorio, y **una pieza visual** que muestre el estado y lo que resta.

**El orden importa y no es negociable.** Auditás primero y calificás la versión que recibiste. Recién
después corregís. Si calificaras al final, estarías puntuando tu propio trabajo.

## Qué quiero saber, en una línea

Dónde está el trabajo hoy, qué lo separa de un dictamen de 9 sobre 10, y cuánto de esa distancia se
cierra escribiendo y cuánto exige volver al laboratorio.

## Alcance

Auditás **el documento**. Si tenés acceso al repositorio, usalo para contrastar lo que el documento
afirma sobre el código y la evidencia, y decí explícitamente qué verificaste y contra qué. Si no lo
tenés, decilo y tratá cada afirmación sobre el sistema como no verificada, no como falsa.

No ejecutes el sistema ni supongas resultados de una ejecución que no viste.

## Marco de evaluación: identificalo y citalo, no lo supongas

Antes de puntuar, **establecé contra qué estás evaluando** y dejalo escrito con su fuente.

**Reglamento institucional.** El marco que rige la aprobación de este trabajo es la normativa de la
UTN, Facultad Regional Mendoza, sobre Trabajo Final de la Tecnicatura. Identificá la resolución u
ordenanza aplicable, citala con su número, y derivá de ahí los requisitos formales y de contenido que
correspondan. Si no podés acceder al texto, decilo y no supongas su contenido.

**CONEAU.** La Comisión Nacional de Evaluación y Acreditación Universitaria acredita carreras e
instituciones; **no publica una rúbrica para calificar un trabajo final individual**. Si vas a
invocar estándares de CONEAU, tenés que: (a) verificar que esta carrera esté efectivamente alcanzada
por un régimen de acreditación, (b) identificar la resolución ministerial que fija los estándares, y
(c) citar el estándar puntual que usás y cómo se proyecta sobre este trabajo. **Si no podés
acreditar esos tres puntos, escribí que no existe una rúbrica de CONEAU aplicable a un trabajo final
individual y evaluá con el reglamento institucional y con criterios académicos generales que
declares.** Inventar una plantilla atribuida a CONEAU es un error más grave que cualquiera de los que
vayas a encontrar en el documento.

**APA 7.** Toda observación de formato bibliográfico **cita la regla concreta** del Manual de
Publicaciones de la APA, séptima edición, con su apartado. «No cumple APA» no es una observación:
«la referencia de la página N omite el localizador que exige el apartado X para documentos web» sí lo
es. Distinguí lo que el manual prescribe de lo que es convención de la institución o preferencia de
estilo, y verificá si el reglamento de la facultad impone un estilo distinto antes de exigir APA.

Si alguno de estos tres marcos no se puede establecer con fuente, esa imposibilidad es en sí misma un
hallazgo y va en el informe.

## Reglas duras

1. **No inventes nada.** Ni cifras, ni fuentes, ni causas, ni fechas, ni pruebas. Si algo no se puede
   determinar, el hallazgo es «no se puede determinar», y eso es una respuesta válida.
2. **Toda observación cita su ubicación exacta** —apartado y, si podés, página— **y transcribe la
   frase textual** que la origina. Una observación sin cita no es accionable y no cuenta.
3. **No propongas retirar resultados adversos, reformular criterios para que los resultados los
   satisfagan, ni redefinir métricas para convertir un incumplimiento en cumplimiento.** Si detectás
   que el documento ya hizo alguna de esas operaciones en alguna versión, ese es un hallazgo grave y
   quiero verlo señalado.
4. **No garantices una calificación.** Tu puntaje es una estimación de control interno con un esquema
   declarado; quien evalúa es la institución y el tribunal.
5. **No atribuyas a CONEAU ni a ningún organismo una plantilla, rúbrica o requisito** sin
   identificar la fuente y citarla. Ver «Marco de evaluación».
6. **No infieras autoría artificial ni fraude** a partir del estilo.
7. No confundas **implementación**, **prueba automatizada**, **comprobación manual** y **evaluación
   experimental**. Un hallazgo que las mezcle está mal formulado.

## Cómo quiero que audites

No trabajes sobre una lista que yo te dé. Derivá todo del documento. En particular:

**Consistencia interna.** Tomá cada magnitud que aparezca más de una vez —recuentos de pruebas,
tamaños de muestra, porcentajes, cantidades de historias, versiones, fechas— y verificá que coincida
en resumen, abstract, cuerpo, tablas y anexos. Reportá cada divergencia con sus dos valores y sus dos
ubicaciones. Rehacé la aritmética que se pueda reconstruir con los datos publicados.

**Proporción entre afirmación y evidencia.** Buscá toda afirmación de completitud, garantía,
verificación total, cumplimiento o aptitud para producción, y contrastala con lo que el propio
documento acredita. Señalá las que exceden su respaldo y proponé la formulación ajustada.

**Cadena de medición.** Para cada indicador temporal, determiná qué intervalo se midió realmente y
si el documento lo declara sin ambigüedad. Si no se puede determinar, decilo: no lo renombres.

**Unidades de análisis.** Verificá que el documento distinga operaciones generadas, eventos
detectados, eventos encolados y eventos entregados, y que no use una cifra de una categoría para
sostener una afirmación sobre otra.

**Inferencia estadística.** Revisá si el diseño es pareado o independiente y si el tratamiento
estadístico corresponde. Señalá supuestos no verificados. No propongas un cálculo si los datos
publicados no lo permiten.

**Fundamentos técnicos.** Revisá las afirmaciones sobre criptografía, integridad, entrega, límites
ante compromiso privilegiado, trazabilidad frente a auditoría inmutable y alcance de «tiempo real».
Señalá las que no se sostienen conceptualmente, con la corrección y su fundamento.

**Encuadre normativo.** Verificá que el documento distinga obligación legal, recomendación técnica,
estrategia y norma aplicable solo a ciertos sujetos, y que no atribuya a una fuente algo que no dice.
Si citás una norma, citá su texto.

**Estado del arte.** Evaluá si las comparaciones con herramientas existentes están respaldadas y si
alguna afirmación de superioridad, menor costo o exclusividad carece de sustento.

**Bibliografía y APA 7.** Correspondencia entre citas y referencias, vigencia de las fuentes,
localizadores, uniformidad. Cada observación cita el apartado del manual que la fundamenta. Señalá lo
que no pudiste verificar en lugar de asumirlo correcto, y distinguí el incumplimiento de una regla
del manual respecto de una inconsistencia interna de estilo: las dos importan, pero no pesan igual.

**Edición.** Numeración, remisiones cruzadas que no resuelven, equivalencia entre resumen y abstract,
densidad de oración, terminología inconsistente.

## Calificación: del 1 al 10, contra un 10 hipotético

**Calificá siempre la versión que recibiste**, nunca la que vas a producir. La nota de la versión
corregida no te corresponde: la tiene que establecer una auditoría posterior, y así debe decirlo tu
informe.

Declará el esquema con el que puntuás —qué dimensiones, cómo pesan, cómo se agrega el global— y
aplicalo de forma explícita y reproducible. Para cada dimensión: el puntaje, **la razón concreta por
la que no es más alto**, y qué observación puntual la deprime.

**El 10 es la referencia, no el objetivo.** Un 10 bajo un esquema de auditoría no significa «muy
bueno»: significa que **ninguna dimensión admite observación**. Antes de listar correcciones, escribí
qué exigiría ese 10 para este trabajo en particular, incluyendo lo que excede el alcance de una
tecnicatura. Eso le da escala a todo lo demás: sin esa referencia, «le falta esto» no dice cuánto.

Cada corrección que propongas se expresa contra esa escala: **qué distancia al 10 cierra**, y cuál es
el objetivo realista para esta entrega. Distinguí con claridad lo que acerca al 9 de lo que solo
acerca al 10 hipotético, porque son decisiones distintas con costos distintos.

Si alguna acción **bajaría** la nota —retirar una limitación declarada, reformular un criterio,
sustituir evidencia por redacción más cuidada—, decilo explícitamente en esta sección.

## Sobre la brecha hasta el 9

Declará el esquema con el que puntuás y aplicalo de forma explícita. Para cada dimensión: el puntaje,
**la razón concreta por la que no es más alto**, y qué observación puntual la deprime.

Después separá con claridad:

- **Lo que se cierra escribiendo**: correcciones que dependen del documento o de fuentes verificables.
- **Lo que exige volver al laboratorio**: nada de lo que escribas puede convertir un criterio
  incumplido en cumplido, y quiero que lo digas así.
- **Lo que no se puede cerrar**: limitaciones que son resultado legítimo del estudio y que
  corresponde declarar, no resolver.

Para cada acción: qué observación cierra, sobre qué apartado, esfuerzo estimado y **por qué esa
acción mueve la nota**. Si una acción es barata y visible, decilo; si es cara y marginal, también.

Ordená el plan por rendimiento, no por número de apartado.

## Qué corregir y qué no

Corregí en el documento **todo lo que se resuelva con el texto o con fuentes verificables**:
inconsistencias internas, afirmaciones que exceden su evidencia, encuadre normativo, bibliografía,
edición, numeración y remisiones.

**No corrijas** lo que exija una ejecución del sistema que no viste, ni des por resuelto un pendiente
técnico. Eso queda como pregunta al equipo, con la ubicación exacta del texto que depende de la
respuesta.

Conservá el original y generá **un archivo nuevo, con otro nombre**. No presentes esa versión como
definitiva mientras falte integrar la devolución técnica.

## Entregables

1. **Marco de evaluación**: contra qué normativa evaluaste, con sus fuentes citadas, y qué no
   pudiste establecer.
2. **Dictamen**: puntaje por dimensión y global, con el esquema declarado, y el párrafo que justifica
   el global.
3. **Hallazgos**, ordenados por severidad. Cada uno con: identificador, ubicación exacta, frase
   textual, en qué consiste el problema, y qué evidencia haría falta para cerrarlo.
4. **Brecha hasta el 9**, con las tres categorías de arriba y el plan ordenado por rendimiento.
5. **Lo que no pudiste verificar**, con el motivo. Esta sección no es opcional: un informe sin ella
   se lee como si todo lo demás estuviera comprobado.
6. **Preguntas al equipo técnico**, cada una con el apartado afectado, el dato faltante, la evidencia
   requerida y qué parte del texto depende de la respuesta.
7. **Documento corregido**, con nombre distinto del original, y su **registro de cambios por
   apartado**: qué modificaste, por qué, y qué dejaste sin tocar deliberadamente.
8. **Pieza visual del estado**, pensada para mirarse de un vistazo y para compartirse:
   - La **nota del 1 al 10** de la versión auditada, bien visible, con su esquema.
   - El puntaje por dimensión y qué la deprime.
   - **Lo que falta**, separado en tres: lo que se cierra escribiendo, lo que exige laboratorio y lo
     que es una limitación legítima a declarar.
   - La distancia al 9 y la distancia al 10 hipotético, diferenciadas.
   - Lo que **ya está sólido**, porque un tablero que solo muestra deuda no permite decidir.

   Que sea legible en un teléfono y entendible sin haber leído el informe. Si tu entorno no permite
   generarla, entregá su contenido completo y estructurado para que otro la arme.

Escribí en español neutro y formal. Sé específico: «la Tabla 12 informa X y el apartado 5.4 informa
Y» vale; «hay inconsistencias en los datos» no vale.

## Criterio de terminación

Terminá cuando hayas recorrido el documento completo, no cuando tengas hallazgos suficientes. Si una
sección está bien, decilo: un informe que solo enumera problemas no permite saber qué está sólido.

Y si el trabajo tiene virtudes que un tribunal valoraría —resultados adversos sostenidos, limitaciones
declaradas, trazabilidad entre afirmación y evidencia—, señalalas. No por cortesía: porque una
recomendación que las ignore puede sugerir cambios que las destruyan.
