# Informe de cierre técnico — plataforma FIM

> **Corte:** 2026-09-10. La evaluación de drenaje final se ejecutó desde una copia limpia de HEAD `965dcacc5c189f4a9808b063e32085d89e636803`; la documentación y evidencia se agregan en un commit posterior. Este documento distingue la evidencia histórica de las nuevas evaluaciones y **no declara validación integral ni aptitud productiva**.

## 1. Estado ejecutivo

| Dimensión | Estado | Fundamento |
|---|---|---|
| Cierre de implementación | **PARCIAL** | US-09 y mTLS quedaron implementados y committeados. Las unidades n8n A y B también quedaron committeadas con evidencia controlada. Persisten criterios parciales en las historias y defectos fuera de esos lotes. |
| Cierre de validación | **PARCIAL** | La nueva corrida causal no produjo ausencias inexplicadas y la nueva corrida de drenaje fue íntegra, pero los 19 casos históricos no admiten reconstrucción causal completa. Tampoco existe una corrida consolidada sobre un único commit final ni un ensayo distribuido de dos anfitriones. |
| Cumplimiento experimental | **PARCIAL** | La latencia reagregada cumple. La corrida causal actual clasificó 50 eventos y 10 descartes legítimos sin ausencias nuevas. Run 4 drenó 3.000 eventos en 29,146335596 s y cumple el umbral original sólo bajo sus condiciones de laboratorio; permanecen indicadores parciales o no evaluados. |
| Aptitud productiva | **NO EVALUABLE** | Las evaluaciones fueron de laboratorio y anfitrión único; no prueban operación multianfitrión, alta disponibilidad ni canales comerciales. |

**Estado global para entrega:** **cierre parcial**. No corresponde declarar el proyecto cerrado integralmente.

## 2. Versiones y alcance evaluado

| Elemento | Identidad | Alcance comprobado |
|---|---|---|
| Corrida histórica | `77f0c53e9c5dac28f9b36e56e09bcdb8b214ba1c` | Baterías originales. `resultados/entorno.txt` informa un archivo sin commit y `resultados/RESULTADOS.md` dice árbol limpio: contradicción histórica no resoluble. |
| Correcciones de recuperación/cola | `c806d1c220824b4e9c7ce6af5f18441482473bc0` | Contención de rutas, journal hasta publicación durable y sincronización drop-oldest. |
| US-09 | `8039624292a1f84d6136dd5ed2b2e59d9bdb6f9b` + `f08626a758899d7bb701b55025ebd13f29c17240` | Diff textual acotado y corrección del snapshot aislado. |
| mTLS | `28f87fe3d8183f506404aa1b4d166fabcbc64527` | Listener dedicado, identidad de certificado, renovación previa al vencimiento, perfil de CA estricto y recuperación administrativa para CA legacy. |
| n8n, unidad controlada A | `f0a2907f2b2d282ea39ff255290f9625744c4bbf` | Backend notifier → n8n 2.17.8 → receptor SQLite controlado. |
| n8n, unidad durable B | `e2519ebee40a149fc2cfaabf8b67c2407eac4da9` + evidencia `3bec5841e92181047e4282453d085b7d944971c2` | Estado de entrega persistido, recuperación tras reinicio y cascada posterior a cuatro intentos n8n. |
| Instrumentación y evidencia causal actual | `aae55e4aa0d79e2e053a3dc74b6a69560ae550b9` + evidencia `f69e4501fa75486f872d27ce93595367a9d0d24a` | Corrida válida en `docs/cierre/evidencia/absence-20260910T052521Z-r2/`; no reconstruye los 19 casos históricos. |
| Atribución y brechas de detección D49–D51 | `b70934d3fb59e0bca2294ce768c76586a7d0ef6f` + integración `b8e9513566c18278f26a78cffdf06d4703c1665d` | UID no resuelto queda `null`, `FAN_Q_OVERFLOW` produce `detection_gap`, y `event_type`/path nulo atraviesan persistencia, API y frontend sin falsa supersesión. |
| Baseline aprobada ligada al evento | `8d370758b26d2bd6fdb3b10b81cafc5a490c9ea0` | El agente conserva un candidato local cifrado por `source_event_id` y sólo promueve bytes/hash coincidentes; rechaza candidato ausente, obsoleto o inconsistente. |
| Optimización de drenaje | Cola/ACK `7c5afa5f429139ed6bffbf4d7bc0a7bc21d841ba`; backend Unidad 1 `965dcacc5c189f4a9808b063e32085d89e636803` | Run 3 conserva el resultado intermedio; Run 4 evalúa Unidad 1 desde copia limpia del segundo commit y registra los intentos inválidos por separado. |
| Evidencia de drenaje Run 4 | `864b67242ab30672e222fa10a75b05bd2cac4c1d` | Paquete durable con corrida válida, fuentes, métricas y dos intentos inválidos preservados. |
| Cuarentena cifrada | `b060e5fb7b5301b2de51c80e116bd703c088c07f` | AES-256-GCM streaming, clave HKDF `quarantine-v1`, metadata cifrada, nombres opacos y eliminación del origen sólo después de fsync/readback. |
| Retención y migración de cuarentena | `947edb6d5d76b3c04afcaf18dd84f5ff55d691c2` | Retención configurable 1..365 días (default 30), mantenimiento al inicio/cada 24 h y migración legacy fail-closed. |
| Coverage backend Run 3 | manifiesto y artefactos en `docs/cierre/evidencia/20260909-coverage-run3/` | Snapshot mixto identificado por manifiesto, anterior a los commits US-09/mTLS/n8n; no representa HEAD actual. |

