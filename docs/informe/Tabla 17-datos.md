# Tabla 17 — cómo se completa

> **Estado.** Los dos scripts ya están en el repo (`scripts/bateria_mmap.py` y
> `scripts/analisis_mmap.py`) y la batería quedó registrada como **Batería 8** en
> `docs/plan_medicion_cap5.md`. La documentación operativa completa —casos, corte de
> validez, salvedades, cómo reportarlo— vive en `scripts/README.md`. Este archivo
> queda solo como nota de traspaso.

Se completa corriendo la batería y cruzándola contra la base. El correlacionador que
faltaba ya está escrito, así que no hay que contar a mano.

## Numeración — resuelto

Había un choque: `docs/plan_medicion_cap5.md:380` ya usaba **Batería 7** para el grupo
de control, y `scripts/control_hashing.py` escribe `bateria7_control.csv`. Correr la de
mmap con el número 7 habría pisado el directorio de salida del control.

Ya está renombrado todo a **Batería 8**, en los scripts, en el plan de medición y en
`cambios_codigo_bloque_A.md`.

**Lo que queda pendiente en la tesis**: el §3.7 dice "seis baterías secuenciales" cuando
el plan interno tiene siete; con esta van **ocho**. Hay que actualizar ese número.

## Procedimiento

```bash
# 1. Correr la batería contra el laboratorio, con el agente andando
sudo ./scripts/bateria_mmap.py \
    --dir /var/fim-lab --agent-prefix /var/fim-lab \
    --repeticiones 10 --salida ./resultados/bateria8

# 2. Esperar ~30 s a que drene la ingesta

# 3. Cruzar contra la tabla events
export DATABASE_URL='postgresql://fim:...@localhost:5432/fim'
python3 scripts/analisis_mmap.py \
    --jsonl  resultados/bateria8/bateria8_cambios.jsonl \
    --salida resultados/bateria8/bateria8_correlacion.csv
```

El paso 4 es copiar las filas que imprime al final directo a la Tabla 17.

## El criterio de atribución — por qué no alcanza con contar eventos

En el caso A el agente **sí emite** un evento —el `CLOSE_WRITE` del descriptor— pero con
el hash del contenido todavía íntegro. Si contás eventos a secas te da "detectado" y es
falso: el evento existe, la detección de la modificación no.

Por eso el correlacionador exige que `hash_detected` del evento coincida con
`hash_despues` del manifiesto, y desglosa en tres estados: `detectada`,
`evento_sin_cambio` (esa es la evasión, y es el hallazgo fino) y `sin_evento`.

Eso cambia la forma de la Tabla 17. Si el caso A da `evento_sin_cambio` en 10/10, la
columna "Eventos emitidos" va a decir 10 y la de "Detección" va a decir 0 — y esa
aparente contradicción **es** el resultado. Por eso la tabla tiene las dos columnas
separadas: para mostrarla, no para esconderla.

## El corte de validez

Si el caso C no detecta 10/10, `analisis_mmap.py` devuelve código 1 y avisa que la
corrida no vale. Un cero en el caso A no prueba evasión mientras el testigo no dé 100 %;
prueba que el agente no estaba mirando. **No reportes la tabla si ese chequeo falla.**

## Cómo redactarlo

**"Consistente en las 10 repeticiones"**, nunca "determinística". El desenlace del caso A
depende de una carrera entre la secuencia in-process (escribir sobre el mapeo → `msync` →
`munmap`, sin syscalls de por medio) y el pipeline cross-thread del agente
(`agent/detector.py:265,400-406,769-778`). La batería no mide ese margen, así que la
afirmación fuerte no se puede sostener si la piden en sala.

Una vez que tengas los números, con esos valores se escribe el párrafo de interpretación
del §5.9.
