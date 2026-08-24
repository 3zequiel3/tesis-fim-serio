## Why

Los archives de OpenSpec vinieron **destruyendo contenido normativo en silencio**, y el tooling reportó verde todo el tiempo.

Dos defectos, una causa común: varios archives crearon la main spec **copiando el archivo delta verbatim** en lugar de mergearlo sobre la estructura de main spec.

### Defecto 1 — truncamiento estructural (29 specs, 110 requisitos invisibles)

Un encabezado de delta (`## ADDED Requirements`) dentro de una main spec **trunca la sección `## Requirements`**: el parser deja de ver todo lo que sigue. `openspec validate --specs` reporta **31 de 40 specs inválidas**.

Un `validate` en verde sobre una spec truncada no dice «esto está bien»: dice «no vi nada». Y `openspec archive` **aborta** al toparse con una — no es hipotético: así abortó el primer intento de archivar `n8n-contract-and-config`, que sólo pudo cerrarse tras reparar `backend-core` e `infra-compose` a mano.

### Defecto 2 — pérdida de requisitos (8 capabilities, 44 requisitos borrados)

Más grave. Cuando el delta se copió encima del archivo entero, **los requisitos que el delta no mencionaba desaparecieron**:

| Capability | Sobreviven | **Perdidos** |
|---|---:|---:|
| `agent-core` | 2 | **9** |
| `agent-fanotify-detector` | 2 | **9** |
| `agent-baseline` | 1 | **8** |
| `agent-config-commands` | 1 | **5** |
| `agent-decision-engine` | 2 | **5** |
| `agent-bootstrap` | 3 | **4** |
| `agent-journal-integrity` | 1 | **2** |
| `backend-event-consumer` | 12 | **2** |

Verificado que son borrados y no renombres: **no existe un solo encabezado `## RENAMED Requirements`** en ningún delta archivado, y los `## REMOVED` explícitos se descontaron del cálculo. Trazado hasta el commit culpable en al menos un caso: `agent-core/spec.md` pasó de 9 requisitos a 2 en `5355465` (`fix(agent): resolve 7 stability bugs (C27)`).

**El código sí implementa lo que se perdió** — por ejemplo `agent/baseline.py` implementa el cifrado AES-256-GCM y la derivación HKDF cuyos requisitos ya no figuran en `agent-baseline`. Lo destruido es el **registro especificado**, no el comportamiento. Para una tesis cuyo capítulo de arquitectura se apoya en estos artefactos, eso importa: hoy las specs del agente documentan una fracción de lo que el agente hace.

Los requisitos perdidos son **recuperables**: viven en los deltas bajo `openspec/changes/archive/*/specs/<cap>/spec.md`.

## What Changes

- **Recuperar los 44 requisitos borrados** desde los deltas archivados, respetando el orden cronológico de los archives para que un `MODIFIED` posterior gane sobre la versión previa del mismo requisito.
- **Reparar la estructura de las 29 specs afectadas**, con tres tratamientos distintos porque hay tres clases de daño:
  - **21 specs — caso simple.** Un único `## ADDED Requirements` y ningún `## Requirements`. Renombre de encabezado más bloque `## Purpose`. Es el transform ya aplicado a `backend-core` (14 requisitos) e `infra-compose` (9).
  - **1 spec — `agent-decision-engine`.** Encabezado `## MODIFIED Requirements` y **sin título**. Requiere reconstruir el merge contra los tres changes archivados que la tocaron.
  - **7 specs — sin encabezado de delta y sin `## Requirements`.** `agent-cert-renewal`, `agent-transport`, `backend-agents`, `frontend-auth`, `frontend-events`, `frontend-scaffold`, `frontend-shell`. Requisitos huérfanos de sección.
- **Verificación por archivo del conteo de `### Requirement:`**, comparando contra la unión de los deltas archivados. Es la única defensa real: un archivo con la estructura arreglada y menos requisitos pasa `validate` igual de bien.
- **Guarda de regresión**: test que recorre `openspec/specs/*/spec.md` y falla si alguna contiene un encabezado de delta, carece de `## Requirements`, o tiene menos requisitos que la unión de sus deltas archivados menos los `REMOVED` explícitos. Sin ella el próximo archive mal hecho repite el daño.

**Fuera de alcance**: redactar requisitos nuevos, corregir la redacción de los recuperados, o completar los `## Purpose` con texto de diseño. Se recupera lo que existió; no se inventa.

## Capabilities

### New Capabilities
- `openspec-artifact-integrity`: la invariante estructural de las main specs, la regla de que ningún archive puede reducir el conjunto de requisitos sin un `REMOVED` explícito, y la guarda automática que verifica ambas.

### Modified Capabilities
Ninguna en el sentido normativo: este change **no cambia lo que el sistema debe hacer**. Restituye requisitos que fueron aprobados y archivados en su momento y que un archive defectuoso borró. Las capabilities cuyo archivo se toca —`agent-core`, `agent-baseline`, `agent-fanotify-detector`, `agent-config-commands`, `agent-decision-engine`, `agent-bootstrap`, `agent-journal-integrity`, `backend-event-consumer` y las 21 con daño sólo estructural— recuperan su contenido histórico, no reciben contenido nuevo.

## Impact

**Artefactos**: 29 archivos bajo `openspec/specs/*/spec.md`.

**Tests**: suite nueva de integridad de artefactos.

**Sin impacto**: código de producción, base de datos, API, despliegue. Este change no toca una línea ejecutable.

**Riesgo principal**: una recuperación mecánica puede restituir una versión **vieja** de un requisito que sí fue modificado legítimamente después. Se mitiga aplicando los deltas en orden cronológico de archive y revisando a mano las 8 capabilities con pérdida — no alcanza con que el validate pase.

**Riesgo secundario**: puede haber requisitos perdidos en changes que nunca se archivaron formalmente, o previos al uso de OpenSpec. Este change recupera lo que está en el archivo; lo que no dejó rastro no es recuperable y debe declararse como tal en vez de simularse completo.

**Hallazgo a escalar aparte**: conviene revisar si el capítulo de arquitectura de la tesis cita estas specs como evidencia del contrato del agente. Si lo hace, la cita apunta hoy a archivos vaciados.
