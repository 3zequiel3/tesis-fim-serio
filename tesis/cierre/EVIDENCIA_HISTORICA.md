# Evidencia de cortes anteriores al candidato v4.0-tesis

Este archivo reproduce sin cambios los apartados del Capítulo 5 de la versión 28 de la tesis que presentaban la batería histórica, los ensayos posteriores de cierre y la síntesis histórica. En la versión 29, el Capítulo 5 se reorganizó en torno al candidato de referencia v4.0-tesis, y estos apartados se trasladaron aquí, conforme a la recomendación N-5 del informe de reevaluación del 28 de septiembre de 2026. La numeración de apartados y tablas es la de la versión 28; las remisiones internas a otros apartados también conservan esa numeración.

En el presente capítulo se presentan los resultados obtenidos de la ejecución del protocolo experimental especificado en el apartado 3.7, con los componentes del sistema desplegados de forma integrada en la configuración de laboratorio allí descripta. Los valores corresponden a la corrida informada y quedan sujetos a actualización si el sistema se vuelve a ejecutar. Los ensayos posteriores de cierre se presentan en apartados propios (5.2.1, 5.3.1, 5.6.1, 5.10 y 5.11) y no se agregan a la corrida histórica.

El candidato de referencia del capítulo, para la evaluación experimental y para las suites, es v4.0-tesis (apartado 5.11), que sucede al candidato v3.0-tesis. El candidato consolidado 7a7ee50 (apartado 5.5) se conserva como corte anterior, con cobertura por componente y custodia por bundle, y como base de la matriz de historias, que no se recontó sobre v4.0-tesis. El capítulo cita, además, en distintos puntos ensayos posteriores realizados sobre otros commits o instantáneas de archivos. La Tabla 12 reúne, a modo de mapa de lectura, los candidatos y cortes de evidencia mencionados en este capítulo, con lo que cada uno acredita y lo que no, tal como se detalla con mayor extensión en el Anexo F.

## 5.1 Consideración metodológica sobre la presentación de resultados

Los resultados que se presentan en este capítulo se obtuvieron mediante la ejecución del protocolo especificado en el apartado 3.7 sobre el laboratorio allí descripto, con los componentes del sistema desplegados de forma integrada y no como prototipos aislados. Cuatro precisiones metodológicas anteceden a su exposición.

La primera se refiere a las condiciones de la batería histórica, que el apartado 3.7 enumera y aquí se reiteran por su incidencia sobre la lectura de las tablas de los apartados 5.2 a 5.9: topología co-residente sobre un único equipo, agente contenedorizado, orquestador de notificaciones inactivo y cifrado de transporte deshabilitado. Esos valores no deben generalizarse a una instalación distribuida con cifrado habilitado. El candidato v3.0-tesis levantó las tres últimas restricciones; sus condiciones, y las del candidato vigente, v4.0-tesis, se consignan en el apartado 5.11.1.

La tercera se refiere a la verificación cruzada. Las mediciones de tiempo se obtienen mediante instrumentación programática del propio sistema, lo que constituye un sesgo de instrumentación reconocido en el apartado 6.4. Para acotarlo se ejecutó una corrida separada de verificación con captura independiente de tráfico y traza de llamadas al sistema, sobre treinta operaciones. La captura registra 660 paquetes y contiene treinta comandos de publicación en el stream de eventos con sus treinta confirmaciones correspondientes, además de los campos de firma y de marca de emisión. Las rutas resultan visibles porque esa corrida se practicó sin cifrado de transporte. La traza registra sesenta y una invocaciones a la llamada de resolución de identificadores de archivo. La verificación acredita la correspondencia entre operación, publicación y confirmación, pero la captura y la traza pertenecen a tramos temporales distintos: no permiten correlacionar llamada al sistema y mensaje uno a uno ni validar el percentil 99 informado en el apartado 5.2. Posteriormente, una corrida independiente de cien modificaciones utilizó strace para fijar el inicio de cada intervalo fuera del reloj del generador (apartado 5.2.1); esa medición no valida retroactivamente el percentil histórico.

## 5.2 Protocolo de medición de latencia de detección

La tercera batería del protocolo mide la latencia de detección, definida en la Tabla 1 como el intervalo entre el instante en que se completa la modificación de un archivo monitoreado y el instante en que el evento correspondiente es recibido por el backend. El protocolo ejecuta el generador de carga con quinientas modificaciones distribuidas uniformemente sobre una ventana de treinta minutos, con tamaños de archivo aleatorios entre un kilobyte y un megabyte. La distribución de operaciones consiste en setenta por ciento de modificación, veinte por ciento de creación y diez por ciento de eliminación. Cada operación se registra con timestamp de nanosegundos y se correlaciona con el timestamp de recepción en el backend.

**Tabla 13. Resultados históricos del tramo agente-backend**

| Estadístico | Valor observado (ms) | Umbral | Cumple |
|---|---|---|---|
| Media aritmética | 10,879 | — |  |
| Mediana | 12,176 | — |  |
| Desvío estándar | 3,699 | — |  |
| Valor mínimo | 3,021 | — |  |
| Valor máximo | 19,802 | — |  |
| Percentil 95 | 16,319 | — |  |
| Percentil 99 (indicador principal) | 17,274 | < 1.000 | Bajo umbral en el tramo medido; no cubre el intervalo completo de la Tabla 4 |
| Eventos medidos | 493 | — (500 operaciones generadas) |  |
| Operaciones sin evento (ejecutadas y verificadas; causa indeterminada) | 7 | 0 | Indeterminado |
| Eventos rechazados por desincronización horaria | 0 | 0 | Sí |

