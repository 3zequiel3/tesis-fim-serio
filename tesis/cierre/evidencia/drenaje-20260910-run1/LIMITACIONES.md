# Limitaciones de Run 1

Run 1 alcanzó el timeout de 300 s con 1.808/3.000 eventos persistidos, 1.192
archivos aún en cola y 0 rechazos. Ese resultado agregado se conserva.

Los timestamps por evento de `metrics.jsonl` fueron sobrescritos cuando el
publisher reintentó el mismo `event_id`; por ello los percentiles por etapa de
`summary.json` contienen intervalos negativos y **no son evidencia válida**.
El defecto pertenece al primer harness de observación, no al protocolo. Run 2
lo corrigió con timestamps de primera observación y contadores de reentrega.

Además, `summary.json.started_at_utc` fue escrito al finalizar pese al nombre.
Las duraciones agregadas usan `time.perf_counter_ns` y no dependen de ese campo.
