-- =====================================================================
-- Migration 0005 (up): transactional outbox for webhook delivery.
--
-- Applied by db.database._migrate_webhook_outbox() during init_db().
--
-- The problem this replaces
-- ------------------------
-- db.database.log_case_event() committed the case event and then, on a
-- separate line, published a Celery task:
--
--     with get_db_connection() as conn:
--         INSERT INTO case_events ...          -- committed
--     dispatch_webhook.delay(...)              -- separate, unprotected
--
-- Two independent failures live in that gap.
--
--   * The publish happens inside the user's own request. Celery's
--     default retry policy is twenty attempts a second apart, so an
--     unreachable broker froze the page for twenty seconds on every
--     case creation, status change and document upload.
--
--   * If the publish then failed - broker down, worker queue full,
--     process killed between the two statements - the event was already
--     committed and the notification was gone. Nothing recorded that it
--     had ever been owed. A customer's downstream system would simply be
--     missing events, and nobody on either side would know which ones.
--
-- Shortening the timeout fixes the first and makes the second worse:
-- giving up faster means losing more.
--
-- The outbox pattern
-- ------------------
-- The intent to deliver is written to this table in the *same
-- transaction* as the case event. Either both are committed or neither
-- is - the database guarantees it, not the application.
--
-- A relay (workers.outbox_tasks) then claims due rows and delivers them.
-- The user's request never touches the broker or the network, so no
-- customer endpoint and no infrastructure outage can slow it down, and
-- nothing that was owed can be silently dropped.
--
-- One row per subscriber, not per event
-- -------------------------------------
-- Each subscriber succeeds or fails independently. With one row per
-- event, a single failing endpoint would force the whole event to be
-- retried and re-delivered to subscribers that had already accepted it.
-- Per-subscriber rows keep the retry where the failure was, and make the
-- table an exact record of what was sent where - which is the answer to
-- "did you notify us of this case?", a question this product should be
-- able to settle from data rather than argument.
--
-- Delivery remains at-least-once. A response lost after the endpoint
-- committed will be retried, so subscribers must treat deliveries as
-- idempotent. That is the same contract Stripe and GitHub webhooks
-- publish, and the alternative - exactly-once over HTTP - does not
-- exist.
--
-- Safe to re-run.
-- =====================================================================

CREATE TABLE IF NOT EXISTS webhook_outbox (
    id                  BIGSERIAL PRIMARY KEY,

    -- Row-Level Security is applied by
    -- db.database._enable_row_level_security(); this table is registered
    -- in _RLS_TABLES. The payload carries case data, so cross-tenant
    -- visibility here would be a data breach.
    tenant_id           INTEGER,

    -- The subscriber this row will be delivered to. ON DELETE CASCADE:
    -- when a customer removes a webhook they have withdrawn consent to
    -- be called, and continuing to deliver from a queue they can no
    -- longer see is not defensible.
    webhook_id          INTEGER NOT NULL
                        REFERENCES webhooks(id) ON DELETE CASCADE,

    -- Denormalised from the case event so a delivery can be reconstructed
    -- without joining back to data that may since have changed.
    company             TEXT NOT NULL,
    event_type          TEXT NOT NULL,

    -- JSONB, not TEXT: the payload is queried when a customer asks which
    -- events they were sent, and it must be structurally valid at write
    -- time rather than at delivery time.
    payload             JSONB NOT NULL,

    -- PENDING    - due at next_attempt_at
    -- DELIVERED  - the endpoint returned a 2xx or 3xx
    -- FAILED     - attempts exhausted; needs a human
    -- CANCELLED  - the subscriber was removed or deactivated
    status              TEXT NOT NULL DEFAULT 'PENDING',

    attempts            INTEGER NOT NULL DEFAULT 0,

    -- Drives the backoff. Set to now() on insert so the first attempt is
    -- immediate; the relay pushes it forward after each failure.
    next_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Kept for the operator, and for the customer asking why they did
    -- not receive something. An empty error column on a FAILED row is a
    -- support ticket nobody can answer.
    last_error          TEXT,
    last_status_code    INTEGER,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at        TIMESTAMPTZ,

    CONSTRAINT webhook_outbox_status_known CHECK (
        status IN ('PENDING', 'DELIVERED', 'FAILED', 'CANCELLED')
    ),

    CONSTRAINT webhook_outbox_attempts_non_negative CHECK (attempts >= 0),

    -- A delivered row without a delivery time cannot be audited, and a
    -- delivery time on a row that was never delivered is a lie. Enforced
    -- here because both are written by application code that could drift.
    CONSTRAINT webhook_outbox_delivered_has_a_timestamp CHECK (
        (status = 'DELIVERED') = (delivered_at IS NOT NULL)
    )
);


-- The relay's only query: the oldest due rows, in order. Partial, because
-- DELIVERED rows accumulate forever and are never selected by it -
-- indexing them would grow the index without bound for no read benefit.
CREATE INDEX IF NOT EXISTS idx_webhook_outbox_due
    ON webhook_outbox (next_attempt_at, id)
    WHERE status = 'PENDING';


-- For the operator and support views: "what is stuck, and for whom".
CREATE INDEX IF NOT EXISTS idx_webhook_outbox_failed
    ON webhook_outbox (tenant_id, created_at)
    WHERE status = 'FAILED';


COMMENT ON TABLE webhook_outbox IS
    'Transactional outbox. Rows are written in the same transaction as '
    'the case event they describe, so a committed event always has its '
    'notifications recorded. workers.outbox_tasks delivers them.';

COMMENT ON COLUMN webhook_outbox.next_attempt_at IS
    'When this row becomes eligible for delivery. Advanced by the relay '
    'with exponential backoff after each failed attempt.';
