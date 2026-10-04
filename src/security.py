from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urlsplit


class UnsafeURL(ValueError):
    """Raised when a configured outbound URL is not safe to use."""


_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
}

# Values that look like credentials in logs or API payloads. Applied before any
# user-controlled string is persisted or printed (see ``redact_secret``).
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(gh[pousr]_[A-Za-z0-9]{20,})\b"), "[redacted-github-token]"),
    (re.compile(r"(?i)\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[redacted-github-token]"),
    (re.compile(r"(?i)\b(sk-[A-Za-z0-9]{16,})\b"), "[redacted-api-key]"),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)\S+"), r"\1[redacted]"),
)


def _is_blocked_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_private: bool = False,
) -> bool:
    """Decide whether an address may be used as an outbound webhook target.

    Link-local (cloud metadata), unspecified, multicast and IPv4-mapped
    addresses are always refused: they are never a legitimate webhook and are
    the classic SSRF credential-theft targets. Private and loopback addresses
    (RFC 1918, CGNAT, ULA) are refused unless the operator opts in with
    ``RADAR_WEBHOOK_ALLOW_PRIVATE_ADDRESSES``, which is what a self-hosted
    notification bridge on the local network needs.
    """

    if (
        address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or (isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None)
    ):
        return True
    if address.is_private:
        return not allow_private
    return address.is_reserved


Resolver = Callable[[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]


def _resolve(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname, returning an empty list when DNS is unavailable."""

    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:  # pragma: no cover - defensive
            continue
    return addresses


def validate_webhook_url(value: str, *, allow_private: bool = False) -> str:
    """Validate a configured webhook target without network access."""

    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("webhook URL must use http or https and include a host")
    if parsed.username or parsed.password:
        raise UnsafeURL("webhook URL must not contain embedded credentials")
    hostname = parsed.hostname.lower()
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise UnsafeURL("webhook URL host is not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and _is_blocked_address(address, allow_private=allow_private):
        raise UnsafeURL("webhook URL must not target a private or local address")
    return value.strip()


def validate_outbound_url(
    value: str,
    *,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> str:
    """Validate a URL immediately before an outbound request.

    Re-resolving the hostname at delivery time prevents DNS-rebinding: a target
    whose DNS record starts pointing at a private address is refused even when it
    was accepted at configuration time. Names that do not resolve are left to the
    HTTP client so genuine DNS failures still surface as transport errors.

    ``resolver`` is injectable so tests never depend on the host's DNS: a machine
    whose resolver answers reserved names with ``0.0.0.0`` or an internal address
    must not change the outcome of a delivery that never actually dials out.
    """

    validated = validate_webhook_url(value, allow_private=allow_private)
    hostname = urlsplit(validated).hostname or ""
    addresses = (resolver or _resolve)(hostname)
    for address in addresses:
        if _is_blocked_address(address, allow_private=allow_private):
            raise UnsafeURL(
                "webhook URL resolves to a private or local address; refusing to "
                f"connect ({address})"
            )
    return validated


def redact_secret(value: str, *, max_length: int = 500) -> str:
    """Remove credential-shaped substrings before storing or printing a value."""

    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted[:max_length]


def redact_mapping(payload: dict[str, object]) -> dict[str, object]:
    """Redact secrets in a flat configuration mapping."""

    return {
        key: redact_secret(str(value)) if isinstance(value, str) else value
        for key, value in payload.items()
    }
