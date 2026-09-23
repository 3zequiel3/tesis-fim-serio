# Las tres trazas de esta batería son inválidas

Los archivos `run-01/traza_run-01.jsonl`, `run-02/traza_run-02.jsonl` y `run-03/traza_run-03.jsonl`
**no corresponden a estas repeticiones**. No son tres trazas: son el mismo archivo copiado tres
veces.

## Prueba

Las tres tienen idéntico SHA-256, idéntico recuento de líneas e idéntico tamaño:

```
888f7f03c178c1879416a7a00b5704c05bd4ebd5bf954c1048fdc0712b8bcb0c   216 581 líneas   92 478 240 bytes
```

El contenido abarca de `2026-09-22T17:58:31` a `2026-09-22T19:17:26`. Las repeticiones de esta
batería se ejecutaron entre las **19:27 y las 19:57**, es decir, íntegramente después del último
registro. De estas repeticiones no hay traza.

## Causa

Dos defectos independientes del arnés, ambos corregidos después de detectarse:

1. `rehacer_notif_resil.sh`, que rehízo las baterías de notificación y resiliencia, nunca invocó
   `vm_trace_on.sh`. Las trazas habían quedado apagadas por el `vm_trace_off.sh` con que cierra
   `corrida_unificada.sh`. El script copió igual el archivo remanente, tres veces, sin fallar.
2. Ni siquiera `corrida_unificada.sh` truncaba `/var/lib/fim-agent/traza_b3.jsonl` entre
   repeticiones: copiaba el mismo archivo acumulativo a cada destino. **Aun con las trazas
   encendidas, `traza_run-02` habría contenido los registros de `run-01`.** Las trazas nunca fueron
   por repetición.

## Alcance: qué invalida y qué no

**No invalida** ninguna medición de esta batería. Los conteos, la ventana de drenaje, la
preservación, los duplicados y los rechazos salen de la base de datos, no de las trazas:

| Repetición | Encolados | Entregados | Descartados | Ventana |
|---|---|---|---|---|
| run-01 | 2671 | 2671 | 0 | 141,061 s |
| run-02 | 2664 | 2664 (+35 residuales) | 0 | 120,366 s |
| run-03 | 2663 | 2663 | 0 | 150,150 s |

**Invalida** la atribución causal por operación en esta batería, y con ella el cumplimiento de la
condición del protocolo que exige trazas internas del agente activas en todas las baterías.

## Sobre el sello

`SHA256SUMS` verifica 46 de 46. El sello es correcto y no fue regenerado: prueba que nadie alteró
los archivos después de la medición. **No prueba que los archivos sean los que corresponden.**
Integridad no es pertinencia, y ninguna suma de verificación distingue un archivo legítimo de un
archivo legítimo pero ajeno.

## Corrección aplicada

- `vm_reset.sh` borra la traza con el agente detenido, de modo que cada repetición produce la suya.
- `vm_trace_range.sh` (nuevo) informa líneas, bytes y rango temporal de la traza.
- `corrida_unificada.sh` aborta si las trazas no quedan activas; por repetición verifica que la
  traza no esté vacía, que su hash difiera del de la repetición anterior y que su primer registro no
  sea anterior al inicio de la repetición. También comprueba que la batería arranque en `events=0` y
  purga el stream de Valkey en cada reset.
- Los helpers se transfieren a la VM en cada corrida: `/tmp` no sobrevive a un reinicio del huésped,
  y las llamadas a `/tmp/vm_reset.sh` redirigen `stderr` a `/dev/null`, de modo que un reset que no
  se ejecuta es indistinguible de un reset que funcionó.

La corrección se verificó de punta a punta contra la VM: activación, truncado en el reset y escritura
de registros nuevos con marca temporal correcta ante un evento real.
