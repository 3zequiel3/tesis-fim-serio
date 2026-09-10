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

## Operaciones históricas sin evento

- B3: 193, 196, 209, 270, 323, 364, 369.
- B5: 185, 276, 291, 380, 982, 1243, 1299, 1311, 1705, 1957, 2078, 2767.

Los manifiestos prueban que fueron operaciones efectivas sin evento correlacionado. No contienen la cadena kernel/baseline/decisión/cola necesaria para demostrar la causa.

## Límites y evidencia pendiente

| Marcador | Falta |
|---|---|
| 19 ausencias históricas | La corrida B9 validó el mecanismo actual de supresión al retornar a la baseline aprobada. Los 19 históricos son compatibles y están fuertemente sustentados por manifiestos/código, pero su causalidad runtime retrospectiva no puede probarse porque faltan trazas por etapa. |
| Drenaje | Nueva medición instrumentada: 51,773 s y 57,945 eventos/s tras optimización; el umbral `<30 s` permanece **NO CUMPLE**. El cuello remanente es la ingesta serial del backend. |
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
```
