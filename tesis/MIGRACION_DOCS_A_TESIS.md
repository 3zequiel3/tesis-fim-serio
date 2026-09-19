# Separación del material de tesis en `tesis/`

**Fecha:** 19 de septiembre de 2026
**Motivo:** `docs/` pesaba 180 MB, de los cuales 179 eran material académico. La documentación del
código y del funcionamiento del proyecto —que es lo que `docs/` debería contener— ocupaba menos de un
megabyte. Esta migración separa las dos cosas antes de la fusión con `main`.

## Resultado

| Directorio | Antes | Después | Contenido |
|---|---|---|---|
| `docs/` | 180 MB | **832 KB** | Documentación del proyecto: arquitectura, reglas de negocio, historias de usuario, flujo de usuario, despliegue, operaciones, n8n, bugs de auditoría, planes de implementación, residuales |
| `tesis/` | — | **189 MB** | Todo el material académico y su evidencia |

## Qué se movió

| Origen | Destino |
|---|---|
| `docs/cierre/` | `tesis/cierre/` |
| `docs/informe/` | `tesis/informe/` |
| `docs/Tesis.pdf` | `tesis/Tesis.pdf` |
| `docs/plan_medicion_cap5.md` | `tesis/plan_medicion_cap5.md` |
| `docs/dataset_cap5.md` | `tesis/dataset_cap5.md` |
| `docs/valores_planillas_cap5.md` | `tesis/valores_planillas_cap5.md` |
| `docs/entrega_valores_cap5.md` | `tesis/entrega_valores_cap5.md` |
| `docs/defensa_guion_10min.md` | `tesis/defensa_guion_10min.md` |
| `docs/trazabilidad_us_tests.md` | `tesis/trazabilidad_us_tests.md` |
| `resultados/` | `tesis/resultados/` |

Los archivos rastreados se movieron con `git mv`, de modo que el historial de cada uno se conserva:
**195 renombres** quedan registrados como tales y no como borrado más alta. Los archivos no
rastreados o excluidos por `.gitignore` —los paquetes de evidencia recientes, los `.docx` de cada
versión, las auditorías— viajaron con el directorio.

## Referencias actualizadas

| Alcance | Referencias |
|---|---|
| Rutas `docs/...` reescritas a `tesis/...` | 55 en 22 archivos |
| Rutas `resultados/...` reescritas a `tesis/resultados/...` | 67 en 11 archivos |
| Reglas de `.gitignore` reapuntadas | 13 |

Entre las funcionales, que habrían roto algo de no corregirse: el montaje de evidencia del
`docker-compose.yml` (`./tesis/cierre/evidencia:/evidence`) y la ruta de salida de
`frontend/playwright.config.ts`.

La reescritura de `resultados/` usó un patrón que exige un separador previo, para no tocar la palabra
«resultados» en prosa. `.gitignore` conserva además una regla defensiva para un `resultados/` suelto
en la raíz, por si algún script con una ruta por defecto vieja vuelve a crearlo.

## Qué NO se tocó, y por qué

**`openspec/changes/archive/**`.** Los changes archivados son registros históricos: describen dónde
estaba cada cosa cuando se escribieron. Reescribirles las rutas falsearía el registro. Sus menciones
a `docs/cierre/...` se leen como lo que son, referencias a la estructura vigente en su momento.

**El material dentro de `tesis/`.** Las auditorías, los registros de cambios y los paquetes de
evidencia son documentos cerrados y sellados. Varios están cubiertos por `SHA256SUMS`: editarlos
invalidaría su verificación. Sus rutas internas quedan como fueron escritas.

## Lo que queda pendiente

**El documento de la tesis cita las rutas viejas.** La V14 tiene 67 menciones a `docs/cierre`, 8 a
`docs/trazabilidad_us_tests.md` y 3 a `resultados/entorno.txt`. Esas citas hay que reescribirlas **en
la misma versión** en la que se apliquen las correcciones pendientes, no por separado: mover las
carpetas y editar el texto en pasadas distintas es exactamente como quedan citas rotas.

El reemplazo es de prefijo y admite la misma verificación que se aplicó acá: que no sobreviva ninguna
ruta vieja y que cada ruta nueva resuelva a un archivo real.

**Las citas al código no cambian.** Las referencias a `backend/app/...`, `agent/...`,
`frontend/e2e/...` y `scripts/...` siguen siendo válidas: el código no se movió.

## Verificación aplicada

1. Ninguna ruta vieja sobrevive en archivos vivos: búsqueda sobre todos los archivos rastreados,
   excluyendo los archivos históricos, sin coincidencias.
2. Las seis rutas nuevas principales resuelven a un archivo o directorio existente.
3. `python3 scripts/check_spec_integrity.py` → `OK — 54 main specs, 385 requisitos, sin problemas`.
