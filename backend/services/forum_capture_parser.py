from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from difflib import SequenceMatcher
import hashlib
import re
from statistics import median
from typing import Any


TIME_LABEL_PATTERN = re.compile(
    r"^(?:刚刚|昨天|前天|今天(?:\s*\d{1,2}:\d{2})?|"
    r"\d+\s*(?:分钟|小时|天|个月)前|"
    r"\d{1,2}月\d{1,2}日(?:\s*\d{1,2}:\d{2})?)$"
)
COMMENT_MARKER_PATTERN = re.compile(
    r"全部(?:评论|評(?:論|论)?|评(?:論|论)?)\s*[·・•.]?\s*(\d+)?\s*条?"
)
EMPTY_COMMENTS_PATTERN = re.compile(r"这里空空如也")
TAG_PATTERN = re.compile(r"#[^#\s，,。；;:：]{2,20}")
INTEGER_PATTERN = re.compile(r"^\d{1,7}$")


@dataclass(frozen=True)
class FeedCandidate:
    display_time: str
    author_hint: str
    card_text: str
    signature: str
    click_x: float
    click_y: float
    top: float
    bottom: float
    anchor_y: float = 0.0
    body_text: str = ""
    tags: tuple[str, ...] = ()
    category: str = ""
    collect_count: int | None = None
    comment_count: int | None = None
    like_count: int | None = None
    truncated: bool = False
    has_comments: bool = False
    needs_detail: bool = True


def normalize_ocr_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for raw in payload.get("lines", []):
        if not isinstance(raw, dict):
            continue
        text_value = " ".join(str(raw.get("text") or "").split()).strip()
        if not text_value:
            continue
        try:
            item = {
                "text": text_value,
                "confidence": float(raw.get("confidence") or 0),
                "x": float(raw.get("x") or 0),
                "y": float(raw.get("y") or 0),
                "width": float(raw.get("width") or 0),
                "height": float(raw.get("height") or 0),
            }
        except (TypeError, ValueError):
            continue
        item["center_x"] = item["x"] + item["width"] / 2
        item["center_y"] = item["y"] + item["height"] / 2
        result.append(item)
    return sorted(result, key=lambda item: (item["center_y"], item["x"]))


