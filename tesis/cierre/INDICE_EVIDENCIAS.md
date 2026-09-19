# Índice de evidencias de cierre

> **Corte:** 2026-09-19. La sección «Cierre del Capítulo 5» reúne el trabajo del 17 al 19 de
> septiembre; lo anterior conserva el corte del 2026-09-10 y su redacción original. Este índice conduce primero a los resultados que
> sostienen el cierre. El inventario con hashes SHA-256 y las precauciones de
> publicación está en [`evidencia/INDICE.md`](evidencia/INDICE.md).

## Evidencia principal

| Tema | Resultado verificable | Código / evidencia |
|---|---|---|
| US-09 | Diff textual real, acotado y validado desde snapshot limpio | `8039624` + `f08626a`; pruebas citadas en [`MATRIZ_TRAZABILIDAD.md`](MATRIZ_TRAZABILIDAD.md) |
| mTLS agente/backend | Handshake TLS 1.3 válido y rechazos sin certificado, CA no confiable y certificado vencido | `28f87fe`; `backend/tests/test_mtls_transport.py` |
| n8n durable | Cuatro fallos n8n → webhook controlado; fallo total persistido; recuperación con el mismo `notification_id` | `f0a2907`, `e2519eb`, `3bec584`; `n8n/e2e/evidence/` |
| Coverage backend | 570 PASS, 2 omitidas; 2484/2780 statements = 89,35 % | [`evidencia/20260909-coverage-run3/`](evidencia/20260909-coverage-run3/) |
| Corrida causal | 60 operaciones = 50 eventos completos + 10 retornos a baseline descartados legítimamente; 0 ausencias nuevas inexplicadas | `aae55e4`, evidencia `f69e450`; [`RESULTADO.md`](evidencia/absence-20260910T052521Z-r2/RESULTADO.md) |
| D49–D51 | Atribución no resuelta como `null`; `FAN_Q_OVERFLOW` observable; `event_type` y path nulo integrados | `b70934d` + `b8e9513` |
| Baseline aprobada | Candidato local cifrado ligado a `source_event_id`; validación exacta antes de promoción | `8d37075` |
| Backend de ingesta | 8→5 sentencias SQL/evento; 32 pruebas dirigidas PASS | `965dcac`; `backend/tests/test_drain_backend_unit1.py` |
| Drenaje Run 4 | 3.000/3.000 en **29,146335596 s** = **102,928891 eventos/s**; 0 rechazos/duplicados; cadena completa y cola final 0 | evidencia `864b672`; [`RESULTADO.md`](evidencia/drenaje-20260910-run4-unit1/RESULTADO.md) |
| Cuarentena cifrada | AES-256-GCM streaming, HKDF `quarantine-v1`, metadata cifrada, nombres opacos y eliminación durable/idempotente | `b060e5f`; 76/76 dirigidas PASS |
| Retención de cuarentena | Default 30 días configurable 1..365; cleanup inicio/24 h; migración legacy atómica/idempotente | `947edb6`; 50/50 dirigidas PASS |

## Resultados que deben preservarse por separado

- B3/B5 históricos mantienen 19 operaciones sin cadena causal contemporánea.
  La corrida causal nueva no reconstruye esos casos.
- Run 3 conserva 3.000/3.000 en 51,773 s y **NO CUMPLE** `<30 s`.
- Run 4 **CUMPLE** `<30 s` únicamente bajo su laboratorio documentado. No
  establece SLA, validación multianfitrión ni aptitud productiva.
- `32,358 s` fue una proyección previa, no una medición.
- Los dos intentos inválidos de Run 4 permanecen bajo
  [`invalid-runs/`](evidencia/drenaje-20260910-run4-unit1/invalid-runs/) y no
  forman parte del resultado.

## Límites abiertos

| Límite | Estado |
|---|---|
| Cuarentena | Implementada y verificada con límites: no protege root/host vivo/adquisición con secreto; corruptos/desconocidos se preservan; legacy perdió el directorio original y usa `ctime` aproximado cuando no hay timestamp. |
| Dos anfitriones con red real y TLS | No ejecutado. |
| SMTP controlado | No acreditado; el fallback ejecutado fue webhook. |
| Suite final única | Falta agente/backend/frontend sobre un mismo commit congelado. |
| 19 ausencias históricas | Explicación compatible, causalidad runtime retrospectiva no demostrable. |

## Ruta de revisión

1. Leer [`INFORME_CIERRE_TECNICO.md`](INFORME_CIERRE_TECNICO.md).
2. Contrastar indicadores en [`RESULTADOS_VERIFICADOS.md`](RESULTADOS_VERIFICADOS.md).
3. Revisar las 31 historias en [`MATRIZ_TRAZABILIDAD.md`](MATRIZ_TRAZABILIDAD.md).
4. Aplicar las correcciones de redacción de [`CAMBIOS_PARA_TESIS.md`](CAMBIOS_PARA_TESIS.md).
5. Repetir ensayos con [`REPRODUCIR.md`](REPRODUCIR.md).
6. Validar hashes en [`evidencia/INDICE.md`](evidencia/INDICE.md).

