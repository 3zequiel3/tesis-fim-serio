## Why

Los archives de OpenSpec vinieron **destruyendo contenido normativo en silencio**, y el tooling reportó verde todo el tiempo.

Dos defectos, una causa común: varios archives crearon la main spec **copiando el archivo delta verbatim** en lugar de mergearlo sobre la estructura de main spec.

### Defecto 1 — truncamiento estructural (29 specs, 110 requisitos invisibles)

Un encabezado de delta (`## ADDED Requirements`) dentro de una main spec **trunca la sección `## Requirements`**: el parser deja de ver todo lo que sigue. `openspec validate --specs` reportaba **29 de 41 specs inválidas**.

Un `validate` en verde sobre una spec truncada no dice «esto está bien»: dice «no vi nada». Y `openspec archive` **aborta** al toparse con una — no es hipotético: así abortó el primer intento de archivar `n8n-contract-and-config`, que sólo pudo cerrarse tras reparar `backend-core` e `infra-compose` a mano.

### Defecto 2 — pérdida de requisitos (9 capabilities, 48 requisitos borrados)

Más grave. Cuando el delta se copió encima del archivo entero, **los requisitos que el delta no mencionaba desaparecieron**:

| Capability | Sobrevivían | **Perdidos** |
|---|---:|---:|
| `agent-core` | 2 | **9** |
| `agent-fanotify-detector` | 2 | **9** |
| `agent-baseline` | 1 | **8** |
| `agent-config-commands` | 1 | **5** |
| `agent-decision-engine` | 2 | **5** |
| `agent-bootstrap` | 3 | **4** |
| `agent-journal-integrity` | 1 | **2** |
| `agent-command-dispatch` | **sin main spec** | **4** |
| `agent-change-detection-integrity` | **sin main spec** | **2** |

Las dos últimas son la peor clase de daño: capabilities archivadas cuya main spec **nunca existió**,
con sus requisitos huérfanos en el archivo y sin destino.

**Corrección importante sobre el método de verificación.** Una versión previa de este documento
argumentaba «no existe ningún `## RENAMED Requirements` ⇒ son borrados y no renombres». Ese
razonamiento es inválido y una revisión adversarial lo desarmó: **los renombres se hicieron vía
`MODIFIED` con el header cambiado**, sin usar nunca el encabezado `RENAMED`. `backend-event-consumer`
parecía haber perdido 2 requisitos y en realidad los renombró — **su spec estaba sana** y quedó
excluida de la reparación de contenido. Tampoco existe un solo bloque `## REMOVED Requirements` en
todo el archivo, así que no había nada que descontar. Trazado hasta el commit culpable en al menos un caso: `agent-core/spec.md` pasó de 9 requisitos a 2 en `5355465` (`fix(agent): resolve 7 stability bugs (C27)`).

**El código sí implementa lo que se perdió** — por ejemplo `agent/baseline.py` implementa el cifrado AES-256-GCM y la derivación HKDF cuyos requisitos ya no figuran en `agent-baseline`. Lo destruido es el **registro especificado**, no el comportamiento. Para una tesis cuyo capítulo de arquitectura se apoya en estos artefactos, eso importa: hoy las specs del agente documentan una fracción de lo que el agente hace.

Los requisitos perdidos son **recuperables**: viven en los deltas bajo `openspec/changes/archive/*/specs/<cap>/spec.md`.

## What Changes

- **Recuperar los 48 requisitos borrados** desde los deltas archivados, aplicándolos en el orden en que **entraron al repositorio según git** — no por el prefijo `YYYY-MM-DD` del directorio, que difiere de la fecha real de commit hasta en 4 días y que siete archives comparten, de modo que no induce un orden total.
- **Crear las dos main specs que nunca existieron** (`agent-command-dispatch`, `agent-change-detection-integrity`) con sus 6 requisitos huérfanos.
- **Reparar la estructura de las 29 specs afectadas**. Las clases de daño **se solapan**: 6 capabilities están simultáneamente entre las estructuralmente rotas y entre las que perdieron contenido, así que la reparación es **por archivo**, no por clase.
- **Preservar todo lo ya redactado**: los `# títulos` y los `## Purpose` escritos a mano no se pisan. 21 títulos y 15 Purpose sobrevivieron intactos; sólo se generaron los faltantes.
- **Verificación de CONTENIDO, no de conteo.** Cada bloque preexistente se compara byte a byte antes y después; el conteo de headers no detecta ni la pérdida de escenarios ni la restauración de la versión equivocada.
- **Guarda de regresión** en `scripts/check_spec_integrity.py`, invocable sin dependencias antes de cualquier `openspec archive`, más un wrapper de pytest. Verifica tres invariantes por archivo: sin encabezados de delta, estructura completa, y ningún requisito por debajo de lo que sus deltas archivados aportaron.

**Fuera de alcance**: redactar requisitos nuevos, corregir la redacción de los recuperados, o completar los `## Purpose` con texto de diseño. Se recupera lo que existió; no se inventa. Las divergencias entre un requisito recuperado y el código actual se **reportan** en `divergences-spec-code.md`, no se corrigen acá.

## Capabilities

### New Capabilities
- `openspec-artifact-integrity`: la invariante estructural de las main specs, la regla de que ningún archive puede reducir el conjunto de requisitos sin un `REMOVED` explícito, y la guarda automática que verifica ambas.

### Modified Capabilities
Ninguna en el sentido normativo: este change **no cambia lo que el sistema debe hacer**. Restituye requisitos que fueron aprobados y archivados en su momento y que un archive defectuoso borró. Las capabilities cuyo archivo se toca —`agent-core`, `agent-baseline`, `agent-fanotify-detector`, `agent-config-commands`, `agent-decision-engine`, `agent-bootstrap`, `agent-journal-integrity`, `backend-event-consumer` y las 21 con daño sólo estructural— recuperan su contenido histórico, no reciben contenido nuevo.

## Impact

**Artefactos**: 41 archivos modificados y 2 creados bajo `openspec/specs/`. De 29 specs inválidas y 244 requisitos con 48 perdidos, se pasa a **43 specs válidas y 244 requisitos, cero perdidos**.

**Código**: `scripts/check_spec_integrity.py` (nuevo, sin dependencias) y `backend/tests/test_openspec_artifact_integrity.py`. El change **sí agrega código ejecutable** — la guarda—, aunque no toca código de producción.

**Sin impacto**: backend, agente, frontend, base de datos, API, despliegue.

**Riesgo asumido y reportado**: la restitución fiel del texto histórico revive requisitos que el código abandonó después. Hay **un caso confirmado**: `agent-fanotify-detector` recupera un `MUST NOT usar FAN_REPORT_DFID_NAME` que `agent/_fanotify.py:132` viola directamente, porque `f1e8681` reemplazó pyfanotify por un backend ctypes. Se documenta en `divergences-spec-code.md` en vez de editarse: cambiar el texto sería inventar contenido normativo dentro de una reparación estructural.

**Limitación declarada**: el escaneo automático de divergencias **no detectó ese caso** — lo encontró una lectura adversarial. No debe tratarse como cobertura; puede haber más entre los 48 recuperados.

**Hallazgo a escalar**: si el capítulo de arquitectura de la tesis cita estas specs como evidencia del contrato del agente, las citas apuntaban hasta hoy a archivos vaciados.
