# Cierre consolidado — FIM Platform

## 1. Portada y alcance

**Proyecto:** FIM Platform (File Integrity Monitoring) para hosts Linux.
**Materia / instancia:** Trabajo final de grado, UTN-FRM.
**Fecha de este documento:** 2026-09-16.
**Repositorio:** `tesis-fim-serio`, rama `devel`.
**HEAD evaluado:** commit `bf24d84d6bb6db486a4bce47d9facfd95a2c0e04` (2026-09-16T11:09:18-03:00).

Este documento consolida, sin recalcular ni corregir ninguna cifra, lo que ya está declarado en `docs/cierre/` (informes de cierre, matriz de trazabilidad, índices de evidencia), en la auditoría externa `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` (archivo excluido de git por `.gitignore` pero presente en el árbol de trabajo, tomado aquí como insumo de lectura) y en `docs/implementaciones/cuarentena-y-diff-arreglos.md`. Cuando dos fuentes citan un mismo hecho con valores distintos, se muestran ambas y se marca la discrepancia; no se elige una por criterio propio.

El proyecto no avanza sobre un único commit congelado, sino sobre varios objetos de evaluación que **no deben mezclarse**:

| Objeto evaluado | Identificador | Qué prueba |
|---|---|---|
| Serie de commits puntuales sobre `devel` | ver tabla completa en §4 | Implementaciones incrementales (US-09, mTLS, n8n durable, drenaje, cuarentena, etc.), cada una con su propia verificación dirigida |
| Candidato consolidado con custodia formal | `7a7ee5011d9234023687687ed95a7cdda9437711` (rama `integration/v10`, árbol `9e9e472bbdfc377674db5dec41224bcc15f48991`) | Suite consolidada de agente/backend/frontend/scripts/E2E sobre un único snapshot, con verificación independiente por auditoría externa |
| Candidato experimental previo | `7df4935f769a2e393a5e6a6330df605c77592e52` | Los tres ensayos de concurrencia, drenaje (5 corridas) y latencia con inicio externo, verificados independientemente por la auditoría |
| Unificación posterior en `devel` | commit `925dab5` (2026-09-15) | Integra los carriles L1–L8 y L10 del candidato V10 en `devel`; **no es un candidato consolidado con custodia** y no tiene una matriz de trazabilidad recalculada sobre sí mismo en este corpus |

**Qué es este documento:** una consolidación de lectura única para un panel académico, con citas a la fuente exacta de cada afirmación y cada cifra, y con las discrepancias entre fuentes señaladas en lugar de resueltas.

**Qué NO es este documento:** no es una declaración de cierre integral del proyecto, no es una fuente primaria nueva de resultados, no es un dictamen de aptitud productiva, y no reemplaza la lectura de los documentos originales para quien necesite el detalle completo. Los números aquí citados no fueron recalculados; cuando una fuente advierte un límite sobre su propio número (por ejemplo, "no establece un SLA"), esa advertencia se reproduce junto con el número.

---

## 2. Estado del cierre

Fuente: `docs/cierre/INFORME_CIERRE_TECNICO.md` §1.

| Dimensión | Estado declarado | Fundamento |
|---|---|---|
| Cierre de implementación | **Parcial** | US-09 y mTLS quedaron implementados y committeados; persisten criterios parciales en historias de usuario y defectos abiertos fuera de esos lotes. |
| Cierre de validación | **Parcial** | La corrida causal nueva no produjo ausencias inexplicadas y la corrida de drenaje optimizada fue íntegra, pero los 19 casos históricos de ausencia no admiten reconstrucción causal completa. No existe una corrida consolidada de agente+backend+frontend sobre un único commit final congelado que cubra, a la vez, todas las unidades (ver candidato V10 en §4, que sí cubre suites completas pero con salvedades de alcance en §11). Tampoco existe, dentro del candidato consolidado, un ensayo distribuido de dos anfitriones (ese ensayo existe, pero corrió sobre otro commit; ver §7 y §11, riesgo N-3). |
| Cumplimiento experimental por umbral | **Parcial** | La latencia reagregada históricamente cumple el umbral original; el drenaje del backend Unidad 1 (Run 4) cumple el umbral de 30 s bajo condiciones de laboratorio documentadas; persisten indicadores que no cumplen (drenaje histórico y Runs 2–3) o que se sostienen en un único candidato experimental distinto del consolidado (concurrencia, latencia con inicio externo, drenaje de 5 corridas). Ver detalle completo en §7. |
| Aptitud productiva | **No se declara / no evaluable** | "Las evaluaciones fueron de laboratorio y anfitrión único; no prueban operación multianfitrión, alta disponibilidad ni canales comerciales" (INFORME_CIERRE_TECNICO.md §10). El propio informe fija el estado correcto como "cierre parcial, no aptitud productiva". |

**Cita textual del estado global** (INFORME_CIERRE_TECNICO.md, línea 14): *"cierre parcial. No corresponde declarar el proyecto cerrado integralmente."*

La auditoría externa independiente, que evalúa específicamente el candidato consolidado `7a7ee50` (no `devel`), llega a una valoración cuantitativa separada y no intercambiable con la anterior: **7,8/10**, con dictamen **"Aprobada con observaciones"** — explícitamente no "Recomendada para defensa" mientras subsistan los cuatro riesgos de severidad alta descriptos en §11 (AUDITORIA_INTEGRAL_TESIS_V10.md, línea 420).

Este documento no declara el proyecto cerrado. Reporta el estado parcial que las fuentes citadas sostienen.

---

## 3. Resumen ejecutivo

El proyecto implementa una plataforma FIM (agente fanotify propio + backend FastAPI + frontend React) sobre PostgreSQL y Valkey Streams, con notificaciones vía n8n. El estado de cierre es **parcial** en las cuatro dimensiones evaluadas (implementación, validación, cumplimiento experimental, aptitud productiva — esta última no se declara ni se evalúa).

**Suites de prueba** (candidato consolidado `7a7ee50`, verificado de forma independiente por la auditoría externa): agente 541 tests (540 passed, 1 skipped, 0 failed), cobertura 79,57 %; backend 689/689 passed, cobertura 91,34 %; frontend 197/197 passed, cobertura de líneas 73,09 %; scripts 19/19; dos suites E2E con código de salida 0; OpenSpec 44 especificaciones / 249 requisitos. Una regresión posterior sobre `devel` (2026-09-15, sin custodia formal) reporta agente 597+1 skip, backend 754/754 (con TLS de Valkey), frontend 197/197 — pero esa corrida **no sustituye una nueva validación consolidada**, que sigue pendiente (INFORME_CIERRE_TECNICO.md §16).

**Cobertura funcional de 31 historias de usuario:** el corte vigente, reconciliado el 2026-09-16 sobre `devel` (commit `2475de8`), es **25 completas / 6 parciales / 0 sin cobertura**. Los conteos anteriores se conservan como historia y **no son intercambiables** dentro del propio corpus documental, porque miden objetos distintos (rama y corte distintos): `docs/cierre/MATRIZ_TRAZABILIDAD.md` sobre `devel` (corte 2026-09-11) reporta **12 completas / 19 parciales / 0 sin cobertura**; `docs/cierre/RESULTADOS_VERIFICADOS.md`, citando esa misma matriz pero con un corte anterior, reporta **10/21/0**; la Tabla 22 del candidato consolidado V10, recompuesta y verificada de forma independiente por la auditoría externa, da **23/8/0**. Ninguna lectura del corpus sostiene "31/31 completas". Ver detalle y reconciliación en §6.

**Experimentos:** de los indicadores con umbral explícito, cumplen bajo las condiciones documentadas la latencia reagregada histórica, el drenaje del backend Unidad 1 (29,146 s sobre un umbral de 30 s, corrida única) y — sobre el candidato experimental `7df4935`, no el consolidado — la concurrencia (P99 616,626 ms sobre umbral 5.000 ms, corrida única exitosa tras un primer intento con 88/100) y el drenaje repetido cinco veces (media 28,424 s, las cinco por debajo de 30 s) y la latencia con inicio externo por `strace` (P99 31,533 ms sobre umbral 1.000 ms). No cumplen el drenaje histórico (153 s) ni los Runs 2 y 3 de la optimización de cola (362,8 s y 51,8 s respectivamente). Detalle completo en §7.

**Seguridad:** se ejercitó mTLS agente-backend (localhost, 1.3, rechazo de certificado ausente/no confiable/vencido) y, en un ensayo posterior de dos anfitriones físicos reales sobre LAN doméstica, mTLS de Valkey con 9/9 rechazos negativos correctos y capturas de tráfico sin cadenas en claro — pero ese ensayo corrió sobre un commit de `devel` distinto del candidato consolidado, y no ejerció notificación externa entre los dos anfitriones porque n8n estaba degradado durante la corrida.

