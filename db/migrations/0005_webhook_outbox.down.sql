-- =====================================================================
-- Migration 0005 (down): remove the webhook outbox.
--
-- Destructive in a way that is easy to underestimate. Any PENDING row is
-- a notification a customer is owed and has not yet received; dropping
-- the table discards it with no record that it was ever due. DELIVERED
-- rows are the evidence of what was sent and when, which is what answers
-- "you never notified us of that case".
--
-- Drain first, then archive, then drop:
--
--   -- 1. Is anything still owed?
--   SELECT status, count(*) FROM webhook_outbox GROUP BY status;
--
--   -- 2. Keep the record.
--   \copy (SELECT * FROM webhook_outbox) TO 'webhook_outbox.csv' CSV HEADER
--
-- Reverting this migration also returns log_case_event() to publishing
-- directly to the broker inside the user's request - the behaviour this
-- replaced. Revert the application code with it, or case events will be
-- recorded with no notification path at all.
-- =====================================================================

DROP INDEX IF EXISTS idx_webhook_outbox_failed;

DROP INDEX IF EXISTS idx_webhook_outbox_due;

DROP TABLE IF EXISTS webhook_outbox;
