# Datos para el informe — candidato `v3.0-tesis`

Este documento reemplaza a `INSUMOS_V18_A1_A7.md`, `INSUMOS_V18_A8_B3.md` e `INSUMOS_V18_C.md` como
fuente de cifras. Aquellos describen el estado anterior a la Change 59 y quedan como registro
histórico.

Todas las cifras salen de un **único candidato** y de una **única corrida**, que es lo que permite
responder en una línea la pregunta más incómoda de una defensa: *¿qué versión estoy mirando?*

---

## 0. Identidad del candidato y procedencia

| Campo | Valor |
|---|---|
| Tag | `v3.0-tesis` |
| Commit | `22f393df41fc4cfd5777e8631431924b1b16abb3` |
| Árbol | `17b460412ef30099bc67a5f0e399dcc138852293` |
| Paquete de evidencia | `tesis/cierre/evidencia/v2-eval-20260923T010103Z/` |
| Ventana de ejecución | 2026-09-23, 01:01 → 02:24 UTC |
| Sello | `SHA256SUMS`, 46 de 46 verifican |

**Procedencia del binario, no sólo del código**: el hash agregado de todo `app/**/*.py` dentro del
contenedor coincide con el del árbol de trabajo (`bfaae9f4a6dce9bb…`). Esta verificación existe porque
un paquete anterior se produjo contra una imagen construida cuatro días antes de su candidato
declarado, y nada en los registros lo mostraba.

Condiciones del entorno: mTLS agente ↔ backend activo, Valkey con TLS y certificado de cliente en
6380, agente nativo bajo systemd en el anfitrión monitoreado, n8n activo como canal primario de
notificación con Mailpit como destino SMTP final, trazas causales del agente activas en todas las
baterías, semilla registrada en el manifiesto de cada corrida.

---

## 1. Latencia de detección (Batería 3)

| Métrica | Valor |
|---|---|
| n | 484 |
| Media | 48,712 ms |
| P50 | 48,916 ms |
| P95 | 61,119 ms |
| P99 | 65,038 ms |
| Mínimo | 30,993 ms |
| Máximo | 80,023 ms |
| Muestras negativas | **0** |

Contra el umbral del protocolo de 1.000 ms, **se cumple con más de un orden de magnitud de margen**.

**Limitación declarada, no resuelta**: el intervalo medido va del estampado del agente al estampado
del backend. No incluye el tiempo que el evento estuvo en la cola del núcleo antes de que el agente lo
leyera, porque el protocolo pide instrumentar el inicio con `strace -ttt -T -f` y eso no se hizo. La
cifra es, por lo tanto, una **cota inferior declarada** de la latencia real.

**Sobre las muestras negativas**: una latencia negativa significaría que el huésped estampó la
detección después de que el anfitrión estampara la recepción, lo que mide los relojes y no el sistema.
Esta corrida no tiene ninguna. La corrida inmediatamente anterior tuvo 23 sobre 485, todas dentro de
los primeros 83 segundos de una ventana de 1.796 y ninguna después: un reloj convergiendo tras un
reinicio. El arnés ahora exige que ambas máquinas se declaren sincronizadas por NTP, espera un período
de asentamiento antes de medir, y reporta cuántas negativas hubo y si se concentran al inicio.

### Falsos negativos: 16 de 16 atribuidos, ninguno es un falso negativo

La Batería 3 ejecuta 500 operaciones y la plataforma persiste 484 eventos. Las 16 restantes **no se
resuelven restando**: restar no distingue «el sistema no la vio» —que sería un falso negativo— de «el
sistema la vio y decidió, correctamente, no reportarla», que es la política documentada, que informa
desviaciones respecto de la línea base y no operaciones de entrada/salida en bruto.

La distinción se establece con la traza causal del agente, que registra una entrada por etapa. El
cruce es reproducible y está publicado en `scripts/atribuir_operaciones_sin_evento.py`, sin
dependencias externas; el detalle por operación queda en `latencia/atribucion_sin_evento.csv` dentro
del paquete.

