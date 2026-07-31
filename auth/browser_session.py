"""
What a browser session is, stated once, for both halves of the product.

Two processes have to agree about the session in a user's browser. The
Streamlit app reads it and decides who is signed in; the FastAPI app
writes it and decides how long it lasts and under what cookie attributes.
If those two ever disagree - a different cookie name, a different
lifetime, one of them setting Secure and the other not - the symptom is a
user who is signed in on one page load and signed out on the next, with
nothing in either log saying why.

So the shared facts live here, in a module both import, rather than
twice.

Why the handoff exists at all
-----------------------------
Streamlit cannot set a cookie. A cookie is an HTTP response header, and
by the time Python runs in a Streamlit script the response that could
have carried one is long finished - what remains is a websocket. Only the
API can set one, and since deploy/nginx.conf it is same-origin, so a
cookie it sets is first-party for Streamlit too.

That leaves the question of how the API learns which user to mint a
session for. The answer is a handoff code: a single-use, seconds-lived
value that names a user and confers nothing else. The session token
itself never crosses the browser, because a token the browser has seen is
a token page script can read - which is the property HttpOnly is adopted
for in the first place.

See db/migrations/0008_session_handoff.up.sql for the storage and its
single-use guarantee.
"""

import datetime
import hashlib
import os
import secrets


# The cookie. Short and unremarkable: a name that advertises what it
# holds invites someone to go looking for it.
#
# Not `__Host-mf_session`, which would be the stronger choice: that
# prefix obliges the browser to reject the cookie unless it is Secure,
# and development runs on plain http://localhost. Adopting it would make
# the product work in production and silently not work on every
# developer's machine, which is the wrong way round. Revisit when
# development also runs over TLS.
SESSION_COOKIE_NAME = "mf_session"


# Short by design. The API's REFRESH_TOKEN_EXPIRY_DAYS is thirty days,
# defensible for a token held by a server-to-server client and not for
# one held in a browser on a desk in an open-plan office. A working day
# plus a margin covers "I refreshed the page" and "I came back after
# lunch", which is the whole problem this solves.
BROWSER_SESSION_HOURS = int(
    os.environ.get("MOBILITYFLOW_BROWSER_SESSION_HOURS", "12")
)


# How long a session survives with nobody using it.
#
# Separate from BROWSER_SESSION_HOURS, and both apply: that one caps how
# long a single login may last at all, this one ends a session nobody has
# touched. Only having the first meant an unattended machine in an office
# stayed signed in for the rest of the working day, which is how this
# came to be added - closing the window stopped being a logout the moment
# sessions became durable.
#
# Thirty minutes is the usual figure for a product holding personal data
# that is not money. Shorter is for banking; longer stops being a control
# and becomes a formality. It is the one number here worth tuning per
# customer, because it trades directly against interrupting someone who
# is reading a long case file.
SESSION_IDLE_MINUTES = int(
    os.environ.get("MOBILITYFLOW_SESSION_IDLE_MINUTES", "30")
)


# The handoff is alive for one page's worth of work: render an invisible
# frame, make one request. Thirty seconds is already generous for that,
# and every second of it is a second in which a code sitting in the DOM
# could be read by injected script. Not configurable - there is no
# deployment for which a longer window is the right answer, and making it
# tunable would only offer a way to weaken it.
SESSION_HANDOFF_SECONDS = 30


# Whether the cookie is marked Secure.
#
#   "auto"  - Secure when the request that sets it arrived over HTTPS.
#   "true"  - always. Correct for any deployment terminating TLS, and the
#             right setting if a proxy in front of this one strips
#             X-Forwarded-Proto.
#   "false" - never. For plain-HTTP development only.
#
# "auto" is the default because the alternatives each fail somewhere:
# hardcoding Secure makes the cookie silently vanish on http://localhost,
# and never setting it lets a session travel in clear text the first time
# someone deploys behind TLS.
SESSION_COOKIE_SECURE_MODE = os.environ.get(
    "MOBILITYFLOW_SESSION_COOKIE_SECURE", "auto"
).strip().lower()


# There is deliberately no switch here to put the session token back in
# the URL.
#
# One existed for a single release, defaulting to on, while the cookie
# path was confirmed against a real deployment - the cookie depends on a
# same-origin request made from the browser, and that is not something
# this repository can prove on its own. It was confirmed, and then the
# fallback was deleted rather than left switched off. A hole one
# environment variable away from reopening is still a hole, and that
# variable is exactly the kind of thing that gets set during an incident
# by whoever is awake and never unset afterwards.
#
# If the cookie cannot be set, the correct behaviour is the one that now
# happens: the user is signed in for that page load and returned to the
# login form by their next refresh. Annoying, visible, and reported -
# which is what a broken session should be.


def generate_handoff_code():
    """A handoff code. Same size as a session token; guessing is not a route."""

    return secrets.token_urlsafe(48)


def hash_handoff_code(code):
    """
    What gets stored. The code itself is never written down.

    Plain SHA-256 rather than a password hash, deliberately: this is a
    48-byte random value with no entropy to protect and a thirty-second
    life, so there is nothing for a slow hash to defend against, and a
    slow hash on the login path would be a cost paid on every sign-in for
    no gain.
    """

    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def handoff_expiry():
    """When a code issued now stops being redeemable."""

    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=SESSION_HANDOFF_SECONDS
    )


def session_expiry_timestamp():
    """
    When a session created now expires, in the shape refresh_tokens uses.

    That column is TEXT and is compared as text elsewhere in
    db.database - list_active_sessions() does so against to_char(NOW()).
    The format is therefore not cosmetic: any other one would sort
    incorrectly against the rows already in the table.
    """

    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        hours=BROWSER_SESSION_HOURS
    )

    return expires.strftime("%Y-%m-%d %H:%M:%S")


def cookie_should_be_secure(request_is_https):
    """
    Resolve SESSION_COOKIE_SECURE_MODE against how the request arrived.

    An unrecognised value is treated as "auto" rather than refused. This
    is read on the login path, and a typo in an environment variable
    should not be able to stop everyone signing in.
    """

    if SESSION_COOKIE_SECURE_MODE == "true":
        return True

    if SESSION_COOKIE_SECURE_MODE == "false":
        return False

    return bool(request_is_https)