## Playwright US-03 / US-25 — 2026-09-10

| Evidencia | Evaluación | Estado | Límite |
|---|---|---|---|
| `docs/cierre/evidencia/us03-us25-playwright-20260910T205424Z/RESULTADO.md` | Refresh/revocación y bulk parcial con usuario/rate-limit aislados | **PASS funcional** | Contratos y tramos live exclusivos continúan BLOCKED. |
| `docs/cierre/evidencia/us03-us25-playwright-20260910T205424Z/combined-final-run1/` | Primera corrida conjunta final | **2/2 PASS** | No acredita multi-key live ni comando/ACK. |
| `docs/cierre/evidencia/us03-us25-playwright-20260910T205424Z/combined-final-run2/` | Segunda corrida consecutiva | **2/2 PASS** | Prueba que el bucket de una corrida no agota la siguiente. |
| `docs/cierre/evidencia/us03-us25-playwright-20260910T203527Z/` y `us03-us25-playwright-20260910T204339Z/` | Descubrimiento/corrección previa | **HISTÓRICO** | No representan el estado final. |

## Laboratorio aislado US-03 / US-16 / US-17 / US-25

| Evidencia | Qué acredita | Resultado | Límite |
|---|---|---|---|
| `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260910T235332Z/RESULTADO.md` | Rotación JWT live, edición/eliminación con agente real y bulk approve con ACK/efecto | **PASS ejecutado** | Cookie US-03 y wire US-25 siguen BLOCKED contractuales. |
| `.../playwright-us16-us17.log` + `.../playwright-us25.log` | Casos individuales | **1/1 + 1/1 PASS** | Sin mocks de red. |
| `.../playwright-combined.log` | Orden conjunto semánticamente válido | **2/2 PASS** | Un worker, archivos propios por historia. |
| `.../teardown-result.json` | Eliminación de recursos y no alteración del stack principal | **0/0/0; true/true** | Verificable por SHA-256. |

## Playwright US-02 / US-20 / US-31

| Evidencia | Resultado |
|---|---|
| `evidencia/us02-us20-us31-playwright-20260910T212203Z/` | US-02 FAIL; US-20 1 PASS + reconexión INCONCLUSA/BLOCKED por método; US-31 1 PASS/1 FAIL; conjunto aprobado 2/2 PASS; build PASS |
| `evidencia/us02-us20-us31-fixed-20260910T233934Z/` | Corrección posterior: individuales US-02 1/1, US-20 2/2 y US-31 2/2; conjunto 5/5 PASS; evidencia textual sanitizada y medios/traces retirados sin reejecución; build, integridad y teardown PASS |
| `evidencia/us02-us20-us31-fixed-us20isolated20260911T0220Z/` | Evidencia vigente: snapshot congelado; US-20 individual 2/2 dos veces y conjunto US-02/20/31 5/5 dos veces; corte físico sólo de SSE con API/refresh 200; integridad, sanitización y teardown PASS |

El primer paquete se conserva como resultado histórico de descubrimiento. El segundo es la evidencia vigente de estas tres historias; no se suman como una única suite.

## Cierre canónico US-03 / US-16 / US-17 / US-25 — 2026-09-11

| Evidencia | Alcance | Estado |
|---|---|---|
| `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260911T015529Z/RESULTADO.md` | Cookie/ruta/revocación y multi-key US-03; labels RuleForm; wire y agente/ACK/efecto US-25 | **PASS ejecutado** |
| `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260911T015529Z/SHA256SUMS` | Integridad del paquete sanitizado | **PASS** |

## Ensayo multianfitrión A-3 y aceptación VPS A-4 — 2026-09-12 / 2026-09-15

> Redacción propuesta para el cuerpo de la tesis: `docs/cierre/CAMBIOS_PARA_TESIS_V11.md` §4. Ninguno de los dos ensayos corrió sobre el candidato consolidado `7a7ee50`.

| Evidencia | Resultado verificable | Código / evidencia |
|---|---|---|
| A-3 — mTLS agente-backend y TLS de Valkey, dos equipos físicos por LAN | 9/9 rechazos negativos (Valkey V1–V4; backend B1–B3, E1–E2); capturas de tráfico sin cadenas en claro en ambos extremos | `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md`, `RUNBOOK_WSL2_MTLS.md`; `devel` `223f85c`+`f9a536a`+`f552aa6`+`656b101` |
| A-4 — aceptación de despliegue en VPS público | 6/6 tareas del grupo 12 PASA; 7 hallazgos operativos corregidos con pruebas en el grupo 14 | `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/README.md`; `devel` `2f84d60`+`ed286d9..277a458` |

**Límites declarados de A-3:** red local doméstica, un único agente monitoreado, una sola corrida por prueba; orquestador de notificaciones degradado (sin ensayo de notificación entre dos anfitriones); hallazgos abiertos no corregidos (`process_exe` vacío, `file_created`/`file_modified` de un archivo nuevo, avalancha de 38.794 mensajes históricos del stream `commands`, reinstalación que anida el código, listener 8443 sin alerta TLS legible al rechazar).

