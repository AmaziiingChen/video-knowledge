from __future__ import annotations

import pytest

from services.campus_digest_payloads import parse_event_brief, parse_fact_card, parse_json_object, split_text_in_order


CATEGORIES = ("校园活动与文体", "其他动态")
DECISIONS = {"include", "mixed", "exclude_ad"}
DOCUMENT_TYPES = {"activity", "other"}
EVENT_STAGES = {"announcement", "unknown"}


def test_fact_card_parser_normalizes_untrusted_enums_and_keeps_only_evidenced_facts():
    card = parse_fact_card(
        {
            "summary": "  校园  活动  ",
            "content_decision": "unknown",
            "category": "unknown",
            "document_type": "unknown",
            "event_stage": "unknown",
            "atomic_facts": [
                {"text": "有证据的事实", "evidence": "原文", "origin": "image_ocr"},
                {"text": "没有证据"},
            ],
        },
        categories=CATEGORIES,
        content_decisions=DECISIONS,
        document_types=DOCUMENT_TYPES,
        event_stages=EVENT_STAGES,
        include_decisions={"include", "mixed"},
    )

    assert card["summary"] == "校园 活动"
    assert card["content_decision"] == "include"
    assert card["category"] == "其他动态"
    assert card["document_type"] == "other"
    assert card["atomic_facts"] == [{
        "text": "有证据的事实",
        "evidence": "原文",
        "origin": "image_ocr",
        "locator": "",
        "ocr_only": True,
    }]


def test_event_brief_filters_unknown_source_ids_and_fenced_json_is_accepted():
    brief = parse_event_brief(
        "```json\n{\"title\":\"活动\",\"summary\":\"摘要\",\"category\":\"校园活动与文体\",\"source_ids\":[\"S01\"],\"stages\":[{\"stage\":\"通知\",\"facts\":[{\"text\":\"事实\",\"source_ids\":[\"S01\",\"S99\"]}]}]}\n```",
        categories=CATEGORIES,
    )

    assert brief["stages"] == [{"stage": "通知", "facts": [{"text": "事实", "source_ids": ["S01"]}]}]
    assert split_text_in_order("abcdef", 3) == ["abc", "def"]


def test_json_parser_rejects_non_object_responses():
    with pytest.raises(ValueError, match="JSON 对象"):
        parse_json_object("[]")
