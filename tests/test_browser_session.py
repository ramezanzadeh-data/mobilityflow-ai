"""
A page refresh must not sign a user out - and must not sign anyone in.

Reported directly: signed in, on the dashboard, pressed refresh, landed
back on the login form. ``st.session_state`` lives in the Streamlit
server's memory and is keyed by a websocket session, so a refresh
discards it. Every rebuild of the container did the same thing to every
signed-in user at once.

The fix moves the session into Postgres and leaves an opaque token in an
HttpOnly cookie. It left it in the URL query string first, because
Streamlit cannot set a cookie - and that was reported too, from the other
direction: the token printed in the footer of every page of an exported
case file. Both halves of that history are in these tests, because the
second fix must not quietly undo the first.

Session restore is an authentication path, and an authentication path
built to be convenient is how products get owned - so most of what
follows is about the ways it has to refuse, not the way it works:

  * a token nobody issued restores nothing;
  * a revoked token stops working the moment Log out is pressed;
  * an expired token restores nothing;
  * a token for a deleted user restores nothing;
  * role and company are re-read from the database every time, so a token
    confers a username and not one thing more.

That last property is what makes the whole arrangement safe. If the
session payload were carried in the token, editing it would be a
privilege escalation.

No database and no Streamlit server: db.database and st.context are
replaced, because every question here is about which decision the code
makes, not about what Postgres stores. The API is replaced too - what it
does when it redeems a handoff is stood in for by api_adopts() below, and
tested for real in tests/test_session_cookie_endpoint.py.
"""

import datetime

import pytest

from auth.browser_session import SESSION_IDLE_MINUTES, hash_handoff_code
from auth.refresh import generate_refresh_token, hash_refresh_token


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _minutes_ago(minutes):
    return _utcnow() - datetime.timedelta(minutes=minutes)


@pytest.fixture
def session(monkeypatch):
    """
    apps.web.session with everything outside the process replaced.

    ``st.session_state`` is a plain dict, the cookie the browser sent is
    a value the test sets, every database call is served from an
    in-memory store, and the request the page would make to the API is
    recorded rather than rendered.
    """

    from apps.web import session as module

    store = {
        "tokens": {},              # token_hash -> refresh_tokens row
        "users": {
            "anna": {
                "id": 1,
                "username": "anna",
                "role": "USER",
                "company": "Acme AG",
                "must_change_password": 0,
            },
        },
        "revoked": [],
        "handoffs": {},            # code_hash -> username
        "handoff_sessions": {},    # code_hash -> token_hash the API minted
        "cookies": {},             # what the browser sent with this page load
        "browser_calls": [],       # the requests the page was asked to make
        "touched": [],             # every "still here" write, throttle included
    }

    monkeypatch.setattr(module.st, "session_state", {}, raising=False)

    def fake_revoke(token_hash):
        store["revoked"].append(token_hash)
        if token_hash in store["tokens"]:
            store["tokens"][token_hash]["revoked"] = 1

    def fake_create_handoff(code_hash, username, expires_at):
        store["handoffs"][code_hash] = username
        return len(store["handoffs"])

    def fake_revoke_for_handoff(code_hash):
        token_hash = store["handoff_sessions"].get(code_hash)
        if token_hash and token_hash in store["tokens"]:
            store["tokens"][token_hash]["revoked"] = 1
            store["revoked"].append(token_hash)
            return True
        return False

    monkeypatch.setattr(module, "revoke_refresh_token", fake_revoke)
    monkeypatch.setattr(
        module, "get_refresh_token", lambda token_hash: store["tokens"].get(token_hash)
    )
    monkeypatch.setattr(module, "get_user", lambda username: store["users"].get(username))
    monkeypatch.setattr(module, "get_or_create_tenant", lambda company: 7)
    def fake_touch(token_hash):
        store["touched"].append(token_hash)
        if token_hash in store["tokens"]:
            store["tokens"][token_hash]["last_seen_at"] = _utcnow()
            return True
        return False

    def fake_touch_for_handoff(code_hash):
        return fake_touch(store["handoff_sessions"].get(code_hash) or "")

    monkeypatch.setattr(module, "create_session_handoff", fake_create_handoff)
    monkeypatch.setattr(module, "revoke_session_for_handoff", fake_revoke_for_handoff)
    monkeypatch.setattr(module, "touch_session", fake_touch)
    monkeypatch.setattr(module, "touch_session_for_handoff", fake_touch_for_handoff)
    monkeypatch.setattr(module, "_cookie_token", lambda: store["cookies"].get("token"))

    # Rendering would otherwise try to enqueue an element with no script
    # run to enqueue it into. Recording the call is also what lets the
    # tests below assert on what the browser was asked to do.
    monkeypatch.setattr(
        module,
        "_render_browser_request",
        lambda html: store["browser_calls"].append(html),
    )

    module._store = store

    return module


