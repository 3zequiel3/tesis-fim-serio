## Context

El agente FIM tiene ahora detector reactivo (C09), transporte bidireccional (C08) y baseline cifrado (C07). El eslabón que falta es el motor de decisión: tras detectar un cambio, el agente debe aplicar las reglas configuradas por el administrador sin depender de conectividad al backend. Las reglas llegan por el comando `rule_sync` (Valkey Streams) y se cachean localmente. El motor debe ser offline-first: mientras el backend esté inalcanzable, las acciones automáticas (`auto_restore`, `quarantine`) se ejecutan igual con las reglas cacheadas.

Restricciones hard:
- Sin servidor HTTP en el agente (RN-108, D8). Todo via Valkey Streams.
- `ruleset_version` monotónico — descartar comandos con versión menor al último aplicado (RN-75).
- Journal transaccional: escribir `state: pending` antes de actuar, luego `completed` o `failed` (RN-83).
- Rehidratación en startup: journal con `state: pending` → reintento (automáticas) o reporte (manuales).

## Goals / Non-Goals

**Goals:**
- Evaluación de reglas glob con negación `!`, orden exclusiva-gana-sobre-inclusiva (RN-05, RN-65).
- Default `alert_only` cuando ninguna regla matchea (RN-06).
- Ejecución de las 4 acciones: `auto_restore`, `quarantine`, `manual_review`, `alert_only` (RN-07).
- Journal transaccional pre/post-acción en `/var/lib/fim-agent/journal/` (RN-83).
- Rehidratación journal en bootstrap (RN-83).
- Cache local persistida en `state.json`; recarga vía `rule_sync` con HMAC + `ruleset_version` (RN-75, RN-79).
- Comportamiento offline: acciones automáticas se ejecutan con caché; evento se encola (RN-42).

**Non-Goals:**
- Creación o edición de reglas — solo el backend las define (RN-07).
- Comunicación directa agente↔agente.
- Ejecución de acciones en el backend (restore, quarantine son siempre locales en el agente).
- Evaluación de reglas con expresiones arbitrarias más allá de glob+negación.

## Decisions

### D1: Tres módulos separados en lugar de un monolito

`agent/rules.py` (cache + evaluación glob), `agent/journal.py` (I/O de journal), `agent/decision.py` (orquestación) se mantienen separados.

**Por qué**: Permite testear la evaluación glob pura sin I/O, y el journal sin depender de la lógica de acciones. Alternativa: todo en `decision.py`. Rechazado porque mezcla responsabilidades y hace los tests más complejos.

### D2: Evaluación glob con fnmatch + negación por orden de declaración

Algoritmo: iterar las reglas en orden de declaración. Si la regla empieza con `!`, es exclusiva (skip path). Si matchea y es inclusiva, recordar la acción. Al final, si alguna exclusiva matcheó → `alert_only` sin importar inclusivas previas. Si solo inclusivas matchearon → acción de la primera con mayor prioridad (primera declarada). Si ninguna matcheó → `alert_only` (RN-06).

Concretamente: exclusiva (`!` prefix) gana sobre cualquier inclusiva (RN-65).

**Por qué**: Simple, determinista, sin dependencia externa. Alternativa: regex completo. Rechazado: innecesario para el modelo de reglas FIM.

### D3: Rules persistidas dentro de state.json bajo clave "rules"

```json
{
  "ruleset_version": 7,
  "rules": [
    {"pattern": "/etc/**", "action": "auto_restore", "negated": false},
    {"pattern": "!/etc/mtab", "action": null, "negated": true}
  ]
}
```

**Por qué**: `state.json` ya existe (C05), un solo archivo atómico, fácil de leer/escribir. Alternativa: archivo separado `rules.json`. Rechazado: introduce una segunda fuente de verdad sin beneficio real.

### D4: Journal como archivos JSON individuales por event_id

`/var/lib/fim-agent/journal/{event_id}.json` con campos: `event_id`, `path`, `action`, `state` (`pending`|`completed`|`failed`), `created_at`, `updated_at`, `error` (opcional).

**Por qué**: Un archivo por evento permite eliminar entradas completadas de forma atómica con `os.unlink()`. Alternativa: log append-only. Rechazado: la rehidratación requiere escanear solo los `pending`, lo cual es más caro con un log append-only.

### D5: auto_restore usa content_b64 del BaselineEntry

Para restaurar, `DecisionEngine` llama `baseline.read_entry(path)` y decodifica `entry.content_b64`. Si `content_b64` es `None` (archivo binario > 1 MB o marcado como `oversize`), la restauración falla gracefully con `state: failed`.

**Por qué**: El baseline ya tiene el contenido cifrado/decodificado. No hay que mantener una copia extra. El hash SHA-256 del contenido restaurado se compara con `entry.hash` para verificar integridad (RN-31).

### D6: quarantine mueve el archivo, no lo copia

`shutil.move(path, quarantine_path)` donde `quarantine_path = /var/lib/fim-agent/quarantine/{event_id}_{basename}`. Si el archivo ya no existe (borrado entre la detección y la cuarentena), journal marca `failed` con error `file_not_found`.

**Por qué**: Mover es atómico en el mismo filesystem; una copia doble el uso de disco innecesariamente.

### D7: Rehidratación journal en bootstrap, solo para acciones automáticas

En `__main__.py`, antes de iniciar el detector, `JournalManager.rehydrate()` escanea `/var/lib/fim-agent/journal/` en busca de entradas con `state: pending`. Para `auto_restore` y `quarantine` pendientes: reintenta la acción. Para `manual_review` y `alert_only` pendientes: los marca `failed` con `error: "rehydrated_without_action"` y los re-publica como `alert_only`.

**Por qué**: Las acciones automáticas pueden completarse sin intervención humana. Las manuales requieren que el backend esté al tanto y tenga el evento completo, por lo que re-publicarlas como `alert_only` garantiza que aparezcan en la UI.

## Risks / Trade-offs

- **Archivo borrado durante quarantine** → Mitigation: `JournalManager` escribe `failed` + loguea; el evento aún se publica para que el admin lo vea.
- **content_b64 None en auto_restore** → Mitigation: `failed` en journal; evento se publica con `action_failed: true` en el payload.
- **Race condition: dos eventos rápidos sobre el mismo path, uno aún en journal pending** → Mitigation: deduplicación ya resuelta en C09 (`parent_event_id`); el segundo evento se encola; ambos se evalúan contra el estado del baseline en ese momento.
- **rules.json vacío al arrancar** → Mitigation: RulesCache inicia vacío y devuelve `alert_only` para todo hasta recibir el primer `rule_sync`. Comportamiento correcto según RN-06.
