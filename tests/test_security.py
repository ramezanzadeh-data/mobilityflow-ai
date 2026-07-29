
import time
import datetime

import pytest
import jwt as pyjwt

from auth.jwt import (
    create_access_token,
    verify_access_token,
    TokenError,
    SECRET_KEY,
    JWT_ALGORITHM,
)
from apps.api.middleware.rate_limiter import RateLimiter
from auth.encryption import encrypt_text, decrypt_text


def test_create_and_verify_token_roundtrip():

    token = create_access_token("alice", "ADMIN", "Demo Company")
    payload = verify_access_token(token)

    assert payload["sub"] == "alice"
    assert payload["role"] == "ADMIN"
    assert payload["company"] == "Demo Company"


def test_verify_rejects_garbage_token():

    with pytest.raises(TokenError):
        verify_access_token("not.a.real.token")


def test_verify_rejects_expired_token():

    now = datetime.datetime.now(datetime.timezone.utc)

    expired_payload = {
        "sub": "alice",
        "role": "ADMIN",
        "company": "Demo Company",
        "iat": now - datetime.timedelta(hours=2),
        "exp": now - datetime.timedelta(hours=1),
    }

    expired_token = pyjwt.encode(expired_payload, SECRET_KEY, algorithm=JWT_ALGORITHM)

    with pytest.raises(TokenError):
        verify_access_token(expired_token)


def test_verify_rejects_token_signed_with_different_key():

    now = datetime.datetime.now(datetime.timezone.utc)

    payload = {
        "sub": "alice",
        "role": "ADMIN",
        "company": "Demo Company",
        "iat": now,
        "exp": now + datetime.timedelta(hours=1),
    }

    wrong_key_token = pyjwt.encode(payload, "a-completely-different-key", algorithm=JWT_ALGORITHM)

    with pytest.raises(TokenError):
        verify_access_token(wrong_key_token)


def test_rate_limiter_allows_up_to_max_requests():

    rl = RateLimiter(max_requests=3, window_seconds=10)

    results = [rl.is_allowed("user_a")[0] for _ in range(3)]

    assert all(results)


def test_rate_limiter_blocks_after_max_requests():

    rl = RateLimiter(max_requests=3, window_seconds=10)

    for _ in range(3):
        rl.is_allowed("user_a")

    allowed, retry_after = rl.is_allowed("user_a")

    assert allowed is False
    assert retry_after is not None
    assert retry_after > 0


def test_rate_limiter_keys_are_independent():

    rl = RateLimiter(max_requests=1, window_seconds=10)

    rl.is_allowed("user_a")

    allowed_a, _ = rl.is_allowed("user_a")
    allowed_b, _ = rl.is_allowed("user_b")

    assert allowed_a is False
    assert allowed_b is True


def test_rate_limiter_resets_after_window_expires():

    rl = RateLimiter(max_requests=1, window_seconds=1)

    rl.is_allowed("user_a")
    blocked, _ = rl.is_allowed("user_a")
    assert blocked is False

    time.sleep(1.1)

    allowed_after_window, _ = rl.is_allowed("user_a")
    assert allowed_after_window is True


def test_rate_limiter_reset_clears_specific_key():

    rl = RateLimiter(max_requests=1, window_seconds=100)

    rl.is_allowed("user_a")
    rl.reset("user_a")

    allowed, _ = rl.is_allowed("user_a")
    assert allowed is True


def test_encrypt_decrypt_roundtrip():

    original = "Passport No: X1234567"
    encrypted = encrypt_text(original)

    assert encrypted != original
    assert decrypt_text(encrypted) == original


def test_encrypted_value_does_not_contain_plaintext():

    original = "Passport No: X1234567"
    encrypted = encrypt_text(original)

    assert "X1234567" not in encrypted


def test_decrypt_passes_through_unencrypted_legacy_data():


    legacy_plain_text = "This is old plain data from before encryption existed"

    result = decrypt_text(legacy_plain_text)

    assert result == legacy_plain_text


def test_encrypt_decrypt_handles_none():

    assert encrypt_text(None) is None
    assert decrypt_text(None) is None