### Entorno histórico conocido

- Python 3.13.14, pytest 8.3.4, PostgreSQL 18.3 y Valkey 9.0.3.
- Batería 8: kernel `7.0.0-30-generic`.
- El filesystem, hardware y versiones Docker/Compose/Node no quedaron preservados con detalle suficiente.
- El código usa `FAN_REPORT_DFID_NAME`; la versión mínima exacta del kernel debe sostenerse con una fuente primaria externa, no inferirse sólo del identificador.

## 3. Componentes ejecutables

| Componente | Estado real | Evidencia | Límite |
|---|---|---|---|
| Agente fanotify | Implementado y ejecutable en Linux con capacidades | 418 pruebas históricas; experimentos fanotify | Suite final y compatibilidad de filesystem no consolidadas. |
| Backend FastAPI/PostgreSQL | Implementado y ejecutable | 494 pruebas históricas; Run 3 de 572 pruebas | Run 3 es una nueva evaluación sobre snapshot manifestado anterior. |
| Valkey Streams | Implementado | B5 y captura B5.5 | Captura histórica en claro; no acredita Valkey TLS. |
| Frontend React | Implementado | Pruebas fuente y verificación dirigida US-09 | Sin salida consolidada equivalente a los 912 históricos. |
| US-09 DiffViewer | Implementado | commits `8039624` + `f08626a`; snapshot limpio: compilación y serialización PASS, agente 10/10, backend 10/10; verificación previa 41 backend/agente + 7 frontend | No conserva contenido binario; lo descarta por contrato. |
| mTLS agente/backend | Implementado | commit `28f87fe`; `backend/tests/test_mtls_transport.py`: 1 PASS con handshake válido y rechazo sin certificado, no confiable y vencido | Un solo anfitrión; la revocación se valida en la autorización de renovación, no como CRL durante handshake. |
| n8n controlado y durable | Implementado y ejecutado | commits `f0a2907`, `e2519eb`, `3bec584`; evidencias `20260909-run.json` y `20260910-durable-fallback.json` | Un backend, receptor webhook de laboratorio; SMTP real y proveedores comerciales no acreditados. |

## 4. Correcciones verificadas

