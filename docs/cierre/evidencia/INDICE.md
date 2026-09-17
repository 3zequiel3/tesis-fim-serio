# Índice de evidencia de cierre

> Corte 2026-09-09. Los hashes identifican los bytes locales indicados. Un hash prueba integridad, no suficiencia metodológica ni aptitud para publicación. Sanitizar datos sensibles antes de distribuir; toda copia sanitizada recibe un hash nuevo.

## Evidencia histórica original

Los archivos bajo `resultados/` están ignorados por Git y deben conservarse sin sobrescritura.

| Archivo | Uso | SHA-256 | Precaución |
|---|---|---|---|
| `resultados/entorno.txt` | Entorno/commit histórico | `3d9f689d0a63805d214545cb8968af7355788a25473fc13555ba1f4fae9bc915` | Revisar host/rutas. |
| `resultados/cronologia_utc.txt` | Cronología B3/B4/B5 | `5fdc3a37bdd728b97847c4e88f22ab2107694c5486482a21cda87947c0105cfc` | Revisar host. |
| `resultados/RESULTADOS.md` | Consolidado histórico | `f1e3bf528a24c4f759b2326190701036c35746cb0e57072975784a090cc8c1ed` | Conserva cifras históricas, incluso contradicciones. |
| `resultados/bateria2_agente.xml` | 418 tests agente | `0d92df5e768bcecfe32b50321737f86c31f9a6da47d32bc44a1d83e2299e311d` | Sanitizar host/rutas. |
| `resultados/bateria2_backend.xml` | 494 tests backend | `8de60bdeedc1415a4bed13aaa196cadfdab3f937d1628baeb6c3d5c72eeddba5` | Sanitizar host/rutas. |
| `resultados/bateria3_manifiesto.jsonl` | 500 operaciones B3 | `2f0641e2c18237cd29dde6a08a44bbe0ecf6658612cd1a0f305b080513155aaf` | Revisar paths. |
| `resultados/bateria3_latencias.csv` | 493 correlaciones B3 | `150015c56887cd8f1ac7ac2dc402de706912b71f988df252ba896f75c85609a3` | Revisar IDs. |
| `resultados/bateria4_todos.csv` | 329 muestras B4 | `2c7bae8e2e43f556f23e5a711ef799a9e46287b810c3e9b580bf3dec73dde732` | Revisar endpoints/IDs. |
| `resultados/bateria4_webhook.jsonl` | Receptor webhook B4 | `34d58a17f6a12f110f29a0309a9340c5ffe3ae52185ec8d1c65fa6b33172e03b` | Sanitizar payloads. |
| `resultados/bateria5_manifiesto.jsonl` | 3.000 operaciones B5 | `81cb339967b066a11bb03c1161fc2d00b9043711e206680f5bf90309ea0b1fbf` | Revisar paths. |
| `resultados/bateria55_valkey.pcap` | Tráfico Valkey histórico | `6834591e6c2686d6623439954706a5a49bc77decb99d1d74e46fc698f6da7e2d` | **No publicar sin sanitización**; contiene tráfico legible. |
| `resultados/bateria55_agente.strace` | Syscalls FID | `b7b3ece2e74a127a10118c41e9cccb112346b7486ebc8512ef4c39d1f504cbd4` | Revisar rutas/host. |
| `resultados/bateria8/bateria8_manifiesto.json` | Casos `mmap` | `b1ffe6f0a92aa463774d13ff083c60093845e846d4522f251b35f5bebdbc0629` | Revisar IDs. |
| `resultados/bateria8/bateria8_correlacion.csv` | 30 correlaciones `mmap` | `c27f39285852e5ad3ee5b12f209d0d4217739b61841a33e32cd50898e7fdc060` | Revisar rutas. |

`capinfos -c resultados/bateria55_valkey.pcap` devuelve 660 paquetes; `RESULTADOS.md` dice 662. Se conservan ambos datos y la discrepancia.

## Nuevas evaluaciones durables

