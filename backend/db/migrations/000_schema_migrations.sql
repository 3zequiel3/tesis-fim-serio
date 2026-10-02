-- Migration 000: Creates the `schema_migrations` registry (D84/RN-178, Change 66).
--
-- The registry records which migrations were applied to this database, with the sha256 of
-- each file, so that `scripts/migrar.py` can detect an edited migration and the backend can
-- refuse to start against an outdated schema (`app/core/schema_version.py`).
--
-- This table is NOT a SQLModel model: `create_all` never creates it, and the per-test
-- TRUNCATE of the backend harness (which walks `SQLModel.metadata`) never empties it. Only
-- this migration creates it, and `migrar.py` always applies this one (it registers itself
-- with version 0).
--
-- `sha256` is the hash of the raw bytes of the file, lowercase hexadecimal.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS. Running the script twice produces no error.
--
-- Apply with `python3 scripts/migrar.py` (never by hand: the tool also writes the row).

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER     PRIMARY KEY,
    filename    TEXT        NOT NULL,
    sha256      CHAR(64)    NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
