-- Migration 013: bounded textual diff metadata for US-09.
--
-- The agent already emits `hash_expected` and a unified `diff_text`; prior
-- backend versions discarded both fields. The diff stores only changed/context
-- lines, not complete baseline/current file versions. Application ingestion
-- limits UTF-8 payloads to 1 MiB before persistence.
--
-- Apply after 012_add_event_type_and_nullable_path.sql:
--   psql $DATABASE_URL -f 013_add_event_diff_metadata.sql

ALTER TABLE events ADD COLUMN IF NOT EXISTS hash_expected VARCHAR(64);
ALTER TABLE events ADD COLUMN IF NOT EXISTS diff_text TEXT;
