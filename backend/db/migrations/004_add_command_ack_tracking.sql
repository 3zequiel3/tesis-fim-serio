-- Migration 004: Command ack execution tracking (D30/RN-124, C36).
--
-- Agrega columnas de tracking de EJECUCIÓN a published_commands, ortogonales
-- a la columna `status` de outbox preexistente (pending|published, H6/D9/D10),
-- que esta migración NO toca.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
-- Ejecutar el script dos veces no produce error.
--
-- Aplicar manualmente contra la base de datos de producción o test (D3, sin Alembic):
--   psql $DATABASE_URL -f 004_add_command_ack_tracking.sql

ALTER TABLE published_commands ADD COLUMN IF NOT EXISTS command_id VARCHAR;
ALTER TABLE published_commands ADD COLUMN IF NOT EXISTS ack_status VARCHAR;
ALTER TABLE published_commands ADD COLUMN IF NOT EXISTS acked_at TIMESTAMP;
ALTER TABLE published_commands ADD COLUMN IF NOT EXISTS error TEXT;
ALTER TABLE published_commands ADD COLUMN IF NOT EXISTS event_id INTEGER;

CREATE UNIQUE INDEX IF NOT EXISTS ix_published_commands_command_id
    ON published_commands (command_id);

CREATE INDEX IF NOT EXISTS ix_published_commands_event_id
    ON published_commands (event_id);
