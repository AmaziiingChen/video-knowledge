from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from services.bilibili_auth import bilibili_playwright_cookies
from services.bilibili_url import requested_page_number
from services.network_policy import direct_browser_launch_options
from services.runtime_components import browser_executable
from services.text_normalizer import normalize_transcript_text


SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".json", ".ass"}
_BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
)
_PREFERRED_BILIBILI_LANGUAGES = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW")
_TITLE_TERM_STOPWORDS = {"这个", "那个", "我们", "你们", "他们", "什么", "怎么", "为什么", "一个", "视频", "分享", "今天", "真的"}


@dataclass
class SubtitleFetchResult:
    success: bool
    transcript: str = ""
    subtitle_path: Path | None = None
    source: str = ""
    source_label: str = ""
    language: str = ""
    segments: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    error: str = ""


def fetch_bilibili_subtitle(
    url: str,
    output_dir: Path,
    cancel_check: Callable[[], bool] | None = None,
) -> SubtitleFetchResult:
    """Read a subtitle only when Bilibili's current player binds it.

    The standalone player endpoint can intermittently return a caption for a
    different video.  It is therefore never used as a fallback: failure to
    verify the page/player binding must lead to speech recognition instead of
    accepting a potentially crossed subtitle.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    return _fetch_bilibili_player_subtitle(url, output_dir, cancel_check=cancel_check)


def _fetch_bilibili_player_subtitle(
    url: str,
    output_dir: Path,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> SubtitleFetchResult:
    """Capture a subtitle from the actual Bilibili player for this page."""
    bvid = _extract_bvid(url)
    if not bvid or not _is_bilibili_video_page_url(url):
        return SubtitleFetchResult(success=False, error="未识别到 B站 BV 号")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return SubtitleFetchResult(success=False, error="内置浏览器不可用，无法验证 B站字幕归属")

    executable = browser_executable()
    if not executable:
        return SubtitleFetchResult(success=False, error="未找到内置 Chromium，无法验证 B站字幕归属")

    player_responses: list[tuple[str, dict[str, Any]]] = []
    try:
        if cancel_check and cancel_check():
            return SubtitleFetchResult(success=False, error="字幕检查已取消")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable,
                **direct_browser_launch_options("--disable-blink-features=AutomationControlled"),
            )
            try:
                context = browser.new_context(user_agent=_BILIBILI_USER_AGENT, locale="zh-CN")
                cookies = bilibili_playwright_cookies()
                if cookies:
                    context.add_cookies(cookies)
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                def capture_player_response(response) -> None:
                    if not _is_bilibili_player_response(response.url):
                        return
                    try:
                        payload = response.json()
                    except Exception:
                        return
                    if isinstance(payload, dict):
                        player_responses.append((response.url, payload))

                page.on("response", capture_player_response)
                page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                if cancel_check and cancel_check():
                    return SubtitleFetchResult(success=False, error="字幕检查已取消")
                page_metadata = _read_bilibili_browser_page_metadata(page, url)
                if page_metadata is None or page_metadata["bvid"].lower() != bvid.lower():
                    return SubtitleFetchResult(success=False, error="B站页面视频身份校验失败，未采用字幕")
                for _ in range(20):
                    if cancel_check and cancel_check():
                        return SubtitleFetchResult(success=False, error="字幕检查已取消")
                    if _browser_bound_bilibili_tracks(player_responses, page_metadata):
                        break
                    page.wait_for_timeout(250)
                tracks = _browser_bound_bilibili_tracks(player_responses, page_metadata)
                if not tracks:
                    return SubtitleFetchResult(success=False, error="当前 B站播放器未加载可验证的外挂字幕")
                candidate = _fetch_best_browser_bilibili_subtitle_candidate(
                    tracks, request_context=context.request, referer=page.url
                )
            finally:
                browser.close()
    except Exception as exc:
        return SubtitleFetchResult(success=False, error=f"B站浏览器字幕校验失败：{exc}")

    if candidate is None:
        return SubtitleFetchResult(success=False, error="播放器字幕文件读取失败，未采用未验证的备用字幕")
    track, subtitle_payload, transcript, segment_count, last_end_seconds = candidate
    title_terms = _bilibili_title_terms(page_metadata["title"])
    if title_terms and _subtitle_title_relevance(transcript, title_terms) <= 0:
        return SubtitleFetchResult(success=False, error="播放器字幕与当前页面标题不匹配，已拒绝采用")

    language = str(track.get("lan") or "")
    language_label = str(track.get("lan_doc") or language or "未知语言")
    subtitle_path = output_dir / f"bilibili-player.{_safe_filename_part(language or 'subtitle')}.json"
    subtitle_path.write_text(json.dumps(subtitle_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_bilibili_srt(subtitle_payload, subtitle_path.with_suffix(".srt"))
    return SubtitleFetchResult(
        success=True,
        transcript=transcript,
        subtitle_path=subtitle_path,
        source="bilibili_browser_player_subtitle",
        source_label="B站网页播放器外挂字幕（已校验视频绑定）",
        language=language_label,
        segments=_bilibili_subtitle_segments(subtitle_payload),
        logs=[f"已从当前 B站网页播放器读取外挂字幕：{language_label}，{segment_count} 段，覆盖至 {last_end_seconds:.1f} 秒"],
    )


def _extract_bvid(url: str) -> str:
    match = re.search(r"/video/(BV[0-9A-Za-z]+)", url, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _is_bilibili_video_page_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"www.bilibili.com", "bilibili.com"}
        and parsed.path.lower().startswith("/video/bv")
    )


def _positive_int(value: Any, *, allow_zero: bool = False) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 or (allow_zero and parsed == 0) else None


def _read_bilibili_browser_page_metadata(page: Any, url: str) -> dict[str, Any] | None:
    """Return the video identity rendered by the opened Bilibili page."""
    try:
        payload = page.evaluate(
            """() => {
                const state = window.__INITIAL_STATE__ || {};
                const video = state.videoData || state.videoInfo || {};
                return {
                    bvid: video.bvid || state.bvid || '',
                    aid: video.aid || state.aid || 0,
                    title: video.title || document.title || '',
                    pages: Array.isArray(video.pages) ? video.pages : [],
                    cid: video.cid || state.cid || 0,
                };
            }"""
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    aid = _positive_int(payload.get("aid"))
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    page_number = requested_page_number(url)
    page_data = pages[page_number - 1] if page_number <= len(pages) else None
    cid = _positive_int(page_data.get("cid")) if isinstance(page_data, dict) else _positive_int(payload.get("cid"))
    bvid = str(payload.get("bvid") or "").strip()
    if not (bvid and aid and cid):
        return None
    return {"bvid": bvid, "aid": aid, "cid": cid, "title": str(payload.get("title") or "")}


def _is_bilibili_player_response(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "api.bilibili.com" and parsed.path in {
        "/x/player/v2",
        "/x/player/wbi/v2",
    }


def _browser_bound_bilibili_tracks(
    responses: list[tuple[str, dict[str, Any]]], page_metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep only tracks returned by the player request for this exact aid/cid."""
    tracks: list[dict[str, Any]] = []
    expected_aid = str(page_metadata["aid"])
    expected_cid = str(page_metadata["cid"])
    for response_url, payload in responses:
        query = parse_qs(urlparse(response_url).query)
        if query.get("aid", [""])[0] != expected_aid or query.get("cid", [""])[0] != expected_cid:
            continue
        data = payload.get("data") if isinstance(payload, dict) else None
        subtitle = data.get("subtitle") if isinstance(data, dict) else None
        offered = subtitle.get("subtitles") if isinstance(subtitle, dict) else None
        if isinstance(offered, list):
            tracks.extend(item for item in offered if isinstance(item, dict))
    return tracks


