# Resultado verificado — Run 4 después de backend Unidad 1

**CUMPLE** el umbral original estricto `<30 s` en esta evaluación controlada:
3.000/3.000 eventos persistidos y retirados de la cola en **29,146 s**
(**102,929 eventos/s**). El denominador planificado y efectivo fue 3.000.

| Marca monotónica desde reconexión | Resultado |
|---|---:|
| Último `XADD events` | 28,140 s |
| Último commit PostgreSQL | 29,014 s |
| Último `XACK` atómico | 29,015 s |
| Último `event_ack` aplicado por el agente | 29,015 s |
| PostgreSQL completo y cola local vacía | 29,146 s |

Se observaron exactamente 3.000 publicaciones, 3.000 lecturas del consumer,
3.000 validaciones HMAC, 3.000 commits, 3.000 `XACK`, 3.000 `event_ack`
firmados y 3.000 aplicaciones de ACK. Hubo 0 rechazos, 0 publicaciones
duplicadas y 0 archivos remanentes.

El criterio histórico usa 2.988 eventos y exige más de 99,6 eventos/s. Esta
corrida usó 3.000 eventos y alcanzó 102,929 eventos/s. El resultado medido
reemplaza como evidencia actual a la **proyección de 32,358 s**, que nunca fue
una medición y no debe presentarse como tal. No reinterpreta causalmente la
corrida histórica de 153 s ni borra el Run 3 de 51,773 s.

## Validez y límites

- HMAC, PostgreSQL, Valkey consumer group, persistencia, pipeline atómico
  `event_ack + XACK`, ACK firmado y borrado durable permanecieron activos.
- Rate limit experimental: 100.000/60 s; default: 100/60 s. No se cambió entre
  Run 3 y Run 4.
- Rutas únicas aíslan transporte/ingesta y no ejercitan supersesión por ruta.
- Un único anfitrión físico: no acredita despliegue multianfitrión ni red real.
- Reloj `time.perf_counter_ns`, monotónico, resolución declarada de 1 ns; todas
  las marcas comparadas pertenecen al mismo proceso/anfitrión.
- En Unidad 1 `event_ack` y `XACK` se ejecutan en una transacción Valkey. El
  harness mide el límite externo de `execute()`; no atribuye orden temporal
  interno a las dos operaciones.
- `invalid-runs/attempt1` y `attempt2` se conservan y excluyen. Sus fallas fueron
  de compatibilidad/cobertura del harness, no resultados de rendimiento.
- Una sola corrida válida demuestra cumplimiento bajo estas condiciones, no un
  SLA productivo ni una distribución de rendimiento entre repeticiones.
