
import os
import datetime

import jwt


JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60

# Minimum acceptable length for the secret. 32 chars is a low bar (16
# bytes if hex-encoded) but catches the common mistake of copy-pasting
# a short test string into production.
_MIN_SECRET_LENGTH = 32

_ENV_SECRET = os.environ.get("JWT_SECRET_KEY")

if not _ENV_SECRET:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is not set. Refusing to "
        "start with a randomly-generated, process-local secret: that "
        "would invalidate every issued token on restart and produce a "
        "different secret per worker process, silently breaking auth "
        "under any multi-process deployment. Generate one with "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
        "and set it in your environment/.env file."
    )

if len(_ENV_SECRET) < _MIN_SECRET_LENGTH:
    raise RuntimeError(
        f"JWT_SECRET_KEY is only {len(_ENV_SECRET)} characters long; "
        f"it must be at least {_MIN_SECRET_LENGTH}. Generate a proper "
        "one with `python -c \"import secrets; print(secrets.token_hex(32))\"`."
    )

if _ENV_SECRET.strip().lower() in {
    "change-me-to-a-long-random-value",
    "change_me",
    "changeme",
    "secret",
}:
    raise RuntimeError(
        "JWT_SECRET_KEY is still set to a placeholder value from "
        ".env.example. Generate a real secret with "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
        "and set it before starting the app."
    )

SECRET_KEY = _ENV_SECRET


class TokenError(Exception):
    pass


def create_access_token(username, role, company, tenant_id=None):

    now = datetime.datetime.now(datetime.timezone.utc)

    payload = {
        "sub": username,
        "role": role,
        "company": company,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRY_MINUTES),
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


MFA_PENDING_EXPIRY_MINUTES = 5


def create_mfa_pending_token(username):

    now = datetime.datetime.now(datetime.timezone.utc)

    payload = {
        "sub": username,
        "purpose": "mfa_pending",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=MFA_PENDING_EXPIRY_MINUTES),
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_mfa_pending_token(token):

    payload = verify_access_token(token)

    if payload.get("purpose") != "mfa_pending":
        raise TokenError("Not a valid MFA pending token.")

    return payload


def verify_access_token(token):

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload

    except jwt.ExpiredSignatureError:
        raise TokenError("Token has expired. Please log in again.")

    except jwt.InvalidTokenError as e:
        raise TokenError(f"Invalid token: {e}")
