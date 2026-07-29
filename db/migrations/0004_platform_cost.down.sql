-- =====================================================================
-- Migration 0004 (down): remove the stated platform cost.
--
-- Destructive: this is a figure the customer supplied once and will not
-- remember. Every value/cost ratio already sent to them becomes
-- unreproducible.
--
-- Take a copy first:
--
--   \copy (SELECT tenant_id, platform_cost_per_month
--          FROM tenant_value_assumptions
--          WHERE platform_cost_per_month IS NOT NULL)
--   TO 'platform_cost_backup.csv' CSV HEADER
-- =====================================================================

ALTER TABLE tenant_value_assumptions
    DROP CONSTRAINT IF EXISTS tenant_value_assumptions_platform_cost_positive;

ALTER TABLE tenant_value_assumptions
    DROP COLUMN IF EXISTS platform_cost_per_month;
