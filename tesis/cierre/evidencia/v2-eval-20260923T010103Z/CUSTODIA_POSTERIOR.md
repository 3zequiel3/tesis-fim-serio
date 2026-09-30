# Custodia posterior al sellado — paquete v2-eval-20260923T010103Z (candidato v3.0-tesis)

## Qué pasó

El manifiesto original, `SHA256SUMS`, se generó en el commit `df9ed0d` (2026-09-23 14:58:56 -03:00)
y cubre 51 archivos. Después del sellado, `RESULTADOS.md` se editó en el commit `1f28c9e`
(2026-09-23 15:50:25 -03:00) para corregir la causa atribuida a dos fallas de la suite del backend
(sección 5 del documento). Ningún otro archivo del paquete cambió.

Por eso `sha256sum -c SHA256SUMS` verifica 50 de 51 archivos: falla solo `RESULTADOS.md`.

El manifiesto original **no se modifica**, para conservar el registro del sellado.

## Hashes de RESULTADOS.md

| Versión | Commit | SHA-256 |
|---|---|---|
| Sellada | df9ed0d | `3c20a06a7fc3184daf72e3859202f58ffe0079abb783b762c7ba3d6ef960e789` |
| Posterior a la edición | 1f28c9e | `befa005c3e071a76a29cef38f736292d90a9a1bb7b08a1b9132b5f2847b7bff6` |

La versión sellada puede recuperarse con:

    git show df9ed0d:tesis/cierre/evidencia/v2-eval-20260923T010103Z/RESULTADOS.md

## Manifiesto posterior

`SHA256SUMS.post-edicion` recalcula los mismos 51 archivos, en el mismo orden, con el estado actual
del paquete. Verificación:

    cd tesis/cierre/evidencia/v2-eval-20260923T010103Z && sha256sum -c SHA256SUMS.post-edicion

Resultado esperado: 51 de 51.

SHA-256 del manifiesto original (`SHA256SUMS`):
`e61b1a2db2b0c40d9af8cc00e0d802965dfde23f2df1c4ff490d3d2b345ef3f9`

## Nota sobre la sección 6 de RESULTADOS.md

La sección 6 declara abierta la contabilidad causal de las operaciones no encoladas. Esa
contabilidad se cerró después, sin modificar este paquete, con `scripts/atribuir_resiliencia.py`;
los resultados están en `tesis/cierre/evidencia/atribucion-resiliencia/v3.0-tesis/`.
