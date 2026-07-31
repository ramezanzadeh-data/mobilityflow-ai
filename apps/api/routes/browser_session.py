"""
The two endpoints that put a browser session into an HttpOnly cookie.

Not part of the versioned API
-----------------------------
Mounted at ``/session``, outside ``/api/v1``. That router is a published
contract for machine clients: Bearer tokens, a version number, and a
promise not to change shape under anyone. These two are the opposite -
browser-only, cookie-bearing, same-origin, and free to change whenever
the web app does. Putting them under /api/v1 would have committed the
product to keeping them stable for integrators who should never call
them, and would have added a cookie-based path to a surface whose entire
authentication story is "send a Bearer token".

Through deploy/nginx.conf they are reachable as ``/api/session/adopt``
and ``/api/session/clear``.

What adopt does, and does not do
--------------------------------
It does not authenticate anybody. Authentication has already happened, in
Streamlit, against the same ``authenticate_user`` every other login path
uses. What arrives here is a handoff code proving that it happened - see
auth/browser_session.py for why the session token itself is deliberately
not the thing that crosses the browser.

From the code, the user is read again from the database. Role, company
and tenant are never taken from anything the browser sent. This is the
same property restore_session() has always had, and it is what makes the
whole arrangement safe: a handoff code names a user and confers nothing.

Why the same-origin check is here
---------------------------------
adopt sets a session cookie, so an attacker who could make a victim's
browser call it with a code of their choosing could sign that victim into
an account the attacker controls - login CSRF, and from there anything
the victim then does happens in the attacker's account.

SameSite does not prevent it: SameSite governs whether the browser sends
*existing* cookies, not whether it accepts new ones. So the request's own
origin is checked instead. A browser always sends Origin on a POST, so
requiring it costs nothing a legitimate caller has, and refuses every
cross-site one.
"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from auth.browser_session import (
    SESSION_COOKIE_NAME,
    BROWSER_SESSION_HOURS,
    cookie_should_be_secure,
    hash_handoff_code,
    session_expiry_timestamp,
)
from auth.refresh import generate_refresh_token, hash_refresh_token
from db.database import (
    consume_session_handoff,
    create_refresh_token,
    get_or_create_tenant,
    get_user,
    link_session_handoff,
    revoke_refresh_token,
    revoke_session_for_handoff,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/session", tags=["browser session"])


# Bounded so an oversized body is rejected before it reaches a hash and a
# query. Real codes are 64 characters.
HandoffCode = Annotated[str, Field(min_length=16, max_length=512)]


class AdoptRequest(BaseModel):

    code: HandoffCode


class ClearRequest(BaseModel):

    # Optional: a logout on a page load that did not create the session
    # has no handoff to name, only the cookie.
    code: Optional[HandoffCode] = None


def _request_is_https(request: Request):
    """
    Whether the browser reached us over TLS.

    X-Forwarded-Proto first, because in every real deployment TLS is
    terminated at the proxy and the scheme this process sees is the
    plain-HTTP hop behind it. deploy/nginx.conf sets the header.
    """

    forwarded = request.headers.get("x-forwarded-proto")

    if forwarded:
        # A comma-separated chain means several proxies; the first entry
        # is the one the browser actually spoke.
        return forwarded.split(",")[0].strip().lower() == "https"

    return request.url.scheme == "https"


def _require_same_origin(request: Request):
    """
    Refuse anything that did not come from a page on this origin.

    Compared by host rather than by full URL, because the scheme the
    browser used and the scheme this process sees differ behind TLS
    termination, and the port is absent from Host on the default ports.
    Comparing the origin's host against the Host header is the part that
    is true on both sides of a proxy.
    """

    origin = request.headers.get("origin")

    if not origin:
        # Every browser sends Origin on a POST. Its absence means the
        # caller is not a browser, and nothing but a browser has any use
        # for a cookie.
        raise HTTPException(status_code=403, detail="Origin required")

    host = request.headers.get("host")

    if not host:
        raise HTTPException(status_code=403, detail="Host required")

    origin_host = origin.split("://")[-1]

    if origin_host != host:
        logger.warning(
            "refused a cross-origin browser-session request from %r", origin
        )
        raise HTTPException(status_code=403, detail="Cross-origin request refused")


def _set_session_cookie(response: Response, token, secure):

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=BROWSER_SESSION_HOURS * 3600,
        path="/",
        # The reason this endpoint exists. Page script cannot read it, so
        # an injected script cannot exfiltrate a working session, and it
        # is never in the address bar, the history, or a copied link.
        httponly=True,
        secure=secure,
        # Lax, not Strict. Strict would withhold the cookie when a user
        # arrives from an external link - a case reference in an email,
        # say - so the product would show them the login form despite a
        # perfectly valid session. Lax sends it on top-level navigations
        # and withholds it on cross-site subrequests, which is the
        # distinction that matters here.
        samesite="lax",
    )


@router.post(
    "/adopt",
    status_code=204,
    summary="Redeem a one-time handoff code and set the session cookie",
    include_in_schema=False,
)
def adopt(payload: AdoptRequest, request: Request, response: Response):

    _require_same_origin(request)

    handoff = consume_session_handoff(hash_handoff_code(payload.code))

    if not handoff:
        # Unknown, already spent, or expired. Not distinguished, and not
        # logged with the code: the browser gains nothing from knowing
        # which, and the log would then contain credentials.
        raise HTTPException(status_code=401, detail="Invalid handoff code")

    user = get_user(handoff["username"])

    if not user:
        # Deleted between signing in and this request. Vanishingly rare,
        # and the safe reading is that there is no session to mint.
        raise HTTPException(status_code=401, detail="Invalid handoff code")

    token = generate_refresh_token()

    session_id = create_refresh_token(
        username=user["username"],
        token_hash=hash_refresh_token(token),
        tenant_id=get_or_create_tenant(user["company"]),
        expires_at=session_expiry_timestamp(),
        # Distinguishable from "streamlit" (the query-string sessions) and
        # from real API clients in /auth/sessions, so a user looking at
        # their active sessions sees where each came from.
        user_agent="streamlit-cookie",
    )

    link_session_handoff(handoff["id"], session_id)

    _set_session_cookie(
        response,
        token,
        secure=cookie_should_be_secure(_request_is_https(request)),
    )

    # Nothing is returned, deliberately. FastAPI merges the headers set on
    # the injected `response` into the 204 it builds; returning a Response
    # object here instead would discard them, taking the Set-Cookie - the
    # only thing this endpoint does - with it.
    return None


@router.post(
    "/clear",
    status_code=204,
    summary="Revoke the browser session and delete the session cookie",
    include_in_schema=False,
)
def clear(payload: ClearRequest, request: Request, response: Response):
    """
    End the session named by the cookie, and by the handoff if one is
    given.

    Both, because they can be different rows. The cookie names the
    session this page load arrived with; the handoff names the one this
    page load created, which the cookie will not mention until the next
    full page load. Logging out has to end whichever exist.

    This endpoint is not the only thing that revokes - apps/web/session.py
    revokes server-side as well, without involving the browser. A logout
    that a failed fetch could quietly skip would not be a logout.
    """

    _require_same_origin(request)

    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)

    if cookie_token:
        try:
            revoke_refresh_token(hash_refresh_token(cookie_token))
        except Exception:
            logger.warning("could not revoke a cookie session", exc_info=True)

    if payload.code:
        try:
            revoke_session_for_handoff(hash_handoff_code(payload.code))
        except Exception:
            logger.warning("could not revoke a handoff session", exc_info=True)

    # Same attributes as when it was set, minus a lifetime. A cookie is
    # deleted by matching name, path and domain; a mismatch here leaves
    # the old one in place and Log out stops working in the browser.
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=cookie_should_be_secure(_request_is_https(request)),
        samesite="lax",
    )

    return None
