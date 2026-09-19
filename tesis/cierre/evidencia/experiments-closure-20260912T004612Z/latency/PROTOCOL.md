# Protocolo M-2 — latencia con inicio observado externamente

## Definición

- Inicio `(a)`: finalización de `close(2)` del archivo modificado, observada por un proceso `strace -ttt -T -yy`. Se calcula como timestamp de entrada del syscall más su duración reportada.
- Fin `(c)`: `events.received_at` persistido por el backend para el mismo path/evento.
- Intervalo: `(c) - (a)`, en milisegundos.

## Procedimiento

Un laboratorio Compose aislado construyó backend y agente desde el candidato congelado. Se crearon 100 archivos antes del arranque del agente y se verificaron 100 entradas de baseline. Luego el generador efectuó 100 secuencias `open → write → fsync → close` a 10 operaciones/s. `strace` registró los cierres sin utilizar los timestamps propios del generador como fuente principal. La base PostgreSQL aportó los fines y el cruce se realizó por path único. La traza observacional opt-in del agente corroboró cobertura de los cien paths.

## Alcance

Es una corrida nueva de 100 modificaciones, no una reagregación de las 500 históricas. Usa un solo anfitrión y reloj de kernel compartido por host/contenedores; no acredita sincronización remota, TLS de Valkey ni latencia de red interhost. El inicio sí es independiente del reloj registrado por el generador; el fin continúa siendo la marca productiva del backend.
