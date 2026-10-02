# LANE L10 — US-24 (paths monitoreados) — criterios UI

Fuente: docs/historias_de_usuario.md §US-24. Criterios 4–10 (infraestructura:
persistencia PostgreSQL, comando `update_config` firmado HMAC, reload en
caliente fanotify, baseline scan + AES-256-GCM, `event_ack`, bootstrap desde
`config.yaml`, `audit_log`) ya demostrados por el lab fanotify privilegiado de
la lane L7 — fuera de alcance de esta lane (UI only).

| # | Criterio (verbatim) | Archivo:línea | Test | Resultado |
|---|---|---|---|---|
| C1 | "En la sección de Agentes, se muestra la lista de paths actualmente monitoreados por cada agente." | `frontend/src/components/ui/AgentCard.tsx:259-273` | `AgentCard.test.tsx` — describe "AgentCard — lista de paths monitoreados (US-24/C1)" > "muestra todos los watch_paths actualmente monitoreados por el agente" | PASS (ya soportado, sin cambios de producción) |
| C2 | "Existe la opción de agregar un nuevo path al listado." | `frontend/src/components/ui/AgentCard.tsx:91-97,227-240` (`handleAddPath`, input + botón "Agregar") | `AgentCard.test.tsx` — describe "AgentCard — agregar un nuevo path (US-24/C2)" > "agrega el path escrito al listado y lo envía en onConfigSave al guardar" | PASS (ya soportado, sin cambios de producción) |
| C3 | "Existe la opción de quitar un path existente del listado." | `frontend/src/components/ui/AgentCard.tsx:99-101,217-223` (`handleRemovePath`, botón "Quitar" por ítem) | `AgentCard.test.tsx` — describe "AgentCard — quitar un path existente (US-24/C3)" > "quita el path seleccionado del listado y lo envía sin él en onConfigSave al guardar" | PASS (ya soportado, sin cambios de producción) |
| C11 | "Si el agente está en estado `draining`, los botones de guardar configuración quedan deshabilitados (ver US-30)." | `frontend/src/components/ui/AgentCard.tsx:243-249` (botón "Guardar paths") | `AgentCard.test.tsx` — describe "AgentCard — botón de guardar deshabilitado durante drenaje (US-24/C11, ver US-30)" > "el botón \"Guardar paths\" está deshabilitado con el tooltip canónico cuando el agente está draining" y "un agente que ya está draining al abrir la tarjeta no puede llegar a guardar (Editar deshabilitado)" | **FAIL → PASS** (gap real, fix de producción aplicado — ver abajo) |

## Gap real encontrado (C11)

El botón "Editar" ya estaba deshabilitado con `disabled={isDraining}` (lane
L5/US-30), lo que impide *entrar* en modo edición mientras el agente está
draining. Pero el botón "Guardar paths" (dentro del modo edición) solo tenía
`disabled={isSavingConfig}` — sin condición sobre `isDraining`.

Escenario real: el usuario abre la edición de paths mientras el agente está
`online`; antes de hacer clic en "Guardar", el polling de `useAgents` refresca
la lista y el agente pasa a `draining` (p. ej. por un shutdown iniciado desde
otra pestaña o por el propio host). El componente re-renderiza con el mismo
`editingPaths=true` pero `agent.status === 'draining'` — el botón "Guardar
paths" seguía habilitado, violando literalmente el criterio C11 ("si el
agente está en estado draining, los botones de guardar configuración quedan
deshabilitados").

### RED (sensibilidad confirmada)

`.v10-evidence/l10/RED-agentcard.log` / `RED-agentcard.junit.xml`:
1 test falló — "el botón \"Guardar paths\" está deshabilitado..." — con el
código de producción sin tocar (18/19 tests de AgentCard pasaban, probando
que C1/C2/C3 ya estaban soportados y que el único test sensible al gap real
era el de C11).

### Fix mínimo aplicado

`frontend/src/components/ui/AgentCard.tsx` — botón "Guardar paths":

```diff
- disabled={isSavingConfig}
+ disabled={isSavingConfig || isDraining}
+ title={isDraining ? DRAINING_TOOLTIP : undefined}
```

Reusa la constante `DRAINING_TOOLTIP` ya existente (mismo tooltip canónico
que "Editar" y "Rescan", D36/RN-93/W17).

### GREEN

`.v10-evidence/l10/GREEN-agentcard.junit.xml` — 19/19 tests de AgentCard.
`.v10-evidence/l10/GREEN-full.junit.xml` — 197/197 tests de todo el frontend.

## Verificación

- `pnpm exec vitest run` (full, junit): 34 archivos, 197 tests — todos PASS.
  Log: `GREEN-full.junit.xml`.
- `pnpm run typecheck`: sin errores. Log: `typecheck.log`.
- `pnpm run build`: build OK (warning de tamaño de chunk pre-existente, no
  relacionado). Log: `build.log`.
- `python3 scripts/check_spec_integrity.py`: "OK — 44 main specs, 249
  requisitos, sin problemas." Log: `spec-integrity.log`.
