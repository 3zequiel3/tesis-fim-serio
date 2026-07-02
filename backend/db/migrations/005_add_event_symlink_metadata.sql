-- Migration 005: Symlink metadata on events (D33/RN-127, C39).
--
-- Agrega las columnas is_symlink/symlink_target a events para persistir el
-- metadato de symlink-as-object reportado por el agente (C39, refina D31/RN-125).
--
-- Idempotente: ADD COLUMN IF NOT EXISTS. Ejecutar el script dos veces no produce error.
--
-- Aplicar manualmente contra la base de datos de producción o test (D3, sin Alembic):
--   psql $DATABASE_URL -f 005_add_event_symlink_metadata.sql

ALTER TABLE events ADD COLUMN IF NOT EXISTS is_symlink BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE events ADD COLUMN IF NOT EXISTS symlink_target VARCHAR;
