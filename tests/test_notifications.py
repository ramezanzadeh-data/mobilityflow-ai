
from core.communication.notifications import sign_payload, verify_webhook_signature


def test_sign_payload_produces_sha256_prefix():

    signature = sign_payload(b'{"case_id": 1}', "my-secret")

    assert signature.startswith("sha256=")


def test_same_payload_and_secret_produce_same_signature():

    payload = b'{"case_id": 1, "event_type": "CASE_CREATED"}'

    sig1 = sign_payload(payload, "secret-a")
    sig2 = sign_payload(payload, "secret-a")

    assert sig1 == sig2


def test_different_secrets_produce_different_signatures():

    payload = b'{"case_id": 1}'

    sig_a = sign_payload(payload, "secret-a")
    sig_b = sign_payload(payload, "secret-b")

    assert sig_a != sig_b


def test_verify_accepts_correct_signature():

    payload = b'{"case_id": 42}'
    secret = "correct-secret"

    signature = sign_payload(payload, secret)

    assert verify_webhook_signature(payload, signature, secret) is True


def test_verify_rejects_wrong_secret():

    payload = b'{"case_id": 42}'

    signature = sign_payload(payload, "correct-secret")

    assert verify_webhook_signature(payload, signature, "wrong-secret") is False


def test_verify_rejects_tampered_payload():

    original_payload = b'{"case_id": 42}'
    secret = "my-secret"

    signature = sign_payload(original_payload, secret)

    tampered_payload = b'{"case_id": 999}'

    assert verify_webhook_signature(tampered_payload, signature, secret) is False


def test_verify_rejects_missing_signature_header():

    payload = b'{"case_id": 42}'

    assert verify_webhook_signature(payload, None, "some-secret") is False
