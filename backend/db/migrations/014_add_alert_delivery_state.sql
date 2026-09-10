-- Migration 014: durable notification delivery state.
--
-- notification_id is stable for the lifetime of an alert. attempt_count and
-- next_retry_at let startup recovery continue the n8n retry ladder rather than
-- restarting it or marking an undelivered alert as successful.

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notification_id VARCHAR;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS ux_alerts_notification_id
    ON alerts (notification_id)
    WHERE notification_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_alerts_pending_delivery
    ON alerts (next_retry_at)
    WHERE delivered_at IS NULL;
