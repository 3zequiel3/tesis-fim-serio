# Índice de evidencias de cierre

> **Corte:** 2026-09-10. Este índice conduce primero a los resultados que
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
| Cuarentena | **NO CUMPLE / PENDIENTE**: contenido en claro y sin política de retención/cleanup acreditada. |
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
