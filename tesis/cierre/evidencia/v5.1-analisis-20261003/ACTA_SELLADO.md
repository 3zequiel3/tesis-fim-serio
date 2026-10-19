# Acta de sellado

- Paquete: `v5.1-analisis-20261003/`
- Generación: 3 de octubre de 2026; versionado en los commits `4ed2aa4` y `a012aff`.
- Sellado: 18 de octubre de 2026, por Nicolás Castro, en un commit firmado posterior a la etiqueta `entrega-tesis`.

## Verificación previa

1. El contenido del paquete en `entrega-tesis` es idéntico al del commit `a012aff`, el último que lo modificó (`git diff --quiet a012aff entrega-tesis -- <paquete>`).
2. Sus 9 archivos originales coinciden con el SHA-256 que consigna la Tabla 37 de la tesis (Anexo L.5), y no había archivos adicionales.

## Archivos agregados en el sellado

Para cumplir P-8 (Anexo F.3), el sellado agrega el recálculo del drenaje de la Tabla 21, sin modificar los 9 archivos originales:

- `recalculo_drenaje.py`: copia idéntica de `scripts/recalculo_drenaje.py` (commit `15f4c72`).
- `recalculo_drenaje_salida.txt`: su salida para las tres repeticiones con t0 tomado de la marca de la línea `FIN_CORTE` (drenaje de 27,000, 25,334 y 26,392 s) y, para run-01, con t0 tomado del campo `t=` (27,006 s).

## Manifiesto

`SHA256SUMS` lista el SHA-256 de todos los archivos del paquete, incluida esta acta, salvo el propio manifiesto. Se generó con:

    find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs sha256sum > SHA256SUMS

y se verifica con `sha256sum -c SHA256SUMS`. El sellado es posterior a la generación: entre el 3 y el 18 de octubre, la integridad de los archivos originales la garantizan los commits `4ed2aa4` y `a012aff`; desde el sellado, también el manifiesto.
