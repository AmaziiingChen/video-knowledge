from types import SimpleNamespace

from services import campus_digest_generation, campus_digest_source_views


def _source(
    citation_id: str,
    content_item_id: str,
    *,
    title: str = "校园活动通知",
    published_at: str = "2026-08-10T09:30:00+08:00",
    source_channel: str = "wechat",
):
    return SimpleNamespace(
        citation_id=citation_id,
        content_item_id=content_item_id,
        title=title,
        source_url=f"https://example.test/{content_item_id}",
        published_at=published_at,
        publisher="校团委",
        source_channel=source_channel,
        material="  正文发布   校园活动安排  ",
    )


def test_generation_keeps_deterministic_source_view_aliases():
    assert campus_digest_generation._cluster_profiles is campus_digest_source_views.cluster_profiles
    assert campus_digest_generation._source_appendix is campus_digest_source_views.source_appendix
    assert campus_digest_generation._facts_for_brief is campus_digest_source_views.facts_for_brief


def test_source_views_build_stable_cluster_and_identity_inputs():
    source = _source("S001", "content-1")
    card = {
        "document_type": "activity",
        "event_stage": "announcement",
        "event_or_subject": "校园文化节",
        "summary": "学校将举办校园文化节",
        "organizers": ["校团委"],
        "locations": ["图书馆"],
        "atomic_facts": [
            {"text": "海报写明周五举行", "origin": "image_ocr"},
            {"text": "网页正文说明报名方式", "origin": "html"},
        ],
    }

    profiles = campus_digest_source_views.cluster_profiles([source])
    identity = campus_digest_source_views.event_identity_text(source, card)

    assert profiles[0]["summary"] == "标题：校园活动通知\n来源：校团委\n正文：正文发布 校园活动安排"
    assert profiles[0]["event_or_subject"] == "校园活动通知"
    assert profiles[0]["content_decision"] == "include"
    assert "核心事项：校园文化节" in identity
    assert "地点：图书馆" in identity
    assert "图片事实：海报写明周五举行" in identity
    assert "网页正文说明报名方式" not in identity


def test_primary_selection_prefers_gwt_and_skips_context_only_clusters():
    sources = [
        _source("S001", "wechat-earlier", published_at="2026-08-09", source_channel="wechat"),
        _source("S002", "gwt-later", published_at="2026-08-10", source_channel="gwt"),
        _source("S003", "context-only"),
    ]
    visible = SimpleNamespace(member_indexes=[0, 1])
    context_only = SimpleNamespace(member_indexes=[2])

    selected = campus_digest_source_views.select_report_cluster_primaries(
        [visible, context_only],
        sources,
        {"wechat-earlier", "gwt-later"},
    )

    assert selected == [(visible, 1)]


def test_publishing_brief_and_source_appendix_keep_fallbacks_and_markdown_escaping():
    source = _source("S001", "content-1", title="校园[活动]通知")
    card = {
        "event_or_subject": "",
        "category": "校园活动与文体",
        "summary": "学校将举办校园活动",
        "event_stage": "announcement",
        "atomic_facts": [],
        "uncertainties": ["时间待确认"],
    }

    brief = campus_digest_source_views.publishing_brief(source, card)
    appendix = campus_digest_source_views.source_appendix([source])

    assert brief["title"] == "校园[活动]通知"
    assert brief["stages"] == [
        {
            "stage": "announcement",
            "facts": [{"text": "学校将举办校园活动", "source_ids": ["S001"]}],
        }
    ]
    assert brief["conflicts"] == ["时间待确认"]
    assert "[校园\\[活动\\]通知](<https://example.test/content-1>)" in appendix
    assert "微信公众号 · 校团委 · 2026-08-10" in appendix
