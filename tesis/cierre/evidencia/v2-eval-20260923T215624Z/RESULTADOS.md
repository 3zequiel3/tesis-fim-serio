# Evaluación unificada — candidato `v4.0-tesis`

Corrida del 2026-09-23, 21:56 a 23:20 UTC. Commit `1f28c9e`. Procedencia del binario verificada por
hash del árbol del contenedor contra el árbol de trabajo: coinciden.

Es la primera corrida del proyecto que pasa las tres guardas de integridad del arnés antes de medir:

| Guarda | Resultado |
|---|---|
| Esquema de la base contra el modelo | toda columna del modelo existe en la base |
| Sumidero de notificación | mailpit resuelve y su API responde |
| Desvío de reloj | anfitrión 907 µs, huésped 971 µs (techo 5.000 µs) |

Sobre `git_status_clean=no`: el árbol figura sucio porque el propio directorio de salida de la corrida
vive dentro del repositorio. Ningún archivo de código está modificado; lo que verifica la identidad
del candidato es `provenance_match=yes`.

---

## 1. Suites sobre el candidato

| Suite | Tests | Fallas | Omitidos |
|---|---|---|---|
| agente | 642 | 0 | 1 |
| backend | **887** | **0** | 4 |
| frontend | 260 | 0 | 0 |

Las 15 fallas del candidato anterior —13 por el puerto 8443 fijo y 2 por el `.env` resuelto contra el
directorio de trabajo— quedaron cerradas por la Change 60, y **estas cifras salen del artefacto
sellado del candidato correcto**, no de una ejecución manual.

## 2. Latencia de detección (Batería 3)

| Métrica | Valor |
|---|---|
| n | 483 |
| Media | 26,923 ms |
| P50 | 26,536 ms |
| P95 | 35,391 ms |
| P99 | 46,274 ms |
| Mínimo | 11,177 ms |
| Máximo | 102,144 ms |
| Muestras negativas | **0** |

Contra el umbral de 1.000 ms se cumple con más de un orden de magnitud de margen.

**Comparabilidad entre candidatos, declarada**: `v3.0-tesis` informó 48,712 ms de media. La diferencia
no debe atribuirse al sistema. Aquella corrida se midió con `systemd-timesyncd`, que informa
sincronización mientras convive con errores de decenas de milisegundos; **ésta es la primera con el
desvío de ambos relojes medido y acotado bajo el milisegundo**. La cifra de esta corrida es la que
tiene respaldo metodológico; las anteriores deben leerse con esa reserva.

La limitación de fondo sigue abierta: el intervalo parte del estampado del agente, no del fin de la
llamada al sistema, de modo que es una **cota inferior declarada**.

### Falsos negativos: 17 de 17 atribuidos

| Resultado | Valor |
|---|---|
| Operaciones del manifiesto | 500 |
| Eventos persistidos | 483 |
| Operaciones sin evento | 17 |
| **Atribuidas con causa** | **17 de 17** |
| Causa única | `matches_active_baseline` |

Además, del propio cruce: **clasificados que no se persistieron = 0** y **persistidos que no se
clasificaron = 0**. No hay pérdida entre la decisión del agente y la base.

Ninguna de las 17 es un falso negativo: el sistema las vio y decidió, correctamente, no reportarlas.
Reproducible con `scripts/atribuir_operaciones_sin_evento.py`; detalle en
`latencia/atribucion_sin_evento.csv`.

## 3. Grupo de control e inferencia pareada (Batería 7)

| Métrica del control | Valor |
|---|---|
| n | 78 |
| Mediana | 591.120,468 ms |
| Mínimo / Máximo | 2.493,293 / 898.964,208 ms |
| Cambios nunca reportados | **422 de 500 (84,4 %)** |

### Tabla pareada

|  | control sí | control no | total |
|---|---|---|---|
| **FIM sí** | 69 | 414 | 483 |
| **FIM no** | 9 | 8 | 17 |
| **total** | 78 | 422 | 500 |

| Estadístico | Valor |
|---|---|
| Proporción detectada, FIM | 0,9660 |
| Proporción detectada, control | 0,1560 |
| **Diferencia pareada** | **0,8100** |
| **IC 95 % de Newcombe (pareado)** | **[0,7671; 0,8440]** |
| **McNemar con corrección, χ²(1)** | **385,8534** |
| **valor p** | **6,61612 × 10⁻⁸⁶** |
| Factor de mejora (mediana) | 22.276,2× |

**Réplica en tres corridas independientes**, sobre tres candidatos distintos:

