## Context

El backend marca notificaciones como entregadas que nunca salieron, y emite un payload que incumple RN-53. Ambos defectos comparten una causa raíz que está **en la spec, no en el código**: `openspec/specs/backend-notifications/spec.md` define requisitos para el retry, la cascada y la DLQ, y **ninguno para el payload**. Un contrato que ninguna spec describe y ningún test verifica sólo puede divergir.

Estado verificado al momento de escribir este diseño:

- `_build_payload` emite 7 campos: `alert_id`, `event_id`, `path`, `severity`, `agent_id`, `detected_at`, `alert_created_at`.
- RN-53 exige además la **acción tomada**, el **contexto de proceso** (`process_pid`, `process_uid`, `process_exe`) y `received_at`.
- `Event` **ya persiste** los cinco campos faltantes, más `is_symlink`, `action_failed`, `action_error` y `status`.
- `docker-compose.yml:138` fija `N8N_WEBHOOK_URL: ${N8N_WEBHOOK_URL:-http://n8n:5678/healthz}`.
- `backend-health/spec.md:11` **prescribe** `GET/HEAD {N8N_WEBHOOK_URL}` para el check de n8n.
- `notifier.py:70` pasa `start_tls=True` sin condición.
- `.env.example` no declara ninguna variable de notificación.

Restricciones que acotan el diseño: despliegue single-instance (RN-76), léxico canónico en `snake_case` (RN-71), y la semántica de `log_only` de D23/RN-120, que este change **no** altera.

## Goals / Non-Goals

**Goals:**

- Que el payload cumpla RN-53 completo, incluido el contexto forense de proceso.
- Que una divergencia futura entre lo que los workflows leen y lo que el backend emite **rompa CI**, no producción.
- Que un despliegue sin configurar reporte la verdad: canal no configurado.
- Que el health check no pueda emitir notificaciones como efecto secundario.
- Que SMTP funcione contra relays en 465 y contra relays internos sin TLS.

**Non-Goals:**

- Los workflows de n8n, el provisioning y el compose del servicio `n8n` → change 47.
- La durabilidad de la escalera, `retry_count` acumulativo, `last_error` por canal, `POST /alerts/test` y RN-92 per-agent → change 48.
- Cambiar la semántica de D23/RN-120.
- Deduplicación efectiva aguas abajo: este change **emite** `notification_id`; consumirlo es del change 47.
- Corregir retroactivamente las filas históricas falsamente `delivered` — es integridad de dato de tesis, se decide aparte.

## Decisions

### D-1. Sobre plano, no anidado

**Decisión**: `schema_version`, `notification_id` y `type` son hermanos de los campos de datos.

**Alternativa considerada y descartada**: `{"schema_version":…, "type":…, "data": {…}}`. Es la forma que uno elegiría por prolijidad, y es la que rompe cosas. La evidencia manda:

- `scripts/receptor_webhook.py` lee `payload.get("alert_id")`, `("event_id")`, `("severity")`, `("path")` **al tope del objeto**. Anidar deja esas columnas en `null` en el JSONL de la Batería 4 del Cap. 5.
- Los tres `n8n/workflows/*.json` leen `$json.body.<campo>` plano. Anidar obliga a reescribir cada expresión, mezclando este change con el 47.

El sobre plano preserva ambos consumidores y hace que la Batería 4 **no** necesite re-correrse. Costo: el espacio de nombres del payload es compartido entre sobre y datos. Se acepta — con `schema_version` presente, una migración futura a forma anidada es un cambio versionado, no una ruptura silenciosa.

### D-2. El fixture del test de contrato son los workflows reales

**Decisión**: el test lee `n8n/workflows/*.json` directamente y extrae `$json.body.<campo>` por expresión regular.

**Alternativa considerada**: un archivo de contrato intermedio en `contracts/`, como el que introdujo la change 45 para el contrato frontend↔backend. Se descarta acá porque la situación es distinta: en la change 45 los dos lados eran código propio y hacía falta un tercer artefacto neutral. Acá **el consumidor es un artefacto declarativo versionado en el repo**. Usar los workflows como fixture elimina la posibilidad de que el fixture y el consumidor real diverjan — que es exactamente el modo de falla que este test existe para prevenir.

**Riesgo asumido**: la extracción por regex es aproximada. Mitigación: el caso negativo obligatorio. Si el regex deja de matchear, el conjunto extraído queda vacío y el test **falla** en vez de pasar vacuamente. Sin esa aserción, vaciar el fixture volvería verde a un test que no verifica nada — la trampa que la change 45 documentó y pagó.

### D-3. `n8n_health_url` es un atributo independiente, no derivado

**Decisión**: `Settings.n8n_health_url` se configura explícitamente y **no** se deriva de `n8n_webhook_url`.

**Alternativa considerada**: derivarla parseando el host del webhook y reemplazando el path por `/healthz`. Descartada: adivina la topología. El webhook puede estar detrás de un proxy, de un path prefix o de un host distinto del de la UI, y una derivación equivocada devuelve el check al problema que D43/RN-137 corrige — pegarle a algo que no es un endpoint de salud. Una variable explícita es una línea más de configuración y ninguna suposición.

