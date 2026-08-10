from __future__ import annotations

from types import SimpleNamespace

from services.campus_digest_cluster_rules import (
    cluster_material,
    cluster_similarity,
    hard_conflict,
    pair_is_worth_judging,
    rule_pair_decision,
)


def _source(*, content_id: str, title: str, material: str, source_url: str) -> SimpleNamespace:
    return SimpleNamespace(
        content_item_id=content_id,
        title=title,
        material=material,
        source_url=source_url,
        publisher="校园公众号",
        published_at="2026-08-10T10:00:00+08:00",
    )


def _card(*, subject: str = "校园文化节", stage: str = "announcement", term: str = "") -> dict[str, object]:
    return {
        "event_or_subject": subject,
        "event_stage": stage,
        "organizers": ["校团委"],
        "objects": ["校园文化节"],
        "audiences": [],
        "issuers": [],
        "actors": [],
        "locations": [],
        "terms_or_batches": [term] if term else [],
        "identifiers": [],
    }


def test_canonical_url_rule_ignores_share_tracking_and_preserves_same_content():
    left = _source(
        content_id="left",
        title="校园文化节活动通知",
        material="活动安排",
        source_url="https://example.test/post?from=share&scene=1",
    )
    right = _source(
        content_id="right",
        title="校园文化节活动通知",
        material="另一份材料",
        source_url="https://example.test/post",
    )

    decision = rule_pair_decision(left, _card(), right, _card(), similarity=0.0)

    assert decision is not None
    assert (decision.relation, decision.same_event, decision.method) == ("same_content", True, "canonical_url")


def test_conflicting_editions_do_not_merge():
    left = _source(content_id="left", title="第六届比赛通知", material="报名安排", source_url="")
    right = _source(content_id="right", title="第七届比赛结果", material="获奖名单", source_url="")
    left_card = _card(term="第六届")
    right_card = _card(stage="result", term="第七届")

    decision = rule_pair_decision(left, left_card, right, right_card, similarity=0.99)

    assert hard_conflict(left_card, right_card) is True
    assert decision is not None
    assert (decision.relation, decision.same_event, decision.method) == ("different_event", False, "hard_conflict")


def test_shared_subject_with_result_stage_uses_event_result_relation():
    left = _source(content_id="left", title="比赛报名通知", material="报名安排", source_url="")
    right = _source(content_id="right", title="比赛获奖公示", material="获奖名单", source_url="")

    decision = rule_pair_decision(left, _card(), right, _card(stage="result"), similarity=0.0)

    assert decision is not None
    assert (decision.relation, decision.same_event, decision.method) == (
        "same_event_result",
        True,
        "subject_and_core_fields",
    )


def test_candidate_helpers_bound_material_and_rank_cluster_members():
    source = _source(
        content_id="item",
        title="校园文化节活动通知",
        material="  首段\n\n第二段  ",
        source_url="",
    )
    cluster = SimpleNamespace(member_indexes=[0, 1])

    assert cluster_material(source) == "标题：校园文化节活动通知\n来源：校园公众号\n正文：首段 第二段"
    assert pair_is_worth_judging(source, source, similarity=0.0) is True
    assert cluster_similarity([1.0, 0.0], cluster, [[0.0, 1.0], [1.0, 0.0]]) == 1.0
