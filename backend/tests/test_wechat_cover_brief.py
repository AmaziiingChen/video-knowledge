from __future__ import annotations

import json

import pytest
from services.wechat_cover_brief import (
    parse_visual_brief,
    stored_visual_brief,
)
from services.wechat_publishing_secrets import WeChatPublishingError


def _brief_payload() -> dict[str, object]:
    return {
        "core_theme": "图书馆夜间延时开放",
        "selection_reason": "这是本期对读者行动影响最大的安排",
        "evidence_sections": "本期概览：图书馆延长开放时间",
        "confidence": 0.92,
        "content_category": "通知政策",
        "primary_subject": "夜色中的开放阅览室",
        "scene": "温暖灯光下的阅览室保持开放",
        "rendering_style": "横版极简编辑海报",
        "mood": "安静而可靠",
        "palette": "深蓝夜色与暖黄灯光",
        "composition": "阅览室落在中央方形安全区",
    }


def test_visual_brief_parses_fenced_json_and_normalizes_input():
    payload = _brief_payload()
    payload["core_theme"] = "  图书馆  夜间延时开放  "

    brief = parse_visual_brief(f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```")

    assert brief.cover_style == "minimal_zine"
    assert brief.core_theme == "图书馆 夜间延时开放"
    assert brief.evidence_sections == ["本期概览：图书馆延长开放时间"]


def test_visual_brief_rejects_invalid_model_output_and_ignores_invalid_stored_value():
    with pytest.raises(WeChatPublishingError, match="没有返回有效"):
        parse_visual_brief("not json")

    assert stored_visual_brief({"cover_plan_json": '{"core_theme":"missing fields"}'}) == {}
