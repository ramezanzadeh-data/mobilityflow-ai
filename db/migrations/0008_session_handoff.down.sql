-- =====================================================================
-- Migration 0008 (down): remove the browser-session handoff codes.
--
-- Less destructive than it looks, and more disruptive than it looks.
--
-- Nothing of record is lost. Every row here is either spent or expiring
-- within seconds; the table holds no history anyone will ever ask about.
--
-- What it does break is Log out. session_id is how a signed-in tab names
-- the browser session it created when it cannot see the cookie - see the
-- up migration. Drop this table while apps/web/session.py still expects
-- it and pressing Log out will clear the tab and leave the cookie
-- session revocable only through the browser, which is to say not
-- reliably at all.
--
-- So revert the application code with it. In practice that means going
-- back to the session token in the query string, which is the exposure
-- this replaced: the token in the address bar, in browser history, and
-- in every copied link.
--
-- Before dropping, confirm nothing is mid-handoff:
--
--   SELECT count(*) FROM session_handoff WHERE consumed_at IS NULL
--     AND expires_at > now();
--
-- Any non-zero result is a user in the middle of signing in; they will
-- be returned to the login form.
-- =====================================================================

DROP INDEX IF EXISTS idx_session_handoff_expiry;

DROP TABLE IF EXISTS session_handoff;
