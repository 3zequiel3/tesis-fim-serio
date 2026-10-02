# US-09 — Visualización de diff de un evento — Criterios de aceptación

Fuente canónica: `docs/historias_de_usuario.md` §US-09 (verbatim). Ningún
criterio en conflicto con los appendices "Decisiones de auditoría/implementación
— Abril 2026" — no hay BLOCKED-BY-DECISION en esta lane.

Base: `lane/l6-diff` sobre `v10-base` (7df4935 + `6790e40` privacy hardening).
Commits de esta lane: ver sección final.

## Criterio 1 — "En el detalle de un evento, se muestra un diff lado a lado o unificado del contenido."

- **Implementación**: `frontend/src/components/ui/DiffViewer.tsx:97-104` (`ReactDiffViewer` con `splitView`, lado a lado), invocado desde `frontend/src/pages/EventDetail.tsx` (sección "Diff de contenido").
- **Test**: `frontend/src/pages/EventDetail.test.tsx` → `renderiza el diff textual real recibido por la API`; `frontend/src/components/ui/DiffViewer.test.ts` → `preserva encabezados y offsets de múltiples hunks sin crear continuidad falsa`.
- **Estado**: PASS (ya existía en `v10-base` para el patch en `<pre>`; ahora renderiza vía la librería con split view real).

## Criterio 2 — "El diff textual (lado a lado o unificado) solo está disponible para archivos de texto."

- **Implementación**: `agent/detector.py` — `_generate_diff` (preexistente, sin cambios de comportamiento) solo produce `diff_text` cuando `_is_text_bytes` valida UTF-8 en ambos lados; el modo binario (criterio 3) solo se evalúa cuando `diff_text is None` (`agent/detector.py:1010-1017`).
- **Test**: `agent/tests/test_detector_diff.py::test_generate_diff_returns_none_for_binary`; `agent/tests/test_detector_binary_diff.py::test_text_modification_does_not_set_is_binary`.
- **Estado**: PASS.

## Criterio 3 — "Para archivos binarios, se muestra: comparación de hashes (hash anterior vs. nuevo con indicador visual) y hex dump parcial (primeros N bytes, lado a lado)."

- **N elegido**: 256 bytes (`agent/detector.py:40`, `_HEX_DUMP_BYTES`). Justificación: acota el campo a un tamaño pequeño y determinístico (16 filas de 16 bytes, formato `hexdump -C` sin columna ASCII) — mismo criterio defensivo que `_MAX_DIFF_BYTES` para el diff textual, pero deliberadamente mucho menor: es una muestra de inspección forense, no un intento de reconstruir el archivo. El backend valida el formato/tamaño antes de persistir (`_bounded_hex_dump`, cota adicional de 4096 caracteres).
- **Implementación**:
  - Agente: `agent/detector.py:235-253` (`_hex_dump`), `agent/detector.py:256-286` (`_binary_diff_info`), wired en `agent/detector.py:1010-1017` (rama `file_modified`).
  - Backend: `backend/app/modules/events/models.py` (columnas `is_binary`/`hex_dump_before`/`hex_dump_after`), `backend/app/modules/events/service.py:86-98` (`_bounded_hex_dump`) y `:298-300,372-374` (ingesta), `backend/app/modules/events/router.py` (`EventDetailOut`, detalle-only).
  - Migración: `backend/db/migrations/016_add_event_binary_diff_metadata.sql` (aplicada e idempotente, verificado dos veces contra `fim-l6-db`).
  - Frontend: `frontend/src/components/ui/DiffViewer.tsx:112-159` (`BinaryComparison`: indicador ✗/✓ + hash antes/después + hex dump lado a lado en grid de 2 columnas).
- **Tests**:
  - `agent/tests/test_detector_binary_diff.py` (7 tests: formato de `_hex_dump`, acotamiento a N bytes, integración `_process_event` con/sin contenido previo, archivo de texto no marcado binario, archivo oversized no marcado binario).
  - `backend/tests/test_event_service.py::test_ingest_event_persists_binary_diff_metadata`, `::test_ingest_event_defaults_is_binary_false_for_older_agents`, `::test_ingest_event_rejects_malformed_hex_dump` (4 casos).
  - `frontend/src/components/ui/DiffViewer.test.ts::detecta modo binario automáticamente...`, `::indica visualmente que los hashes difieren...`.
  - `frontend/src/pages/EventDetail.test.tsx::muestra comparación de hashes y hex dump para un evento binario`.
- **Estado**: PASS.

## Criterio 4 — "El componente DiffViewer detecta automáticamente si el archivo es texto o binario y cambia de modo."

- **Implementación**: `frontend/src/components/ui/DiffViewer.tsx:170-194` — el componente decide el modo (texto / binario / no disponible) internamente a partir de `diffText`/`isBinary`, sin que `EventDetail` (`frontend/src/pages/EventDetail.tsx`) rame la decisión (antes había un ternario en el caller; ahora `DiffViewer` siempre recibe todas las props y decide).
- **Test**: `frontend/src/components/ui/DiffViewer.test.ts::detecta modo binario automáticamente...`, `::declara ausencia de diff cuando no hay patch textual ni contenido binario`.
- **Estado**: PASS.

## Criterio 5 — "Se utiliza react-diff-viewer-continued con opciones de escapado activas; queda prohibido el uso de dangerouslySetInnerHTML (W8)."

