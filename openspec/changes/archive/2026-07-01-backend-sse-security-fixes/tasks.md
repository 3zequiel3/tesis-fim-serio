## 1. FIX-02 — AgentStatus.revoked (hacerlo primero: afecta migración de BD)

- [x] 1.1 Inspeccionar `backend/db/migrations/` para determinar el prefijo numérico del próximo script
- [x] 1.2 Agregar `revoked = "revoked"` al enum `AgentStatus` en `backend/app/modules/agents/models.py`
- [x] 1.3 Crear script `backend/db/migrations/NNN_add_agent_status_revoked.sql` con `ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'revoked'` (NNN = próximo número secuencial)
- [x] 1.4 Verificar que el script sea idempotente ejecutándolo dos veces en el contenedor de test
- [x] 1.5 En `backend/app/modules/events/consumer.py`: agregar check `agent.status != AgentStatus.revoked` antes de procesar cada mensaje; si revocado → log INFO + descartar
- [x] 1.6 En `backend/app/modules/agents/heartbeat_consumer.py`: agregar el mismo check por `AgentStatus.revoked` → log INFO + descartar heartbeat
- [x] 1.7 Correr suite completa (`pytest`) para confirmar que los 257+ tests existentes siguen en verde

## 2. FIX-01 — Sesión DB y cola SSE acotada

- [x] 2.1 En `backend/app/modules/alerts/stream.py`: wrappear la fase de replay en `async with session:` que se cierra explícitamente antes de entrar al bucle `while True`; verificar que la sesión no es referenciada después del cierre
- [x] 2.2 En `backend/app/modules/alerts/stream.py` (o donde se inicializa la cola): reemplazar `asyncio.Queue()` por `asyncio.Queue(maxsize=100)`
- [x] 2.3 Agregar manejo de `asyncio.QueueFull` en el productor de eventos SSE: descartar el evento nuevo (drop-newest) y emitir `logger.warning(...)` con contexto del stream
- [x] 2.4 Verificar en `backend/app/modules/alerts/router.py` que el ciclo de vida de la sesión sea consistente con el cambio de 2.1 (ajustar dependencia inyectada si aplica)
- [x] 2.5 Correr suite completa para confirmar regresión cero

## 3. FIX-03 — PublishedCommand para todos los tipos de comando

- [x] 3.1 En `backend/app/modules/actions/streams.py`: extraer la lógica de inserción de `PublishedCommand` a una función auxiliar `_record_published_command(session, agent_id, command_type, payload_json)` (o inline si el módulo es pequeño)
- [x] 3.2 Llamar a esa lógica para los tipos `restore_file`, `quarantine_file` y `baseline_update` además de `rule_sync` — la inserción debe ocurrir antes del `XADD` a Valkey, dentro de la misma transacción de sesión
- [x] 3.3 Correr suite completa para confirmar regresión cero

## 4. Tests de regresión

- [x] 4.1 Escribir test de regresión para FIX-01 sesión DB: verificar que el pool no retiene sesión abierta durante el lifetime SSE (puede ser un test de integración que inspeccione el pool después del replay)
- [x] 4.2 Escribir test de regresión para FIX-01 cola acotada: verificar que con 101 eventos encolados, el 101° se descarta y hay un WARNING en logs
- [x] 4.3 Escribir test de regresión para FIX-02 event consumer: crear agente con `status=revoked`, publicar mensaje en stream, confirmar que no se procesa
- [x] 4.4 Escribir test de regresión para FIX-02 heartbeat consumer: agente `revoked` → heartbeat descartado, `last_seen` no actualizado
- [x] 4.5 Escribir test de regresión para FIX-03: publicar cada tipo de comando (`restore_file`, `quarantine_file`, `baseline_update`, `rule_sync`) y verificar que existe registro `PublishedCommand` para cada uno
- [x] 4.6 Correr la suite completa con los nuevos tests; confirmar que todos pasan

## 5. Documentación de limitaciones conocidas (D27 y D28)

- [x] 5.1 En `docs/arquitectura_stack.md` appendix "Decisiones de implementación — Abril 2026": agregar nota explícita bajo D27 que `shared_secret_hex` se almacena en plaintext en DB y que key wrapping / KMS es trabajo futuro
- [x] 5.2 En `docs/arquitectura_stack.md` appendix "Decisiones de implementación — Abril 2026": agregar nota bajo D28 que el heartbeat consumer con `last_id="$"` pierde heartbeats durante restart del backend, produciendo falso positivo `offline` de <30s, y que este comportamiento es aceptable para la tesis
- [x] 5.3 Revisar que las notas de D27 y D28 no contradigan contenido previo en los docs; ajustar si hay conflicto

## 6. Commit y cierre

- [x] 6.1 Commit fix(agents): add revoked status + consumer guard — cubre FIX-02 y migración SQL
- [x] 6.2 Commit fix(alerts): bounded SSE queue + DB session release after replay — cubre FIX-01
- [x] 6.3 Commit fix(actions): record PublishedCommand for all command types — cubre FIX-03
- [x] 6.4 Commit docs(arch): document D27/D28 as known limitations — cubre tarea 5
- [x] 6.5 Correr suite completa final y confirmar verde antes de marcar el change como completo
