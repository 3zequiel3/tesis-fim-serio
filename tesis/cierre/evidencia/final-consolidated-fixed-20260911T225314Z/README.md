# Validación consolidada del candidato corregido

- **Commit temporal inmutable:** `7df4935f769a2e393a5e6a6330df605c77592e52`
- **Resultado de las suites:** **PASS**. Control ambiental: advertencia; los dos intentos US-02/20/31 eliminaron todos sus recursos, pero detectaron que el inventario del stack principal externo cambió durante cada corrida.
- **Linaje:** todos los resultados pertenecen exclusivamente a este commit; no se agregan con resultados históricos.

## Resultados

| Componente | Resultado | Cobertura |
|---|---:|---:|
| Agente | 507 aprobadas, 0 fallidas, 1 omitida (508 total) | 78,93 % de líneas (2638/3342), excluyendo `agent/tests/*` |
| Backend | 599 aprobadas, 0 fallidas, 0 omitidas | 90,69 % de líneas (2737/3018), alcance `backend/app` |
| Frontend | 128 aprobadas, 0 fallidas (29 archivos) | líneas/statements 57,97 % (1995/3441); funciones 55,55 % (105/189); branches 76,00 % (396/521) |
| Typecheck frontend | PASS | no aplica |
| Build frontend | PASS | no aplica |
| E2E US-02/20/31 | PASS | 17 ejecuciones entre casos individuales y corridas repetidas |
| E2E US-03/16/17/25 | PASS | 9 ejecuciones entre casos individuales y corridas repetidas |
| Integridad OpenSpec | PASS | 44 specs y 249 requisitos |

Los casos repetidos acreditan estabilidad dirigida; no se suman a las suites unitarias ni se reinterpretan como historias adicionales. No se definió ni se infirió un umbral para la cobertura frontend.

## Comparación con la corrida fallida anterior

La evidencia histórica `final-consolidated-20260911T214511Z/` permanece intacta y ligada al commit temporal `6e81ccf95f8da644b74b41a499d3414a08248e06`.

- Agente: de 505 aprobadas, 2 fallidas y 1 omitida a 507 aprobadas, 0 fallidas y 1 omitida.
- Backend: de 590 aprobadas y 8 fallidas a 599 aprobadas y 0 fallidas. El denominador creció en una prueba.
- Frontend: conserva 128/128 y ahora aporta cobertura V8 propia.
- OpenSpec: ahora acredita explícitamente 44 specs y 249 requisitos.

## Trazabilidad y límites

- `metadata/` contiene identidad, estado limpio, inventario, exclusiones, versiones y cleanup.
- `junit/` contiene XML parseable por componente.
- `coverage/` contiene XML/JSON Python y `coverage-summary.json`, `coverage-final.json`, `lcov.info` y reporte LCOV frontend.
- `sbom/` contiene lockfiles, requisitos e inventarios instalados. No se afirma un SBOM certificado CycloneDX/SPDX porque no había un generador instalado.
- `e2e-*/` contiene recibos sanitizados y checksums de cada laboratorio aislado.
- `SHA256SUMS` sella el paquete completo.

Las suites aportan la evidencia necesaria para cerrar A-1 dentro del alcance ejecutado y M-5 para la identidad exacta de este candidato. Se conserva como advertencia que el control `main_stack_unchanged` de US-02/20/31 fue `false` en dos intentos, aunque ambos tuvieron exit 0 y cero recursos residuales; no se atribuye una causa sin evidencia. No acredita multianfitrión, TLS de Valkey, concurrencia de clientes, repetición estadística de drenaje ni criterios de historias no incluidos en estos laboratorios.

## Corrección de cadena de custodia

El commit temporal `7df4935f769a2e393a5e6a6330df605c77592e52` **no pertenece al repositorio Git original**. Fue creado en el repositorio temporal usado para congelar la corrida. La verificación que lo buscaba en la base de objetos original estaba, por lo tanto, consultando el repositorio equivocado.

La identidad autocontenida queda preservada en:

- `custody/candidate.bundle`: bundle Git que contiene el commit y la referencia `refs/heads/evidence-candidate`.
- `custody/candidate-tree.tar.gz`: archive determinista del mismo árbol, con prefijo `candidate/`.

Identidades verificadas:

- commit: `7df4935f769a2e393a5e6a6330df605c77592e52`;
- tree: `95455f919ec602b6cddf1440341652d99b784bd3`;
- bundle SHA-256: `3b26d3301d5ad7def9ecb2723a71b73d88855e8250aa253e6657539b3a050a9c`;
- archive SHA-256: `1d3e8e731b6d802f7a0e5549a5f5ddd843dbd1a656ced735a3696311c3dc2f26`.

Se verificó desde cero el bundle, se clonó sin depender de la base de objetos original, se resolvió el commit, se obtuvo el mismo tree, el checkout quedó limpio y los 813 archivos coincidieron byte a byte con `metadata/candidate-files.sha256`. El archive reprodujo los mismos 813 archivos y su regeneración desde el commit produjo bytes idénticos. Esta corrección amplía la custodia; no cambia ni repite resultados de prueba.