**Tabla 14. Reagregación reportada desde la marca posterior a la operación**

| n | Media (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
|---|---|---|---|---|
| 493 | 11,316 | 12,639 | 16,798 | 17,745 |

Nota. Los valores corresponden a la topología co-residente, sin latencia de red ni cifrado de transporte, descripta en los apartados 3.7 y 5.1; se obtuvieron en condiciones favorables y no deben extrapolarse a un despliegue distribuido. El valor histórico de 17,274 ms para el percentil 99 corresponde al intervalo received_at − detected_at, es decir, al tramo entre la recepción del evento por el agente y su recepción por el backend. El informe de cierre reporta una reagregación desde la marca posterior a la operación del generador hasta received_at, sobre las mismas 493 observaciones, con media de 11,316 ms, mediana de 12,639 ms, percentil 95 de 16,798 ms y percentil 99 de 17,745 ms. Se trata de un nuevo análisis de datos históricos, no de una nueva corrida. La marca posterior a la operación es una referencia instrumental y no demuestra el instante físico exacto de modificación. La reagregación debe acompañarse de su script y datos de origen. Los valores se obtuvieron sobre un único anfitrión, sin cifrado de transporte en aquella ejecución, y no se extrapolan a un despliegue distribuido.

La batería histórica produjo 493 eventos sobre 500 operaciones. El cierre técnico identifica las siete operaciones sin evento como segundas operaciones de pares revertidos y señala que sus manifiestos son compatibles con un retorno al contenido de referencia. Sin embargo, no se conservaron trazas contemporáneas de todas las etapas internas del agente. En consecuencia, su causa no puede demostrarse retrospectivamente y no se clasifican como siete falsos negativos comprobados ni como siete descartes legítimos demostrados.

Para investigar el mecanismo se ejecutó una nueva corrida causal de sesenta operaciones. Cincuenta operaciones reportables recorrieron la cadena de detección, decisión, encolado, publicación, confirmación y persistencia; diez retornos a la baseline activa fueron descartados con la razón matches_active_baseline. La tabla de correlación contiene sesenta operaciones y el extracto del backend contiene cincuenta registros. No hubo ausencias nuevas inexplicadas en esta corrida. El ensayo se realizó sobre ext4, con fanotify dentro de un contenedor con capacidades y servicios aislados en un único anfitrión. La evidencia demuestra el comportamiento observado en esos casos, pero no reconstruye las siete ausencias históricas ni prueba ausencia general de falsos negativos.

### 5.2.1 Medición posterior con inicio observado externamente

Para atender la falta de triangulación temporal se ejecutó una corrida nueva de cien modificaciones sobre el candidato 7df4935, en un laboratorio Compose aislado. Se crearon cien archivos antes de arrancar el agente y se verificaron cien entradas de baseline. Luego el generador aplicó a cada archivo la secuencia open, write, fsync y close, a diez operaciones por segundo. El inicio de cada intervalo es la finalización de close(2), observada por un proceso strace externo (-ttt -T -yy) como marca de entrada más duración de la llamada. El fin es events.received_at, persistido por el backend. El cruce se realizó por ruta única, y una traza opcional del agente confirmó la cobertura de las cien rutas.

**Tabla 15. Latencia con inicio observado externamente (corrida posterior)**

| n | Media (ms) | Mediana (ms) | P95 (ms) | P99 (ms) | Máximo (ms) | Umbral P99 | Cumple |
|---|---|---|---|---|---|---|---|
| 100 | 15,260 | 13,331 | 26,506 | 31,533 | 31,897 | < 1.000 ms | Sí, en esta corrida |

Nota. Corrida nueva, no reagregación de las 500 operaciones históricas. Cien de cien modificaciones quedaron correlacionadas y no hubo intervalos negativos; el desvío muestral fue 6,168 ms. El inicio es independiente del reloj del generador, pero el fin sigue siendo la marca productiva del backend. Anfitrión y contenedores comparten el reloj del núcleo, y Valkey operó sin TLS. El valor no se compara aritméticamente con 17,274 ms (tramo (b)→(c)) ni con 17,745 ms (reagregación desde la marca posterior a la operación): mide otro intervalo sobre otra muestra. Un primer intento, en el que el generador no encontró los nombres de archivo esperados y no ejecutó modificaciones, se conserva como inválido y sin resultados. Fuente: experiments-closure-20260912T004612Z/latency/.

## 5.3 Protocolo de medición de tiempo de notificación

La cuarta batería histórica midió el intervalo entre la recepción del evento por el backend y la aceptación de un webhook por un receptor HTTP de laboratorio. No atravesó n8n ni un proveedor comercial. Aunque el protocolo preveía mil invocaciones y niveles de concurrencia de 1, 50 y 100, el cierre informa 360 operaciones generadas y 329 muestras: 60/60, 99/100 y 170/200, respectivamente. Los valores 1, 50 y 100 describen tasas de emisión en operaciones por segundo mediante un bucle secuencial temporizado, no concurrencia efectiva de solicitudes. La causa del apartamiento del protocolo no quedó documentada.

Los percentiles describen únicamente las muestras registradas. Las 31 operaciones sin webhook medido permanecen sin clasificación causal: los datos disponibles no permiten determinar cuántas requerían notificación ni en qué etapa terminó cada una. Por ello no se computan retrospectivamente como entregas ni como fallos. El ensayo documenta tasas de emisión de 1, 50 y 100 operaciones/s mediante un bucle secuencial; no demuestra el criterio original de cien solicitudes concurrentes ni la recepción en un canal externo.

**Tabla 16. Resultados — Tiempo de notificación**

| Escenario | Media (ms) | P50 (ms) | P95 (ms) | P99 (ms) | Cumple |
|---|---|---|---|---|---|
| Secuencial (1 operación/s; n=60) | 47,6 | 49,2 | 55,8 | 63,4 | Bajo umbral; 60/60 medidas |
| Tasa moderada (50 operaciones/s; n=99) | 50,1 | 48,7 | 69,8 | 80,7 | Bajo umbral; muestra incompleta |
| Tasa alta (100 operaciones/s; n=170) | 45,6 | 44,3 | 66,7 | 85,5 | Bajo umbral; muestra incompleta |

Nota. Los escenarios corresponden a tasas de emisión de 1, 50 y 100 operaciones por segundo, con 60, 99 y 170 webhooks medidos. La medición termina en la aceptación por el receptor HTTP de laboratorio. No acredita concurrencia de cien solicitudes, ejecución de n8n ni entrega comercial. Los valores son descriptivos de las muestras registradas y no incluyen un análisis causal de las 31 operaciones sin webhook medido.

### 5.3.1 Ensayo posterior con cien solicitudes simultáneas

La batería histórica no ejercitó el criterio de cien solicitudes concurrentes. Un ensayo posterior importó la función productiva de envío send_n8n desde el candidato 7df4935 y lanzó cien corrutinas que esperaron en una barrera común; las cien estaban listas antes de liberarla. Cada corrutina fijó received_at inmediatamente después de la barrera y envió un payload sintético identificable a un receptor HTTP local controlado. El receptor selló la recepción antes de procesar el cuerpo y retuvo cada solicitud 50 ms después del sello, para hacer observable el solapamiento sin alterar esa marca.

El primer intento registró 88 solicitudes aceptadas y 12 fallidas, con un máximo de 49 solicitudes activas, y no cumplió el requisito de denominador completo. Se conserva como intento fallido. La repetición modificó sólo el receptor de laboratorio: amplió su cola de conexiones pendientes (request_queue_size) de 5, valor predeterminado de la biblioteca estándar de Python, a 256. El criterio, la función evaluada, el payload y el umbral no cambiaron. El intento fallido no se atribuye a un defecto del producto, pero muestra que el resultado depende de la capacidad del receptor.

**Tabla 17. Notificación con cien solicitudes simultáneas (ensayo posterior)**

| Intento | Listas antes de la barrera | Aceptadas | Máx. activas | P50 (ms) | P95 (ms) | P99 (ms) | Cumple |
|---|---|---|---|---|---|---|---|
| 1 (fallido, preservado) | 100 | 88/100 | 49 | 609,933 | 1.496,556 | 1.615,443 (n = 88) | No: denominador incompleto |
| 2 (repetición) | 100 | 100/100 | 100 | 354,850 | 595,037 | 616,626 | Sí, en el tramo ensayado |

Nota. Intervalo: received_at fijado tras la barrera → aceptación del receptor controlado, medido sobre la función productiva send_n8n. El inicio es simulado y no incluye ingesta ni persistencia del evento. En la repetición, el tiempo de ida y vuelta del cliente tuvo P99 de 712,668 ms. La clase del receptor también declara daemon_threads=True, igual al valor predeterminado de ThreadingHTTPServer. El ensayo no atraviesa n8n, SMTP, proveedores comerciales, reintentos ni un segundo anfitrión; no constituye validación integral ni evidencia de comportamiento productivo. Fuente: experiments-closure-20260912T004612Z/concurrency/.

## 5.4 Protocolo de cobertura de automatización del triage

## 5.5 Validación funcional mediante casos de prueba

La validación funcional —segunda batería del protocolo— se practica mediante la batería automatizada de pruebas que acompaña al sistema. La ejecución informada comprende 912 casos, distribuidos entre la verificación del agente y la verificación de integración del backend. Se contrasta contra las treinta y una historias de usuario del backlog consolidado —las veinticuatro originales más las siete incorporadas tras la auditoría interna— y contra las reglas de negocio del catálogo descripto en el apartado 3.8. El criterio de aceptación exige la verificación automatizada completa de la totalidad de las historias. El recuento que sigue corresponde a esa ejecución y queda sujeto a actualización en ejecuciones posteriores.

La ejecución de la batería del agente no requiere infraestructura de respaldo, dado que el enlace al subsistema fanotify se sustituye de forma controlada según se describe en el apartado 4.9. La ejecución de la batería del backend requiere instancias efímeras de PostgreSQL y de Valkey, levantadas mediante contenedores de vida acotada a la sesión de pruebas.

**Tabla 19. Resultado informado de la batería automatizada**

| Batería | Casos ejecutados | Aprobados | Omitidos | Fallidos |
|---|---|---|---|---|
| Agente | 418 | 417 | 1 | 0 |
| Backend (integración) | 494 | 494 | 0 | 0 |
| Total | 912 | 911 | 1 | 0 |

Nota. El único caso omitido corresponde a una verificación del agente que solo resulta aplicable cuando el subsistema fanotify no se encuentra disponible; su condición se declara explícitamente en la salida del ejecutor y no se contabiliza como aprobación.

Validación consolidada del candidato 7a7ee50 (corte anterior). El candidato 7a7ee50 registró 540 pruebas del agente aprobadas, ninguna fallida y una omitida; 689/689 del backend; 197/197 del frontend; y 19/19 de scripts. La comprobación de tipos y la construcción del frontend aprobaron. Las coberturas propias fueron 79,57 % (2726/3426) del agente, excluidos tests, y 91,34 % (2902/3177) de backend/app. En frontend fueron 73,09 % (2836/3880) de líneas/statements, 67,52 % (158/234) de funciones y 80,85 % (587/726) de ramas. Estos porcentajes se informan por separado. No se promedian con el 89,35 % histórico de Coverage Run 3 ni con el candidato 7df4935, que registró 507 pruebas del agente, 599 del backend y 128 del frontend.

El alcance consolidado incluyó además los laboratorios E2E dirigidos US-02/20/31 y US-03/16/17/25, y la integridad OpenSpec de 44 especificaciones y 249 requisitos. Su aprobación no transforma las ejecuciones repetidas en casos unitarios adicionales. En el candidato 7df4935, el control ambiental main_stack_unchanged=false apareció en dos intentos US-02/20/31, sin inventarios crudos que permitieran reconstruir su causa. La repetición con inventarios crudos registró true: US-02 1/1, US-20 2/2 en dos corridas, US-31 2/2 y el conjunto combinado 5/5 en dos corridas. El candidato 7a7ee50 también conservó sin cambios el inventario del stack principal. Su primer intento, sobre el commit d35fb9c, falló en el E2E de US-25 y se conserva separado (apartado 4.9 y Anexo F).

### 5.5.1 Sobre la cobertura de las historias de usuario

## 5.6 Protocolo de resiliencia offline

La quinta batería del protocolo evalúa la capacidad del agente de preservar eventos ante la indisponibilidad del intermediario de mensajería. Se interrumpe el servicio Valkey durante cinco minutos, conforme al plan de medición del 18 de agosto de 2026 (apartado 3.7), durante los cuales el generador produce operaciones a una tasa constante de diez por segundo, totalizando tres mil operaciones. Tras el reinicio se verifica la preservación de los eventos encolados (hasta el límite de cien megabytes con política drop-oldest), la entrega en orden FIFO estricto tras procesamiento previo de comandos pendientes, y la ausencia de duplicaciones mediante el protocolo con identificador único por evento. La Tabla 21 distingue las operaciones generadas por el instrumento de los eventos que el agente encoló y de los que el backend recibió, por cuanto son recuentos distintos.

**Tabla 21. Resultados — Resiliencia offline**

| Indicador | Valor observado | Umbral | Cumple |
|---|---|---|---|
| Duración de la desconexión | 326 s | — (previsto: 300 s) | - |
| Operaciones generadas durante la desconexión | 3.000 | — (previsto: 3.000) | - |
| Eventos encolados en la cola local | 2.988 | Igual a generados | No (12 operaciones sin evento; causa indeterminada) |
| Eventos entregados tras reconexión | 2.988 | Igual a generados (preregistrado) | No (2.988 de 3.000); 2.988 de 2.988 encolados como medida complementaria |
| Orden FIFO preservado | Sí — 0 de 2.988 fuera de orden | Sí | Sí |
| Duplicaciones detectadas | 0 | 0 | Sí |
| Comandos procesados antes que eventos encolados | Parcial; sin cuantificación | Sí | Funcional; no cuantificado |
| Tiempo de drenaje tras reconexión | 153 s | < 30 s | No |

Nota. La cota de cien megabytes de la cola local no se alcanzó en ningún momento de la corrida, de modo que la política de descarte del más antiguo no llegó a ejercitarse.

La preservación y la entrega resultan íntegras respecto de los eventos efectivamente encolados: los 2.988 eventos encolados se entregaron en su totalidad, en orden estricto y sin duplicación alguna. Ese resultado sustenta la propiedad de no pérdida entre la cola local y el backend; no sustenta, por sí mismo, la preservación completa de las tres mil operaciones generadas, por cuanto doce de ellas no llegaron a producir evento encolado. El indicador de preservación, en su definición preregistrada, exige que los eventos preservados y entregados igualen a los generados y, por tanto, no se alcanza (2.988 de 3.000). La entrega del 100 % de lo encolado se informa como medida complementaria, cuya definición es posterior a esta corrida (apartado 1.6). El orden de precedencia entre comandos y eventos tras la reconexión se comprobó en su ciclo funcional: se creó un comando de actualización de baseline, el agente lo ejecutó, emitió su confirmación y los eventos encolados fueron drenados. La implementación invoca el vaciado de comandos antes del drenaje de la cola de eventos, de modo que la precedencia está respaldada por el código. La corrida, sin embargo, no preservó un registro de reconexión con marcas temporales suficientes para determinar cuántos comandos se procesaron antes y cuántos después del primer evento drenado, por lo que la propiedad no quedó cuantificada experimentalmente. La ausencia de descartes locales confirma que la cota de la cola no se alcanzó. La ausencia de rechazos del backend, por su parte, es consistente con el comportamiento que el control anti-replay descripto en el apartado 4.5 prescribe. Si la versión ensayada ya aplicaba la ventana temporal sobre el instante de transmisión, la ausencia de rechazos es compatible con un tránsito inferior a la tolerancia, pese a que la permanencia en cola de los eventos más antiguos superó los trescientos veintiséis segundos; el tránsito no se midió de forma separada. La deduplicación por identificador, además, no registró coincidencias, lo que indica que no se persistieron reentregas. La batería resulta, en consecuencia, compatible con la coexistencia de la resiliencia offline y del control anti-replay en el diseño adoptado, bajo las condiciones ensayadas; la compatibilidad entre la resiliencia y la ventana anti-replay definida sobre sent_at se acredita en los candidatos v3.0-tesis y v4.0-tesis, que la incorporan y no registraron rechazos por desfase temporal (apartado 5.11.5).

La evaluación histórica registró 3.000 operaciones y 2.988 eventos encolados. El cierre técnico caracteriza las doce diferencias como compatibles con retornos a la baseline, pero no permite reconstruir su recorrido interno en aquella ejecución. Los 2.988 eventos encolados se entregaron íntegramente; esto no acredita por sí mismo detección de las 3.000 operaciones. La nueva corrida causal del apartado 5.2 demuestra descartes legítimos en sus propios diez casos, sin resolver retrospectivamente las doce diferencias de la batería histórica.

### 5.6.1 El tiempo de drenaje tras reconexión no alcanza el umbral

El indicador de tiempo de drenaje tras reconexión registra 153 segundos frente a un umbral de treinta, y no cumple. El resultado se reporta como tal, sin atenuación, y merece análisis.

Como descripción complementaria, y sin sustituir el criterio, el drenaje de los 2.988 eventos encolados se sostuvo a una tasa efectiva de 19,5 eventos por segundo. Alcanzar el umbral de treinta segundos habría exigido sostener 99,6 eventos por segundo, esto es, un caudal cinco veces superior. La medición se practicó con la limitación de tasa del consumo de eventos ya elevada a cien mil por minuto. Este valor se declara porque la configuración por defecto descripta en el apartado 4.11 —cien eventos por minuto por agente— habría producido un tiempo de drenaje órdenes de magnitud mayor. El cuello de botella no reside, en consecuencia, en la limitación de tasa sino en el caudal de ingesta del backend.

Corresponde señalar que el umbral de treinta segundos, fijado a priori conforme al apartado 1.6, se formuló como resiliencia operativa mínima aceptable sin especificar el volumen acumulado sobre el cual debía medirse. El tiempo de drenaje es función del volumen encolado, de modo que el criterio resulta más exigente cuanto más prolongada es la desconexión ensayada. Una formulación futura podría expresar el criterio como caudal de drenaje —eventos por segundo— en lugar de tiempo absoluto, o fijar el tiempo para un volumen determinado.

Esta observación no convierte el resultado en un cumplimiento: el incumplimiento se consigna contra el criterio tal como fue formulado, y la reformulación se propone para un estudio posterior en el apartado 8.1, sin aplicación retroactiva. Con independencia de la formulación del criterio, el resultado señala una limitación real del caudal de ingesta del backend en las condiciones ensayadas.

Evaluaciones complementarias del drenaje. Tras modificaciones de la cola y de la ingesta se efectuaron ensayos específicos del trayecto de transporte y persistencia. Run 3 drenó 3.000 eventos en 51,773 segundos y no alcanzó el umbral de 30 segundos. Run 4, ejecutado sobre una copia limpia del commit 965dcacc5c189f4a9808b063e32085d89e636803, drenó 3.000 eventos en 29,146 segundos, con un caudal de 102,929 eventos por segundo, sin rechazos ni publicaciones duplicadas y con la cola local vacía al finalizar.

Run 4 empleó 3.000 eventos preencolados con rutas únicas y acción manual_review. Permanecieron activos HMAC, persistencia PostgreSQL, consumer group de Valkey, confirmaciones y eliminación durable de la cola. El límite de ingesta experimental fue de 100.000 eventos por minuto, frente al valor predeterminado de 100. El transporte Valkey del ensayo utilizó una conexión local sin TLS. La preparación de la cola se excluyó del tiempo de drenaje; el reloj de medición fue monotónico.

La corrida original de Run 4 registró 29,146 s, es decir, un margen descriptivo de 0,854 s respecto del umbral de 30 s, exclusivamente bajo las condiciones de ese ensayo. Esa corrida, por sí sola, no permitía estimar variabilidad, robustez ni probabilidad de cumplimiento; tampoco se reproduce la desconexión completa de cinco minutos ni se valida la detección durante ella. No evalúa el límite de tasa predeterminado, la supersesión sobre una misma ruta ni un despliegue multianfitrión. Se conservan por separado el resultado histórico de 153 segundos y Run 3 de 51,773 segundos. Dos intentos inválidos del arnés están identificados y excluidos de Run 4.

Repetición posterior de Run 4. Sobre el candidato 7df4935 se repitió el arnés de Run 4 sin modificarlo: el mismo run_profile.py, con idéntico SHA-256 en las cinco corridas. PostgreSQL 18.3 y Valkey 9.0.3 funcionaron en contenedores aislados. Cada corrida reinició la base, Valkey y el directorio de cola, preencoló 3.000 eventos y aplicó los mismos parámetros: timeout de 300 s, límite experimental de 100.000 eventos por 60 s y reloj monotónico. El intervalo empieza al iniciar el publicador y termina cuando PostgreSQL contiene los 3.000 eventos y la cola local queda vacía. Se informan las cinco corridas válidas; no se seleccionó la mejor. Una invocación interrumpida por el transporte de ejecución, sin resumen ni código de salida, se conserva como inválida y no se cuenta.

**Tabla 22. Repetición del drenaje de Run 4 sobre el candidato 7df4935**

| Corrida | Tiempo (s) | Eventos persistidos | Caudal (eventos/s) | Duplicados / rechazos / cola residual | < 30 s |
|---|---|---|---|---|---|
| run-01 | 27,784 | 3.000/3.000 | 107,97 | 0 / 0 / 0 | Sí |
| run-02 | 29,043 | 3.000/3.000 | 103,30 | 0 / 0 / 0 | Sí |
| run-03 | 28,109 | 3.000/3.000 | 106,73 | 0 / 0 / 0 | Sí |
| run-04 | 29,188 | 3.000/3.000 | 102,78 | 0 / 0 / 0 | Sí |
| run-05 | 27,997 | 3.000/3.000 | 107,15 | 0 / 0 / 0 | Sí |
| Serie (n = 5) | media 28,424; mediana 28,109; desvío muestral 0,644; mín. 27,784; máx. 29,188 | 3.000/3.000 en cada corrida | — | 0 / 0 / 0 en cada corrida | 5 de 5 |

Nota. Corridas nuevas sobre el candidato 7df4935; no reinterpretan el resultado histórico de 153 s, Run 3 de 51,773 s ni la corrida original de Run 4 (29,146 s, commit 965dcac), que se conservan por separado. Condiciones: anfitrión único, eventos preencolados, tasa experimental distinta del valor productivo de 100 eventos por minuto y sin reproducir la desconexión completa de cinco minutos. La serie describe variabilidad bajo esas condiciones; cinco repeticiones no habilitan inferencia poblacional. Fuente: experiments-closure-20260912T004612Z/drain/.

## 5.7 Comparación con grupo de control

El componente comparativo de la tercera batería contrasta el grupo experimental contra el grupo de control. Ambos se ejecutan simultáneamente sobre la misma carga de trabajo y sobre los mismos directorios monitoreados. La ejecución simultánea reduce la variabilidad proveniente de condiciones de sistema distintas y permite comparar ambos paradigmas bajo una carga común; conforme al apartado 3.1, no habilita la atribución causal de la diferencia a decisiones arquitectónicas particulares.

**Tabla 23. Resultados — Comparación experimental vs. control**

| Indicador | Plataforma FIM | Script cron (900 s) | Factor de mejora |
|---|---|---|---|
| Mediana de latencia | 12,176 ms | 553.054,29 ms (9,2 min) | — |
| Latencia percentil 99 | 17,274 ms | 897.370,87 ms (15,0 min) | — |
| Operaciones sin evento / no detectadas | 7 de 500 (1,4 %; causa indeterminada) | 395 de 500 (79,0 %) | — |
| Baseline con separación y cifrado | Sí | No | — |
| Notificación automática con alternativas | Sí | No | — |
| Trazabilidad de auditoría | Sí | No | — |

Nota. El grupo de control verifica los mismos directorios cada novecientos segundos mediante cómputo de huellas. Los intervalos de la plataforma reactiva y del control periódico no comparten un mismo inicio y fin operacional: la plataforma informa marcas internas o posteriores a la operación, mientras el control queda acotado por su ciclo de sondeo. Por esa diferencia de alcance, la tabla conserva los valores descriptivos y retira los factores de mejora; no se interpreta la comparación como una mejora validada de extremo a extremo.

Los valores de latencia muestran la diferencia descriptiva entre una plataforma reactiva y un sondeo periódico de quince minutos, pero no permiten cuantificar un factor de mejora de extremo a extremo porque los intervalos no son equivalentes. La comparación de operaciones sin evento se presenta por separado con denominadores comunes.

El grupo de control no detectó 395 de las 500 operaciones, esto es, el setenta y nueve por ciento de la carga. El desglose de esa pérdida convierte la limitación estructural del encuestamiento en un dato con causa identificada. Doscientas noventa y tres operaciones se perdieron por colapso: dos o más cambios sucesivos sobre el mismo archivo dentro del mismo intervalo de encuestamiento, de los cuales el escaneo periódico observa únicamente el estado final y computa un solo cambio. Ciento dos operaciones se perdieron por no detección propiamente dicha: el archivo retornó a un estado indistinguible del de la verificación anterior antes de que esta se practicara.

Clasificadas por patrón de la carga, las pérdidas se distribuyen en doscientas veintidós operaciones simples, ochenta y tres colapsadas, ochenta revertidas y diez efímeras. Las noventa operaciones de los dos últimos patrones —revertidas y efímeras— resultan particularmente significativas, por cuanto corresponden a modificaciones que fueron aplicadas y deshechas dentro de la ventana de ceguera. Frente a ellas el grupo de control, con su intervalo de quince minutos, no es lento sino ciego: un encuestamiento más frecuente solo las capturaría si su intervalo resultara menor que la duración de cada modificación, lo que lo aproxima al modelo reactivo. Esa es la conclusión que el apartado 1.2 anticipaba y que la Tabla 23 documenta para la carga ensayada.

Corresponde una precisión sobre la simetría de la comparación. El grupo experimental también registra siete operaciones sin evento asociado, cuya interpretación quedó indeterminada en el apartado 5.2. Aun computando las siete como falsos negativos en el peor de los casos, la diferencia entre el uno coma cuatro y el setenta y nueve por ciento conserva su sentido. La comparación exige, no obstante, consignar ambos valores con el mismo criterio, y así lo hace la Tabla 23.

El contraste adecuado es McNemar sobre los pares discordantes, con el intervalo de Newcombe (1998) para la diferencia de proporciones pareadas. Para esta batería histórica no se conservaron la tabla operación por operación ni un script verificable, de modo que la diferencia de 77,6 puntos porcentuales se conserva sólo como descripción: no se calcula un intervalo ni se anticipa significación. El contraste pareado se ejecutó en tres corridas, sobre los candidatos v1.0-tesis, v3.0-tesis y v4.0-tesis, y se informa en el apartado 5.11.3; no se proyecta retroactivamente sobre esta batería.

Corresponde, no obstante, una advertencia sobre el alcance de este resultado. De las 395 operaciones que el esquema de encuestamiento no detectó, 293 corresponden al colapso de cambios sucesivos sobre una misma ruta dentro de la ventana de verificación. Este mecanismo es determinístico y no estocástico: un esquema que verifica cada novecientos segundos reporta una única modificación por ruta y por ventana, con independencia de cuántas se hayan producido. La comparación cuantifica, en consecuencia, la magnitud de una diferencia cuyo mecanismo es estructural. Su valor es el de una medida descriptiva del tamaño del efecto, antes que el de evidencia de una relación causal. El diseño adoptado no está en condiciones de establecer esa relación causal, conforme se delimita en el apartado 3.1. Tampoco un intervalo de confianza obtenido mediante el recálculo pareado informaría sobre la generalización a otras cargas de trabajo, cuya composición determina directamente la proporción de cambios colapsables.

## 5.8 Síntesis de criterios de aceptación

Síntesis: recibieron apoyo experimental la latencia de detección, el tiempo de notificación en el tramo ensayado, la cobertura de automatización del triage, la entrega íntegra de los eventos encolados, como medida complementaria, y la diferencia descriptiva frente al grupo de control. No se alcanzaron la cobertura completa de las 31 historias de usuario (23 completas, 8 parciales, matriz de cierre), el tiempo de drenaje tras reconexión (153 s frente al umbral de 30 s) ni la preservación en su definición preregistrada (2.988 de 3.000). Los falsos negativos de la batería histórica quedaron indeterminados. El detalle de cada indicador frente a los umbrales de la Tabla 1 se presenta en la Tabla 24. Esta síntesis corresponde a las baterías históricas y a los ensayos de cierre; la del candidato vigente, v4.0-tesis, se presenta por separado en la Tabla 32 (apartado 5.11.7).

**Tabla 24. Síntesis de criterios de aceptación**

| Indicador | Valor observado | Umbral | Estado |
|---|---|---|---|
| Latencia de detección P99 (ms) | Histórico: 17,274 ms (received_at − detected_at). Reagregación posterior: 17,745 ms (received_at − marca post-operación; n = 493). Corrida independiente nueva: 31,533 ms (close(2) observado con strace → received_at; n = 100). | < 1.000 | Los tres valores quedan bajo 1.000 ms en sus intervalos y muestras; no son intercambiables. La corrida nueva es local, de un anfitrión y sin TLS de Valkey. |
| Tiempo de notificación (P99, ms) | 63,4 (n = 60; orquestador inactivo) | < 5.000 | Aceptación de webhook local dentro del umbral en la muestra histórica; no equivale a recepción final externa. |
| Tiempo de notificación bajo carga (P99, ms) | Histórico: 85,5 (n = 170; tasas, no concurrencia). Ensayo posterior: 616,626 (100/100 solicitudes simultáneas; send_n8n → receptor local). | < 5.000 | Histórico: parcial. El ensayo posterior cumple el umbral con 100 solicitudes simultáneas en el tramo de transporte ensayado; inicio simulado, sin n8n ni canal final; no es validación integral. |
| Cobertura de automatización del triage (%) | 81,8 (9 de 11 tareas; lista sobre SP 800-61r2) | ≥ 80 | Alcanzado |
| Cobertura de historias de usuario | Candidato 7a7ee50: 23 completas, 8 parciales y 0 sin cobertura funcional. Recuentos de los demás cortes y reserva sobre US-07: Tabla 20 (apartado 5.5.1). | 31 de 31 | No alcanzado: el criterio exige las 31 historias completas. La reclasificación de trece historias procede de implementación y pruebas por criterio del candidato 7a7ee50 (apartado 5.5.1); los criterios no se modificaron. |
| Preservación de eventos ante desconexión (%) | 100 de los eventos encolados (2.988 de 2.988); 12 de 3.000 operaciones sin evento, indeterminadas | 100 | No alcanzado según la definición preregistrada (apartado 1.6). Histórico: 2.988/2.988 eventos encolados entregados, como medida complementaria; 12 operaciones sin evento permanecen indeterminadas. Run 4 y serie posterior: 3.000/3.000 preencolados drenados en cada corrida. |
| Tiempo de drenaje tras reconexión (s) | Histórico: 153 s. Run 3: 51,773 s. Run 4 original: 29,146 s. Serie posterior (5 corridas): media 28,424 s; mediana 28,109 s; desvío 0,644 s; máx. 29,188 s. | < 30 | Histórico y Run 3 no cumplen. Run 4 y la serie posterior cumplen sólo en ensayos locales con eventos preencolados, tasa modificada y sin repetir la desconexión completa de cinco minutos. |
| Falsos negativos (n) | 7 operaciones sin evento, causa no establecida | 0 | Histórico indeterminado. Las 19 ausencias históricas citadas en el documento suman estas 7 operaciones de la batería de detección y las 12 de la batería de desconexión (fila de preservación). Corrida causal nueva: 50 eventos y 10 descartes legítimos; no reclasifica ninguna de las 19. |
| Proporción de detección comparativa (puntos) | +77,6 (diferencia descriptiva) | > 0 | Diferencia histórica descriptiva +77,6 pp; incorporar inferencia pareada sólo con tabla y script verificables. |

Nota. Los umbrales proceden de la Tabla 1. Las filas de notificación, automatización del triage y comparación, y los valores históricos de latencia, preservación, drenaje y falsos negativos, pertenecen a las baterías históricas. La reagregación de latencia es posterior. La cobertura 23/8/0 corresponde a la matriz de cierre del candidato 7a7ee50. La reclasificación de ausencias corresponde a la corrida causal posterior. Run 3 y Run 4 pertenecen a esos ensayos dirigidos. La latencia con inicio externo, la concurrencia de cien solicitudes y la serie de cinco drenajes provienen de los ensayos posteriores de cierre (apartados 5.2.1, 5.3.1 y 5.6.1). Las filas de concurrencia, drenaje repetido y latencia con inicio externo proceden de ensayos sobre el candidato 7df4935, no repetidos sobre el candidato 7a7ee50. Ninguna fila autoriza a tratar el conjunto como una única corrida o versión final. Los resultados del candidato v3.0-tesis se sintetizan por separado en la Tabla 32 (apartado 5.11.7) y no se mezclan con esta tabla.

La hipótesis conjunta no fue corroborada porque al menos uno de los criterios preestablecidos no se alcanzó. Este resultado no invalida las contribuciones de ingeniería ni los criterios satisfechos, que se informan por separado, pero impide afirmar la validación integral de la plataforma. Recibieron apoyo experimental la latencia de detección, el tiempo de notificación en el tramo ensayado, la cobertura de automatización del triage según la lista autoral, la entrega de los eventos encolados, como medida complementaria, y la diferencia descriptiva de detección frente al control. Cada uno de esos resultados vale bajo sus propias condiciones. No se alcanzaron la cobertura de las treinta y una historias, el drenaje de la batería histórica ni la preservación en su definición preregistrada, y los falsos negativos históricos quedaron indeterminados.

La matriz de cierre informa veintitrés historias completas, ocho parciales y ninguna sin cobertura funcional; por tanto, no se alcanza el criterio de verificación completa de las treinta y una. Las diecinueve ausencias históricas siguen sin reconstrucción causal contemporánea. La corrida causal posterior registró cincuenta eventos reportables y diez descartes legítimos bajo sus propias condiciones. El drenaje histórico de 153 segundos no cumplió. Run 4 alcanzó 29,146 segundos y la serie posterior de cinco corridas quedó entre 27,784 y 29,188 segundos, siempre con 3.000 eventos preencolados, límite de tasa modificado y sin reproducir la desconexión completa de cinco minutos.

El tiempo histórico de notificación describe aceptación por un receptor local y tasas de emisión; no demuestra recepción comercial. El ensayo posterior sí ejercitó cien solicitudes simultáneas, pero sólo en el tramo de transporte hacia un receptor local. La reagregación de latencia reportada debe distinguirse del tramo interno originalmente tabulado y de la corrida independiente posterior. En conjunto, estos resultados sostienen mejoras concretas y límites identificados, no validación integral ni aptitud productiva.

## 5.9 Protocolo de caracterización del mapeo de memoria

## 5.10 Ensayo posterior sobre dos anfitriones

## 5.11 Evaluación de los candidatos v3.0-tesis y v4.0-tesis

Este apartado presenta la evaluación del candidato v4.0-tesis, candidato de referencia vigente, junto con la del candidato v3.0-tesis, que lo precedió. Cada evaluación se obtuvo sobre un único candidato y en una única corrida, y sus cifras se presentan por separado. Sus resultados no se agregan a los de la batería histórica ni a los de los cortes anteriores, que se conservan en los apartados precedentes.

### 5.11.1 Identidad, procedencia y condiciones

### 5.11.2 Latencia de detección

### 5.11.3 Comparación pareada con el grupo de control

### 5.11.4 Tiempo de notificación

### 5.11.5 Resiliencia ante un corte del intermediario de mensajería

### 5.11.6 Suites y corrección evaluada

### 5.11.7 Síntesis del candidato
