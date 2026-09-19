# Plan de correcciones para alcanzar una calificación de 9 / 10

**Trabajo:** Plataforma distribuida para el monitoreo de integridad de archivos (FIM) en Linux — UTN-FRM
**Autores:** Ezequiel González · Nicolás Castro
**Punto de partida:** 5,0 / 10 (versión revisada de 111 páginas, re-auditoría del 21/08/2026)
**Objetivo:** 9 / 10
**Fecha:** 21 de agosto de 2026

---

## Cómo leer este plan

Un 5,0 sube a un 6,5–7,0 con **corrección documental** que despeje los siete hallazgos críticos. Pero un **9** exige tres cosas más, y conviene decirlas de entrada porque condicionan todo lo demás:

1. Que el diseño, los resultados y el código **coincidan entre sí** —hoy no lo hacen— y que esa coincidencia sea verificable por un tercero.
2. Que el rigor metodológico esté **completo**, no apenas presente: población, muestra, prueba estadística, validación de instrumentos, comparador real.
3. Que no queden **puntos blandos** que un tribunal exigente pueda tocar sin encontrar respuesta.

El plan está ordenado en cinco bloques. Los bloques A–D son el piso; el bloque E es lo que separa un 7 de un 9. Al final hay un orden de trabajo sugerido y una estimación de cómo cada bloque mueve la nota.

---

## BLOQUE A — Los siete críticos (imprescindibles, sin excepción)

Ninguno de estos es negociable para superar el 7, y por lo tanto tampoco para el 9. Seis de los siete son correcciones de menos de dos jornadas.

### A.1 — Resolver la contradicción anti-replay ↔ resiliencia offline (C-4)

Es la más grave y la que primero hay que despejar, porque hoy el §5.6 reporta un resultado imposible bajo el §4.5.

- Redefinir la ventana anti-replay sobre el instante de **publicación** del evento, no sobre `detected_at`; o reemplazar el control temporal por un **contador monotónico por agente** (el mismo mecanismo que ya usan para el `ruleset_version`). Con eso, un evento encolado durante una desconexión larga deja de ser indistinguible de una reinyección.
- Corregir la constante de tolerancia en el código (hoy 300 s) en consecuencia, y **re-ejecutar la Batería 5** con el código corregido, reportando los nuevos valores.
- En el §4.5, describir el mecanismo nuevo y explicar explícitamente por qué la resiliencia offline ya no lo activa.

Criterio de aprobado del punto: leer el §4.5 junto al §5.6 ya no produce una contradicción.

### A.2 — Corregir la afirmación sobre fanotify, UID y ejecutable (C-2)

- En el §2.6, quitar la afirmación de que el evento fanotify «incluye el identificador de usuario y la ruta del ejecutable». La estructura del núcleo entrega solo el `pid`.
- Describir cómo el sistema obtiene realmente UID y ruta: resolución posterior vía `/proc/<pid>`, con su condición de carrera declarada; o reconocer que el modo FID adoptado **no** los provee y que el sistema no los captura.
- Alinear la **Tabla 13, tarea 1** (§5.4) con lo anterior: hoy reporta como logrado algo que el modo FID no habilita. Si el código fija `process_uid = 0` y `exe = None`, la tabla y el §2.6 deben decirlo, no lo contrario.
- Quitar la conclusión de que «desaparece la necesidad de correlacionar con auditd», que se apoya en el error.

### A.3 — Declarar la evasión por escritura mapeada en memoria (C-3)

- Incorporar en §1.7, §2.6 y §6.5 la limitación documentada en `fanotify(7)`: las modificaciones vía `mmap`/`msync`/`munmap` no generan `FAN_MODIFY`.
- Evaluar explícitamente si esta limitación explica los **7 falsos negativos** «no verificables» del §5.6 / Tabla 16, y acotar el criterio «falsos negativos: cero» de la Tabla 1 a las modificaciones realizadas por la API de archivos.
- Para el 9, no basta declararla: conviene **medirla** (una batería breve que modifique un archivo monitoreado a través de un mapeo y confirme la no detección), convirtiendo una debilidad omitida en un resultado honesto y caracterizado.

