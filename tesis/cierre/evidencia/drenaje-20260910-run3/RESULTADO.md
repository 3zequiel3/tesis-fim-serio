# Resultado verificado — Run 3 optimizado

La nueva evaluación completó 3.000/3.000 eventos, sin rechazos ni archivos
remanentes, en **51,773 s (57,945 eventos/s)**. Mejoró frente a Run 2
(362,834 s; 8,268 eventos/s) y la corrida histórica (153 s; 19,529 eventos/s),
pero **NO CUMPLE** el umbral original `<30 s` (99,6 eventos/s para 2.988).

La primera publicación de los 3.000 eventos terminó en 6,602 s. Se realizaron
exactamente 3.000 XADD, sin las 5.682 publicaciones excedentes de Run 2. Esto
confirma que el listener de ACK concurrente y el índice de cola eliminaron la
tormenta de reintentos y el cuello cuadrático local.

El remanente está en la ingesta serial del backend: el último commit llegó a
51,556 s. La operación de persistencia individual promedió 5,660 ms, pero cada
evento también realiza consultas separadas para obtener el secreto del agente,
consultar revocación, deduplicar y determinar severidad. Los eventos se
procesan uno por uno dentro de cada batch de 50.

No corresponde declarar el umbral alcanzado. Para acercarse a 99,6 eventos/s
sin quitar controles, el siguiente cambio razonable es reducir round trips de
lectura combinando autenticación/revocación/deduplicación en una consulta, o
introducir persistencia por batch preservando el orden por ruta. Esto exige una
nueva corrida; una proyección no es un resultado experimental.

## Condiciones y límites

- Rate limit experimental: 100.000/60 s; default: 100/60 s.
- HMAC, PostgreSQL, XACK, ACK firmado y borrado durable activos.
- Un único anfitrión físico; no valida red multianfitrión.
- Rutas únicas para aislar transporte e ingesta, sin costo de supersesión.
- `source-manifest.sha256` identifica los bytes relevantes porque la evaluación
  se ejecutó sobre un working tree con instrumentación y correcciones aún no
  commiteadas.
- Los intervalos concurrentes no deben sumarse. Diferencias negativas menores
  a 1 ms alrededor de XADD/XREAD son orden de observación entre coroutines.
