-- Migration 001: Agrega el valor 'revoked' al tipo enum agent_status.
--
-- Idempotente: IF NOT EXISTS garantiza que ejecutar el script dos veces no produce error.
-- Soportado en PostgreSQL 12+ (incluyendo PG 18.3 usado en este proyecto).
--
-- Aplicar manualmente contra la base de datos de producción o test:
--   psql $DATABASE_URL -f 001_add_agent_status_revoked.sql

ALTER TYPE agentstatus ADD VALUE IF NOT EXISTS 'revoked';
