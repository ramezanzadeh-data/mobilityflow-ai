-- =====================================================================
-- Migration 0002 (down): remove the per-tenant value-report assumptions.
--
-- Destructive: this drops every customer's stated baseline. Those are
-- figures the customer gave once and will not remember, and every value
-- report generated afterwards would silently fall back to the defaults
-- in core/reporting/value.py - producing different numbers from the ones
-- already sent to that customer.
--
-- Take a copy before running this:
--
--   \copy tenant_value_assumptions TO 'value_assumptions_backup.csv' CSV HEADER
-- =====================================================================

-- The tenant_isolation policy is dropped with the table; it is created
-- by _enable_row_level_security(), not by the up migration. Remove
-- "tenant_value_assumptions" from _RLS_TABLES as well, or the next
-- init_db() will fail trying to apply a policy to a table that is gone.

DROP TABLE IF EXISTS tenant_value_assumptions;