| Resultado | Valor |
|---|---|
| Operaciones del manifiesto | 500 |
| Eventos persistidos | 484 |
| Operaciones sin evento | 16 |
| **Atribuidas con causa** | **16 de 16** |
| Causa única hallada | `matches_active_baseline` |

Dos comprobaciones independientes del cruce, que salen de la misma traza:

- **Clasificados que no se persistieron: 0.** Todo lo que el agente decidió reportar llegó a la base.
- **Persistidos que no se clasificaron: 0.** Nada apareció en la base sin pasar por la decisión.

Es decir: no hay pérdida entre la clasificación y la persistencia, y las 16 ausencias son supresiones
deliberadas con motivo registrado. **El criterio de cero falsos negativos queda cerrado**, y no por
inferencia sino con el registro del propio sistema.

Hay precedente del mismo resultado en la corrida del 17 de septiembre, donde se atribuyeron 19 de 19
con idéntica causa.

---

## 2. Grupo de control e inferencia pareada (Batería 7)

Cron de 900 s sobre la misma carga y en la misma ventana que la Batería 3, que es lo que hace legítimo
el pareo.

| Métrica del control | Valor |
|---|---|
| n | 78 |
| Mediana | 591.169,758 ms |
| P99 | 898.961,628 ms |
| Media | 540.442,964 ms |
| Desvío muestral (ddof=1) | 275.684,821 ms |
| Mínimo / Máximo | 2.543,353 / 899.016,789 ms |
| Cambios nunca reportados | **422 de 500 (84,4 %)** |

Causas de los 422 no reportados: 294 por colapso entre scans, 128 nunca detectados. Por patrón: 265
simples, 69 revertidos, 68 colapsados, 20 efímeros.

### Tabla pareada — una observación por operación del generador

|  | control sí | control no | total |
|---|---|---|---|
| **FIM sí** | 71 | 413 | 484 |
| **FIM no** | 7 | 9 | 16 |
| **total** | 78 | 422 | 500 |

| Estadístico | Valor |
|---|---|
| Proporción detectada, FIM | 0,9680 (484/500) |
| Proporción detectada, control | 0,1560 (78/500) |
| **Diferencia pareada** | **0,8120** |
| **IC 95 % de Newcombe (pareado)** | **[0,7702; 0,8452]** |
| Pares discordantes | b = 413, c = 7 |
| **McNemar con corrección, χ²(1)** | **390,5357** |
| **valor p** | **6,32779 × 10⁻⁸⁷** |
| Factor de mejora (mediana) | 12.085,4× |
| Factor de mejora (P99) | 13.822,1× |

Script: `scripts/analisis_mcnemar.py`, sin dependencias externas. Referencia del intervalo: Newcombe,
R. G. (1998), método 10, para la diferencia entre proporciones binomiales **con datos pareados** —
no el trabajo sobre una proporción única.

Estas cifras replican las publicadas en la corrida del 17 de septiembre (χ² = 386,5409,
p = 4,69 × 10⁻⁸⁶, diferencia 0,8040, IC [0,7618; 0,8377]) sobre un candidato distinto y una corrida
independiente, lo que es evidencia de reproducibilidad y conviene declararlo como tal.

---

## 3. Notificación (Baterías 3 y 4), tres escenarios

Canal primario n8n, destino SMTP final Mailpit. Intervalo medido: `events.received_at` →
`alerts.delivered_at`.

**Este indicador no es el que la Tabla 4 define, y hay que decirlo.** La Tabla 4 define el intervalo
como recepción del evento por el backend → **emisión exitosa del webhook**, excluyendo explícitamente
la entrega dentro de n8n y en el canal final, y sólo por el camino feliz en el primer intento. Lo que
se mide es `alerts.delivered_at − events.received_at`, que es un intervalo distinto y mayor: incluye
la espera por un cupo de entrega, que bajo la cota de D76/RN-170 es justamente la parte grande.