| Corrida | χ²(1) | Diferencia | IC 95 % |
|---|---|---|---|
| 17/09, `v1.0-tesis` | 386,5409 | 0,8040 | [0,7618; 0,8377] |
| 23/09, `v3.0-tesis` | 390,5357 | 0,8120 | [0,7702; 0,8452] |
| 23/09, `v4.0-tesis` | **385,8534** | **0,8100** | **[0,7671; 0,8440]** |

Los tres intervalos se solapan ampliamente. Eso es evidencia de reproducibilidad y conviene
presentarlo como tal, no como tres mediciones sueltas.

## 4. Notificación, tres escenarios

| Escenario | n | Entregadas | Media | P50 | P95 | P99 | Máx |
|---|---|---|---|---|---|---|---|
| secuencial | 1000 | **1000** | 13.256,856 | 14.043,574 | 21.687,104 | 22.135,756 | 22.211,400 |
| concurrencia 50 | 1000 | **1000** | 12.090,537 | 12.939,007 | 20.520,838 | 20.979,580 | 21.006,211 |
| concurrencia 100 | 1000 | **1000** | 9.832,914 | 10.406,837 | 17.104,211 | 17.493,441 | 17.534,554 |

3.000 de 3.000 entregadas. Canal primario n8n, destino SMTP final Mailpit.

**Este indicador no es el que la Tabla 4 define.** La Tabla 4 pide el intervalo hasta la **emisión
exitosa del webhook**; lo medido es hasta `alerts.delivered_at`, que incluye la espera por un cupo de
entrega. La Change 60 agrega la columna `channel_accepted_at`, que registra el instante correcto, pero
**esta corrida todavía no lo explota**: la marca existe desde este candidato y su serie se medirá por
separado.

## 5. Resiliencia ante un corte del broker (Batería 5)

| Repetición | Encolados | Entregados | Descartados | Duplicados | Drenaje |
|---|---|---|---|---|---|
| run-01 | 2.672 | 2.672 | 0 | 0 | **34,050 s** |
| run-02 | 2.671 | 2.671 | 0 | 0 | **35,044 s** |
| run-03 | 2.672 | 2.672 | 0 | 0 | **35,257 s** |

**Preservación 100 % de los encolados** en las tres. Cero rechazos. Las tres arrancaron con la base en
`events=0`, verificado por el arnés, y cada una produjo su propia traza causal con hash distinto
(65.038 / 65.465 / 63.886 registros).

### Evolución del drenaje

| Candidato | Mediana | Tasa |
|---|---|---|
| `v2.0-tesis` | 141,061 s | ≈ 18,9 ev/s |
| `v3.0-tesis` | 37,873 s | ≈ 70,6 ev/s |
| `v4.0-tesis` | **35,044 s** | **≈ 76,2 ev/s** |

**El umbral del protocolo sigue sin cumplirse.** El protocolo exige 30 s y la mediana es 35,044 s. El
incumplimiento bajó de 4,7× a 1,17×, pero sigue siendo incumplimiento y así debe informarse.

Un intento anterior de este mismo candidato midió 29,4 a 30,2 s y **parecía cumplir**. No cumplía:
medía con cero alertas creadas por un esquema desactualizado, es decir, con el carril de notificación
inexistente. Su acta está en `../invalidos/v4-eval-20260923T190201Z-esquema-desactualizado/`.

## 6. Supuesto abierto, declarado y no resuelto

La contabilidad causal de las operaciones que no llegaron a encolarse en la Batería 5 **no cierra**:
3.000 operaciones emitidas, 420 marcas de colapso por repetición, y 420 + 2.672 = 3.092 > 3.000. El
marcador de colapso no particiona el universo de operaciones. No se infiere explicación; cerrarlo
requiere instrumentación adicional en el agente.

## 7. Custodia

`SHA256SUMS` cubre los archivos tal como están almacenados, con las trazas ya comprimidas: verificar
con `sha256sum -c SHA256SUMS`, sin pasos previos. Las tres trazas tienen hash distinto y cada una
comienza dentro de la ventana de su repetición.

## 8. Intentos inválidos preservados, con su acta

- `../invalidos/v4-eval-20260923T190201Z-esquema-desactualizado/` — midió con la migración 022 sin
  aplicar: 0 alertas creadas, y un drenaje que parecía cumplir el umbral por eso mismo.
- `../invalidos/v4-eval-20260923T202713Z-reloj-corrido/` — 347 latencias negativas sobre 484 por un
  reloj del huésped corrido, con ambas máquinas declarándose sincronizadas.
