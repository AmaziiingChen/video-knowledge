from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse


WECHAT_HOSTS = {"mp.weixin.qq.com", "mp.wechat.qq.com"}
WECHAT_URL_RE = re.compile(r"https?://(?:mp\.weixin\.qq\.com|mp\.wechat\.qq\.com)/[^\s<>'\"]+")
_WECHAT_BIZ_RE = re.compile(r"[A-Za-z0-9+/]{8,}={0,2}\Z")
_TRAILING_PUNCTUATION = "，。；、,.!?)）]】>"
_SENSITIVE_OR_TRACKING_QUERY_KEYS = {
    "ascene",
    "clicktime",
    "enterid",
    "exportkey",
    "fontscale",
    "from",
    "isappinstalled",
    "key",
    "lang",
    "nettype",
    "pass_ticket",
    "scene",
    "subscene",
    "uin",
    "version",
    "wx_header",
}


@dataclass(frozen=True)
class WeChatArticleIdentity:
    biz: str = ""
    mid: str = ""
    idx: str = ""

    @property
    def canonical_id(self) -> str | None:
        if self.biz and self.mid:
            return f"wechat:{self.biz}:{self.mid}:{self.idx or '1'}"
        return None


def extract_wechat_urls(value: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in WECHAT_URL_RE.finditer(_decode_url_entities(str(value or ""))):
        normalized = normalize_wechat_url(match.group(0))
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls


def normalize_wechat_url(value: str) -> str:
    raw = _decode_url_entities(str(value or "")).strip().rstrip(_TRAILING_PUNCTUATION)
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or host not in WECHAT_HOSTS:
        return ""
    netloc = host
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port and port not in {80, 443}:
        return ""
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=False)
            if key.lower() not in _SENSITIVE_OR_TRACKING_QUERY_KEYS
        ]
    )
    return urlunparse(("https", netloc, parsed.path or "/", "", query, ""))


def is_wechat_article_url(value: str) -> bool:
    normalized = normalize_wechat_url(value)
    if not normalized:
        return False
    path = urlparse(normalized).path.rstrip("/")
    return path == "/s" or path.startswith("/s/")


def is_wechat_album_url(value: str) -> bool:
    normalized = normalize_wechat_url(value)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    if parsed.path.rstrip("/") != "/mp/appmsgalbum":
        return False
    query = parse_qs(parsed.query)
    return bool(_first(query, "__biz") and _first(query, "album_id"))


def article_identity_from_url(value: str) -> WeChatArticleIdentity:
    normalized = normalize_wechat_url(value)
    query = parse_qs(urlparse(normalized).query) if normalized else {}
    return WeChatArticleIdentity(
        biz=_first(query, "__biz"),
        mid=_first(query, "mid") or _first(query, "appmsgid"),
        idx=_first(query, "idx") or _first(query, "itemidx"),
    )


def article_identity_from_html(value: str) -> WeChatArticleIdentity:
    source = html.unescape(str(value or ""))
    return WeChatArticleIdentity(
        biz=_first_valid_biz_match(
            source,
            (
                r'(?:window\.)?biz\s*=\s*["\']([^"\']+)["\']',
                r'["\']__biz["\']\s*:\s*["\']([^"\']+)["\']',
                r'[?&]__biz=([^&"\'\s]+)',
            ),
        ),
        mid=_first_match(
            source,
            (
                r'(?:window\.)?(?:mid|appmsgid)\s*=\s*["\']?(\d+)["\']?',
                r'["\'](?:mid|appmsgid)["\']\s*:\s*["\']?(\d+)["\']?',
                r'[?&](?:mid|appmsgid)=(\d+)',
            ),
        ),
        idx=_first_match(
            source,
            (
                r'(?:window\.)?(?:idx|itemidx)\s*=\s*["\']?(\d+)["\']?',
                r'["\'](?:idx|itemidx)["\']\s*:\s*["\']?(\d+)["\']?',
                r'[?&](?:idx|itemidx)=(\d+)',
            ),
        ),
    )


def merge_article_identity(*identities: WeChatArticleIdentity) -> WeChatArticleIdentity:
    return WeChatArticleIdentity(
        biz=next((item.biz for item in identities if item.biz), ""),
        mid=next((item.mid for item in identities if item.mid), ""),
        idx=next((item.idx for item in identities if item.idx), ""),
    )


def canonical_wechat_article_id(value: str) -> str:
    normalized = normalize_wechat_url(value)
    identity = article_identity_from_url(normalized)
    if identity.canonical_id:
        return identity.canonical_id
    parsed = urlparse(normalized)
    short_token = parsed.path.removeprefix("/s/").strip("/") if parsed.path.startswith("/s/") else ""
    if short_token:
        return f"wechat-short:{short_token}"
    return "wechat-url:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def album_identity(value: str) -> tuple[str, str]:
    normalized = normalize_wechat_url(value)
    query = parse_qs(urlparse(normalized).query) if normalized else {}
    return _first(query, "__biz"), _first(query, "album_id")


def album_endpoint(*, biz: str, album_id: str, begin_msgid: str = "", begin_itemidx: str = "") -> str:
    query = {
        "action": "getalbum",
        "__biz": biz,
        "album_id": album_id,
        "count": "10",
        "f": "json",
    }
    if begin_msgid:
        query["begin_msgid"] = begin_msgid
    if begin_itemidx:
        query["begin_itemidx"] = begin_itemidx
    return "https://mp.weixin.qq.com/mp/appmsgalbum?" + urlencode(query)


def _first(values: dict[str, list[str]], key: str) -> str:
    return str(values.get(key, [""])[0] or "").strip()


def _first_match(value: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _first_valid_biz_match(value: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        for match in re.finditer(pattern, value, re.IGNORECASE):
            candidate = unquote(html.unescape(match.group(1))).strip()
            if _is_valid_wechat_biz(candidate):
                return candidate
    return ""


def _is_valid_wechat_biz(value: str) -> bool:
    if not _WECHAT_BIZ_RE.fullmatch(value):
        return False
    try:
        decoded = base64.b64decode(value, validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    return decoded.isdigit()


def _decode_url_entities(value: str) -> str:
    # html.unescape also treats a bare ``&timestamp`` prefix as the legacy
    # ``&times`` entity. URL query strings commonly contain that key, so only
    # decode explicitly terminated entities here.
    text = re.sub(r"&amp;", "&", str(value or ""), flags=re.IGNORECASE)

    def decode_numeric(match: re.Match[str]) -> str:
        try:
            token = match.group(1)
            codepoint = int(token[1:], 16) if token.lower().startswith("x") else int(token)
            return chr(codepoint)
        except (ValueError, OverflowError):
            return match.group(0)

    return re.sub(r"&#(x[0-9a-f]+|\d+);", decode_numeric, text, flags=re.IGNORECASE)