USER = {
    "id": 1,
    "username": "anna",
    "role": "USER",
    "company": "Acme AG",
    "tenant_id": 7,
    "must_change_password": False,
}


FAR_FUTURE = "2999-01-01 00:00:00"


def api_adopts(session, code=None, username="anna", expires_at=FAR_FUTURE,
               last_seen_at=None):
    """
    Stand in for the API redeeming a handoff code.

    apps/web/session.py never mints a session - it asks the API to, so
    the token goes straight into the cookie without passing through the
    browser. This is that half, reduced to what the tests need: a row in
    refresh_tokens, and the link back to the code that produced it.

    Returns the raw token, which is what the browser would then be
    holding in its cookie.
    """

    token = generate_refresh_token()
    token_hash = hash_refresh_token(token)

    session._store["tokens"][token_hash] = {
        "username": username,
        "token_hash": token_hash,
        "tenant_id": 7,
        "expires_at": expires_at,
        "revoked": 0,
        # A session the API has just minted was, by definition, used a
        # moment ago. Overridden by the idle tests below.
        "last_seen_at": last_seen_at or _utcnow(),
    }

    if code:
        session._store["handoff_sessions"][hash_handoff_code(code)] = token_hash

    return token


def arrive_with(session, cookie=None):
    """A fresh page load, carrying whatever cookie the browser had."""

    session.st.session_state.clear()
    session._store["cookies"].clear()

    if cookie:
        session._store["cookies"]["token"] = cookie


def sign_in(session):
    """Log in, and let the API redeem the handoff. Returns the cookie."""

    code = session.remember_session(USER)

    return api_adopts(session, code)


# ------------------------------------------------------- the reported bug ---


def test_a_remembered_session_survives_the_page_being_refreshed(session):
    """
    The defect, directly. A refresh empties session_state; the cookie is
    the only thing that crosses that boundary.
    """

    cookie = sign_in(session)

    arrive_with(session, cookie=cookie)

    restored = session.restore_session()

    assert restored is not None, (
        "the session cookie restored nothing, so the user is returned to "
        "the login form by an action that should not end a session"
    )
    assert restored["username"] == "anna"
    assert restored["tenant_id"] == 7


def test_the_restored_session_is_shaped_like_the_one_login_writes(session):
    """
    Two paths produce a signed-in user. A key present on one and absent
    on the other is an AttributeError on whichever page reads it, in
    exactly one of the two cases - which is the kind of bug that reaches
    production.
    """

    arrive_with(session, cookie=sign_in(session))

    assert set(session.restore_session()) == set(USER)


# --------------------------------------------------------- refusing ---


def test_a_token_nobody_issued_restores_nothing(session):

    arrive_with(session, cookie="not-a-real-token")

    assert session.restore_session() is None


def test_logging_out_stops_the_cookie_from_working(session):
    """
    Revocation is server-side, so a cookie still sitting in a browser -
    or copied out of one - is dead the moment Log out is pressed.
    """

    cookie = sign_in(session)

    arrive_with(session, cookie=cookie)
    session.restore_session()

    session.forget_session()

    arrive_with(session, cookie=cookie)

    assert session.restore_session() is None


def test_an_expired_token_restores_nothing(session):

    code = session.remember_session(USER)
    cookie = api_adopts(session, code, expires_at="2020-01-01 00:00:00")

    arrive_with(session, cookie=cookie)

    assert session.restore_session() is None


