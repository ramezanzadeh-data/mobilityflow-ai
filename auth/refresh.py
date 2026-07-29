import os
import secrets
import hashlib
import datetime

REFRESH_TOKEN_EXPIRY_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRY_DAYS", "30"))


def generate_refresh_token():
    return secrets.token_urlsafe(48)


def hash_refresh_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry_timestamp():
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=REFRESH_TOKEN_EXPIRY_DAYS
    )
    return expires.strftime("%Y-%m-%d %H:%M:%S")


def now_timestamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
