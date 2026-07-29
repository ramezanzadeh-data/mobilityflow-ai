
import hashlib
import os

_HASH_ITERATIONS = 100_000


def hash_password(password, salt=None):

    if salt is None:
        salt = os.urandom(16).hex()

    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _HASH_ITERATIONS
    ).hex()

    return f"{salt}${hashed}"


def verify_password(password, stored_hash):

    try:
        salt, hashed = stored_hash.split("$")
    except (ValueError, AttributeError):


        return False

    check = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _HASH_ITERATIONS
    ).hex()

    return check == hashed
