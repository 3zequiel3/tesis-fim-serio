# Baterias complementarias sobre el candidato v5.1-tesis

Paquete: `v5.1-complementarias-20261003T125747Z`. Candidato `v5.1-tesis` (commit 404402a); HEAD descendiente con agent/, backend/, frontend/ y n8n/ sin cambios (ver `env/procedencia.txt`). Laboratorio vivo: pila Docker `tesis-fim-serio-*`, imagen `fim-backend:dev` sin reconstruir, agente en la VM `fim-host` (watch `/srv/fim-watch`). Antes de cada bateria se purgo el agente (`vm_reset.sh`, conserva el cursor de comandos), se vaciaron events/alerts/rejected_events_audit y el stream, y se recreo el backend sin build hasta ver `consumer.started`. No se modifico ningun script del harness.

## b5b_reconciliacion/ — reconciliacion al arranque (B-5b)
Comando: `TAG=v5.1-tesis bash lab/b5b_reconciliacion.sh <pkg>/b5b_reconciliacion 10`.
Resultado: 10 de 10 repeticiones conformes. En cada una: 4 file_modified y 3 file_deleted, todos con detected_offline=true, y 0 eventos para los 3 archivos recreados con bytes identicos ni para ninguna otra ruta. El journal del agente registra `baseline.reconcile.complete` con deleted=3, modified=4, unchanged=3, sin errores. Sin desviaciones. Archivos: `resumen.csv`, `resumen.txt`, `rep-NN.csv`, logs.

## b5_mmap_casoD/ — barrido del retardo mmap (B-5, caso D)
Comando (en la VM, como root): `python3 bateria_mmap.py --dir /srv/fim-watch --agent-prefix /srv/fim-watch --casos C,D --repeticiones 10`; analisis en el host con `scripts/analisis_mmap.py --tolerancia-s 30` (conexion a PostgreSQL por la IP del contenedor).
Resultado: testigo (caso C) 10/10 detectado, corrida valida. Para d = 0, 5, 10, 20, 50, 100 y 500 ms: 10/10 detectadas en cada retardo (70/70), con hash_detected igual al contenido final; 0 `evento_sin_cambio` y 0 `sin_evento`. No se observo ventana de evasion hasta 500 ms. Complemento (`latencia_deteccion.txt`): el detected_at del evento sigue al instante de la escritura sobre el mapeo (mediana 13,8 ms para d=0; 114,1 ms para d=100; 512,6 ms para d=500), es decir, la deteccion se produce despues de la escritura y no ~10 ms despues del cierre del descriptor. El mecanismo no se investigo en esta bateria.
Intento previo invalido: ver `invalidos/b5_mmap_casoD-doble-ejecucion/LEEME.md` (lanzamiento duplicado por un error de comillas del wrapper; repetida desde estado limpio).

## b1_strace/ — generador bajo strace (B-1)
Comando (VM, root): `sh /tmp/vm_strace_gen.sh v51` (125 operaciones = 25 creaciones + 100 modificaciones a 10/s, semilla 20261001).
Resultado: 1036 lineas de strace. Por cada una de las 100 modificaciones: exactamente 1 openat, 1 write y 1 close sobre la ruta (distribucion (1,1,1) en 100/100); ningun write corto (el retorno coincide con los bytes del manifiesto); el cierre ocurre en mediana 0,84 ms (max 1,31 ms) despues de la apertura. Totales de modificacion: openat=100, write=100, close=100. Creaciones: tambien (1,1,1) en 25/25. En la base: 100 file_modified + 25 file_created = 125 eventos, es decir, ninguna operacion sin evento. Script de resumen: `resumen_strace.py` (salida en `resumen_strace.txt`).

## b3_barrido/ — barrido de notify_max_concurrent_deliveries (B-3)
Comando: `TAG=v5.1-tesis bash lab/exportar_notif.sh barrido <pkg>/b3_barrido` (100 notificaciones por valor, concurrencia 100).
Resultado (ms, n=100 por valor; ms_aceptacion = channel_accepted_at - received_at):

| max | media | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| 8 | 2225,1 | 2221,5 | 3778,0 | 3831,8 | 3837,1 |
| 16 | 2318,6 | 2325,8 | 3698,0 | 3819,0 | 3824,6 |
| 32 | 2540,7 | 2599,0 | 3747,1 | 3817,3 | 3892,4 |
| 64 | 2791,3 | 2546,0 | 3718,3 | 3751,8 | 3758,1 |

La latencia de aceptacion no mejora al subir el limite (el p99 es ~3,8 s en los cuatro valores; la media sube de 2,2 a 2,8 s): con estos datos el limite de entregas concurrentes no es el factor que acota la cadena. ms_entrega supera a ms_aceptacion en 4-5 ms en media. Al final el backend se recreo sin override: `printenv NOTIFY_MAX_CONCURRENT_DELIVERIES` queda vacio (variable no definida) y `settings.notify_max_concurrent_deliveries` = 32, el default de `backend/app/core/config.py` (`restauracion.txt`). Nota: el resumen final del script fallo porque el Python del host no tiene pandas; `resumen.txt` se genero con el mismo codigo del script ejecutado en un venv con pandas (el fallo figura en `ejecucion.out`).

## Revision de logs
En las cuatro baterias no hubo lineas de nivel error/critical ni trazas en el backend ni en el journal del agente (los warnings del agente son el aviso conocido de work_dir compartido con watch_paths).

## Sellado
`SHA256SUMS` cubre todos los archivos del paquete salvo si mismo; verificar con `sha256sum -c SHA256SUMS` desde este directorio.
