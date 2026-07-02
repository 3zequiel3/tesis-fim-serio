-- Migration 006: Severidad persistida en events (D34/RN-128, C38).
--
-- Agrega la columna severity a events, calculada al ingerir con la lógica
-- compartida de D-C15-01 (rules/service.py::determine_severity_for_path).
-- Backfill de filas preexistentes a 'low' — el default de D-C15-01 para paths
-- sin regla; no se recalcula contra el ruleset vigente porque atribuiría
-- severidades de reglas que podían no existir al momento del evento.
--
-- El tipo enum ruleseverity ya existe (creado por create_all para rules.severity).
--
-- Idempotente: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
-- Ejecutar el script dos veces no produce error.
--
-- Aplicar manualmente contra la base de datos de producción o test (D3, sin Alembic):
--   psql $DATABASE_URL -f 006_add_event_severity.sql

ALTER TABLE events ADD COLUMN IF NOT EXISTS severity ruleseverity NOT NULL DEFAULT 'low';

CREATE INDEX IF NOT EXISTS ix_events_severity ON events (severity);