**Defectos y riesgos:** hay defectos abiertos de producto (cuarentena automática que sobrescribe la última versión aprobada — Q-1, severidad alta —, ausencia de liberación de cuarentena, clasificación errónea de `file_created`, `process_exe` vacío en un entorno, entre otros — ver §10) y 17 riesgos de la auditoría externa sin cerrar (4 altos, 7 medios, 6 bajos — ver §11).

**Aptitud productiva:** no se declara ni se evalúa en ninguna de las fuentes de este corpus.

---

## 4. Estado real del proyecto

### 4.1 Stack y entorno verificado

Python 3.13.14, pytest 8.3.4, PostgreSQL 18.3, Valkey 9.0.3 (INFORME_CIERRE_TECNICO.md §2). El agente usa `FAN_REPORT_DFID_NAME` (modo FID); la versión mínima exacta de kernel requerida no se fija en este corpus sin una fuente primaria externa. Entorno del candidato consolidado (`metadata/tool-versions.txt`, `final-consolidated-v10-20260912T210903Z/`): Linux `7.0.0-31-generic` x86_64, git 2.53.0, Python 3.13.14, pytest 8.3.4, coverage.py 7.14.3, Node v24.17.0, pnpm 11.8.0, Docker 29.7.2.

### 4.2 Componentes implementados y ejecutables

| Componente | Estado | Notas |
|---|---|---|
| Agente fanotify (`agent/`) | Implementado, ejecutable en Linux con capacidades (`CAP_SYS_ADMIN`, `CAP_DAC_READ_SEARCH`) | 418 pruebas históricas preservadas; ver suite consolidada en §5 |
| Backend FastAPI/PostgreSQL (`backend/`) | Implementado y ejecutable | 494 pruebas históricas preservadas; ver §5 |
| Valkey Streams (transporte backend↔agente) | Implementado | La captura histórica de tráfico es en claro (`valkey://`); TLS de Valkey verificado solo en el ensayo de dos anfitriones (§8) y en pruebas de integración del backend, no en la operación histórica ni en el candidato consolidado como despliegue |
| Frontend React | Implementado | Sin salida consolidada histórica equivalente a los 912 tests backend+agente; ver suite consolidada en §5 |
| US-09 (DiffViewer) | Implementado (commits `8039624`, `f08626a`) | En `devel`, al corte de la matriz, sin comparación de hashes + hex dump para binarios ni `react-diff-viewer-continued`; sí implementado en el candidato V10 (lane l6) y posteriormente en `devel` vía commit `1c68e79` según CAMBIOS_PARA_TESIS_V11.md §7.2 |
| mTLS agente-backend | Implementado (commit `28f87fe`) | Listener dedicado, identidad de certificado, renovación antes de expirar, CA estricta; sin CRL/OCSP en el handshake |
| n8n unidades A y B (notificación durable) | Implementadas (commits `f0a2907`, `e2519eb`+`3bec584`) | Ver §8 |
| Cuarentena cifrada y retención | Implementadas (commits `b060e5f`, `947edb6`) | AES-256-GCM streaming, HKDF `quarantine-v1`, retención parametrizable 1–365 días; defectos abiertos en §10 |

### 4.3 Candidatos y qué prueba cada uno

**Commits puntuales sobre `devel`** (INFORME_CIERRE_TECNICO.md §2):

| Elemento | Commit(s) | Qué prueba |
|---|---|---|
| Corrida histórica original | `77f0c53e` | Baterías originales de laboratorio; contradicción no resuelta entre `entorno.txt` (sin commit) y `RESULTADOS.md` (árbol limpio) |
| Correcciones de recuperación/cola | `c806d1c2` | Contención de rutas, journal hasta publicación durable, sync drop-oldest |
| US-09 | `8039624`, `f08626a` | Diff textual acotado, corrección de snapshot aislado |
| mTLS | `28f87fe` | Listener dedicado, rechazo de certificado inválido/ausente/vencido |
| n8n unidad A | `f0a2907` | Backend notifier → n8n 2.17.8 → receptor controlado |
| n8n unidad B | `e2519eb` + evidencia `3bec584` | Persistencia de estado de entrega, recuperación tras reinicio, cascada tras 4 intentos |
| Instrumentación causal | `aae55e4` + evidencia `f69e450` | Corrida válida en `absence-20260910T052521Z-r2/`; no reconstruye los 19 casos históricos |
| D49–D51 | `b70934d`, `b8e9513` | UID no resuelto → `null`; `FAN_Q_OVERFLOW` → `detection_gap` |
| Baseline ligada al evento | `8d37075` | Candidato local cifrado por `source_event_id` |
| Optimización de drenaje (cola/ACK, backend Unidad 1) | `7c5afa5`, `965dcac` | Ver Run 4 en §7/§9 |
| Cuarentena cifrada | `b060e5f` | AES-256-GCM streaming |
| Retención de cuarentena | `947edb6` | Retención 1–365 días, migración legacy fail-closed |

**Candidato consolidado V10** (`7a7ee50`, rama `integration/v10`): custodia formal en `docs/cierre/evidencia/final-consolidated-v10-20260912T210903Z/` — bundle Git verificado (`custody/candidate.bundle`, referencia `refs/heads/evidence-candidate-v10`), 840 hashes de archivo, `verify-custody.sh` PASS, `sha256sum -c`: 130/130 OK, `results.json.overall_status: PASS`. Ninguno de los paquetes de evidencia de este candidato está versionado en git (0 archivos trackeados en `final-consolidated-v10-20260912T210903Z/`, `experiments-closure-20260912T004612Z/`, y en `v10-closure-20260912T190052Z/lanes/`).

Existen dos intentos previos preservados como fallidos/abortados sobre el mismo candidato: `final-consolidated-v10-20260912T205729Z-attempt1-failed/` (E2E US-03/16/17/25 falló por un conflicto de validación de patrón duplicado entre pruebas; corregido sin tocar código de producto) y `final-consolidated-v10-20260912T210821Z-aborted-dirty-worktree/` (abortado en un chequeo previo por worktree sucio, sin ejecutar ninguna suite).

**Candidato experimental** `7df4935` (anterior al consolidado): sobre él corrieron los tres ensayos de concurrencia, drenaje de 5 corridas y latencia con inicio externo, verificados de forma independiente por la auditoría (AUDITORIA_INTEGRAL_TESIS_V10.md, riesgo N-3: este candidato modificó rutas de drenaje/cola/Valkey respecto del consolidado; los resultados no se transfieren automáticamente a `7a7ee50`).

**Unificación en `devel`** (2026-09-15, commit `925dab5`): integra los carriles L1–L8 y L10 del candidato V10 (L9 excluido por estar superado). Regresión: agente 597 passed + 1 skip, backend 754/754 con `TEST_VALKEY_TLS=1`, frontend 197/197, OpenSpec 44/249. Advertencia explícita de la fuente: *"Esta regresión no es un candidato consolidado congelado con custodia [...]. No sustituye una nueva validación consolidada, que sigue pendiente"* (INFORME_CIERRE_TECNICO.md §16). Su evidencia primaria (`summary.json`) reside fuera del repositorio.

---

## 5. Validación por componente

### 5.1 Evidencia histórica preservada

Backend: 494/494 aprobadas. Agente: 418 recolectadas, 417 aprobadas, 1 omitida. Total 912 (911 aprobadas + 1 omitida) — INFORME_CIERRE_TECNICO.md §5 aclara explícitamente que una cifra anterior de 675 "no describe esta misma corrida" (corrección documentada en `docs/cierre/CAMBIOS_PARA_TESIS.md`, línea 20).

### 5.2 Coverage backend Run 3 (snapshot anterior, no HEAD)

Fuente: `docs/cierre/evidencia/20260909-coverage-run3/README.md`, ejecutado 2026-09-09 sobre un snapshot con HEAD `c806d1c` más cambios locales — explícitamente no representativo del HEAD actual.

- **572 tests recolectados: 570 aprobadas, 2 omitidas (requieren Valkey real, opt-in), 0 fallidas.**
- Cobertura de sentencias: **2.484/2.780 = 89,3525 %** (296 faltantes, 3 excluidas; branch coverage deshabilitada).
- El listener mTLS estuvo deshabilitado sólo en ese harness: "esta corrida no acredita mTLS".
- El JUnit fue sanitizado (ruta absoluta y hostname reemplazados); el hash original y el sanitizado difieren por diseño, ambos trazables en `docs/cierre/evidencia/20260909-coverage-run3/`.

### 5.3 Verificación dirigida de cuarentena

Fuente: INFORME_CIERRE_TECNICO.md §5. U1 (`b060e5f`): 76/76 pruebas dirigidas PASS; suite completa del agente 489 recolectadas, 486 PASS, 1 SKIP, 2 FAIL (reproducidos también en la base, no atribuidos a la cuarentena). U2 (`947edb6`): 50/50 dirigidas PASS; suite completa 508 recolectadas, 505 PASS, 1 SKIP, mismos 2 FAIL preexistentes.

