# Resultados verificados

> Estados: `CUMPLE`, `NO CUMPLE`, `PARCIAL`, `NO EVALUABLE`, `HISTÓRICO — NO REVALIDADO`. Cada fila separa el resultado original de la nueva evaluación.

| Indicador | Criterio original | Resultado original disponible | Resultado final de este corte | Condiciones / denominador / exclusiones | Estado | Evidencia |
|---|---|---|---|---|---|---|
| Pruebas backend históricas | Suite sin fallos | 494/494 aprobadas | No reejecutadas sobre HEAD | Denominador 494 | HISTÓRICO — NO REVALIDADO | `resultados/bateria2_backend.xml` |
| Pruebas agente históricas | Suite sin fallos | 418: 417 aprobadas, 1 omitida | No reejecutadas sobre HEAD | Denominador 418; una omisión | HISTÓRICO — NO REVALIDADO | `resultados/bateria2_agente.xml` |
| Total histórico | Conteo reproducible | 912: 911 aprobadas y 1 omitida | Dirime el valor 675 para esa corrida | Suma exacta de ambos JUnit | CUMPLE | JUnit Batería 2 |
| Coverage backend Run 3 | Porcentaje con denominador | Sin reporte histórico equivalente | 2484/2780 statements = **89,35 %**; 570 passed, 2 skipped, 0 failed | 572 tests; 296 missing, 3 excluded, branch off; Valkey real opt-in omitido; listener mTLS deshabilitado sólo en harness; snapshot manifestado anterior a HEAD | CUMPLE | `docs/cierre/evidencia/20260909-coverage-run3/` |
| Historias | 31 historias trazadas | 3 completas, 27 parciales, 1 sin cobertura funcional | **10 completas, 21 parciales, 0 sin cobertura funcional** | US-02/03/16/17/20/25/31 cerraron criterios canónicos mediante verificaciones posteriores; US-09 avanzó sólo a parcial porque no implementa el modo binario ni la biblioteca exigida. No implica 31/31 historias completas | PARCIAL | `docs/cierre/MATRIZ_TRAZABILIDAD.md` |

