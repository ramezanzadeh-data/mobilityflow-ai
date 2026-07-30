-- =====================================================================
-- Migration 0007 (down): remove the case commune.
--
-- Destructive. Where the column holds a value, somebody recorded which
-- commune the case registers in - and that value is what selects the
-- renewal window and the correspondence language. Dropping it returns
-- every case to the canton-level default, which the research showed is
-- wrong for at least two of the three communes examined.
--
-- Nothing will complain. The deadlines will simply go back to being
-- computed from a number that does not apply.
--
-- Take a copy first:
--
--   \copy (SELECT id, employee_name, canton, commune
--          FROM cases WHERE commune IS NOT NULL)
--   TO 'case_commune.csv' CSV HEADER
-- =====================================================================

DROP INDEX IF EXISTS idx_cases_commune;

ALTER TABLE cases
    DROP COLUMN IF EXISTS commune;