def test_an_unreadable_expiry_is_treated_as_expired(session):
    """
    Fail closed. A row whose expiry cannot be parsed is a storage bug,
    and the safe reading of a storage bug is "this session has ended",
    not "this session never ends".
    """

    assert session._has_expired("not a timestamp") is True
    assert session._has_expired(None) is True
    assert session._has_expired("") is True


def test_a_token_for_a_deleted_user_restores_nothing(session):

    arrive_with(session, cookie=sign_in(session))

    del session._store["users"]["anna"]

    assert session.restore_session() is None


def test_no_cookie_means_no_session_and_no_error(session):

    arrive_with(session)

    assert session.restore_session() is None


# ------------------------------------------- the token confers nothing ---


def test_the_role_is_read_from_the_database_not_from_the_token(session):
    """
    A token names a user. Everything else - role, company, tenant - is
    looked up again on every restore, so a promotion or a demotion takes
    effect immediately and a forged cookie cannot manufacture privileges.
    """

    arrive_with(session, cookie=sign_in(session))

    session._store["users"]["anna"]["role"] = "ADMIN"

    assert session.restore_session()["role"] == "ADMIN"

    session._store["users"]["anna"]["role"] = "READONLY"

    assert session.restore_session()["role"] == "READONLY"


# ------------------------------------------------------ walking away ---
#
# Durable sessions cost something, and it was reported: "I closed the
# window without logging out, opened the app again, and it went straight
# to the dashboard." Correct - that is what durable means - and not what
# anyone wants from a machine in a shared office holding passport scans.
#
# Before this, closing the tab *was* the logout, because the session
# lived only in the Streamlit server's memory. Nobody had to decide
# anything. Now somebody does.


def test_a_session_nobody_has_used_stops_working(session):
    """
    The reported behaviour, ended.

    expires_at cannot do this on its own: it counts from the login, so
    any value short enough to protect an abandoned machine also throws
    out a consultant in the middle of a case.
    """

    code = session.remember_session(USER)
    cookie = api_adopts(
        session, code, last_seen_at=_minutes_ago(SESSION_IDLE_MINUTES + 5)
    )

    arrive_with(session, cookie=cookie)

    assert session.restore_session() is None


def test_an_abandoned_session_is_revoked_not_merely_refused(session):
    """
    Refusing to restore leaves a working token in whatever browser was
    left open on that desk. Ending it server-side is what makes walking
    away equivalent to logging out.
    """

    code = session.remember_session(USER)
    cookie = api_adopts(
        session, code, last_seen_at=_minutes_ago(SESSION_IDLE_MINUTES + 5)
    )

    arrive_with(session, cookie=cookie)
    session.restore_session()

    assert session._store["tokens"][hash_refresh_token(cookie)]["revoked"] == 1


def test_a_session_in_use_is_not_treated_as_abandoned(session):
    """
    The other half, and the one that turns this from a security control
    into a complaint if it is wrong. Someone who is working must not be
    signed out for having logged in a while ago.
    """

    code = session.remember_session(USER)
    cookie = api_adopts(
        session, code, last_seen_at=_minutes_ago(SESSION_IDLE_MINUTES - 5)
    )

    arrive_with(session, cookie=cookie)

    assert session.restore_session() is not None


def test_an_unknown_last_use_counts_as_abandoned(session):
    """
    Fail closed. Reading "we do not know when this was last used" as
    "recently" produces a session that can never go idle, which is the
    whole failure being fixed. Migration 0009 backfills the column so no
    live session starts out unknown.
    """

    assert session._has_gone_idle(None) is True
    assert session._has_gone_idle("") is True
    assert session._has_gone_idle("not a timestamp") is True


def test_working_keeps_the_session_alive(session):
    """
    Activity is recorded on every rerun - which is every click - so the
    clock runs from the last thing the person did, not from their login.
    """

    arrive_with(session, cookie=sign_in(session))
    session.restore_session()

    session._store["touched"].clear()
    session.st.session_state.pop("_session_touched_at", None)

    session.keep_session_alive()

    assert session._store["touched"], (
        "nothing recorded that the user is still here, so an active "
        "session ages as if the screen were unattended"
    )