La cifra de cierre **10/21/0** surge de clasificar las 31 historias contra sus criterios canónicos: **10 + 21 + 0 = 31**. Los recuentos anteriores se conservan sólo como cortes históricos y no se fusionan como si fueran una única suite.
| US-09 | Todos los criterios canónicos del visor de diferencias | Sin implementación funcional en el corte histórico | Implementación textual en `8039624` + `f08626a`; snapshot limpio: compilación/serialización PASS, 10/10 agente y 10/10 backend; además 41 backend/agente + 7 frontend dirigidas | Texto UTF-8 acotado a 1 MiB; binarios/controles descartados. No implementa comparación de hashes + hex dump para binarios ni usa `react-diff-viewer-continued`; tampoco hay prueba específica integral de logs y nomenclatura hashes/tamaño | PARCIAL | `docs/historias_de_usuario.md` §US-09; commits y tests citados en la matriz |
| D49–D51 | Atribución honesta y brechas de detección observables | UID desconocido podía degradarse a root; overflow fanotify no generaba evidencia; backend perdía `event_type`/path nulo | Implementado en `b70934d` e integrado en `b8e9513`: `null` conserva atribución no resuelta; `detection_gap` representa `FAN_Q_OVERFLOW`; eventos sin ruta persisten, filtran y renderizan sin falsa supersesión | Ventana monotónica de 60 s limita la emisión bajo saturación; no demuestra que se recuperen eventos ya perdidos por el kernel | CUMPLE | commits y regresiones de agente/backend/frontend |
| Baseline aprobada ligada al evento | Restaurar/aprobar una versión legítima aun si el archivo cambia | El hash aprobado podía quedar asociado a contenido anterior | `8d37075` conserva candidato cifrado por `source_event_id` y valida identidad, ruta, estado, hash y bytes antes de promoverlo | Límite de 10 MiB para contenido; candidato ausente/obsoleto/inconsistente falla cerrado; no es almacenamiento central completo | CUMPLE | `agent/tests/test_baseline.py`, `agent/tests/test_commands.py`, `backend/tests/test_actions.py` |
| Ingesta backend Unidad 1 | Reducir cuello sin desactivar controles | 8 sentencias SQL/evento | 5 sentencias SQL/evento; **32 pruebas dirigidas PASS** | Mantiene HMAC, persistencia, deduplicación, XACK y ACK; una instancia backend | CUMPLE | commit `965dcac`; `backend/tests/test_drain_backend_unit1.py` |
| Detección B3 | 500 operaciones reportables | 493 eventos | 7 operaciones efectivas identificadas, causa interna no probada | Denominador 500; secuencias 193, 196, 209, 270, 323, 364, 369 | PARCIAL | `resultados/bateria3_manifiesto.jsonl`, `resultados/bateria3_latencias.csv` |
| Offline B5 | 3.000 operaciones preservadas | 2.988 eventos | 12 ausencias identificadas, sin causa individual comprobada | Denominador 3.000 | PARCIAL | `resultados/bateria5_manifiesto.jsonl`, `resultados/RESULTADOS.md` |
| Corrida causal actual | Clasificar operación→baseline→kernel→decisión→cola→backend | No disponible históricamente | 60 operaciones: 50 eventos con cadena completa y persistencia; 10 retornos a baseline aprobada suprimidos legítimamente; 0 ausencias nuevas inexplicadas | `ext4`, fanotify nativo en contenedor con capabilities, servicios aislados y reloj monotónico compartido; no reconstruye B3/B5 | CUMPLE | `docs/cierre/evidencia/absence-20260910T052521Z-r2/RESULTADO.md`, traza/correlación/SHA256SUMS del mismo paquete |
| Drenaje B5 histórico | Menor a 30 s | 153 s | 19,529 eventos/s; objetivo 99,6 eventos/s para 2.988 | Sin timestamps por etapa | NO CUMPLE | `resultados/cronologia_utc.txt`, `resultados/RESULTADOS.md` |
| Drenaje Run 3 | Menor a 30 s | No aplica | 3.000/3.000, 51,773 s = 57,945 eventos/s; mejora de 101,227 s frente al histórico | 0 rechazos, 0 duplicados, 3.000 XADD, cola final 0; HMAC/PostgreSQL/XACK/ACK durable activos; rate limit experimental 100.000/60 vs default 100/60; implementación `7c5afa5` | NO CUMPLE | `docs/cierre/evidencia/drenaje-20260910-run3/RESULTADO.md`, `summary.json`, `metrics.jsonl`, `source-manifest.sha256`, `SHA256SUMS` |
| Drenaje Run 4 — backend Unidad 1 | Menor a 30 s | No aplica; 32,358 s fue sólo una proyección | 3.000/3.000, **29,146335596 s = 102,928891 eventos/s** | 3.000 planificados/efectivos; 0 rechazos/duplicados; 3.000 XADD/XREAD/HMAC/commit/XACK/event_ack; cola final 0; mismos controles y rate limit experimental de Run 3; copia limpia de `965dcac`; dos intentos inválidos excluidos | CUMPLE sólo en laboratorio documentado | `docs/cierre/evidencia/drenaje-20260910-run4-unit1/RESULTADO.md`, `summary.json`, `metrics.jsonl`, `invalid-runs/`, `source-manifest.sha256`, `SHA256SUMS`; evidencia `864b672` |
| FIFO offline | 0 fuera de orden | 0/2.988 | Sin nueva corrida | 12 ausencias no son ordenables | HISTÓRICO — NO REVALIDADO | `resultados/bateria5_manifiesto.jsonl` |
| Duplicados offline | 0 | 0 históricos | Run 4: 0 mensajes duplicados entre 3.000 publicaciones | Rutas únicas; no prueba deduplicación temporal de una misma ruta | CUMPLE | `resultados/bateria5_manifiesto.jsonl`; `docs/cierre/evidencia/drenaje-20260910-run4-unit1/summary.json` |
| Latencia Tabla 1 | P99 <1.000 ms | El informe usó el tramo más corto `received_at-detected_at`: 17,274 ms | Reagregación `received_at-marca post-operación`: n=493, media 11,316, P50 12,639, P95 16,798, P99 **17,745 ms** | No es corrida nueva; la marca post-operación no prueba el instante físico exacto | CUMPLE | `scripts/generador_carga.py:579-619`, manifiesto y latencias B3 |
| Notificaciones B4 | 1.000; niveles 1/10/100 | 329 muestras de 360 operaciones | Sin repetición equivalente | 60/60, 99/100, 170/200; tasas reales 1/50/100 ops/s; receptor HTTP local, no n8n | PARCIAL | `resultados/bateria4_todos.csv`, `resultados/bateria4_webhook.jsonl` |
| Captura Valkey | Inventario consistente | Documento: 662 paquetes | `capinfos`: 660 paquetes | Discrepancia de 2 preservada | PARCIAL | `resultados/bateria55_valkey.pcap`, `resultados/RESULTADOS.md` |
| TLS Valkey | Transporte cifrado | `valkey://` en la corrida | No revalidado con TLS | Captura legible | NO CUMPLE | `resultados/bateria55_valkey.pcap` |
| mTLS agente/backend | Handshake mutuo real | No acreditado históricamente | Handshake válido y scope seguro; rechazo sin certificado, CA no confiable y certificado vencido | Un test E2E localhost PASS, TLS 1.3; no es ensayo de dos hosts; revocación de identidad se prueba en autorización de renovación | CUMPLE | `28f87fe`, `backend/tests/test_mtls_transport.py`, tests de renovación/PKI |
| Renovación de certificado | Pre-expiry, identidad segura, rotación | No acreditada | Misma clave pública, nuevo serial, identidad/revocación fail-closed; CA legacy exige recuperación administrativa | Pruebas focales, no operación prolongada | CUMPLE | `backend/tests/test_agent_cert_renewal.py`, `agent/tests/test_cert_renewal.py`, `backend/tests/test_c22_pki.py` |
| n8n unidad A | Backend → n8n → receptor externo controlado | B4 no pasó por n8n | Éxito 202; receptor caído 502 sin falso éxito; n8n caído error de transporte; recuperación 202 | n8n 2.17.8, receptor SQLite controlado, un host, destinatario sintético | CUMPLE | `f0a2907`, `n8n/e2e/evidence/20260909-run.json` |
| n8n unidad B durable | Persistencia, reintento tras reinicio y fallbacks | Tests unitarios del dispatcher | 9 pruebas dirigidas PASS; PostgreSQL limpio: cuatro intentos n8n fallidos → webhook controlado entregado; fallo total persistido; recuperación tras restart con mismo `notification_id` | Delays 0 sólo en ensayo; producción 5/30/120 s; una instancia backend; entrega al menos una vez con deduplicación del receptor | CUMPLE | `e2519eb`, `3bec584`, `n8n/e2e/evidence/20260910-durable-fallback.json` |
| Fallbacks externos | n8n→SMTP→webhook→log | Tests unitarios | Fallback webhook real acreditado después de cuatro fallos n8n; fallo de todos los canales persiste sin falso éxito | SMTP real y proveedor comercial no acreditados; log terminal no es entrega externa | PARCIAL | `n8n/e2e/evidence/20260910-durable-fallback.json`, `backend/tests/test_notifications.py` |
| Ejecución ampliada de notificaciones | Suite ampliada sin fallos | No aplica | 62 recolectadas: 55 passed, 7 failed | Los 7 fallos provienen del harness mTLS preexistente; no se atribuyen a n8n; no es una suite aprobada | PARCIAL | salida de ejecución no preservada como artefacto durable; 9 pruebas focales sí constan en evidencia n8n |
| `mmap` | Caracterizar limitación | 30/30 | Sin nueva corrida adversarial | 10 repeticiones por caso; no midió demora adversarial | PARCIAL | `resultados/bateria8/` |
| Cuarentena | Contenido protegido y retención definida | Histórico: contenido/nombres en claro y sin cleanup | U1 cifra contenido+metadata con AES-256-GCM streaming y nombres opacos; U2 aplica retención default 30 días, configurable 1..365, al inicio/cada 24 h y migra legacy reconocido | 76/76 + 50/50 dirigidas PASS; protege copia aislada sin secreto, no root/host vivo/adquisición con secreto; corruptos/desconocidos se preservan degradados; legacy sin directorio original y `ctime` aproximado | CUMPLE con límites declarados | `b060e5f`, `947edb6`; `agent/tests/test_quarantine.py`, `agent/tests/test_quarantine_maintenance.py` |
| Dos hosts | Red real y TLS habilitado | No ejecutado | No ejecutado | 0 corridas distribuidas | NO EVALUABLE | cronología y topología históricas |
| Figura NotificationDispatcher | Fuente editable alineada al código | Raster sin fuente | No regenerada | Figura 6, 1840×1280 | NO CUMPLE | `docs/Tesis.pdf`, servicio/notifier |
| Código deontológico | Fuente institucional precisa | Invocación genérica | No identificado | Retirar o completar referencia | NO EVALUABLE | tesis y bibliografía actuales |
| AAIP 47/2018 | Retención/destrucción justificadas | Interpretación imprecisa | La resolución aprueba medidas recomendadas y contempla destrucción segura; no prescribe retención ilimitada | Debe justificarse finalidad y proporcionalidad | PARCIAL | https://www.argentina.gob.ar/normativa/nacional/resoluci%C3%B3n-47-2018-312662/texto |

