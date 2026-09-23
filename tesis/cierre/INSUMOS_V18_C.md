# Insumos v18 — sección C: qué cubre la corrida existente y qué falta

**Corrida candidata a ser «la unificada»:** `tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/`,
sobre el candidato **`v1.0-tesis` (`7a906c2`)**, ejecutada entre el 17 y el 19 de septiembre de 2026.

El pedido dice: «si ya existe una corrida que cumpla todas estas condiciones, entréguenla y no la
repitan». Este documento contrasta lo existente contra C1 y C2, condición por condición, para que la
decisión de repetir o no se tome con el detalle a la vista y no por impresión.

---

## C1 — Condiciones obligatorias

| Condición | Estado | Evidencia o faltante |
|---|---|---|
| Un único commit etiquetado | **Cumple** | `git_status_clean=yes`, commit `7a906c202e417aec5f03d9a7545e216a724aca81`, tag `v1.0-tesis`, árbol `1d5848c4…`, en `metadata/entorno.txt`. Es el único tag del repositorio |
| mTLS agente ↔ backend activo | **Cumple** | Todas las corridas con `docker-compose.tls.yml`; el arnés aborta si el puerto TLS deja de publicarse, y hay un intento preservado que se invalidó justamente por eso |
| TLS con certificado de cliente en Valkey | **Cumple** | Valkey publica 6380 con mTLS durante toda la corrida; el chequeo del puerto es parte del arnés |
| n8n activo en el camino de notificación | **NO cumple** | `N8N_WEBHOOK_URL` vacío. El notificador cae a `log_only`, que es un camino distinto del que la batería debe medir |
| Agente nativo bajo systemd | **Cumple** | Agente nativo en el anfitrión monitoreado, `fim-vm`, bajo systemd. No contenedorizado |
| Límite de ingesta predeterminado o declarado | **Cumple, con matiz** | La Batería 5 corrió con el límite elevado a 100000/60 s, **declarado** en el acta, y existe además una corrida con el valor predeterminado de 100/60 s. Las dos están en el paquete |
| Semilla fija y registrada | **Cumple** | `--seed 20260917`, registrada en el manifiesto de cada corrida |
| Trazas internas del agente | **Cumple parcialmente** | Activadas y explotadas en la corrida de diagnóstico causal, con un registro por etapa del núcleo hasta la confirmación. **No estuvieron activas en las demás baterías** |

**Dos condiciones bloquean que la corrida existente se entregue como «la unificada»: n8n y las trazas
en todas las baterías.**

---

## C2 — Baterías

| # | Batería | Estado | Detalle |
|---|---|---|---|
| 1 | Latencia y falsos negativos | **Cumple parcialmente** | 500 operaciones con la mezcla y los patrones pedidos. Mediana 35,594 ms, P95 40,556, P99 **42,602** contra un umbral de 1.000: cumple con margen. Falsos negativos: **0**, establecido con la traza causal, no por resta. **Falta**: el inicio se toma del estampado del agente, no del fin de la syscall observado con `strace -ttt -T -f` |
| 2 | Grupo de control | **Cumple** | Cron de 900 s sobre la misma carga y en la misma ventana que la batería 1. Mediana 591.050,981 ms, P99 898.842,935 ms, 422 de 500 cambios nunca reportados. McNemar χ²(1) = 386,5409, p = 4,69 × 10⁻⁸⁶, diferencia pareada 0,8040, IC 95 % de Newcombe [0,7618, 0,8377] |
| 3 | Notificación secuencial | **NO se ejecutó** | Bloqueada por n8n |
| 4 | Notificación concurrente | **NO se ejecutó** | Bloqueada por n8n |
| 5 | Resiliencia | **Cumple parcialmente** | Corte real de 5 min y 3.000 operaciones a 10/s, con el corte del protocolo —Valkey— y no del backend. Preservación 2.920 de 2.920 encolados, 0 descartados, 0 rechazos, 0 duplicados, 0 inversiones de orden. Drenaje **58,809 s contra un umbral de 30: no cumple**, con causa raíz identificada. **Falta**: son 2 corridas válidas, el pedido exige de 3 a 5 repeticiones |
| 6 | Mapeo de memoria | **NO se ejecutó** en este candidato | La evidencia disponible es de `resultados/bateria8/`, que nunca se versionó. El caso D con demora deliberada no existe |

---

## Lo que reporta la Batería 5 por repetición

De los siete datos que el pedido enumera, el paquete tiene seis: operaciones generadas, eventos
encolados, eventos entregados, duplicados, fuera de orden y tiempo de drenaje con reloj monotónico.

El séptimo —**causa de cada operación que no llegó a encolarse**— existe para la Batería 3, con la
traza causal, y **no** para la Batería 5, porque las trazas no estuvieron activas en esa corrida.

---

## Lo que falta, ordenado por lo que cuesta

1. **Configurar n8n y SMTP** y correr las baterías 3 y 4. Es el único bloqueo que no depende de
   ejecutar de nuevo lo ya hecho, y desbloquea dos baterías completas.
2. **Repetir la Batería 5 entre una y tres veces más**, con las trazas del agente activas, para
   alcanzar las 3 a 5 repeticiones y poder atribuir causa a cada operación no encolada.
3. **Instrumentar el inicio de la Batería 1 con `strace`**, si se quiere que el intervalo medido sea
   el que el protocolo define. Hoy el intervalo es una **cota inferior declarada**: excluye el tiempo
   que el evento estuvo en la cola del núcleo.
4. **Batería 6**, opcional según el propio pedido.

---

## Una observación sobre el nombre del manifiesto

El pedido especifica `MANIFEST.sha256`. Este proyecto usa **`SHA256SUMS`**, generado con el mismo
comando y verificable con `sha256sum -c`. Conviene acordar un nombre antes de la entrega: renombrar
los manifiestos existentes rompería la verificación de los paquetes ya sellados, de modo que lo
sensato es declarar la equivalencia en el Anexo F en lugar de renombrar.

---

## Lo que esta corrida aporta y el pedido no enumera

Vale declararlo, porque cubre puntos que el propio pedido ubica fuera de la sección C:

- **Procedencia del binario verificada**, no solo del código fuente: el hash agregado de todo
  `app/**/*.py` dentro del contenedor coincide con el del árbol de trabajo. Se detectó y corrigió que
  las primeras corridas usaban una imagen construida cuatro días antes del candidato, y esas corridas
  quedaron en cuarentena con su acta en lugar de borrarse.
- **Causa registrada para toda operación sin evento** en la Batería 3: 513 eventos del núcleo para 500
  operaciones, 31 supresiones todas con causa `matches_active_baseline`, y las 19 operaciones sin
  evento persistido explicadas 19 de 19.
- **Inferencia pareada ejecutada**, con su script publicado y sin dependencias externas.
- **Suites sobre el candidato**: agente 641, frontend 260 de 260, backend 827 de 839 con las 8 fallas
  restantes atribuidas a un conflicto de puerto entre pruebas y no al código.
- **Intentos inválidos preservados** con su motivo, incluido uno que se abortó al detectarse el árbol
  de trabajo sucio.
