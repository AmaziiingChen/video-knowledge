from types import SimpleNamespace

import pytest

from services.wechat_cover_brief import CoverVisualBrief
from services.wechat_publishing_cover_policy import (
    COVER_STYLE_POETIC_ANIMATION,
    COVER_STYLE_MINIMAL_ZINE,
    cover_task_dict,
    image_visual_brief,
    resolve_required_prompt_inputs,
    select_cover_style_block,
)
from services.wechat_publishing_secrets import WeChatPublishingError


def _brief(*, cover_style: str = COVER_STYLE_MINIMAL_ZINE) -> CoverVisualBrief:
    return CoverVisualBrief.model_validate(
        {
            "cover_style": cover_style,
            "core_theme": "校园创新",
            "selection_reason": "主题契合资料内容",
            "evidence_sections": ["创新实践"],
            "confidence": 0.9,
            "content_category": "校园新闻",
            "primary_subject": "实验室里的学生团队",
            "scene": "午后实验室协作讨论",
            "visual_metaphor": "向上延展的纸页",
            "decorative_microcopy": "创新周报",
            "rendering_style": "编辑插画",
            "mood": "克制明亮",
            "palette": "蓝绿与暖白",
            "composition": "横版留白构图",
            "supporting_elements": ["微型排字：不应进入模型", "笔记与光点"],
            "must_avoid": ["可识别人像"],
        }
    )


def test_style_selection_keeps_only_the_selected_prompt_contract():
    template = "通用说明\n[[STYLE:minimal_zine]]杂志规则[[/STYLE]]\n[[STYLE:poetic_animation]]动画规则[[/STYLE]]"

    resolved = select_cover_style_block(template, COVER_STYLE_POETIC_ANIMATION)

    assert "通用说明" in resolved
    assert "动画规则" in resolved
    assert "杂志规则" not in resolved


def test_style_selection_rejects_a_missing_selected_style_block():
    with pytest.raises(WeChatPublishingError, match="缺少"):
        select_cover_style_block("[[STYLE:minimal_zine]]杂志规则[[/STYLE]]", COVER_STYLE_POETIC_ANIMATION)


def test_prompt_inputs_are_retained_when_a_custom_template_drops_required_variables():
    value = resolve_required_prompt_inputs(
        "主题：{title}",
        {
            "{title}": ("标题", "校园创新"),
            "{visual_brief}": ("视觉执行简报", "保留留白"),
        },
    )

    assert value.startswith("主题：校园创新")
    assert "运行时必要输入" in value
    assert "视觉执行简报：\n保留留白" in value


def test_image_brief_allows_microcopy_only_for_text_permitted_style_and_excludes_editorial_noise():
    permitted = image_visual_brief(_brief())
    restricted = image_visual_brief(_brief(cover_style=COVER_STYLE_POETIC_ANIMATION))

    assert "允许的唯一装饰微文案：创新周报" in permitted
    assert "允许的唯一装饰微文案：无" in restricted
    assert "微型排字：不应进入模型" not in permitted


def test_cover_task_presentation_retains_the_existing_queue_contract():
    task = SimpleNamespace(
        task_id="task-1",
        task_type="generate_wechat_cover",
        content_item_id="content-1",
        status="running",
        result=SimpleNamespace(step="生成图片", error=""),
    )

    assert cover_task_dict(task) == {
        "task_id": "task-1",
        "task_type": "generate_wechat_cover",
        "content_item_id": "content-1",
        "status": "running",
        "step": "生成图片",
        "error": "",
    }
