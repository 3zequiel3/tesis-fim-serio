# Tabla 17 — resultado de la Batería 8

> **Estado: CORRIDA HECHA Y VÁLIDA — 2026-09-01.** 10 repeticiones por caso, 30
> operaciones, cero errores. Testigo (caso C) 10/10 → la corrida vale.
> **El resultado contradice la hipótesis**: el caso A fue detectado 10/10, cero
> `evento_sin_cambio`. La interpretación que este archivo anticipaba —«si el caso A da
> `evento_sin_cambio` en 10/10»— **no** es la que aplica. La rama que aplica está
> redactada más abajo, en «Interpretación».
>
> Los artefactos crudos (`bateria8_cambios.jsonl`, `bateria8_manifiesto.json`,
> `bateria8_correlacion.csv`) quedan en `resultados/bateria8/`, que está en `.gitignore`
> como todas las corridas. Por eso los números viven acá, en un archivo trackeado.

## Los números — Tabla 17

Corrida 2026-09-01 · agente `docker-agent` sobre `/watch` (bind mount `./fim-watch`) ·
kernel 7.0.0-30-generic · 10 repeticiones por caso.

| Caso | Mod. efectivas | Eventos emitidos | Detección | Ev. sin cambio | Sin evento |
|---|---|---|---|---|---|
| A — `mmap`, `close(fd)` **previo** a la escritura | 10/10 | 10 | **10/10** | 0 | 0 |
| B — `mmap`, `close(fd)` posterior (control) | 10/10 | 10 | 10/10 | 0 | 0 |
| C — `open`/`write`/`close` (testigo) | 10/10 | 10 | 10/10 | 0 | 0 |

Latencia entre la operación y el evento persistido, para los eventos que sí traen el
hash posterior a la modificación:

| Caso | n | mín | mediana | máx |
|---|---|---|---|---|
| A | 10 | 0,9 ms | 9,5 ms | 10,1 ms |
| B | 10 | 1,0 ms | 5,5 ms | 9,9 ms |
| C | 10 | 0,4 ms | 0,7 ms | 1,2 ms |

## Interpretación — para el §5.9

**La evasión no se observó.** El caso A —la secuencia que la hipótesis daba por evasiva—
fue detectado en las 10 repeticiones, con `hash_detected` igual al contenido posterior a
la modificación.

**Mecanismo.** La hipótesis acertó la premisa y erró la conclusión. El `CLOSE_WRITE`
efectivamente se emite antes de la escritura sobre el mapeo: el agente no tiene forma de
enterarse de esa escritura. Pero el agente **no hashea en el instante del evento**. El
`close(fd)` solo encola: el hilo lector de fanotify hace `call_soon_threadsafe` hacia una
`asyncio.Queue` (`agent/detector.py:400`) y el hash se computa después, en
`_process_event`, sobre el event loop. La secuencia in-process del caso A (escribir sobre
el mapeo → `msync` → `munmap`) no tiene syscalls de por medio y consume microsegundos.
Para cuando el agente abre el archivo y lo hashea, la modificación ya está en la página.
El agente detecta **no por haber visto la escritura, sino por hashear tarde**.

**Alcance — esto no cierra la limitación, la acota.** Lo que la batería mide es que la
ventana de evasión existe y es estrecha —del orden de los 10 ms de la latencia de
detección—, no que sea nula. Un adversario que introduzca una demora mayor a esa latencia
entre el `close(fd)` y la escritura sobre el mapeo debería seguir evadiendo, porque el
agente ya habría hasheado contenido íntegro. **Esta batería no midió ese caso.**

**Cómo redactarlo**: «consistente en las 10 repeticiones», nunca «determinística». El
desenlace depende de una carrera entre la secuencia in-process y el pipeline cross-thread
del agente (`agent/detector.py:265,400-406,769-778`), y el margen no fue caracterizado.
La afirmación fuerte no se sostiene si la piden en sala.

## Numeración — resuelto

Había un choque: `docs/plan_medicion_cap5.md:380` ya usaba **Batería 7** para el grupo
de control, y `scripts/control_hashing.py` escribe `bateria7_control.csv`. Correr la de
mmap con el número 7 habría pisado el directorio de salida del control.

Ya está renombrado todo a **Batería 8**, en los scripts, en el plan de medición y en
`cambios_codigo_bloque_A.md`.

**Lo que queda pendiente en la tesis**: el §3.7 dice "seis baterías secuenciales" cuando
el plan interno tiene siete; con esta van **ocho**. Hay que actualizar ese número.

## Procedimiento — cómo reproducirla

```bash
# 1. Correr la batería contra el laboratorio, con el agente andando.
#    No hace falta sudo: el script crea sus propios archivos en fim-watch/ y el
#    agente los lee como root desde el contenedor.
./scripts/bateria_mmap.py \
    --dir fim-watch --agent-prefix /watch \
    --repeticiones 10 --salida ./resultados/bateria8

# 2. Esperar ~30 s a que drene la ingesta.

# 3. Cruzar contra la tabla events.
#    OJO: el servicio `db` del compose NO publica el 5432 al host. Apuntar a localhost
#    te conecta a cualquier otro Postgres que escuche ahí y falla la autenticación.
DBIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' \
       tesis-fim-serio-db-1 | awk '{print $1}')
export DATABASE_URL="postgresql://fim:${DB_PASSWORD}@${DBIP}:5432/fim"

python3 scripts/analisis_mmap.py \
    --jsonl  resultados/bateria8/bateria8_cambios.jsonl \
    --salida resultados/bateria8/bateria8_correlacion.csv
```

`analisis_mmap.py` necesita `psycopg`, su única dependencia no-stdlib. Si el host no
tiene `pip` ni `venv` disponibles, correrlo con
`uv run --with 'psycopg[binary]' python3 scripts/analisis_mmap.py ...`.

## El criterio de atribución — por qué no alcanza con contar eventos

Si el caso A hubiera evadido, el agente igual habría emitido un evento —el `CLOSE_WRITE`
del descriptor— pero con el hash del contenido todavía íntegro. Contar eventos a secas
habría dado "detectado" y habría sido falso: el evento existe, la detección de la
modificación no.

Por eso el correlacionador exige que `hash_detected` del evento coincida con
`hash_despues` del manifiesto, y desglosa en tres estados: `detectada`,
`evento_sin_cambio` (esa habría sido la evasión) y `sin_evento`. La Tabla 17 tiene
"Eventos emitidos" y "Detección" en columnas separadas por esa razón: para poder mostrar
la diferencia si aparece. En esta corrida las dos columnas coinciden, y eso **también**
es información — dice que no hubo evento ciego.

## El corte de validez

Si el caso C no detecta 10/10, `analisis_mmap.py` devuelve código 1 y avisa que la
corrida no vale. Un cero en el caso A no prueba evasión mientras el testigo no dé 100 %;
prueba que el agente no estaba mirando. **No reportar la Tabla 17 si ese chequeo falla.**

En esta corrida el testigo dio 10/10.
