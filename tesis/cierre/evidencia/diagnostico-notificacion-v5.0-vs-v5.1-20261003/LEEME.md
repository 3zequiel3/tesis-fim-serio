# Tasa de entrega de notificaciones: v5.0-tesis contra v5.1-tesis — 2026-10-03

No es una corrida del Capítulo 5. Es el diagnóstico de por qué el P99 de la Batería 3 pasó de 22,6–23,7 s en `v5.0-tesis` a 29,5–29,6 s en `v5.1-tesis`.

**Método** (`medir_tasa_entrega.sh`): se truncaron `events` y `alerts` y se recreó el backend. Después se publicaron 1.000 eventos sintéticos (`b4_*`) con concurrencia 50 y se midió, con timestamps absolutos, desde el primer `received_at` hasta el último `delivered_at`. El laboratorio y el sumidero (n8n → Mailpit) fueron los mismos; lo único que cambió fue la imagen del backend.

| Imagen | Absorción de los 1.000 (`received_at`) | Primer `received_at` → último `delivered_at` | Tasa de entrega |
|---|---|---|---|
| `v5.0-tesis` | 12,79 s | 36,16 s | 27,7 notif/s |
| `v5.1-tesis` (1.ª) | 5,16 s | 36,55 s | 27,4 notif/s |
| `v5.1-tesis` (2.ª) | 5,92 s | 34,70 s | 28,8 notif/s |

**Conclusión.** La entrega no cambió entre las dos versiones: unas 28 notificaciones por segundo, limitadas por la cadena n8n → SMTP. El P99 de la Batería 3 creció porque el intervalo arranca en `received_at`. Con la ingesta más rápida de la Change 70, los 1.000 eventos se reciben antes, y la espera en la cola de entrega queda dentro del intervalo. En §5 el P99 de notificación tiene que leerse como drenaje de cola y compararse por la tasa de entrega, no entre candidatos con distinta velocidad de ingesta.