### 5.4 Otras verificaciones dirigidas puntuales

US-09 (snapshot limpio): agente 10/10, backend 10/10; verificación inicial 41 backend/agente + 7 frontend. mTLS (`backend/tests/test_mtls_transport.py`): 1 PASS (handshake válido + rechazo de certificado ausente/no confiable/vencido). Backend Unidad 1 de ingesta (`965dcac`): 32 pruebas dirigidas PASS. n8n unidad B: 9 pruebas dirigidas PASS. Ejecución ampliada de notificaciones: 62 recolectadas, 55 PASS, 7 FAIL atribuidos a un harness mTLS preexistente — "no se atribuyen esos siete fallos a n8n ni se presenta esa ejecución como suite aprobada" (INFORME_CIERRE_TECNICO.md, línea 126).

### 5.5 Suite consolidada del candidato V10 `7a7ee50` (verificada de forma independiente por la auditoría)

Fuente: `docs/cierre/evidencia/final-consolidated-v10-20260912T210903Z/results.json` y `AUDITORIA_INTEGRAL_TESIS_V10.md` §3.D.

| Suite | Recolectados | Passed | Failed | Skipped | Cobertura | Exit code |
|---|---|---|---|---|---|---|
| Agente | 541 | 540 | 0 | 1 | 2.726/3.426 líneas = 79,57 % | 0 |
| Backend | 689 | 689 | 0 | 0 (incluye 16 unitarias + 4 integración TLS de Valkey) | 2.902/3.177 líneas = 91,34 % | 0 |
| Frontend | 197 | 197 | 0 | 0 | líneas 2.836/3.880 = 73,09 %; funciones 158/234 = 67,52 %; ramas 587/726 = 80,85 % | typecheck y build: 0 |
| Scripts | 19 | 19 | 0 | 0 | — | 0 |
| E2E US-02/20/31 | — | — | — | — | — | 0 |
| E2E US-03/16/17/25 | — | — | — | — | — | 0 |
| OpenSpec | — | — | — | — | 44 especificaciones / 249 requisitos, 0 problemas | 0 |

Nota de integridad: el `SHA256SUMS` del paquete final se regeneró después de la corrida por una redacción de ruta absoluta del home en dos archivos de metadatos (`POSTRUN_NOTE.md`, explícito: *"Ningún resultado de prueba, código de salida, archivo de cobertura, archivo JUnit o artefacto de custodia fue modificado"*). El mismo patrón de nota post-corrida existe en el intento fallido preservado.

### 5.6 Regresión post-unificación en `devel` (2026-09-15, sin custodia formal)

Agente 597 passed + 1 skipped; backend 754/754 con `TEST_VALKEY_TLS=1`; frontend 197/197; OpenSpec 44/249 (INFORME_CIERRE_TECNICO.md, línea 225). No reemplaza una validación consolidada nueva.

---

## 6. Cobertura funcional de las 31 historias de usuario

### 6.1 Los conteos del corpus

| Fuente | Corte / rama | Completas | Parciales | Sin cobertura | Nota |
|---|---|---|---|---|---|
| `docs/cierre/MATRIZ_TRAZABILIDAD.md` (líneas 39-47) | `devel`, 2026-09-11 | **12** | **19** | 0 | Fuente citada como autoritativa por el resto del corpus para `devel` |
| `docs/cierre/RESULTADOS_VERIFICADOS.md` (línea 11) | cita a la misma matriz, corte anterior | **10** | **21** | 0 | **Discrepancia con su propia fuente citada**: la diferencia de 2 corresponde a US-05 y US-12, reclasificadas a completas por el change `backlog-partial-stories-completion` (2026-09-15) en la matriz, aparentemente posterior a la redacción de esta fila |
| Tabla 22 del candidato consolidado V10 (`7a7ee50`), recompuesta por AUDITORIA_INTEGRAL_TESIS_V10.md §3.E | rama `integration/v10`, 2026-09-12 | **23** | **8** | 0 | Verificado de forma independiente por la auditoría, con reserva propia: "en el peor caso, el recuento defendible sería 22-23 completas" (riesgos N-4, N-8) |
| **Corte vigente**: `MATRIZ_TRAZABILIDAD.md` y `docs/trazabilidad_us_tests.md`, reconciliados | `devel`, commit `2475de8`, 2026-09-16 | **25** | **6** | 0 | Primer recuento posterior a la unificación de los carriles V10 en `devel` (2026-09-15) |
| `docs/cierre/CAMBIOS_PARA_TESIS.md` (línea 22) | corte previo a todos los anteriores | 9 | 22 | 0 | Corte histórico anterior al cierre de US-02/03/16/17/20/25/31 |

**Ninguna lectura de este corpus sostiene "31/31 historias completas".** Esta afirmación está explícitamente incluida en la lista de enunciados a retirar (CAMBIOS_PARA_TESIS.md, línea 66).

Los tres conteos vigentes miden objetos distintos y no son intercambiables: (1) y (4) miden `devel` en momentos sucesivos; (3) mide el candidato consolidado `7a7ee50` en una rama separada. La unificación de los carriles V10 en `devel` (commit `925dab5`, 2026-09-15) ocurrió después del corte de la matriz (2026-09-11), Ese vacío quedó cubierto por la reconciliación del 2026-09-16, descripta en §6.5.

### 6.2 Estado por historia — corte histórico del 2026-09-11 (`devel`)

| Historia | Estado | Historia | Estado | Historia | Estado | Historia | Estado |
|---|---|---|---|---|---|---|---|
| US-01 | Parcial | US-09 | Parcial | US-17 | Completa | US-25 | Completa |
| US-02 | Completa | US-10 | Parcial | US-18 | Parcial | US-26 | Parcial |
| US-03 | Completa | US-11 | Parcial | US-19 | Parcial | US-27 | Parcial |
| US-04 | Completa | US-12 | Completa | US-20 | Completa | US-28 | Parcial |
| US-05 | Completa | US-13 | Completa | US-21 | Completa | US-29 | Parcial |
| US-06 | Completa | US-14 | Parcial | US-22 | Parcial | US-30 | Parcial |
| US-07 | Parcial | US-15 | Parcial | US-23 | Parcial | US-31 | Completa |
| US-08 | Parcial | US-16 | Completa | US-24 | Parcial | | |

Total: 12 completas / 19 parciales — consistente con la tabla resumen de la matriz.

### 6.3 Razón exacta de cada historia parcial — corte histórico del 2026-09-11

- **US-01**: faltan tests de atributos de cookie, vida de tokens y almacenamiento en memoria; la cookie diverge del criterio (`samesite="lax"` y `path="/"` en `auth/router.py`, el criterio pide `SameSite=Strict`).
- **US-07**: faltan los 3 criterios de interfaz; el selector enumera 6 estados en vez de 7.
- **US-08**: falta el campo "tipo de acción" y la "posición en la cadena" (ver §6.4: PASS en el candidato V10).
- **US-09**: no implementa comparación de hashes + hex dump para binarios ni `react-diff-viewer-continued` en `devel` al corte de la matriz (ver §6.4).
- **US-10**: cubierto el modelo de datos, pero no existe endpoint que devuelva la cadena de un path; documentado como fuera de alcance en `EventTimeline.tsx` (ver §6.4).
- **US-11**: divergencia documentada como decisión (D2), no como brecha: la baseline debería usar el hash actual del filesystem.
- **US-14**: `ruleset_version` global del sistema no lo expone ningún endpoint (ver §6.4).
- **US-15**: precedencia de reglas exclusivas probada solo en el agente; validación de patrón duplicado no implementada (ver §6.4).
- **US-18**: `event_ack` tras `rule_sync` no implementado; los tests documentan la decisión contraria (ver §6.4).
- **US-19**: `AlertResponse` no expone `path` ni tipo de acción; navegación al evento no implementada (ver §6.4).
- **US-22**: sin selección de paths; el comando no incrementa `ruleset_version`; sin guard de versión; la supersesión alcanza a todos los pending del agente (ver §6.4).
- **US-23**: el payload de contexto completo (proceso, `received_at`, acción tomada) sigue sin acreditarse.
- **US-24**: los tests de recarga de paths no invocan el método que dicen probar; reconfiguración real de fanotify sin test (ver §6.4).
- **US-26**: solo navegación "Anterior"/"Siguiente" — faltan navegación numerada e input "ir a página" (ver §6.4).
- **US-27**: sin test el redirect forzado ni el `audit_log` de login/logout.
- **US-28**: sin test el poll de 10 s, componente `agents` de `check_components`, endpoint HTTP `GET /health/components`, timestamp del último check saludable ni botón de cierre (ver §6.4).
- **US-29**: sin test HTTP dedicado de `last_error`/`retry_count`/`failed_at`; la tabla `failed_notifications` no existe (el rol lo cumple `alerts` por diseño).
- **US-30**: sin test/implementación el cese de aceptación de eventos de fanotify ni el timeout de 30 s de drenaje (ver §6.4).

