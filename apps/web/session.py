"""
Keeping a signed-in user signed in across a browser refresh.

The problem
-----------
``st.session_state`` lives in the memory of the Streamlit server process
and is keyed by a websocket session. Refresh the page and that session is
gone, so ``"user" not in st.session_state`` and the login form comes
back. Restart the container and every user in the product is logged out
at once.

Nobody reads that as a session model. They read it as the product losing
their login, and they are not wrong: they refreshed a page, which is not
an action that should ever end a session.

Where the session is kept
-------------------------
Server side, in Postgres, in the ``refresh_tokens`` table that already
exists for the API. Browser side, in an HttpOnly cookie. The browser
holds only an opaque random token; every fact about the user is re-read
from the database on each restore.

That last point is the one that matters. The token carries a username and
nothing else. Role, company and tenant are looked up fresh, so:

* a user whose role was changed does not keep the old one until they
  log out;
* a user who was deleted cannot restore a session at all;
* a token cannot be edited into a different role, because the role is
  not in it.

Why the cookie is not set here
------------------------------
Because it cannot be. A cookie is an HTTP response header, and by the
time Python runs in a Streamlit script the response that could have
carried one is long finished - what is left is a websocket. Only the
FastAPI app can set one, and since deploy/nginx.conf put both halves on
one origin, a cookie it sets is first-party for Streamlit too.

Reading it back is straightforward: ``st.context.cookies`` is the
handshake request's headers, and HttpOnly keeps a cookie from page
script, not from the server it was sent to.

So login hands the API a one-time code rather than a session. See
auth/browser_session.py for why the code, and not the session token, is
the thing that crosses the browser.

What used to be here
--------------------
The token travelled in the URL query string, and the cost was stated
plainly rather than buried: it was in the address bar, so a screen-share
or a screenshot disclosed it; it was in browser history; anyone a link
was copied to inherited the session until it expired. A printed page
carried a working login in the footer of every sheet, which is how the
defect was found.

That path is gone, not disabled. It survived one release as a fallback
while the cookie was confirmed in a real deployment, then came out -
because a hole one environment variable away from reopening is still a
hole, and the switch that reopens it is the kind of thing that gets set
during an incident and never unset.
"""

import datetime
import json
import logging
import os

import streamlit as st

from auth.browser_session import (
    SESSION_COOKIE_NAME,
    SESSION_IDLE_MINUTES,
    generate_handoff_code,
    handoff_expiry,
    hash_handoff_code,
)
from auth.refresh import hash_refresh_token
from db.database import (
    create_session_handoff,
    get_or_create_tenant,
    get_refresh_token,
    get_user,
    revoke_refresh_token,
    revoke_session_for_handoff,
    touch_session,
    touch_session_for_handoff,
)

logger = logging.getLogger(__name__)


# Where the API answers, as the browser sees it. deploy/nginx.conf maps
# /api/ to the API service, so /api/session/adopt reaches its
# /session/adopt. Configurable because the prefix is a deployment fact,
# not an application one.
#
# There is no longer a deployment where this path is absent. The direct
# :8501 port is not published: reaching Streamlit without the proxy in
# front of it would mean reaching it without any way to set a cookie,
# which is now the only way a session exists.
API_BASE_PATH = os.environ.get("MOBILITYFLOW_API_BASE_PATH", "/api").rstrip("/")

# session_state keys. Underscore-prefixed, like every other internal key
# in this app.
_TOKEN_KEY = "_session_token"
_HANDOFF_KEY = "_session_handoff"
_PENDING_KEY = "_session_browser_action"
_TOUCHED_KEY = "_session_touched_at"

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# How often "this session is still in use" is written to the database.
#
# keep_session_alive() is called on every Streamlit rerun, which is every
# click, so writing each time would make one column the busiest write in
# the product for no added accuracy - the idle window is measured in tens
# of minutes and this resolution is a minute.
_TOUCH_INTERVAL_SECONDS = 60


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _has_expired(expires_at):
    """
    Whether a stored expiry has passed.

    A row with no expiry, or one this cannot parse, is treated as
    expired. The alternative - treating an unreadable expiry as valid -
    turns a storage bug into a session that never ends.
    """

    if not expires_at:
        return True

    if isinstance(expires_at, datetime.datetime):
        moment = expires_at
    else:
        try:
            moment = datetime.datetime.strptime(
                str(expires_at)[:19], _TIMESTAMP_FORMAT
            )
        except ValueError:
            logger.warning("session expiry could not be parsed; treating as expired")
            return True

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)

    return moment <= _now()


