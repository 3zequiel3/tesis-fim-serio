# Custodia de las trazas causales del agente

Las tres trazas causales de la batería de resiliencia se almacenan **comprimidas con gzip**:

```
resiliencia/run-01/traza_run-01.jsonl.gz
resiliencia/run-02/traza_run-02.jsonl.gz
resiliencia/run-03/traza_run-03.jsonl.gz
```

Ocupaban 89 MB cada una sin comprimir (267 MB en total) y ocupan 15 MB comprimidas (43 MB en
total). La compresión es **sin pérdida**: el archivo descomprimido es idéntico bit a bit al que
produjo el agente.

## El sello certifica el contenido sin comprimir

`SHA256SUMS` se generó al cerrar la medición, sobre los archivos **`.jsonl`**, antes de comprimir.
No se regeneró: el sello que acompaña al paquete es el mismo que se emitió en el momento de medir.

En consecuencia, `sha256sum -c SHA256SUMS` reporta las tres trazas como ausentes mientras estén
comprimidas. Eso es esperado y no indica alteración.

## Procedimiento de verificación

Descomprimir conservando el `.gz` y verificar el paquete completo:

```bash
cd tesis/cierre/evidencia/v2-eval-20260922T175053Z
gunzip -k resiliencia/run-0{1,2,3}/traza_run-0{1,2,3}.jsonl.gz
sha256sum -c SHA256SUMS
```

Las 46 líneas deben reportar `OK`. Si alguna de las tres trazas no coincide, el contenido fue
alterado después del sellado.

Para volver al estado almacenado, borrar los `.jsonl` descomprimidos y conservar los `.gz`.