### 6.4 Cruce con las lane `CRITERIOS.md` del candidato V10 (rama `integration/v10`, 2026-09-12)

Las lane `CRITERIOS.md` de `docs/cierre/evidencia/v10-closure-20260912T190052Z/lanes/` declaran PASS en historias que la matriz clasifica como parciales para `devel`. Esto es coherente cronológicamente (la matriz es anterior a la fusión de los carriles V10 en `devel`), pero implica que ninguno de los dos documentos por sí solo describe el estado combinado actual:

| Historia | `MATRIZ_TRAZABILIDAD.md` (devel, 2026-09-11) | Lane `CRITERIOS.md` (candidato V10, 2026-09-12) |
|---|---|---|
| US-08 | Parcial | `lanes/l4/CRITERIOS.md`: 6/6 PASS (agrega `action_type`, severidad, fecha, posición en cadena); con reserva propia de la auditoría (riesgo N-8: el criterio de skew se acepta citando una prueba de formato, no de rechazo) |
| US-09 | Parcial | `lanes/l6/CRITERIOS.md`: 6/6 PASS, incluye modo binario (hex dump 256 bytes) y `react-diff-viewer-continued@3.4.0` |
| US-10 | Parcial | `lanes/l4/CRITERIOS.md`: 4/4 PASS, nuevo endpoint `GET /events/{id}/chain` |
| US-14 | Parcial | `lanes/l1/CRITERIOS.md`: 4/4 PASS, nuevo endpoint `GET /rules/version` |
| US-15 | Parcial | `lanes/l1/CRITERIOS.md`: 7/7 PASS, negación `!` con precedencia exclusiva y validación de patrón duplicado |
| US-18 | Parcial | `lanes/l1/CRITERIOS.md`: 8/8 PASS, `event_ack` de `rule_sync` implementado |
| US-19 | Parcial | `lanes/l3/CRITERIOS.md`: 8/8 sub-criterios PASS |
| US-22 | Parcial | `lanes/l5/CRITERIOS.md`: 10/10 PASS |
| US-24 | Parcial | `lanes/l7/CRITERIOS.md` (infraestructura, 8/8 de los criterios 4–10; criterios 1–3 y 11 explícitamente fuera de alcance de ese laboratorio, no fallidos) + `lanes/l10/CRITERIOS.md` (UI): un criterio (C11) se encontró en falla real y se corrigió — el botón "Guardar paths" no respetaba el estado `draining` del agente; corregido en `AgentCard.tsx`, verificado con prueba roja→verde, suite frontend completa 197/197 tras el fix |
| US-26 | Parcial | `lanes/l2/CRITERIOS.md`: 5/5 PASS, nuevo componente `Pagination.tsx` |
| US-28 | Parcial | `lanes/l2/CRITERIOS.md`: 6/6 PASS |
| US-30 | Parcial | `lanes/l5/CRITERIOS.md`: 7/7 PASS |

La propia auditoría recompone independientemente la Tabla 22 del candidato V10 y confirma **23 completas + 8 parciales + 0 sin cobertura = 31**, con dos reservas explícitas: US-08 (riesgo N-8, ver §11) y US-24 (riesgo N-4: los criterios dinámicos 4–10 se probaron en la cabeza de carril `37fee44`, no en `7a7ee50` mismo). Las 8 historias parciales del candidato V10 son: **US-01, US-05, US-11, US-12, US-21, US-23, US-27, US-29** (`AUDITORIA_INTEGRAL_TESIS_V10_METRICAS.json`, campo `partial_ids`).

### 6.5 Corte vigente reconciliado (2026-09-16)

El 2026-09-16 se reconciliaron `docs/cierre/MATRIZ_TRAZABILIDAD.md` y `docs/trazabilidad_us_tests.md` sobre `devel`, commit `2475de8`, ya con los carriles V10 unificados. Ambos documentos declaran el mismo recuento: **25 completas / 6 parciales / 0 sin cobertura = 31**.

| Historia parcial | Criterio faltante |
|---|---|
| US-07 | El selector enumera 6 de los 7 estados; `superseded` es un checkbox aparte |
| US-11 | El baseline adopta el hash reportado por el evento, no una relectura del archivo (decisión D2) |
| US-21 | `queue_pressure` viaja como proporción 0,0–1,0 y el umbral del 80 % lo decide el cliente; el texto canónico y el apéndice W3 exigen un indicador booleano |
| US-22 | La confirmación visual del re-scan existe, pero ninguna prueba la ejercita |
| US-27 | Falta prueba del registro de auditoría de inicio y cierre de sesión |
| US-29 | Los campos `last_error`, `retry_count` y `failed_at` de la respuesta HTTP no se asertan |

**Ajuste de criterios del 2026-09-15.** El commit `cc73c2d` modificó el texto de cinco criterios del backlog canónico (US-01, US-05, US-23, US-27 y US-29) para alinearlos con decisiones vigentes: la unificación de las notificaciones fallidas en la tabla `alerts` (D6/RN-107) y la definición del banner de fallo terminal sin umbral de reintentos (D6/RN-102). El ajuste de la ruta de cambio forzado de contraseña, de `/account/change-password` a `/change-password`, no cuenta con una decisión previa registrada. Parte de las reclasificaciones de US-01, US-05 y US-23 depende de ese ajuste; el resto se apoya en implementación y pruebas nuevas. Los criterios anteriores se conservan en el historial del repositorio.

**Conclusión de la sección**: el corte vigente es 25/6/0 sobre `devel` (`2475de8`, 2026-09-16); los cortes 3/27/1, 9/22/0, 10/21/0, 12/19/0 y 23/8/0 corresponden a objetos y momentos distintos y se conservan como historia. Ninguna lectura del corpus sostiene 31/31, y el criterio de aceptación original —verificación automatizada completa de las 31 historias— sigue incumplido.

---

## 7. Experimentos y umbrales