| Defecto | Corrección | Verificación |
|---|---|---|
| Escape de alcance en restauración/cuarentena | Contención por rutas canónicas bajo raíces autorizadas | 80 pruebas focales del lote `c806d1c` sobre índice exportado. |
| Journal confirmado antes de persistir | El journal queda pendiente hasta publicación durable | Regresiones focales del mismo lote. |
| Evento expulsado seguía en `_pending` | La expulsión drop-oldest retira el ID exacto | Regresión focal del mismo lote. |
| US-09 inexistente/no autosuficiente | Unified patch textual, validación UTF-8/control/binario, límite de 1 MiB, persistencia y render multi-hunk; commit correctivo aislado | Snapshot limpio de `8039624` + `f08626a`: compilación/serialización PASS, 10/10 agente y 10/10 backend; además 41 pruebas backend/agente + 7 frontend dirigidas. |
| Renovación sobre transporte no autenticado | Endpoint sólo en listener mTLS; certificado del peer llega por el scope TLS, no por headers | Handshake real 1 PASS y pruebas focales de PKI/renovación. |
| Certificados incompatibles con OpenSSL estricto | CA nuevas con `KeyUsage` crítico; CA legacy fallan cerrado y exigen rotación administrativa | Pruebas de CA nueva/legacy y handshake TLS 1.3. |
| Falso éxito n8n cuando el receptor falla | El workflow responde 202 sólo después de recepción durable; falla downstream produce 502 | Evaluación controlada: éxito 202, receptor caído 502, n8n caído con error de transporte y recuperación 202. |
| Reintentos n8n se perdían al reiniciar | `notification_id`, `attempt_count` y `next_retry_at` persisten en `alerts`; startup recupera filas no terminales y evita reiniciar la escalera | 9 pruebas dirigidas PASS; runtime PostgreSQL limpio con cuatro intentos n8n, fallback webhook real, fallo total persistido y recuperación tras restart. |
| Atribución desconocida se convertía en root | UID/proceso no resolubles se preservan como `null`; `0` queda reservado para root real | Regresiones D49 en agente y render null-safe, commit `b70934d`. |
| Desborde fanotify era invisible | `FAN_Q_OVERFLOW` genera `detection_gap`, deduplicado por ventana monotónica de 60 s y con supresiones contabilizadas | Regresiones D50 y recorrido pathless integrado en `b70934d` + `b8e9513`. |
| Backend descartaba `event_type` y convertía path nulo en cadena vacía | `event_type` persiste; path puede ser nulo; esos eventos no se compactan por ruta y reciben severidad `high` | Pruebas de persistencia, filtros, detalle y frontend incluidas en D51. |
| Aprobación podía asociar hash nuevo con bytes viejos | Candidato cifrado local ligado a `source_event_id`; validación de identidad, ruta, estado, hash y contenido antes de promover baseline | Regresiones de aprobación exacta, idempotencia y rechazo de candidato ausente/obsoleto en `8d37075`. |
| Ingesta ejecutaba 8 sentencias SQL por evento | Snapshot de credenciales/revocación y severidad persistida reducen el trayecto a 5 sentencias SQL por evento | **32 pruebas dirigidas PASS** en `965dcac`; Run 4 confirma el trayecto completo. |
| Cuarentena almacenaba contenido y nombres en claro | Store único para cuarentena automática/comando con AES-256-GCM streaming, metadata cifrada, nombres opacos, modo 0400 y barreras durables antes de borrar el origen | Snapshot limpio `b060e5f`: py_compile PASS y 76/76 pruebas dirigidas. |
| Cuarentena no tenía retención ni migración | Default 30 días configurable 1..365; cleanup al arranque y cada 24 h; legacy reconocido se migra de forma atómica/idempotente | Snapshot limpio `947edb6`: py_compile PASS y 50/50 pruebas dirigidas. |

## 5. Pruebas y coverage

### Evidencia histórica preservada

- Backend: **494/494** aprobadas.
- Agente: **418 recolectadas, 417 aprobadas, 1 omitida**.
- Total: **912**, con **911 aprobadas y 1 omitida**. El valor 675 no describe esta misma corrida.

### Nueva evaluación de coverage Run 3

- **572 recolectadas: 570 aprobadas, 2 omitidas, 0 fallidas/errores**.
- Omisiones: pruebas opt-in que requieren Valkey real.
- `coverage.py` 7.14.3, statements: **2484/2780 = 89,3525 %** (redacción: **89,35 %**), 296 faltantes, 3 excluidas, branch coverage deshabilitada.
- El listener mTLS fue deshabilitado sólo en ese harness; Run 3 no acredita mTLS.
- Artefactos durables: `docs/cierre/evidencia/20260909-coverage-run3/`. El JUnit fue sanitizado reemplazando ruta absoluta y hostname; su hash difiere del original temporal.

Esta evaluación no debe atribuirse a HEAD `3bec584`: su manifiesto identifica un snapshot anterior y con cambios locales.

### Verificación de cuarentena

- U1 `b060e5f`: **76/76 dirigidas PASS**; suite agente 489 recolectadas, 486 PASS, 1 SKIP y 2 FAIL reproducidos también en la base.
- U2 `947edb6`: **50/50 dirigidas PASS**; suite agente 508 recolectadas, 505 PASS, 1 SKIP y los mismos 2 FAIL de base.
- Los dos fallos preexistentes no se contabilizan como defectos introducidos por cuarentena; tampoco se presenta ninguna de esas suites completas como aprobada.

