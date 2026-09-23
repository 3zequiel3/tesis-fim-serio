# Custodia del paquete

## Qué certifica el sello

`SHA256SUMS` cubre los **51 archivos tal como están almacenados en este paquete**, incluidas las
trazas causales en su forma comprimida. Verificar es directo, sin pasos previos:

```bash
cd tesis/cierre/evidencia/v2-eval-20260923T215624Z
sha256sum -c SHA256SUMS
```

Las 51 líneas deben reportar `OK`.

## Las trazas están comprimidas

```
resiliencia/run-01/traza_run-01.jsonl.gz
resiliencia/run-02/traza_run-02.jsonl.gz
resiliencia/run-03/traza_run-03.jsonl.gz
```

Ocupaban unos 89 MB cada una sin comprimir y ocupan unos 15 MB comprimidas. La compresión es **sin
pérdida**: `gunzip -k` devuelve un archivo idéntico bit a bit al que produjo el agente.

Las tres tienen **hash distinto** y cada una comienza dentro de la ventana de su propia repetición.
Eso no es un detalle menor: en el paquete del candidato anterior las tres eran el mismo archivo
copiado tres veces, y el acta de aquel defecto está en
`../v2-eval-20260922T175053Z/resiliencia/MOTIVO_TRAZAS_INVALIDAS.md`.

## El sello se regeneró una vez, y conviene saber por qué

El sello original de esta corrida cubría 46 archivos. Se regeneró el 2026-09-23 al incorporar tres
artefactos que faltaban o estaban mal:

1. `latencia/atribucion_sin_evento.csv` — la atribución de las 16 operaciones sin evento, producida
   por `scripts/atribuir_operaciones_sin_evento.py`.
2. `control/bateria7_latencias.csv` y `control/pareado.csv` — la atribución del grupo de control y la
   tabla pareada de la inferencia.
3. `suites/` — reemplazado por completo. Los artefactos que este paquete traía correspondían al
   candidato **`v1.0-tesis`**, no a este, porque `scripts/correr_suites_candidato.sh` tenía el
   candidato y el directorio de salida escritos a mano. El script ahora los toma como parámetros y
   estos artefactos salen de una corrida propia de `v3.0-tesis`.

Ninguno de los archivos de medición originales fue alterado: la regeneración incorporó artefactos,
no reescribió datos.

## Una advertencia que este proyecto aprendió a los golpes

Un sello prueba que **nadie alteró los archivos después de sellarlos**. No prueba que los archivos
sean los que corresponden. Un paquete anterior verificó 46 de 46 y aun así contenía tres trazas
ajenas y las suites de otro candidato.

Integridad no es pertinencia, y ninguna suma de verificación distingue un archivo legítimo de un
archivo legítimo pero ajeno. Por eso el arnés verifica ahora la procedencia de lo que archiva, además
de sellarlo.
