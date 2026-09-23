# Corrida inválida — no usar para el informe

Primera evaluación unificada del candidato **`v3.0-tesis`**, ejecutada el 2026-09-22 entre las
23:32 y las 00:53 UTC. Se conserva en lugar de borrarse, con su motivo, como el resto de los
intentos inválidos del proyecto.

## Dos defectos de entorno, ninguno del código bajo prueba

### 1. Las tres baterías de notificación midieron contra un sumidero inexistente

Los tres escenarios reportan **0 muestras y 0 correos**. La causa no es el sistema: el contenedor
`fim-mailpit` estaba **detenido**, y `docker-compose.mailpit.yml` sólo contenía *overrides* de
variables para `backend` y `n8n` — **nunca definió el servicio**. Mailpit se levantaba a mano, fuera
de compose, de modo que nada en el arnés lo creaba ni verificaba que existiera.

El camino de notificación funcionó correctamente: creó 2.673 alertas y reintentó la entrega. Con
`SMTP_HOST=fim-mailpit` sin resolver y el webhook de n8n fallando, la escalera de reintentos entró
en esperas de 30 s y la batería, que espera ~30 s, midió cero.

**Esto contamina además la batería de resiliencia de esta corrida.** El perfil de carga no es
comparable con el de `v2.0-tesis`: allí las notificaciones se entregaban en ~300 ms cada una, y acá
fallaban y reintentaban. Los tiempos de drenaje de esta corrida —34,581 / 36,737 / 36,392 s— **no
pueden contrastarse** contra los 141,061 / 120,366 / 150,150 s del candidato anterior.

### 2. Veintitrés latencias negativas por un reloj aún convergiendo

La batería de latencia informa `negativos=23` sobre 485 muestras, con un mínimo de −34,4 ms. Una
latencia negativa significa que el huésped estampó la detección después de que el anfitrión estampara
la recepción: mide los relojes, no el sistema.

Los 23 casos **se concentran en los primeros 83 segundos** de una ventana de 1.796, y no vuelve a
aparecer ninguno en la media hora restante. Es el patrón de un reloj asentándose, no el de un
desfasaje sostenido. El huésped había reiniciado a las 22:27 UTC.

Conviene dejar asentado un error de método propio: se intentó medir el desfasaje ejecutando
`multipass exec fim-host -- date` y corrigiendo por ida y vuelta. Ese instrumento informó ~150 ms de
forma consistente, y **ese valor no existe**: el viaje de ida y vuelta de `multipass exec` es de unos
300 ms y es asimétrico, de modo que el comando se ejecuta tarde dentro del intervalo y el huésped
aparece adelantado. Contrastado contra NTP, el anfitrión está a 0,8 ms de la hora de referencia y el
huésped sincroniza con jitter de 1,4 ms: no hay tal desfasaje. Un instrumento cuya resolución es
diez veces peor que la magnitud medida no puede usarse para medirla.

## Lo que sí es válido en esta corrida

La procedencia está verificada —árbol del contenedor idéntico al del árbol de trabajo— y **las trazas
causales son, por primera vez, propias de cada repetición**: 64.900, 66.654 y 67.003 registros, cada
una comenzando dentro de su ventana, y las tres repeticiones arrancando en `events=0`. Las
correcciones del arnés introducidas antes de esta corrida funcionaron.

## Correcciones aplicadas antes de repetir

- `docker-compose.mailpit.yml` **define** el servicio `mailpit`, con `container_name: fim-mailpit`,
  alias de red y *healthcheck*. El arnés lo levanta junto al backend.
- El arnés aborta si el backend no resuelve `fim-mailpit` o si la API del sumidero no responde.
- El arnés exige que ambas máquinas se declaren sincronizadas por NTP y espera un período de
  asentamiento antes de la batería de latencia.
- Tras la batería de latencia, el arnés informa cuántas muestras negativas hubo y si se concentran al
  inicio —reloj convergiendo— o se reparten por toda la ventana —desfasaje que invalida la corrida.
- Se eliminó el medidor de desfasaje basado en `multipass exec`, por no tener resolución suficiente.
