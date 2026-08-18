# Guion de defensa de tesis — 10 minutos (dos presentadores)

> **Tesis**: [TÍTULO A CONFIRMAR — sugerido: "Plataforma de Monitoreo de Integridad de Archivos (FIM) para hosts Linux"]
> **Presentan**: Nico y Eze · **Director/a**: [DIRECTOR/A A CONFIRMAR]
> **Duración objetivo**: 10:00 · Ritmo ~130–150 palabras/minuto
>
> Convenciones del guion:
> - **Nico** / **Eze**: quién habla.
> - `[MOSTRAR: ...]`: apoyo visual (slide, diagrama, captura, demo, tabla, código).
> - El texto está pensado para leerse y practicarse en voz alta, en español rioplatense natural.

---

## [0:00–0:45] Apertura e identificación

`[MOSTRAR: Slide de título — nombre de la tesis, nombres de los dos autores, director/a, universidad, fecha]`

**Nico:** Buenas, buenas tardes a todos. Muchas gracias al tribunal por el tiempo. Soy Nico.

**Eze:** Y yo soy Eze. Venimos a presentar nuestra tesis de grado: una **plataforma de monitoreo de integridad de archivos** —lo que en la industria se conoce como FIM, *File Integrity Monitoring*— pensada para hosts Linux.

**Nico:** La idea, en una frase: detectar cuándo un archivo crítico de un servidor cambió sin que nadie lo autorizara, y darle a un operador las herramientas para decidir qué hacer con ese cambio. Arrancamos por el problema que nos motivó.

---

## [0:45–2:00] Problema y motivación

`[MOSTRAR: Slide con un caso concreto — ícono de servidor con un archivo /etc/ modificado por un proceso desconocido; abajo, logos de AIDE, Tripwire, Wazuh]`

**Nico:** Pensemos en un servidor Linux de producción. Ahí viven archivos que casi nunca deberían cambiar: binarios del sistema, configuraciones en `/etc`, claves, cron jobs. Cuando uno de esos archivos cambia y nadie lo pidió, muchas veces es la **primera señal** de que algo anda mal: un atacante que dejó una puerta trasera, una configuración adulterada, un binario reemplazado.

**Nico:** El problema es que ese cambio, en el momento en que ocurre, es **invisible**. No dispara una alarma, no queda registrado con contexto. Cuando lo detectás, muchas veces ya es tarde.

`[MOSTRAR: comparativa breve — "detección periódica (scan) vs. detección reactiva (kernel)"]`

**Nico:** Las herramientas clásicas de FIM —AIDE, Tripwire— resuelven parte de esto, pero trabajan por **escaneo periódico**: comparan un snapshot cada tantas horas. Entre scan y scan, el cambio existe y no lo ves. Y casi ninguna te dice **qué proceso** hizo el cambio, ni te da un flujo claro para responder: aprobar, rechazar, restaurar. Ahí vimos nuestro espacio.

---

## [2:00–3:00] Pregunta de investigación y objetivos

`[MOSTRAR: Slide con la pregunta central destacada y debajo los 4 objetivos como bullets]`

**Eze:** Entonces la pregunta que guió el trabajo fue: **¿es posible construir una plataforma de FIM que detecte cambios en tiempo real, con contexto del proceso responsable, y que le dé a un operador un ciclo completo y seguro para decidir sobre cada cambio?**

**Eze:** De ahí salieron cuatro objetivos concretos. Primero, **detección reactiva**: enterarnos del cambio en el instante en que ocurre, no en el próximo scan. Segundo, **contexto forense**: saber qué proceso, qué usuario y qué ejecutable tocaron el archivo. Tercero, un **ciclo de decisión humano**: que un operador pueda aprobar, rechazar, restaurar o poner en cuarentena, con trazabilidad total. Y cuarto —y esto es central en nuestra tesis— hacerlo con una **arquitectura segura por diseño**: canal cifrado, mensajes firmados, y la línea base de referencia cifrada en reposo.

---

## [3:00–4:30] Marco teórico y antecedentes

`[MOSTRAR: Slide "Dónde se ubica este trabajo" — tabla: AIDE / Tripwire / OSSEC-Wazuh vs. nuestra propuesta, columnas: detección, contexto de proceso, ciclo de aprobación]`

**Nico:** Un poco de contexto sobre qué existe. La integridad de archivos se resuelve, en esencia, con **funciones de hash**: guardás un hash de referencia —la *baseline*— y comparás. Si el hash cambió, el archivo cambió. Eso es lo que hacen AIDE y Tripwire, que son los referentes históricos.