### A.4 — Resolver el compromiso del oráculo de confianza (C-5)

- Reformular el argumento del §2.10 / §4.8: la protección real contra un atacante con privilegios administrativos no la da el cifrado local (la clave está en el mismo anfitrión), sino la **copia autoritativa de la baseline en el servidor central** (PostgreSQL).
- Declarar el cifrado local por lo que efectivamente mitiga: exfiltración de disco (robo del equipo, copia de snapshot), no compromiso en caliente.
- Para el 9, ir un paso más: evaluar y mencionar una alternativa que cierre el hueco de raíz —TPM, servicio de custodia de claves, o entrega de la clave por sesión mTLS sin persistencia en disco— aunque sea como decisión fundamentada de no implementarla en el alcance actual.

### A.5 — Corregir el flujo de aprobación humana (C-6)

- El §4.4 y el Anexo B describen al backend hasheando el filesystem del anfitrión dentro de una transacción local: imposible en la topología separada.
- Opción correcta: especificar un **comando de re-hash bajo demanda** (el backend pide al agente el hash actual, respuesta asíncrona, transición de estado diferida al recibirla), e incluirlo en la enumeración de comandos del §2.9.
- Opción alternativa: aceptar el hash reportado por el agente al momento del evento y **documentar la ventana de inconsistencia** que eso introduce.
- Sea cual sea, el texto debe describir lo que el código realmente hace.

### A.6 — Resolver las dos referencias no verificables (C-7)

- Clément et al. (2025) y Babić et al. (2025) no se recuperan por DOI, título, autores ni tema. Clément et al. es, además, la única cita del caso paradigmático del §1.1.
- Aportar los PDF si existen; corregir los datos si hubo errata de transcripción; o **retirarlas y sustituirlas por fuentes verificables**. Para el caso XZ Utils sobran fuentes primarias reales (aviso de CISA, hilo de oss-security, análisis técnicos publicados). Para el punto de eBPF vs. FIM del §6.7, buscar una comparación revisada por pares que sí exista.
- Es la corrección más barata y la de mayor riesgo reputacional en sala; hacerla sí o sí.

### A.7 — Respaldar el Capítulo 5 en el repositorio (cierre de C-1)

Este es el que **no se resuelve con edición** y es condición de posibilidad del 9.

- La carpeta `results/` que promete el Anexo F debe contener las **mediciones crudas individuales** (no las tablas ya resumidas): timestamps por evento, salidas de `tcpdump` y trazas de la verificación cruzada que menciona el §5.1.
- Debe estar el **generador de carga**, los **scripts de las seis baterías** y el **script del grupo de control** ejecutables, de modo que un tercero reproduzca los números.
- El historial de git debe mostrar que esos datos y scripts existen y son coherentes con las fechas del trabajo.
- Quitar el resto de edición «EZE 1» al final del Anexo F.

---

## BLOQUE B — Cerrar los vacíos metodológicos (necesarios para pasar de 7 a 9)

La primera devolución marcó estos como severidad alta y siguen abiertos. Un 9 no los tolera.

