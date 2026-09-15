-- Migration 017: index on rejected_events_audit.received_at for D65/RN-159.
--
-- rejected_events_retention_task() (backend/app/modules/events/service.py)
-- deletes rejected_events_audit rows older than
-- REJECTED_EVENTS_RETENTION_DAYS in batches of at most 1000, each batch
-- filtering by "WHERE received_at < cutoff ORDER BY id LIMIT batch_size"
-- (bind parameters, not literal colon syntax — spelled out here without a
-- leading colon so this comment stays plain text for any tool that scans
-- for bind-parameter placeholders, e.g. SQLAlchemy's text()).
-- Without an index on received_at that filter is a sequential scan on every
-- hourly run; this index lets Postgres seek directly to the rows past the
-- cutoff. received_at (not detected_at) is the reference column: it is
-- NOT NULL and comes from the backend's own clock (D65/RN-159).
--
-- audit_log is NOT touched by this migration or by the retention task —
-- W18/RN-94 ratifies unlimited retention for audit_log.
--
-- Idempotent: CREATE INDEX IF NOT EXISTS. Running the script twice is a no-op.
--
-- Apply (before or after deploying the backend/frontend images — indistinct,
-- see design.md "Migration Plan"):
--   psql $DATABASE_URL -f 017_add_rejected_events_audit_received_at_index.sql

CREATE INDEX IF NOT EXISTS ix_rejected_events_audit_received_at
    ON rejected_events_audit (received_at);
