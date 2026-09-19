# Intento inválido — Batería 5 (nominal), 2026-09-17T22:41:18Z

## Qué pasó

El guion de la batería reconectó el backend con `docker compose --profile app up -d backend`,
**sin** los dos archivos de composición (`-f docker-compose.yml -f docker-compose.tls.yml`).
Compose recreó los servicios con la configuración base, sin el override de TLS, y Valkey dejó
de publicar el puerto 6380. Desde ese momento el agente no pudo publicar:

    publisher.* error: "Error 111 connecting to 192.168.1.43:6380. Connect call failed"

## Por qué la corrida no mide lo que dice medir

El cronómetro del drenaje quedó corriendo mientras el transporte estaba caído. Los 100 eventos
persistidos corresponden a una sola ventana del límite de ingesta (100 por 60 s) antes de la
pérdida del transporte, y el estancamiento posterior no es atribuible al sistema evaluado.

## Qué sí quedó registrado, y es del sistema

- 3.000 cambios generados a 10/s durante 299,901 s, con manifiesto completo.
- 8.121 rechazos por `rate_limited` y 84 por `clock_skew` en `rejected_events_audit`.
- Al restaurar el override de TLS, el agente reanudó la publicación sin intervención y sin
  pérdida de la cola local: la ingesta retomó a razón de una ventana por minuto.

## Defecto del arnés, corregido

`bateria5.sh` pasa a invocar siempre `docker compose -f docker-compose.yml -f docker-compose.tls.yml`
tanto para detener como para levantar el backend.

Este intento se conserva sin resultado válido, conforme al criterio del paquete de cierre de
preservar los intentos fallidos.
