## 1. Guarda de regresión (primero, en rojo)

- [ ] 1.1 Escribir el helper que, dada una capability, recorre sus deltas bajo `openspec/changes/archive/*/specs/<cap>/spec.md` en orden cronológico y devuelve el conjunto esperado de requisitos aplicando `ADDED` / `MODIFIED` / `REMOVED` / `RENAMED`.
- [ ] 1.2 Test de invariante estructural: ninguna `openspec/specs/*/spec.md` contiene encabezados de delta; todas tienen título, `## Purpose` y `## Requirements`; ningún `### Requirement:` queda fuera de esa sección.
- [ ] 1.3 Test de invariante de completitud: el conjunto de requisitos de cada main spec incluye todo lo que sus deltas agregaron y no removieron explícitamente. **La aserción es por archivo** — nunca un total agregado, que dejaría que una pérdida se cancele con una ganancia ajena.
- [ ] 1.4 Confirmar que ambos tests **fallan hoy**, y que el mensaje nombra archivo y requisito. Un test de reparación escrito después de reparar no prueba nada.

## 2. Caso simple — 21 specs (transform mecánico)

- [ ] 2.1 Aplicar a las 21 con un único `## ADDED Requirements` y sin `## Requirements`: título `# <cap> Specification`, bloque `## Purpose` que declare el origen de reparación (D-4), y `## ADDED Requirements` → `## Requirements`.
- [ ] 2.2 Verificar por archivo que el conteo de `### Requirement:` es idéntico antes y después. El contenido no se toca en esta clase.
- [ ] 2.3 Revisar el diff completo antes de commitear. Que `validate` pase no es evidencia de que no se perdió contenido.
- [ ] 2.4 Commit único para esta clase.

## 3. Sin sección Requirements — 7 specs

- [ ] 3.1 Reparar `agent-cert-renewal`, `agent-transport`, `backend-agents`, `frontend-auth`, `frontend-events`, `frontend-scaffold`, `frontend-shell`: insertar `## Requirements` en la posición correcta sin alterar el orden ni el texto de los requisitos.
- [ ] 3.2 Tres de ellas (`backend-async-consumer`, `backend-heartbeat-hmac`, `frontend-events`) ya tienen `## Purpose` — no sobreescribirlo.
- [ ] 3.3 Verificar conteo por archivo y revisar el diff.
- [ ] 3.4 Commit único para esta clase.

## 4. Recuperación de requisitos borrados — 8 capabilities, un commit cada una

- [ ] 4.1 `agent-core` — recuperar 9 (conserva 2 de 11).
- [ ] 4.2 `agent-fanotify-detector` — recuperar 9 (conserva 2 de 11).
- [ ] 4.3 `agent-baseline` — recuperar 8 (conserva 1 de 9).
- [ ] 4.4 `agent-config-commands` — recuperar 5 (conserva 1 de 6).
- [ ] 4.5 `agent-decision-engine` — recuperar 5 y reconstruir el merge de los tres archives que la tocaron. Es la única con `## MODIFIED Requirements` y sin título. **Si aparece una ambigüedad genuina entre dos deltas, detenerse y preguntar** en vez de elegir una interpretación.
- [ ] 4.6 `agent-bootstrap` — recuperar 4 (conserva 3 de 7).
- [ ] 4.7 `agent-journal-integrity` — recuperar 2 (conserva 1 de 3).
- [ ] 4.8 `backend-event-consumer` — recuperar 2 (conserva 12 de 14).
- [ ] 4.9 En cada una: aplicar los deltas en orden cronológico (D-1), texto histórico sin reescribir (D-4 de la spec), y revisar el diff a mano antes de commitear.

## 5. Cierre y verificación

- [ ] 5.1 `openspec validate --specs` pasa las 40. Hoy: 9 passed, 31 failed.
- [ ] 5.2 La guarda de regresión del grupo 1 pasa en verde.
- [ ] 5.3 Verificar que un `openspec archive` sobre un change que toque cualquiera de las 29 ya no aborta.
- [ ] 5.4 Registrar en el reporte final qué **no** se pudo recuperar: requisitos de changes nunca archivados o previos a OpenSpec no dejan rastro y no son recuperables. Declararlo, no simular un corpus completo.
- [ ] 5.5 Registrar como hallazgo aparte —sin corregirlo acá— cualquier requisito recuperado que ya no describa lo implementado. Reconciliar spec↔código es trabajo distinto.
- [ ] 5.6 Escalar la pregunta abierta 1 del design: si el capítulo de arquitectura de la tesis cita estas specs como evidencia del contrato del agente, hoy la cita apunta a archivos vaciados.
