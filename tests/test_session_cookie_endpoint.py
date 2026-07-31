"""
The endpoint that takes the session token out of the URL.

Streamlit cannot set a cookie - its Python runs behind a websocket whose
handshake is long over - so the API sets one on its behalf, and the two
are introduced by a single-use handoff code. That makes /session/adopt an
authentication endpoint, and an authentication endpoint is judged by what
it refuses.

Which is most of what is below: a code that was already spent, a code for
a user who no longer exists, a request from another origin, a request
from something that is not a browser at all. The one positive test is
that the cookie it does set carries the attributes it is being adopted
for - HttpOnly above all, since a cookie without it is a session token in
the DOM with extra steps.

No HTTP client and no database. Requests are built as ASGI scopes, which
is what Starlette parses anyway, and the two database calls are replaced.
Every question here is about which decision the code makes.
"""

from urllib.parse import quote

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from apps.api.routes import browser_session as route
from auth.browser_session import SESSION_COOKIE_NAME


def make_request(origin="http://localhost", host="localhost",
                 forwarded_proto=None, cookies=None):
    """A POST as Starlette sees it, without an HTTP client in between."""

    headers = [(b"content-type", b"application/json")]

    if host is not None:
        headers.append((b"host", host.encode()))

    if origin is not None:
        headers.append((b"origin", origin.encode()))

    if forwarded_proto:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))

    if cookies:
        jar = "; ".join(f"{k}={quote(v)}" for k, v in cookies.items())
        headers.append((b"cookie", jar.encode()))

    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/session/adopt",
        "raw_path": b"/session/adopt",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("192.0.2.10", 51000),
        "server": ("api", 8000),
    })


ANNA = {
    "id": 1,
    "username": "anna",
    "role": "USER",
    "company": "Acme AG",
    "must_change_password": 0,
}


@pytest.fixture
def api(monkeypatch):
    """The route module with its four database calls replaced."""

    store = {
        "handoff": {"id": 11, "username": "anna"},   # what consume returns
        "user": ANNA,
        "created": [],
        "linked": [],
        "revoked": [],
        "revoked_handoffs": [],
    }

    def fake_consume(code_hash):
        store["consumed"] = code_hash
        return store["handoff"]

    def fake_create(username, token_hash, tenant_id, expires_at, user_agent=None):
        store["created"].append({
            "username": username,
            "token_hash": token_hash,
            "tenant_id": tenant_id,
            "expires_at": expires_at,
            "user_agent": user_agent,
        })
        return 99

    monkeypatch.setattr(route, "consume_session_handoff", fake_consume)
    monkeypatch.setattr(route, "get_user", lambda u: store["user"])
    monkeypatch.setattr(route, "get_or_create_tenant", lambda company: 7)
    monkeypatch.setattr(route, "create_refresh_token", fake_create)
    monkeypatch.setattr(
        route, "link_session_handoff",
        lambda handoff_id, session_id: store["linked"].append((handoff_id, session_id))
    )
    monkeypatch.setattr(
        route, "revoke_refresh_token",
        lambda token_hash: store["revoked"].append(token_hash)
    )
    monkeypatch.setattr(
        route, "revoke_session_for_handoff",
        lambda code_hash: store["revoked_handoffs"].append(code_hash)
    )

    route._store = store

    return route


CODE = "a-handoff-code-long-enough-to-pass-validation"


def adopt(api, request=None):
    """Call the endpoint and return the Response it wrote headers into."""

    response = Response()

    api.adopt(
        api.AdoptRequest(code=CODE),
        request or make_request(),
        response,
    )

    return response


def set_cookie_header(response):

    header = response.headers.get("set-cookie")

    assert header, "no cookie was set, which is the only thing this endpoint does"

    return header


# --------------------------------------------------- what it sets ---


def test_the_cookie_is_httponly(api):
    """
    The reason the endpoint exists. Without this flag the session is
    readable by any script on the page, and the whole change amounts to
    moving the token from one place script can read to another.
    """

    assert "HttpOnly" in set_cookie_header(adopt(api))


def test_the_cookie_is_samesite_lax(api):
    """
    Lax, not None. A session cookie sent on cross-site subrequests is a
    CSRF primitive; the browser withholding it is a defence the product
    gets for the price of one attribute.
    """

    assert "samesite=lax" in set_cookie_header(adopt(api)).lower()


def test_the_cookie_is_scoped_to_the_whole_site(api):
    """
    Streamlit is at / and the API at /api/. A narrower path would set a
    cookie that the pages needing it never receive.
    """

    assert "Path=/" in set_cookie_header(adopt(api))


