"""Evidence context and quotation validation for grounded knowledge answers."""
from __future__ import annotations

import html
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.knowledge_v2 import RetrievedChunk


ANSWER_EVIDENCE_MAX_CANDIDATES = 10
ANSWER_CONTEXT_CHAR_BUDGET = 16_000
_SENTENCE_RE = re.compile(r"(?<=[。！？；.!?;])\s*")


def evidence_payload(results: list[RetrievedChunk], *, question: str = "") -> list[dict[str, object]]:
    return [
        {
            "evidence_id": f"E{index:03d}",
            "chunk_id": result.chunk_id,
            "parent_chunk_id": result.parent_chunk_id,
            "content_item_id": result.content_item_id,
            "title": result.title,
            "source_name": result.source_name,
            "source_label": result.source_name,
            "source_url": result.source_url,
            "published_at": result.published_at,
            "heading_path": result.heading_path,
            "child_text": result.child_text,
            "parent_text": result.parent_text,
            # The answer model receives parent context. Use that same context
            # for the visible excerpt so a child chunk that lands on a page
            # footer cannot hide the sentence that actually supports the answer.
            "excerpt": citation_excerpt(result.parent_text or result.child_text, question, title=result.title),
        }
        for index, result in enumerate(results, 1)
    ]


def answer_evidence_payload(
    results: list[RetrievedChunk],
    *,
    question: str,
    evidence_limit: int | None,
) -> list[dict[str, object]]:
    """Fit all ranked candidates into a stable answer-context budget.

    The parent chunk is intentionally retained for the reader-facing evidence
    preview but not repeated in the model prompt: it often duplicates the
    child chunk several times and can exhaust a thinking model's output budget.
    """
    limit = ANSWER_EVIDENCE_MAX_CANDIDATES if evidence_limit is None else max(1, int(evidence_limit))
    selected = results[:limit]
    evidence = evidence_payload(selected, question=question)
    if not evidence:
        return evidence
    per_evidence_chars = max(800, ANSWER_CONTEXT_CHAR_BUDGET // len(evidence))
    compacted: list[dict[str, object]] = []
    for item in evidence:
        child_text = str(item["child_text"] or "")
        compacted.append(
            {
                **item,
                "child_text": compact_answer_evidence(
                    child_text,
                    question=question,
                    title=str(item["title"] or ""),
                    limit=per_evidence_chars,
                ),
            }
        )
    return compacted


def compact_answer_evidence(text: str, *, question: str, title: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    relevant = citation_excerpt(value, question, title=title, limit=max(240, limit // 2))
    prefix = value[: max(160, limit - len(relevant) - 10)].strip()
    if relevant and relevant not in prefix:
        return f"{prefix}\n…\n{relevant}"[:limit]
    return prefix[:limit]


def citation_excerpt(text: str, question: str, *, title: str = "", limit: int = 220) -> str:
    """Show the most relevant readable passage, not a page header or image URL."""
    value = html.unescape(str(text or "")).replace("\r\n", "\n")
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[原图[^\]]*\](?:\([^)]*\))?", " ", value)
    value = re.sub(r"<img\b[^>]*>", " ", value, flags=re.I)
    value = re.sub(r"</?(?:div|p|br|span)[^>]*>", " ", value, flags=re.I)
    value = strip_leading_page_chrome(value, title=title)
    paragraphs: list[str] = []
    for raw in re.split(r"\n\s*\n", value):
        paragraph = re.sub(r"^#{1,6}\s+.*$", "", raw, flags=re.M)
        paragraph = re.sub(r"https?://\S+", " ", paragraph)
        paragraph = re.sub(r"\s+", " ", paragraph).strip(" -—\t")
        if not paragraph or "点击" in paragraph and "关注公众号" in paragraph:
            continue
        if paragraph in {"原文内容", "点击关注公众号", "精致科研生活从这里开始"}:
            continue
        paragraphs.extend(
            sentence.strip()
            for sentence in _SENTENCE_RE.split(paragraph)
            if len(sentence.strip()) >= 12
        )
    if not paragraphs:
        return re.sub(r"\s+", " ", value).strip()[:limit]

    query_and_title = f"{str(question or '')} {str(title or '')}"
    phrases = [
        phrase.lower()
        for phrase in re.findall(
            r"[\u3400-\u9fff]{2,}|[A-Za-z0-9_]{2,}",
            query_and_title,
        )
        if len(phrase) >= 2
    ]
    # CJK does not have spaces. Add short overlapping terms so a title's
    # “崩溃退出” can still locate the source sentence “异常崩溃”.
    for sequence in re.findall(r"[\u3400-\u9fff]{2,}", query_and_title):
        phrases.extend(sequence[index : index + 2].lower() for index in range(len(sequence) - 1))
    phrases = list(dict.fromkeys(phrases))

    def score(paragraph: str) -> tuple[int, int, int]:
        lowered = paragraph.lower()
        matched = [phrase for phrase in phrases if phrase in lowered]
        return len(matched), sum(len(phrase) * lowered.count(phrase) for phrase in matched), -paragraphs.index(paragraph)

    selected = max(paragraphs, key=score)
    focus = next((selected.lower().find(phrase) for phrase in phrases if selected.lower().find(phrase) >= 0), 0)
    if len(selected) <= limit:
        return selected
    start = max(0, focus - limit // 3)
    end = min(len(selected), start + limit)
    start = max(0, end - limit)
    return ("…" if start else "") + selected[start:end].strip() + ("…" if end < len(selected) else "")


def strip_leading_page_chrome(value: str, *, title: str) -> str:
    """Remove RSS/translation page metadata before selecting an excerpt."""
    lines = value.splitlines()
    retained_from = 0
    skip_next_value = False
    normalized_title = re.sub(r"\s+", "", str(title or ""))
    for index, raw_line in enumerate(lines[:30]):
        line = raw_line.strip()
        normalized = re.sub(r"\s+", "", line)
        metadata = (
            not line
            or line.startswith("#")
            or line in {"See all posts", "Published on", "Translated on", "原文：", "作者：", "原文内容"}
            or bool(re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", line))
            or line.startswith(("[原图", "http://", "https://"))
            or line.startswith(("原文：", "作者："))
            or (normalized_title and normalized == normalized_title)
        )
        if skip_next_value:
            metadata = True
            skip_next_value = False
        if line in {"原文：", "作者："}:
            skip_next_value = True
        if not metadata:
            retained_from = index
            break
        retained_from = index + 1
    return "\n".join(lines[retained_from:])


def validated_evidence_quotes(
    value: object,
    *,
    evidence_ids: list[str],
    evidence: list[dict[str, object]],
    insufficient: bool,
) -> dict[str, str]:
    permitted = {str(item["evidence_id"]): item for item in evidence}
    if insufficient:
        if value not in (None, []):
            raise ValueError("证据不足时不应返回引用摘录")
        return {}
    if value in (None, []):
        # Quotes are optional for Flash Thinking because exact copying from
        # several long passages made structured answers unreliable. The
        # selected evidence is still scope-validated, and the UI receives a
        # server-derived readable excerpt from that evidence.
        return {
            evidence_id: str(permitted[evidence_id].get("excerpt") or "")
            for evidence_id in evidence_ids
        }
    if not isinstance(value, list):
        raise ValueError("模型回答缺少可验证的原文引用摘录")
    selected_ids = set(evidence_ids)
    quotes: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("模型返回的引用摘录格式错误")
        evidence_id = item.get("evidence_id")
        quote = str(item.get("quote") or "").strip()
        if not isinstance(evidence_id, str) or evidence_id not in selected_ids or evidence_id in quotes:
            raise ValueError("模型返回了范围外或重复的引用摘录")
        if not 8 <= len(quote) <= 220:
            raise ValueError("模型返回的引用摘录长度无效")
        source = permitted[evidence_id]
        source_text = f"{source['child_text']}\n{source['parent_text']}"
        if normalized_text(quote) not in normalized_text(source_text):
            raise ValueError("模型返回的引用摘录不在原文证据中")
        quotes[evidence_id] = quote
    for evidence_id in selected_ids.difference(quotes):
        quotes[evidence_id] = str(permitted[evidence_id].get("excerpt") or "")
    return quotes


def normalized_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    # Quotes may change full-width punctuation, Markdown escaping or whitespace.
    # Retain only letters and numbers (CJK included) so we tolerate presentation
    # differences without accepting a paraphrased factual claim.
    return "".join(char for char in normalized if char.isalnum())
