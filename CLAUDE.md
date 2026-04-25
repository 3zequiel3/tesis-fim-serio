# CLAUDE.md — FIM Platform

## Identidad del proyecto

Tesis de grado: **File Integrity Monitoring (FIM) Platform** para hosts Linux.

Stack:
- **Backend**: Python 3.13 + FastAPI 0.136 + SQLModel + PostgreSQL 18.3 + Valkey 9.0.3
- **Agente**: Python + pyfanotify 0.3.0 + systemd (con `CAP_SYS_ADMIN`)
- **Frontend**: Vite + React 19 + TypeScript + Tailwind v4 (CSS-first, sin tailwind.config.js)
- **Notificaciones**: n8n 2.16.1
- **Deployment**: Docker Compose (single-instance backend, RN-76)

Estado: documentación 100% terminada y validada (Abril 2026). Implementación pendiente.

## Documentación canónica

Toda decisión técnica y de producto vive en estos 4 docs + el roadmap:

- [docs/arquitectura_stack.md](docs/arquitectura_stack.md) — stack, modelo de eventos, decision engine, baseline cifrado AES-GCM, mTLS, máquina de estados
- [docs/flujo_de_usuario.md](docs/flujo_de_usuario.md) — flujos UI/UX por pantalla
- [docs/historias_de_usuario.md](docs/historias_de_usuario.md) — historias priorizadas
- [docs/reglas_de_negocio.md](docs/reglas_de_negocio.md) — 16 dominios, ~108 reglas (RN-01 a RN-108)
- [CHANGES.md](CHANGES.md) — roadmap de 20 changes en 4 hitos (M1 → M4)

**Importante**: los appendices "Decisiones de auditoría — Abril 2026" y "Decisiones de implementación — Abril 2026" en `reglas_de_negocio.md` y `arquitectura_stack.md` **prevalecen** sobre el contenido previo en caso de conflicto.

## Workflow canónico: OPSX (MANDATORIO)

**Toda implementación pasa por OPSX**, el flujo CLI-driven construido sobre el `openspec` CLI. **No se escribe código sin pasar por una OPSX change.** El `openspec` CLI es la única fuente de verdad sobre el estado de los artefactos — nunca asumir, siempre consultar.

### Flujo OPSX

```
/opsx:explore   (opcional — pensar antes de comprometer)
       │
       ▼
/opsx:propose   (crear change + todos los artefactos en un paso)
       │
       ▼
/opsx:apply     (implementar tasks del change)
       │
       ▼
/opsx:archive   (sync de specs + cerrar el change)
```

El flujo es **fluido**: cualquier paso se puede re-correr, cualquier artefacto se puede actualizar, cualquier acción se puede ejecutar en cualquier momento. No hay phase locks.

### Slash commands del proyecto

Definidos en [.claude/commands/opsx/](.claude/commands/opsx/):

- `/opsx:explore [topic]` — modo exploración (pensar, sin implementar)
- `/opsx:propose [change-name]` — crear nueva change con todos los artefactos
- `/opsx:apply [change-name]` — implementar las tasks de una change
- `/opsx:archive [change-name]` — archivar la change y sincronizar specs

### Skills disponibles

Definidas en [.claude/skills/](.claude/skills/) — se cargan automáticamente por contexto y aparecen en autocomplete:

- `openspec-explore`
- `openspec-propose`
- `openspec-apply-change`
- `openspec-archive-change`

### Agentes (orquestador + equipo de fase)

El flujo lo coordina el agente **`sdd-orchestrator`** (opus) definido en [.claude/agents/sdd-orchestrator.md](.claude/agents/sdd-orchestrator.md). El orquestador NO ejecuta — delega cada fase a un sub-agente dedicado en contexto fresco con el modelo asignado:

| Sub-agente | Modelo | Wrap de skill | Cuándo se invoca |
|------------|--------|---------------|------------------|
| [`opsx-explore`](.claude/agents/opsx-explore.md) | sonnet | `openspec-explore` | exploración / thinking partner |
| [`opsx-propose`](.claude/agents/opsx-propose.md) | opus | `openspec-propose` | crear change + artefactos |
| [`opsx-apply`](.claude/agents/opsx-apply.md) | sonnet | `openspec-apply-change` | implementar tasks |
| [`opsx-archive`](.claude/agents/opsx-archive.md) | haiku | `openspec-archive-change` | sync specs + cerrar change |

Reglas del orquestador:
- Consulta el estado vía `openspec list --json` y `openspec status --change "<name>" --json` antes de actuar.
- Delega a `opsx-<phase>` vía la `Agent` tool — NO carga skills inline en su propio contexto.
- NO replica lógica de las skills.
- NO bloquea por phase gates — OPSX es fluido.

### Configuración del proyecto

| Parámetro | Valor | Por qué |
|-----------|-------|---------|
| Modelo del orquestador | **opus** | Coordina y decide arquitectura (definido en frontmatter del agente) |
| Project ID en engram | `tesis-fim-serio` | Usar siempre en `mem_save`, `mem_search` |
| Change names | mismo kebab-case que CHANGES.md | Trazabilidad 1:1 roadmap ↔ change |
| Layout de artefactos | `openspec/changes/<name>/` (gestionado por CLI) | NO crear estructura manualmente |

### Antes de `/opsx:propose`

1. Verificar que el change esté en [CHANGES.md](CHANGES.md) y que sus dependencias del DAG estén satisfechas (changes previos archivados o equivalente).
2. Si surge una **nueva suposición** durante la exploración o el diseño que NO esté cerrada en los appendices de decisiones: **detener el flujo**, agregar la decisión al appendix "Decisiones de implementación — Abril 2026" del doc canónico que corresponda, y recién entonces continuar. No avanzar con suposiciones tácitas.

### Excepciones al workflow

Las siguientes tareas NO requieren OPSX y se pueden hacer inline:
- Edición de documentación canónica (docs/, CHANGES.md, este CLAUDE.md)
- Bug fixes triviales (typo, link roto, una línea)
- Configuración de tooling (`.claude/settings*.json`, hooks, skills, agentes)

Todo lo demás (modelos, endpoints, módulos, features de frontend, scripts del agente FIM) → OPSX obligatorio.

## Convenciones del proyecto

- **Idioma del usuario**: rioplatense (voseo). El asistente responde en el mismo registro.
- **Commits**: conventional commits. **Nunca** "Co-Authored-By" ni atribución a IA.
- **Léxico canónico de eventos** (RN-71): minúsculas snake_case en código, schemas, JSON, logs y docs técnicas → `pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`. Mayúsculas solo en títulos markdown o botones de UI en prosa narrativa.
- **Estructura backend**: `backend/app/{core,modules}/` con módulos por dominio (events, rules, agents, alerts, auth, users, audit, health).
- **Estructura agente FIM**: `agent/` con módulos por responsabilidad (config, logging, state, detector, baseline, rules, actions, publisher, heartbeat, queue, bootstrap).
- **Estructura frontend**: `frontend/src/{api,stores,pages,components/{ui,layout},hooks}/` con TanStack Query + Zustand.
- **Sin servidor HTTP en el agente FIM** (RN-108, D8). Todo backend ↔ agente vía Valkey Streams.
- **Cross-cutting** (logging sanitizado, rate limit, trace_id) viaja con el primer feature que lo necesita (D7), no se centraliza al final.

## Engram

Memoria persistente siempre activa. Usar `project: "tesis-fim-serio"` en todos los `mem_save` / `mem_search`.

Topic keys importantes ya en uso:
- `implementation/roadmap` — CHANGES.md y su evolución
- `implementation/decisions-2026-04-24` — las 8 decisiones D1-D8
- `workflow/canonical-rule` — esta regla (OPSX como workflow obligatorio)
- `sdd/<change-name>/{explore,proposal,design,tasks,apply-progress,archive-report}` — observaciones SDD-relacionadas por change (la fuente de verdad de los artefactos siempre es el filesystem `openspec/changes/<name>/`, no engram)