def detect_feed_candidates(payload: dict[str, Any]) -> list[FeedCandidate]:
    lines = normalize_ocr_lines(payload)
    width = max(1.0, float(payload.get("width") or 1))
    height = max(1.0, float(payload.get("height") or 1))
    time_lines = [
        line
        for line in lines
        if is_time_label(line["text"])
        and height * 0.14 <= line["center_y"] <= height * 0.86
        and line["x"] <= width * 0.72
    ]
    candidates = []
    for index, line in enumerate(time_lines):
        next_y = time_lines[index + 1]["center_y"] if index + 1 < len(time_lines) else height * 0.94
        top = max(height * 0.10, line["center_y"] - height * 0.075)
        bottom = min(height * 0.94, next_y - height * 0.045)
        recommendation = next(
            (
                item
                for item in lines
                if line["center_y"] < item["center_y"] < bottom
                and "达人推荐" in "".join(item["text"].split())
            ),
            None,
        )
        bounded_by_recommendation = recommendation is not None
        if recommendation:
            bottom = min(bottom, recommendation["center_y"] - height * 0.018)
        if bottom - top < height * 0.07:
            continue
        card_lines = [item for item in lines if top <= item["center_y"] < bottom]
        author = _author_before(lines, line)
        card_text = "\n".join(item["text"] for item in card_lines)
        body_targets = [
            item
            for item in card_lines
            if item["center_y"] > line["center_y"] + line["height"] * 0.4
            and not _looks_like_action_or_preview(item["text"])
            and item["x"] < width * 0.85
            and not (
                len(_stable_text(item["text"])) <= 2
                and item["center_x"] > width * 0.40
            )
        ]
        preview_index = next(
            (
                position
                for position, item in enumerate(body_targets)
                if _looks_like_feed_comment_preview(item["text"])
            ),
            None,
        )
        content_targets = body_targets[:preview_index] if preview_index is not None else body_targets
        identity_lines: list[str] = []
        for item in content_targets:
            value = item["text"]
            identity_lines.append(value)
            if len(identity_lines) >= 6:
                break
        stable_text = _stable_text("\n".join((line["text"], author, *identity_lines)))
        if len(stable_text) < 4:
            continue
        tags = tuple(
            dict.fromkeys(
                match
                for item in content_targets
                for match in TAG_PATTERN.findall(item["text"])
            )
        )
        category = _extract_category([item["text"] for item in content_targets], list(tags))
        body_lines = [
            item["text"]
            for item in content_targets
            if not TAG_PATTERN.search(item["text"])
            and not _is_feed_category_text(item["text"])
            and not INTEGER_PATTERN.fullmatch("".join(item["text"].split()))
        ][:5]
        body_text = "\n".join(body_lines).strip()
        truncated = any(_looks_truncated(value) for value in body_lines)
        probe_bottom = bottom
        if not recommendation:
            probe_bottom = min(height * 0.965, next_y - height * 0.015)
        action_probe_lines = [
            item for item in lines if top <= item["center_y"] < probe_bottom
        ]
        has_preview = any(
            _looks_like_feed_comment_preview(item["text"])
            for item in action_probe_lines
        )
        reply_count = _feed_reply_count(action_probe_lines)
        has_comments = reply_count is not None or preview_index is not None or has_preview
        metrics = _feed_metrics(action_probe_lines, width, line["center_y"])
        if reply_count is not None:
            metrics["comment_count"] = reply_count
        elif has_comments and metrics["comment_count"] is None:
            metrics["comment_count"] = 1
        fully_visible = index + 1 < len(time_lines) or bounded_by_recommendation
        needs_detail = bool(truncated or has_comments or not fully_visible or not body_text)
        target = content_targets[0] if content_targets else (body_targets[0] if body_targets else line)
        click_y = min(bottom - 4, max(line["center_y"] + height * 0.035, target["center_y"]))
        candidates.append(
            FeedCandidate(
                display_time=line["text"],
                author_hint=author,
                card_text=card_text,
                signature=hashlib.sha256(stable_text.encode("utf-8")).hexdigest(),
                click_x=width * 0.48,
                click_y=click_y,
                top=top,
                bottom=bottom,
                anchor_y=line["center_y"],
                body_text=body_text,
                tags=tags,
                category=category,
                collect_count=metrics["collect_count"],
                comment_count=metrics["comment_count"],
                like_count=metrics["like_count"],
                truncated=truncated,
                has_comments=has_comments,
                needs_detail=needs_detail,
            )
        )
    return candidates


def feed_candidates_equivalent(left: FeedCandidate, right: FeedCandidate) -> bool:
    """Fuzzy run-local identity that tolerates small OCR changes."""
    if left.signature == right.signature:
        return True
    left_author = _stable_text(left.author_hint)
    right_author = _stable_text(right.author_hint)
    authors_equivalent = bool(
        not left_author
        or not right_author
        or _ocr_text_equivalent(left_author, right_author)
    )
    left_body = _stable_text(left.body_text)
    right_body = _stable_text(right.body_text)
    if not left_body or not right_body:
        return False
    shortest = min(len(left_body), len(right_body))
    # The nickname can be badly distorted between overlapping frames. A long
    # identical body is a stronger local identity anchor than the nickname.
    if shortest >= 12 and (left_body in right_body or right_body in left_body):
        return True
    matcher = SequenceMatcher(None, left_body, right_body)
    matched_coverage = sum(block.size for block in matcher.get_matching_blocks()) / shortest
    coverage_threshold = 0.82 if authors_equivalent else 0.92
    if shortest >= 12 and matched_coverage >= coverage_threshold:
        return True
    if not authors_equivalent:
        threshold = 0.90 if shortest >= 12 else 0.95
    else:
        threshold = 0.78 if shortest >= 12 else 0.86
    return matcher.ratio() >= threshold