## 6. Resultados experimentales

| Indicador | Resultado | Estado |
|---|---|---|
| Latencia según intervalo de Tabla 1 | Reagregación histórica `received_at - marca post-operación`: n=493, media 11,316 ms, P50 12,639, P95 16,798, P99 **17,745 ms** | **CUMPLE** <1.000 ms; no es una corrida nueva y la marca no prueba el instante físico exacto. |
| Detección B3 histórica | 493/500; faltan secuencias 193, 196, 209, 270, 323, 364 y 369 | **PARCIAL**: manifiestos compatibles con retorno a baseline, pero sin cadena runtime contemporánea. |
| Desconexión B5 histórica | 2.988/3.000; 12 ausencias identificadas | **PARCIAL** por el mismo límite retrospectivo. |
| Corrida causal actual | 60 operaciones: 50 eventos totalmente correlacionados/persistidos + 10 retornos a baseline aprobada descartados como `matches_active_baseline` | **CUMPLE** el contrato bajo estas condiciones; 0 ausencias nuevas inexplicadas. No reconstruye los 19 históricos. |
| Drenaje histórico | 2.988 eventos en 153 s = 19,529 eventos/s | **NO CUMPLE** <30 s. |
| Drenaje Run 3 | 3.000/3.000; 0 rechazos; 0 duplicados; 3.000 XADD; cola final 0; 51,773 s = 57,945 eventos/s | **NO CUMPLE** <30 s; se conserva como resultado intermedio. |
| Drenaje Run 4 (backend Unidad 1) | 3.000/3.000; 0 rechazos; 0 duplicados; 3.000 XADD/XREAD/HMAC/commit/XACK/event_ack; cola final 0; **29,146335596 s = 102,928891 eventos/s** | **CUMPLE** `<30 s` sólo bajo las condiciones documentadas de laboratorio. |
| Notificaciones históricas B4 | 329 muestras de 360 operaciones (60/60, 99/100, 170/200) | No fueron 1.000 ni atravesaron n8n. |
| Tasas B4 | 1/50/100 operaciones/s | No fueron concurrencias simultáneas 1/10/100. |
| `mmap` | 30/30 en tres casos | Consistencia de laboratorio; no descarta ventana evasiva. |

Las 19 ausencias históricas son segundas operaciones de pares revertidos y sus manifiestos son compatibles con el retorno al hash de la baseline aprobada. La corrida causal válida actual preservó operación, hash, baseline, evento kernel, decisión, cola, XADD, ACK y persistencia: 50 operaciones reportables completaron toda la cadena y los 10 retornos C2→C0 fueron suprimidos legítimamente antes de encolar. Esto sustenta el mecanismo actual, pero **no demuestra retrospectivamente** que los 19 casos históricos recorrieran esas mismas etapas, porque sus trazas no existen.

Run 3 redujo el drenaje desde 153 s históricos a 51,773 s y delimitó la ingesta backend serial. Después de backend Unidad 1 (`965dcac`), Run 4 procesó 3.000/3.000 en 29,146335596 s: último XADD 28,140 s, último commit 29,014 s, XACK/ACK aplicado 29,015 s, 0 rechazos/duplicados y cola final 0. La tasa fue 102,928891 eventos/s, superior a los 99,6 eventos/s requeridos para 2.988 eventos. La cifra 32,358 s era sólo una proyección previa y **no una medición**. Los dos intentos de harness incompatibles se conservan como `INVALID_RUN` y no integran el resultado.

## 7. Seguridad, notificaciones y durabilidad

