-- Migration 002: Agrega el campo `email` (NOT NULL + UNIQUE) a la tabla users.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS, backfill antes de endurecer NOT NULL,
-- índice UNIQUE con IF NOT EXISTS. Ejecutar el script dos veces no produce error.
--
-- Backfill: las filas existentes (p. ej. el admin sembrado antes de esta
-- migración) no tienen email real todavía. Se backfillea con un placeholder
-- derivado de `username` (único, ya que `username` es UNIQUE) para poder
-- endurecer NOT NULL sin perder filas; el seed de aplicación (ADMIN_EMAIL)
-- sobrescribe el valor real del admin en el próximo `seed_admin()` si el
-- admin es recreado, y un operador puede actualizar el email manualmente
-- para usuarios preexistentes.
--
-- Aplicar manualmente contra la base de datos de producción o test (D3, sin Alembic):
--   psql $DATABASE_URL -f 002_add_user_email.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR;

UPDATE users
SET email = username || '@fim.local'
WHERE email IS NULL;

ALTER TABLE users ALTER COLUMN email SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