- **Implementación**: `frontend/src/components/ui/DiffViewer.tsx:1,97-104` importa y usa `react-diff-viewer-continued@3.4.0` (antes declarado en `package.json`/`vite-env.d.ts` pero sin uso real). Verificado que la librería NO usa `dangerouslySetInnerHTML` en su propio código (`node_modules/.../react-diff-viewer-continued/lib/src/index.js` — grep sin resultados) y que ningún código propio de este repo lo usa tampoco (`rg dangerouslySetInnerHTML frontend/src` sin resultados).
- **Reconstrucción por hunk**: dado que el backend solo persiste un patch unificado acotado (nunca el archivo completo — decisión de privacidad preexistente), `parseUnifiedDiff` (`DiffViewer.tsx:39-67`) reconstruye texto "antes"/"después" POR HUNK a partir del patch ya recibido (nunca pide ni expone más contenido del que ya estaba en `diff_text`), y renderiza cada hunk por separado para no crear continuidad falsa entre hunks distantes — la misma garantía que el test preexistente `preserva encabezados y offsets de múltiples hunks sin crear continuidad falsa` ya exigía.
- **Test**: `frontend/src/components/ui/DiffViewer.test.ts::nunca usa dangerouslySetInnerHTML (W8)...` (verifica que un `<script>` inyectado en el diff nunca se parsea como HTML real, solo aparece como texto escapado).
- **Estado**: PASS.

## Criterio 6 — "El contenido del diff nunca se loguea en los logs estructurados (W6) — solo se registran hash_before, hash_after y size_delta."

- **Implementación**:
  - `size_delta` agregado al esquema cerrado de `agent/experiment_trace.py:25-34` (`_ALLOWED_FIELDS`) y poblado en `agent/detector.py:402-424` (`_trace_change_created`) + `agent/detector.py:975,1013-1024,1059` (cálculo en la rama `file_modified`).
  - Redacción defensiva por nombre de key (defensa en profundidad, además de que ningún log real pasa este contenido como kwarg): `agent/logging.py` (`_SENSITIVE_RE` ahora incluye `hex_dump`), `backend/app/core/logging.py` (`_EXTENDED_KEYS` ahora incluye `hex_dump_before`/`hex_dump_after`), `backend/app/modules/events/consumer.py:103-133` (`_build_payload_dump` redacta `diff_text` Y `hex_dump_before`/`hex_dump_after` en `payload_dump` de `RejectedEventAudit`).
- **Tests** (incluye el "integral log inspection test" pedido):
  - Agente: `agent/tests/test_log_inspection.py` (2 tests — modificación binaria y textual reales vía `_process_event`, con `structlog.testing.capture_logs()`: ningún log emitido contiene `diff_text`/`hex_dump_before`/`hex_dump_after` como key NI el contenido real como substring de ningún valor; el trace JSONL sí contiene `hash_before`/`hash_after`/`size_delta`).
  - Agente: `agent/tests/test_logging.py::test_hex_dump_before_redacted`, `::test_hex_dump_after_redacted`.
  - Backend: `backend/tests/test_consumer.py::test_ingest_with_binary_diff_never_logs_diff_or_hexdump_content` (integral — ingesta real firmada HMAC vía `_handle_message`, `capture_logs()` sobre toda la ruta feliz del consumer; ningún log captura diff/hexdump, pero el evento persistido SÍ conserva ambos campos íntegros en la DB).
  - Backend: `backend/tests/test_consumer.py::test_rejection_audit_redacts_hex_dump_from_payload_dump`, `backend/tests/test_logging_sanitize.py::test_hex_dump_keys_redacted`.
- **Estado**: PASS.

---

## Resumen

| # | Criterio | Estado |
|---|----------|--------|
| 1 | Diff lado a lado/unificado en el detalle | PASS |
| 2 | Diff textual solo para archivos de texto | PASS |
| 3 | Binarios: hash comparison + hex dump parcial lado a lado | PASS |
| 4 | Auto-detección texto/binario en DiffViewer | PASS |
| 5 | react-diff-viewer-continued con escapado, sin dangerouslySetInnerHTML | PASS |
| 6 | Diff nunca logueado; solo hash_before/hash_after/size_delta | PASS |

**6/6 criterios demostrados. 0 bloqueados por decisión.**

## Migración

`backend/db/migrations/016_add_event_binary_diff_metadata.sql` — agrega
`events.is_binary` (BOOLEAN NOT NULL DEFAULT FALSE), `events.hex_dump_before`
(TEXT), `events.hex_dump_after` (TEXT). Aplicada e idempotente contra
`fim-l6-db` (verificado dos veces: primera corrida 3× `ALTER TABLE`, segunda
corrida 3× `NOTICE: ... already exists, skipping`).

## Impacto en privacidad

- Ningún campo nuevo se loguea en texto plano en logs estructurados (agente
  ni backend) — cubierto por redacción por nombre de key (defensa en
  profundidad) y verificado por tests de inspección integral de logs.
- `hex_dump_before`/`hex_dump_after` quedan acotados a 256 bytes por lado en
  origen (agente) y re-validados/acotados a 4096 caracteres en el backend
  (`_bounded_hex_dump`) — mismo criterio que `diff_text`.
- El endpoint de detalle (`GET /events/{id}`) sigue siendo admin-only
  (`require_admin`, sin cambios) — el listado (`GET /events`) sigue sin
  exponer ni `diff_text` ni los campos binarios nuevos.
- `payload_dump` de `RejectedEventAudit` redacta `hex_dump_before`/
  `hex_dump_after` igual que `diff_text` (RN-105).
- Cola local del agente (`agent/queue.py`): sigue en texto plano (limitación
  conocida, documentada desde antes de esta lane) — el comentario de
  `_ensure_dir_0700` se actualizó para reflejar que ahora también incluye
  `hex_dump_before`/`hex_dump_after`, sin ampliar la superficie de exposición
  más allá de lo que el criterio exige (mismo tratamiento que `diff_text`).

## Bloqueados por decisión

Ninguno.
