## ADDED Requirements

### Requirement: Estructura canónica de una main spec

Todo archivo `openspec/specs/<capability>/spec.md` SHALL tener la estructura de una main spec: un título de nivel 1, una sección `## Purpose` y una sección `## Requirements` que contenga **todos** los requisitos del archivo.

Un archivo de main spec SHALL NOT contener encabezados de delta (`## ADDED Requirements`, `## MODIFIED Requirements`, `## REMOVED Requirements`, `## RENAMED Requirements`). Esos encabezados sólo son válidos dentro de `openspec/changes/<name>/specs/<capability>/spec.md`.

El motivo no es de estilo: un encabezado de delta dentro de una main spec **trunca la sección `## Requirements`**, y el parser deja de ver todo lo que sigue. El archivo queda pasando por válido mientras su contenido normativo es invisible para `validate`, `list` y `archive`.

#### Scenario: Main spec bien formada
- **WHEN** se inspecciona cualquier archivo bajo `openspec/specs/*/spec.md`
- **THEN** empieza con un título de nivel 1 que nombra la capability
- **AND** contiene una sección `## Purpose`
- **AND** contiene una sección `## Requirements`
- **AND** todos sus `### Requirement:` están dentro de esa sección

#### Scenario: Encabezado de delta en una main spec
- **WHEN** un archivo bajo `openspec/specs/*/spec.md` contiene `## ADDED Requirements`
- **THEN** la guarda de integridad falla nombrando el archivo y el encabezado encontrado

#### Scenario: Requisitos fuera de la sección Requirements
- **WHEN** un archivo de main spec tiene un `### Requirement:` que no está dentro de `## Requirements`
- **THEN** la guarda de integridad falla nombrando el archivo y el requisito huérfano

---

### Requirement: Un archive no puede reducir el conjunto de requisitos sin un REMOVED explícito

El conjunto de requisitos de una main spec SHALL incluir todo requisito que sus deltas archivados hayan agregado y que no haya sido eliminado mediante un bloque `## REMOVED Requirements` explícito ni renombrado mediante `## RENAMED Requirements`.

Esta invariante existe porque el daño observado no fue estructural sino de **contenido**: al copiar un delta encima del archivo entero, los requisitos que el delta no mencionaba desaparecieron. Se midieron **44 requisitos borrados en 8 capabilities** — `agent-core` conservaba 2 de 11, `agent-fanotify-detector` 2 de 11, `agent-baseline` 1 de 9 — sin que ninguna herramienta lo señalara.

Un archive que reduce el corpus sin declararlo SHALL considerarse un defecto, no una simplificación.

#### Scenario: Requisito presente en un delta archivado y ausente de la main spec
- **WHEN** un delta bajo `openspec/changes/archive/*/specs/<cap>/spec.md` agregó un requisito
- **AND** ese requisito no aparece en `openspec/specs/<cap>/spec.md`
- **AND** ningún delta archivado lo eliminó bajo `## REMOVED Requirements`
- **THEN** la guarda de integridad falla nombrando la capability y el requisito faltante

#### Scenario: Eliminación declarada no dispara falla
- **WHEN** un delta archivado eliminó un requisito bajo `## REMOVED Requirements`
- **THEN** su ausencia de la main spec es correcta y la guarda no falla

#### Scenario: La verificación es por archivo, nunca agregada
- **WHEN** una capability pierde 3 requisitos y otra gana 3
- **THEN** la guarda falla por la capability que perdió
- **AND** no compensa una pérdida con una ganancia de otro archivo

---

### Requirement: La reparación preserva el texto histórico de los requisitos

Un requisito recuperado desde un delta archivado SHALL restituirse con su texto original, sin reescritura ni mejora de redacción. La reconstrucción SHALL aplicar los deltas de una capability en **orden cronológico de archive** (el prefijo `YYYY-MM-DD` del directorio), de modo que un `MODIFIED` posterior prevalezca sobre la versión previa del mismo requisito.

La unión de todos los requisitos vistos alguna vez SHALL usarse como **verificación** de completitud, nunca como método de reconstrucción: resucitaría requisitos legítimamente eliminados y restituiría versiones superadas.

#### Scenario: MODIFIED posterior gana
- **WHEN** un requisito fue agregado por un archive de junio y modificado por uno de agosto
- **THEN** la main spec reparada contiene la versión de agosto

#### Scenario: El texto no se reescribe
- **WHEN** se recupera un requisito desde su delta archivado
- **THEN** su texto en la main spec es idéntico al del delta de origen

---

### Requirement: El Purpose de una spec reparada declara su origen

Una spec cuyo `## Purpose` haya sido generado durante una reparación SHALL indicarlo explícitamente, nombrando el change de reparación y el motivo.

Un `## Purpose` SHALL NOT redactarse como si fuera una decisión de diseño original: un lector futuro no debe poder confundir texto de reparación con intención documentada en su momento.

#### Scenario: Purpose de reparación es identificable
- **WHEN** se lee el `## Purpose` de una spec reparada por este change
- **THEN** el texto indica que la estructura fue reparada y por qué change
- **AND** no afirma nada sobre el propósito de diseño de la capability
