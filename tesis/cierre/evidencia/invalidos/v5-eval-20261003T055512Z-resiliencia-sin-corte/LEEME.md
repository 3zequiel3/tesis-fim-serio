# Corrida incompleta — v5.0-tesis, 2026-10-03T05:55:12Z

**Inválida como paquete del Capítulo 5.** Latencia (3 repeticiones) y notificación (3 escenarios) se completaron, pero la batería de resiliencia no llegó a cortar Valkey en ninguna repetición.

- **Causa.** En `lab/bateria5.sh` la guarda de procedencia corría dentro de un pipe (`procedencia_exigir … | tee`). Cada etapa de un pipe corre en un subshell, así que `COMMIT` no llegaba al shell principal, y `set -u` terminaba el script en la línea siguiente sin escribir nada en el log. `corrida_unificada.sh` informaba cualquier salida distinta de cero como «el backend se recreó durante el corte», lo que ocultaba la causa real.
- **Notificación.** El `resumen.txt` original falló con `TypeError` después del primer escenario: el DataFrame reutilizaba el nombre de la variable del directorio. Se recalculó desde los CSV antes del sellado; los CSV no se tocaron.
- **Corrección.** Commits posteriores a `4a46d10` en `lab/`: la guarda ya no corre dentro de un pipe y la batería usa códigos de salida 2 (aborto previo al corte) y 3 (corte inválido).