def _as_datetime(value):
    """A stored timestamp as an aware datetime, or None if unreadable."""

    if not value:
        return None

    if isinstance(value, datetime.datetime):
        moment = value
    else:
        try:
            moment = datetime.datetime.strptime(
                str(value)[:19], _TIMESTAMP_FORMAT
            )
        except ValueError:
            return None

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)

    return moment


def _has_gone_idle(last_seen_at):
    """
    Whether nobody has used this session for long enough to end it.

    Separate from _has_expired, and both are checked. expires_at caps how
    long one login may last at all; this ends a session nobody is at.
    Only having the first meant that closing the window without logging
    out left the product signed in on that machine for the rest of the
    day - which is what durable sessions cost, and what this repays.

    An unreadable or absent timestamp counts as idle. The alternative -
    reading "we do not know when this was last used" as "recently" -
    produces a session that can never go idle, which is the exact failure
    being fixed. db/migrations/0009 backfills the column for this reason,
    so no live session starts out unknown.
    """

    moment = _as_datetime(last_seen_at)

    if moment is None:
        return True

    idle_for = _now() - moment

    return idle_for > datetime.timedelta(minutes=SESSION_IDLE_MINUTES)


def _user_payload(user, tenant_id):
    """
    The session dict, built from a freshly read user row.

    Deliberately the same shape login() writes, so there is one
    description of what a signed-in user is and the two paths cannot
    drift into disagreeing about it.
    """

    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "company": user["company"],
        "tenant_id": tenant_id,
        "must_change_password": bool(user.get("must_change_password")),
    }


# ------------------------------------------------------------ reading ---


def _cookie_token():
    """
    The session token the browser sent, or None.

    ``st.context.cookies`` reports the cookies present on the request
    that opened this websocket session - so a cookie the API set after
    this page loaded is not visible here until the next full page load.
    That is a property of the transport, not a bug, and it is why
    forget_session() has a second way to find the session it created.

    Wrapped, because st.context is empty outside a script run and absent
    on Streamlit older than the version requirements.txt pins. Neither is
    a reason to fail a page load; both mean "no session", which shows the
    login form.
    """

    try:
        return st.context.cookies.get(SESSION_COOKIE_NAME)
    except Exception:  # noqa: BLE001 - see the docstring
        return None


# ------------------------------------------------------------ writing ---


def _issue_handoff(username):
    """
    A one-time code the API can redeem into a cookie session.

    Best-effort, like everything about remembering a session: a login
    that has already authenticated must not be refused because the
    session could not be made durable. Returns None on failure, and the
    caller carries on - the user is signed in for this page load and a
    refresh will return them to the login form, which is the behaviour
    the whole module exists to improve on rather than a new failure.
    """

    code = generate_handoff_code()

    try:
        create_session_handoff(
            code_hash=hash_handoff_code(code),
            username=username,
            expires_at=handoff_expiry(),
        )
    except Exception:
        logger.warning("could not issue a browser session handoff", exc_info=True)
        return None

    return code


def remember_session(user):
    """
    Record a signed-in user so a refresh does not sign them out.

    Issues the handoff and queues the request that redeems it; the
    session row itself is created by the API, on the other side of that
    request, so that the token it mints never passes through the browser.

    Returns the handoff code, or None if one could not be issued.
    """

    username = (user or {}).get("username")

    if not username:
        return None

    code = _issue_handoff(username)

    if not code:
        return None

    st.session_state[_HANDOFF_KEY] = code

    # Not rendered here: login() calls st.rerun() immediately after this
    # returns, which discards everything queued in this run. The request
    # is made on the next run - see emit_pending_browser_updates().
    st.session_state[_PENDING_KEY] = "adopt"

    return code