Peor aún, **el protocolo ofrecía dos fuentes para validar de forma cruzada y las dos miden lo mismo
equivocado**. Su «Fuente B» propone el registro estructurado `notify.delivered` como emisión exitosa,
pero esa línea se emite *después* de que `_mark_delivered` persiste `delivered_at`: marca el mismo
instante, con un log en lugar de una columna.

El instante de aceptación **no existe hoy en ningún lado**: ninguna columna de `alerts` lo registra, y
la línea de registro que sí ocurre en el momento correcto —dentro de `send_n8n`, apenas la respuesta
se valida— no lleva identificador de alerta ni de evento, de modo que no puede reasociarse, y menos
con 32 entregas simultáneas en vuelo. La Change 60 agrega esa marca.

| Escenario | n | Entregadas | Media | P50 | P95 | P99 | Máx |
|---|---|---|---|---|---|---|---|
| secuencial | 1000 | **1000** | 13.170,494 | 13.955,994 | 21.637,906 | 22.209,017 | 22.228,375 |
| concurrencia 50 | 1000 | **1000** | 11.670,719 | 12.100,248 | 19.890,119 | 20.406,679 | 20.473,269 |
| concurrencia 100 | 1000 | **1000** | 10.536,879 | 10.950,617 | 18.504,900 | 18.910,475 | 19.005,947 |

### La comparación que importa, a igual carga

| | `v2.0-tesis` | `v3.0-tesis` |
|---|---|---|
| Entregadas, secuencial | 213 de 1.000 | **1.000 de 1.000** |
| Entregadas, concurrencia 50 | 0 de 1.000 | **1.000 de 1.000** |
| Entregadas, concurrencia 100 | 0 de 1.000 | **1.000 de 1.000** |
| Media, secuencial | 6.918,762 ms | 13.170,494 ms |

**Cada notificación tarda aproximadamente el doble, y eso es la cota funcionando.** Antes la cadena
saturaba: 787 de 1.000 notificaciones no llegaban nunca en el escenario secuencial, y ninguna llegaba
en los dos concurrentes. Ahora llegan las 3.000, esperando turno. La cota convierte **pérdida
silenciosa en espera declarada**, que para un sistema de monitoreo es el intercambio correcto.

Costo de una notificación **aislada**, medido aparte: 302,8 ms de media, 349,4 ms máximo, n = 10. La
diferencia contra los 13.170 ms bajo carga es encolamiento, no el canal.

Valor de la cota: 32 entregas concurrentes (`notify_max_concurrent_deliveries`). Queda como decisión
abierta si es el valor correcto: subirlo baja la latencia de notificación y devuelve presión al carril
de ingesta, que es exactamente el acoplamiento que la Change 59 eliminó.

---

## 4. Resiliencia ante un corte (Batería 5)

Corte real de 5 minutos del **broker** —Valkey, que es lo que el protocolo especifica, no el
backend— con 3.000 operaciones a 10/s.

| Repetición | Encolados | Entregados | Descartados | Duplicados | Fuera de orden | Ventana de drenaje |
|---|---|---|---|---|---|---|
| run-01 | 2.674 | 2.674 | 0 | 0 | 0 | **37,873 s** |
| run-02 | 2.670 | 2.670 | 0 | 0 | 0 | **37,213 s** |
| run-03 | 2.674 | 2.674 | 0 | 0 | 0 | **37,957 s** |

**Preservación: 100 % de los encolados en las tres repeticiones.** Cero rechazos.

### Contra el candidato anterior

| Repetición | `v2.0-tesis` | `v3.0-tesis` |
|---|---|---|
| run-01 | 141,061 s | 37,873 s |
| run-02 | 120,366 s | 37,213 s |
| run-03 | 150,150 s | 37,957 s |
| **Mediana** | **141,061 s** | **37,873 s** |
| Tasa | ≈ 18,9 ev/s | ≈ 70,6 ev/s |

