# Verificación de cifras contra los paquetes sellados

Responde al pedido del equipo de redacción: *«comparar las cifras de las Tablas 25 a 31 contra los
paquetes sellados. Yo no abrí ningún paquete; trabajé solo con los insumos, que escribió otra IA, y ya
tuvieron errores».*

El pedido es correcto y era necesario. Esta verificación se hizo contra los **artefactos crudos**
—CSV, JSON y XML— y no contra la prosa de los documentos de resultados, porque una cifra citada en
prosa que contradice al artefacto está mal, diga lo que diga la prosa.

---

## 1. Lo que coincide

**Tablas 25 a 30: todas las cifras verificadas coinciden con el artefacto crudo del paquete
`v2-eval-20260923T010103Z` (candidato `v3.0-tesis`, commit `22f393d`), que es el que las tablas citan.**

| Tabla | Qué se verificó | Contra qué |
|---|---|---|
| 25 | n=484, media 48,712 ms, P50 48,916, P95 61,119, P99 65,038, mín 30,993, máx 80,023, negativas 0 | `latencia/resumen.txt` |
| 26 | Tabla pareada 71 / 413 / 7 / 9, totales 484/16/78/422/500 | **Recomputada desde `control/pareado.csv`**, 500 filas |
| 27 | χ²=390,5357; p=6,33×10⁻⁸⁷; diferencia 0,8120; IC [0,7702; 0,8452] | **Re-ejecutado `scripts/analisis_mcnemar.py`** sobre los conteos crudos |
| 28 | Tres escenarios, 1.000 de 1.000 cada uno, con sus percentiles | `notificacion/resumen.txt` y las tres CSV, contadas fila por fila |
| 29 | 2.674/37,873 s · 2.670/37,213 s · 2.674/37,957 s; mediana 37,873 s | `resiliencia/run-0N/counts.json` |
| 30 | Síntesis; y «entre 326 y 330 sin encolar» (3.000−2.674=326, 3.000−2.670=330) | Aritmética contra la Tabla 29 |

Dos verificaciones merecen destacarse porque no son una lectura sino un recálculo: **la tabla pareada
se reconstruyó desde las 500 filas de `pareado.csv`** y **el McNemar se volvió a ejecutar** con el
script publicado, reproduciendo el estadístico hasta la precisión informada.

La fila de preservación de la Tabla 30 ya está enunciada de la forma correcta —usando *generados*
como denominador vinculante y *encolados* sólo como medida complementaria—, así que no requiere
cambio.

---

## 2. La única discrepancia: la Tabla 31

**Tabla 31, fila del objetivo 8.** Dice «860 aprobadas, 4 omitidas y 0 fallidas» para `v3.0-tesis`.

Esa cifra **no tiene artefacto sellado detrás**. Provino de una ejecución manual contra contenedores
efímeros, donde el conflicto de puerto no se daba. El propio paquete la retracta en su
`RESULTADOS.md`.

Cifras correctas, leídas de los JUnit del paquete:

| Suite | Tests | Fallas | Omitidos |
|---|---|---|---|
| agente | 642 | 0 | 1 |
| backend | **864** | **15** | 4 |
| frontend | 260 | 0 | 0 |

**Redacción sugerida**: «642/0/1 (agente), 864/15/4 (backend), 260/0/0 (frontend). Las 15 fallas se
atribuyen a acoplamiento de configuración —el puerto 8443 fijo en `pki.py` y el archivo de entorno
resuelto contra el directorio de trabajo— y quedaron corregidas por la Change 60.»

Conviene **no** escribir «no son defectos del producto». Las dos causas son rigidez de configuración
del producto, no sólo de las pruebas: un puerto que no se puede mover y una ruta relativa que hace
depender la configuración cargada del directorio desde el que se arranca el proceso.

Si la versión que se está redactando ya retiró esa cifra, este punto está cubierto.

---

## 3. Hallazgo nuevo: un paquete cita el candidato equivocado y subcuenta sus fallas

El paquete `v2-eval-20260922T175053Z/`, que el capítulo trata como del candidato `v2.0-tesis`, tiene
en `suites/procedencia.txt`:

```
candidate_commit=7a906c202e417aec5f03d9a7545e216a724aca81
candidate_tag=v1.0-tesis
```

Es decir, **sus artefactos de suites pertenecen a `v1.0-tesis`**, no a `v2.0-tesis`. La causa ya está
identificada y corregida: `scripts/correr_suites_candidato.sh` tenía el candidato y el directorio de
salida escritos a mano.

Y hay un segundo problema dentro del mismo paquete. Su `backend.xml` registra **10 fallas**, pero su
relato explica **8**. Las dos que faltan son:

```
tests.core.test_notification_settings::test_notification_settings_default_to_empty
tests.core.test_notification_settings::test_health_url_is_not_derived_from_webhook
```

Esas dos son exactamente el defecto del archivo de entorno con ruta relativa, que recién se
diagnosticó el 23/09. **Estaba presente desde `v1.0-tesis` y nunca se contó.**

Consecuencia para el informe: **la cifra de «8 fallas preexistentes» que circuló en varias versiones
es incorrecta; eran 10.** Debe usarse la cifra del artefacto sellado y explicarse la diferencia, que
es justamente el caso que el Anexo F ya discute: un sello garantiza integridad, no pertinencia.

---

## 4. Qué falta, y de quién es cada cosa

### Sólo el equipo puede hacerlo

| Qué | Por qué no puede hacerlo otro |
|---|---|
| Declaración de originalidad, párrafo 2; §9.1.2; introducción del Anexo I | Es una declaración de honestidad académica sobre el propio trabajo. Que la redacte una IA contradice lo que la declaración afirma. |
| Aceptar cambios en Word y regenerar los índices | Los números de página son texto fijo y hay que rehacerlos en el procesador. |

### Ya resuelto en el repositorio

Contra lo que decía el pedido, **`DATOS_PARA_DECISIONES_V22.md` sí existe**, junto con
`PARA_LA_V22_estado_real.md`, `RESPUESTAS_PENDIENTES_V22.md` y `RESPUESTAS_ULTIMAS_MARCAS_V22.md`,
todos en `tesis/cierre/`. No se veían porque el repositorio no estaba publicado; ahora lo está, con
`main` al día y las cuatro etiquetas de candidato (`v1.0-tesis` a `v4.0-tesis`) subidas.

### Pendiente de código o laboratorio

| # | Qué | Estado |
|---|---|---|
| 1 | **Drenaje bajo 30 s.** Mediana actual 35,044 s en `v4.0-tesis` | Abierto. Exige separar el stream y el proceso consumidor de la notificación, lo que a su vez obliga a revisar la regla de instancia única |
| 2 | **Que el marcador de colapso particione el universo de operaciones** (hoy 420 + 2.672 = 3.092 > 3.000) | Abierto. Sube de prioridad porque la preservación preregistrada exige encolados = generados |
| 3 | Clasificar las operaciones sin evento | **Cerrado.** `scripts/atribuir_operaciones_sin_evento.py`, 17 de 17 atribuidas |
| 4 | Medir la notificación como la define la Tabla 4 | **Parcial.** La columna `channel_accepted_at` existe desde `v4.0-tesis`; su serie todavía no se midió |
| 5 | Instrumentar el inicio de la latencia con `strace` | Abierto |
| 6 | Que el arnés escriba siempre el entorno de cada anfitrión en el paquete | Abierto |
| 7 | Recuento de historias y coberturas sobre el candidato vigente | Abierto |
| 8 | 31/31 historias | **Cerrado antes de esta serie** |
| 12 | Colisión del puerto 8443 | **Cerrado** por la Change 60 |

---

## 5. El candidato vigente ya no es `v3.0-tesis`

Las Tablas 25 a 31 describen `v3.0-tesis`. El candidato actual es **`v4.0-tesis`** (`1f28c9e`), con su
propio paquete sellado en `tesis/cierre/evidencia/v2-eval-20260923T215624Z/`, 50 de 50 archivos
verificados.

Diferencias que importan para el capítulo:

| Indicador | `v3.0-tesis` | `v4.0-tesis` |
|---|---|---|
| Suites del backend | 864 tests, 15 fallas | **887 tests, 0 fallas** |
| Latencia media | 48,712 ms | 26,923 ms |
| Operaciones sin evento | 16, sin clasificar | 17, **17 de 17 atribuidas** |
| Drenaje, mediana | 37,873 s | **35,044 s** |
| McNemar χ² | 390,5357 | 385,8534 |

**Sobre la latencia, una reserva que hay que declarar y no atribuir al sistema**: `v4.0-tesis` es la
primera corrida cuyo desvío de reloj se **midió** en ambas máquinas (907 µs y 971 µs) en lugar de
suponerse. Las corridas anteriores usaban `systemd-timesyncd`, que informa «sincronizado» conviviendo
con errores de decenas de milisegundos. La diferencia entre 48,7 y 26,9 ms **no debe presentarse como
una mejora del sistema**.

El McNemar, en cambio, **replica en tres corridas independientes sobre tres candidatos distintos**:
386,5409 · 390,5357 · 385,8534, con diferencias 0,8040 · 0,8120 · 0,8100 e intervalos ampliamente
solapados. Eso es reproducibilidad demostrada y conviene presentarlo así.