def measure_ocr_vertical_displacement(
    before: dict[str, Any], after: dict[str, Any]
) -> float | None:
    """Measure content movement from stable OCR anchors; negative means page-down."""
    before_anchors = _scroll_anchors(before)
    after_anchors = _scroll_anchors(after)
    if not before_anchors or not after_anchors:
        return None
    used: set[int] = set()
    displacements: list[float] = []
    for before_key, before_y in before_anchors:
        best_index = None
        best_score = 0.0
        for index, (after_key, after_y) in enumerate(after_anchors):
            if index in used:
                continue
            if before_key == after_key:
                score = 1.0
            elif min(len(before_key), len(after_key)) >= 8:
                score = SequenceMatcher(None, before_key, after_key).ratio()
            else:
                score = 0.0
            if score >= 0.88 and score > best_score:
                best_index = index
                best_score = score
        if best_index is not None:
            used.add(best_index)
            displacements.append(after_anchors[best_index][1] - before_y)
    return float(median(displacements)) if displacements else None


def parse_feed_candidate(candidate: FeedCandidate, *, captured_at: datetime) -> dict[str, Any]:
    """Create a complete record when a no-comment post is fully visible in the feed."""
    estimated_from, estimated_to = estimate_display_time(candidate.display_time, captured_at)
    stable = _stable_text(
        "\n".join((candidate.author_hint, candidate.body_text, " ".join(candidate.tags)))
    )
    if len(stable) < 4:
        stable = candidate.signature
    return {
        "fingerprint": hashlib.sha256(stable.encode("utf-8")).hexdigest(),
        "author_label": candidate.author_hint,
        "display_time": candidate.display_time,
        "estimated_from": estimated_from,
        "estimated_to": estimated_to,
        "body_text": candidate.body_text,
        "tags": list(candidate.tags),
        "category": candidate.category,
        "collect_count": candidate.collect_count,
        "comment_count": candidate.comment_count,
        "like_count": candidate.like_count,
        "comments": [],
        "capture_complete": True,
        "raw_ocr_frames": [candidate.card_text.splitlines()],
    }


def looks_like_detail_page(payload: dict[str, Any]) -> bool:
    texts = [line["text"] for line in normalize_ocr_lines(payload)]
    return any(text == "详情" or COMMENT_MARKER_PATTERN.search(text) for text in texts)


def looks_like_deleted_post(payload: dict[str, Any]) -> bool:
    """Identify a deleted post without confusing it with a deleted comment."""
    compact = _compact_ocr_text(payload)
    return any(
        marker in compact
        for marker in (
            "帖子已经被删除",
            "帖子已经被删",
            "帖子已被删除",
            "帖子已删除",
            "该帖子不存在",
            "帖子不存在",
        )
    )


def looks_like_feed_page(payload: dict[str, Any]) -> bool:
    texts = [line["text"] for line in normalize_ocr_lines(payload)]
    compact = {"".join(value.split()) for value in texts}
    campus_tab = any(
        "本校" in value or (len(value) == 2 and value.startswith("本"))
        for value in compact
    )
    category_hits = sum(
        value in compact
        for value in ("全部", "避雷", "精选", "校园动态", "社团生活", "校园日常")
    )
    # The recommendation block can occupy the viewport. The sticky campus tab
    # and category strip are the reliable page identity; timestamps are not.
    return campus_tab and category_hits >= 2


def latest_tab_position(payload: dict[str, Any]) -> tuple[float, float] | None:
    width = max(1.0, float(payload.get("width") or 1))
    height = max(1.0, float(payload.get("height") or 1))
    lines = normalize_ocr_lines(payload)
    recommendation_tabs = [line for line in lines if line["text"] == "推荐"]
    for line in lines:
        paired = any(
            abs(other["center_y"] - line["center_y"]) <= height * 0.035
            for other in recommendation_tabs
        )
        if (
            line["text"] == "最新"
            and width * 0.08 <= line["center_x"] <= width * 0.38
            and height * 0.35 <= line["center_y"] <= height * 0.68
            and paired
        ):
            return line["center_x"], line["center_y"]
    return None