| Experimento | Criterio | Resultado | Condiciones | Estado | Evidencia |
|---|---|---|---|---|---|
| Latencia Tabla 1 (reagregación histórica) | P99 &lt; 1.000 ms | n=493, media 11,316 ms, P50 12,639, P95 16,798, **P99 17,745 ms** | Reagregación de `received_at - marca post-operación`, no es corrida nueva; auditoría señala explícitamente que este cálculo "no se recalculó" | **Cumple** | `scripts/generador_carga.py`; `docs/cierre/RESULTADOS_VERIFICADOS.md` |
| Latencia con inicio externo (candidato `7df4935`, verificada de forma independiente) | P99 &lt; 1.000 ms | 100/100 correlacionados, 0 intervalos negativos; **P99 = 31,533 ms** (mean 15,260; mediana 13,331; P95 26,506; máx 31,897; mín 6,167; desvío 6,168 ms) | Inicio = fin de `close(2)` por `strace -ttt -T -yy`; fin = `events.received_at`; host único, reloj compartido, Valkey sin TLS, agente contenedorizado | **Cumple** | `docs/cierre/evidencia/experiments-closure-20260912T004612Z/latency/summary.json`; AUDITORIA_INTEGRAL_TESIS_V10.md §3.C |
| Latencia — intento inválido | — | — | El harness generó nombres de baseline con dos dígitos mientras el generador esperaba tres; se detuvo antes de cualquier modificación | Sin resultado, preservado como inválido | `experiments-closure-20260912T004612Z/latency/invalid-attempt1/INVALID_RUN.txt` |
| Detección B3 histórica | 500 operaciones reportables | 493/500; faltan 7 secuencias (193, 196, 209, 270, 323, 364, 369) | Histórico, sin cadena causal runtime contemporánea | **Parcial** | `resultados/bateria3_manifiesto.jsonl` |
| Desconexión B5 histórica | 3.000 operaciones preservadas | 2.988/3.000; 12 ausencias | Histórico | **Parcial** | `resultados/bateria5_manifiesto.jsonl` |
| Corrida causal actual (B9) | Reconstruir cadena operación→baseline→kernel→decisión→cola→backend | 60 operaciones: 50 con cadena completa y persistencia; 10 retornos a baseline aprobada legítimamente suprimidos (`matches_active_baseline`); 0 ausencias nuevas inexplicadas | `ext4`, fanotify nativo contenedorizado con capabilities, reloj monotónico compartido; **no reconstruye** los 19 casos históricos de B3/B5 | Cumple el contrato actual, sin retroactividad | `docs/cierre/evidencia/absence-20260910T052521Z-r2/RESULTADO.md`, commit `aae55e4` |
| Drenaje histórico | &lt; 30 s | 2.988 eventos en 153 s = 19,529 ev/s | Histórico | **No cumple** | `resultados/cronologia_utc.txt` |
| Drenaje Run 1 | &lt; 30 s | Interrumpido a los 300 s con 1.808/3.000 persistidos | Defecto de harness (timestamps sobrescritos en reintentos); percentiles de latencia por etapa inválidos | **Inválido**, preservado | `docs/cierre/evidencia/drenaje-20260910-run1/LIMITACIONES.md` |
| Drenaje Run 2 | &lt; 30 s | 3.000/3.000, 0 rechazos, **362,834 s = 8,268 ev/s** | Causa raíz identificada: 8.682 XADD para 3.000 ids por tormenta de republicación (el listener de ACK arrancaba después del drenaje completo) | **No cumple** | `docs/cierre/evidencia/drenaje-20260910-run2/RESULTADO.md` |
| Drenaje Run 3 (optimizado) | &lt; 30 s | 3.000/3.000, 0 rechazos/duplicados, **51,773 s = 57,945 ev/s** | Corrección de la tormenta de republicación confirmada (exactamente 3.000 XADD); cuello de botella remanente en ingesta backend serial | **No cumple** | `docs/cierre/evidencia/drenaje-20260910-run3/RESULTADO.md` |
| Drenaje Run 4 — backend Unidad 1 | &lt; 30 s | 3.000/3.000, 0 rechazos/duplicados, **29,146335596 s = 102,928891 ev/s** | Copia limpia de `965dcac`; dos intentos inválidos preservados y excluidos (error de harness por firma de función y por pipeline atómico mal envuelto); rate limit experimental (100.000/60 vs. 100/60 en producción) | **Cumple**, corrida única, bajo laboratorio documentado | `docs/cierre/evidencia/drenaje-20260910-run4-unit1/RESULTADO.md` |
| Drenaje (candidato `7df4935`, 5 corridas, verificado de forma independiente) | &lt; 30 s | 27,784; 29,043; 28,109; 29,188; 27,997 s → media **28,424 s**, mediana 28,109 s, desvío muestral 0,644 s; 5/5 con 3.000/3.000, 0 duplicados, cola residual 0 | Mismo SHA-256 de `run_profile.py` en las 5 corridas, mismas condiciones | **Cumple** (5/5) | `docs/cierre/evidencia/experiments-closure-20260912T004612Z/drain/aggregate.json`; AUDITORIA_INTEGRAL_TESIS_V10.md §3.B |
| Micro-benchmark de índice de cola (`queue-index-profile`) | Aislar el costo de la cola local | Enqueue 29,458 s→0,166 s; Bump de intento 38,075 s→0,220 s; Remove por ACK 17,697 s→0,036 s | Excluye Valkey/PostgreSQL; mismo lote de 3.000 payloads, mismo proceso/filesystem | Confirma el costo cuadrático de escaneo completo y su corrección; "no prueba por sí sola el umbral extremo a extremo" | `docs/cierre/evidencia/drenaje-20260910-queue-index-profile/RESULTADO.md` |
| Notificaciones históricas B4 | 1.000 operaciones, niveles 1/10/100 ops/s | 329 muestras de 360 operaciones (60/60, 99/100, 170/200); receptor HTTP local, no n8n | Histórico | No cumple el denominador ni pasa por n8n | `resultados/bateria4_todos.csv` |
| Concurrencia (candidato `7df4935`, verificada de forma independiente) | P99 &lt; 5.000 ms | 100/100 aceptadas, máx. 100 activas simultáneas; **P99 = 616,626 ms** (mediana 354,850; P95 595,037; ida-y-vuelta cliente P99 712,668 ms) | Cubre solo el tramo de la función de transporte `send_n8n` hacia un receptor HTTP local controlado — "no acredita n8n/canal final ni sistema integral" | **Cumple**, corrida única exitosa | `docs/cierre/evidencia/experiments-closure-20260912T004612Z/concurrency/summary.json`; AUDITORIA_INTEGRAL_TESIS_V10.md §3.A |
| Concurrencia — intento previo | — | 88/100 aceptadas (12 fallidas), máx. 49 activas, P99 1.615,443 ms (n=88) | Capacidad de cola por defecto del receptor insuficiente; la repetición solo cambió `request_queue_size` (5→256) y activó hilos daemon | **No cumple**, no atribuido a un defecto de producto | `experiments-closure-20260912T004612Z/concurrency/attempt1-summary.json` |
| `mmap` (caracterización) | Caracterizar limitación conocida | 30/30 en tres casos, 10 repeticiones por caso | Laboratorio | Consistencia observada; "no descarta ventana evasiva" | `resultados/bateria8/` |
| Captura Valkey (inventario) | Consistencia de paquetes capturados | Documento reporta 662 paquetes; `capinfos` mide 660 | Discrepancia de 2 preservada, no resuelta | **Parcial** | `resultados/bateria55_valkey.pcap` |

**Nota sobre precisión numérica**: los valores de media/mediana/P99 citados arriba para concurrencia, drenaje (5 corridas) y latencia con inicio externo provienen simultáneamente de `docs/cierre/evidencia/experiments-closure-20260912T004612Z/*/summary.json` (o `aggregate.json`) y de `AUDITORIA_INTEGRAL_TESIS_V10.md` §3, que los recalculó de forma independiente a partir de los mismos registros crudos y confirmó coincidencia exacta (`metadata/independent-verification.json`, 17 verificaciones, todas `true`).

---

## 8. Seguridad y notificaciones

**mTLS agente-backend**: nueva evaluación real en localhost con TLS 1.3; acepta certificado confiable y rechaza ausencia de certificado, CA no confiable y certificado vencido (1 test dirigido PASS, `backend/tests/test_mtls_transport.py`). Limitación declarada: la ruta HTTP común no expone renovación; la identidad/revocación del agente se valida solo al autorizar la renovación (sin CRL/OCSP en el handshake).

**mTLS/TLS de Valkey en dos anfitriones físicos reales** (2026-09-12, `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/`): dos equipos físicos por LAN doméstica — laptop `192.168.1.43` (servidor central, Docker Compose completo) y una PC física separada con Ubuntu 26.04.1 LTS instalado en disco (bare-metal, sin virtualización), `192.168.1.36`, con el agente FIM nativo vía systemd. Se descartó un plan preliminar sobre WSL2 (superó su propio checkpoint pero se abandonó antes de instalar el agente, para poder afirmar host físico real sin VM/reloj legado de Windows). Resultado: **9/9 rechazos negativos correctos** (V1–V4 sobre Valkey, B1–B3 y E1–E2 sobre backend, incluyendo controles positivos V3/B3), capturas de tráfico en ambos extremos sin cadenas de protocolo en claro (413/297 paquetes en la laptop, 220/135 en la PC, dos rondas cada una). Corrió sobre `devel` en los commits `223f85c`+`f9a536a`+`f552aa6`+`656b101` — **no sobre el candidato consolidado `7a7ee50`**. n8n estaba degradado durante el ensayo, por lo que **no se ejerció notificación externa entre los dos anfitriones**.

**Transporte Valkey en general**: la captura histórica usa `valkey://` sin TLS y contiene tráfico legible; la verificación de mTLS agente-backend no convierte esa captura en TLS. El ensayo de dos anfitriones subsana esto parcialmente, pero no corre sobre el candidato consolidado ni sobre una topología de despliegue productivo.

**HMAC**: aporta autenticidad e integridad del mensaje, no confidencialidad.

**n8n unidad A** (`f0a2907`): receptor controlado persiste cada `notification_id` antes de responder 202; separa `received_at`, `backend_dispatched_at`, `n8n_accepted_at`, `receiver_received_at`. No se midió un límite de sincronización de relojes.

**n8n unidad B** (`e2519eb`+`3bec584`): sobre PostgreSQL 18.3 limpio, 4 intentos n8n fallidos seguidos de un webhook controlado exitoso; fallo total persistido sin falso éxito; recuperación desde proceso nuevo con el mismo `notification_id`; delays reducidos solo en el ensayo (producción mantiene 5/30/120 s); garantía al-menos-una-vez con deduplicación por `notification_id`. **SMTP real no fue acreditado en esta unidad.**

**Cascada de notificaciones bajo n8n inalcanzable** (US-23, lane l7): laboratorio con n8n deliberadamente inalcanzable, 8/8 criterios de US-23 verificados, incluyendo 4 reintentos reales con delays nominales 5/30/120 s (tiempos reales medidos de punta a punta, no acelerados), cascada SMTP directo (Mailpit) → webhook directo → log crítico, persistencia en DLQ (`alerts`), continuidad operativa del sistema (`GET /health`, `GET /rules` en 200) durante la caída.

**Entrega SMTP real posterior** (2026-09-15, cierre parcial de la brecha SMTP): entrega real por email vía n8n en la aceptación VPS (`docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/a4-12.6-webhook-email.txt`, respuesta 202, `{"channel":"email","delivered":true}`) y fallback SMTP directo del backend contra un capturador desechable (Mailpit), mensaje recibido con ID `1NQ73pW1kKvdeH7iLt9vAO`. Aun con esta evidencia, **US-23 permanece clasificada como parcial** en `devel` porque el payload de contexto completo no se acredita en ese corte.

