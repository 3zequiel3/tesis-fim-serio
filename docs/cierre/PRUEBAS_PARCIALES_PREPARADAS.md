# Verificación dirigida de historias parciales

> **Estado vigente: pruebas dirigidas ejecutadas; US-20 cerró sus criterios enumerados mediante un corte aislado exclusivamente sobre la ruta SSE.**

Este documento consolida la preparación inicial y las ejecuciones posteriores. La evidencia funcional inicial de US-03/US-25 está en `us03-us25-playwright-20260910T205424Z/`; la integración exclusiva vigente es `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260911T015529Z/RESULTADO.md`.

## Resumen actual

| Alcance | Resultado | Límite |
|---|---:|---|
| Frontend dirigido preparado | **24 PASS** | Incluye `auth.store.test.ts` **4/4** después de agregar clock skew. No es la suite frontend completa. |
| Backend dirigido preparado | **6 PASS** | Cuatro casos US-20 y dos contratos multi-key unitarios; la rotación live se ejecutó aparte. |
| Playwright US-03/US-16/US-17/US-25 aislado | **1/1 + 1/1 + 1/1; conjunto 3/3 PASS dos veces** | Frontend/backend/DB/Valkey/agente reales; contratos canónicos incluidos. |
| Playwright US-02/US-20/US-31 posterior (histórico) | **1/1 + 2/2 + 2/2; conjunto 5/5 PASS** | Stack real aislado; la carrera metodológica de US-20 detectada después impide usar esta corrida para cerrar su reconexión. |
| Repetición US-20 sobre snapshot congelado | **run 1: 2/2 PASS; run 2: 1/2 FAIL; combinada no ejecutada** | La segunda corrida no observó una segunda respuesta SSE exitosa dentro del límite; por fail-fast no se ejecutaron las dos corridas combinadas requeridas. US-20 continúa parcial. |
| Repetición US-20 con proxy SSE aislado | **run 1: 2/2 PASS; run 2: 2/2 PASS; combinadas: 5/5 PASS dos veces** | Mismo snapshot congelado; backend/auth disponibles durante el corte; cierre acotado a los criterios de US-20. |
| Build frontend | **PASS** | `tsc -b && vite build`, 205 módulos. |

No se suman E2E y unitarios como si fueran una sola suite ni se reclasifica una historia sólo por estos conteos.

## Estado por historia

| Historia | Evidencia automatizada ejecutada | Criterios todavía pendientes |
|---|---|---|
| US-02 | Unitarias y Playwright real verifican Bearer, revocación access/refresh, cookie, limpieza local, redirección y Back seguro. | Criterios funcionales completos. |
| US-03 | Unitarias, Playwright de cookie/ruta/rotación/logout/reuso y rotación multi-key live PASS. | Criterios cubiertos; `Secure=false` sólo en lab HTTP dev. |
| US-16 | Playwright real: precarga por labels, edición, persistencia, audit, versión, outbox y recepción por agente PASS. | Criterios funcionales completos; no se afirma accesibilidad global. |
| US-17 | Playwright real: cancelar/confirmar, DELETE, persistencia, audit, sync y efecto `alert_only` PASS. | Criterios funcionales y labels del formulario completos; no se afirma accesibilidad global. |
| US-20 | Cadena real consumer→DB Alert→SSE→toast y reconexión real PASS en dos corridas individuales y dos combinadas. | Sin pendiente funcional dentro de los criterios enumerados; el ensayo sigue limitado a un corte local controlado y no acredita HA. |
| US-25 | Unitarias, wire `event_ids[]`, UX/parcialidad y approve real con comando firmado/versionado, ACK y efecto en baseline PASS. | Contrato canónico cubierto; legacy `items[]` rechazado 422. |
| US-31 | Unitarias y Playwright real verifican toggle/URL/request/reload y `parent_event_id` visible. | Criterios funcionales completos. |

## Correcciones verificadas durante este lote

- US-20: el FAIL inicial era drift del fixture; el evento positivo debía persistir severidad `critical`. Producción no se alteró para enseñar el test.
- US-03: Playwright descubrió un loop ante clock skew. El scheduler ahora usa la duración `exp - iat` desde recepción, valida/clampa hints y conserva autorización exclusivamente backend. RED: dos refresh inmediatos; GREEN: caso focal PASS, archivo 4/4 PASS, E2E PASS.
- US-25/build: `BulkResultRow.path` admite `null` con fallback accesible; se eliminó `replaceAll` incompatible con el `lib` actual. Build PASS.