**Mejora de 3,7× en la mediana**, y la dispersión entre repeticiones cae de 30 s a 0,7 s.

**El umbral del protocolo sigue sin cumplirse.** El protocolo exige drenar en 30 s y la mediana es
37,873 s. La Change 59 reduce el incumplimiento de 4,7× a 1,26×, pero **no lo elimina**. Esto debe
informarse como incumplimiento con causa identificada y corrección parcial, nunca como cumplimiento.

### Trazas causales, una por repetición

| Repetición | Registros | Primer registro |
|---|---|---|
| run-01 | 65.121 | 2026-09-23T02:01:36 |
| run-02 | 65.754 | 2026-09-23T02:09:25 |
| run-03 | 65.850 | 2026-09-23T02:17:18 |

Las tres tienen hash distinto y cada una comienza dentro de su propia ventana; las tres repeticiones
arrancaron con la base en `events=0`, verificado por el arnés. En el paquete del candidato anterior las
tres trazas eran **el mismo archivo copiado tres veces**; su acta está en
`evidencia/v2-eval-20260922T175053Z/resiliencia/MOTIVO_TRAZAS_INVALIDAS.md`.

---

## 5. Suites sobre el candidato

Artefacto sellado con procedencia `v3.0-tesis`: agente 642/0/1, backend 864 tests con **15 fallas** y 4 omitidos, frontend 260/0/0. Las 15 son acoplamiento de las pruebas entre sí (13, puerto 8443 fijo en `pki.py`) y con el entorno (2, la prueba lee `N8N_WEBHOOK_URL` del proceso), no defectos del producto.

Desglose de las 15, por mensaje, tomado del `backend.xml` del paquete:

- **13** con `RuntimeError: This portal is not running`, en `tests.test_notifications` (7) y
  `tests.test_sse_alerts` (6). `backend/app/core/pki.py` fija el puerto 8443 sin opción de moverlo;
  las pruebas que ejecutan el ciclo de vida real compiten por él, y cuando una falla al enlazar el
  *portal* compartido de anyio queda roto y arrastra a sus hermanas.
- **2** en `tests.core.test_notification_settings`, por una causa distinta: la prueba afirma que una
  opción queda vacía cuando no se define, y la ve definida. La prueba **sí** limpia el entorno del
  proceso —hace `monkeypatch.delenv` sobre las seis claves—, de modo que la fuga no entra por ahí:
  entra por `backend/app/core/config.py`, que declara `env_file=".env"` con **ruta relativa**.
  pydantic-settings la resuelve contra el directorio de trabajo del proceso, y la suite corre desde la
  raíz del repositorio, donde hay un `.env` real que define esas claves. Un arreglo que solo limpiara
  variables de entorno dejaría el defecto intacto.

**Matiz que debe declararse sin adornos**: la misma suite ejecutada contra contenedores efímeros de
Postgres y Valkey reporta 0 fallas. Eso **no** significa que estén corregidas: significa que ese
entorno evita el conflicto. Las cifras de referencia para el capítulo son las del artefacto sellado.

Historia de esta cifra, que conviene conocer porque explica una corrección: hasta el 2026-09-23 el
script `scripts/correr_suites_candidato.sh` tenía **el candidato y el directorio de salida escritos a
mano**, fijados en `7a906c2` y en la carpeta `suites/` del paquete de septiembre. En consecuencia,
toda corrida posterior pisaba aquel paquete y entregaba sus artefactos estampados como `v1.0-tesis`,
fuera cual fuera el candidato evaluado. El script ahora los toma como parámetros.

---

## 6. La corrección medida: Change 59 (D76/RN-170)

