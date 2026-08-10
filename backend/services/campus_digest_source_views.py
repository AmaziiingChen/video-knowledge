"""Deterministic source and fact-card projections for campus digests."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

from services import campus_digest_cluster_rules as cluster_rules
from services.campus_digest_payloads import one_line


class DigestSource(Protocol):
    citation_id: str
    content_item_id: str
    title: str
    source_url: str
    published_at: str
    publisher: str
    source_channel: str
    material: str


class DigestCluster(Protocol):
    member_indexes: list[int]


ClusterT = TypeVar("ClusterT", bound=DigestCluster)


def event_identity_text(source: DigestSource, card: dict[str, Any]) -> str:
    parts = [
        f"标题：{source.title}",
        f"来源：{source.publisher}",
        f"渠道：{source.source_channel}",
        f"文种：{card['document_type']}",
        f"阶段：{card['event_stage']}",
        f"核心事项：{card['event_or_subject']}",
        f"摘要：{card['summary']}",
    ]
    labels = {
        "issuers": "发布单位",
        "organizers": "主办单位",
        "actors": "主体",
        "actions": "动作",
        "objects": "对象事项",
        "audiences": "面向对象",
        "time_points": "时间",
        "locations": "地点",
        "terms_or_batches": "届次批次",
        "identifiers": "编号",
        "attachments": "附件",
        "topics": "主题",
    }
    for key, label in labels.items():
        values = card.get(key) or []
        if values:
            parts.append(f"{label}：{'；'.join(values)}")
    ocr_facts = [
        fact["text"]
        for fact in card.get("atomic_facts") or []
        if fact.get("origin") == "image_ocr"
    ]
    if ocr_facts:
        parts.append("图片事实：" + "；".join(ocr_facts[:12]))
    return "\n".join(part for part in parts if not part.endswith("："))[:8000]


def cluster_profiles(sources: Sequence[DigestSource]) -> list[dict[str, Any]]:
    """Create lightweight, non-LLM inputs used only for duplicate retrieval."""
    profiles: list[dict[str, Any]] = []
    for source in sources:
        profiles.append(
            {
                "summary": cluster_rules.cluster_material(source),
                "content_decision": "include",
                "decision_reason": "聚类候选不作内容取舍",
                "category": "其他动态",
                "document_type": "other",
                "event_stage": "unknown",
                "event_or_subject": source.title,
                "issuers": [],
                "organizers": [],
                "actors": [],
                "actions": [],
                "objects": [],
                "audiences": [],
                "time_points": [],
                "locations": [],
                "terms_or_batches": [],
                "identifiers": [],
                "links": [],
                "attachments": [],
                "topics": [],
                "atomic_facts": [],
                "ad_segments": [],
                "uncertainties": [],
            }
        )
    return profiles


def select_report_cluster_primaries(
    clusters: Sequence[ClusterT],
    sources: Sequence[DigestSource],
    report_ids: set[str],
) -> list[tuple[ClusterT, int]]:
    selected: list[tuple[ClusterT, int]] = []
    for cluster in clusters:
        candidates = [
            index
            for index in cluster.member_indexes
            if sources[index].content_item_id in report_ids
        ]
        if not candidates:
            continue
        # 公文通是同一内容的主来源；其余正式来源按最早发布时间稳定选择。
        primary = min(
            candidates,
            key=lambda index: (
                0 if sources[index].source_channel == "gwt" else 1,
                sources[index].published_at or "9999",
                sources[index].content_item_id,
            ),
        )
        selected.append((cluster, primary))
    return selected


def publishing_brief(source: DigestSource, card: dict[str, Any]) -> dict[str, Any]:
    facts = facts_for_brief(card, source.citation_id)
    return {
        "title": card["event_or_subject"] or source.title,
        "category": card["category"],
        "summary": card["summary"],
        "stages": [{"stage": card["event_stage"], "facts": facts}],
        "conflicts": list(card.get("uncertainties") or []),
        "source_ids": [source.citation_id],
    }


def source_appendix(sources: Sequence[DigestSource]) -> str:
    lines = ["## 来源文章", ""]
    for source in sources:
        title = one_line(source.title).replace("[", "\\[").replace("]", "\\]") or "未命名文章"
        publisher = one_line(source.publisher) or "未知来源"
        date = source.published_at[:10] if source.published_at else "日期未知"
        channel = {
            "gwt": "公文通",
            "college_website": "学院官网",
            "wechat": "微信公众号",
        }.get(source.source_channel, source.source_channel or "校园来源")
        link = f"[{title}](<{source.source_url}>)" if source.source_url else title
        lines.append(f"[^{source.citation_id}]: {link} · {channel} · {publisher} · {date}")
    return "\n".join(lines)


def facts_for_brief(card: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    facts = [
        {"text": fact["text"], "source_ids": [source_id]}
        for fact in card.get("atomic_facts") or []
    ]
    if not facts:
        facts.append({"text": card["summary"], "source_ids": [source_id]})
    return facts


__all__ = [
    "cluster_profiles",
    "event_identity_text",
    "facts_for_brief",
    "publishing_brief",
    "select_report_cluster_primaries",
    "source_appendix",
]
