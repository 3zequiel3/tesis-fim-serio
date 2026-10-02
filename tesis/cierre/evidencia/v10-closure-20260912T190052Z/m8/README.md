# M-8 — Repetición con inventario externo registrado

**Resultado: EJECUTADO — `main_stack_unchanged=true`**

## Motivo

En `final-consolidated-fixed-20260911T225314Z/` dos intentos del laboratorio US-02/20/31 registraron
`main_stack_unchanged=false`. El script `scripts/run-us02-us20-us31-acceptance-lab.sh` compara
`docker ps --filter label=com.docker.compose.project=tesis-fim-serio --format '{{.ID}}:{{.Names}}:{{.Status}}'`
antes y después, pero sólo persiste el booleano. `{{.Status}}` incluye el tiempo de actividad (`Up N minutes`).

## Procedimiento

`run-m8-stable-inventory.sh` ejecuta el script del laboratorio **sin modificarlo** y guarda, antes y después:

- `main-status-*.txt`: el mismo formato que usa el script (ID, nombre, estado);
- `main-stable-*.txt`: ID, nombre e imagen;
- `main-started-*.txt`: ID completo, nombre, `StartedAt` y `RestartCount`.

## Resultados observados

| Control | Resultado |
|---|---|
| Código de salida del laboratorio | 0 |
| `teardown-result.json` del laboratorio | `main_stack_unchanged=true`; 0 contenedores, volúmenes y redes residuales |
| Inventario de estado | idéntico |
| Inventario ID+nombre+imagen | idéntico |
| `StartedAt`/`RestartCount` | idénticos |
| Playwright | US-02 1/1; US-20 2/2 y 2/2; US-31 2/2; combinado 5/5 y 5/5 |
| `SHA256SUMS` del paquete del laboratorio | verificado |
| Inventario de fuentes vs. candidato final | 427 archivos no-caché idénticos; sólo difieren archivos `.pytest_cache` |

Paquete del laboratorio: `docs/cierre/evidencia/us02-us20-us31-fixed-v10m820260912T190809Z/`.

## Dato contextual, no causa demostrada

`docker inspect` del contenedor `tesis-fim-serio-backend-1` registra `StartedAt=2026-09-11T22:45:01Z` y
`RestartCount=0`. El primer intento histórico comenzó hacia 2026-09-11T22:59Z y el segundo hacia 23:10Z (marcas
de `candidate-files.sha256`). Con esa antigüedad, `{{.Status}}` se expresa en minutos y cambia durante una corrida
de varios minutos. Es un mecanismo compatible con la advertencia; al no existir inventarios crudos de aquellos
intentos, no se afirma como causa.

## Límites

Laboratorio local de un solo anfitrión. La repetición no amplía el alcance funcional de las pruebas dirigidas.