**Hallazgo 14.7 (cuerpo de correo vacío)**: durante la aceptación VPS, el correo de alerta llegó con cuerpo vacío más pie de n8n (`12.6-mail-cuerpo-vacio-hallazgo-14.7.png`); causa raíz: el cuerpo se fijaba en el campo `message`, que el nodo `emailSend` v2.1 ignora. Corregido usando los campos `html`+`text` (commit `b0865c6`), verificado antes de sellar la evidencia.

**Fuera de alcance / no ejercitado en este corpus**: SMTP comercial real (más allá del capturador Mailpit y Gmail vía n8n), notificación externa entre dos anfitriones (n8n degradado durante A-3), proveedores comerciales de mensajería.

**Ejecución ampliada de 62 pruebas de notificaciones**: 55 pasaron, 7 fallaron por un harness mTLS preexistente; no se atribuyen a n8n ni se presenta esa ejecución como suite aprobada.

---

## 9. Recuperación, durabilidad y concurrencia

**Drenaje**: ver tabla completa en §7. Resumen: histórico no cumple (153 s); Run 1 inválido (harness); Run 2 no cumple (362,8 s); Run 3 no cumple (51,8 s, aunque mejora sustancialmente); Run 4 sobre backend Unidad 1 cumple (29,146 s) bajo laboratorio documentado, corrida única; las 5 corridas del candidato experimental `7df4935`, verificadas de forma independiente, cumplen todas (media 28,424 s). Ninguna fuente declara estas repeticiones como un SLA — "una única repetición no establece un SLA" (INFORME_CIERRE_TECNICO.md §9).

**Deduplicación**: Run 4 registró 0 mensajes duplicados entre 3.000 publicaciones, pero eso "no prueba deduplicación temporal de una misma ruta" (RESULTADOS_VERIFICADOS.md). La deduplicación de tickets con el mismo `event_id` en el entorno VPS (aceptación A-4) **no fue verificada en ese entorno** — "el VPS no dispone de un sistema de tickets controlado; esa propiedad se cubrió en un ensayo aislado con n8n real, no en esta corrida" (INFORME_CIERRE_TECNICO.md §15).

**Concurrencia**: verificada solo sobre el candidato experimental `7df4935` (no el consolidado `7a7ee50`), en una única corrida exitosa (100/100) tras modificar la configuración del receptor de laboratorio; el primer intento dio 88/100. La auditoría cataloga esto como riesgo A-2 (bajado de "Alto" a "Medio" en esta versión, no cerrado): "Repetir ≥5 corridas con receptor fijo y, de ser posible, ingesta real y n8n" (AUDITORIA_INTEGRAL_TESIS_V10.md, tabla de riesgos).

**Corte de backend / recuperación (dos anfitriones, A-3)**: corte de 120 s registró eventos 2–10 con detección→recepción entre 114,9 y 123,0 s; 11 re-publicaciones, 10 confirmaciones, 0 descartes. Calificado como "informativo", no como medición de rendimiento generalizable.

**"Exactamente una vez"**: descartado explícitamente como garantía general. "La cadena distribuida es al menos una vez. 'Exactamente una vez' sólo puede usarse para una transición concreta con idempotencia demostrada, no para todos los efectos" (INFORME_CIERRE_TECNICO.md §7). Incluido explícitamente en la lista de afirmaciones a retirar (CAMBIOS_PARA_TESIS.md, fila "Exactamente una vez").

---

## 10. Defectos abiertos

### 10.1 Diagnosticados en `docs/implementaciones/cuarentena-y-diff-arreglos.md` (documento de diagnóstico, sin implementar)

| ID | Severidad | Descripción | Evidencia | Presente en el candidato V10 (`7a7ee50`) |
|---|---|---|---|---|
| Q-1 | **Alta** | Tras la cuarentena automática, `mark_absent` sobrescribe la entrada con `content_b64=None`/`snapshots=[]`: se pierde la última versión aprobada, ya no restaurable — contradice RN-37 ("el baseline permanece intacto") | `agent/detector.py:849,987`; `agent/baseline.py:385-400` | Sí (`agent/detector.py:1119,1124`) |
| Q-2 | Alta | No existe liberación ni recuperación de cuarentena desde el producto (sin comando, endpoint ni botón) | `agent/commands.py:106-201` | Sí |
| Q-3 | Media | No existe "cuarentena + restauración": el operador debe elegir entre conservar evidencia o recuperar el servicio | `agent/decision.py:219-304` | Sí |
| Q-4 | Media | El mismo resultado físico produce `quarantined` (automático) o `rejected` (operador); filtrar por `quarantined` no muestra lo cuarentenado por operador | `events/service.py:135-153`; `actions/service.py:292,312` | Sí |
| U-1 | Media | La consola muestra Aprobar/Rechazar para `alert_only`, pero el backend solo acepta `pending`: siempre responde 409 | `EventDetail.tsx:59`; `actions/service.py:202,289` | Sí |
| D-2 | Baja | El diff de modificaciones sucesivas es acumulado contra la baseline aprobada, no incremental, y la consola no lo aclara | `agent/detector.py:684,911-919,989-993` | Sí |
| D-3 | Baja | Sin prueba E2E de US-09 ni de flujos visuales de US-12 | `frontend/e2e/` | Sí |
| X-1 | A confirmar | El `unlink` del origen por el agente podría generar un evento `file_deleted` posterior; no verificado cómo se filtra ni si altera la baseline | `agent/quarantine.py:626` | Sin verificar |
| X-2 | A confirmar | Un archivo creado inmediatamente después de su directorio puede clasificarse como `file_modified` (hallazgo consistente con el ensayo de dos anfitriones, §10.2) | `agent/detector.py:662-678` | Sin verificar con prueba dedicada |

Impacto declarado por la fuente: "Q-1 y U-1 afectan al candidato V10 y deberían declararse como limitaciones si no se corrigen: la tesis describe la cuarentena como conservación de evidencia sin modificar la baseline (RN-37), y el código automático no lo cumple. Corregirlos implica un candidato nuevo y repetir la validación consolidada."

### 10.2 Hallazgos operativos del ensayo de dos anfitriones (A-3), no corregidos

| Defecto | Descripción | Impacto |
|---|---|---|
| `process_exe` vacío | Contexto forense de proceso incompleto en eventos generados en la PC remota | Atribución forense degradada en ese entorno |
| `file_created` reportado como `file_modified`; `diff_text` vacío en `file_created` | Un archivo creado 2 s después de su directorio se clasifica mal; contenido inicial no viaja en el evento | Clasificación incorrecta, pérdida de información de auditoría |
| Avalancha de 38.794 mensajes históricos en el stream `commands` | &gt;22.000 `detector.out_of_scope_drop` en los primeros 20 s de un agente nuevo; ~65/min en régimen estable | Ruido de journal, sin impacto funcional declarado |
| Listener 8443 sin alerta TLS legible al rechazar certificado inválido | Corta con `unexpected eof`/`errno=104` en vez de una alerta TLS explícita (a diferencia de Valkey) | Diagnóstico degradado |

### 10.3 Hallazgos de la aceptación VPS (A-4), corregidos antes de sellar la evidencia

Siete hallazgos (14.1–14.7) fueron corregidos con pruebas antes del cierre de esa evidencia: validación de versión de Python en `install.sh`, resolución de rutas relativas del instalador, secreto opcional exigido innecesariamente en reinstalación, `ADMIN_PASSWORD` silenciosamente ignorado, reprovisioning de n8n rompiendo el webhook, ajuste manual de CORS para `self_signed`, y el cuerpo de correo vacío (14.7, detalle en §8). Se listan porque documentan defectos reales encontrados en un entorno de aceptación real, aunque ya no estén abiertos.

### 10.4 Fallas de manifiesto/custodia en paquetes de evidencia

`final-consolidated-v10-20260912T205729Z-attempt1-failed/`: discrepancia de 1 archivo no documentada en su nota. `v10-closure-20260912T190052Z/`: 349 OK, 1 falla de manifiesto (`a3-multihost/RUNBOOK_WSL2_MTLS.md` modificado después del corte). `lanes/l7/us23` y `lanes/l7/us24`: ambos fallan la verificación de `raw/services-before-teardown.jsonl`. Ninguna de estas fallas afecta los resultados de JUnit ni la custodia del paquete final (AUDITORIA_INTEGRAL_TESIS_V10.md, riesgo N-5).

---

## 11. Riesgos de la auditoría V10

Fuente: `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` §13 y `AUDITORIA_INTEGRAL_TESIS_V10_METRICAS.json`. Totales: 0 críticos, **4 altos**, **7 medios**, **6 bajos** = 17 riesgos, evaluados sobre el candidato consolidado `7a7ee50`.

