## Why

El corte de trazabilidad del 2026-09-16 (`devel`, `2475de8`, `docs/cierre/MATRIZ_TRAZABILIDAD.md`) deja el
backlog en **25 completas / 6 parciales / 0**. Tres parciales divergen del texto canónico (US-07, US-11,
US-21) y tres tienen un criterio implementado sin aserción (US-22, US-27, US-29). Además, cuatro historias
contadas como completas lo son gracias a ajustes de criterio hechos en `cc73c2d` (US-01, US-05, US-12,
US-23) que la matriz no declara de forma explícita. El Capítulo 5 no puede afirmar "31 de 31" mientras
el número dependa de divergencias abiertas o de reinterpretaciones no declaradas.

## What Changes

El change se organiza en **dos partes** ordenadas, cada una verificable y commiteable por separado.

**Parte 1 — código y tests (cierra US-07, US-21, US-22, US-27, US-29)**

- **US-07**: el selector de estado de `frontend/src/pages/Events.tsx` enumera los 7 estados. `superseded`
  aparece siempre, desmarcado y excluido por defecto (W1). Marcarlo activa `include_superseded`; apagar el
  toggle "Mostrar superseded" lo quita del filtro; un deep-link con `status=superseded` sin el toggle se
  normaliza al parsear la URL. Se conserva el ícono distintivo de US-31. Sin cambios en el backend.
- **US-21 (D72/RN-166)**: el heartbeat del agente agrega el booleano `queue_pressure_high` (`true` cuando
  `queue_pressure > 0.8`, calculado en el agente) y **conserva** el float `queue_pressure`. El backend lo
  persiste en una columna booleana nullable (migración aditiva e idempotente
  `021_add_agent_queue_pressure_high.sql`), con ingesta tolerante (mismo patrón que `out_of_scope_drops`
  del change 56) y lo expone en `GET /agents` y `GET /agents/{id}`. El banner W3 de `AgentCard` se deriva
  sólo del flag. Un agente sin la clave se lee `null` y no rompe nada.
- **US-22**: test del toast de confirmación del rescan (`Agents.tsx`).
- **US-27**: tests de las filas de `audit_log` de `login` y `logout`.
- **US-29**: aserciones HTTP de `last_error`, `retry_count` y `failed_at` en `GET /alerts/failed`.

**Parte 2 — declaraciones y trazabilidad (US-01, US-05, US-11, US-12, US-23 y recuento)**

- `docs/cierre/MATRIZ_TRAZABILIDAD.md` y `docs/trazabilidad_us_tests.md` pasan a **31/0/0**, con una tabla
  nueva **"Ajustes de criterio declarados"** (texto original, texto vigente, decisión, fecha, commit) y el
  **conteo estricto** —historias completas sin ningún ajuste— visible junto a 31/0/0.
- Decisiones declaradas: D70/RN-164 (US-01, US-27), D71/RN-165 (US-11), D6/RN-107 como reescritura de
  RN-102 (US-05, US-23, US-29), D66/RN-160 (US-12).
- Verificación: `scripts/check_spec_integrity.py` y suites completas de agente, backend (Postgres y Valkey
  reales) y frontend (typecheck, build, tests).
- Fuera de alcance: un nuevo candidato consolidado con cadena de custodia.

Sin cambios **BREAKING**: la clave nueva es aditiva y el float se mantiene.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `agent-transport`: el requisito del heartbeat incorpora `queue_pressure_high` junto al ratio.
- `backend-agent-management`: el consumer de heartbeat persiste y los endpoints exponen `queue_pressure_high`
  con ingesta tolerante y nullable.
- `frontend-agents`: el banner de presión de cola se deriva del flag booleano y no de un umbral en el
  cliente.
- `frontend-events`: el selector de estado enumera los 7 estados y mantiene la coherencia entre
  `superseded` y `include_superseded`.

US-22, US-27 y US-29 sólo agregan tests sobre comportamiento ya especificado; la parte 2 es documental.
Ninguna de las dos genera delta.

## Impact

- **Agente**: `agent/heartbeat.py`, `agent/queue.py` (constante de umbral), `agent/tests/`.
- **Backend**: `backend/app/modules/agents/{models,heartbeat_consumer,service}.py`,
  `backend/db/migrations/021_add_agent_queue_pressure_high.sql`, `backend/tests/test_heartbeat_consumer.py`,
  `test_agent_mgmt.py`, `test_auth.py`, `test_notifications.py`.
- **Frontend**: `frontend/src/pages/Events.tsx`, `frontend/src/utils/eventFilters.ts`,
  `frontend/src/api/agents.ts`, `frontend/src/components/ui/AgentCard.tsx` y sus tests; test nuevo de
  `Agents.tsx`.
- **Docs**: las dos matrices de trazabilidad. Las decisiones D70–D72 y el criterio 4 de US-11 ya quedaron
  cerrados en los docs canónicos antes de esta propuesta.
- **Dependencias**: change 55 (archivado); change 56 **archivado antes de aplicar** (mismos archivos, dueño
  de la migración `020`). El slice del agente se despliega antes de re-correr las baterías del Capítulo 5.
- **Reglas y decisiones**: W3, RN-84, RN-92, RN-94, RN-22, RN-98, W1, W20, US-31; D2, D6/RN-107,
  D66/RN-160, D69/RN-163 (patrón de ingesta), D70/RN-164, D71/RN-165, D72/RN-166.
