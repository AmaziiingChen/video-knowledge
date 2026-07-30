from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import httpx

from config import settings
from services.cookie_files import write_cookie_pairs_to_netscape


SAVED_COOKIE_FILENAME = "bilibili_cookies.txt"
_STATUS_CACHE_SECONDS = 300
_status_cache: dict | None = None
_status_cache_expires_at = 0.0


def save_bilibili_cookie(cookie_string: str) -> Path:
    global _status_cache, _status_cache_expires_at
    result = write_cookie_pairs_to_netscape(
        cookie_string,
        settings.data_dir / SAVED_COOKIE_FILENAME,
        ".bilibili.com",
    )
    _status_cache = None
    _status_cache_expires_at = 0.0
    return result


def clear_saved_bilibili_cookie() -> None:
    """Remove only the app-managed login state, never an environment override."""
    global _status_cache, _status_cache_expires_at
    try:
        (settings.data_dir / SAVED_COOKIE_FILENAME).unlink()
    except FileNotFoundError:
        pass
    _status_cache = None
    _status_cache_expires_at = 0.0


def get_bilibili_cookie_status(*, force: bool = False) -> dict:
    global _status_cache, _status_cache_expires_at
    if not force and _status_cache and time.time() < _status_cache_expires_at:
        return dict(_status_cache)
    cookie_file, source = _configured_cookie_file()
    if cookie_file:
        status = {
            "configured": True,
            "label": "B站登录态待验证",
            "detail": "将用于字幕提取、下载可用清晰度和创作者采集",
            "source": source,
        }
    elif settings.bilibili_cookie.strip():
        status = {
            "configured": True,
            "label": "B站登录态待验证",
            "detail": "将使用 backend/.env 中的 BILIBILI_COOKIE",
            "source": "environment",
        }
    else:
        return {
            "configured": False,
            "state": "missing",
            "label": "B站登录态未配置",
            "detail": "部分 B站字幕仅在登录后提供；配置 Cookie 后会优先提取字幕",
            "source": "",
        }
    if force:
        status.update(_probe_bilibili_login())
    else:
        status["state"] = "unknown"
    _status_cache = dict(status)
    _status_cache_expires_at = time.time() + _STATUS_CACHE_SECONDS
    return status


def _probe_bilibili_login() -> dict:
    cookies = bilibili_playwright_cookies()
    if not cookies:
        return {"state": "missing", "label": "B站登录态未配置", "detail": "未读取到有效 Cookie"}
    cookie_jar = {str(item["name"]): str(item["value"]) for item in cookies if item.get("name") and item.get("value")}
    try:
        response = httpx.get(
            "https://api.bilibili.com/x/web-interface/nav",
            cookies=cookie_jar,
            headers={"User-Agent": "KnowledgeHub/1.0"},
            timeout=8.0,
            follow_redirects=True,
        )
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        logged_in = bool((payload.get("data") or {}).get("isLogin")) if isinstance(payload, dict) else False
        if response.status_code == 200 and logged_in:
            return {"state": "valid", "label": "B站登录态可用", "detail": "登录探针通过，可用于创作者采集"}
        return {"state": "invalid", "label": "B站登录态需更新", "detail": "B站未确认当前登录会话，请更新 Cookie"}
    except (httpx.HTTPError, ValueError):
        return {"state": "unknown", "label": "B站登录态待确认", "detail": "登录探针暂时不可达，采集时会再次验证"}


@contextmanager
def bilibili_yt_dlp_cookie_args() -> Iterator[list[str]]:
    """Yield yt-dlp cookie arguments without exposing raw Cookie headers."""
    cookie_file, _ = _configured_cookie_file()
    if cookie_file:
        yield ["--cookies", str(cookie_file)]
        return

    raw_cookie = settings.bilibili_cookie.strip()
    if not raw_cookie:
        yield []
        return

    with TemporaryDirectory(prefix="knowledgehub-bilibili-cookie-") as directory:
        cookie_path = write_cookie_pairs_to_netscape(
            raw_cookie,
            Path(directory) / SAVED_COOKIE_FILENAME,
            ".bilibili.com",
        )
        yield ["--cookies", str(cookie_path)]


def bilibili_playwright_cookies() -> list[dict[str, str | bool]]:
    """Return the configured Bilibili login state in Playwright's cookie shape."""
    cookie_file, _ = _configured_cookie_file()
    if cookie_file:
        return _read_netscape_cookies(cookie_file)

    raw_cookie = settings.bilibili_cookie.strip()
    if not raw_cookie:
        return []
    cookies: list[dict[str, str | bool]] = []
    for pair in (part.strip() for part in raw_cookie.split(";") if part.strip()):
        if "=" not in pair:
            continue
        name, value = (part.strip() for part in pair.split("=", 1))
        if name and value and not any(char in f"{name}{value}" for char in "\t\r\n"):
            cookies.append(
                {"name": name, "value": value, "domain": ".bilibili.com", "path": "/", "secure": True}
            )
    return cookies


def _read_netscape_cookies(cookie_file: Path) -> list[dict[str, str | bool]]:
    cookies: list[dict[str, str | bool]] = []
    try:
        lines = cookie_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return cookies
    for line in lines:
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.removeprefix("#HttpOnly_").split("\t")
        if len(parts) < 7:
            continue
        domain, _subdomains, path, secure, _expires, name, value = parts[:7]
        if domain and name and value:
            cookies.append(
                {"name": name, "value": value, "domain": domain, "path": path or "/", "secure": secure.upper() == "TRUE"}
            )
    return cookies


def _configured_cookie_file() -> tuple[Path | None, str]:
    saved_cookie = settings.data_dir / SAVED_COOKIE_FILENAME
    if _is_nonempty_file(saved_cookie):
        return saved_cookie, "saved"

    configured_path = settings.bilibili_cookie_file.strip()
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if _is_nonempty_file(candidate):
            return candidate, "file"
    return None, ""


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False