def test_the_cookie_is_marked_secure_when_the_browser_used_tls(api):
    """
    TLS terminates at the proxy, so this process sees plain HTTP and has
    to be told. deploy/nginx.conf sets X-Forwarded-Proto; without reading
    it, every production cookie would go out unmarked and travel in clear
    text on any downgraded request.
    """

    request = make_request(forwarded_proto="https")

    assert "Secure" in set_cookie_header(adopt(api, request))


def test_the_cookie_is_not_marked_secure_on_plain_http(api):
    """
    Development runs on http://localhost. A browser silently discards a
    Secure cookie there, so hardcoding the flag would make the product
    work in production and appear broken on every developer's machine.
    """

    assert "Secure" not in set_cookie_header(adopt(api))


def test_the_handoff_code_is_not_what_lands_in_the_cookie(api):
    """
    The code is spent and seconds old; the session is neither. Reusing it
    as the session token would hand the browser back a value it had
    already seen in the DOM.
    """

    assert CODE not in set_cookie_header(adopt(api))


def test_the_session_is_stored_hashed(api):

    adopt(api)

    stored = api._store["created"][0]["token_hash"]

    assert len(stored) == 64            # sha256, hex
    assert stored not in set_cookie_header(adopt(api))


def test_the_tenant_is_read_from_the_database_not_from_the_request(api):
    """
    A handoff code names a user and confers nothing. Role, company and
    tenant are looked up again, exactly as restore_session() does, so a
    code cannot carry a privilege into the session it mints.
    """

    adopt(api)

    assert api._store["created"][0]["tenant_id"] == 7
    assert api._store["created"][0]["username"] == "anna"


def test_the_session_is_linked_to_the_handoff(api):
    """
    What lets Log out revoke this session in the same page load that
    created it, when st.context.cookies cannot see the cookie yet.
    """

    adopt(api)

    assert api._store["linked"] == [(11, 99)]


# ------------------------------------------------- what it refuses ---


def test_a_spent_or_unknown_code_is_refused(api, monkeypatch):
    """
    consume_session_handoff() returns None for unknown, already spent and
    expired alike. All three are one answer here, and the browser learns
    nothing about which.
    """

    monkeypatch.setattr(route, "consume_session_handoff", lambda code_hash: None)

    with pytest.raises(HTTPException) as refusal:
        adopt(api)

    assert refusal.value.status_code == 401


def test_a_code_for_a_deleted_user_mints_nothing(api, monkeypatch):

    monkeypatch.setattr(route, "get_user", lambda username: None)

    with pytest.raises(HTTPException) as refusal:
        adopt(api)

    assert refusal.value.status_code == 401
    assert api._store["created"] == []


def test_a_cross_origin_request_is_refused(api):
    """
    Login CSRF. An attacker who can make a victim's browser call this
    with a code of their own signs that victim into the attacker's
    account, and everything the victim then files goes into it.

    SameSite does not help: it governs whether the browser sends cookies
    it already has, not whether it accepts new ones.
    """

    with pytest.raises(HTTPException) as refusal:
        adopt(api, make_request(origin="http://evil.example"))

    assert refusal.value.status_code == 403
    assert api._store["created"] == []


def test_a_request_with_no_origin_is_refused(api):
    """
    Every browser sends Origin on a POST. Something that does not is not
    a browser, and nothing but a browser has any use for a cookie.
    """

    with pytest.raises(HTTPException) as refusal:
        adopt(api, make_request(origin=None))

    assert refusal.value.status_code == 403


def test_the_origin_must_match_the_host_it_reached(api):
    """
    Compared against Host rather than a configured value, so the check
    holds on localhost, on a customer's domain, and behind a rename, with
    nothing to keep in step.
    """

    request = make_request(origin="http://localhost", host="app.example.com")

    with pytest.raises(HTTPException) as refusal:
        adopt(api, request)

    assert refusal.value.status_code == 403


# ----------------------------------------------------------- clear ---


def test_clear_revokes_the_session_in_the_cookie(api):

    from auth.refresh import hash_refresh_token

    request = make_request(cookies={SESSION_COOKIE_NAME: "a-live-session"})

    api.clear(api.ClearRequest(), request, Response())

    assert api._store["revoked"] == [hash_refresh_token("a-live-session")]


def test_clear_also_revokes_the_session_named_by_a_handoff(api):
    """
    The two can be different rows: the cookie names the session this page
    load arrived with, the handoff names the one it created.
    """

    api.clear(api.ClearRequest(code=CODE), make_request(), Response())

    assert len(api._store["revoked_handoffs"]) == 1


