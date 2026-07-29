-- =====================================================================
-- Migration 0006 (down): remove the case correspondence language.
--
-- Destructive. Where the column holds a value, somebody chose it - most
-- often because the canton default was wrong for that commune, which is
-- exactly the case where the information is worth keeping. Dropping the
-- column silently returns every one of those cases to the default, and
-- the next letter goes out in the wrong language.
--
-- Take a copy first:
--
--   \copy (SELECT id, employee_name, canton, correspondence_language
--          FROM cases WHERE correspondence_language IS NOT NULL)
--   TO 'case_correspondence_language.csv' CSV HEADER
--
-- Revert the application code with this. Without the column, the
-- language resolver falls back to the canton default for every case,
-- which is a behaviour change rather than an error - nothing will
-- complain, and the wrong-language letters will look normal.
-- =====================================================================

ALTER TABLE cases
    DROP CONSTRAINT IF EXISTS cases_correspondence_language_known;

ALTER TABLE cases
    DROP COLUMN IF EXISTS correspondence_language;