**Nico:** OSSEC y su sucesor **Wazuh** ya suman monitoreo más continuo y lo integran a un SIEM. Son herramientas maduras y potentes. Pero, para nuestro caso de uso, encontramos tres limitaciones que quisimos atacar.

`[MOSTRAR: los 3 puntos de diferenciación resaltados]`

**Nico:** Una: la **detección**. Nosotros no escaneamos periódicamente; usamos **fanotify**, un subsistema del kernel de Linux que nos **notifica** el cambio en el momento, y que además nos entrega el PID, el usuario y el ejecutable del proceso que lo causó. Eso, inotify o el scan clásico no te lo dan.

**Eze:** Dos: el **ciclo de decisión**. La mayoría de las herramientas te alertan y ahí termina. Nosotros modelamos el evento como una **máquina de estados** —de `pending` a `approved`, `rejected`, `superseded`— con aprobación humana y acciones ejecutables sobre el host. Y tres: **seguridad por diseño** en todo el canal agente–servidor, que es donde pusimos el foco de ingeniería.

---

## [4:30–6:30] Metodología

`[MOSTRAR: Diagrama de arquitectura — Agente (fanotify) → Valkey Streams → Backend (FastAPI + PostgreSQL) → Frontend (React); marcar mTLS + HMAC + baseline AES-GCM sobre el canal]`

**Eze:** Al ser un trabajo de **desarrollo de software**, nuestra metodología es de ingeniería, no de investigación empírica clásica. Tiene tres pilares.

**Eze:** El primero es la **arquitectura**. El sistema tiene cuatro piezas. Un **agente** en cada host, que corre como servicio systemd con la capacidad `CAP_SYS_ADMIN` y escucha el kernel con fanotify. Un **backend** en FastAPI con PostgreSQL, organizado por dominios —eventos, reglas, agentes, alertas, auth—. Un **frontend** en React para el operador. Y entre el agente y el backend, deliberadamente, **no hay HTTP**: se comunican por **Valkey Streams**, con el canal protegido por mTLS, cada mensaje firmado con HMAC, y la baseline cifrada con AES-256-GCM.

`[MOSTRAR: Slide "Desarrollo dirigido por especificaciones" — RN-01…RN-126, decisiones D1…D32, y el flujo propose → apply → archive]`

**Nico:** El segundo pilar es cómo lo construimos: **desarrollo dirigido por especificaciones**. Antes de escribir código, escribimos las reglas. Tenemos **126 reglas de negocio** trazables, y **32 decisiones de arquitectura** documentadas, cada una con su porqué. Ningún código entra sin pasar por una *change* especificada. Eso nos dio trazabilidad total entre lo que el sistema **debe** hacer y lo que **hace**.

`[MOSTRAR: Diagrama del proceso de revisión adversarial dual — un mismo cambio → Juez A + Juez B a ciegas → síntesis → fix]`

**Nico:** Y el tercero, que es nuestro **aporte metodológico** más fuerte: **verificación por revisión adversarial dual**. Por cada cambio, además de la suite de tests, lo pasamos por **dos revisores independientes y a ciegas**: uno empírico, que corre todo y verifica que esté verde; y otro adversarial, que asume que el código está mal y busca romperlo. Recién cuando los dos coinciden, el cambio se cierra. Y en un momento vamos a ver por qué eso importó tanto.

---

## [6:30–8:00] Resultados

`[MOSTRAR: Tabla de resultados — Backend: 8 dominios, ~341 tests; Agente: 16 módulos, ~267 tests; Frontend: 9 pantallas, 15 componentes; 126 reglas especificadas]`

**Eze:** ¿Qué construimos concretamente? El **backend** está implementado por dominios, con el ciclo de vida del evento, aprobación con *optimistic locking*, notificaciones y alertas en tiempo real. El **agente** tiene sus dieciséis módulos: detector fanotify, baseline cifrada, cola offline resiliente, motor de decisión. Y un **frontend** parcial con las pantallas de operación. En números: más de **600 tests** entre backend y agente sobre las 126 reglas especificadas.

`[MOSTRAR: DEMO opcional o captura — flujo de aprobación en la UI: evento pending → aprobar → baseline actualizada]`

