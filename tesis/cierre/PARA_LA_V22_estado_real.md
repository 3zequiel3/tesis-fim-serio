# Para la v22 — qué cambió desde la v21, qué falta en código y qué falta en el informe

Documento de traspaso al equipo de redacción. Acompaña a `Correcciones_v22_informe_vs_codigo.md` y
**corrige su base de partida**: aquel documento se escribió contra el repositorio público en el commit
`361c1e7` del 19/09/2026 y contra la `Tesis_v21`. Desde entonces cambiaron el candidato vigente, el
contenido publicado del repositorio y el estado de varios de sus ítems.

---

## 0. Los dos bloqueantes de entrega ya están resueltos

| Bloqueante | Estado |
|---|---|
| **0.2** Publicar el commit y las etiquetas de candidato | **Resuelto.** `main` está en `63d8463` y el repositorio publica cuatro etiquetas anotadas: `v1.0-tesis`, `v2.0-tesis`, `v3.0-tesis` y `v4.0-tesis`. |
| **0.3** Versionar los paquetes de evidencia faltantes | **Resuelto, con una excepción declarada.** |

Detalle de 0.3, verificado archivo por archivo en la rama publicada:

| Paquete | Archivos versionados |
|---|---|
| `v2-eval-20260922T175053Z/` | 49 |
| `v2-eval-20260923T010103Z/` | 52 |
| `v2-eval-20260923T215624Z/` (nuevo, candidato vigente) | 50 |
| `evidencia/invalidos/` | 142 |
| Laboratorios E2E `us02-us20-us31-*` | 59 |
| Laboratorios E2E `us03-us16-us17-us25-*` | 24 |

**La excepción, corregida**: una versión anterior de este documento afirmaba que **todos** los paquetes
`final-consolidated-*` estaban excluidos. Era impreciso. El `.gitignore` tiene dos líneas:

```
/tesis/cierre/evidencia/final-consolidated-*/
!/tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/
```

La segunda es una excepción explícita, y ese paquete **sí está versionado**, con 133 archivos.
Verificado en `main`:

| Paquete | Archivos versionados |
|---|---|
| `final-consolidated-20260911T214511Z/` | 0 |
| `final-consolidated-fixed-20260911T225314Z/` | 0 |
| `final-consolidated-v10-20260912T210903Z/` | **133** |

En consecuencia, las rutas de F.1, F.3 y la Tabla 37 que citan el paquete `v10` **son correctas y no
hay que tocarlas**. Lo que corresponde es declarar en el Anexo F por qué los otros dos se excluyen
deliberadamente.

Los bloqueantes **0.1** (declaración de originalidad) y **0.4** (comentarios anclados) siguen abiertos
y son del equipo, no del laboratorio.

---

## 1. El candidato vigente ya no es `v3.0-tesis`

**Es `v4.0-tesis`**, commit `1f28c9e`, con el paquete `tesis/cierre/evidencia/v2-eval-20260923T215624Z/`
(50 de 50 archivos verifican). Toda cifra de la v21 que cite `v3.0-tesis` como candidato de referencia
debe revisarse contra estos valores.

| Indicador | `v3.0-tesis` (v21) | **`v4.0-tesis` (vigente)** |
|---|---|---|
| Suites, backend | 864 pruebas, 15 fallas | **887 pruebas, 0 fallas** |
| Suites, agente | 642, 0 fallas | 642, 0 fallas |
| Suites, frontend | 260, 0 fallas | 260, 0 fallas |
| Latencia, media | 48,712 ms | **26,923 ms** |
| Latencia, P99 | 65,038 ms | **46,274 ms** |
| Muestras negativas | 0 | 0 |
| Notificación entregada | 1.000/1.000 ×3 | 1.000/1.000 ×3 |
| Drenaje, mediana | 37,873 s | **35,044 s** |
| Preservación | 100 % de encolados | 100 % de encolados |
| McNemar χ²(1) | 390,5357 | **385,8534** |
| Diferencia pareada | 0,8120 | **0,8100** |
| IC 95 % | [0,7702; 0,8452] | **[0,7671; 0,8440]** |