| ID | Severidad | Descripción | Estado | Qué se necesita para cerrarlo |
|---|---|---|---|---|
| A-1 | Alta | La hipótesis conjunta del proyecto no fue corroborada: drenaje histórico en 153 s, 23/31 historias completas, 19 ausencias sin causa runtime reconstruida | Declarado, sin cambios respecto de la versión anterior de la auditoría | "Mantener; explicitar qué criterios sí se sostienen" |
| A-2 | Media (bajó de Alta) | Concurrencia acreditada solo en el tramo `send_n8n`→receptor local, inicio simulado, una única corrida exitosa, dependiente de la capacidad del receptor | Verificado con datos crudos y diff de scripts | "Repetir ≥5 corridas con receptor fijo y, de ser posible, ingesta real y n8n" |
| A-3 | Alta | Sin ensayo sobre dos anfitriones ni TLS de Valkey en despliegue, al momento del corte de esta auditoría | Verificado; parcialmente cubierto después por el ensayo de dos anfitriones y la aceptación VPS, pero ninguno de los dos corrió sobre `7a7ee50` | "Ejecutar el runbook y preservar la evidencia" (parcialmente satisfecho fuera del candidato consolidado) |
| A-4 | Alta | Backlog incompleto: 23/8/0 sobre el candidato V10; corte vigente 25/6/0 sobre `devel` (`2475de8`, 2026-09-16, §6.5) | Recomputado por la auditoría y reconciliado el 2026-09-16 | "Completar US-27/29/11/12 o defender la parcialidad" |
| N-1 | Alta | Hallazgo de redacción de la declaración de originalidad, pendiente de decisión del autor. | — | — |
| M-3 | Media | 81,8 % sobre checklist autoral NIST r2, sin segundo evaluador | Verificado contra el documento oficial | "Segundo evaluador o mapeo r3 documentado" |
| M-4 | Media | Privacidad con pendientes: cola sin cifrar, token SSE en query, retención de `audit_log`/`rejected_events_audit`, TLS de Valkey en despliegue | Verificado en código | "Cifrar la cola, retirar el token de la URL, fijar la retención" |
| M-9 | Media | Reproducibilidad ambiental incompleta (SBOM/digests) | Inventario local sin digests fijos para imágenes base | "Fijar digests base; depósito institucional" |
| N-2 | Media | Evidencia citada (paquetes V10, experimentos, candidato `7df4935`) no versionada en git; código integrado no fusionado | Verificado (0 archivos trackeados en los paquetes citados) | "Entregar los paquetes con la tesis o versionarlos y declararlo" |
| N-3 | Media | Los tres ensayos experimentales posteriores (concurrencia/drenaje/latencia) corrieron sobre `7df4935`, no sobre `7a7ee50` | Verificado en el historial | "Repetir sobre `7a7ee50` o reforzar la advertencia" |
| N-4 | Media | Evidencia dinámica de US-24 (criterios 4-10) y US-23 proviene de la cabeza de carril `37fee44`, no de `7a7ee50` | Verificado (`git diff --stat`: 36 archivos modificados después) | "Reejecutar sobre `7a7ee50` o anotar el commit exacto" |
| M-2 | Baja (bajó de Media) | Triangulación temporal parcial: inicio externo, pero el fin usa la marca productiva y reloj compartido | Declarado | "Captura de red o segundo reloj para el fin" |
| B-1 | Baja | Tipografía interna pequeña en dos figuras del documento de tesis | Juicio visual | "Redibujar desde fuente editable" |
| N-5 | Baja | Higiene de manifiestos con fallas puntuales (ver §10.4); el `SHA256SUMS` final se regeneró después de la corrida | Verificado; "no afecta resultados verificados por JUnit ni custodia" | "Regenerar con nota o corregir los escritores posteriores al manifiesto" |
| N-6 | Baja | Un anexo de la tesis afirmaba una sola capacidad Linux requerida; el unit systemd declara cinco | Error factual identificado | "Actualizar el anexo con las cinco capacidades" — ya corregido según `CAMBIOS_PARA_TESIS_V11.md` §5 |
| N-7 | Baja | Residuos editoriales puntuales (afirmaciones imprecisas, una fila de tabla sin explicar su suma, una versión de librería inconsistente entre secciones) | Errores menores | "Corrección puntual" — con texto propuesto en `CAMBIOS_PARA_TESIS_V11.md` §6 |
| N-8 | Baja | US-08 se declara completa apoyándose en una decisión de diseño (D37/RN-131) citando una prueba de formato, no de rechazo por desfase de reloj | Juicio evaluativo | "Citar la prueba de rechazo por `clock_skew` del consumidor" — direccionado en `CAMBIOS_PARA_TESIS_V11.md` §6.5 |

**Riesgos cerrados o reducidos respecto de la versión anterior de la auditoría** (AUDITORIA_INTEGRAL_TESIS_V10.md §16, §18): cerrados 7 (M-1, M-5, M-6, M-7, M-8, B-2, B-3); reducidos de severidad 6 (A-2, A-4 con mejor denominador aunque sigue Alta, M-2, M-4, M-9, B-1); sin cambios 3 (A-1, A-3, M-3). Calificación numérica global: 7,8/10, con una nota de sensibilidad informativa: sin el riesgo N-1, la calificación bruta sería 7,86 (redondearía a 7,9).

---

## 12. Limitaciones y lo no acreditado

- **Aptitud productiva**: no se declara ni se evalúa (§2, §3).
- **Validación multianfitrión en despliegue productivo**: todas las evaluaciones disponibles son de anfitrión único, salvo el ensayo de dos anfitriones (§8), que no corre sobre el candidato consolidado, no cubre WAN/Internet, alta disponibilidad, ni rendimiento extrapolable.
- **Valkey TLS en despliegue productivo**: la operación histórica usa `valkey://` en claro; TLS de Valkey solo verificado en el ensayo de dos anfitriones (LAN doméstica, un agente, sin n8n, sin candidato consolidado) y en pruebas de integración del backend.
- **SMTP comercial real**: no acreditado como proveedor comercial; la entrega real usó Gmail vía n8n y un capturador desechable (Mailpit) para el fallback directo del backend.
- **Causalidad runtime de los 19 casos históricos de ausencia (B3+B5)**: "explicación fuertemente sustentada pero no demostrable retrospectivamente; no presentarlos como causalidad probada" (INFORME_CIERRE_TECNICO.md §9).
- **Suite consolidada única sobre un commit final congelado**: el candidato V10 cubre agente+backend+frontend+scripts+E2E sobre un mismo snapshot, pero con las salvedades de alcance de §11 (N-2, N-3, N-4); no existe una repetición posterior de esa consolidación sobre `devel` tras la unificación del 2026-09-15.
- **31/31 historias completas**: descartado explícitamente en todos los cortes del corpus (§6).
- **Baseline y cuarentena cifradas**: protegen frente a copia aislada del soporte cifrado, no frente a adquisición completa del host ni frente a `root`; la retención elimina la entrada del directorio, sin acreditar borrado seguro del soporte.
- **Reconciliación central de agentes**: no es atestación remota; no detecta necesariamente a un agente comprometido que reporta falsamente.
- **Deduplicación de tickets con mismo `event_id` en el entorno VPS**: no verificada en ese entorno (§9).
- **"Exactamente una vez" como garantía general**: descartado explícitamente (§9).
- **Migraciones automáticas del backend**: el backend no aplica migraciones de `backend/db/migrations/*.sql` automáticamente al arrancar (solo `create_all` + seed admin); se aplican manualmente — corrección respecto de una afirmación previa (`CAMBIOS_PARA_TESIS_V11.md` §7.1).
- **Limitaciones de cuarentena/diff (Q-1 a Q-4, U-1, D-2, D-3, X-1, X-2)**: pendientes de decisión del autor sobre si se corrigen antes de una versión final o se declaran como limitación (§10.1).
- **Evidencia no versionada / fuera del repositorio**: los paquetes de custodia del candidato V10, la evidencia de la aceptación VPS y el `summary.json` de la unificación en `devel` residen fuera del repositorio o no están versionados (detalle en §13) — "un tercero que clone el repositorio no puede verificarlos sin que el autor los adjunte por separado" (`CAMBIOS_PARA_TESIS_V11.md` §4).
- **Código deontológico institucional**: no identificado un instrumento específico de UTN-FRM en este corpus.

---

## 13. Índice de evidencia