def looks_like_detail_bottom(payload: dict[str, Any]) -> bool:
    compact = _compact_ocr_text(payload).upper()
    return (
        "长按评论可赞赏" in compact
        and "遇到热心猹友可以给TA一点鼓励" in compact
    )


def looks_like_transient_overlay(payload: dict[str, Any]) -> bool:
    compact = _compact_ocr_text(payload)
    return (
        (
            "分享至" in compact
            and any(value in compact for value in ("生成分享图", "微信好友", "朋友圈", "复制链接"))
        )
        or "正在努力生成中" in compact
        or ("保存图片" in compact and "长按扫码查看回复" in compact)
    )


def detail_matches_candidate(payload: dict[str, Any], candidate: FeedCandidate) -> bool:
    if not looks_like_detail_page(payload):
        return False
    page = _stable_text("\n".join(line["text"] for line in normalize_ocr_lines(payload)))
    anchors = [candidate.author_hint, *(candidate.body_text.splitlines()[:2])]
    stable_anchors = [_stable_text(value) for value in anchors]
    stable_anchors = [value for value in stable_anchors if len(value) >= 4]
    return not stable_anchors or any(value in page for value in stable_anchors)


def parse_detail_capture(
    frames: list[dict[str, Any]],
    *,
    captured_at: datetime,
    author_hint: str = "",
    display_time_hint: str = "",
) -> dict[str, Any]:
    normalized_frames = [normalize_ocr_lines(frame) for frame in frames]
    flat_first = normalized_frames[0] if normalized_frames else []
    all_texts = [[line["text"] for line in lines] for lines in normalized_frames]
    marker_index = next(
        (index for index, texts in enumerate(all_texts) if any(_is_comment_boundary(text) for text in texts)),
        None,
    )

    first_time_line = next((line for line in flat_first if is_time_label(line["text"])), None)
    detail_author = _author_before(flat_first, first_time_line) if first_time_line else ""
    author = detail_author or author_hint
    # Detail is captured after opening the card and can refresh stale relative
    # times shown by the feed, so prefer its header timestamp.
    display_time = (first_time_line["text"] if first_time_line else "") or display_time_hint

    post_frame_end = marker_index if marker_index is not None else len(normalized_frames) - 1
    post_texts: list[str] = []
    for lines in normalized_frames[: post_frame_end + 1]:
        frame_values: list[str] = []
        for line in lines:
            text_value = line["text"]
            if _is_comment_boundary(text_value):
                break
            if _is_post_chrome(text_value, author=author, display_time=display_time):
                continue
            frame_values.append(text_value)
        _merge_overlapping_sequence(post_texts, frame_values)

    tags = []
    for text_value in post_texts:
        for match in TAG_PATTERN.findall(text_value):
            if match not in tags:
                tags.append(match)
    category = _extract_category(post_texts, tags)
    body_lines = [
        value
        for value in post_texts
        if not TAG_PATTERN.search(value)
        and not _looks_like_action_or_preview(value)
        and not INTEGER_PATTERN.fullmatch(value)
    ]
    body_text = "\n".join(_deduplicate_ocr_lines(body_lines)).strip()
    if not body_text:
        body_text = "\n".join(post_texts).strip()

    comments = _parse_comments(normalized_frames, marker_index)
    metrics = _parse_metrics(all_texts)
    spatial_metrics = _parse_detail_spatial_metrics(frames)
    for key, value in spatial_metrics.items():
        if value is not None:
            metrics[key] = value
    estimated_from, estimated_to = estimate_display_time(display_time, captured_at)
    stable = _stable_text("\n".join((author, body_text, " ".join(tags))))
    if len(stable) < 8:
        stable = _stable_text("\n".join(all_texts[0] if all_texts else []))
    fingerprint = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    return {
        "fingerprint": fingerprint,
        "author_label": author,
        "display_time": display_time,
        "estimated_from": estimated_from,
        "estimated_to": estimated_to,
        "body_text": body_text,
        "tags": tags,
        "category": category,
        "collect_count": metrics.get("collect_count"),
        "comment_count": metrics.get("comment_count"),
        "like_count": metrics.get("like_count"),
        "comments": comments,
        "capture_complete": marker_index is not None,
        "raw_ocr_frames": all_texts,
    }


