# Resultado verificado — Run 2

La nueva evaluación completó el ciclo de **3.000 eventos en 362,834 s**:
**8,268 eventos/s**. No cumple el umbral original `< 30 s` (99,6 eventos/s
para 2.988 eventos) y resultó más lenta que la corrida histórica (153 s;
19,529 eventos/s). Persistió 3.000/3.000, dejó 0 en cola local y registró 0
rechazos.

## Cuello observado

El agente realizó **8.682 XADD** para 3.000 identificadores: 5.682
publicaciones excedentes. `Publisher.run()` inicia `_ack_listener` recién
después de esperar `_drain_queue`; la primera publicación completa de los
3.000 eventos tardó 114,220 s, ya por encima del timeout de ACK de 60 s. Al
habilitarse luego el listener, `_retry_loop` encuentra eventos vencidos y
republica mientras llegan las confirmaciones. El backend deduplica la
persistencia, pero debe validar y consultar esas entregas adicionales.

Además, entre el final de un XADD inicial y el comienzo del siguiente hubo
29,685 ms en promedio. Ese tramo incluye principalmente
`EventQueue.bump_attempts()`, cuya búsqueda `_find_file()` vuelve a listar y
ordenar todos los archivos de la cola en cada evento, además de interferencia
del consumer concurrente. La cola también tardó 31,884 s en construirse, fuera
del indicador, por el escaneo total que `enqueue()` ejecuta para calcular su
tamaño.

La persistencia individual midió 10,874 ms de media (P95 16,438 ms), pero NO
explica sola los 362,834 s: antes de cada inserción existen consultas separadas
de agente, revocación y deduplicación; las 5.682 publicaciones excedentes
amplifican ese trabajo. Los intervalos se solapan y no deben sumarse.

## Corrección mínima propuesta

1. Iniciar el listener de ACK inmediatamente después del flush de comandos y
   antes del drenaje; mantener el retry loop posterior o evitar reintentar
   elementos que todavía pertenecen al drenaje inicial.
2. Mantener un índice local `event_id → archivo` y el total de bytes de la cola,
   actualizado en cada alta/baja, en vez de releer y ordenar todo el directorio
   en `contains`, `bump_attempts`, `remove` y cada `enqueue`.
3. Repetir 3.000 eventos. Sólo si continúa bajo 99,6 eventos/s corresponde
   rediseñar la ingesta PostgreSQL (reducir round trips o transaccionar batches)
   sin eliminar HMAC, persistencia, XACK ni confirmaciones.

## Límites de la evidencia

- Un único anfitrión físico; no valida rendimiento de red multianfitrión.
- Rate limit experimental 100.000/60 s; el default 100/60 s impediría comparar
  el caudal bruto y debe permanecer declarado por separado.
- Rutas únicas: evita que el costo de supersesión por ruta distorsione el
  perfil de transporte.
- `summary.json.started_at_utc` fue escrito al finalizar, pese a su nombre. No
  se usa para calcular duraciones; todas derivan del reloj monotónico.
- Pequeños intervalos negativos alrededor de XADD/XREAD (<1 ms) reflejan el
  orden de observación de coroutines concurrentes, no viaje temporal.
