from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import unquote

from config import settings
from services.database import database_path
from services.network_policy import direct_browser_launch_options


STATUS_CACHE_SECONDS = 300
RECENT_FAILURE_WINDOW_SECONDS = 30 * 60

_cache_lock = Lock()
_probe_lock = Lock()
_status_cache: dict | None = None
_cache_expires_at = 0.0


def get_douyin_cookie_status(*, force: bool = False, probe: bool = True) -> dict:
    global _status_cache, _cache_expires_at

    now = time.time()
    with _cache_lock:
        if not force and _status_cache is not None and now < _cache_expires_at:
            return _with_recent_task_health(dict(_status_cache))

    status = _inspect_cookie_status(probe=probe)
    with _cache_lock:
        _status_cache = status
        _cache_expires_at = now + STATUS_CACHE_SECONDS
    return _with_recent_task_health(dict(status))


def invalidate_douyin_cookie_status() -> None:
    global _status_cache, _cache_expires_at
    with _cache_lock:
        _status_cache = None
        _cache_expires_at = 0.0


def _inspect_cookie_status(*, probe: bool = True) -> dict:
    cookie_file = settings.data_dir / "douyin_cookies.txt"
    has_cookie_file = cookie_file.exists() and cookie_file.stat().st_size > 0
    configured = has_cookie_file
    checked_at = _now_iso()

    base = {
        "configured": configured,
        "cookie_file": has_cookie_file,
        "checked_at": checked_at,
        "expires_at": None,
    }
    if not configured:
        return {
            **base,
            "state": "missing",
            "label": "抖音凭据未配置",
            "detail": "请在设置中粘贴已登录抖音浏览器的 Cookie",
        }

    expiry = _sid_guard_expiry(cookie_file)
    if expiry is not None:
        base["expires_at"] = datetime.fromtimestamp(expiry, timezone.utc).isoformat()
        if expiry <= time.time():
            return {
                **base,
                "state": "invalid",
                "label": "抖音凭据需更新",
                "detail": "登录会话已过期，请更新 Cookie",
            }

    if not probe:
        return {
            **base,
            "state": "unknown",
            "label": "抖音登录态待确认",
            "detail": "将在资料库首屏就绪后后台检测登录态",
        }

    state, detail = _probe_douyin_browser_session()
    labels = {
        "valid": "抖音登录态可用",
        "invalid": "抖音凭据需更新",
        "unknown": "抖音登录态暂不可确认",
    }
    return {**base, "state": state, "label": labels[state], "detail": detail}


def _with_recent_task_health(status: dict) -> dict:
    """Do not let a fixed probe hide a fresh, real download failure.

    A signed Douyin CDN URL can reject a session even when its profile page is
    still reachable. Recent task outcomes are therefore stronger evidence than
    a lightweight login-page probe. Failures from before the credentials were
    last changed are deliberately ignored so saving fresh credentials clears
    stale alarms immediately.
    """
    failure = _recent_douyin_cdn_failure()
    if not failure:
        return status

    checked_at = failure["updated_at"]
    return {
        **status,
        "state": "blocked",
        "label": "抖音下载受限",
        "detail": (
            f"最近任务 {failure['task_id']} 的媒体 CDN 连续返回 403（{checked_at}），"
            "请更新 Cookie 后重新检测"
        ),
    }


def _recent_douyin_cdn_failure() -> dict | None:
    db_path = database_path()
    if not db_path.exists():
        return None

    now = time.time()
    credentials_updated_at = _credentials_updated_at()
    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                """
                SELECT id, request_json, result_json, error_message, updated_at
                FROM tasks
                WHERE status = 'failed'
                ORDER BY updated_at DESC
                LIMIT 24
                """
            ).fetchall()
    except sqlite3.Error:
        return None

    for task_id, request_json, result_json, error_message, updated_at in rows:
        updated_timestamp = _iso_timestamp(updated_at)
        if updated_timestamp is None:
            continue
        if now - updated_timestamp > RECENT_FAILURE_WINDOW_SECONDS:
            return None
        if credentials_updated_at and updated_timestamp <= credentials_updated_at:
            continue

        request = _json_object(request_json)
        result = _json_object(result_json)
        url = str(result.get("url") or request.get("share_text") or "")
        if "douyin.com" not in url:
            continue
        if _is_cdn_403(result, error_message):
            return {"task_id": task_id, "updated_at": updated_at}
    return None


