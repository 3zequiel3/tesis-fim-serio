## Why

El agente FIM detecta cambios en el filesystem (C09) pero aún no sabe qué hacer con ellos: sin motor de decisión, todos los eventos se publican como `alert_only` sin distinción. Este change implementa la lógica que evalúa cada evento contra las reglas de decisión cacheadas localmente y ejecuta la acción correspondiente (`auto_restore`, `quarantine`, `manual_review` o `alert_only`), cerrando el loop de detección→acción en el agente sin dependencia de conectividad al backend.

## What Changes

- **Nuevo módulo `agent/rules.py`**: cache local de reglas de decisión, recibidas vía comando `rule_sync` desde el backend. Evaluación glob con negación `!` (exclusiva gana sobre inclusiva). Default `alert_only` si ninguna regla matchea (RN-05, RN-06, RN-07, RN-65).
- **Nuevo módulo `agent/journal.py`**: journal pre/post-acción en `/var/lib/fim-agent/journal/{event_id}.json`. Estado `pending` → `completed` | `failed`. Rehidratación al arrancar: reintenta `pending` automáticas o las marca `failed` con reporte (RN-83).
- **Nuevo módulo `agent/decision.py`**: orquesta evaluación de reglas + ejecución de acción + escritura de journal. Ejecuta `auto_restore` y `quarantine` offline con reglas cacheadas; encola evento igual (RN-42).
- **Acciones implementadas**:
  - `auto_restore`: restaura el archivo desde el contenido del baseline (content_b64), verifica hash SHA-256, publica evento `auto_restored` (RN-30–33).
  - `quarantine`: mueve el archivo a `/var/lib/fim-agent/quarantine/{event_id}_{filename}` (RN-34–37).
  - `manual_review`: pasa sin acción adicional; el evento queda `pending` para revisión humana.
  - `alert_only`: pasa sin acción adicional; publicación normal.
- **Modificación `agent/detector.py`**: conecta `DecisionEngine` antes de publicar al stream; el detector delega la acción pre-publicación.
- **Modificación `agent/__main__.py`**: inicializa `DecisionEngine` con `RulesCache` y `JournalManager`; rehidrata journal en bootstrap; conecta callback `on_rule_sync` al publisher.

## Capabilities

### New Capabilities

- `agent-decision-engine`: evaluación de reglas glob con negación, cache local, 4 acciones con journal transaccional y rehidratación de acciones pendientes al arrancar.

### Modified Capabilities

_(ninguna — el wiring en `__main__.py` y el callback `on_rule_sync` en el publisher son detalles de implementación, no cambios de requisitos en specs existentes)_

## Impact

- **`agent/rules.py`** (nuevo) — RulesCache: parse del payload `rule_sync`, evaluación glob con fnmatch + negación `!`, persistencia del ruleset en `/var/lib/fim-agent/state.json`.
- **`agent/journal.py`** (nuevo) — JournalManager: escritura/lectura de entradas JSON en `/var/lib/fim-agent/journal/`, rehidratación al arrancar.
- **`agent/decision.py`** (nuevo) — DecisionEngine: orquestador de evaluación + acción; llama a BaselineEngine para leer content_b64 en auto_restore.
- **`agent/detector.py`** (modificado) — `_process_event` invoca `DecisionEngine.evaluate_and_act(detected_change)` antes de publicar.
- **`agent/__main__.py`** (modificado) — inicialización de RulesCache, JournalManager, DecisionEngine; rehidratación journal en startup; callback `on_rule_sync`.
- **Dependencias**: BaselineEngine (C07) para leer content_b64 y hash en auto_restore; PersistentQueue (C08) para encolar el evento tras ejecutar la acción.
- **Sin HTTP**: toda sincronización de reglas vía Valkey Streams (comando `rule_sync`, RN-79). No se abre ningún puerto en el agente (RN-108, D8).
