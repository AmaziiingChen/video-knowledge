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
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse


@dataclass(frozen=True)
class _PublicHttpTarget:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


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
    return _resolve_public_http_url(
        value,
        invalid_message=invalid_message,
        blocked_message=blocked_message,
    ).url


def _resolve_public_http_url(
    value: str,
    *,
    invalid_message: str,
    blocked_message: str,
) -> _PublicHttpTarget:
    """Resolve and freeze a public destination for one HTTP request hop."""
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

    addresses: list[str] = []
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
        normalized_address = str(address)
        if normalized_address not in addresses:
            addresses.append(normalized_address)
    return _PublicHttpTarget(url=url, host=host, port=port, addresses=tuple(addresses))


def get_public_http_response(
    url: str,
    *,
    invalid_message: str,
    blocked_message: str,
    redirect_invalid_message: str,
    redirect_limit_message: str,
    max_redirects: int,
    **request_kwargs: Any,
) -> tuple[Any, str]:
    """Request an untrusted URL with validation and connection pinning per hop.

    The URL host stays intact for HTTP Host, TLS SNI and certificate validation,
    while libcurl is given only the public IPs observed during this validation.
    It therefore cannot perform a later, attacker-controlled DNS lookup.
    """
    current_url = str(url or "").strip()
    for redirects_followed in range(max_redirects + 1):
        target = _resolve_public_http_url(
            current_url,
            invalid_message=invalid_message,
            blocked_message=blocked_message,
        )
        session = _new_pinned_curl_session(target, blocked_message=blocked_message)
        try:
            response = session.get(
                target.url,
                allow_redirects=False,
                # Explicitly clear libcurl proxy use even when the parent
                # process inherited proxy environment variables.
                proxies={"all": ""},
                **request_kwargs,
            )
        except Exception:
            _close_session(session)
            raise
        if not _is_redirect(response):
            return _SessionBoundResponse(response, session), target.url

        location = str(getattr(response, "headers", {}).get("location") or "").strip()
        if not location:
            _close_response(response)
            _close_session(session)
            raise ValueError(redirect_invalid_message)
        _close_response(response)
        _close_session(session)
        if redirects_followed >= max_redirects:
            raise ValueError(redirect_limit_message)
        current_url = urljoin(target.url, location)

    # Kept for static exhaustiveness; the loop always returns or raises.
    raise ValueError(redirect_limit_message)


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _close_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()


def _is_redirect(response: Any) -> bool:
    if hasattr(response, "is_redirect"):
        return bool(response.is_redirect)
    return int(getattr(response, "status_code", 0) or 0) in {301, 302, 303, 307, 308}


def _new_pinned_curl_session(target: _PublicHttpTarget, *, blocked_message: str) -> Any:
    """Open a direct libcurl session pinned to the addresses just validated."""
    try:
        from curl_cffi import CurlOpt
        from curl_cffi.requests import Session as CurlSession
    except ImportError as exc:
        # A normal `requests` fallback would reopen the DNS-rebinding hole.
        raise ValueError(blocked_message) from exc
    return CurlSession(
        trust_env=False,
        curl_options={CurlOpt.RESOLVE: [_curl_resolve_rule(target)]},
    )


def _curl_resolve_rule(target: _PublicHttpTarget) -> str:
    host = f"[{target.host}]" if ":" in target.host else target.host
    addresses = ",".join(
        f"[{address}]" if ":" in address else address
        for address in target.addresses
    )
    return f"{host}:{target.port}:{addresses}"


class _SessionBoundResponse:
    """Close the curl session together with the response returned to callers."""

    def __init__(self, response: Any, session: Any):
        self._response = response
        self._session = session

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def close(self) -> None:
        try:
            _close_response(self._response)
        finally:
            _close_session(self._session)