## Límite de la evaluación n8n

La unidad B está incorporada. Permanece pendiente únicamente la entrega SMTP real si ese canal continúa en el alcance, además de cualquier prueba multinstancia, que está fuera de la arquitectura aprobada de una sola instancia backend. No presentar el receptor webhook controlado como proveedor comercial.

## Aceptación Playwright US-03 / US-25 — 2026-09-10

La ejecución corregida está en `docs/cierre/evidencia/us03-us25-playwright-20260910T205424Z/`.

- **US-03 funcional:** E2E individual y combinado PASS después de corregir el scheduler para usar `exp - iat` desde la recepción; revocación, navegación y Back también PASS.
- **US-25 funcional:** selección/modal/cancelación, parcial real 11+1, resumen, conciliación, refresco y 11 auditorías PASS.
- **Pendientes:** cookie Strict+`/auth/refresh` y wire `event_ids[]` son decisiones contractuales BLOCKED. La rotación multi-key live y el comando/ACK/efecto agente ya fueron ejecutados en el laboratorio aislado de estado, datos y recursos.
- **Build:** `tsc -b && vite build` PASS después de admitir path nulo con fallback y eliminar `replaceAll` incompatible.

El conjunto Playwright fue **2/2 PASS**, pero ninguna historia pasa a COMPLETA mientras existan criterios BLOCKED.