def test_recording_activity_is_throttled(session):
    """
    keep_session_alive() runs on every interaction. One UPDATE per click
    would make an idle-timeout column the busiest write in the product,
    for a value that is read once per page load and measured in tens of
    minutes.
    """

    arrive_with(session, cookie=sign_in(session))
    session.restore_session()

    before = len(session._store["touched"])

    for _ in range(20):
        session.keep_session_alive()

    assert len(session._store["touched"]) == before, (
        "every rerun wrote to the database"
    )


def test_the_session_created_in_this_page_load_can_still_be_kept_alive(session):
    """
    The case the handoff link exists for, again.

    Immediately after signing in, st.context.cookies reports what came
    with the websocket handshake - which is nothing - so the tab cannot
    name its own session. Without the handoff route, someone who logs in
    and then works for an hour without refreshing is active in fact and
    idle by the clock, and is signed out the moment they refresh.
    """

    code = session.remember_session(USER)
    cookie = api_adopts(session, code)

    assert session._cookie_token() is None

    session.keep_session_alive()

    assert hash_refresh_token(cookie) in session._store["touched"]


def test_a_new_session_is_not_born_already_abandoned():
    """
    The bug this test exists because of, and the reason it reads the SQL.

    _has_gone_idle() fails closed, so a refresh_tokens row inserted with
    no last_seen_at is an abandoned session at the instant it is created.
    The symptom was exact and unhelpful: sign in, refresh, back at the
    login form - every time - while the same session survived perfectly
    if you happened to click around for a minute first, because a touch
    landed before the refresh did.

    Everything above this line passed throughout, because the fake in
    this file's fixture set last_seen_at itself while the real INSERT did
    not. A fake that is kinder than the code it stands for tests the
    fake. So this one reads the statement.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "db" / "database.py"
    ).read_text(encoding="utf-8")

    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "create_refresh_token"
    )

    statements = " ".join(
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )

    assert "last_seen_at" in statements, (
        "create_refresh_token() inserts no last_seen_at, so every session "
        "it creates is already idle and a refresh straight after signing "
        "in returns the user to the login form"
    )


def test_activity_is_recorded_once_the_session_exists_to_record_it(session):
    """
    The throttle must not start on a write that landed nowhere.

    In the page load that signs in, the frame asking the API to redeem
    the handoff has been rendered but the browser has not made the
    request yet - so there is no session row to mark as used. Treating
    that as done would ignore the next sixty seconds of clicks, which are
    precisely the seconds in which the session appears.
    """

    code = session.remember_session(USER)

    # Before the API has redeemed anything.
    session.keep_session_alive()

    assert "_session_touched_at" not in session.st.session_state, (
        "the throttle started on a write that matched no row"
    )

    cookie = api_adopts(session, code)

    session.keep_session_alive()

    assert hash_refresh_token(cookie) in session._store["touched"]
    assert "_session_touched_at" in session.st.session_state


def test_a_failed_activity_write_does_not_break_the_page(session, monkeypatch):
    """
    This runs on every interaction. An exception here would be an error
    on the dashboard in exchange for a value that matters to the minute.
    """

    arrive_with(session, cookie=sign_in(session))
    session.restore_session()

    session.st.session_state.pop("_session_touched_at", None)

    def explode(token_hash):
        raise RuntimeError("database is down")

    monkeypatch.setattr(session, "touch_session", explode)

    session.keep_session_alive()  # must not raise


def test_require_login_records_activity():
    """
    A static check on login.py. The session module can be correct and the
    page can still never tell it that anyone is there - in which case
    every user is signed out thirty minutes after logging in, however
    hard they are working.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "apps" / "web" / "login.py"
    ).read_text(encoding="utf-8")

    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "require_login"
    )

    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(function) if isinstance(node, ast.Call)
    }

    assert "keep_session_alive" in called


def test_the_idle_window_is_shorter_than_the_session_itself():
    """
    An idle timeout longer than the maximum session length is a setting
    that does nothing, and reads in a security review as a control that
    is present.
    """

    from auth.browser_session import (
        BROWSER_SESSION_HOURS,
        SESSION_IDLE_MINUTES,
    )

    assert SESSION_IDLE_MINUTES < BROWSER_SESSION_HOURS * 60