| Evidencia | Evaluación | SHA-256 | Límite |
|---|---|---|---|
| `docs/cierre/evidencia/20260909-coverage-run3/README.md` | Metadatos y sanitización Run 3 | `c382723fedd5a48d53544f72df767be8c31432ed362e1dfbe79961a5d4e78cf7` | Explica identidad y transformación del JUnit. |
| `docs/cierre/evidencia/20260909-coverage-run3/SHA256SUMS` | Manifiesto del paquete Run 3 | `d1b7ac65814ed71e483c153a85167020534de8309174daecfa8c21ad76c8c25b` | Hash externo del manifiesto registrado en este índice. |
| `docs/cierre/evidencia/20260909-coverage-run3/coverage.json` | Coverage backend | `710687b7ae799ad8b3fb6a90545a68133fd5a773fcfcc6f6b6768f4c92ba0b66` | Snapshot anterior y mixto; branch off. |
| `docs/cierre/evidencia/20260909-coverage-run3/junit.xml` | 572 tests backend | `d4a2662c5342ea3afb153a94653ce05ee6885dad4a18b42e7e1ec8b3ca79964f` | Copia sanitizada; ver README. |
| `docs/cierre/evidencia/20260909-coverage-run3/source-manifest.sha256` | Identidad de fuentes Run 3 | `3df2104873f01b7db790968428eb8c4323c9274e362a4ae737da06d360c3a89c` | Identifica el snapshot, no HEAD posterior. |
| `n8n/e2e/evidence/20260909-run.json` | n8n unidad A controlada | `9a082de238b186aae44c67e36b833f39187fb8cd2edd974460fb11488e57adf4` | Un host; receptor sintético; este archivo corresponde sólo a A. |
| `n8n/e2e/evidence/20260910-durable-fallback.json` | n8n unidad B durable | `92150b5d57a1182ac65349719dd72d424f9cc9a1ecb504d0a0c79dd594370e7d` | PostgreSQL limpio; webhook controlado; delays 0 de ensayo; SMTP no ejecutado. |
| `backend/tests/test_mtls_transport.py` | Harness mTLS real | `5dd680916abc9cd16e7e46698985eac70fa37fa4a2be2f5bb62d1840e88c1638` | El resultado observado fue 1 PASS; el archivo no es por sí solo la salida de pytest. |
| `docs/cierre/evidencia/absence-20260910T052521Z-r2/RESULTADO.md` | Corrida causal B9 válida: 60 operaciones | `a84b750e8d409d7b45dbecd8c68746df8bcf4d741158d4056fea929d25349c86` | 50 correlaciones completas y 10 retornos a baseline descartados legítimamente; no prueba causalidad retrospectiva de B3/B5. |
| `docs/cierre/evidencia/absence-20260910T052521Z-r2/SHA256SUMS` | Integridad del paquete causal B9 | `0bff353aca996f06fd738d42a332246c396e990a546e5d05971cdab2e8b7f477` | Incluye operaciones, trace, export PostgreSQL, correlación y condiciones; revisar rutas locales antes de publicar. |
| `docs/cierre/evidencia/drenaje-20260910-run1/SHA256SUMS` | Primer perfil de drenaje; timeout a 300 s | `5e328280826b80a62c50cd1f5c118bd630a4c18b5eced87542617f7dfe435091` | 1.808/3.000 persistidos; percentiles por etapa inválidos por sobrescritura del primer harness, conservados y delimitados. |
| `docs/cierre/evidencia/drenaje-20260910-run2/SHA256SUMS` | Drenaje completo antes de optimizar | `12c3b9737afaadf74eaca1bbba215cb6f972bbdd43db4cee583aaf21686eb0a4` | 3.000/3.000 en 362,834 s; 5.682 publicaciones excedentes. Un host. |
| `docs/cierre/evidencia/drenaje-20260910-queue-index-profile/SHA256SUMS` | Comparación dirigida del índice de cola | `ac026d7d8a75ff15f18baba3f017026c9ee6fd7d0d838b3385542c9b81f7ad25` | Mismo proceso, filesystem y 3.000 payloads; excluye Valkey/PostgreSQL. |
| `docs/cierre/evidencia/drenaje-20260910-run3/SHA256SUMS` | Drenaje después de índice O(1) y ACK concurrente | `7058e7b7d7ba3166a86e000bbc69eed2ff2d60f3dd90aff3f4e2c40f0da3d635` | 3.000/3.000 en 51,773 s; 0 rechazos y 0 duplicados; **NO CUMPLE** `<30 s`. Un host. |
| `docs/cierre/evidencia/drenaje-20260910-run4-unit1/SHA256SUMS` | Drenaje después de backend Unidad 1 | `e77050a081c0ae8404a977fc3e0eee5ecce7d6aa3f604e9c5db6e89837130984` | 3.000/3.000 en 29,146 s (102,929 eventos/s); cadena completa, 0 rechazos/duplicados; **CUMPLE** `<30 s`. Un host; dos intentos inválidos preservados y excluidos. |

