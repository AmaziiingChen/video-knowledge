"""Reliable, resumable HTTP media downloads shared by platform adapters.

The service deliberately knows nothing about Bilibili/Douyin signatures.  A
platform adapter supplies a resolved media URL and headers; this module owns
the filesystem and HTTP transfer behaviour so every adapter follows the same
rules for progress, partial files and validation by its caller.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import time

import httpx


ProgressCallback = Callable[[int, int | None], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class HttpMediaDownloadResult:
    success: bool
    path: Path
    downloaded_bytes: int
    total_bytes: int | None
    resumed_from_bytes: int = 0
    status_code: int | None = None
    error: str = ""
    elapsed_seconds: float = 0.0

    @property
    def average_bytes_per_second(self) -> float:
        return self.downloaded_bytes / self.elapsed_seconds if self.elapsed_seconds else 0.0


def download_http_media(
    url: str,
    destination: Path,
    *,
    headers: dict[str, str] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    timeout: float = 15.0,
    client: httpx.Client | None = None,
) -> HttpMediaDownloadResult:
    """Download ``url`` to ``destination`` with safe HTTP Range resumption.

    Incomplete data remains at ``destination``.  A later call asks the server
    to continue from that byte.  If the server ignores Range and answers 200,
    the partial file is replaced rather than producing a corrupt append.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing_bytes = destination.stat().st_size if destination.exists() else 0
    request_headers = dict(headers or {})
    if existing_bytes:
        request_headers["Range"] = f"bytes={existing_bytes}-"

    own_client = client is None
    # Downloads must remain direct even when the desktop was started from a
    # shell with HTTP(S)_PROXY configured.  Proxy-enabled product features use
    # their own explicit client configuration instead.
    active_client = client or httpx.Client(follow_redirects=True, trust_env=False)
    started = time.monotonic()
    written = existing_bytes
    total: int | None = None
    status_code: int | None = None

    try:
        with active_client.stream("GET", url, headers=request_headers, timeout=timeout) as response:
            status_code = response.status_code
            if response.status_code not in (200, 206):
                return _result(False, destination, written, None, existing_bytes, status_code, response.reason_phrase, started)

            append = response.status_code == 206 and existing_bytes > 0
            if not append:
                written = 0
                existing_bytes = 0

            total = _total_length(response, written if append else 0)
            mode = "ab" if append else "wb"
            with destination.open(mode) as file:
                for chunk in response.iter_bytes(1024 * 512):
                    if cancel_check and cancel_check():
                        return _result(False, destination, written, total, existing_bytes, status_code, "下载已取消", started)
                    if not chunk:
                        continue
                    file.write(chunk)
                    written += len(chunk)
                    if progress_callback:
                        progress_callback(written, total)

        if total is not None and written < total:
            return _result(False, destination, written, total, existing_bytes, status_code, "响应在媒体传输完成前结束", started)
        return _result(True, destination, written, total, existing_bytes, status_code, "", started)
    except (httpx.HTTPError, OSError) as exc:
        return _result(False, destination, written, total, existing_bytes, status_code, str(exc), started)
    finally:
        if own_client:
            active_client.close()


def download_browser_context_media(
    request_context: object,
    url: str,
    destination: Path,
    *,
    headers: dict[str, str] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    timeout: float = 15.0,
    chunk_size: int = 2 * 1024 * 1024,
) -> HttpMediaDownloadResult:
    """Download media through the active Playwright browser context.

    Douyin's browser provider obtains short-lived signed CDN URLs from the
    work page.  Sending that URL to an unrelated Python client loses the
    browser context that produced it.  This helper keeps the transfer inside
    Playwright's request context, which shares the page's cookie store, while
    writing bounded Range chunks to disk so a whole video is never retained in
    memory. Each request is intentionally short-lived so a queued cancellation
    is observed between chunks instead of waiting for a two-minute browser
    request timeout.

    ``request_context`` is deliberately duck-typed to avoid making
    Playwright a mandatory import for the shared download module.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing_bytes = destination.stat().st_size if destination.exists() else 0
    written = existing_bytes
    resumed_from = existing_bytes
    total: int | None = None
    status_code: int | None = None
    started = time.monotonic()

    try:
        while True:
            if cancel_check and cancel_check():
                return _result(False, destination, written, total, resumed_from, status_code, "下载已取消", started)

            request_headers = dict(headers or {})
            request_headers["Range"] = f"bytes={written}-{written + chunk_size - 1}"
            response = request_context.get(
                url,
                headers=request_headers,
                timeout=int(timeout * 1000),
                fail_on_status_code=False,
            )
            status_code = int(getattr(response, "status", 0) or 0) or None
            response_headers = dict(getattr(response, "headers", {}) or {})
            if status_code not in (200, 206):
                return _result(
                    False,
                    destination,
                    written,
                    total,
                    resumed_from,
                    status_code,
                    str(getattr(response, "status_text", "媒体请求失败") or "媒体请求失败"),
                    started,
                )

            payload = response.body()
            if not payload:
                return _result(False, destination, written, total, resumed_from, status_code, "媒体响应为空", started)

            if status_code == 206:
                total = _total_length_from_headers(response_headers, written)
                mode = "ab"
            else:
                # A provider that ignores Range only gives us a safe response
                # when there is no partial file.  Do not append a full file to
                # an existing partial download.
                if written:
                    return _result(False, destination, written, total, resumed_from, status_code, "媒体服务器未接受断点续传", started)
                total = _total_length_from_headers(response_headers, 0)
                mode = "wb"

            with destination.open(mode) as file:
                file.write(payload)
            written += len(payload)
            if progress_callback:
                progress_callback(written, total)

            if status_code == 200 or total is None or written >= total:
                if total is not None and written < total:
                    return _result(False, destination, written, total, resumed_from, status_code, "响应在媒体传输完成前结束", started)
                return _result(True, destination, written, total, resumed_from, status_code, "", started)
    except Exception as exc:
        return _result(False, destination, written, total, resumed_from, status_code, str(exc), started)


def _total_length(response: httpx.Response, offset: int) -> int | None:
    return _total_length_from_headers(response.headers, offset)


def _total_length_from_headers(headers: dict[str, str] | httpx.Headers, offset: int) -> int | None:
    content_range = headers.get("content-range", "")
    match = re.fullmatch(r"bytes\s+\d+-\d+/(\d+|\*)", content_range, re.IGNORECASE)
    if match and match.group(1) != "*":
        return int(match.group(1))
    length = headers.get("content-length")
    return offset + int(length) if length and length.isdigit() else None


def _result(
    success: bool,
    path: Path,
    downloaded: int,
    total: int | None,
    resumed: int,
    status: int | None,
    error: str,
    started: float,
) -> HttpMediaDownloadResult:
    return HttpMediaDownloadResult(
        success=success,
        path=path,
        downloaded_bytes=downloaded,
        total_bytes=total,
        resumed_from_bytes=resumed,
        status_code=status,
        error=error,
        elapsed_seconds=time.monotonic() - started,
    )