def _fetch_best_browser_bilibili_subtitle_candidate(
    tracks: list[dict[str, Any]], *, request_context: Any, referer: str
) -> tuple[dict[str, Any], dict[str, Any], str, int, float] | None:
    """Read browser-player tracks through the same authenticated context."""
    candidates: list[tuple[dict[str, Any], dict[str, Any], str, int, float]] = []
    for track in tracks:
        subtitle_url = _normalise_bilibili_subtitle_url(track.get("subtitle_url"))
        if not subtitle_url:
            continue
        try:
            response = request_context.get(subtitle_url, headers={"Referer": referer})
            subtitle_payload = response.json() if response.ok else None
        except Exception:
            continue
        if not isinstance(subtitle_payload, dict):
            continue
        transcript = parse_subtitle_text(json.dumps(subtitle_payload, ensure_ascii=False), ".json")
        body = subtitle_payload.get("body") if isinstance(subtitle_payload.get("body"), list) else []
        segment_count = len(body)
        last_end_seconds = max(
            (_as_float(item.get("to")) for item in body if isinstance(item, dict)),
            default=0.0,
        )
        if transcript:
            candidates.append((track, subtitle_payload, transcript, segment_count, last_end_seconds))
    if not candidates:
        return None

    chinese_candidates = [candidate for candidate in candidates if _bilibili_subtitle_language_rank(candidate[0]) <= 6]
    pool = chinese_candidates or candidates
    return max(
        pool,
        key=lambda candidate: (
            len(candidate[2]),
            candidate[3],
            candidate[4],
            -_bilibili_subtitle_language_rank(candidate[0]),
        ),
    )