def restore_session():
    """
    Rebuild a signed-in user from the session cookie, or None.

    Returns None for every failure mode - absent, unknown, revoked,
    expired, or belonging to a user who no longer exists - and does not
    distinguish between them to the caller. The page shows the login form
    in all of those cases, and telling the browser which of them applied
    would only describe the token store to whoever holds a bad token.
    """

    token = _cookie_token()

    if not token:
        return None

    try:
        record = get_refresh_token(hash_refresh_token(token))
    except Exception:
        logger.warning("could not read the browser session", exc_info=True)
        return None

    if not record:
        forget_session()
        return None

    if record.get("revoked"):
        forget_session()
        return None

    if _has_expired(record.get("expires_at")):
        forget_session()
        return None

    if _has_gone_idle(record.get("last_seen_at")):
        # Revoked, not merely refused. An abandoned session that is only
        # ignored is still a working token in whatever browser was left
        # open; ending it server-side is what makes walking away from a
        # shared machine equivalent to logging out.
        forget_session()
        return None

    # Read the user again rather than trusting anything the token was
    # issued alongside. The token names a user and confers nothing; every
    # privilege is looked up here, on every page load.
    try:
        user = get_user(record["username"])
    except Exception:
        logger.warning("could not read the user for a session", exc_info=True)
        return None

    if not user:
        # The account was deleted or renamed while the token lived on.
        forget_session()
        return None

    # Note on what is deliberately NOT checked here: the `users` table has
    # no is_active / disabled column, so there is nothing to test. That is
    # a real gap - today the only way to end a specific person's access is
    # to delete their row or revoke their tokens, and neither is what
    # "deactivate this user" should mean in a product sold to enterprises.
    # It is recorded here rather than faked with a check against a column
    # that does not exist.

    try:
        tenant_id = get_or_create_tenant(user["company"])
    except Exception:
        logger.warning("could not resolve the tenant for a session", exc_info=True)
        return None

    st.session_state[_TOKEN_KEY] = token

    keep_session_alive()

    return _user_payload(user, tenant_id)


def keep_session_alive():
    """
    Record that somebody is still here.

    Called on every rerun, which is every click, and writes at most once
    a minute - see _TOUCH_INTERVAL_SECONDS. Without a throttle this would
    be one UPDATE per interaction for a value read once per page load.

    Two ways to name the session, because which one is available depends
    on when it was created. Usually it is the token this page load
    arrived with. In the page load that signed in, that token does not
    exist yet - st.context.cookies reports only what came with the
    websocket handshake - so the handoff names it instead. Without the
    second, somebody who logs in and then works for an hour without
    refreshing is active in fact and idle by the clock, and is signed out
    the moment they finally refresh.

    Best-effort. A failed write means the session ages a minute faster
    than it should, which is not worth failing a page load over.
    """

    last = st.session_state.get(_TOUCHED_KEY)

    if last and (_now() - last).total_seconds() < _TOUCH_INTERVAL_SECONDS:
        return

    token = st.session_state.get(_TOKEN_KEY)
    code = st.session_state.get(_HANDOFF_KEY)

    if not token and not code:
        return

    try:
        if token:
            recorded = touch_session(hash_refresh_token(token))
        else:
            recorded = touch_session_for_handoff(hash_handoff_code(code))
    except Exception:
        logger.warning("could not record session activity", exc_info=True)
        return

    if not recorded:
        # Matched no row, so nothing was recorded and the throttle must
        # not be started. This is the normal state for the first moments
        # after signing in: the frame that asks the API to redeem the
        # handoff has been rendered but the browser has not made the
        # request yet, so there is no session to mark as used. Starting
        # the throttle here would blind the next sixty seconds of clicks
        # to a session that came into existence during them.
        return

    st.session_state[_TOUCHED_KEY] = _now()


