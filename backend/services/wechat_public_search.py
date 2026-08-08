from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import html
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from services.network_policy import direct_requests_session
from services.wechat_urls import is_wechat_article_url, normalize_wechat_url


SEARCH_BLOCK_SECONDS = 30 * 60
SEARCH_TIMEOUT_SECONDS = 20
MAX_RESULTS_PER_PROVIDER = 30


class PublicSearchError(RuntimeError):
    pass


class PublicSearchBlocked(PublicSearchError):
    pass


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    provider: str
    query: str
    rank: int


_provider_lock = Lock()
_blocked_until: dict[str, datetime] = {}


def search_public_wechat_articles(
    query: str,
    *,
    providers: tuple[str, ...] = ("sogou", "bing", "duckduckgo"),
) -> tuple[list[SearchResult], dict[str, dict[str, Any]]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return [], {}
    results: list[SearchResult] = []
    states: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for provider in providers:
        try:
            provider_results = _search_provider(provider, normalized_query)
            for result in provider_results:
                if result.url in seen:
                    continue
                seen.add(result.url)
                results.append(result)
            states[provider] = {
                "status": "ok",
                "result_count": len(provider_results),
            }
        except PublicSearchBlocked as exc:
            states[provider] = {"status": "blocked", "message": str(exc)}
        except Exception as exc:
            states[provider] = {
                "status": "failed",
                "message": str(exc)[:300] or "公开搜索暂时不可用",
            }
    return results, states


def _search_provider(provider: str, query: str) -> list[SearchResult]:
    _raise_if_blocked(provider)
    session = direct_requests_session()
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
        ),
    }
    public_web_query = f'"{query}" site:mp.weixin.qq.com/s'
    if provider == "sogou":
        return _search_sogou(session, headers, query)
    if provider == "bing":
        response = session.get(
            "https://www.bing.com/search",
            params={"q": public_web_query, "count": MAX_RESULTS_PER_PROVIDER, "setlang": "zh-Hans"},
            headers=headers,
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
    elif provider == "duckduckgo":
        response = session.post(
            "https://html.duckduckgo.com/html/",
            data={"q": public_web_query, "kl": "cn-zh"},
            headers=headers,
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
    else:
        raise PublicSearchError(f"不支持的公开搜索渠道：{provider}")
    if response.status_code in {403, 429} or _looks_blocked(str(response.text or "")):
        _block_provider(provider)
        raise PublicSearchBlocked("渠道要求验证码或触发频控，30 分钟后可再次尝试")
    try:
        response.raise_for_status()
    except Exception as exc:
        raise PublicSearchError(f"渠道返回 HTTP {response.status_code}") from exc
    return _parse_results(provider, public_web_query, str(response.text or ""))


def _search_sogou(session: Any, headers: dict[str, str], query: str) -> list[SearchResult]:
    search_url = "https://weixin.sogou.com/weixin"
    response = session.get(
        search_url,
        params={"type": "2", "query": query},
        headers={**headers, "Referer": "https://weixin.sogou.com/"},
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    if response.status_code in {403, 429} or _looks_blocked(str(response.text or "")):
        _block_provider("sogou")
        raise PublicSearchBlocked("渠道要求验证码或触发频控，30 分钟后可再次尝试")
    try:
        response.raise_for_status()
    except Exception as exc:
        raise PublicSearchError(f"渠道返回 HTTP {response.status_code}") from exc
    soup = BeautifulSoup(str(response.text or ""), "lxml")
    nodes = soup.select(".txt-box h3 a[href], h3 a[href]")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in nodes[:10]:
        redirect_url = urljoin(str(response.url or search_url), str(node.get("href") or ""))
        redirect_target = urlparse(redirect_url)
        if (
            redirect_target.scheme != "https"
            or (redirect_target.hostname or "").lower() != "weixin.sogou.com"
        ):
            continue
        try:
            redirect = session.get(
                redirect_url,
                headers={**headers, "Referer": str(response.url or search_url)},
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
            if redirect.status_code in {403, 429} or _looks_blocked(str(redirect.text or "")):
                _block_provider("sogou")
                raise PublicSearchBlocked("渠道要求验证码或触发频控，30 分钟后可再次尝试")
            redirect.raise_for_status()
            target = _sogou_script_target(str(redirect.text or ""))
            normalized = normalize_wechat_url(target)
            if not is_wechat_article_url(normalized) or normalized in seen:
                continue
            seen.add(normalized)
            results.append(
                SearchResult(
                    url=normalized,
                    title=html.unescape(node.get_text(" ", strip=True)),
                    provider="sogou",
                    query=query,
                    rank=len(results) + 1,
                )
            )
            time.sleep(1)
        except PublicSearchBlocked:
            raise
        except Exception:
            continue
    return results


def _parse_results(provider: str, query: str, page: str) -> list[SearchResult]:
    soup = BeautifulSoup(page, "lxml")
    if provider == "bing":
        nodes = soup.select("li.b_algo h2 a[href], .b_algo h2 a[href]")
    else:
        nodes = soup.select("a.result__a[href], .result__title a[href]")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in nodes:
        target = _unwrap_result_url(str(node.get("href") or ""))
        normalized = normalize_wechat_url(target)
        if not is_wechat_article_url(normalized) or normalized in seen:
            continue
        seen.add(normalized)
        results.append(
            SearchResult(
                url=normalized,
                title=html.unescape(node.get_text(" ", strip=True)),
                provider=provider,
                query=query,
                rank=len(results) + 1,
            )
        )
        if len(results) >= MAX_RESULTS_PER_PROVIDER:
            break
    return results


def _unwrap_result_url(value: str) -> str:
    target = re.sub(r"&amp;", "&", str(value or "").strip(), flags=re.IGNORECASE)
    parsed = urlparse(target)
    if parsed.netloc.endswith("duckduckgo.com"):
        nested = parse_qs(parsed.query).get("uddg", [""])[0]
        if nested:
            return unquote(nested)
    return target


def _sogou_script_target(page: str) -> str:
    pieces = re.findall(r"""url\s*\+=\s*['"]([^'"]*)['"]""", str(page or ""))
    return re.sub(r"&amp;", "&", "".join(pieces), flags=re.IGNORECASE)


def _looks_blocked(page: str) -> bool:
    compact = "".join(str(page or "").lower().split())
    markers = (
        "captcha",
        "unusualtraffic",
        "verifyyouarehuman",
        "请输入验证码",
        "访问过于频繁",
    )
    return any(marker in compact for marker in markers)


def _raise_if_blocked(provider: str) -> None:
    now = datetime.now(timezone.utc)
    with _provider_lock:
        deadline = _blocked_until.get(provider)
        if deadline and deadline > now:
            minutes = max(1, int((deadline - now).total_seconds() // 60) + 1)
            raise PublicSearchBlocked(f"渠道正在短时冷却，约 {minutes} 分钟后可重试")
        if deadline:
            _blocked_until.pop(provider, None)


def _block_provider(provider: str) -> None:
    with _provider_lock:
        _blocked_until[provider] = datetime.now(timezone.utc) + timedelta(seconds=SEARCH_BLOCK_SECONDS)