**Límites declarados de A-4:** deduplicación de tickets con mismo `event_id` no verificada en este entorno (sin sistema de tickets controlado en el VPS).

**Estado de versionado:** `a3-multihost/` está íntegramente versionado en git (66 archivos) y trae su propio `SHA256SUMS`. Las carpetas `a4-vps-acceptance-20260915T153824Z/` y `a4-vps-20260915T145238Z/` **no están versionadas** (excluidas por `.gitignore`, patrón `/docs/cierre/evidencia/a4-vps-*/`); sólo la primera trae `SHA256SUMS` propio, la segunda no tiene README ni `SHA256SUMS`.


---

## Cierre del Capítulo 5 — 17 al 19 de septiembre de 2026

Todo lo de esta sección corre sobre el candidato **`v1.0-tesis` (`7a906c2`)**, con la imagen del
backend reconstruida desde ese commit y la procedencia verificada por hash agregado entre el
contenedor y el árbol de trabajo.

| Tema | Resultado | Acta |
|---|---|---|
| Batería 3 — latencia | n=480; mediana 35,594 ms; P95 40,556; P99 42,602; 0 negativos. Agregado con pandas, como exige el capítulo | `evidencia/oficial-cap5-20260917T223823Z/bateria3/latencia_resumen.txt` |
| Batería 5 — resiliencia | Corte de Valkey (el del protocolo): 2.920 preservados, **2.920 entregados**, 0 descartados, 0 rechazos, 0 duplicados | `evidencia/oficial-cap5-20260917T223823Z/bateria5/corte-valkey/` |
| Batería 7 — grupo de control | Mediana 591.050,981 ms; P99 898.842,935 ms; 422 de 500 cambios nunca reportados; mejora 16.605,4× en mediana | [`control/RESULTADO.md`](evidencia/oficial-cap5-20260917T223823Z/control/RESULTADO.md) |
| Ítem 9 — eventos perdidos | **0.** 513 eventos del núcleo para 500 operaciones; 31 supresiones, todas con causa `matches_active_baseline`; las 19 sin evento explicadas 19 de 19 | [`diagnostico-deteccion/RESULTADO.md`](evidencia/oficial-cap5-20260917T223823Z/diagnostico-deteccion/RESULTADO.md) |
| Inferencia pareada | McNemar χ²(1) = 386,5409; p = 4,69 × 10⁻⁸⁶; diferencia 0,8040; IC 95 % de Newcombe [0,7618, 0,8377] | [`control/MCNEMAR.md`](evidencia/oficial-cap5-20260917T223823Z/control/MCNEMAR.md) |
| Ítems 40 y 41 | 0 inversiones de orden y 0 duplicados en 5.571 eventos, antes y después de la Change 58 | `evidencia/oficial-cap5-20260917T223823Z/bateria5/corte-valkey-post-d75/verificacion-items-40-41.txt` |
| Ítem 43 — drenaje | **No cumple.** 58,809 s contra un umbral de 30. Causa raíz en el agente: `_ACK_TIMEOUT_S = 60` más la cadencia de 5 s del bucle de reintentos, no rendimiento | `evidencia/oficial-cap5-20260917T223823Z/bateria5/corte-valkey-post-d75/` |
| Corridas invalidadas | Preservadas con su motivo: imagen del backend anterior al candidato, y un intento con el arnés sin el override de TLS | [`MOTIVO.md`](evidencia/oficial-cap5-20260917T223823Z/invalido-imagen-desactualizada/MOTIVO.md) |

## Mapa de documentos de esta carpeta

Los documentos **no se unifican a propósito**. Las auditorías son instantáneas fechadas y su
sucesión es parte de la evidencia: muestra qué se observó, cuándo y qué se hizo al respecto. Las
actas viven dentro de paquetes sellados, donde fusionarlas invalidaría su `SHA256SUMS`. Y el
documento de la tesis cita varios por nombre.

| Cuándo leerlo | Documento |
|---|---|
| Para saber qué falta para la próxima versión | `DATOS_PARA_TESIS_V15.md` |
| Para reproducir un resultado desde cero | `REPRODUCIR.md` |
| Para ver qué está verificado y con qué alcance | `RESULTADOS_VERIFICADOS.md` |
| Para el estado técnico consolidado | `INFORME_CIERRE_TECNICO.md`, `CIERRE_CONSOLIDADO.md` |
| Para la trazabilidad historia ↔ prueba | `MATRIZ_TRAZABILIDAD.md` |
| Para el inventario con hashes | `evidencia/INDICE.md` |
| Para la evolución del dictamen | `AUDITORIA_INTEGRAL_TESIS_V5..V11.md` y sus `_METRICAS.json`, en orden |
| Para qué cambió entre versiones del documento | `REGISTRO_CAMBIOS_TESIS_V5/V12/V13.md`, `CAMBIOS_PARA_TESIS*.md` |
| Para la reorganización del repositorio | `../MIGRACION_DOCS_A_TESIS.md` |
