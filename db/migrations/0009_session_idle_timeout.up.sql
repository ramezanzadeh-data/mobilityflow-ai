-- =====================================================================
-- Migration 0009 (up): when a browser session was last used, so an
-- abandoned one can end itself.
--
-- Applied by db.database._migrate_session_idle_timeout() during
-- init_db().
--
-- What this fixes
-- ---------------
-- Sessions became durable in migration 0008, which was the point: a
-- refresh no longer signs anyone out. The cost was that closing the
-- window no longer signs anyone out either. Before durable sessions,
-- closing the tab *was* the logout - the session lived only in the
-- Streamlit server's memory - so nobody had to think about the
-- difference.
--
-- Reported the way these things are: "I closed the window without
-- logging out, opened http://localhost again, and it went straight to
-- the dashboard." Correct behaviour, and not the behaviour anyone wants
-- from a shared machine in an office that holds other people's passport
-- scans and employment contracts.
--
-- Why a timestamp and not a shorter lifetime
-- ------------------------------------------
-- expires_at already exists and already caps a session at
-- BROWSER_SESSION_HOURS. Shortening it is the change that needs no
-- migration, and it is the wrong one: it counts from the login, not from
-- the last thing the person did, so it throws out a consultant in the
-- middle of a case at the same rate it throws out an abandoned window.
-- Every value is either too short to work with or too long to protect
-- anything.
--
-- last_seen_at separates the two questions. expires_at answers "how long
-- may one login last at most"; this answers "has anyone been here
-- lately". A session ends when either says so.
--
-- Why NOT NULL matters here
-- -------------------------
-- The check in apps/web/session.py treats an absent last_seen_at as
-- idle, because the alternative - treating "we do not know" as "recently
-- active" - is a session that can never go idle, which is the failure
-- this migration exists to remove.
--
-- That makes the backfill below load-bearing rather than tidy. Without
-- it every session in flight at deploy time has NULL here and is signed
-- out mid-sentence. With it, they are treated as active as of the
-- migration, which extends them by at most one idle window.
--
-- Applies only to browser sessions. The API's refresh tokens live in the
-- same table and are never read through restore_session(), so a
-- server-to-server client is not affected - it has no "user" to be idle.
--
-- Safe to re-run.
-- =====================================================================

ALTER TABLE refresh_tokens
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;


-- Only the live rows. Revoked and expired sessions are not going to be
-- restored whatever this column says, and writing to them would be a
-- table rewrite for no effect.
UPDATE refresh_tokens
   SET last_seen_at = now()
 WHERE last_seen_at IS NULL
   AND revoked = 0;


-- Written on every restore, and read on every restore. Partial, because
-- revoked rows are never the subject of either.
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_last_seen
    ON refresh_tokens (last_seen_at)
    WHERE revoked = 0;


COMMENT ON COLUMN refresh_tokens.last_seen_at IS
    'When this browser session was last used. Advanced at most once a '
    'minute while someone is working - see apps/web/session.py - and '
    'read to decide whether a session has been abandoned. NULL means '
    'unknown, which is treated as idle.';
