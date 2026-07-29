-- =====================================================================
-- Migration 0002 (up): persist each tenant's value-report assumptions.
--
-- Applied by db.database._migrate_tenant_value_assumptions() during
-- init_db(). This was the first schema change made after the data model
-- was frozen, and was reviewed and approved as such.
--
-- Why a table is needed
-- --------------------
-- The value report multiplies recorded activity by the customer's own
-- estimate of manual effort ("you told us document review takes 12
-- minutes"). That number is what makes the report defensible in a
-- procurement review, so it has to be:
--
--   * per tenant   - a 20-person relocation firm and a bank do not have
--                    the same specialist cost;
--   * durable      - a figure that resets every session cannot be cited
--                    in a renewal conversation six months later;
--   * attributable - the report says "you provided this", so there has
--                    to be a record of who provided it and when.
--
-- Session state satisfies none of those. Until this is applied the UI
-- recomputes from whatever the user typed this session, which is honest
-- but not usable for a recurring quarterly report.
--
-- Why these columns
-- -----------------
-- One row per tenant, not per user: the rates describe the organisation,
-- not the person running the report. Two people generating the same
-- quarter must get identical figures, or the report is not evidence.
--
-- NUMERIC, not TEXT or FLOAT. These values are multiplied into a figure
-- a customer may be invoiced against, so exact decimal arithmetic is
-- required - binary floating point would make the same inputs produce
-- figures that differ in the last rappen between runs.
--
-- hourly_cost is deliberately NULLable. NULL means "the customer has not
-- given us a rate", and the report then reports hours and stays silent
-- about money. A default here would invent the least defensible number
-- in the document.
--
-- Safe to re-run.
-- =====================================================================

CREATE TABLE IF NOT EXISTS tenant_value_assumptions (
    tenant_id                       INTEGER PRIMARY KEY
                                    REFERENCES tenants(id) ON DELETE CASCADE,

    minutes_per_document_review     NUMERIC(6, 2) NOT NULL DEFAULT 12.00,
    minutes_per_document_request    NUMERIC(6, 2) NOT NULL DEFAULT 8.00,
    minutes_per_case_status_update  NUMERIC(6, 2) NOT NULL DEFAULT 5.00,

    -- NULL = not supplied. See the header.
    hourly_cost                     NUMERIC(10, 2),
    currency                        TEXT NOT NULL DEFAULT 'CHF',

    -- Attribution: the report asserts these are the customer's figures,
    -- so it must be possible to show who set them and when.
    updated_by                      TEXT,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT tenant_value_assumptions_minutes_non_negative CHECK (
        minutes_per_document_review    >= 0 AND
        minutes_per_document_request   >= 0 AND
        minutes_per_case_status_update >= 0
    ),

    -- A zero rate would silently produce a zero-value report rather than
    -- omitting the money column, which reads as "this product is worth
    -- nothing" instead of "no rate supplied".
    CONSTRAINT tenant_value_assumptions_hourly_cost_positive CHECK (
        hourly_cost IS NULL OR hourly_cost > 0
    )
);


-- Row-Level Security is deliberately NOT defined here.
--
-- db.database._enable_row_level_security() applies the tenant_isolation
-- policy to every table in _RLS_TABLES, and this table is registered
-- there. Writing the policy a second time in this file would create a
-- copy that drifts: the first draft of this migration did exactly that
-- and omitted the WITH CHECK clause the shared policy has, which would
-- have left writes unconstrained while reads looked correctly isolated -
-- the most dangerous kind of half-applied security control.
--
-- One definition, one place. See _enable_row_level_security().


COMMENT ON TABLE tenant_value_assumptions IS
    'Per-tenant manual-effort and cost baselines used by the value '
    'realisation report. Customer-supplied: the report attributes these '
    'figures to the customer, so they must not be defaulted silently.';