- **mTLS agente/backend:** nueva evaluación real en localhost con TLS 1.3; acepta certificado confiable y rechaza ausencia de certificado, CA no confiable y certificado vencido. La ruta HTTP común no expone renovación. Identidad/revocación del agente se valida al autorizar la renovación.
- **Valkey:** la captura histórica usa `valkey://` y contiene tráfico legible. La verificación mTLS agente/backend no convierte esa captura en TLS.
- **HMAC:** aporta autenticidad e integridad del mensaje; no confidencialidad.
- **n8n A:** el receptor controlado persiste cada `notification_id` antes de 202 y separa `received_at`, `backend_dispatched_at`, `n8n_accepted_at` y `receiver_received_at`. Los relojes conservan sus offsets; no se midió un límite de sincronización.
- **n8n B:** `alerts` persiste `notification_id`, `attempt_count`, `next_retry_at` y estado terminal. En PostgreSQL 18.3 limpio se observaron cuatro intentos n8n fallidos seguidos por webhook controlado exitoso, fallo total persistido sin falso éxito y recuperación en un proceso nuevo con el mismo `notification_id`. Los delays fueron 0 sólo en el proceso de ensayo; producción conserva 5/30/120 s. La garantía es al menos una vez y el receptor deduplica por `notification_id`. SMTP real no fue acreditado. Se asume una única instancia backend.
- La DLQ implementada usa `alerts` (`failed_at`/`delivered_at`); no existe una tabla `failed_notifications` separada.
- La cadena distribuida es **al menos una vez**. “Exactamente una vez” sólo puede usarse para una transición concreta con idempotencia demostrada, no para todos los efectos.
- Una ejecución ampliada recolectó 62 pruebas: 55 aprobaron y 7 fallaron por el harness mTLS preexistente. No se atribuyen esos siete fallos a n8n ni se presenta esa ejecución como suite aprobada.

## 8. Baseline, restauración y cuarentena

- Baseline local: `/var/lib/fim-agent/baseline/<sha256(path)>.bin`, cifrado AES-256-GCM; secreto maestro en `/var/lib/fim-agent/secrets/master_secret`.
- Se conserva una entrada activa por ruta y hasta tres snapshots previos. El servidor conserva metadatos/hashes y cambios aprobados; no está acreditado como copia autónoma completa de todos los contenidos.
- Desde `8d37075`, el agente conserva un candidato local cifrado ligado a `source_event_id`, ruta, estado y hash. La aprobación sólo promueve ese contenido si coincide exactamente; si el archivo cambió, el candidato falta o corresponde a otro evento, falla cerrado. La restauración usa la baseline activa resultante, no una lectura tardía del archivo observado.
- Guardar secreto y ciphertext en el mismo host protege frente a copia aislada del soporte cifrado, no frente a adquisición completa ni frente a `root`.
- Desde `b060e5f`, la cuarentena automática y por comando usa un store común AES-256-GCM streaming con clave HKDF de dominio `quarantine-v1`, metadata cifrada, nombres opacos y artefactos 0400. Sólo elimina el origen después de escritura, fsync y readback autenticado; reintentos son idempotentes, una ruta recreada no se borra, symlinks se capturan como objeto y hardlinks fallan cerrado.
- Desde `947edb6`, la retención es configurable entre 1 y 365 días, con default 30; el mantenimiento corre al inicio y cada 24 h. Artefactos corruptos/desconocidos se preservan y degradan el estado en lugar de borrarse. La migración legacy es atómica/idempotente; como el formato viejo perdió el directorio original registra `original_path_known:false`, y el formato automático usa `ctime` como aproximación temporal.
- Esta protección cubre una copia aislada sin `master_secret`. No protege frente a `root`, host vivo comprometido, memoria de proceso ni adquisición que incluya el secreto. La retención elimina la entrada del directorio; no acredita borrado seguro del soporte.
- La reconciliación central compara estado reportado; no es atestación remota y no detecta necesariamente a un agente comprometido que miente.

## 9. Bloqueos que permanecen

1. Mantener los 19 casos históricos como explicación fuertemente sustentada pero no demostrable retrospectivamente; no presentarlos como causalidad probada.
2. Repetir Run 4 si se necesita caracterizar variabilidad; la corrida válida actual cumple, pero una única repetición no establece un SLA.
3. Ejecutar una corrida consolidada de agente, backend y frontend sobre un commit final congelado.
4. Ejecutar una prueba reducida de dos anfitriones con red real y TLS habilitado; no se realizó.
5. Acreditar SMTP con receptor controlado si se mantiene como canal del alcance; la evaluación durable comprobó el fallback webhook, no SMTP.
6. Regenerar la figura editable de NotificationDispatcher.
7. Identificar el código deontológico aplicable o retirar su invocación. La Res. AAIP 47/2018 no prescribe retención ilimitada.

## 10. Conclusión