def estimate_display_time(label: str, captured_at: datetime) -> tuple[str | None, str | None]:
    value = "".join(str(label or "").split())
    if not value:
        return None, None
    if value == "刚刚":
        return (captured_at - timedelta(minutes=1)).isoformat(), captured_at.isoformat()
    match = re.fullmatch(r"(\d+)分钟前", value)
    if match:
        end = captured_at - timedelta(minutes=int(match.group(1)))
        return (end - timedelta(minutes=1)).isoformat(), end.isoformat()
    match = re.fullmatch(r"(\d+)小时前", value)
    if match:
        end = captured_at - timedelta(hours=int(match.group(1)))
        return (end - timedelta(hours=1)).isoformat(), end.isoformat()
    if value in {"昨天", "前天"}:
        days = 1 if value == "昨天" else 2
        day = (captured_at - timedelta(days=days)).date()
        return _whole_day(day, captured_at)
    match = re.fullmatch(r"(\d+)天前", value)
    if match:
        return _whole_day((captured_at - timedelta(days=int(match.group(1)))).date(), captured_at)
    match = re.fullmatch(r"(\d+)个月前", value)
    if match:
        days = int(match.group(1)) * 30
        start = captured_at - timedelta(days=days + 15)
        end = captured_at - timedelta(days=max(0, days - 15))
        return start.isoformat(), end.isoformat()
    match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{2}))?", value)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        hour = int(match.group(3)) if match.group(3) else 0
        minute = int(match.group(4)) if match.group(4) else 0
        try:
            candidate = captured_at.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > captured_at + timedelta(days=1):
                candidate = candidate.replace(year=candidate.year - 1)
        except ValueError:
            return None, None
        if match.group(3):
            return candidate.isoformat(), (candidate + timedelta(minutes=1)).isoformat()
        return _whole_day(candidate.date(), captured_at)
    return None, None


def is_time_label(value: str) -> bool:
    return bool(TIME_LABEL_PATTERN.fullmatch(" ".join(str(value or "").split()).strip()))


def _whole_day(day, captured_at: datetime) -> tuple[str, str]:
    start = datetime.combine(day, time.min, tzinfo=captured_at.tzinfo)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def _author_before(lines: list[dict[str, Any]], target: dict[str, Any] | None) -> str:
    if not target:
        return ""
    previous = [
        line
        for line in lines
        if line["center_y"] < target["center_y"]
        and target["center_y"] - line["center_y"] < max(80, target["height"] * 4)
        and not _is_generic_ui(line["text"])
        and bool(re.search(r"[0-9A-Za-z\u3400-\u9fff]", line["text"]))
    ]
    return previous[-1]["text"] if previous else ""


def _is_generic_ui(value: str) -> bool:
    return value in {
        "详情", "分享", "置顶", "收藏", "赞赏", "推荐", "最新", "只看作者",
        "签到", "关注", "高校圈", "本校", "十大", "达人推荐", "换一批",
        "首页", "团购", "消息", "我的", "全部", "避雷", "精选", "校园动态", "社团生活", "校园日常",
    }


def _is_post_chrome(value: str, *, author: str, display_time: str) -> bool:
    if (
        not value
        or value == display_time
        or is_time_label(value)
        or (author and _ocr_text_equivalent(value, author))
        or _is_generic_ui(value)
    ):
        return True
    return _is_comment_boundary(value)


