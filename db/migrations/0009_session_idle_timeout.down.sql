-- =====================================================================
-- Migration 0009 (down): stop tracking when a session was last used.
--
-- Loses nothing anyone will ask for later - the column holds a working
-- value, not a record. What it removes is the only reason an abandoned
-- session ends before BROWSER_SESSION_HOURS is up.
--
-- So revert the application code with it. Left in place while
-- apps/web/session.py still reads this column, every restore would find
-- no last_seen_at, treat it as idle - the check fails closed - and sign
-- out every user in the product on their next page load. The failure is
-- total and looks nothing like a missing column.
--
-- After reverting, a session on an unattended machine stays usable for
-- the full twelve hours. That is the behaviour that was reported as a
-- problem, and it should be a deliberate decision to accept it again.
-- =====================================================================

DROP INDEX IF EXISTS idx_refresh_tokens_last_seen;

ALTER TABLE refresh_tokens
    DROP COLUMN IF EXISTS last_seen_at;