## Comandos vigentes

```bash
cd frontend
pnpm exec vitest run \
  src/stores/auth.store.test.ts \
  src/components/ui/BulkActionBar.test.tsx
pnpm run build

FIM_E2E_RUN_DIR="../docs/cierre/evidencia/<run>/individual-us03" \
  pnpm exec playwright test e2e/us03-session-refresh.spec.ts
FIM_E2E_RUN_DIR="../docs/cierre/evidencia/<run>/individual-us25" \
  pnpm exec playwright test e2e/us25-bulk-actions.spec.ts
FIM_E2E_RUN_DIR="../docs/cierre/evidencia/<run>/combined" \
  pnpm exec playwright test e2e/us03-session-refresh.spec.ts e2e/us25-bulk-actions.spec.ts

cd ..
scripts/run-isolated-acceptance-lab.sh
scripts/run-us02-us20-us31-acceptance-lab.sh
```

## Criterio de cierre

- [x] Contratos automatizables preparados y ejecutados de forma dirigida.
- [x] US-03 y US-25 ejecutadas en navegador real para el alcance seguro.
- [ ] Resolver explícitamente los contratos de cookie y bulk wire.
- [x] Ejecutar multi-key live y agente/ACK en laboratorio exclusivo.
- [ ] Completar las verificaciones manuales/externas restantes antes de reclasificar historias.

## Ejecución posterior: US-02 / US-20 / US-31

Estas pruebas dejaron de estar sólo preparadas: fueron ejecutadas con Playwright y servicios reales. El resultado evaluado se conserva en `evidencia/us02-us20-us31-playwright-20260910T212203Z/`: dos casos PASS, dos FAIL y la reconexión US-20 INCONCLUSA/BLOCKED porque el método no cerró el SSE abierto. Los fallos y el bloqueo no se cuentan como aceptación aprobada ni como historia completa.

## Corrección posterior: US-02 / US-20 / US-31

El paquete histórico anterior se conserva sin reescribir sus resultados. La reevaluación posterior está en `evidencia/us02-us20-us31-fixed-20260910T233934Z/`: US-02 1/1, US-20 2/2 y US-31 2/2 individuales; conjunto 5/5 PASS. US-20 reemplazó el método inconcluso por una detención real del backend con cierre observado de la request SSE original, reinicio, nueva request y recepción de un evento nuevo. Esta evidencia posterior no se suma a la batería histórica.

La repetición metodológica sobre el snapshot inventariado `evidencia/us02-us20-us31-fixed-us20cdp20260911T0205Z/` no fue reproducible: US-20 pasó 2/2 en la primera corrida y falló 1/2 en la segunda al no establecer una segunda respuesta SSE antes del timeout. El trap sanitizó y selló también este camino de FAIL. Las corridas combinadas no se ejecutaron por fail-fast; por lo tanto, este paquete es diagnóstico y no acredita el cierre de US-20.

La corrida vigente `evidencia/us02-us20-us31-fixed-us20isolated20260911T0220Z/` sustituyó el corte ambiguo del backend por un proxy exclusivo del laboratorio para `/alerts/stream`. El backend y autenticación permanecieron accesibles: API y refresh devolvieron 200 durante cada corte. Tras restaurar el proxy, la prueba esperó la segunda respuesta SSE exitosa antes de publicar y recibió el toast del evento real. Pasaron dos ejecuciones individuales 2/2 y dos combinadas 5/5 sobre el mismo snapshot congelado.

## Actualización de cierre canónico — 2026-09-11

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

US-03 y US-25 ya no conservan los bloqueos contractuales de cookie/wire. La corrida vigente `us03-us16-us17-us25-isolated-20260911T015529Z/` valida cookie/ruta/rotación/revocación, wire `event_ids[]`, rechazo 422 de `items[]`, comando/ACK/efecto y los labels asociados de RuleForm. Las corridas anteriores permanecen como evidencia histórica de los defectos, no como estado vigente.