def _looks_like_action_or_preview(value: str) -> bool:
    compact = "".join(value.split())
    if not re.search(r"[0-9A-Za-z\u3400-\u9fff]", compact):
        return True
    if compact in {"分享", "置顶", "收藏", "赞赏", "推荐", "最新", "只看作者", "达人推荐", "换一批"}:
        return True
    if re.fullmatch(r"共\d+条回复>?", compact):
        return True
    if compact.startswith("发一条友善的评论"):
        return True
    if compact.startswith("长按评论可赞赏") or compact in {"励", "这里空空如也哦"}:
        return True
    if len(compact) <= 7 and any(marker in compact for marker in ("分享", "置顶", "收藏", "赞赏")):
        return True
    if len(compact) <= 5 and "赞" in compact:
        return True
    if re.fullmatch(r"[A-Za-z]?\d{1,3}", compact):
        return True
    return False


def _looks_like_feed_comment_preview(value: str) -> bool:
    compact = "".join(value.split())
    return bool(
        re.fullmatch(r"共\d+条回复>?", compact)
        or re.match(r".{1,24}(?:…|⋯|[.•·]+)[:：].+", compact)
    )


def _looks_truncated(value: str) -> bool:
    compact = "".join(value.split())
    return bool(re.search(r"(?:…|⋯|\.{3})(?:[>~]?)$", compact))


def _is_feed_category_text(value: str) -> bool:
    compact = "".join(value.split()).lstrip("#")
    return compact in {
        "校园日常", "校园动态", "社团生活", "闲置集市", "校内求助", "避雷", "精选",
    }


def _feed_reply_count(lines: list[dict[str, Any]]) -> int | None:
    for line in lines:
        match = re.search(r"共\s*(\d+)\s*条回复", line["text"])
        if match:
            return int(match.group(1))
    return None


def _feed_metrics(
    lines: list[dict[str, Any]], width: float, time_y: float
) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "collect_count": None,
        "comment_count": None,
        "like_count": None,
    }
    # Feed action counts have no OCR labels. Their horizontal slots are stable:
    # collect, comment, like. Restricting to the action half of the card avoids
    # interpreting years, prices, or phone-number fragments as metrics.
    for line in lines:
        compact = "".join(line["text"].split())
        if line["center_y"] <= time_y or not INTEGER_PATTERN.fullmatch(compact):
            continue
        ratio = line["center_x"] / width
        key = None
        if 0.62 <= ratio < 0.73:
            key = "collect_count"
        elif 0.73 <= ratio < 0.86:
            key = "comment_count"
        elif 0.86 <= ratio <= 0.99:
            key = "like_count"
        if key:
            result[key] = int(compact)
    return result


def _compact_ocr_text(payload: dict[str, Any]) -> str:
    return "".join(
        re.sub(r"\s+", "", line["text"])
        for line in normalize_ocr_lines(payload)
    )


def _scroll_anchors(payload: dict[str, Any]) -> list[tuple[str, float]]:
    height = max(1.0, float(payload.get("height") or 1))
    anchors: list[tuple[str, float]] = []
    for line in normalize_ocr_lines(payload):
        if not height * 0.48 <= line["center_y"] <= height * 0.90:
            continue
        if _is_generic_ui(line["text"]) or _looks_like_action_or_preview(line["text"]):
            continue
        stable = _stable_text(line["text"])
        if len(stable) < 4:
            continue
        anchors.append((stable, line["center_y"]))
    return anchors


def _extract_category(lines: list[str], tags: list[str]) -> str:
    known = {"校园日常", "校园动态", "社团生活", "闲置集市", "校内求助", "避雷", "精选"}
    for value in lines:
        for candidate in known:
            if candidate in value and f"#{candidate}" not in tags:
                return candidate
    return ""