### Commits que fijan las nuevas implementaciones

| Unidad | Commit |
|---|---|
| US-09 | `8039624292a1f84d6136dd5ed2b2e59d9bdb6f9b` + `f08626a758899d7bb701b55025ebd13f29c17240` |
| mTLS | `28f87fe3d8183f506404aa1b4d166fabcbc64527` |
| n8n unidad A | `f0a2907f2b2d282ea39ff255290f9625744c4bbf` |
| n8n unidad B | `e2519ebee40a149fc2cfaabf8b67c2407eac4da9` |
| Evidencia n8n B | `3bec5841e92181047e4282453d085b7d944971c2` |
| Instrumentación causal B9 | `aae55e4aa0d79e2e053a3dc74b6a69560ae550b9` |
| Optimización de drenaje | `7c5afa5f429139ed6bffbf4d7bc0a7bc21d841ba` |
| Optimización backend de drenaje Unidad 1 | `965dcacc5c189f4a9808b063e32085d89e636803` |

## Operaciones históricas sin evento

- B3: 193, 196, 209, 270, 323, 364, 369.
- B5: 185, 276, 291, 380, 982, 1243, 1299, 1311, 1705, 1957, 2078, 2767.

Los manifiestos prueban que fueron operaciones efectivas sin evento correlacionado. No contienen la cadena kernel/baseline/decisión/cola necesaria para demostrar la causa.

## Límites y evidencia pendiente

| Marcador | Falta |
|---|---|
| 19 ausencias históricas | La corrida B9 validó el mecanismo actual de supresión al retornar a la baseline aprobada. Los 19 históricos son compatibles y están fuertemente sustentados por manifiestos/código, pero su causalidad runtime retrospectiva no puede probarse porque faltan trazas por etapa. |
| Drenaje | Run 4 midió 29,146 s y 102,929 eventos/s: **CUMPLE** `<30 s` bajo las condiciones documentadas. Una sola corrida no establece un SLA; 32,358 s era proyección, no medición. |
| Dos hosts | Manifiestos de ambos hosts, red real y TLS habilitado. |
| Cuarentena | Política y prueba de retención/cifrado o justificación de alcance. |
| Suites finales | JUnit agente/backend/frontend y coverage sobre un único commit congelado. |
| n8n SMTP | Receptor SMTP controlado si el canal se mantiene dentro del alcance; no fue ejecutado. |
| Reproducción runtime n8n B | El driver ad hoc no quedó versionado; persistirlo para repetir exactamente los tres escenarios. |
| Figura | Fuente editable y figura regenerada. |

## Verificar integridad

```bash
sha256sum docs/cierre/evidencia/20260909-coverage-run3/coverage.json
sha256sum docs/cierre/evidencia/20260909-coverage-run3/junit.xml
sha256sum docs/cierre/evidencia/20260909-coverage-run3/source-manifest.sha256
sha256sum n8n/e2e/evidence/20260909-run.json
sha256sum n8n/e2e/evidence/20260910-durable-fallback.json
(cd docs/cierre/evidencia/absence-20260910T052521Z-r2 && sha256sum -c SHA256SUMS)
(cd docs/cierre/evidencia/drenaje-20260910-run3 && sha256sum -c SHA256SUMS)
(cd docs/cierre/evidencia/drenaje-20260910-run4-unit1 && sha256sum -c SHA256SUMS)
```

## Playwright US-03 / US-25 — 2026-09-10

- `us03-us25-playwright-20260910T205424Z/RESULTADO.md`: estado final; dos conjuntos consecutivos 2/2 PASS con login aislado.
- `us03-us25-playwright-20260910T205424Z/individual-us03-final/` y `individual-us25/`: ejecuciones individuales finales.
- `us03-us25-playwright-20260910T205424Z/combined-final-run1/` y `combined-final-run2/`: repetición consecutiva que prueba aislamiento del rate limit.
- `us03-us25-playwright-20260910T205424Z/SHA256SUMS`: integridad del paquete final.
- `us03-us25-playwright-20260910T205424Z/ARTIFACT_RETENTION.md`: retiro retrospectivo de trazas y medios no sanitizables; resultados textuales preservados sin reejecución.
- `us03-us25-playwright-20260910T203527Z/` y `us03-us25-playwright-20260910T204339Z/`: descubrimiento y corrección previos, preservados como históricos; no son el estado final.

