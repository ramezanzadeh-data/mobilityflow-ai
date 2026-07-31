-- =====================================================================
-- Migration 0008 (up): one-time codes that hand a browser session from
-- Streamlit to the API, so the session token can live in an HttpOnly
-- cookie instead of the URL.
--
-- Applied by db.database._migrate_session_handoff() during init_db().
--
-- The problem this exists to solve
-- -------------------------------
-- The browser session token travelled in the query string - see the
-- "Honest limits" section that used to head apps/web/session.py. It was
-- in the address bar, in browser history, and in any copied link. A
-- printed page carried a working session.
--
-- The fix is an HttpOnly cookie. Migration 0008 is the piece that makes
-- one reachable, because Streamlit cannot set a cookie: a cookie is an
-- HTTP response header, and Streamlit's Python runs behind a websocket
-- that has long since finished its handshake. Only the FastAPI app,
-- same-origin behind nginx since deploy/nginx.conf landed, can set one.
--
-- So the two halves have to be introduced to each other, and the
-- introduction itself is a credential. This table is that credential.
--
-- Why not just pass the session token to the API
-- ----------------------------------------------
-- Because it would have to travel through the browser to get there, and
-- a token that passes through the DOM is a token that page-level script
-- can read. HttpOnly exists precisely to prevent that. Handing over a
-- token the browser has already seen would put the cookie in place and
-- leave the property it was adopted for behind.
--
-- What crosses the browser instead is a code that:
--
--   * names a user and confers nothing else - the API re-reads the role,
--     company and tenant, exactly as restore_session() always has;
--   * is single-use - consumed_at is claimed by the UPDATE that reads
--     it, so a replay finds nothing, even if two requests race;
--   * lives ~30 seconds, so the exposure is a window rather than a
--     lifetime;
--   * is stored only as a SHA-256 hash, so a leaked backup of this table
--     is not a set of usable logins.
--
-- Why the session id is kept
-- --------------------------
-- session_id links a consumed handoff to the refresh_tokens row it
-- minted. Logging out has to revoke that row, and the tab doing the
-- logging out may not be able to see the cookie: st.context.cookies
-- reports the cookies sent with the *initial* request of the websocket
-- session, so a cookie adopted after the page loaded is invisible until
-- the next full page load.
--
-- Without this column, Log out in the same page load as Log in could not
-- name the session it had just created, and revocation would depend on a
-- best-effort call from the browser. Revocation that depends on the
-- browser is not revocation.
--
-- Not tenant-scoped
-- -----------------
-- Deliberately absent from _RLS_TABLES, for the same reason `users` is:
-- this table is read while establishing who the caller is, which is
-- before the tenant is known. There is nothing here to scope - a row is
-- a username and an expiry.
--
-- Safe to re-run.
-- =====================================================================

CREATE TABLE IF NOT EXISTS session_handoff (
    id            BIGSERIAL PRIMARY KEY,

    -- SHA-256 hex of the code, never the code. Same reasoning as
    -- refresh_tokens.token_hash: whoever can read this table must not be
    -- able to sign in as the people in it.
    code_hash     TEXT NOT NULL UNIQUE,

    -- The only thing a handoff asserts. Role, company and tenant are
    -- read from `users` when the code is redeemed, so an entry here can
    -- never carry a privilege.
    username      TEXT NOT NULL,

    issued_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Seconds, not hours. This value exists only long enough for one
    -- page to hand it to one endpoint.
    expires_at    TIMESTAMPTZ NOT NULL,

    -- Set by the UPDATE that claims the row. Non-NULL means spent; the
    -- claim and the read are the same statement, so two concurrent
    -- redemptions cannot both succeed.
    consumed_at   TIMESTAMPTZ,

    -- The browser session this handoff minted, so Log out can revoke it
    -- server-side without needing to see the cookie. ON DELETE CASCADE:
    -- a handoff whose session row is gone describes nothing.
    session_id    INTEGER REFERENCES refresh_tokens(id) ON DELETE CASCADE
);


-- Pruning only. Rows are looked up by code_hash, which the UNIQUE
-- constraint already indexes; this one serves the housekeeping delete so
-- it does not degrade into a sequential scan as the table grows.
CREATE INDEX IF NOT EXISTS idx_session_handoff_expiry
    ON session_handoff (expires_at);


COMMENT ON TABLE session_handoff IS
    'Single-use, seconds-lived codes that let the Streamlit app ask the '
    'API to mint a browser session and set it as an HttpOnly cookie. '
    'The session token itself never passes through the browser.';

COMMENT ON COLUMN session_handoff.consumed_at IS
    'Claimed by the UPDATE ... RETURNING that redeems the code, which is '
    'what makes redemption single-use under concurrency.';

COMMENT ON COLUMN session_handoff.session_id IS
    'The refresh_tokens row this handoff produced. Lets logout revoke '
    'the cookie session without depending on the browser.';
