# Corrida abortada — v5.0-tesis, 2026-10-02T21:57:44Z

**Inválida. No se usa en el Capítulo 5.** Se conserva como evidencia del defecto del arnés que la invalidó.

- **Síntoma.** Batería 3 run-01: n = 498, P50 = 3.234 ms, P99 = 112.574 ms (en `v4.0-tesis`, P99 ≈ 46 ms).
- **Causa.** La purga L-11 (`lab/vm_reset.sh`) borraba `state.json`, y con él `last_stream_command_id`. Al arrancar con el cursor en `0-0`, el agente reprocesa el stream `commands` completo (RN-109). Ese stream no tiene retención y tenía 209.619 entradas. La traza causal de run-01 registra 209.613 lecturas de comandos, 209.115 de ellas `ack_valid_ignored`/`queue_absent`, que compitieron con la publicación de eventos.
- **Corrección.** Commit `0880567`: la purga conserva el cursor y sólo vacía `initialized_roots`.
- **Corte.** Abortada manualmente al inicio de run-02. Antes de relanzar se esperó a que el cursor del agente alcanzara el último id del stream.