def _parse_metrics(frames: list[list[str]]) -> dict[str, int | None]:
    result: dict[str, int | None] = {"collect_count": None, "comment_count": None, "like_count": None}
    for texts in frames:
        joined = " ".join(texts)
        match = COMMENT_MARKER_PATTERN.search(joined)
        if match and match.group(1):
            result["comment_count"] = int(match.group(1))
        elif result["comment_count"] is None and EMPTY_COMMENTS_PATTERN.search(joined):
            result["comment_count"] = 0
        for key, patterns in (
            ("collect_count", (r"收藏\s*(\d+)",)),
            ("like_count", (r"(?:点赞|赞)\s*(\d+)",)),
        ):
            for pattern in patterns:
                match = re.search(pattern, joined)
                if match:
                    result[key] = int(match.group(1))
                    break
    return result


def _parse_detail_spatial_metrics(
    frames: list[dict[str, Any]],
) -> dict[str, int | None]:
    result: dict[str, int | None] = {"collect_count": None, "like_count": None}
    for payload in frames:
        width = max(1.0, float(payload.get("width") or 1))
        height = max(1.0, float(payload.get("height") or 1))
        lines = normalize_ocr_lines(payload)
        collect_labels = [line for line in lines if "收藏" in line["text"]]
        for label in collect_labels:
            same_row = [
                line
                for line in lines
                if abs(line["center_y"] - label["center_y"]) <= height * 0.025
            ]
            collect_candidates = [
                line
                for line in same_row
                if label["center_x"] < line["center_x"] < width * 0.76
                and re.fullmatch(r"\d{1,7}", "".join(line["text"].split()))
            ]
            if collect_candidates:
                result["collect_count"] = int(collect_candidates[0]["text"])
            like_candidates = [
                line
                for line in same_row
                if line["center_x"] >= width * 0.82
                and re.fullmatch(r"[VvYy]?\d{1,7}", "".join(line["text"].split()))
            ]
            if like_candidates:
                compact = "".join(like_candidates[-1]["text"].split())
                match = re.search(r"(\d+)$", compact)
                if match:
                    result["like_count"] = int(match.group(1))
    return result


def _parse_comments(
    frames: list[list[dict[str, Any]]], marker_index: int | None
) -> list[dict[str, Any]]:
    if marker_index is None:
        return []
    stream: list[str] = []
    marker_seen = False
    for lines in frames[marker_index:]:
        frame_marker = next(
            (index for index, line in enumerate(lines) if _is_comment_boundary(line["text"])),
            None,
        )
        if frame_marker is not None:
            marker_seen = True
            selected_lines = lines[frame_marker + 1 :]
        elif marker_seen:
            selected_lines = lines
        else:
            continue
        frame_values: list[str] = []
        for line in selected_lines:
            value = line["text"]
            compact = "".join(value.split())
            if _is_generic_ui(value) or _is_comment_boundary(value):
                continue
            if _looks_like_comment_chrome(value):
                continue
            if line["x"] > 250 and re.fullmatch(r"\d+\s*[★☆]?️?", compact):
                continue
            frame_values.append(value)
        _merge_overlapping_sequence(stream, frame_values)

    comments = []
    used: set[str] = set()
    time_indexes = [index for index, value in enumerate(stream) if is_time_label(value)]
    for position, index in enumerate(time_indexes):
        value = stream[index]
        author = stream[index - 1] if index > 0 and not is_time_label(stream[index - 1]) else ""
        next_time = time_indexes[position + 1] if position + 1 < len(time_indexes) else len(stream)
        body_end = max(index + 1, next_time - 1) if next_time < len(stream) else next_time
        body = [
            following
            for following in stream[index + 1 : body_end]
            if following != author and not _looks_like_comment_chrome(following)
        ][:12]
        body_text = "\n".join(body).strip()
        stable = _stable_text("\n".join((author, value, body_text)))
        if len(stable) < 3:
            continue
        fingerprint = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        if fingerprint in used:
            continue
        used.add(fingerprint)
        comments.append(
            {
                "fingerprint": fingerprint,
                "author_label": author,
                "display_time": value,
                "body_text": body_text,
                "like_count": None,
                "images": [],
            }
        )
    return comments