def _credentials_updated_at() -> float:
    timestamps: list[float] = []
    try:
        timestamps.append((settings.data_dir / "douyin_cookies.txt").stat().st_mtime)
    except OSError:
        pass
    return max(timestamps, default=0.0)


def _iso_timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _json_object(value: object) -> dict:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_cdn_403(result: dict, error_message: object) -> bool:
    messages = [str(error_message or ""), str(result.get("error") or "")]
    logs = result.get("logs")
    if isinstance(logs, list):
        messages.extend(
            str(item.get("message") or "") for item in logs if isinstance(item, dict)
        )
    combined = "\n".join(messages).lower()
    return "403" in combined and ("cdn" in combined or "视频下载" in combined or "媒体" in combined)


def _sid_guard_expiry(cookie_file: Path) -> float | None:
    if not cookie_file.exists():
        return None
    try:
        lines = cookie_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7 or parts[5] != "sid_guard":
            continue
        try:
            _, issued_at, ttl, *_ = unquote(parts[6]).split("|")
            return float(issued_at) + float(ttl)
        except (TypeError, ValueError):
            return None
    return None


def _probe_douyin_browser_session() -> tuple[str, str]:
    """Verify the saved session in the same browser environment as downloads.

    A signed-in ``/user/self`` page is a cheap, platform-native proof of the
    login state. Actual media 403 failures still override this optimistic
    result in ``_with_recent_task_health`` above.
    """
    try:
        from playwright.sync_api import sync_playwright
        from services.downloader import _load_cookies_for_playwright
        from services.runtime_components import browser_executable
    except ImportError:
        return "unknown", "浏览器组件不可用，无法验证抖音登录态"

    executable = browser_executable()
    cookies = _load_cookies_for_playwright()
    if not executable:
        return "unknown", "未找到浏览器组件，无法验证抖音登录态"
    if not cookies:
        return "invalid", "未读取到可用于浏览器会话的抖音 Cookie，请重新登录"

    with _probe_lock:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=executable,
                    **direct_browser_launch_options("--disable-blink-features=AutomationControlled"),
                )
                try:
                    context = browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                        ),
                        locale="zh-CN",
                    )
                    context.add_cookies(cookies)
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                    page.goto(
                        "https://www.douyin.com/user/self?from_tab_name=main",
                        wait_until="commit",
                        timeout=20_000,
                    )
                    for _ in range(16):
                        title = page.title()
                        try:
                            body = page.locator("body").inner_text(timeout=750)
                        except Exception:
                            body = ""
                        state = _douyin_page_login_state(page.url, title, body)
                        if state is not None:
                            return state
                        page.wait_for_timeout(500)
                finally:
                    browser.close()
        except Exception as exc:
            return "unknown", f"浏览器登录态探测暂不可达：{exc.__class__.__name__}"
    return "unknown", "抖音页面未在限定时间内返回明确的登录状态"


def _douyin_page_login_state(url: str, title: str, body: str) -> tuple[str, str] | None:
    normalized_url = str(url or "").lower()
    normalized_title = str(title or "").strip()
    if "/login" in normalized_url:
        return "invalid", "抖音已跳转到登录页，请重新登录"
    if "抖音号：" in body or normalized_title.endswith("的抖音 - 抖音"):
        return "valid", "已在抖音网页“我的”页面确认登录态"
    if "扫码登录" in body and "抖音号：" not in body:
        return "invalid", "抖音要求重新登录，请在设置中点击“登录并连接”"
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