| Ruta (relativa al repositorio) | Contenido | Verificación | Versionado en git |
|---|---|---|---|
| `docs/cierre/INFORME_CIERRE_TECNICO.md` | Informe técnico de cierre, estado por dimensión | Lectura directa | Sí |
| `docs/cierre/RESULTADOS_VERIFICADOS.md` | Tabla de resultados verificados con fuente por fila | Lectura directa | Sí |
| `docs/cierre/MATRIZ_TRAZABILIDAD.md` | Matriz de las 31 historias de usuario | Lectura directa | Sí |
| `docs/cierre/INDICE_EVIDENCIAS.md` | Índice narrativo de evidencia con ruta de revisión sugerida | Lectura directa | Sí |
| `docs/cierre/REPRODUCIR.md` | Instrucciones de reproducción | Lectura directa | Sí |
| `docs/cierre/CAMBIOS_PARA_TESIS.md` | Correcciones respecto de la auditoría V5 | Lectura directa | Sí |
| `docs/cierre/CAMBIOS_PARA_TESIS_V11.md` | Continuación para el corte de auditoría V10 | Lectura directa | **No** (archivo nuevo, sin trackear al corte de este documento) |
| `docs/cierre/PRUEBAS_PARCIALES_PREPARADAS.md` | Preparación de pruebas parciales | Lectura directa | Sí |
| `docs/cierre/evidencia/INDICE.md` | Índice técnico con SHA-256 por archivo | `sha256sum <archivo>` por entrada | Sí |
| `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` | Auditoría externa del candidato V10 | Lectura directa | **No** (excluido por `.gitignore:58`, presente en disco) |
| `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10_METRICAS.json` | Métricas estructuradas de la auditoría | Lectura directa / `jq` | **No** (mismo patrón de exclusión) |
| `docs/implementaciones/cuarentena-y-diff-arreglos.md` | Diagnóstico de defectos de cuarentena y diff (sin implementar) | Lectura directa | Sí |
| `docs/cierre/evidencia/20260909-coverage-run3/` | Coverage backend Run 3 (snapshot anterior) | `sha256sum coverage.json`; `sha256sum junit.xml` | Sí (5 archivos) |
| `docs/cierre/evidencia/absence-20260910T051102Z/` | Intento inválido de corrida causal (preservado) | Lectura de `INVALID_RUN.md` | Sí (17 archivos) |
| `docs/cierre/evidencia/absence-20260910T052521Z-r2/` | Corrida causal válida (B9) | `cd <dir> && sha256sum -c SHA256SUMS` | Sí (18 archivos) |
| `docs/cierre/evidencia/drenaje-20260910-run1/` | Drenaje Run 1 (inválido, timeout de harness) | Lectura de `LIMITACIONES.md` | Sí (8 archivos) |
| `docs/cierre/evidencia/drenaje-20260910-run2/` | Drenaje Run 2 (no cumple umbral) | Lectura de `RESULTADO.md` | Sí (11 archivos) |
| `docs/cierre/evidencia/drenaje-20260910-run3/` | Drenaje Run 3 optimizado (no cumple umbral) | `cd <dir> && sha256sum -c SHA256SUMS` | Sí (12 archivos) |
| `docs/cierre/evidencia/drenaje-20260910-run4-unit1/` | Drenaje Run 4 sobre backend Unidad 1 (cumple umbral) | `cd <dir> && sha256sum -c SHA256SUMS` | Sí (19 archivos) |
| `docs/cierre/evidencia/drenaje-20260910-queue-index-profile/` | Micro-benchmark de índice de cola | Lectura de `RESULTADO.md` | Sí (9 archivos) |
| `docs/cierre/evidencia/final-consolidated-v10-20260912T210903Z/` | Bundle final de custodia del candidato V10 (`results.json`, JUnit, coverage, custodia) | `bash verify-custody.sh`; `sha256sum -c SHA256SUMS` | **No** (0 archivos trackeados) |
| `docs/cierre/evidencia/final-consolidated-v10-20260912T205729Z-attempt1-failed/` | Intento 1 fallido, preservado | Lectura de `ATTEMPT_NOTE.md` | **No** |
| `docs/cierre/evidencia/final-consolidated-v10-20260912T210821Z-aborted-dirty-worktree/` | Intento abortado por worktree sucio | Lectura de `metadata/ABORTED.txt` | **No** |
| `docs/cierre/evidencia/experiments-closure-20260912T004612Z/` | Concurrencia, drenaje (5 corridas) y latencia sobre el candidato `7df4935` | `python3 scripts/verify_experiments.py` (referenciado en `metadata/independent-verification.json`) | **No** |
| `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/` | Ensayo de dos anfitriones (mTLS agente-backend, TLS Valkey) | `cd <dir> && sha256sum -c SHA256SUMS` | Sí (66 archivos) |
| `docs/cierre/evidencia/v10-closure-20260912T190052Z/lanes/l1`–`l10/` | Evidencia por carril del candidato V10, con `CRITERIOS.md` en l1–l7 y l10 | Lectura de cada `CRITERIOS.md` | **No** |
| `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/` | Aceptación en VPS real (grupo 12, `vps-deployment-readiness`) | `cd <dir> && sha256sum -c SHA256SUMS` | **No** (excluido por patrón `.gitignore` `/docs/cierre/evidencia/a4-vps-*/`) |
| `docs/cierre/evidencia/a4-vps-20260915T145238Z/` | Captura precursora de la aceptación VPS (sin README propio) | Inspección manual de archivos crudos | **No** |

Para los paquetes no versionados en git, la verificación de integridad depende de que el autor los adjunte junto con la tesis (depósito institucional o anexo digital con hashes), tal como señala el riesgo N-2 de la auditoría (§11).

---

## 14. Trazabilidad documental

| Sección de este documento | Fuentes principales |
|---|---|
| 1. Portada y alcance | `git rev-parse HEAD`; `docs/cierre/INFORME_CIERRE_TECNICO.md` §2 |
| 2. Estado del cierre | `docs/cierre/INFORME_CIERRE_TECNICO.md` §1; `AUDITORIA_INTEGRAL_TESIS_V10.md` |
| 3. Resumen ejecutivo | Síntesis de §4-§11 de este documento |
| 4. Estado real del proyecto | `docs/cierre/INFORME_CIERRE_TECNICO.md` §2-§3, §16; `evidencia/final-consolidated-v10-20260912T210903Z/`; `AUDITORIA_INTEGRAL_TESIS_V10.md` |
| 5. Validación por componente | `docs/cierre/INFORME_CIERRE_TECNICO.md` §5; `evidencia/20260909-coverage-run3/`; `evidencia/final-consolidated-v10-20260912T210903Z/results.json`; `AUDITORIA_INTEGRAL_TESIS_V10.md` §3.D |
| 6. Cobertura funcional de 31 historias | `docs/cierre/MATRIZ_TRAZABILIDAD.md`; `docs/cierre/RESULTADOS_VERIFICADOS.md`; `evidencia/v10-closure-20260912T190052Z/lanes/*/CRITERIOS.md`; `AUDITORIA_INTEGRAL_TESIS_V10.md` §3.E |
| 7. Experimentos y umbrales | `docs/cierre/RESULTADOS_VERIFICADOS.md`; `docs/cierre/PRUEBAS_PARCIALES_PREPARADAS.md`; `evidencia/drenaje-20260910-*/`; `evidencia/experiments-closure-20260912T004612Z/`; `AUDITORIA_INTEGRAL_TESIS_V10.md` §3 |
| 8. Seguridad y notificaciones | `docs/cierre/INFORME_CIERRE_TECNICO.md` §7, §14, §15; `evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md`; `evidencia/a4-vps-acceptance-20260915T153824Z/README.md`; `evidencia/v10-closure-20260912T190052Z/lanes/l7/CRITERIOS.md` |
| 9. Recuperación, durabilidad y concurrencia | `docs/cierre/INFORME_CIERRE_TECNICO.md` §7, §9; `docs/cierre/RESULTADOS_VERIFICADOS.md`; `evidencia/experiments-closure-20260912T004612Z/`; `evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md` |
| 10. Defectos abiertos | `docs/implementaciones/cuarentena-y-diff-arreglos.md`; `evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md`; `evidencia/a4-vps-acceptance-20260915T153824Z/README.md`; `AUDITORIA_INTEGRAL_TESIS_V10.md` §0, §16 |
| 11. Riesgos de la auditoría V10 | `docs/cierre/AUDITORIA_INTEGRAL_TESIS_V10.md` §13, §16, §18; `AUDITORIA_INTEGRAL_TESIS_V10_METRICAS.json` |
| 12. Limitaciones y lo no acreditado | Todas las fuentes anteriores, consolidadas |
| 13. Índice de evidencia | `docs/cierre/INDICE_EVIDENCIAS.md`; `docs/cierre/evidencia/INDICE.md`; verificación directa de tracking con `git ls-files` / `git check-ignore` sobre el repositorio |
| 14. Trazabilidad documental | Este documento |

---

*Documento generado por consolidación de fuentes existentes en `docs/cierre/`, sin recálculo de cifras. Renderizado a PDF con WeasyPrint a partir de una transcripción HTML de este mismo Markdown.*
