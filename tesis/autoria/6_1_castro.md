6.1 Interpretación de los resultados obtenidos



La evaluación de la versión v5.1-tesis representa el escenario más cercano al despliegue recomendado: incorpora un agente nativo, mantiene n8n activo hacia un capturador SMTP local, aplica el límite de ingesta del producto, purga la línea base entre repeticiones y verifica la procedencia antes de medir (según el apartado 3.7). Aunque la Tabla 26 dictamina el resultado de cada criterio y concluye que la hipótesis conjunta no se corrobora, este apartado busca ir más allá de ese veredicto. Para ello, el análisis se estructura en torno a tres interrogantes fundamentales: qué evidencian los datos, qué limitaciones presentan y qué explicaciones alternativas admiten.



¿Qué muestran los datos?

En respuesta a la interrogante planteada en el apartado 1.2, los resultados evidencian con claridad la proporción de carga que el control periódico omite. Al medir por operación, la omisión rondó entre el 80,4 % y el 85,6 %, causada principalmente por el colapso de modificaciones sucesivas o por cambios que se deshicieron antes de que ocurriera el escaneo (Tabla 18). Si se contabiliza por archivo, lo que resultó invisible para el control se situó entre el 25,6 % y el 49,8 %. Frente a cambios dinámicos, el escaneo periódico no solo es lento, sino también «ciego» a una parte de ellos. Esa pérdida, sin embargo, no constituye un hallazgo empírico independiente, sino la expresión de un mecanismo estructural: el control detecta a lo sumo un cambio por ruta y escaneo, de modo que su proporción no puede superar la cota R·S/n, que con los parámetros ensayados es del 60 %. El control es, por tanto, demostrativo (apartado 5.3), y los datos cuantifican la ventana de ceguera sobre la carga ensayada, no la del escaneo periódico en general.



Por otro lado, la latencia de la solución propuesta es aproximadamente cuatro órdenes de magnitud inferior a la del control. No obstante, este contraste por sí solo no valida la tesis, ya que cualquier arquitectura de naturaleza reactiva superaría inherentemente a un escaneo configurado cada quince minutos. Aun así, la latencia obtenida se encuentra dentro del orden de magnitud documentado en la literatura para la detección mediante eventos del núcleo. Por ejemplo, herramientas como Peeler reportan medias de 115 ms (Ahmed et al., 2021); Falco, Tetragon y Tracee oscilan entre 0,42 y 1,62 s (Syairozi \& Arizal, 2025); y Wazuh promedia 3.033 ms en diferentes escenarios de ataque (Sutanto \& Rakhman, 2025). Dado que estos trabajos miden desde el inicio del ataque hasta la alerta, la comparación sirve para contextualizar la magnitud del tiempo de respuesta, no para afirmar estrictamente que este artefacto sea más rápido (Tabla 3).



En el plano de datos, la versión v5.1-tesis logró persistir todo el volumen encolado, respetando el orden y sin registrar duplicados. Un aspecto técnico a destacar es que el control anti-replay no haya rechazado eventos: si se hubiera implementado una ventana basada de forma estricta en el instante de detección, se habría rechazado masivamente cualquier cola acumulada por más de cinco minutos (apartado 4.5). En cuanto a las notificaciones, se entregaron todas las alertas, aunque sujetas a esperar su turno en una cadena de n8n que entrega entre 32 y 34 notificaciones por segundo. Esto confirma que el límite reside aguas abajo del backend —específicamente en la cadena de n8n y SMTP— y no en el backend propiamente dicho (apartado 5.4).



¿Qué no muestran los datos?

La latencia inferior al segundo es válida únicamente en condiciones de operación habitual (apartado 5.2); basta un evento masivo, como una actualización de paquetes del sistema, para superar esa marca. En el plano de control, el tiempo de drenaje arrojó resultados no concluyentes (apartado 5.5). Además, se identificó que la indisponibilidad del intermediario Valkey inhabilita por completo la superficie autenticada del backend (apartado 6.6). Este último punto representa una limitación operativa severa. La Disposición 1/2026 obliga solo a los organismos del Sector Público Nacional, no a los sistemas, y exige planes de contingencia que el sistema no sustituye (Tabla 2 y apartado 6.3); por eso, no corresponde dictaminar si el sistema la satisface. Sí puede afirmarse que, para un organismo alcanzado, un sistema que preserva la evidencia pero impide consultarla durante un incidente dificulta sostener la continuidad del servicio que la disposición exige, y que esa indisponibilidad debería contemplarse en sus planes de contingencia.



A estas limitaciones se suma un alcance restringido en las pruebas, las cuales proceden de un único agente en una máquina virtual, con tres repeticiones por batería (apartado 5.1). En esas condiciones, el orden de entrega se sostuvo en las tres repeticiones y el backend persistió todo lo encolado, sin duplicados; aun así, la preservación no alcanza su definición preregistrada, porque el agente encoló el 99,9 % de las operaciones generadas, y el tiempo de drenaje resultó no concluyente (apartado 5.5 y Tabla 26). Tres repeticiones muestran esos resultados, no los garantizan. Si bien los datos indican que la arquitectura atiende la ventana de ceguera bajo las condiciones ensayadas, carecen de validez externa (apartado 6.5) para extrapolar afirmaciones sobre despliegues distribuidos, cargas sostenidas de alta intensidad o volúmenes mayores.



¿Qué explicaciones alternativas quedan abiertas?

Existen tres resultados cuyo comportamiento podría explicarse por factores ajenos al diseño de la plataforma:



La proporción de cambios detectados: esta métrica no cuenta con una contraparte publicada para compararse directamente y depende de manera crítica de los parámetros de la carga inyectada (donde la cota R·S/n determina gran parte de la diferencia observada frente al control demostrativo, apartado 5.3). Para otorgarle mayor validez a esta comparación, sería necesario incorporar un comparador de mercado real y realizar un barrido sistemático variando el período y el número de rutas (apartados 6.7 y 8.1).



La cobertura del proceso de triage: el sistema superó el umbral de éxito por apenas una tarea de diferencia. Sin embargo, la lista de criterios fue elaborada y aplicada por los propios autores, y su reducción (de trece a once tareas) ocurrió después de obtener el primer resultado (apartado 1.6). Por lo tanto, no se puede descartar que la propia construcción de la métrica haya condicionado el éxito. Asimismo, las dos tareas que permanecen manuales son aquellas que requieren juicio experto, lo que evidencia que el diseño no elimina al operador, sino que le reserva la decisión.



La cota de latencia obtenida: el percentil 99 de 41,73 ms no es un subproducto del límite de ingesta, porque la batería corrió a 0,28 operaciones por segundo, seis veces por debajo del ritmo sostenido de 1,67 eventos por segundo que ese límite admite, de modo que el límite no intervino en la medición (apartado 5.2). Lo que sí depende de la configuración es el dominio de validez de la cota: por encima de ese ritmo, la latencia se degradaría según lo que el límite permite derivar, una estimación que la evaluación no midió. La configuración condiciona, en cambio, el tiempo de drenaje: la cola de unos 3.000 eventos cupo entera en la ráfaga de 3.000 fichas, que los autores dimensionaron con referencia a esa misma batería, por lo que el resultado es no concluyente (apartado 5.5). Por otra parte, afirmar que es preferible contar con una alerta tardía pero registrada en lugar de una alerta perdida constituye un juicio sobre el diseño, no un parámetro técnico riguroso evaluable mediante la Tabla 1.