### US-02 / US-20 / US-31 — Playwright real

- `us02-us20-us31-playwright-20260910T212203Z/RESULTADO.md`: veredicto por criterio y bloqueos.
- `us02-us20-us31-playwright-20260910T212203Z/COMMANDS.md`: comandos ejecutados y de repetición.
- `us02-us20-us31-playwright-20260910T212203Z/CLEANUP.md`: aislamiento y conteos finales en cero.
- `us02-us20-us31-playwright-20260910T212203Z/SHA256SUMS`: integridad del paquete sanitizado.

Ese paquete es histórico. La corrección posterior y evidencia vigente están en:

- `us02-us20-us31-fixed-20260910T233934Z/RESULTADO.md`: alcance exacto de la reevaluación.
- `us02-us20-us31-fixed-20260910T233934Z/playwright-us02.log`, `playwright-us20.log` y `playwright-us31.log`: pruebas individuales 1/1, 2/2 y 2/2 PASS.
- `us02-us20-us31-fixed-20260910T233934Z/playwright-combined.log`: conjunto 5/5 PASS.
- `us02-us20-us31-fixed-20260910T233934Z/teardown-result.json`: cero contenedores, volúmenes y redes residuales; stack principal sin cambios.
- `us02-us20-us31-fixed-20260910T233934Z/SHA256SUMS`: integridad del paquete sanitizado.
- `us02-us20-us31-fixed-20260910T233934Z/ARTIFACT_RETENTION.md`: paquete textual; trazas y medios retirados sin reejecutar ni alterar resultados.
- `us02-us20-us31-fixed-us20isolated20260911T0220Z/`: paquete vigente sobre snapshot congelado; US-20 2/2 dos veces y conjunto 5/5 dos veces. Sus cuatro `sse-reconnect.json` prueban cierre exclusivo de SSE, API/refresh 200 durante el corte, segunda respuesta establecida antes de publicar y toast real posterior.

### US-03 / US-16 / US-17 / US-25 — laboratorio aislado real

- `us03-us16-us17-us25-isolated-20260910T235332Z/RESULTADO.md`: veredicto vigente y límites contractuales.
- `us03-us16-us17-us25-isolated-20260910T235332Z/us03-multikey-result.json`: rotación CURRENT/PREVIOUS live y uso del token nuevo contra `/rules`, sin tokens persistidos.
- `us03-us16-us17-us25-isolated-20260910T235332Z/playwright-us16-us17.log` y `playwright-us25.log`: casos individuales PASS.
- `us03-us16-us17-us25-isolated-20260910T235332Z/playwright-combined.log`: conjunto 2/2 PASS.
- `us03-us16-us17-us25-isolated-20260910T235332Z/teardown-result.json`: cero recursos lab y stack principal sin cambios.
- `us03-us16-us17-us25-isolated-20260910T235332Z/ARTIFACT_INVENTORY.md`: inventario de las dos trazas textuales retenidas y referencias relativas verificadas.
- `us03-us16-us17-us25-isolated-20260910T235332Z/SHA256SUMS`: integridad completa.

Los paquetes `...T221818Z/`, `...T222631Z/`, `...T224506Z/`, `...T230300Z/`, `...T234339Z/` y `...T234725Z/` son históricos y no constituyen evidencia vigente. El paquete `...T235332Z/` incorpora las aserciones, elimina evidencia visual no sanitizable, sanitiza variantes percent-encoded y verifica identidad y salud del stack principal.

### US-03 / US-16 / US-17 / US-25 — contratos canónicos, 2026-09-11

- Paquete vigente: `us03-us16-us17-us25-isolated-20260911T015529Z/`.
- Individuales: US-03 1/1, US-16/17 1/1, US-25 1/1 PASS.
- Combinado: 3/3 PASS, repetido dos veces.
- Incluye multi-key real, cookie canónica, RuleForm por labels, wire `event_ids[]`, comando firmado, ACK y efecto en baseline.
- Las carpetas anteriores se conservan como historial y no describen el estado contractual vigente.

