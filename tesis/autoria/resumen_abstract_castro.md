# RESUMEN

Este Trabajo Final diseña, implementa y evalúa en laboratorio una plataforma distribuida de monitoreo de integridad de archivos para sistemas Linux. Parte de la premisa de que la verificación periódica deja ventanas de ceguera, expone la línea base a la manipulación local y se integra mal con la respuesta a incidentes.

El artefacto combina un agente nativo en Python, que detecta los cambios mediante fanotify y decide en forma local, con un backend en FastAPI y PostgreSQL que registra y resuelve los eventos. Valkey Streams actúa como intermediario de mensajería, n8n orquesta las notificaciones y una consola en React sostiene la validación humana.

La evaluación de la versión v5.1-tesis registró un percentil 99 de 41,73 ms (IC 95 %: 40,53 a 42,32 ms) en el tramo entre el agente y el backend. Ese tramo excluye la permanencia en la cola del núcleo, y el valor rige solo por debajo de 1,67 eventos por segundo, el ritmo sostenido que admite el límite de ingesta. Frente a un esquema que escanea cada quince minutos, el artefacto detectó entre 79,4 y 85,6 puntos porcentuales más de operaciones en tres réplicas. El esquema periódico no registró entre el 80,4 y el 85,6 % de las operaciones; con la lectura por archivo, que solo exige advertir que el archivo cambió, no registró entre el 25,6 y el 49,8 %. Ante un corte de cinco minutos del intermediario, el backend persistió todo lo encolado, en orden y sin duplicados. La automatización del triage alcanzó el 81,8 %, por encima del umbral por una sola tarea.

Cuatro criterios no alcanzan su definición preregistrada. El percentil 99 del tiempo de notificación llegó a unos 29,5 s con colas de 1.000 eventos, frente a un umbral de 5 s, y la cobertura de historias de usuario fue de 24 sobre 31 en conteo estricto. El agente no encoló dos o tres de cada 3.000 operaciones, y seis de 1.500 no produjeron evento: en ambos casos, reversiones al contenido aprobado que suprime por diseño. El drenaje tras la reconexión, de 25,3 a 27,0 s, no es concluyente, porque la ráfaga del límite de ingesta se dimensionó con la cola de la misma batería. Además, el agente no observa cambios de permisos, propietario ni capacidades, y la línea base cifrada no resiste a un adversario con privilegios de administrador sobre el anfitrión. En consecuencia, la hipótesis conjunta no se corrobora.

**Palabras clave:** Monitoreo de Integridad de Archivos, fanotify, Zero Trust, autenticación mutua, Ley 25.326.

---

# ABSTRACT

This Final Project designs, implements and evaluates, in a laboratory environment, a distributed file integrity monitoring platform for Linux systems. It starts from the premise that periodic verification leaves blind windows, exposes the baseline to local tampering and integrates poorly with incident response.

The artifact combines a native Python agent, which detects changes through fanotify and makes decisions locally, with a FastAPI and PostgreSQL backend that records and resolves the events. Valkey Streams acts as the message broker, n8n orchestrates the notifications and a React console supports human validation.

The evaluation of version v5.1-tesis recorded a 99th percentile of 41.73 ms (95% CI: 40.53 to 42.32 ms) on the segment between the agent and the backend. That segment excludes the time spent in the kernel queue, and the value holds only below 1.67 events per second, the sustained rate allowed by the ingest limit. Compared with a scheme that scans every fifteen minutes, the artifact detected between 79.4 and 85.6 percentage points more operations across three replicas. The periodic scheme failed to record between 80.4% and 85.6% of the operations; under the per-file reading, which only requires noticing that the file changed, it failed to record between 25.6% and 49.8%. During a five-minute outage of the broker, the backend persisted everything that had been queued, in order and without duplicates. Triage automation reached 81.8%, above the threshold by a single task.

Four criteria do not meet their preregistered definition. The 99th percentile of notification time reached about 29.5 s with queues of 1,000 events, against a 5 s threshold, and user-story coverage was 24 out of 31 under strict counting. The agent did not queue two or three out of every 3,000 operations, and six out of 1,500 produced no event: in both cases, reversions to the approved content that the agent suppresses by design. The drain time after reconnection, between 25.3 and 27.0 s, is inconclusive, because the burst of the ingest limit was sized using the queue of the same test battery. Furthermore, the agent does not observe permission, ownership or capability changes, and the encrypted baseline does not withstand an adversary with administrator privileges on the host. Consequently, the joint hypothesis is not corroborated.

**Keywords:** File Integrity Monitoring, fanotify, Zero Trust, mutual authentication, Law 25.326.