- **Población, muestra y muestreo (A-6).** Definir el universo (¿anfitriones? ¿eventos de archivo?) y **justificar** los tamaños 500 / 1.000 / 3.000 por cálculo de precisión del percentil, no por elección arbitraria.
- **Prueba estadística (A-4).** La hipótesis nula invoca significancia; hay que especificar el contraste (por ejemplo, Mann-Whitney sobre las latencias experimental vs. control), el nivel α y la potencia. Hoy no hay ninguna prueba, solo descriptivos.
- **Repeticiones e intervalos de confianza (M-26).** Cada batería con una sola corrida no permite estimar la variabilidad del percentil 99. Correr cada una varias veces e informar dispersión.
- **Validación de instrumentos (A-21).** El generador de carga y la checklist de triage son de elaboración propia, sin piloto ni validación. Documentar una prueba piloto y, para la checklist, derivarla explícita y trazablemente del texto de NIST SP 800-61r2 (hoy la cobertura 11/13 = 84,6 % está aritméticamente predeterminada por qué casillas se pusieron en la lista — A-2).
- **Unificar los indicadores (A-5).** Las Tablas 1, 3 y 16 definen conjuntos distintos. Una única tabla maestra referenciada desde los tres capítulos, con la cadena objetivo → hipótesis → variable → instrumento → planilla completa y sin eslabones rotos.
- **El grupo de control (A-7).** La comparación contra un `cron` de 15 min da un resultado analíticamente deducible; presentarla como ilustración es correcto, pero para el 9 conviene **agregar un comparador real** (AIDE o Wazuh), que es contra lo que un FIM se mide de verdad. El desglose de pérdidas del §5.7 (colapsadas, revertidas, efímeras) ya es bueno; apoyarlo en un comparador real lo vuelve contundente.
- **Nivel explicativo (A-11).** Reclasificar el diseño como descriptivo-comparativo, o incorporar el control de variables confusoras que un nivel explicativo exige.
- **Paradigma (ausente).** Declarar el paradigma epistemológico (el marco de ciencia del diseño encaja bien y resolvería de paso la disonancia entre vocabulario hipotético-deductivo y producto de diseño).

---

## BLOQUE C — Base bibliográfica y estado del arte

- **Estado del arte con método (A-16).** El §2.5 caracteriza cuatro categorías en ocho oraciones sin una sola cita. Declarar protocolo de búsqueda, bases, cadenas de consulta, período y criterios; construir una **tabla comparativa** con dimensiones de análisis (Tripwire, AIDE, OSSEC, Wazuh, comerciales).
- **Literatura fundacional y estándares (A-15).** Incorporar el trabajo fundacional del campo (Kim y Spafford sobre Tripwire), ISO/IEC 27001-27002, el control SI-7 de NIST SP 800-53 y el requisito de FIM de PCI DSS.
- **Elevar la base académica revisada por pares.** Hoy queda en una sola fuente verificable. Un 9 necesita varias fuentes académicas reales y pertinentes, no solo normas y documentación técnica.
- **Citar la premisa del §1.1 (A-3).** Los reportes IBM / Mandiant / Verizon están en la bibliografía pero no en el cuerpo; citarlos con cifras concretas donde se afirma que el vector es «de los más frecuentes». Incorporar además una estimación de costo (M-18), ya que la accesibilidad económica es un diferencial declarado.
- **Reivindicación de originalidad (A-10).** Acotar «no documentado en la literatura» a «no identificado en las fuentes consultadas por los autores», enumerándolas, o sostenerla con la revisión sistemática del punto anterior.
- **Higiene APA.** Autores corporativos correctos, fechas de recuperación en documentación viva, ISBN en libros, criterio de citación de normativa declarado y URL homogéneas.

---

## BLOQUE D — Escritura, figuras y forma

- **Figuras vectoriales y de interfaz (M-13, A-24).** Reinsertar las seis figuras en formato vectorial (hoy son mapas de bits) y **agregar la interfaz**: no hay una sola captura, maqueta ni wireframe, pese a un apartado entero de frontend y 31 historias de usuario. Sumar diagrama de despliegue y de componentes; declarar la notación UML de las Figuras 4 y 5.
- **Oraciones y densidad (A-20).** Fragmentar los pasajes de más de 40 palabras (el objetivo general del §1.4 y la enumeración del stack del §4.6 son los casos extremos); bajar la densidad de nominalizaciones. El índice de escritura de la primera devolución era 6,3; para un 9 debería acercarse a 8.
- **Duplicaciones (B-1, B-2, B-3, B-10).** ~8 % del documento se repite (patrones de diseño en §2.13 y §4.9; flujo del agente en §4.3 y Anexo A; marco normativo en §2.4 y §10.2; esquema en Tabla 5 y Anexo C). Consolidar.
- **`silenciosa` (M-17).** El §6.6 dice que fanotify pierde eventos «silenciosamente» y a la vez que el agente detecta la condición: contradicción interna. El núcleo emite `FAN_Q_OVERFLOW`; corregir el adjetivo.
- **Modo de permisos (A-12).** El §2.6 presenta el modo con contenido previo como capacidad de «prevención efectiva de escrituras», pero el diseño adoptó el modo FID (notificación), incompatible con ese modo. Precisar que los eventos de permiso son de acceso/apertura/ejecución y que el sistema no los usa.
- **Anexos con artefactos (A-22).** Que dejen de ser prosa: incluir el esquema SQL, el `docker-compose.yml`, el unit file, el listado completo de las 31 historias de usuario y el script del grupo de control (o remitir a las rutas exactas del repo).
- **Epígrafes (M-16).** Retirar los de atribución no verificable.

