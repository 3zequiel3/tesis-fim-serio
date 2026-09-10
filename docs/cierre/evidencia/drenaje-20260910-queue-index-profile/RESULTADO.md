# Resultado comparativo

Misma lista de 3.000 payloads, mismo proceso, filesystem y orden:

| Etapa | `HEAD` 7115511 | Working tree indexado |
|---|---:|---:|
| Enqueue | 29,458 s | 0,166 s |
| Bump de intento | 38,075 s | 0,220 s |
| Remove por ACK | 17,697 s | 0,036 s |

Ambas variantes terminaron con cero entradas. La comparación prueba el costo
cuadrático del escaneo completo y que el índice elimina ese cuello local. No
prueba por sí sola el umbral extremo a extremo: todavía intervienen Valkey,
validación, PostgreSQL y el orden de arranque del listener de ACK.
