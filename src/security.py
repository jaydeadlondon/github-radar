from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


class UnsafeURL(ValueError):
    """Raised when a configured outbound URL is not safe to use."""


def validate_webhook_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("webhook URL must use http or https and include a host")
    if parsed.username or parsed.password:
        raise UnsafeURL("webhook URL must not contain embedded credentials")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain", "metadata.google.internal"}:
        raise UnsafeURL("webhook URL host is not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
    ):
        raise UnsafeURL("webhook URL must not target a private or local address")
    return value.strip()
