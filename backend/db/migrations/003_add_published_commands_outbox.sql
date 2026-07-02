-- Migration 003: Extiende published_commands a un outbox pending/published (H6).
--
-- Idempotente: ADD COLUMN IF NOT EXISTS, backfill antes de tocar constraints,
-- DROP NOT NULL solo si aplica. Ejecutar el script dos veces no produce error.
--
-- H6: el fan-out rule_sync ahora persiste el payload firmado completo como
-- `pending` en la misma transacción que avanza ruleset_version, y un
-- background task lo publica de forma diferida con retry, marcándolo
-- `published` al confirmar el XADD. Las filas preexistentes (siempre
-- síncronas, ya publicadas) se backfillean como `published`.
--
-- Aplicar manualmente contra la base de datos de producción o test (D3, sin Alembic):
--   psql $DATABASE_URL -f 003_add_published_commands_outbox.sql

ALTER TABLE published_commands ADD COLUMN IF NOT EXISTS payload TEXT DEFAULT '';
ALTER TABLE published_commands ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'published';

UPDATE published_commands
SET status = 'published'
WHERE status IS NULL;

ALTER TABLE published_commands ALTER COLUMN published_at DROP NOT NULL;

CREATE INDEX IF NOT EXISTS ix_published_commands_status ON published_commands (status);
