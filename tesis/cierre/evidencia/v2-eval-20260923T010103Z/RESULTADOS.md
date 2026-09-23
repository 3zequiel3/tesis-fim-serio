# Evaluación unificada — candidato `v3.0-tesis`

Corrida del 2026-09-23, 01:01 a 02:24 UTC. Commit `22f393d`, árbol `17b4604`. Procedencia verificada
por hash del árbol del contenedor contra el árbol de trabajo: coinciden.

Este candidato incorpora la Change 59 (`notify-isolate-executor-lane`, D76/RN-170), que aísla el
carril de notificación en su propio *executor* con concurrencia acotada. El candidato anterior,
`v2.0-tesis`, es el **antes** de esa corrección y su paquete es
`tesis/cierre/evidencia/v2-eval-20260922T175053Z/`.

---

## 1. Drenaje tras un corte — el objetivo de la corrección

| Repetición | `v2.0-tesis` | `v3.0-tesis` |
|---|---|---|
| run-01 | 141,061 s | **37,873 s** |
| run-02 | 120,366 s | **37,213 s** |
| run-03 | 150,150 s | **37,957 s** |
| Mediana | 141,061 s | **37,873 s** |
| Tasa | ≈ 18,9 ev/s | **≈ 70,6 ev/s** |

**Mejora de 3,7× en la mediana**, y la dispersión se estrecha de 30 s a 0,7 s entre repeticiones.

Preservación **100 % de los encolados** en las tres repeticiones de ambos candidatos: 2.674, 2.670 y
2.674 eventos, 0 descartados, 0 duplicados, 0 rechazos.

**El umbral del protocolo sigue sin cumplirse.** El protocolo exige drenar en 30 s y la mediana es
37,873 s. La corrección reduce el incumplimiento de 4,7× a 1,26×, pero no lo elimina.

## 2. Latencia de detección — no se degradó

| | `v2.0-tesis` | `v3.0-tesis` |
|---|---|---|
| n | 483 | 484 |
| Media | 45,797 ms | 48,712 ms |
| P50 | 46,524 ms | 48,916 ms |
| P95 | 62,615 ms | 61,119 ms |
| P99 | 67,481 ms | 65,038 ms |
| Máximo | 132,768 ms | 80,023 ms |
| Negativos | 0 | 0 |

Sin cambio material en la tendencia central; los percentiles altos y el máximo mejoran. Contra el
umbral de 1.000 ms, se cumple con un orden de magnitud de margen.

## 3. Notificación — la contrapartida de la cota

Comparación a **igual carga**, 1.000 eventos por escenario en los dos candidatos:

| | `v2.0-tesis` | `v3.0-tesis` |
|---|---|---|
| Entregadas, escenario secuencial | **213 de 1.000** | **1.000 de 1.000** |
| Entregadas, concurrencia 50 | **0 de 1.000** | **1.000 de 1.000** |
| Entregadas, concurrencia 100 | **0 de 1.000** | **1.000 de 1.000** |
| Media, secuencial | 6.918,762 ms | 13.170,494 ms |

Los tres escenarios de `v3.0-tesis`:

| Escenario | n | Media | P50 | P95 | P99 | Máx |
|---|---|---|---|---|---|---|
| secuencial | 1000 | 13.170,494 | 13.955,994 | 21.637,906 | 22.209,017 | 22.228,375 |
| conc50 | 1000 | 11.670,719 | 12.100,248 | 19.890,119 | 20.406,679 | 20.473,269 |
| conc100 | 1000 | 10.536,879 | 10.950,617 | 18.504,900 | 18.910,475 | 19.005,947 |

**La notificación individual tarda casi el doble, y eso es la cota funcionando, no un defecto.** Antes
la cadena saturaba y 787 de 1.000 notificaciones no llegaban nunca en el escenario secuencial, y
ninguna llegaba en los dos concurrentes. Ahora llegan las 3.000, esperando turno. La cota convierte
pérdida silenciosa en espera declarada.

Queda como decisión abierta si 32 entregas concurrentes es el valor correcto: subirlo baja la latencia
de notificación y devuelve presión al carril de ingesta, que es exactamente el acoplamiento que esta
change eliminó.

Canal de entrega: **n8n**, el primario del protocolo, con Mailpit como destino SMTP final.

## 4. Trazas causales — por primera vez propias de cada repetición

| Repetición | Registros | Primer registro |
|---|---|---|
| run-01 | 65.121 | 2026-09-23T02:01:36 |
| run-02 | 65.754 | 2026-09-23T02:09:25 |
| run-03 | 65.850 | 2026-09-23T02:17:18 |

Las tres tienen hash distinto y cada una comienza dentro de su propia ventana. Las tres repeticiones
arrancaron con la base en `events=0`, verificado por el arnés.

En el paquete de `v2.0-tesis` las tres trazas eran **el mismo archivo copiado tres veces**; su acta
está en `v2-eval-20260922T175053Z/resiliencia/MOTIVO_TRAZAS_INVALIDAS.md`.

## 5. Suites sobre el candidato

860 pasando, 4 saltados, 0 fallando.

**Matiz que debe declararse**: los 8 fallos preexistentes por colisión del puerto 8443 no aparecen
porque la corrida usa contenedores efímeros de Postgres y Valkey, no porque se hayan corregido. El
entorno cambió, no el resultado de esas pruebas.

## 6. Supuesto abierto, declarado y no resuelto

La contabilidad causal de las operaciones que no llegaron a encolarse **no cierra**. El generador
emite 3.000 operaciones y el registro del agente marca 420 líneas `modify colapsado` por repetición,
pero 420 + 2.674 = 3.094 > 3.000: el marcador de colapso **no particiona** el universo de operaciones,
de modo que algunas operaciones colapsadas produjeron igualmente un evento encolado antes.

No se infiere explicación. Cerrarlo requiere instrumentación adicional en el agente, que es otra
change. Este es el séptimo dato que el protocolo enumera para la Batería 5 y **queda sin cubrir**.

## 7. Custodia

`SHA256SUMS` verifica 46 de 46. Las trazas se almacenan comprimidas con gzip y el sello certifica el
contenido **sin** comprimir: descomprimir con `gunzip -k` antes de `sha256sum -c`.

## 8. Intento inválido preservado

La primera corrida de este mismo candidato está en
`tesis/cierre/evidencia/invalidos/v3-eval-20260922T233242Z-sin-sumidero/`, con su acta. Midió las tres
baterías de notificación contra un sumidero SMTP inexistente y reportó 23 latencias negativas por un
reloj aún convergiendo.
