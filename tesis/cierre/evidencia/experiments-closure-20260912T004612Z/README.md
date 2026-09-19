# Cierre experimental A-3 / M-1 / M-2

**Estado: EJECUTADO — VERIFICACIÓN INDEPENDIENTE PASS**

Candidato: commit autocontenido `7df4935f769a2e393a5e6a6330df605c77592e52`, árbol `95455f919ec602b6cddf1440341652d99b784bd3`, recuperado del bundle de la validación consolidada final.

## Resultados

| Riesgo | Resultado nuevo | Estado acotado |
|---|---|---|
| A-3, concurrencia | 100 tareas listas antes de la barrera; 100/100 solicitudes aceptadas; 100 identificadores únicos; máximo 100 handlers activos; P99 backend→receptor **616,626 ms** | Cumple `<5.000 ms` en el transporte productivo `send_n8n` hacia receptor local controlado. No acredita n8n/canal final ni sistema integral. |
| M-1, drenaje | 5/5 corridas válidas: **27,784; 29,043; 28,109; 29,188; 27,997 s**. Media **28,424 s**, mediana **28,109 s**, min/max **27,784/29,188 s**, desvío muestral **0,644 s**. 3.000/3.000, cero rechazos, duplicados y cola residual en todas. | Cumple `<30 s` en las cinco repeticiones comparables. No reproduce desconexión completa de cinco minutos y conserva tasa experimental. |
| M-2, latencia | 100/100 modificaciones correlacionadas; P99 `(close externo)→received_at` **31,533 ms**; media 15,260 ms; mediana 13,331 ms; P95 26,506 ms; 0 intervalos negativos. | Cumple `<1.000 ms` en esta corrida nueva local. No reinterpreta 17,274/17,745 ms históricos. |

## Intentos inválidos preservados

- Concurrencia intento 1: 88/100. La capacidad predeterminada de la cola del receptor no soportó la ráfaga; se preserva sin incorporarlo al resultado final. La repetición cambió únicamente `request_queue_size` del receptor y obtuvo el denominador completo. No se atribuye el intento a un defecto del producto.
- Drenaje intento interrumpido: el comando agrupado terminó durante la segunda invocación sin producir resumen ni exit code; se conserva en `invalid-interrupted-run-02/` y no se cuenta. Se ejecutó luego una corrida 02 completa.
- Latencia intento 1: los archivos baseline tenían dos dígitos y el generador buscaba tres; finalizó antes de la primera modificación. Se preserva y no se cuenta. La repetición corrigió sólo el padding del nombre.

## Integridad y límites

`metadata/independent-verification.json` recompone los estadísticos desde registros individuales y verifica 17 condiciones. La inspección de privacidad no encontró credenciales reales; las copias de Run 4 contienen sólo la clave HMAC sintética fija documentada. Los laboratorios no tocaron código productivo, no stagearon ni commitearon. Los recursos aislados quedaron en cero y la identidad nombre+imagen de los 14 contenedores preexistentes fue idéntica antes/después.

Esto no constituye una validación integral, no cambia la hipótesis ni acredita multianfitrión, TLS de Valkey, SMTP o proveedores comerciales.
