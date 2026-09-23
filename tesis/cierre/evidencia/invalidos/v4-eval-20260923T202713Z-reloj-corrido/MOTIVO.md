# Corrida inválida — no usar la batería de latencia

Segunda evaluación unificada del candidato **`v4.0-tesis`** (`1f28c9e`), ejecutada el 2026-09-23 entre
las 20:27 y las 21:50 UTC.

## El defecto: el reloj del huésped estaba corrido, y la guarda no lo vio

La batería de latencia informa **347 muestras negativas sobre 484**, con media −6,840 ms y mediana
−5,276 ms. Una latencia negativa es imposible: significa que el huésped estampó la detección después
de que el anfitrión estampara la recepción. Toda la distribución aparece desplazada unos 54 ms
respecto de la corrida anterior del mismo sistema.

La guarda de reloj que el arnés traía exigía que ambas máquinas se declararan sincronizadas por NTP, y
**las dos lo declaraban**. Ese es el punto: `systemd-timesyncd` informa `NTPSynchronized=yes` sondeando
hasta cada 34 minutos y corrigiendo despacio, de modo que «sincronizado» convive sin contradicción con
un error mayor que la magnitud que se está midiendo. La guarda no era débil por descuido: preguntaba
lo que no había que preguntar.

## Qué se corrigió

- Se instaló **chrony** en el huésped, en lugar de `systemd-timesyncd`. Tras converger, el huésped
  queda a microsegundos de la hora de referencia y el anfitrión bajo el milisegundo.
- La guarda ya no pregunta si hay sincronización: **lee el desvío informado por chrony en las dos
  máquinas, en microsegundos, y aborta si cualquiera supera un techo explícito** (5.000 µs por
  defecto, configurable con `CLOCK_MAX_US`). El desvío de ambas queda escrito en la procedencia.

Comprobación posterior al arreglo, sobre el laboratorio limpio: seis operaciones reales midieron entre
22,1 y 31,6 ms, **todas positivas**, en el rango histórico del sistema.

## Lo que sí es válido en esta corrida

Todo lo que no depende de comparar relojes de dos máquinas. El drenaje y la notificación se miden con
marcas tomadas ambas del lado del anfitrión.

| Suite | Tests | Fallas | Omitidos |
|---|---|---|---|
| agente | 642 | 0 | 1 |
| backend | 887 | 0 | 4 |
| frontend | 260 | 0 | 0 |

| Escenario de notificación | n | Entregadas | Media |
|---|---|---|---|
| secuencial | 1000 | 1000 | 13.455,937 ms |
| concurrencia 50 | 1000 | 1000 | 11.528,103 ms |
| concurrencia 100 | 1000 | 1000 | 9.819,435 ms |

| Repetición | Encolados | Entregados | Descartados | Drenaje |
|---|---|---|---|---|
| run-01 | 2.673 | 2.673 | 0 | 34,417 s |
| run-02 | 2.672 | 2.672 | 0 | 35,863 s |
| run-03 | 2.668 | 2.668 | 0 | 32,877 s |

Estas cifras de drenaje —mediana 34,417 s— son las que corresponden al sistema **completo**, con el
carril de notificación entregando 3.000 de 3.000. Contrastan con los 29,4 a 30,2 s del intento
anterior, que midió con cero alertas creadas por un esquema desactualizado y por eso parecía cumplir
el umbral.