def _merge_overlapping_sequence(target: list[str], incoming: list[str]) -> None:
    if not incoming:
        return
    maximum = min(len(target), len(incoming), 40)
    overlap = 0
    for size in range(maximum, 0, -1):
        pairs = zip(target[-size:], incoming[:size])
        equivalent = sum(_ocr_text_equivalent(left, right) for left, right in pairs)
        required = size if size <= 2 else max(2, int(size * 0.8 + 0.999))
        if equivalent >= required:
            overlap = size
            break
    target.extend(incoming[overlap:])


def _is_comment_boundary(value: str) -> bool:
    return bool(COMMENT_MARKER_PATTERN.search(value) or EMPTY_COMMENTS_PATTERN.search(value))


def _looks_like_comment_chrome(value: str) -> bool:
    compact = "".join(value.split())
    return (
        compact.startswith("发一条友善的评论")
        or compact.startswith("长按评论可赞赏")
        or compact in {"励", "这里空空如也哦"}
    )


def _ocr_text_equivalent(left: str, right: str) -> bool:
    normalized_left = _stable_text(left)
    normalized_right = _stable_text(right)
    if normalized_left == normalized_right:
        return True
    shortest = min(len(normalized_left), len(normalized_right))
    if shortest < 4:
        return False
    threshold = 0.75 if shortest < 8 else 0.84
    return SequenceMatcher(None, normalized_left, normalized_right).ratio() >= threshold


def _deduplicate_ocr_lines(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        duplicate_index = next(
            (
                index
                for index in range(max(0, len(result) - 120), len(result))
                if _ocr_duplicate_equivalent(result[index], value)
            ),
            None,
        )
        if duplicate_index is None:
            result.append(value)
        elif len(value) > len(result[duplicate_index]):
            result[duplicate_index] = value
    return result


def _ocr_duplicate_equivalent(left: str, right: str) -> bool:
    normalized_left = _stable_text(left)
    normalized_right = _stable_text(right)
    if normalized_left == normalized_right:
        return True
    shortest = min(len(normalized_left), len(normalized_right))
    if shortest < 4:
        return False
    threshold = 0.75 if shortest == 4 else 0.90
    return SequenceMatcher(None, normalized_left, normalized_right).ratio() >= threshold


def _append_unique(values: list[str], value: str) -> None:
    compact = " ".join(value.split()).strip()
    if not compact:
        return
    # Overlapping scroll captures repeat most lines.  Exact and containment
    # checks preserve reading order while avoiding a quadratic fuzzy matcher.
    if compact in values[-20:]:
        return
    if values and min(len(compact), len(values[-1])) >= 4 and (compact in values[-1] or values[-1] in compact):
        if len(compact) > len(values[-1]):
            values[-1] = compact
        return
    values.append(compact)


def _stable_text(value: str) -> str:
    compact = re.sub(r"\s+", "", value or "")
    compact = re.sub(r"(?:刚刚|昨天|前天|\d+(?:分钟|小时|天|个月)前)", "", compact)
    compact = re.sub(r"(?:分享|置顶|收藏|赞赏|推荐|最新|只看作者|全部评论)", "", compact)
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff#]", "", compact).lower()


__all__ = [
    "FeedCandidate",
    "detail_matches_candidate",
    "detect_feed_candidates",
    "estimate_display_time",
    "feed_candidates_equivalent",
    "is_time_label",
    "latest_tab_position",
    "looks_like_deleted_post",
    "looks_like_detail_bottom",
    "looks_like_detail_page",
    "looks_like_feed_page",
    "looks_like_transient_overlay",
    "measure_ocr_vertical_displacement",
    "normalize_ocr_lines",
    "parse_detail_capture",
    "parse_feed_candidate",
]
