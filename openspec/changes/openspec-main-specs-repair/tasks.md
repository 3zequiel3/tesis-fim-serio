## 1. Re-medición desde cero

- [x] 1.1 Descartar la medición previa. Una revisión adversarial (`review-ledger.md`) demostró que sus cifras y su método estaban mal: 44/8 era incorrecto, los números base estaban desactualizados por un archive, y el razonamiento «no hay `RENAMED` ⇒ no hay renombres» es un non-sequitur.
- [x] 1.2 Construir un medidor que ordene los deltas por **fecha de commit en git**, no por el prefijo del directorio (7 archives comparten `2026-06-23`; los prefijos difieren de la fecha real hasta en 4 días).
- [x] 1.3 Detectar renombres hechos vía `MODIFIED` con header cambiado. **Por mapa explícito, no por umbral de similitud**: un falso renombre descarta en silencio un requisito genuinamente perdido.
- [x] 1.4 Modelar las fusiones de capability (`agent-baseline-merge` → `agent-baseline`, `agent-bootstrap-verification` → `agent-bootstrap`), cuyos requisitos son los que el conteo previo tomaba por «sobrevivientes» nativos.
- [x] 1.5 Detectar capabilities archivadas **sin main spec**, invisibles para cualquier verificación que itere sobre `openspec/specs/*`.
- [x] 1.6 Resultado: **48 requisitos perdidos en 9 capabilities** (42 en 7 specs existentes + 6 huérfanos en 2 sin main spec). `backend-event-consumer` **queda excluida**: sus 2 «pérdidas» son renombres y su spec está sana.

## 2. Reparación

- [x] 2.1 Reparar **por archivo, no por clase**: 6 capabilities están simultáneamente rotas de estructura y vaciadas de contenido, así que tratar las clases como disjuntas dejaría archivos verdes y destripados.
- [x] 2.2 Preservar los `# títulos` y `## Purpose` ya redactados; generar sólo los faltantes. Resultado: 21 títulos y 15 Purpose intactos; 20 y 26 generados.
- [x] 2.3 Recuperar cada requisito desde la **última** definición en el orden de git, con su texto histórico sin reescribir.
- [x] 2.4 Crear `agent-command-dispatch` (4 requisitos) y `agent-change-detection-integrity` (2), que nunca tuvieron main spec.
- [x] 2.5 Corregir el bug de captura del `Purpose`: sin frenar el lookahead en `### Requirement:`, en un archivo sin `## Requirements` el Purpose se tragaba los requisitos huérfanos y se re-emitían duplicados. Lo detectó `openspec validate`, no la verificación de contenido — porque nada se perdía, se duplicaba.

## 3. Verificación

- [x] 3.1 **Contenido byte a byte**, no conteo: cada bloque preexistente comparado antes/después. Resultado `content_check: OK`.
- [x] 3.2 Ningún requisito preexistente desaparecido, verificado contra `git HEAD` archivo por archivo.
- [x] 3.3 Sin requisitos duplicados dentro de ningún archivo.
- [x] 3.4 Re-medición posterior: cero faltantes, cero capabilities sin main spec, cero specs estructuralmente rotas.
- [x] 3.5 `openspec validate --specs` → **43 passed, 0 failed**. Antes: 12 passed, 29 failed.

## 4. Guarda de regresión

- [x] 4.1 `scripts/check_spec_integrity.py` — sin dependencias, invocable antes de cualquier `openspec archive`. Le da a la guarda una casa y un punto de enforcement fuera del CLI, que es necesario porque al menos un archive dañino (`5355465`) fue **escrito a mano** sin invocar el CLI.
- [x] 4.2 Tres invariantes, todas **por archivo**: sin encabezados de delta (anclados a `^##`), estructura completa, y ningún requisito por debajo de lo que aportaron sus deltas.
- [x] 4.3 Wrapper de pytest en `backend/tests/test_openspec_artifact_integrity.py`.
- [x] 4.4 Verificada **en verde y en rojo**: borrar un requisito de `agent-core` la hace fallar nombrándolo; restaurarlo la devuelve a verde. Una guarda que nunca se vio fallar no es evidencia de nada.

## 5. Divergencias spec ↔ código

- [x] 5.1 Reportar en `divergences-spec-code.md`, **sin corregir**: editar el texto recuperado sería inventar contenido normativo dentro de una reparación estructural.
- [x] 5.2 Caso confirmado documentado: `agent-fanotify-detector` recupera un `MUST NOT usar FAN_REPORT_DFID_NAME` que `agent/_fanotify.py:132` viola, y exige `pyfanotify 0.3.0`, que dejó de ser dependencia en `f1e8681`.
- [x] 5.3 Declarar la limitación del escaneo automático: **no detectó ese caso**. Lo encontró una lectura adversarial. No es cobertura.

## 6. Pendientes que este change NO resuelve

- [x] 6.1 **Reconciliar spec ↔ código** en las 9 capabilities reparadas. **RESUELTO** — barrido de los 60 requisitos por clase de afirmación verificable (14 prohibiciones, 6 citas de librería, 9 módulos, 28 paths). Una sola divergencia real: el clúster fanotify en 4 requisitos. Cerrada con **D46/RN-140**, más la corrección de RN-01, RN-110, el stack de `arquitectura_stack.md`, `CLAUDE.md` y `openspec/config.yaml`. Detalle y verificación en `divergences-spec-code.md`.

> **El requisito viejo no estaba desactualizado: era irrealizable.** Exigía `FAN_CREATE`/`FAN_DELETE`/`FAN_MOVED_*` sobre una marca de filesystem **y** prohibía `FAN_REPORT_DFID_NAME` — pero el modo fd clásico no entrega esos eventos, el kernel responde `EINVAL`. Manda el código porque la spec pedía algo imposible, no por antigüedad.

- [x] 6.5 Registrar la asimetría que explica el desalineamiento: el reemplazo de `pyfanotify` **sí se documentó** en `docs/operations.md` y `docs/valores_planillas_cap5.md` cuando ocurrió. No se actualizaron las reglas ni las specs — y las specs del agente estaban vaciadas, así que la contradicción era invisible para el tooling. El daño estructural no sólo escondía requisitos: escondía **contradicciones entre lo especificado y lo construido**.
- [ ] 6.2 **Revisar si el capítulo de arquitectura de la tesis cita estas specs** como evidencia del contrato del agente. Hasta hoy esas citas apuntaban a archivos vaciados.
- [ ] 6.3 **Correr la guarda antes de archivar cada uno de los changes pendientes.** Hay changes sin archivar que apuntan a `agent-fanotify-detector` y `agent-baseline`, las dos capabilities más destruidas: la recurrencia está agendada, no es hipotética.
- [ ] 6.4 **Decidir sobre la causa raíz.** El CLI actual (1.4.1) archiva correctamente — lo demuestra la spec bien formada que generó el 2026-08-24. El daño histórico incluye archives escritos a mano, que ningún arreglo del CLI habría evitado. Falta una regla de proceso que lo prohíba explícitamente.
