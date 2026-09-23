# Corrida inválida — no usar para el informe

Primera evaluación unificada del candidato **`v4.0-tesis`** (`1f28c9e`), ejecutada el 2026-09-23 entre
las 19:02 y las 20:23 UTC. Se conserva con su motivo, como el resto de los intentos inválidos.

## El defecto: el esquema de la base no acompañó al candidato

Este proyecto aplica las migraciones **a mano**, por decisión documentada (D3), y **el arnés nunca las
aplicaba**. El candidato incorpora la migración `022_add_alert_channel_accepted_at.sql`, que agrega la
columna `channel_accepted_at` a `alerts`. El arnés reconstruyó el backend desde el tag —con el modelo
que declara esa columna— contra una base que no la tenía.

En consecuencia, **todo `INSERT` sobre `alerts` falló**. La medición lo muestra sin ambigüedad:

| Magnitud | Valor |
|---|---|
| Eventos ingeridos | 2.672 |
| Alertas creadas | **0** |
| Notificaciones entregadas, los tres escenarios | **0** |

## Por qué este defecto es peor que los anteriores

Los defectos de arnés detectados antes —trazas acumulativas, control acumulativo, sumidero ausente,
candidato de suites clavado— degradaban o falseaban un dato. **Este mejoró el resultado.**

Con cero alertas creadas, el carril de notificación no hizo trabajo alguno, y el drenaje de ingesta
quedó sin su competidor:

| Repetición | Drenaje observado |
|---|---|
| run-01 | 29,383 s |
| run-02 | 29,511 s |
| run-03 | 30,237 s |

Contra los 37,873 s de mediana del candidato anterior, eso parece **cruzar el umbral de 30 s que el
protocolo exige y que hasta ahora no se cumplía**. No lo cruza: mide un sistema al que le falta un
subsistema. La cifra es inválida y **no debe informarse como cumplimiento**, ni siquiera con una nota
al pie.

Un defecto que empeora un número se descubre solo. Un defecto que lo mejora se publica.

## Lo que sí es válido en esta corrida

Las **suites** no dependen de la base del laboratorio: corren contra contenedores efímeros, y su
procedencia está estampada con el candidato correcto (`candidate_tag=v4.0-tesis`,
`candidate_commit=1f28c9e`).

| Suite | Tests | Fallas | Omitidos |
|---|---|---|---|
| agente | 642 | 0 | 1 |
| backend | **887** | **0** | 4 |
| frontend | 260 | 0 | 0 |

Es la primera corrida del proyecto en la que el artefacto sellado de suites corresponde al candidato
evaluado y no arrastra fallas de acoplamiento: las 15 del candidato anterior —13 por el puerto 8443
fijo y 2 por el `.env` resuelto contra el directorio de trabajo— quedaron cerradas por la Change 60.

La procedencia del binario también verificó: el árbol del contenedor coincide con el del árbol de
trabajo (`c17ec878…`).

## Corrección aplicada antes de repetir

El arnés ahora, antes de medir nada:

1. Aplica todas las migraciones de `backend/db/migrations/` en orden.
2. **Verifica el resultado**, que es lo que de verdad cierra el agujero: compara los campos que
   declara cada modelo de SQLModel contra las columnas que la tabla tiene, y **aborta** nombrando las
   que faltan. Correr las migraciones sin comprobar el resultado habría dejado el mismo defecto a un
   error de ejecución de distancia.