Consecuencia deliberada: quien configure el webhook y olvide el health URL verá `n8n: degraded`. Es correcto — el sistema no puede afirmar que n8n está sano si no tiene con qué comprobarlo.

### D-4. `notification_id` se genera al crear la notificación, no por intento

**Decisión**: un uuid v4 por notificación, reutilizado en todos los reintentos.

Es lo que lo hace útil como clave de deduplicación (D41/RN-135): si cambiara por intento, un receptor no podría distinguir un reintento de una notificación nueva — que es precisamente la ambigüedad a resolver. `retry_count` y `attempt` siguen siendo los contadores de intento; `notification_id` identifica **la notificación**.

Nota de implementación: hoy `_build_payload` se invoca una sola vez en `notify_event`, fuera del bucle de reintentos, así que la estabilidad sale gratis. El change 48 reestructura ese bucle en un barrido persistido — a partir de ahí `notification_id` deberá persistirse en la fila `alerts`. Este change **no** agrega la columna; sólo garantiza la estabilidad dentro del ciclo de vida actual del proceso.

### D-5. `smtp_starttls` y `smtp_ssl` como booleanos separados, con default retrocompatible

**Decisión**: dos flags, default `starttls=True` / `ssl=False`, que reproduce exactamente el comportamiento actual.

**Alternativa considerada**: un solo enum `smtp_security: starttls | ssl | none`. Es más limpio y evita por construcción el estado contradictorio. Se descarta por una razón concreta: dos booleanos con default explícito hacen que la migración sea de cero pasos para cualquier despliegue existente, mientras que un enum obliga a definir el valor. La combinación inválida (`ambos true`) se cubre con validación y un escenario de spec.

## Risks / Trade-offs

**[Riesgo] Un deploy limpio pasa a mostrar `n8n: degraded` y el banner de RN-101.**
→ Mitigación: es el comportamiento correcto y el objetivo declarado del change. Se documenta como nota de despliegue en el proposal y en `.env.example`. Requiere avisar antes de sacar capturas nuevas para el Cap. 5, porque las capturas previas muestran `ok` sobre una premisa falsa.

**[Riesgo] La extracción por regex de `$json.body.X` puede no cubrir todas las formas de expresión de n8n** (por ejemplo acceso con corchetes, o campos construidos dinámicamente).
→ Mitigación: el caso negativo detecta el fallo total de extracción. Para el fallo parcial, el change 47 reescribe los workflows y es el momento natural para acotar las formas de acceso admitidas. Se declara como limitación conocida en vez de simularse resuelta.

**[Riesgo] El sobre plano comparte espacio de nombres entre metadatos y datos.** Un campo de datos futuro llamado `type` colisionaría.
→ Mitigación: `schema_version` está presente desde el inicio, así que una reforma es versionada. Los tres nombres del sobre se eligen suficientemente específicos.

**[Trade-off] Ampliar el payload sin migrar las filas históricas** deja el dataset del Cap. 5 con notificaciones de dos formas distintas.
→ Se acepta: las filas históricas ya son inválidas por otra razón más grave (fueron marcadas `delivered` sin entrega real). Unificar la forma no arreglaría eso, y el arreglo real es una decisión de integridad de dato que se toma aparte.

## Migration Plan

1. `Settings` gana `n8n_health_url`, `smtp_starttls`, `smtp_ssl`. Los tres con default, así que ningún despliegue existente rompe al arrancar.
2. `_build_payload` se amplía. Ningún consumidor actual valida esquema estricto: el receptor de laboratorio usa `.get()` y guarda el crudo, y los workflows leen campos que siguen presentes con el mismo nombre.
3. `_check_n8n` pasa a `n8n_health_url`. Con la variable vacía reporta `degraded` — no rompe, informa.
4. Se saca el default del compose y se pueblan las variables en `.env.example`.

**Rollback**: revertir el commit. No hay migración de base de datos, ni cambio de forma en ningún endpoint, ni cambio en el agente. Un rollback parcial que dejara `Settings` nuevo con el código viejo es inofensivo: los atributos quedarían sin consumir.

**Orden de despliegue**: irrelevante — no hay coordinación con el agente ni con el frontend.

## Open Questions

1. **`schema_version` arranca en `1`, ¿y la política de versionado?** La propuesta es que un cambio aditivo no incremente y uno con remoción o renombre sí. Se puede fijar en el change 47, cuando haya un consumidor real que dependa de ello.
2. **¿`action_taken` es exactamente `Event.status`?** D35/RN-129 establece que el `status` derivado *es* la acción ejecutada, así que emitir ambos es redundante en el estado actual del modelo. Se emiten los dos por explicitud del contrato de RN-53; si el equipo prefiere uno solo, es un ajuste de una línea en el spec y en `_build_payload`.
3. **Las filas históricas falsamente `delivered`** (miles, durante el período en que el webhook apuntaba a `/healthz`) — anotar, purgar o declarar la limitación. Es integridad de dato de tesis y excede este change, pero conviene resolverlo **antes** de la defensa.
