"""Validation and redirect handling for untrusted remote HTTP URLs.

Article pages, article images, and OCR result links are supplied by remote
publishers.  A syntactically-valid URL is not sufficient at those boundaries:
the hostname can resolve to a loopback or private address, including after a
redirect.  Keep the check next to the request loop so every hop is resolved
and verified before it is requested.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse


def ensure_public_http_url(
    value: str,
    *,
    invalid_message: str,
    blocked_message: str,
) -> str:
    """Return a normalized HTTP URL only when all DNS answers are public.

    Rejecting a hostname whenever *any* address answer is non-public is
    deliberate.  Accepting the public answer and leaving address selection to
    the HTTP client would make mixed DNS answers an SSRF bypass.
    """
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(invalid_message)

    host = parsed.hostname.rstrip(".")
    if not host or host.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError(blocked_message)
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError(invalid_message) from exc
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError, ValueError) as exc:
        raise ValueError(blocked_message) from exc
    if not answers:
        raise ValueError(blocked_message)

    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0])
        except (IndexError, ValueError) as exc:
            raise ValueError(blocked_message) from exc
        # IPv4-mapped IPv6 addresses inherit the policy of the embedded IPv4.
        mapped_ipv4 = getattr(address, "ipv4_mapped", None)
        if mapped_ipv4 is not None:
            address = mapped_ipv4
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValueError(blocked_message)
    return url


def get_public_http_response(
    session: Any,
    url: str,
    *,
    invalid_message: str,
    blocked_message: str,
    redirect_invalid_message: str,
    redirect_limit_message: str,
    max_redirects: int,
    **request_kwargs: Any,
) -> tuple[Any, str]:
    """Request an untrusted URL with validation before every redirect hop."""
    current_url = str(url or "").strip()
    for redirects_followed in range(max_redirects + 1):
        current_url = ensure_public_http_url(
            current_url,
            invalid_message=invalid_message,
            blocked_message=blocked_message,
        )
        response = session.get(current_url, allow_redirects=False, **request_kwargs)
        if not bool(getattr(response, "is_redirect", False)):
            return response, current_url

        location = str(getattr(response, "headers", {}).get("location") or "").strip()
        if not location:
            _close_response(response)
            raise ValueError(redirect_invalid_message)
        _close_response(response)
        if redirects_followed >= max_redirects:
            raise ValueError(redirect_limit_message)
        current_url = urljoin(current_url, location)

    # Kept for static exhaustiveness; the loop always returns or raises.
    raise ValueError(redirect_limit_message)


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()