## Laboratorio aislado US-03 / US-16 / US-17 / US-25 — 2026-09-10

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

El paquete `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260910T235332Z/` conserva la corrida reproducible sobre un project Compose con estado, datos y recursos propios. Resultados: build frontend PASS; rotación live US-03 PASS (200/200/401/200); US-16/17 individual 1/1 PASS; US-25 individual 1/1 PASS; conjunto ordenado 2/2 PASS. El teardown dejó 0 contenedores, 0 volúmenes y 0 redes del lab, eliminó el directorio temporal y conservó sin cambios el stack principal. El aislamiento no incluye el kernel: fanotify puede observar eventos externos a `/watch`, pero el filtro de alcance los descarta. La accesibilidad de los `label` de `RuleForm` continúa pendiente por separado.

US-16 y US-17 pasan a **COMPLETA**. US-03 y US-25 permanecen **PARCIAL** exclusivamente por las divergencias contractuales ya registradas: cookie `Lax`+`/` frente a `Strict`+`/auth/refresh`, y wire `items[]`+`baseline_absent` frente a `event_ids[]`. El laboratorio no resolvió esas decisiones mediante tests ni atribuyó ACK a `rule_sync`.

## Playwright US-02 / US-20 / US-31 — ejecución histórica de 2026-09-10

