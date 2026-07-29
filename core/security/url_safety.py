"""
Guards against Server-Side Request Forgery (SSRF) when this app makes
an outbound HTTP request to a URL supplied by a user - currently:
webhook registration/delivery.

Used at two points, deliberately:

  1. Webhook registration time (apps/api/schemas/webhook.py) - fail
     fast with a clear error before the URL is ever stored.
  2. Immediately before every outbound delivery
     (core/communication/notifications.py) - defense in depth, since
     DNS can change between registration and delivery ("DNS
     rebinding"): a hostname that resolved to a public IP when the
     webhook was created could later resolve to an internal one.

Without this, a user with webhooks:manage permission could register
a webhook pointing at an internal service (e.g. the database, Redis,
MinIO admin console, or - if deployed to a cloud VM - the instance
metadata endpoint) and have this app's own worker make requests to it
on their behalf.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a URL is not a safe target for an outbound request."""
    pass


# Hostnames used by this app's own docker-compose stack (and common
# local aliases). Blocked outright, independent of DNS resolution.
_BLOCKED_HOSTNAMES = {
    "localhost",
    "postgres",
    "redis",
    "minio",
    "metadata.google.internal",
}

# Cloud provider instance-metadata addresses. Never a legitimate
# webhook target.
_BLOCKED_LITERAL_IPS = {
    "169.254.169.254",
    "fd00:ec2::254",
}


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # Not a parseable IP at all - treat as unsafe rather than
        # silently letting it through.
        return True

    if str(ip) in _BLOCKED_LITERAL_IPS:
        return True

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_https_url(url: str) -> None:
    """
    Raise UnsafeUrlError if `url` is not a safe target for an
    outbound webhook request. Returns None if the URL is acceptable.
    """

    if not url or not isinstance(url, str):
        raise UnsafeUrlError("URL is required.")

    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise UnsafeUrlError("Only https:// URLs are allowed for webhooks.")

    hostname = parsed.hostname

    if not hostname:
        raise UnsafeUrlError("URL must include a hostname.")

    hostname_lower = hostname.lower()

    if hostname_lower in _BLOCKED_HOSTNAMES:
        raise UnsafeUrlError(
            f"'{hostname}' is not a permitted webhook destination."
        )

    # If the hostname itself is a literal IP address, check it directly.
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None and _is_blocked_ip(str(literal_ip)):
        raise UnsafeUrlError(
            "Webhook URL resolves to a private/internal address, "
            "which is not permitted."
        )

    # Resolve the hostname and check every returned address - this
    # guards against both an already-internal hostname and DNS
    # rebinding (the same hostname later resolving to an internal
    # address at delivery time).
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(
            f"Could not resolve webhook hostname '{hostname}'."
        ) from exc

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise UnsafeUrlError(
                f"Webhook hostname '{hostname}' resolves to a "
                "private/internal address, which is not permitted."
            )