def forget_session():
    """
    End the session on the server, then ask the browser to forget it.

    In that order, and the order is the whole design. Revocation happens
    here, in Python, against the database - not in the browser. A logout
    that a blocked request or a closed tab could quietly skip would leave
    a working session behind while telling the user they had signed out.

    Two things are revoked, because a session can be found two ways and
    which one applies depends on when it was created:

      * the token in the cookie, when this page load arrived with one;
      * the session minted by this page load's handoff, which the cookie
        cannot name yet - st.context.cookies reports only what came with
        the websocket handshake, so a session created since this page
        loaded is invisible to it.

    Signing in and out without an intervening refresh is the second case,
    and it is not an edge case: it is what happens on a shared machine
    when someone checks one thing and leaves.

    Each is a no-op when it does not apply. Revoking a token twice, or a
    session that was never created, costs one UPDATE that matches
    nothing.
    """

    for token in {st.session_state.get(_TOKEN_KEY), _cookie_token()}:

        if not token:
            continue

        try:
            revoke_refresh_token(hash_refresh_token(token))
        except Exception:
            logger.warning("could not revoke the browser session", exc_info=True)

    code = st.session_state.get(_HANDOFF_KEY)

    if code:
        try:
            revoke_session_for_handoff(hash_handoff_code(code))
        except Exception:
            logger.warning("could not revoke the cookie session", exc_info=True)

        # Asks the browser to drop the cookie. Cosmetic - the session it
        # names is already dead - but a browser still holding a session
        # cookie after Log out is the kind of thing that has to be
        # explained in a security review, and "it does not work" is a
        # worse answer than "it is not there".
        st.session_state[_PENDING_KEY] = "clear"

    st.session_state.pop(_TOKEN_KEY, None)
    st.session_state.pop(_TOUCHED_KEY, None)


# ------------------------------------------------- talking to the API ---


def _render_browser_request(html):
    """
    Put a zero-height frame on the page and let it make one request.

    The only place this module touches the browser, isolated behind one
    function for two reasons. It is the seam the tests watch, without
    needing a Streamlit runtime to watch it through. And the import is
    deliberately local: importing streamlit.components.v1 at module level
    makes this file unimportable in any test that has replaced
    ``streamlit`` in sys.modules with a stub, which several do - a
    module-level submodule import would tie the session logic to whether
    some unrelated test happened to run first.
    """

    import streamlit.components.v1 as components

    components.html(html, height=0)


def emit_pending_browser_updates():
    """
    Make the one request Streamlit cannot make for itself.

    Setting or deleting a cookie means sending a header on an HTTP
    response, and Streamlit has none to send: its Python runs behind a
    websocket whose handshake finished long ago. So the browser is asked
    to make the request instead, from a zero-height component frame,
    same-origin, to the API on the other side of the same nginx.

    Called on the run *after* the one that queued it. login() and logout()
    both end in st.rerun(), which discards whatever the interrupted run
    had queued - including this frame, if it were rendered there.

    What travels through the browser is the handoff code, which is
    single-use and expires in thirty seconds. The session token is
    created by the API and goes straight into the cookie, so it is never
    in the DOM and never reachable by page script. That is the entire
    point; see auth/browser_session.py.
    """

    action = st.session_state.pop(_PENDING_KEY, None)

    if not action:
        return

    code = st.session_state.get(_HANDOFF_KEY)

    if action == "clear":
        st.session_state.pop(_HANDOFF_KEY, None)

    if not code:
        return

    endpoint = f"{API_BASE_PATH}/session/{'adopt' if action == 'adopt' else 'clear'}"

    # json.dumps, not an f-string interpolation: the code is a
    # url-safe base64 value today, and "today's values happen not to
    # need escaping" is how script injection gets into a page.
    body = json.dumps({"code": code})

    _render_browser_request(
        f"""
        <script>
        fetch({json.dumps(endpoint)}, {{
            method: "POST",
            // Same-origin since deploy/nginx.conf. The cookie the
            // response sets is first-party, which is what stops
            // increasingly strict third-party cookie rules from
            // silently dropping it.
            credentials: "same-origin",
            headers: {{"Content-Type": "application/json"}},
            body: {json.dumps(body)}
        }}).catch(function () {{
            // Nothing to do and nobody to tell. A failure here leaves
            // the user signed in for this page load and returned to the
            // login form by their next refresh - visible to them, and
            // not something a message on this page could fix.
        }});
        </script>
        """
    )
