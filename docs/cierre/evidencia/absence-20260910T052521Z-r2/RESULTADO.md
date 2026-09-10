# Resultado de la corrida causal de ausencias

## Veredicto

La corrida válida ejecutó 60 operaciones sobre `ext4` con fanotify nativo dentro de un contenedor con `CAP_SYS_ADMIN` y `CAP_DAC_READ_SEARCH`, backend/Valkey/PostgreSQL aislados y el mismo reloj monotónico del host.

| Caso | Operaciones | Clasificación | Persistencia backend |
|---|---:|---|---|
| Cambio C0→C1 | 10 | 10 totalmente correlacionadas | 10/10 |
| Cambio sucesivo C1→C2 | 10 | 10 totalmente correlacionadas | 10/10 |
| Retorno C2→baseline aprobada C0 | 10 | 10 descartes legítimos `matches_active_baseline` | No aplicable: no se generó evento |
| Creación | 10 | 10 totalmente correlacionadas | 10/10 |
| Eliminación | 10 | 10 totalmente correlacionadas | 10/10 |
| Modificación efímera create/write/delete | 10 | 10 observadas y totalmente correlacionadas en esta corrida | 10/10 |

Resultado consolidado del analizador: `fully_correlated=50 | suppressed_by_active_baseline=10`. No hubo una ausencia nueva inexplicada. La detección 10/10 de modificaciones efímeras es un resultado observado bajo estas condiciones, no una garantía determinista.

## Baseline y correlación

Antes de las operaciones contadas, C0 fue creado con el agente detenido y se aplicó el comando firmado `rescan_baseline`. `rescan-agent.log` prueba la ejecución. Para cada retorno C2→C0, `agent_trace.jsonl` registra `kernel_received`, `baseline_read` con estado `present` y hash C0, y `decision_suppressed` con razón `matches_active_baseline`; no registra enqueue/XADD/ACK para esa operación. C1 y C2 conservan el mismo hash de baseline C0 y alcanzan enqueue, XADD, ACK y persistencia PostgreSQL.

El analizador usa ventanas no solapadas por ruta. Prefiere `CLOCK_MONOTONIC` porque generador y agente comparten kernel y no existe un time namespace; UTC queda como referencia humana. Los timestamps `started_*` se toman antes de cada mutación y `completed_*` después.

## Límite histórico

Esta corrida valida el mecanismo actual compatible con los 7 faltantes de B3 y 12 de B5, todos retornos al hash de la baseline aprobada según manifiestos y código histórico. NO demuestra retrospectivamente que los 19 siguieran exactamente estas etapas: los runs históricos no conservaron eventos kernel, lectura de baseline, decisión, cola, publish ni ACK. Su clasificación histórica correcta sigue siendo “explicación fuertemente sustentada, causalidad runtime retrospectiva no demostrable”.

## Incidentes excluidos

`../absence-20260910T051102Z/` conserva dos intentos inválidos y no debe contarse:

1. El trace inicial registraba eventos fuera de alcance en el mismo filesystem marcado y se autoamplificó antes de la carga. Se detuvo, se conservó el raw comprimido y se corrigió con regresión.
2. El primer harness asumió incorrectamente que escribir C0 establecía una baseline; el trace mostró `baseline_status=missing`. Se interrumpió y se reemplazó por precreación + rescan firmado.

También se detectó que el backend compartido rechazó correctamente una CA histórica sin el perfil requerido. Para no rotar credenciales ni alterar datos compartidos, la corrida válida usó un proyecto Compose aislado con volúmenes nuevos.

## Evidencia

- `bateria9_operaciones.jsonl`: operación, límites temporales, ruta y hashes antes/después.
- `agent_trace.jsonl`: kernel, baseline, decisión, cola, XADD y ACK append-only.
- `backend-events.csv`: 50 filas persistidas seleccionadas por slug de run.
- `bateria9_correlacion.csv`: clasificación por operación.
- `environment.txt`, `containers.txt`, `source-sha256.txt`, `worktree-before.txt`: condiciones e identidad.
- `raw-sha256.txt` y `SHA256SUMS`: integridad.

No se almacenó contenido completo, diff, credenciales ni secretos en este paquete.