### Sobre la latencia, una salvedad que hay que escribir

La media bajó de 48,712 a 26,923 ms y **esa diferencia no debe atribuirse al sistema**. La corrida de
`v3.0-tesis` se midió con `systemd-timesyncd`, que informa sincronización mientras convive con errores
de decenas de milisegundos. La corrida de `v4.0-tesis` es **la primera cuyo desvío de reloj se midió**
—anfitrión 907 µs, huésped 971 µs, con chrony— **en lugar de suponerse**. Las cifras anteriores llevan
esa reserva y así conviene declararlo.

### El contraste pareado replicó tres veces

| Corrida | Candidato | χ²(1) | Diferencia | IC 95 % |
|---|---|---|---|---|
| 17/09 | `v1.0-tesis` | 386,5409 | 0,8040 | [0,7618; 0,8377] |
| 23/09 | `v3.0-tesis` | 390,5357 | 0,8120 | [0,7702; 0,8452] |
| 23/09 | `v4.0-tesis` | 385,8534 | 0,8100 | [0,7671; 0,8440] |

Los tres intervalos se solapan ampliamente. **Presentarlo como réplica**, no como tres mediciones
sueltas: es de lo más defendible que tiene el capítulo.

---

## 2. Ítems de laboratorio del documento de correcciones: estado real

| # | Ítem | Estado |
|---|---|---|
| 1 | Drenaje < 30 s | **Abierto.** Mediana 35,044 s. El incumplimiento bajó de 4,7× a 1,17× en tres candidatos, pero **sigue siendo incumplimiento**. |
| 2 | Explicar las operaciones no encoladas (420 + 2.674 > 3.000) | **Abierto.** El marcador de colapso no particiona el universo. Declarado como supuesto abierto, sin inferir explicación. |
| 3 | Clasificar las operaciones sin evento (P-10) | **Resuelto, con un hallazgo — ver §3.** |
| 4 | Medir la notificación como la define la Tabla 4 | **Parcial.** La columna `channel_accepted_at` existe desde `v4.0-tesis` (migración 022), pero **su serie todavía no se midió**. Falta una corrida que la explote. |
| 5 | Instrumentar el inicio de la latencia con `strace` | **Abierto.** La latencia sigue siendo una cota inferior declarada. |
| 6 | Que el arnés escriba siempre `metadata/entorno.txt` | **Abierto.** |
| 7 | Recuento de historias y coberturas sobre el candidato | **Abierto.** |
| 8 | 31/31 historias | **Ya estaba resuelto antes de la v21.** El cierre del backlog (`2d07cb2`, 17/09) es ancestro del candidato vigente. Son 31/31, con 24/31 en conteo estricto: siete se cerraron ajustando el texto del criterio, con la tabla de ajustes declarada, y una sola con código (US-21). Si la tesis dice «8 parciales», está desactualizada. |
| 9 | Defectos de cuarentena y visor de diferencias | **Abierto.** Sólo se sustancia la mitad de cuarentena: hay dos implementaciones divergentes (`agent/decision.py:299` y `agent/commands.py:422`), declarado en `docs/residuales_declarados.md` §9. Del visor de diferencias **no se encontró defecto abierto** en el repositorio; puede ser una referencia obsoleta. |
| 10 | Barrido de `notify_max_concurrent_deliveries` | **Abierto.** El valor 32 sigue elegido por diseño, no por medición. |
| 11 | Batería 8 (mapeo de memoria) | **Abierto.** La corrida vigente es del 01/09, con el agente contenedorizado. |
| 12 | Colisión del puerto 8443 | **Resuelto.** Ver §4. La cifra de 8 fallas ya no corresponde. |
| 13 | Verificar la versión del núcleo en el preflight | **Abierto**, opcional. |

---

## 3. P-10: las operaciones sin evento, resueltas — y un hallazgo que cambia cómo nombrarlas

`scripts/atribuir_operaciones_sin_evento.py` (publicado, sin dependencias externas) cruza el
manifiesto, la traza causal y los eventos persistidos. Sobre `v4.0-tesis`:

| Resultado | Valor |
|---|---|
| Operaciones del manifiesto | 500 |
| Eventos persistidos | 483 |
| Operaciones sin evento | 17 |
| **Atribuidas con causa** | **17 de 17** |
| Causa única | `matches_active_baseline` |

Y dos controles que salen del mismo cruce: **clasificados que no se persistieron = 0** y **persistidos
que no se clasificaron = 0**. No hay pérdida entre la decisión del agente y la base.

### El hallazgo: no son reversiones, y tampoco son una ventana ciega

El revisor planteó con razón que la lectura cambia según el patrón de cada operación, y que si alguna
fuera una modificación *simple* habría que declarar una ventana ciega del sistema. El desglose es:

| Patrón | Cantidad |
|---|---|
| `simple` | 14 |
| `revertido` | 3 |

O sea, **la mayoría no son reversiones**. Pero la explicación no es una ventana ciega del producto,
sino un defecto del arnés de medición, y está probado:

De las 17, ocho son operaciones **`create`**. Las ocho encontraron, en su primera lectura, una línea
base **ya presente y con exactamente el hash que ese `create` iba a escribir**. Eso sólo es posible si
la línea base sobrevivió a un reset que sí borró el archivo.

La causa es `~/fim-lab/vm_reset.sh`: borra el directorio vigilado, la cola, los descartes y la traza,
pero **nunca la línea base del agente**. Como el generador es determinista —semilla fija, mismo
contenido por archivo—, la repetición siguiente reescribe exactamente lo mismo que la anterior, el
agente lee una línea base que coincide y suprime. Correctamente, según su política.

**Cómo conviene redactarlo**, y es más fuerte que cualquiera de las dos lecturas anteriores:

> De las 500 operaciones, 17 no produjeron evento persistido. Las 17 fueron atribuidas por la traza
> causal del agente a supresión por coincidencia con la línea base activa. No se observaron
> operaciones que el agente no haya visto, ni pérdidas entre la clasificación y la persistencia. El
> análisis de esas 17 identificó, además, una limitación del protocolo de medición y no del sistema:
> el procedimiento de reinicio entre repeticiones no purgaba la línea base del agente, de modo que un
> generador determinista reescribía contenidos ya aprobados en corridas previas.

Eso declara un hallazgo propio, explica el número y no exagera la conclusión. **No conviene escribir
«cero falsos negativos» sin esa explicación**: el valor literal del indicador, tal como la Tabla 4 lo
define, es 17 y no 0.

**Lo que falta en código para cerrarlo del todo**: purgar la línea base del agente en el reinicio entre
repeticiones y repetir la batería. Recién entonces el conteo distinguirá supresiones legítimas de
artefactos de arrastre.

**Sobre el precedente del 17/09 («19 de 19»)**: el revisor advierte que viene de un paquete con un
intento invalidado por imagen desactualizada. La advertencia es correcta y conviene no apoyarse en él.

---

## 4. Suites: la cifra de la v21 quedó obsoleta dos veces

La v21 informa «860 aprobadas, 4 omitidas, ninguna fallida». Esa cifra **nunca tuvo artefacto sellado
detrás**: provenía de una ejecución manual contra contenedores efímeros.

Hay además un defecto de arnés que explica el desorden: `scripts/correr_suites_candidato.sh` tenía **el
candidato y el directorio de salida escritos a mano**, fijados en `7a906c2` y en la carpeta `suites/`
del paquete de septiembre. En consecuencia, toda corrida posterior pisaba aquel paquete y entregaba
sus artefactos estampados como `v1.0-tesis`, fuera cual fuera el candidato evaluado. El script ahora
los toma como parámetros.

**Consecuencia para el Anexo F, que conviene declarar**: la carpeta `suites/` del paquete
`oficial-cap5-20260917T223823Z/` fue sobrescrita por corridas posteriores y ya no corresponde
necesariamente a `7a906c2`. Es el mismo principio que el capítulo ya usa en otro lado: **un sello
prueba integridad, no pertinencia**.

Cifras reales, del artefacto sellado de cada candidato:

| Candidato | Agente | Backend | Frontend |
|---|---|---|---|
| `v3.0-tesis` | 642 / 0 fallas / 1 omitida | 864 / **15 fallas** / 4 omitidas | 260 / 0 / 0 |
| **`v4.0-tesis`** | 642 / 0 / 1 | **887 / 0 fallas / 4 omitidas** | 260 / 0 / 0 |

Las 15 fallas de `v3.0-tesis` tenían **dos causas distintas**, no una:

- **13** con `RuntimeError: This portal is not running`. `backend/app/core/pki.py` fija el puerto 8443
  sin opción de moverlo; las pruebas que ejecutan el ciclo de vida real compiten por él y, cuando una
  falla al enlazar, el *portal* compartido de anyio queda roto y arrastra a sus hermanas. Afectaba a
  `tests.test_notifications` (7) y `tests.test_sse_alerts` (6).
- **2** en `tests.core.test_notification_settings`, por una causa distinta: `backend/app/core/config.py`
  declara `env_file=".env"` con **ruta relativa**, que pydantic-settings resuelve contra el directorio
  de trabajo. La prueba sí limpia las variables de entorno; la fuga entraba por el archivo.

**La observación del revisor sobre «no defectos del producto» es correcta y conviene incorporarla.**
El puerto fijo es rigidez de configuración, y una ruta relativa al directorio de trabajo puede hacer
que en producción se cargue una configuración equivocada según desde dónde se arranque el proceso.
Ambas se corrigieron en la Change 60 (D77/RN-171, D78/RN-172), verificadas con el `.env` presente y
los puertos 8443 y 8444 ocupados: **887 aprobadas, 0 fallidas**.

La cifra de «8 fallas preexistentes» que circuló antes **no debe usarse**. Provenía de otro entorno.

---

## 5. Lo que falta en código, ordenado por lo que mueve la nota

| Prioridad | Qué | Costo |
|---|---|---|
| 1 | **Drenaje < 30 s.** Separar el stream y el proceso consumidor de la notificación. Antes de encararlo conviene perfilar: de los ~14 ms por evento sólo ~2,9 ms son trabajo de base medido, y los ~11 ms restantes no están atribuidos. La dirección documentada exige además revisar RN-76 (backend de instancia única). | Días |
| 2 | **Purgar la línea base del agente entre repeticiones** y repetir la Batería 3. Cierra del todo el §3 de este documento. | Horas |
| 3 | **Medir la serie de `channel_accepted_at`.** La columna existe; falta la corrida que la explote. Es el indicador que la Tabla 4 realmente define. | Horas |
| 4 | **Instrumentar el marcador de colapso** para que particione el universo de operaciones. | Horas a un día |
| 5 | **`metadata/entorno.txt` en cada paquete** (SO, núcleo, red, VM o no). Cierra P-03 para siempre. | Horas |
| 6 | **Recuento de historias sobre el candidato vigente.** No hay script: ninguna prueba cita una historia, así que es una pasada manual. La matriz está desactualizada de forma comprobada (US-23 cita `service.py:144-177`, hoy esas funciones están en `:255-288`). | Horas |
| 7 | **Unificar las dos implementaciones de cuarentena**, con pruebas compartidas. | Horas a un día |
| 8 | **Instrumentar el inicio de la latencia con `strace`.** Convierte la cota inferior en intervalo. Ojo con el sesgo: el propio `strace` altera lo que mide. | Un día o dos |
| 9 | **Barrido de `notify_max_concurrent_deliveries`.** | Horas |
| 10 | **Batería 8 sobre el candidato vigente.** Opcional según el protocolo. | Medio día |

Cualquiera de estos cambios que toque código **invalida `v4.0-tesis`** y obliga a re-etiquetar y
repetir la corrida unificada (~1,5 h, automatizada).

---

## 6. Lo que falta en el informe

Además de todo lo que el documento de correcciones ya enumera y sigue vigente (A1 completo, A2, D1,
D2, Anexo I), hay que **agregar o corregir**:

1. **Reemplazar el candidato de referencia** de `v3.0-tesis` por `v4.0-tesis` en §5.11 y en todas las
   tablas de resultados, con las cifras de §1 de este documento.
