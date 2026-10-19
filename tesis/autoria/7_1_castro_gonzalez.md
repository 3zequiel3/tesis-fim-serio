## 7.1 Cumplimiento de los objetivos formulados

Los once objetivos específicos se cumplen en grados distintos, y ninguno equivale a la corroboración de la hipótesis. Los objetivos describen capacidades del artefacto (apartado 1.5); los criterios de aceptación, los umbrales contra los que se lo evaluó (apartado 1.6). Por eso un objetivo puede estar implementado aunque el criterio que lo mide no se alcance. La Tabla 28 presenta, para cada objetivo, la evidencia, el resultado y su limitación.

*[Tabla 28 sin cambios]*

Los párrafos siguientes agrupan los objetivos por el tipo de resultado y señalan solo lo que la Tabla 28 no dice por sí sola.

**Objetivos analíticos (1 a 4).** Los objetivos 1, 3 y 4 se alcanzan como análisis. El apartado 2.2 fundamenta SHA-256, sin evaluar funciones alternativas. El apartado 2.4 ordena los instrumentos normativos, y el 6.3 los presenta como contribución, no como cumplimiento. La Tabla 4 aplica STRIDE al propio sistema, pero ninguna prueba adversarial verificó sus mitigaciones, y la evasión por desalojo de la cola queda como riesgo residual sin mitigación. El objetivo 2 se alcanza parcialmente: la búsqueda del apartado 2.5 no fue sistemática ni incluyó una evaluación funcional de las herramientas.

**Objetivos de diseño e implementación (5 a 9).** Las capacidades de estos objetivos están implementadas y verificadas por las suites de v5.1-tesis: 811 pruebas del agente, 1.106 del backend y 298 de la consola, sin fallas y con cinco omitidas en total (Tabla 23). Ante un corte real de Valkey, el backend persistió todo lo encolado, en orden y sin duplicados, en tres de tres repeticiones (apartado 5.5). Cinco límites acotan ese resultado:

- la garantía de entrega se limita a la persistencia deduplicada y no alcanza a los efectos laterales (objetivo 6);
- dos o tres operaciones por repetición no llegaron a encolarse, de modo que la preservación no alcanza su definición preregistrada (objetivo 7);
- la clave maestra reside en el mismo anfitrión que la línea base cifrada (objetivo 7, apartado 2.10);
- las suites no acreditan operación con varios anfitriones ni aptitud productiva, y Valkey sigue siendo una dependencia de la autenticación (objetivo 8, apartado 6.6);
- la evaluación corrió sobre la red virtual entre el equipo físico y una máquina virtual, por lo que no acredita transporte cifrado entre anfitriones físicos (objetivos 5 y 9, apartado 5.1).

**Objetivo de notificación (10).** La política está implementada, pero el criterio de tiempo no se alcanza. n8n entregó 3.000 de 3.000 notificaciones a un capturador SMTP local, y el percentil 99 hasta la aceptación por el canal fue de unos 29,5 s con colas de 1.000 eventos, frente a un umbral de 5 s (apartado 5.4). Con 100 notificaciones en cola, el percentil 99 fue de unos 3,8 s; esa lectura es posterior a medir y no sustituye el dictamen. La evaluación no ejercitó las alternativas automáticas, que se activan tras hasta 195 s si n8n falla (apartado 4.7), ni acredita proveedores comerciales.

**Objetivo metodológico (11).** Se alcanza en el laboratorio. Todas las baterías de v5.1-tesis corrieron en una corrida unificada sobre una etiqueta, con arnés versionado, guardas de procedencia con el alcance del apartado 3.7 y paquetes sellados (Capítulo 5 y Anexo F). Ningún tercero repitió las mediciones. El arnés presentó dieciséis defectos de instrumentación, todos corregidos (apartado 6.4). La custodia de la evidencia de versiones anteriores tiene tres defectos, que no afectan cifras de v5.1-tesis: cinco de los 35 manifiestos no verifican íntegros, el paquete sellado de v1.0-tesis fue sobrescrito y las tres trazas de resiliencia de v2.0-tesis son copias de una misma corrida de diagnóstico (Anexo F.1).

**Criterio de cobertura de historias.** La última fila de la Tabla 28 no corresponde a un objetivo, sino a un criterio de la Tabla 1. No se alcanza: v5.1-tesis cubre 24 de 31 historias en conteo estricto, o 23 con la reserva sobre US-07 (apartado 5.7). El cierre del backlog registra 31 de 31 solo con ocho criterios ajustados después de evaluar, y el trabajo no los computa como cumplimiento.

En síntesis, los autores no declaran el cumplimiento integral de los once objetivos ni la corroboración de la hipótesis. El dictamen de cada criterio figura en el apartado 5.9.

### 7.1.1 Respuesta a la pregunta de investigación

La pregunta tiene dos partes (apartado 1.2). La primera recibe una respuesta doble: la plataforma detecta las modificaciones de forma reactiva, pero no protege la línea base frente a un adversario privilegiado. La segunda recibe una respuesta afirmativa en lo técnico y acotada en lo normativo. Las cuatro respuestas valen bajo las condiciones del apartado 5.1.

**Detección reactiva mediante eventos del núcleo.** Sí, para las operaciones que la máscara observa. El agente detecta creaciones, escrituras cerradas y eliminaciones con un percentil 99 de 41,73 ms en el tramo medido, por debajo de 1,67 eventos por segundo, y supera al escaneo periódico en las tres réplicas (apartados 5.2 y 5.3). Tres reservas acotan la respuesta. El tramo medido excluye la cola del núcleo (apartado 3.6). Las reversiones al contenido aprobado no dejan constancia, y el criterio de falsos negativos no se alcanza en su definición preregistrada. Los cambios de permisos, propietario o capacidades no generan eventos (apartados 1.7 y 6.4).

**Protección de la línea base mediante separación arquitectónica y cifrado autenticado.** No frente al adversario del modelo de amenazas. Con la clave maestra en el mismo anfitrión, un atacante con privilegios de administrador puede leer y reescribir la línea base (apartado 2.10). El diseño eleva el costo del ataque, pero no resuelve el compromiso del oráculo de confianza; el apartado 8.9 formula una línea de solución.

**Decisión automatizada graduada y validación humana formalizada.** Sí. El motor de decisión, la máquina de estados, el bloqueo optimista y la cadena de eventos superados están implementados y verificados por pruebas (Tabla 23). v5.1-tesis corrigió, además, los defectos de cuarentena de versiones anteriores (apartado 4.12).

**Adecuación al marco normativo argentino.** Como contribución, no como cumplimiento. El sistema aporta a la medida de seguridad del artículo 9.º de la Ley 25.326 y a cuatro procesos del Anexo I de la Resolución AAIP 47/2018 (apartado 6.3). No acredita el cumplimiento integral, y el plazo de retención de audit_log sigue pendiente (apartado 8.1).