Puede sostenerse que US-09, el límite mTLS agente/backend y los flujos n8n controlado y durable fueron implementados y verificados en evaluaciones nuevas y acotadas. También quedaron corregidos la atribución falsa a root, la invisibilidad de `FAN_Q_OVERFLOW`, el recorrido de eventos sin ruta, la promoción de baseline ligada al evento y el almacenamiento/retención de cuarentena. Puede sostenerse la cobertura Run 3 con su denominador, la reagregación correcta de latencia y el cumplimiento de drenaje Run 4 sólo para el laboratorio documentado.

No puede sostenerse validación integral: aunque el drenaje Run 4 cumple 30 s bajo condiciones controladas, la causalidad runtime de los 19 históricos no puede reconstruirse, falta la evaluación en dos anfitriones y SMTP real no fue acreditado. El estado correcto es **cierre parcial**, no aptitud productiva.

## 11. Aceptación de navegador añadida para US-03 y US-25

Playwright 1.63.0 con Chromium 1243 ejecutó ambas historias contra frontend actual, backend, PostgreSQL y Valkey reales. El paquete durable está en `docs/cierre/evidencia/us03-us25-playwright-20260910T205424Z/`.

US-03 quedó funcionalmente verde después de basar el scheduling en la duración `exp - iat` recibida, con validación y clamp; esto elimina el loop ante clock skew sin usar claims locales para autorizar. US-25 validó UX y parcialidad real con auditoría. El build productivo también pasó.

Ambas historias continúan PARCIAL únicamente por sus contratos divergentes: cookie Strict+`/auth/refresh` y bulk `event_ids[]` siguen BLOCKED. La rotación multi-key live y el comando/ACK/efecto de agente se ejecutaron sin mocks en un laboratorio aislado de estado, datos y recursos.

## Laboratorio aislado de reglas, rotación y acciones

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

Se incorporó un harness opt-in separado del Compose principal. Usa PostgreSQL, Valkey, PKI mTLS, estado del agente, baseline y watch directory propios. Aísla estado, datos y recursos de Compose, no el kernel del host: fanotify puede observar eventos fuera de `/watch`, que el filtro de alcance descarta y que no se persisten en la evidencia. Validó la rotación JWT live de US-03, cerró la aceptación funcional de US-16/US-17 y acreditó para US-25 la cadena firmada/versionada backend → agente → ACK → baseline cifrada. El defecto de accesibilidad de `RuleForm` queda registrado por separado.

La evidencia NO elimina divergencias de producto por decreto: US-03 continúa bloqueada por el contrato de cookie y US-25 por el wire canónico. Tampoco se atribuye `event_ack` a `rule_sync`; su recepción se midió mediante el `ruleset_version` persistido por el agente.

## Actualización Playwright: US-02, US-20 y US-31

La primera ejecución real del 2026-09-10 no completó estas historias. US-02 expuso que el frontend llamaba logout sin la autenticación exigida por backend; US-20 acreditó la cadena hasta el toast, mientras la reconexión quedó INCONCLUSA porque el modo offline no cerró el SSE abierto; US-31 acreditó toggle/URL/backend/reload, pero el ID del padre permanecía sólo en el tooltip. Ese resultado histórico se conserva en `evidencia/us02-us20-us31-playwright-20260910T212203Z/`.

Una corrección y reevaluación posterior resolvió US-02 y US-31. Para US-20 se observó cierre, reinicio, nueva request y un evento posterior, pero una revisión independiente detectó que el harness publicaba antes de acreditar la segunda respuesta SSE establecida. Por eso US-20 permanece parcial hasta repetir el ensayo con ese límite explícito. `evidencia/us02-us20-us31-fixed-20260910T233934Z/` se conserva como evidencia histórica y no se suma a la corrida inicial.

La repetición sobre un snapshot congelado (`evidencia/us02-us20-us31-fixed-us20cdp20260911T0205Z/`) eliminó la publicación anticipada, pero no produjo un resultado consecutivo: la primera corrida US-20 pasó 2/2 y la segunda falló 1/2 al no observar la segunda respuesta SSE dentro del límite. El fail-fast impidió ejecutar las combinadas previstas. La evidencia fue sanitizada y sellada en el camino de error; US-20 continúa parcial y el resultado no se presenta como defecto productivo concluyente.

