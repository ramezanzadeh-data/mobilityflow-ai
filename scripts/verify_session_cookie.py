"""
End-to-end check of the browser session cookie, against a running stack.

Usage (from the repository root, with docker compose up):

    docker compose exec -T api python -m scripts.verify_session_cookie

Runs inside the api container and talks to the *proxy*, not to the API
directly, because the thing being verified is the whole path a browser
takes: nginx maps /api/ onto the API, the API sets a first-party cookie,
and the same-origin check sees an Origin that matches the Host.

Prints one line per property and exits non-zero if any of them fails.
Nothing is left behind: the sessions it mints are revoked before it
returns.
"""

from bootstrap import load_environment

load_environment()

import os  # noqa: E402  (deliberate - see above)

import requests  # noqa: E402

from auth.browser_session import (  # noqa: E402
    SESSION_COOKIE_NAME,
    generate_handoff_code,
    handoff_expiry,
    hash_handoff_code,
)
from db.database import (  # noqa: E402
    create_session_handoff,
    get_user,
    revoke_session_for_handoff,
)


BASE_URL = os.environ.get("MOBILITYFLOW_VERIFY_BASE_URL", "http://proxy")

ORIGIN = BASE_URL

USERNAME = os.environ.get("DEFAULT_ADMIN_USERNAME", "admin")

TIMEOUT = 10


_results = []


def check(description, condition, detail=""):

    _results.append(bool(condition))

    mark = "PASS" if condition else "FAIL"

    print(f"[{mark}] {description}{f'  -  {detail}' if detail else ''}")


def mint_code():
    """A real handoff code, issued the way apps/web/session.py issues one."""

    code = generate_handoff_code()

    create_session_handoff(
        code_hash=hash_handoff_code(code),
        username=USERNAME,
        expires_at=handoff_expiry(),
    )

    return code


def adopt(code, origin=ORIGIN):

    headers = {} if origin is None else {"Origin": origin}

    return requests.post(
        f"{BASE_URL}/api/session/adopt",
        json={"code": code},
        headers=headers,
        timeout=TIMEOUT,
        allow_redirects=False,
    )


def main():

    print(f"target: {BASE_URL}   user: {USERNAME}\n")

    if not get_user(USERNAME):
        print(f"No such user {USERNAME!r}. Set DEFAULT_ADMIN_USERNAME.")
        return 2

    # 1. The proxy is carrying the API at all.
    health = requests.get(f"{BASE_URL}/api/health", timeout=TIMEOUT)
    check("/api/health answers through the proxy", health.status_code == 200,
          f"status {health.status_code}")

    # 2. A real handoff sets a cookie with the attributes it exists for.
    code = mint_code()
    response = adopt(code)

    check("adopt answers 204", response.status_code == 204,
          f"status {response.status_code}")

    cookie = response.headers.get("set-cookie", "")

    check("a session cookie is set", cookie.startswith(f"{SESSION_COOKIE_NAME}="),
          cookie or "no Set-Cookie header")
    check("the cookie is HttpOnly", "HttpOnly" in cookie)
    check("the cookie is SameSite=Lax", "samesite=lax" in cookie.lower())
    check("the cookie is scoped to /", "Path=/" in cookie)
    check("the handoff code is not the session token", code not in cookie)

    # 3. Single use. The same code a second time mints nothing.
    replay = adopt(code)
    check("a replayed code is refused", replay.status_code == 401,
          f"status {replay.status_code}")

    revoke_session_for_handoff(hash_handoff_code(code))

    # 4. Login CSRF. A page on another origin cannot sign this browser in.
    hostile = adopt(mint_code(), origin="http://evil.example")
    check("a cross-origin request is refused", hostile.status_code == 403,
          f"status {hostile.status_code}")

    # 5. Not a browser, no cookie.
    headless = adopt(mint_code(), origin=None)
    check("a request with no Origin is refused", headless.status_code == 403,
          f"status {headless.status_code}")

    # 6. An unknown code.
    unknown = adopt("this-code-was-never-issued-anywhere-at-all")
    check("an unissued code is refused", unknown.status_code == 401,
          f"status {unknown.status_code}")

    failed = _results.count(False)

    print(f"\n{len(_results) - failed}/{len(_results)} passed")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