# ------------------------------------------------------------- lifetime ---


def test_a_browser_session_is_far_shorter_than_an_api_refresh_token():
    """
    Guards the constant against being "harmonised" with the API's.

    REFRESH_TOKEN_EXPIRY_DAYS is thirty days, which is defensible for a
    token held by a server-to-server client and not for one held by a
    browser on a desk in an open-plan office.
    """

    from auth.browser_session import BROWSER_SESSION_HOURS
    from auth.refresh import REFRESH_TOKEN_EXPIRY_DAYS

    assert BROWSER_SESSION_HOURS <= 24
    assert BROWSER_SESSION_HOURS < REFRESH_TOKEN_EXPIRY_DAYS * 24


# ----------------------------------------------- login must not be blocked ---


def test_a_login_still_succeeds_when_the_handoff_cannot_be_issued(session,
                                                                  monkeypatch):
    """
    Persistence is an improvement on the old behaviour, not a
    precondition for signing in. If the write fails, the user gets what
    they had before - a session that a refresh ends - rather than being
    refused a login they authenticated for.
    """

    def explode(**kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(session, "create_session_handoff", explode)

    assert session.remember_session(USER) is None
    assert "_session_browser_action" not in session.st.session_state


def test_a_failing_token_store_does_not_break_the_page(session, monkeypatch):
    """
    Restore is called on every page load. An exception here would be an
    unhandled error on the dashboard, not a login form.
    """

    arrive_with(session, cookie="anything")

    def explode(token_hash):
        raise RuntimeError("database is down")

    monkeypatch.setattr(session, "get_refresh_token", explode)

    assert session.restore_session() is None


# -------------------------------------------------------- the handoff ---


def test_logging_in_asks_the_browser_to_adopt_a_cookie(session):
    """
    Streamlit cannot set a cookie, so it queues a request for the browser
    to make. Queued rather than made: login() calls st.rerun() straight
    after, which discards anything rendered in the same run.
    """

    session.remember_session(USER)

    assert session.st.session_state["_session_browser_action"] == "adopt"
    assert session._store["browser_calls"] == [], (
        "the request was rendered in the run that st.rerun() throws away, "
        "so no cookie is ever set"
    )

    session.emit_pending_browser_updates()

    assert len(session._store["browser_calls"]) == 1
    assert "/api/session/adopt" in session._store["browser_calls"][0]


def test_the_request_is_made_once_not_on_every_rerun(session):
    """
    Streamlit reruns the whole script on every interaction. A request
    left queued would re-mint a session on every click, filling
    refresh_tokens with rows nobody can account for.
    """

    session.remember_session(USER)

    session.emit_pending_browser_updates()
    session.emit_pending_browser_updates()
    session.emit_pending_browser_updates()

    assert len(session._store["browser_calls"]) == 1


def test_only_the_handoff_code_crosses_the_browser_never_a_session(session):
    """
    The property the whole handoff exists for.

    HttpOnly stops page script reading the cookie. Handing the session
    token to the page in order to get it into that cookie would put it
    within reach of exactly the script the cookie is meant to defeat.
    """

    code = session.remember_session(USER)
    cookie = api_adopts(session, code)

    session.emit_pending_browser_updates()

    rendered = session._store["browser_calls"][0]

    assert cookie not in rendered, (
        "a session token was written into the page, so any injected "
        "script can read the thing HttpOnly was adopted to hide"
    )

    assert code in rendered
    assert hash_handoff_code(code) in session._store["handoffs"]


def test_the_handoff_is_stored_only_as_a_hash(session):
    """A leaked backup of the handoff table must not be a set of logins."""

    code = session.remember_session(USER)

    assert code not in session._store["handoffs"]
    assert len(next(iter(session._store["handoffs"]))) == 64  # sha256, hex


def test_two_logins_do_not_produce_the_same_handoff(session):

    assert session.remember_session(USER) != session.remember_session(USER)


def test_the_handoff_is_long_enough_to_be_unguessable(session):

    assert len(session.remember_session(USER)) >= 40


# ------------------------------------------------------------- logout ---


def test_logging_out_revokes_the_cookie_it_can_see(session):

    cookie = sign_in(session)

    arrive_with(session, cookie=cookie)
    session.restore_session()

    session.forget_session()

    arrive_with(session, cookie=cookie)

    assert session.restore_session() is None


def test_logging_out_revokes_the_cookie_it_cannot_see_yet(session):
    """
    The case that makes session_handoff.session_id load-bearing.

    Sign in and sign out within one page load and st.context.cookies
    still reports what arrived with the websocket handshake - which is
    nothing. The tab cannot name the cookie session it just created.
    Without the handoff link, Log out would clear the screen and leave
    that session alive until it expired on its own.

    Not an edge case: it is what happens on a shared machine when someone
    checks one thing and leaves.
    """

    code = session.remember_session(USER)
    cookie = api_adopts(session, code)

    # No refresh in between, so the cookie is still invisible here.
    assert session._cookie_token() is None

    session.forget_session()

    arrive_with(session, cookie=cookie)

    assert session.restore_session() is None, (
        "the session created in this page load survived Log out, because "
        "nothing could name it"
    )


def test_logging_out_does_not_depend_on_the_browser(session):
    """
    Revocation happens in Python against the database. The request asking
    the browser to drop the cookie is tidying, not the mechanism - a
    blocked request or a tab closed mid-logout must not leave a working
    session behind.
    """

    cookie = sign_in(session)

    arrive_with(session, cookie=cookie)
    session.restore_session()

    session._store["browser_calls"].clear()

    session.forget_session()

    assert session._store["browser_calls"] == []
    assert session._store["tokens"][hash_refresh_token(cookie)]["revoked"] == 1


# ------------------------------------------- the URL path is really gone ---


def test_the_session_never_touches_the_query_string():
    """
    The regression guard for the fallback that was deleted.

    The token lived in the URL for one release, and the cost was a
    printout: a working session in the footer of every page of an
    exported case file, plus the address bar, browser history, and any
    copied link.

    It came out rather than being switched off, so what stops it coming
    back is this test and not an environment variable. Navigation state
    still uses query parameters - see apps/web/state/navigation.py, which
    is deliberately not scanned here; a page name in a URL is not a
    credential.
    """

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    for name in ("session.py", "login.py"):

        source = (root / "apps" / "web" / name).read_text(encoding="utf-8")

        assert "query_params" not in source, (
            f"apps/web/{name} touches the query string again; a session "
            f"token in a URL is in the address bar, in history, and in "
            f"the footer of every printed page"
        )


# ------------------------------------------------------ the call site ---


def test_require_login_consults_the_durable_store_before_giving_up():
    """
    A static check on login.py, because that is where the bug was: the
    session module can be perfect and the page can still call login()
    without asking it anything.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "apps" / "web" / "login.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "require_login"
    )

    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(function) if isinstance(node, ast.Call)
    }

    assert "restore_session" in called, (
        "require_login() shows the login form without asking whether a "
        "session already exists, so every page refresh signs the user out"
    )

    assert "emit_pending_browser_updates" in called, (
        "nothing makes the request that sets or clears the cookie, so a "
        "login is forgotten by the next refresh and a logout leaves the "
        "cookie in the browser"
    )


def test_logging_out_clears_both_halves_of_the_session():
    """
    Revoking without clearing session_state leaves this tab signed in;
    clearing without revoking leaves the cookie working. Log out has to
    do both or it does not mean what it says.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "apps" / "web" / "login.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "logout"
    )

    body = ast.dump(function)

    assert "forget_session" in body
    assert "'user'" in body or '"user"' in body


def test_the_interface_offers_a_way_to_log_out():
    """
    Sessions are durable now. Without this control a shared machine stays
    signed in until the session expires by itself, and the person who
    wanted to leave has no way to make it happen - which the previous,
    memory-only model hid, because closing the tab was the logout.
    """

    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "apps" / "web" / "app.py"
    ).read_text(encoding="utf-8")

    assert "logout(" in source, (
        "no page calls logout(), so the product keeps a durable session "
        "with no way for the user to end it"
    )