Evidencia: `docs/cierre/evidencia/us02-us20-us31-playwright-20260910T212203Z/`.

- **US-02: FAIL.** Logout respondió 401, no borró cookie ni revocó tokens y Back abrió `/dashboard`.
- **US-20: PARCIAL.** Cadena real consumer→DB Alert→SSE→toast PASS; reconexión **INCONCLUSA/BLOCKED** porque `setOffline(true)` no cerró el SSE abierto y el método no ejerció una reconexión real. No se atribuye FAIL a producción.
- **US-31: PARCIAL.** Toggle/URL/request/reload PASS; `parent_event_id` visible FAIL.
- **Balance histórico exacto:** 2 casos PASS, 2 casos FAIL y 1 criterio INCONCLUSO/BLOCKED. **Build:** PASS. Esa corrida no reclasificó las historias.

## Corrección y reevaluación posterior de US-02 / US-20 / US-31 — 2026-09-10

Evidencia: `docs/cierre/evidencia/us02-us20-us31-fixed-20260910T233934Z/`.

- **US-02: PASS.** El cliente envía el Bearer a `POST /auth/logout`; la corrida real verificó respuesta 200, eliminación de cookie, rechazo posterior del access y refresh, redirección y Back seguro.
- **US-20: PENDIENTE METODOLÓGICO.** La cadena real hasta el toast permanece PASS. La corrida de reconexión observó cierre, nueva request y evento, pero una revisión independiente demostró que publicaba antes de acreditar la segunda respuesta SSE establecida.
- **US-31: PASS.** El enlace conserva su semántica accesible y ahora representa `parent_event_id` como texto visible; toggle, URL, backend y persistencia tras reload también pasaron.
- **Balance posterior:** los conteos ejecutados se conservan, pero no cierran US-20 por la carrera metodológica. El paquete no se suma aritméticamente a la batería histórica.

Una repetición adicional sobre snapshot congelado e inventariado quedó registrada en `evidencia/us02-us20-us31-fixed-us20cdp20260911T0205Z/`. US-20 obtuvo 2/2 PASS en la primera corrida y 1/2 en la segunda: tras el corte real se observó la nueva solicitud, pero no una segunda respuesta SSE exitosa dentro de 60 s. El runner se detuvo antes de las combinadas. El resultado confirma que el cierre no es reproducible y mantiene US-20 como **PARCIAL**; no demuestra por sí solo un defecto productivo.

La evaluación vigente está en `evidencia/us02-us20-us31-fixed-us20isolated20260911T0220Z/`. El laboratorio agregó un proxy físico exclusivo para `/alerts/stream`, sin cambiar endpoints productivos: dos corridas US-20 2/2 y dos combinadas 5/5 pasaron sobre el mismo snapshot. En las cuatro reconexiones se observó cierre del stream, API y refresh 200 durante el corte, segunda respuesta SSE exitosa antes de publicar un único evento y toast posterior. US-20 queda **COMPLETA** respecto de sus criterios enumerados, limitada a este corte local controlado.

## Cierre canónico US-03 / US-25 y labels de RuleForm — 2026-09-11

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

El paquete `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260911T015529Z/` reemplaza como evidencia vigente a las corridas contract-block anteriores, que se conservan como historial. Backend dirigido: 66/66 PASS sobre PostgreSQL efímero. Frontend dirigido: 19/19 PASS. Build: PASS. Playwright aislado: US-03 1/1, US-16/17 1/1, US-25 1/1, y suite combinada 3/3 PASS en dos ejecuciones consecutivas. Teardown: cero contenedores, volúmenes y redes residuales; stack principal healthy y sin cambio de identidad.

