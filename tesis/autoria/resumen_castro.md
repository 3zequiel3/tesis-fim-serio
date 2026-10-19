RESUMEN



Este Trabajo Final diseña, implementa y evalúa en un entorno de laboratorio una plataforma distribuida de monitoreo de integridad de archivos para sistemas Linux. El proyecto surge de la premisa de que la verificación periódica tradicional genera ventanas de ceguera, expone la línea base a manipulaciones locales y ofrece una integración deficiente con los procesos de respuesta a incidentes.




Para abordar esta problemática, se desarrolló una arquitectura compuesta por un agente nativo en Python que detecta cambios en tiempo real mediante fanotify y toma decisiones de forma local. La infraestructura se complementa con un backend en FastAPI y PostgreSQL para el registro y resolución de los eventos, Valkey Streams como intermediario de transporte, n8n para el manejo de notificaciones, y una interfaz en React que facilita la validación humana.




La evaluación de la versión final (v5.1-tesis) registró una latencia de 41,73 ms (percentil 99) entre el agente y el backend. Este valor representa una cota inferior de la latencia real y se mantiene válido bajo un ritmo de ingesta sostenido inferior a 1,67 eventos por segundo. Al contrastar esta solución con un enfoque de escaneo tradicional de quince minutos, este último falló en registrar entre el 80,4 % a el 85,6 % de las operaciones individuales (omitiendo entre el 25,6 % a el 49,8 % de los archivos modificados). Asimismo, las pruebas de resiliencia demostraron que, ante una caída de cinco minutos del intermediario, el sistema logra encolar y entregar la totalidad de los eventos en orden y sin duplicados.





Sin embargo, la evaluación del tiempo de drenaje (esperado en menos de 30 s) resultó no concluyente, dado que la ráfaga del límite de ingesta se dimensionó en función de la cola ensayada. Por otra parte, no se alcanzaron las metas estipuladas para el tiempo de notificación y la cobertura de historias de usuario; tampoco se logró cumplir, en su definición literal, con los criterios de preservación y prevención de falsos negativos. A nivel de seguridad, el agente actual no audita cambios de permisos, propietario o capacidades (capabilities), y la línea base carece de protección frente a un adversario con máximos privilegios. En consecuencia, la hipótesis conjunta del trabajo no se corrobora.





Palabras clave: Monitoreo de Integridad de Archivos, fanotify, Zero Trust, autenticación mutua, Ley 25.326.

