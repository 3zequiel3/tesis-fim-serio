# Diagnóstico del drenaje sobre v5.0-tesis — 2026-10-03

No es una corrida del Capítulo 5. Es el diagnóstico que reabre el INSERT agrupado (grupo 7 de la Change 69), por la regla fijada en `mediciones.md` §5: si el laboratorio mide menos de 95 ev/s, se reabre.

- **Condiciones.** Batería 5 aislada sobre `v5.0-tesis`, con servidor truncado, bucket lleno y backend recreado con `FIM_PROFILE_INGEST=true`.
- **Ritmo.** 2.995 eventos consumidos en 39,1 s: **76,6 ev/s**.
- **Desglose por etapa** (`timing.jsonl`, 2.995 muestras por evento):

  | Etapa | Media por evento | Total |
  |---|---|---|
  | `auth_ms` | 0,02 ms | 0,1 s |
  | `validation_ms` | 0,14 ms | 0,4 s |
  | `ingest_ms` | 12,27 ms | 36,7 s |

  El flush de ACK suma 0,4 s en 64 lotes. **El 98 % del tiempo está en la ingesta.**
- **Lado del cuello de botella.** En `lag_stream_prueba2.txt`, el lag del grupo de consumidores sube de 20 a 581 en 8 s después de restaurar Valkey. El agente publica más rápido de lo que el backend consume.
- **Prueba 2.** Esa prueba no truncó el servidor ni recreó el backend: el bucket estaba casi vacío y sus totales no valen. Sólo se usan sus primeros 15 s de lag.