**Eze:** Pero el resultado del que más orgullosos estamos no es una feature: es un **hallazgo metodológico**. La revisión adversarial dual encontró bugs **críticos que la suite de tests en verde ocultaba**. Dos ejemplos reales.

`[MOSTRAR: Slide "Bug 1 — Poison loop en borrados" — diagrama: agente emite hash=None → backend NOT NULL → IntegrityError → redelivery infinito]`

**Nico:** El primero. Un cambio renombró un campo del contrato entre el agente y el backend. Todos los tests seguían en verde. Pero para los archivos **borrados**, el agente empezó a mandar el hash como nulo, el backend lo rechazaba por ser un campo obligatorio, y el sistema lo reintentaba **infinitamente** —un *poison loop*—. Resultado: **todos los borrados se perdían**, ni se guardaban ni alertaban. En un FIM, no detectar un borrado es una falla de seguridad crítica. El revisor que corría todo lo daba por aprobado; **solo el revisor adversarial lo encontró**, porque los tests armaban el mensaje a mano con las claves correctas y nunca cruzaban de verdad el límite entre los dos procesos.

`[MOSTRAR: Slide "Bug 2 — Autenticaba pero no autorizaba" — agente A firma un ack válido para el comando del agente V]`

**Eze:** El segundo es todavía más fino. Teníamos una firma HMAC que **autenticaba pero no autorizaba**. El backend verificaba que la firma fuera válida, pero **nunca chequeaba que el agente que firmaba fuera el dueño del comando**. ¿Qué significa? Que un host comprometido, con su propia firma legítima, podía confirmar comandos de **otro** agente y **envenenarle la baseline** —hacerle aceptar como válido un archivo adulterado—. Autenticado, sí; autorizado, no. Ese es exactamente el tipo de bug que un test verde no ve y que un atacante sí aprovecha.

---

## [8:00–9:00] Discusión y conclusiones

`[MOSTRAR: Slide "Conclusiones" — 3 bullets: detección reactiva viable · seguridad por diseño · el verde no alcanza]`

**Nico:** ¿Qué nos dejan estos resultados? Tres conclusiones. La primera: la pregunta se respondió que **sí**. Es viable construir un FIM con detección reactiva, contexto de proceso y ciclo de decisión humano, sobre una arquitectura desacoplada y segura por diseño.

**Nico:** La segunda, y para nosotros la más valiosa: **una suite de tests en verde no es evidencia de que el sistema anda**. Los dos bugs más graves que encontramos convivían con tests que pasaban. La cobertura vivía dentro de cada proceso; los bugs vivían **en las costuras entre procesos**, que es justo donde ningún test miraba.

**Eze:** Y la tercera: la **revisión adversarial dual** no es un lujo, es parte del método. El ángulo empírico y el ángulo adversarial encuentran **cosas distintas**. Tenerlos a los dos, a ciegas y por separado, fue lo que nos permitió cerrar cada cambio con confianza real, no con confianza de tablero verde.

---

## [9:00–10:00] Limitaciones, trabajo futuro y cierre

`[MOSTRAR: Slide "Estado y limitaciones" — honesto: documentación 100% · implementación en curso · fanotify no probado en host real]`

**Eze:** Ahora, siendo honestos con el alcance. La **documentación y las especificaciones están 100% terminadas y validadas**. La **implementación está en curso**: hay varias *changes* aplicadas y revisadas en local —backend, agente, frontend parcial—, pero el sistema **no está desplegado end-to-end en producción**.

**Eze:** Y una limitación importante que queremos decir de frente: **fanotify no fue probado todavía contra un host real** con la capability `CAP_SYS_ADMIN` en producción. En nuestros tests, esa capa está *mockeada*. Es lo primero de la lista.

`[MOSTRAR: Slide "Trabajo futuro" — despliegue end-to-end · prueba con fanotify real · cifrado del secreto en DB · auditoría de calidad del frontend]`

**Nico:** Como **trabajo futuro**, entonces: el despliegue completo y la validación con fanotify real; endurecer el almacenamiento de secretos en la base; y una auditoría de calidad del frontend, que hasta ahora revisamos solo por contratos, no por arquitectura ni UX.

**Nico:** Cerramos con esto: creemos que el aporte no es solo la plataforma, sino **el método** con el que la construimos y verificamos. Muchas gracias.

**Eze:** Gracias, y quedamos a disposición del tribunal para las preguntas.

`[MOSTRAR: Slide final — título de la tesis + "Gracias" + datos de contacto de los dos autores]`
