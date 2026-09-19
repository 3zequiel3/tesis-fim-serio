# Protocolo A-3 — cien solicitudes concurrentes

## Criterio conservado

Cien solicitudes simultáneas y percentil 99 del intervalo backend→aceptación del receptor menor que 5.000 ms. El ensayo no sustituye la batería histórica ni modifica su denominador.

## Procedimiento

1. Se importó `app.modules.alerts.notifier.send_n8n` desde el candidato congelado.
2. Cien corutinas alcanzaron una barrera antes de ser liberadas.
3. Cada corutina fijó `received_at` inmediatamente después de la barrera y llamó a la función productiva con un payload sintético identificable.
4. Un receptor HTTP local controlado selló la recepción antes de procesar el cuerpo. Retuvo cada handler 50 ms después del sello para hacer observable el solapamiento, sin alterar el instante de recepción.
5. Se exigieron 100 identificadores únicos recibidos, 100 retornos exitosos, actividad concurrente observada y P99 <5.000 ms.

## Alcance

Acredita el tramo de transporte de notificación desde una recepción backend simulada hasta un receptor HTTP controlado. No atraviesa persistencia de eventos, n8n, SMTP, proveedores comerciales, reintentos ni un segundo anfitrión; no es una validación integral.
