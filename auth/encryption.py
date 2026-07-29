
import os
import base64
import binascii

from cryptography.fernet import Fernet, InvalidToken


class DecryptionError(Exception):
    """
    Raised when a value looks like a Fernet token (i.e. it is valid
    base64 in the expected shape) but fails to decrypt with the
    configured key - meaning the data was encrypted with a different
    key, or has been corrupted/tampered with. This must never be
    silently swallowed: doing so would return raw ciphertext to the
    caller as if it were the real plaintext.
    """
    pass


_ENV_KEY = os.environ.get("ENCRYPTION_KEY")

if not _ENV_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY environment variable is not set. Refusing to "
        "start with a randomly-generated, process-local key: any data "
        "encrypted with it becomes permanently unreadable after a "
        "restart, and every worker process would use a different key. "
        "Generate one with "
        "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
        "and set it in your environment/.env file. Store it somewhere "
        "durable (secrets manager) - losing it makes existing "
        "encrypted data unrecoverable."
    )

try:
    _FERNET = Fernet(_ENV_KEY.encode() if isinstance(_ENV_KEY, str) else _ENV_KEY)
except (ValueError, binascii.Error) as exc:
    raise RuntimeError(
        "ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
        "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`."
    ) from exc


def generate_new_key():

    return Fernet.generate_key().decode()


def encrypt_text(plain_text):

    if plain_text is None:
        return None

    return _FERNET.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_text(encrypted_text):
    """
    Decrypt a value previously produced by encrypt_text.

    For backward compatibility with rows written before encryption was
    introduced, a value that is not even shaped like a Fernet token
    (i.e. it fails to base64-decode) is treated as legacy plain text
    and returned unchanged.

    A value that IS shaped like a Fernet token but fails to decrypt
    (wrong key, or tampered/corrupted data) is a real error and must
    be raised, not silently returned as if it were the plaintext -
    otherwise garbled ciphertext could be shown to a user as if it
    were their actual data.
    """

    if encrypted_text is None:
        return None

    raw = encrypted_text.encode("utf-8")

    # cryptography's Fernet.decrypt() collapses every internal failure
    # (bad base64, bad version byte, bad HMAC, wrong key) into the
    # single InvalidToken exception, so it can't tell us on its own
    # whether this was legacy plaintext or real-but-undecryptable
    # ciphertext. Check the base64 shape ourselves first: only a
    # string that isn't valid base64 at all is legacy plain text.
    try:
        base64.urlsafe_b64decode(raw)
    except (ValueError, binascii.Error):
        return encrypted_text

    try:
        return _FERNET.decrypt(raw).decode("utf-8")

    except InvalidToken as exc:
        # Valid base64 shape, but decryption failed: wrong key, or the
        # data was tampered with/corrupted. This is a real error and
        # must be surfaced, never swallowed and returned as if it were
        # the plaintext.
        raise DecryptionError(
            "Failed to decrypt a value: the data is either encrypted "
            "with a different ENCRYPTION_KEY than the one currently "
            "configured, or has been corrupted."
        ) from exc