2. **Retirar las frases que declaran el repositorio sin etiquetas y los paquetes sin versionar.** Están
   en el Anexo F intro, en el párrafo «Candidato v3.0-tesis» de F.1 y en el primer párrafo de §5.11.1.
   Ya no son ciertas.
3. **Declarar la excepción de `final-consolidated-*`** en el Anexo F, o revertir `.gitignore:71`.
4. **Reescribir el apartado de falsos negativos** con la formulación de §3, incluido el hallazgo sobre
   la línea base no purgada.
5. **Corregir las suites** en §5.11.6 y su tabla, con el desglose de las dos causas de §4, y describir
   las fallas como acoplamiento de configuración y no como ausencia de defectos del producto.
6. **Declarar en el Anexo F que la carpeta `suites/` del paquete del 17/09 fue sobrescrita** y ya no
   corresponde necesariamente a su candidato. Es la segunda instancia del principio «un sello prueba
   integridad, no pertinencia», y el capítulo gana declarándola.
7. **Agregar al Anexo F** el script de atribución, el CSV `atribucion_sin_evento.csv` y los dos
   intentos inválidos nuevos, con su acta:
   - `invalidos/v4-eval-20260923T190201Z-esquema-desactualizado/`
   - `invalidos/v4-eval-20260923T202713Z-reloj-corrido/`
8. **Corregir el apartado de historias**: son 31/31 desde el 17/09, no 8 parciales. Distinguir las
   siete cerradas por ajuste declarado de criterio de la única cerrada por código (US-21).
9. **Sumar a las amenazas a la validez** los defectos de instrumentación de §7. Bien escrito, es de lo
   que más suma.

---

## 7. Amenazas a la validez: ocho defectos de instrumentación propios

Durante esta campaña se detectaron y corrigieron **ocho defectos del arnés de medición**, todos de la
misma familia: estado que se acumula entre corridas, o un recurso que se da por presente sin
verificarlo.

| # | Defecto | Efecto sobre el dato |
|---|---|---|
| 1 | Las trazas causales no se truncaban entre repeticiones | Las tres «trazas por repetición» eran un mismo archivo copiado tres veces |
| 2 | El CSV del grupo de control era acumulativo desde el 17/09 | Un paquete entregaba 418 filas de seis días como si fueran de una corrida |
| 3 | Mailpit nunca estuvo definido como servicio | Una corrida midió las tres baterías de notificación contra un sumidero inexistente |
| 4 | `/tmp` del huésped no sobrevive a un reinicio | Un reinicio silencioso dejaba los reinicios de laboratorio sin ejecutar, indistinguibles de los exitosos |
| 5 | El candidato de las suites estaba escrito a mano | Los artefactos de suites correspondían a otro candidato |
| 6 | El arnés no aplicaba las migraciones | Ningún evento creó alerta; **el drenaje pareció cumplir el umbral** |
| 7 | La guarda de reloj preguntaba si había sincronización NTP | 347 latencias negativas sobre 484, con ambas máquinas declarándose sincronizadas |
| 8 | El reinicio no purgaba la línea base del agente | Operaciones legítimas suprimidas por coincidir con contenidos de corridas previas |

**El sexto merece un párrafo propio en el capítulo.** Los otros siete degradaban o falseaban un dato, y
por eso alguien terminaba preguntando por qué había salido mal. El sexto lo **mejoraba**: con cero
alertas creadas, el carril de notificación no competía por recursos y el drenaje marcó 29,4 a 30,2 s,
es decir, **parecía cruzar por primera vez el umbral de 30 s que el protocolo exige**. Lo que lo delató
no fue el número sino la ausencia de mecanismo: la change de ese candidato agregaba una columna y
arreglaba pruebas, y eso no puede acelerar un drenaje un 22 %.

Un defecto que empeora un resultado se descubre solo. Uno que lo mejora se publica.

El arnés verifica hoy, antes de medir: que el esquema de la base coincida con el modelo, que el
sumidero de notificación responda, y que el desvío de reloj de ambas máquinas esté bajo un techo
explícito. Los tres abortan la corrida en lugar de continuar.
