-- =====================================================================
-- Migration 0004 (up): record what the customer pays for the platform.
--
-- Why
-- ---
-- The value report can now show value against cost - "CHF 1,976 created,
-- CHF 508 paid, 3.9x" - but only when the customer states the cost. The
-- software does not know its own price and must never assume one: a
-- vendor that computes its own return produces the least credible figure
-- in a procurement pack.
--
-- Stored alongside the other assumptions because it is the same kind of
-- fact: a number the customer supplied, which every derived figure is
-- traceable back to.
--
-- NULL means "not supplied", and the report then shows no comparison
-- against cost at all. There is deliberately no default. A default here
-- would be the product inventing its own price and dividing by it.
--
-- Safe to re-run.
-- =====================================================================

ALTER TABLE tenant_value_assumptions
    ADD COLUMN IF NOT EXISTS platform_cost_per_month NUMERIC(12, 2);


COMMENT ON COLUMN tenant_value_assumptions.platform_cost_per_month IS
    'Monthly platform cost as stated by the customer. NULL = not '
    'supplied; the value/cost ratio is then omitted rather than '
    'estimated.';


-- Zero would produce a division by zero in the ratio, and a "free"
-- platform is not a case this represents - absence is expressed as NULL.
ALTER TABLE tenant_value_assumptions
    DROP CONSTRAINT IF EXISTS tenant_value_assumptions_platform_cost_positive;

ALTER TABLE tenant_value_assumptions
    ADD CONSTRAINT tenant_value_assumptions_platform_cost_positive CHECK (
        platform_cost_per_month IS NULL OR platform_cost_per_month > 0
    );
