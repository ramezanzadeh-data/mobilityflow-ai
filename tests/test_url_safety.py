import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.security.url_safety import UnsafeUrlError, validate_public_https_url


def test_rejects_non_https_scheme():
    with pytest.raises(UnsafeUrlError):
        validate_public_https_url("http://example.com/hook")


def test_rejects_missing_hostname():
    with pytest.raises(UnsafeUrlError):
        validate_public_https_url("https:///hook")


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.5/hook",
        "https://169.254.169.254/latest/meta-data/",
        "https://postgres:5432/",
        "https://redis:6379/",
        "https://minio:9000/",
    ],
)
def test_rejects_internal_and_private_targets(url):
    with pytest.raises(UnsafeUrlError):
        validate_public_https_url(url)


def test_accepts_a_plausible_public_https_url():
    # Resolved manually to a known globally-routable address so this
    # test doesn't depend on live DNS.
    from unittest.mock import patch

    with patch(
        "socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
    ):
        validate_public_https_url("https://example-webhook-target.test/hook")


def test_rejects_hostname_that_resolves_to_a_private_address():
    # Simulates DNS rebinding: a hostname that resolves to an internal
    # address even though the URL itself doesn't look internal.
    from unittest.mock import patch

    with patch(
        "socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("10.0.0.5", 0))],
    ):
        with pytest.raises(UnsafeUrlError):
            validate_public_https_url("https://looks-external.test/hook")