def _bilibili_subtitle_language_rank(track: dict[str, Any]) -> int:
    language = str(track.get("lan") or "")
    normalized_language = language.lower().replace("_", "-")
    if language in _PREFERRED_BILIBILI_LANGUAGES:
        return _PREFERRED_BILIBILI_LANGUAGES.index(language)
    if normalized_language.startswith("zh"):
        return len(_PREFERRED_BILIBILI_LANGUAGES)
    if normalized_language.startswith("ai-zh"):
        return len(_PREFERRED_BILIBILI_LANGUAGES) + 1
    return len(_PREFERRED_BILIBILI_LANGUAGES) + 2


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bilibili_title_terms(title: str) -> set[str]:
    """Build specific, local title terms for rejecting obviously crossed subtitles."""
    title = str(title or "").upper()
    terms = {token for token in re.findall(r"[A-Z0-9]{2,}", title) if token not in _TITLE_TERM_STOPWORDS}
    for sequence in re.findall(r"[\u4e00-\u9fff]+", title):
        for size in range(2, min(4, len(sequence)) + 1):
            for start in range(len(sequence) - size + 1):
                term = sequence[start:start + size]
                if term not in _TITLE_TERM_STOPWORDS:
                    terms.add(term)
    return terms


def _subtitle_title_relevance(transcript: str, title_terms: set[str]) -> int:
    normalized = str(transcript or "").upper()
    return sum(len(term) ** 2 for term in title_terms if term in normalized)


def _normalise_bilibili_subtitle_url(value: Any) -> str:
    raw_url = str(value or "").strip()
    if raw_url.startswith("//"):
        raw_url = f"https:{raw_url}"
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or not (host == "bilibili.com" or host.endswith(".bilibili.com") or host.endswith(".hdslb.com")):
        return ""
    return raw_url


def _safe_filename_part(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-") or "subtitle"


def _write_bilibili_srt(payload: dict[str, Any], output_path: Path) -> None:
    body = payload.get("body") if isinstance(payload.get("body"), list) else []
    entries: list[str] = []
    for index, item in enumerate(body, start=1):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("text") or "").strip()
        try:
            start = float(item.get("from"))
            end = float(item.get("to"))
        except (TypeError, ValueError):
            continue
        if not content or end < start:
            continue
        entries.extend([str(index), f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}", content, ""])
    if entries:
        output_path.write_text("\n".join(entries).rstrip() + "\n", encoding="utf-8")


def _bilibili_subtitle_segments(payload: dict[str, Any]) -> list[dict]:
    body = payload.get("body") if isinstance(payload.get("body"), list) else []
    segments: list[dict] = []
    for position, item in enumerate(body):
        if not isinstance(item, dict):
            continue
        text = normalize_transcript_text(str(item.get("content") or item.get("text") or ""))
        try:
            start = float(item.get("from"))
            end = float(item.get("to"))
        except (TypeError, ValueError):
            continue
        if not text or start < 0 or end < start:
            continue
        segments.append({
            "start_seconds": start,
            "end_seconds": end,
            "text": text,
            "position": position,
        })
    return segments


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def parse_subtitle_text(content: str, suffix: str = "") -> str:
    suffix = suffix.lower()
    if suffix == ".json":
        return normalize_transcript_text(_parse_json_subtitle(content))
    if suffix == ".ass":
        return normalize_transcript_text(_parse_ass_subtitle(content))
    return normalize_transcript_text(_parse_vtt_or_srt(content))


def _parse_vtt_or_srt(content: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.upper() == "WEBVTT":
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = line.replace("&nbsp;", " ").strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines).strip()


def _parse_json_subtitle(content: str) -> str:
    try:
        data = json.loads(content)
    except Exception:
        return ""
    texts: list[str] = []
    body = data.get("body") if isinstance(data, dict) else None
    if isinstance(body, list):
        for item in body:
            if not isinstance(item, dict):
                continue
            text = str(item.get("content") or item.get("text") or "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _parse_ass_subtitle(content: str) -> str:
    texts: list[str] = []
    for line in content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = re.sub(r"\{[^}]+\}", "", parts[-1]).replace("\\N", " ").strip()
        if text:
            texts.append(text)
    return "\n".join(texts).strip()