**Diagnóstico.** La Change 58 sacó las sesiones bloqueantes del bucle de eventos, pero **no resolvió
la contención: la reubicó**. `backend/app/main.py` construía un único `ThreadPoolExecutor` y lo
instalaba como executor por defecto, de modo que todo `run_in_executor(None, …)` del proceso tiraba del
mismo pool de 10 hilos. Sobre él competían dos carriles con reglas de admisión opuestas: la ingesta
despacha **secuencialmente**, un evento por vez, y la notificación **sin cota**, encolando entre dos y
cinco trabajos por notificación desde `_fire_and_forget` y desde `recover_pending_notifications`, que
dispara todas las pendientes de golpe al arrancar. El `_ingest` del evento siguiente esperaba detrás
del backlog de notificaciones: **la latencia de la ingesta era función de cuánto tarda un mail**.

**Corrección.** Executor dedicado para el carril de notificación, referenciado explícitamente;
semáforo dentro de `notify_event`, que cubre las tres puertas de entrada; presupuesto de conexiones
expresado como **una sola desigualdad sobre la suma** de ambos executors. El carril de ingesta
conserva el executor por defecto en exclusiva y **no cede hilos**: se le quita un competidor.

**Invariantes preservados**: `notification_id` estable en toda la escalera de reintentos
(`_build_payload` se invoca una sola vez, fuera del bucle, y el permiso del semáforo se adquiere antes
de preparar el payload), entrega al-menos-una-vez, cascada de canales, despacho secuencial de la
ingesta.

---

## 7. Lo que queda abierto, declarado y no resuelto

1. **El umbral de drenaje de 30 s no se cumple** (37,873 s de mediana). Causa identificada y corregida
   parcialmente; la corrección completa —stream y proceso consumidor separados para notificación— está
   documentada como dirección y fuera del alcance de la Change 59.
2. **La contabilidad causal de operaciones no encoladas no cierra.** El generador emite 3.000
   operaciones y el agente marca 420 colapsos por repetición, pero 420 + 2.674 = 3.094 > 3.000: el
   marcador de colapso **no particiona** el universo de operaciones. No se infiere explicación.
   Cerrarlo requiere instrumentación adicional en el agente.
3. **El inicio de la Batería 3 no está instrumentado con `strace`**, de modo que la latencia informada
   es una cota inferior.
4. **Batería 6 (mapeo de memoria) no se ejecutó** sobre este candidato. El protocolo la declara
   opcional.
5. **El valor de la cota de notificación (32) no está justificado empíricamente**: se eligió por
   diseño, no por barrido.

---

## 8. Custodia y verificación

`SHA256SUMS` verifica 46 de 46 archivos. Las trazas causales se almacenan comprimidas con gzip y el
sello certifica el contenido **sin** comprimir: descomprimir con `gunzip -k` antes de `sha256sum -c`.
El procedimiento está en `CUSTODIA_TRAZAS.md` dentro del paquete.

**Sobre el nombre del manifiesto**: el pedido especifica `MANIFEST.sha256` y este proyecto usa
`SHA256SUMS`, generado con el mismo comando y verificable con `sha256sum -c`. Conviene declarar la
equivalencia en el Anexo F en lugar de renombrar, porque renombrar rompería la verificación de los
paquetes ya sellados.

**Un punto que conviene explicar en el informe, porque suena a contradicción y no lo es**: un paquete
anterior verificó 46 de 46 y aun así contenía tres trazas que no correspondían a sus repeticiones. El
sello prueba que nadie alteró los archivos después de la medición; **no prueba que los archivos sean
los que corresponden**. Integridad no es pertinencia, y ninguna suma de verificación distingue un
archivo legítimo de un archivo legítimo pero ajeno.

## 9. Intentos inválidos preservados

Ninguno se borró; todos conservan su acta.

- `evidencia/invalidos/v3-eval-20260922T233242Z-sin-sumidero/` — midió las tres baterías de
  notificación contra un sumidero SMTP inexistente y reportó 23 latencias negativas.
- `evidencia/oficial-cap5-20260917T223823Z/invalido-imagen-desactualizada/` — imagen construida cuatro
  días antes del candidato declarado.
- `evidencia/final-consolidated-v10-20260912T210821Z-aborted-dirty-worktree/` — abortada al detectarse
  el árbol de trabajo sucio.