El cierre metodológico posterior aisló el transporte mediante un proxy de laboratorio usado únicamente por `/alerts/stream`, manteniendo backend, API y refresh disponibles. En `evidencia/us02-us20-us31-fixed-us20isolated20260911T0220Z/`, dos corridas individuales US-20 2/2 y dos combinadas 5/5 pasaron sobre el mismo snapshot congelado. Cada reconexión acreditó stream inicial, cierre físico, API y refresh 200 durante el corte, segunda respuesta SSE establecida antes de publicar y toast de un evento real posterior. US-20 queda completa para sus criterios enumerados; el ensayo local no acredita HA ni todas las particiones de red posibles.

## 13. Resolución de los bloqueos contractuales de US-03 y US-25

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

La implementación posterior adoptó los contratos canónicos en vez de adaptar las pruebas al wire anterior. US-03 restringe la cookie de refresh a `SameSite=Strict; Path=/auth/refresh`, con migración de la cookie legacy y revocación enlazada por `refresh_jti`. La ventana de gracia valida también el JTI del refresh ganador, evitando que el replay de R0 resucite R1 después de logout o cambio de contraseña. US-25 usa exclusivamente `event_ids[]` y una acción compartida para reject; la forma `items[]` se rechaza con 422 y la respuesta bulk ya no expone `baseline_absent`.

La evidencia vigente es `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260911T015529Z/`: casos individuales PASS y conjunto de tres casos PASS dos veces, con backend, PostgreSQL, Valkey, frontend, PKI mTLS y agente reales dentro del laboratorio efímero. Los labels de RuleForm se validaron por nombre accesible; no se extrapola a accesibilidad global.

## 14. Ensayo multianfitrión con mTLS y TLS de Valkey (A-3) — 2026-09-12

> Corrección de redacción propuesta con detalle en `docs/cierre/CAMBIOS_PARA_TESIS_V11.md` §4.

El ensayo A-3 verificó, por primera vez, el sistema sobre **dos equipos físicos** distintos conectados por una red local doméstica: un servidor central en una laptop (`192.168.1.43`) y un agente FIM nativo bajo `systemd`, corriendo en un entorno virtual Python 3.13, en una **segunda PC física con Ubuntu 26.04.1 LTS instalado en disco** (`192.168.1.36`, sin virtualización). El plan preliminar consideraba monitorear esa PC mediante WSL2; se descartó antes de instalar el agente en favor del anfitrión de metal desnudo, y el nombre del runbook (`RUNBOOK_WSL2_MTLS.md`) se conserva sólo por trazabilidad con esa referencia anterior — el ensayo ejecutado no usó WSL2.

Se ejecutó sobre la línea de desarrollo `devel` a la fecha del ensayo (HEAD inicial `223f85c`), con las correcciones `f9a536a` (listener TLS de bootstrap dedicado en el puerto 8444, D52/RN-146), `f552aa6` (Authority Key Identifier en el certificado de Valkey) y `656b101` (preflight de escritura con `effective_ids`). **No se ejecutó sobre el candidato consolidado `7a7ee50`.**

**Resultados:** los siete puntos de control del runbook (preparación de la PC, preparación de la laptop, servidor central con TLS en Valkey, instalación/registro/bootstrap del agente, pruebas positivas, pruebas negativas y capturas, y cierre) aprobaron, con un punto parcial documentado. mTLS agente-backend y TLS con certificado de cliente en Valkey quedaron verificados de punta a punta, incluidos 9/9 rechazos negativos (V1–V4 en Valkey; B1–B3, E1–E2 en el backend) y capturas de tráfico en ambos extremos sin cadenas del protocolo en claro (413/297 paquetes en la laptop, 220/135 en la PC, en dos rondas).

**Hallazgos abiertos, no corregidos durante el ensayo:**

- `process_exe` llega vacío en los eventos generados en la PC.
- Un archivo nuevo se reportó como `file_modified` en lugar de `file_created`; los eventos `file_created` observados llegan con `diff_text` vacío.
- El primer arranque del agente frente a un stream `commands` compartido con historial (38.794 mensajes de agentes de laboratorio anteriores) generó más de 22.000 advertencias `detector.out_of_scope_drop` en los primeros 20 s y ruido transitorio en la bitácora; en régimen estable persisten del orden de 65 `detector.out_of_scope_drop` por minuto por superposición de sistemas de archivos.
- Reinstalar con `agent/install.sh` sobre una instalación existente anida el árbol de código (`cp -r` lo copia dentro de sí mismo) en lugar de reemplazarlo.
- El listener 8443 no emite una alerta TLS legible al rechazar un certificado de cliente inválido (corta la conexión con `unexpected eof`/`errno=104`), a diferencia de Valkey.

