-- =====================================================================
-- Migration 0003 (down): remove the statutory date columns.
--
-- DESTRUCTIVE. These columns hold facts that were collected from
-- employees and their documents - an arrival date is not something the
-- system can recompute. Dropping them discards that, and every statutory
-- deadline reverts to "needs arrival_date".
--
-- Take a copy first:
--
--   \copy (SELECT id, employee_name, arrival_date, contract_start_date,
--                 permit_expiry_date
--          FROM cases
--          WHERE arrival_date IS NOT NULL
--             OR contract_start_date IS NOT NULL
--             OR permit_expiry_date IS NOT NULL)
--   TO 'case_statutory_dates_backup.csv' CSV HEADER
-- =====================================================================

ALTER TABLE cases DROP CONSTRAINT IF EXISTS cases_statutory_dates_plausible;

DROP INDEX IF EXISTS idx_cases_arrival_date;
DROP INDEX IF EXISTS idx_cases_permit_expiry_date;

ALTER TABLE cases DROP COLUMN IF EXISTS arrival_date;
ALTER TABLE cases DROP COLUMN IF EXISTS contract_start_date;
ALTER TABLE cases DROP COLUMN IF EXISTS permit_expiry_date;
