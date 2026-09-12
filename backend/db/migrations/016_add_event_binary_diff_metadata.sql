-- Migration 016: binary-mode diff metadata for US-09 (DiffViewer binary mode).
--
-- The agent already emits diff_text for text files (migration 013). This adds
-- the binary counterpart: is_binary flags when the agent detected non-UTF8
-- content and therefore produced no diff_text; hex_dump_before/hex_dump_after
-- are a bounded partial hex dump (first N bytes of each side, agent-side
-- constant _HEX_DUMP_BYTES=256 in agent/detector.py) used by the frontend's
-- side-by-side binary comparison. Same defensive posture as diff_text: the
-- backend validates format/size before persisting (_bounded_hex_dump in
-- app/modules/events/service.py) and never reconstructs full file content.
--
-- Backfill of pre-existing rows to is_binary=false is covered by the NOT NULL
-- DEFAULT FALSE itself — no separate UPDATE needed, since no existing row
-- could have been produced by an agent that emits is_binary (this is the
-- first change to introduce the field).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS. Running the script twice is a no-op.
--
-- Apply after 013_add_event_diff_metadata.sql:
--   psql $DATABASE_URL -f 016_add_event_binary_diff_metadata.sql

ALTER TABLE events ADD COLUMN IF NOT EXISTS is_binary BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE events ADD COLUMN IF NOT EXISTS hex_dump_before TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS hex_dump_after TEXT;
