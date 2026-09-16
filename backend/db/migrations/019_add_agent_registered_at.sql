-- Migration 019: Agrega `registered_at` (timestamptz NOT NULL) a agents (D68/RN-162).
--
-- Sin esta columna, un agente recién registrado nace `offline` con
-- `last_heartbeat IS NULL`. La segunda pasada de _sweep_offline
-- (heartbeat_consumer.py) compara `last_heartbeat < dead_threshold`, y en SQL
-- `NULL < x` es `NULL`: la fila nunca matchea. El agente no se marca `dead`
-- antes de tiempo, se queda `offline` para siempre, indistinguible de uno que
-- latió hace un minuto.
--
-- `registered_at` da a esos agentes una referencia temporal propia: la
-- segunda pasada del barrido usa `registered_at < dead_threshold` para los
-- agentes sin heartbeat, reutilizando el mismo `_DEAD_THRESHOLD_S` (300 s) que
-- ya rige la transición a `dead` — sin introducir un umbral nuevo.
--
-- Backfill: las filas existentes toman el instante de la migración (`now()`)
-- como `registered_at`, ya que no hay forma de reconstruir cuándo se
-- registraron realmente. DEFAULT now() cubre además cualquier insert que no
-- lo especifique explícitamente (la app siempre lo hace vía
-- default_factory en Agent.registered_at).
--
-- Idempotente: ADD COLUMN IF NOT EXISTS; el backfill solo toca filas con
-- registered_at IS NULL; SET NOT NULL / SET DEFAULT son no-op si ya están
-- aplicados. Ejecutar el script dos veces no produce error.
--
-- Migrations are applied by hand (D3) — this one included. Apply with:
--   psql $DATABASE_URL -f 019_add_agent_registered_at.sql

ALTER TABLE agents ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ;

UPDATE agents
SET registered_at = now()
WHERE registered_at IS NULL;

ALTER TABLE agents ALTER COLUMN registered_at SET DEFAULT now();
ALTER TABLE agents ALTER COLUMN registered_at SET NOT NULL;