## A-3 — Ensayo multianfitrión con mTLS y TLS de Valkey — 2026-09-12

- `v10-closure-20260912T190052Z/a3-multihost/README.md`: resumen del ensayo, anfitriones, resultados por punto de control, métricas clave y hallazgos.
- `v10-closure-20260912T190052Z/a3-multihost/RUNBOOK_WSL2_MTLS.md`: registro paso a paso completo (72 KB); el nombre se conserva por trazabilidad con un plan preliminar sobre WSL2 que se descartó antes de instalar el agente — el ensayo ejecutado usó una segunda PC física con Ubuntu 26.04.1 LTS instalado en disco, sin virtualización.
- `v10-closure-20260912T190052Z/a3-multihost/MANIFEST_EXCLUSION.md`: historial de por qué la carpeta quedó excluida del manifiesto de integridad mientras el ensayo estaba en curso, y de su inclusión posterior.
- `v10-closure-20260912T190052Z/a3-multihost/SHA256SUMS`: manifiesto propio del paquete. **Este paquete está íntegramente versionado en git** (66 archivos verificados con `git ls-files`); se verifica con:

  ```bash
  cd docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost
  sha256sum -c SHA256SUMS
  ```

- Código base: rama `devel`, HEAD inicial `223f85c` más las correcciones `f9a536a` (listener TLS de bootstrap dedicado, D52/RN-146), `f552aa6` (Authority Key Identifier en el certificado de Valkey) y `656b101` (preflight de escritura con `effective_ids`). **No corresponde al candidato consolidado `7a7ee50`.**
- Hallazgos abiertos, no corregidos durante el ensayo: `process_exe` vacío en eventos de la PC; archivo nuevo reportado como `file_modified` en vez de `file_created`, con `diff_text` vacío en los `file_created` observados; avalancha de 38.794 mensajes históricos en el stream `commands` compartido (más de 22.000 `detector.out_of_scope_drop` en los primeros 20 s, ~65/min en régimen estable); reinstalación de `agent/install.sh` que anida el árbol de código; listener 8443 sin alerta TLS legible al rechazar un certificado de cliente inválido.
- Límites: red local doméstica, un único agente monitoreado, una sola corrida por prueba; orquestador de notificaciones degradado durante el ensayo (sin prueba de notificación entre dos anfitriones); no acredita WAN, alta disponibilidad ni rendimiento extrapolable.
- El resto del paquete `v10-closure-20260912T190052Z/` (`lanes/`, `m3/`, `m4/`, `m8/`, `m9/`, `build/`, `backlog/`, `figures/`) **no está versionado en git**; el manifiesto `../SHA256SUMS` de ese directorio padre lo incluye, pero un clon del repositorio no puede verificarlo. Sólo `a3-multihost/` es una excepción versionada dentro de ese paquete.

## A-4 — Aceptación de despliegue en un servidor remoto (VPS) — 2026-09-14/15

- `a4-vps-acceptance-20260915T153824Z/README.md`: entorno (VPS HostGator Ubuntu 22.04.5 kernel 6.8 + PC del operador Ubuntu 26.04 kernel 7.0), resultados por tarea del grupo 12 del change `vps-deployment-readiness`, y los siete hallazgos del grupo 14 con su commit de corrección.
- `a4-vps-acceptance-20260915T153824Z/SHA256SUMS`: manifiesto propio de esta carpeta.
- `a4-vps-20260915T145238Z/`: carpeta hermana de una corrida previa del mismo ensayo. **No tiene `README.md` ni `SHA256SUMS` propio.**
- Código base: rama `devel`, commit inicial `2f84d60`; correcciones de hallazgos en `ed286d9..277a458`. **No corresponde al candidato consolidado `7a7ee50`.**
- No verificado en este entorno: deduplicación de tickets con el mismo `event_id` (el VPS no tiene un sistema de tickets controlado); los arreglos 14.5 y 14.7 se reverificaron en un proyecto Docker aislado con n8n real, no en el VPS.
- **Ninguna de las dos carpetas A-4 está versionada en git.** Ambas quedan excluidas por `.gitignore` (patrón `/docs/cierre/evidencia/a4-vps-*/`); son evidencia local del equipo de trabajo, no parte del paquete de cierre distribuido con el repositorio. Verificado con `git ls-files` (0 archivos) y `git check-ignore -v`.
