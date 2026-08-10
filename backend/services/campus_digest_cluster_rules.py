"""Deterministic candidate and merge rules for campus digest event clustering."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from services.campus_digest_embeddings import cosine_similarity
from services.campus_digest_identity import (
    canonical_url,
    normalize_identity,
    text_shingle_similarity,
)

_ORDINAL_RE = re.compile(r"(?:第?[一二三四五六七八九十百千万0-9]+(?:届|期|批|轮|季)|20\d{2}届)")


class _ClusterMembers(Protocol):
    member_indexes: list[int]


class _ClusterSource(Protocol):
    title: str
    source_url: str
    published_at: str
    publisher: str
    material: str


@dataclass(frozen=True)
class PairDecision:
    relation: str
    same_event: bool
    confidence: float
    method: str
    contradictions: tuple[str, ...] = ()


def cluster_material(source: _ClusterSource) -> str:
    text = re.sub(r"\s+", " ", source.material or "").strip()
    return f"标题：{source.title}\n来源：{source.publisher}\n正文：{text}"[:7_500]


def rule_pair_decision(
    left_source: _ClusterSource,
    left: dict[str, Any],
    right_source: _ClusterSource,
    right: dict[str, Any],
    similarity: float,
) -> PairDecision | None:
    left_url = canonical_url(left_source.source_url)
    right_url = canonical_url(right_source.source_url)
    if left_url and left_url == right_url:
        return PairDecision("same_content", True, 1.0, "canonical_url")
    overlap = text_shingle_similarity(left_source.material, right_source.material)
    if overlap >= 0.78:
        relation = "verbatim_repost" if overlap >= 0.92 else "rewritten_repost"
        return PairDecision(relation, True, min(0.99, overlap), "content_fingerprint")
    if hard_conflict(left, right):
        return PairDecision("different_event", False, 0.99, "hard_conflict")
    left_title = normalize_identity(left_source.title)
    right_title = normalize_identity(right_source.title)
    shared = shared_core_evidence(left, right)
    if len(left_title) >= 8 and left_title == right_title and shared >= 1:
        return PairDecision("rewritten_repost", True, 0.96, "normalized_title")
    subject_left = normalize_identity(left.get("event_or_subject"))
    subject_right = normalize_identity(right.get("event_or_subject"))
    if subject_left and subject_left == subject_right and shared >= 1:
        return PairDecision(stage_relation(left, right), True, 0.94, "subject_and_core_fields")
    if similarity >= 0.91 and shared >= 2:
        return PairDecision(stage_relation(left, right), True, 0.92, "embedding_and_core_fields")
    return None


def pair_payload(source: _ClusterSource, card: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": source.title,
        "publisher": source.publisher,
        "published_at": source.published_at,
        "source_url": source.source_url,
        "article_excerpt": cluster_material(source),
        "fact_card": card,
    }


def pair_is_worth_judging(left: _ClusterSource, right: _ClusterSource, similarity: float) -> bool:
    if similarity >= 0.55:
        return True
    if text_shingle_similarity(left.material, right.material) >= 0.2:
        return True
    left_title = normalize_identity(left.title)
    right_title = normalize_identity(right.title)
    return len(left_title) >= 8 and (left_title in right_title or right_title in left_title)


def stage_relation(left: dict[str, Any], right: dict[str, Any]) -> str:
    stages = {left.get("event_stage"), right.get("event_stage")}
    if "result" in stages or "publication" in stages:
        return "same_event_result"
    if "recap" in stages:
        return "same_event_report"
    if stages & {"adjustment", "supplement"}:
        return "same_event_update"
    return "same_event"


def hard_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_terms = {normalize_identity(value) for value in left.get("terms_or_batches") or [] if _ORDINAL_RE.search(value)}
    right_terms = {normalize_identity(value) for value in right.get("terms_or_batches") or [] if _ORDINAL_RE.search(value)}
    # Codes and identifiers are optional article details rather than a global
    # event identity: extraction formats vary and must never split reposts.
    return bool(left_terms and right_terms and left_terms.isdisjoint(right_terms))


def shared_core_evidence(left: dict[str, Any], right: dict[str, Any]) -> int:
    fields = ("issuers", "organizers", "actors", "objects", "audiences", "locations", "terms_or_batches", "identifiers")
    count = 0
    for field_name in fields:
        left_values = {normalize_identity(value) for value in left.get(field_name) or [] if normalize_identity(value)}
        right_values = {normalize_identity(value) for value in right.get(field_name) or [] if normalize_identity(value)}
        if left_values and right_values and left_values & right_values:
            count += 1
    return count


def cluster_similarity(vector: list[float], cluster: _ClusterMembers, embeddings: list[list[float]]) -> float:
    return max((cosine_similarity(vector, embeddings[index]) for index in cluster.member_indexes), default=0.0)