US-03 cumple `SameSite=Strict` y `Path=/auth/refresh`, usa una URL same-origin exacta, elimina la cookie legacy amplia y revoca el refresh mediante `refresh_jti` cuando la cookie acotada no corresponde a logout/change-password. La corrección de seguridad posterior verifica además que el refresh ganador de la ventana de gracia siga vigente: tras revocar R1, tanto R1 como su predecesor R0 responden 401. US-25 adoptó el wire canónico sin alias legacy; `items[]` da 422. RuleForm asocia labels/controles y expone el error del pattern mediante ARIA; esto no constituye una afirmación de accesibilidad global.

## Ensayo multianfitrión A-3 y aceptación VPS A-4 — 2026-09-12 / 2026-09-15

> Detalle y redacción propuesta para el cuerpo de la tesis en `docs/cierre/CAMBIOS_PARA_TESIS_V11.md` §4. Ninguna de las dos evaluaciones corrió sobre el candidato consolidado `7a7ee50`.

| Indicador | Resultado | Condiciones / denominador | Estado | Evidencia |
|---|---|---|---|---|
| mTLS agente-backend y TLS con certificado de cliente en Valkey, dos equipos físicos | 9/9 rechazos negativos (V1–V4 Valkey; B1–B3, E1–E2 backend); 0 cadenas del protocolo en claro en captura de tráfico de ambos extremos | Laptop (servidor central) + segunda PC física con Ubuntu 26.04.1 LTS en disco, sin virtualización, conectadas por LAN doméstica; `devel` HEAD `223f85c` + `f9a536a` + `f552aa6` + `656b101` | CUMPLE, límites declarados | `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md`, `RUNBOOK_WSL2_MTLS.md` |
| 100 modificaciones, publicación → confirmación (journal PC) | n=100/100; mín 6,1 ms, mediana 17,4 ms, p95 23,1 ms, máx 43,8 ms | Un agente, una corrida, red local doméstica | No extrapolable a rendimiento | ídem |
| 100 modificaciones, detección → recepción (reloj de dos equipos) | n=100; mín 6,7 ms, mediana 26,1 ms, p95 199,5 ms, máx 291,7 ms | Reloj no sincronizado entre ambos equipos | No extrapolable | ídem |
| Corte de backend (120 s) | eventos 2 a 10 con detección → recepción entre 114,9 y 123,0 s; 11 re-publicaciones, 10 confirmaciones, 0 descartes | Un agente, una corrida | Informativo | ídem |
| Aceptación de despliegue en VPS público (grupo 12, `vps-deployment-readiness`) | 6/6 tareas PASA (con hallazgos operativos corregidos) | VPS HostGator Ubuntu 22.04.5 + PC del operador Ubuntu 26.04; `devel` `2f84d60` + correcciones `ed286d9..277a458` | PASA, límites declarados | `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/README.md` |
| Deduplicación de tickets con mismo `event_id` en VPS | No verificado en este entorno | El VPS no dispone de un sistema de tickets controlado; propiedad cubierta en un ensayo aislado previo, no en A-4 | NO EVALUABLE en A-4 | ídem |

**Hallazgos abiertos declarados por A-3 (no corregidos durante el ensayo):** `process_exe` vacío en eventos generados en la PC; un archivo nuevo reportado como `file_modified` en lugar de `file_created`, con `diff_text` vacío en los `file_created` observados; avalancha inicial de 38.794 mensajes históricos del stream `commands` compartido (más de 22.000 `detector.out_of_scope_drop` en los primeros 20 s, ~65/minuto en régimen estable); `agent/install.sh` anida el árbol de código al reinstalar sobre una instalación existente; el listener 8443 no emite alerta TLS legible al rechazar un certificado de cliente inválido.

**Verificación de integridad de las carpetas de evidencia:** `a3-multihost/` está íntegramente versionado en git (66 archivos, `git ls-files`) y se verifica con `sha256sum -c SHA256SUMS` dentro de esa carpeta. Las carpetas `a4-vps-acceptance-20260915T153824Z/` y `a4-vps-20260915T145238Z/` **no están versionadas** (0 archivos bajo control de versiones; excluidas por `.gitignore:62`, patrón `/docs/cierre/evidencia/a4-vps-*/`); son evidencia local únicamente.