---

## BLOQUE E — Lo que un 9 exige por encima del piso

Todo lo anterior lleva a un 7 sólido. La distancia hasta el 9 se cubre demostrando que el trabajo no solo está corregido, sino que es **riguroso y reproducible sin puntos ciegos**:

1. **Ejecutar y reportar con los tres artefactos alineados.** Diseño (Cap. 4), resultados (Cap. 5) y código (repo) diciendo lo mismo, verificable por un tercero en diez minutos. Hoy el mayor riesgo del trabajo es que no lo estén; cerrarlo es lo que más mueve la nota.
2. **Convertir los tres incumplimientos en fortalezas.** El tiempo de recuperación (153 s), la historia sin construir y los 7 falsos negativos ya se reportan con honestidad —eso es valioso—. Para el 9: corregir el cuello de ingesta y re-medir el tiempo de recuperación; construir la historia faltante o retirarla formalmente del backlog con justificación; y **resolver la indeterminación de los falsos negativos** con la batería de `mmap` y una prueba de reversión-al-contenido-vigente que dirima el origen de los siete.
3. **Comparador real, no solo el `cron`.** Medir contra AIDE o Wazuh sobre la misma carga cierra la objeción del grupo de control degenerado y respalda la reivindicación de originalidad con evidencia.
4. **Cierre estadístico.** Con repeticiones, intervalos de confianza y una prueba de contraste, la confirmación parcial de la hipótesis deja de ser una afirmación descriptiva y pasa a ser un resultado defendible.

La honestidad intelectual del trabajo —que reporta lo que no cumple en lugar de maquillarlo— ya está al nivel de un 9. Lo que falta es que el sustento técnico y metodológico esté a esa misma altura.

---

## Orden de trabajo sugerido

1. **Primero, y por sí solo decisivo:** confirmar/armar el respaldo del Capítulo 5 en el repo (A.7). Si los datos no se pueden respaldar, nada de lo demás alcanza; si se pueden, todo lo demás es alcanzable.
2. Correcciones documentales de los críticos: A.1, A.2, A.5, A.6, y la mitad de A.4 — menos de dos jornadas.
3. Declaraciones y mediciones de limitaciones: A.3 y el punto 2 del bloque E.
4. Cierre metodológico: bloque B (población/muestra, prueba estadística, repeticiones, unificación de indicadores, comparador real).
5. Bibliografía y estado del arte: bloque C.
6. Escritura, figuras y forma: bloque D.
7. El extra del 9: comparador real ejecutado y cierre estadístico (bloque E, puntos 3 y 4).

---

## Cómo se traduce en la nota

| Estado | Nota aproximada |
|--------|-----------------|
| Hoy | 5,0 |
| Bloque A completo (críticos resueltos, datos respaldados en repo) | 6,5 – 7,0 |
| A + B completos (rigor metodológico completo) | 7,5 – 8,0 |
| A + B + C + D | 8,5 |
| Todo, incluido el bloque E (ejecución alineada + comparador real + cierre estadístico) | **9,0** |

El salto grande y no editable es el primero: sin datos respaldados y sin las contradicciones diseño↔resultados resueltas, el techo real ronda el 6, por prolija que quede la redacción. A partir de ahí, cada bloque suma de manera acumulativa, y el 9 es alcanzable sin rehacer el sistema —pero sí ejecutándolo de verdad y midiéndolo bien.