**Límites declarados:** red de área local doméstica con un único agente monitoreado y una sola corrida por prueba; no acredita despliegue en red de área amplia, alta disponibilidad ni rendimiento extrapolable (la prueba de 100 modificaciones del punto de control 5 no es una medición de rendimiento generalizable). El orquestador de notificaciones permaneció degradado durante el ensayo, por lo que no se ejerció la notificación externa entre dos anfitriones.

**Evidencia:** `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md` y `RUNBOOK_WSL2_MTLS.md`. El paquete está íntegramente versionado en git (66 archivos) y se verifica con su propio `SHA256SUMS`.

## 15. Aceptación de despliegue en un servidor remoto (A-4) — 2026-09-14/15

> Corrección de redacción propuesta con detalle en `docs/cierre/CAMBIOS_PARA_TESIS_V11.md` §4.

El ensayo A-4 verificó el procedimiento operativo de `docs/despliegue_servidor_remoto.md` contra infraestructura real: un **VPS público** (HostGator, Ubuntu 22.04.5, kernel 6.8, IP pública) como servidor central, y una **PC del operador** (Ubuntu 26.04, kernel 7.0) como host monitoreado, sin túnel ni red compartida. Código en `devel`, commit inicial `2f84d60`; las correcciones de hallazgos llegaron en `ed286d9..277a458`. **No se ejecutó sobre `7a7ee50`.**

**Resultados:** las seis tareas del grupo 12 del change `vps-deployment-readiness` aprobaron (arranque del stack sin editar YAML; puertos publicados correctos desde otro host; registro e instalación del agente con bootstrap por 8444 y eventos por 6380; consola HTTP/HTTPS con login y refresh; reinstalación sin anidar el código; `n8n: ok` con un POST real entregado por Gmail). Los siete hallazgos operativos detectados durante la corrida se corrigieron con pruebas en el grupo 14 antes de cerrar la evidencia: validación de versión de Python en `install.sh`, rutas relativas del instalador, secreto opcional en reinstalación de un agente ya enrolado, aplicación silenciosa de `ADMIN_PASSWORD` sobre un admin preexistente, reprovisioning de n8n en un `up -d` posterior, orígenes CORS del modo `self_signed`, y cuerpo vacío del correo de alerta.

**No verificado en este entorno:** que dos solicitudes con el mismo `event_id` produzcan un único ticket (el VPS no dispone de un sistema de tickets controlado); esa propiedad se cubrió en un ensayo aislado con n8n real, no en esta corrida. Los arreglos 14.5 y 14.7 se reverificaron con n8n real en un proyecto Docker aislado, pero no se repitieron en el VPS.

**Evidencia:** `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/README.md`. La carpeta hermana `docs/cierre/evidencia/a4-vps-20260915T145238Z/` corresponde a una corrida previa sin README ni `SHA256SUMS` propio. **Ninguna de las dos carpetas A-4 está versionada en git** (`.gitignore` las excluye con el patrón `/docs/cierre/evidencia/a4-vps-*/`); son evidencia local, no parte del paquete de cierre entregable en el repositorio.

## 16. Nota sobre la unificación de los commits V10 en `devel`

El 2026-09-15 se incorporaron a `devel` los commits del candidato V10 (carriles L1–L8 y L10, backlog y la corrección E2E; el carril L9 quedó excluido por superado) y se publicaron como `devel` `925dab5`. La regresión completa sobre esa rama aprobó: agente 597 pruebas aprobadas + 1 omitida; backend 754/754 con `TEST_VALKEY_TLS=1`; frontend 197/197 con comprobación de tipos y construcción; OpenSpec 44 especificaciones/249 requisitos.

**Esta regresión no es un candidato consolidado congelado con custodia** equivalente a los paquetes `final-consolidated-v10-*`: es una corrida de verificación posterior a la unificación de rama, sin bundle ni manifiesto de custodia propios. No sustituye una nueva validación consolidada, que sigue pendiente. Su evidencia primaria (`summary.json`) reside fuera de este repositorio, en un worktree local de la máquina de desarrollo, y no forma parte del paquete de cierre. **[CONFIRMAR POR EL AUTOR: si corresponde citar esta unificación en el cuerpo de la tesis y con qué alcance exacto.]**
