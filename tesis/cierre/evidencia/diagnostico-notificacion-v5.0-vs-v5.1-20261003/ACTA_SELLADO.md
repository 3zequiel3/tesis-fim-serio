# Acta de sellado

- Paquete: `diagnostico-notificacion-v5.0-vs-v5.1-20261003/`
- Generación: 3 de octubre de 2026; versionado en el commit `995bdc8`.
- Sellado: 18 de octubre de 2026, por Nicolás Castro, en un commit firmado posterior a la etiqueta `entrega-tesis`.

## Verificación previa

1. El contenido del paquete en `entrega-tesis` es idéntico al del commit `995bdc8` (`git diff --quiet 995bdc8 entrega-tesis -- <paquete>`).
2. Sus 2 archivos coinciden con el SHA-256 que consigna la Tabla 37 de la tesis (Anexo L.5), y no hay archivos adicionales.

## Manifiesto

`SHA256SUMS` lista el SHA-256 de todos los archivos del paquete, incluida esta acta, salvo el propio manifiesto. Se generó con:

    find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs sha256sum > SHA256SUMS

y se verifica con `sha256sum -c SHA256SUMS`. El sellado es posterior a la generación: entre el 3 y el 18 de octubre, la integridad la garantiza el commit `995bdc8`; desde el sellado, también el manifiesto.