def test_clear_deletes_the_cookie_with_the_attributes_it_was_set_with(api):
    """
    A cookie is replaced by matching name, path and domain. Get any of
    them wrong and the browser keeps the old one, so Log out leaves a
    session cookie sitting in the browser - dead, but still there to be
    explained in a security review.
    """

    response = Response()

    api.clear(api.ClearRequest(), make_request(), response)

    header = set_cookie_header(response)

    assert SESSION_COOKIE_NAME in header
    assert "Path=/" in header
    assert "Max-Age=0" in header or "expires=Thu, 01 Jan 1970" in header.lower()


def test_clear_is_refused_cross_origin_too(api):

    with pytest.raises(HTTPException):
        api.clear(
            api.ClearRequest(),
            make_request(origin="http://evil.example"),
            Response(),
        )


# -------------------------------------- and it survives the framework ---


def test_the_cookie_actually_reaches_the_wire(api):
    """
    Everything above inspects the Response object the endpoint wrote
    into. This one drives the ASGI app and reads the headers that would
    go to the browser, because between the two there is a framework
    decision that is easy to get wrong and impossible to notice.

    The endpoint returns None and is declared 204. FastAPI builds that
    204 itself and merges in the headers set on the injected Response.
    Returning a Response object instead - the more obvious way to write a
    204 - discards them, taking the Set-Cookie with it. The endpoint
    would still answer 204, the browser would still be sent on its way,
    and no cookie would ever be set: a silent, total failure of the only
    thing this endpoint does.

    So the merge is pinned here rather than trusted to survive the next
    FastAPI upgrade.
    """

    import asyncio
    import json

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api.router)

    body = json.dumps({"code": CODE}).encode()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/session/adopt",
        "raw_path": b"/session/adopt",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"localhost"),
            (b"origin", b"http://localhost"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("192.0.2.10", 51000),
        "server": ("api", 8000),
    }

    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))

    start = next(m for m in messages if m["type"] == "http.response.start")

    assert start["status"] == 204

    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}

    assert "set-cookie" in headers, (
        "the endpoint answered 204 and set no cookie - the response the "
        "browser receives has lost the only thing this endpoint does"
    )
    assert headers["set-cookie"].startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in headers["set-cookie"]


# ----------------------------------------- one definition, two apps ---


def test_the_web_app_and_the_api_agree_about_the_cookie_name():
    """
    The web app reads this cookie and the API writes it. Disagree about
    the name and the symptom is a user signed in on one page load and
    signed out on the next, with nothing in either log to say why. Both
    import the same module so that they cannot.

    Only the name is shared. How long the session lasts is the API's
    business alone - it is the only side that creates one - which is why
    apps/web/session.py no longer imports BROWSER_SESSION_HOURS at all.
    A constant imported and not used is a second opinion waiting to
    happen.
    """

    import auth.browser_session as policy
    from apps.web import session as web

    assert web.SESSION_COOKIE_NAME is policy.SESSION_COOKIE_NAME
    assert route.SESSION_COOKIE_NAME is policy.SESSION_COOKIE_NAME
    assert route.BROWSER_SESSION_HOURS == policy.BROWSER_SESSION_HOURS


def test_the_session_minted_here_expires_when_the_policy_says(api):
    """
    The cookie's Max-Age and the database row's expiry describe the same
    session and are written by two different lines. If they drift, the
    browser keeps sending a token the database has already stopped
    honouring - which presents as a random logout partway through a day.
    """

    import datetime

    from auth.browser_session import BROWSER_SESSION_HOURS

    response = adopt(api)

    header = set_cookie_header(response)

    assert f"Max-Age={BROWSER_SESSION_HOURS * 3600}" in header

    written = datetime.datetime.strptime(
        api._store["created"][0]["expires_at"], "%Y-%m-%d %H:%M:%S"
    )

    expected = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) \
        + datetime.timedelta(hours=BROWSER_SESSION_HOURS)

    assert abs((written - expected).total_seconds()) < 120


def test_two_logins_do_not_produce_the_same_session(api):
    """
    Moved here from the web tests when minting moved here. The token is
    the whole credential; two users holding the same one is one user.
    """

    adopt(api)
    adopt(api)

    minted = [row["token_hash"] for row in api._store["created"]]

    assert len(set(minted)) == 2


def test_the_session_token_is_long_enough_to_be_unguessable(api):

    cookie = set_cookie_header(adopt(api))

    value = cookie.split("=", 1)[1].split(";", 1)[0]

    assert len(value) >= 40


def test_the_browser_endpoints_are_not_published_as_api():
    """
    /api/v1 is a contract with integrators. These two are the web app
    talking to its own backend over cookies; publishing them would invite
    calls the product would then have to keep working.
    """

    for api_route in route.router.routes:
        assert api_route.include_in_schema is False, (
            f"{api_route.path} is published in the OpenAPI schema"
        )
