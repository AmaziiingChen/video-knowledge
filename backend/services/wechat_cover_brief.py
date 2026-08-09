from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from services.wechat_publishing_secrets import WeChatPublishingError

DEFAULT_COVER_STYLE = "minimal_zine"


class CoverVisualBrief(BaseModel):
    """The editable contract between editorial planning and image generation."""

    model_config = ConfigDict(extra="ignore")

    cover_style: Literal[
        "minimal_zine",
        "poetic_animation",
        "transparent_watercolor",
        "twilight_painterly",
        "duotone_risograph",
        "modern_geometric",
        "editorial_collector",
        "oriental_ink",
    ] = DEFAULT_COVER_STYLE
    core_theme: str = Field(min_length=2, max_length=160)
    selection_reason: str = Field(min_length=2, max_length=500)
    evidence_sections: list[str] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0, le=1)
    content_category: str = Field(min_length=1, max_length=80)
    primary_subject: str = Field(min_length=2, max_length=240)
    scene: str = Field(min_length=2, max_length=400)
    visual_metaphor: str = Field(default="", max_length=240)
    decorative_microcopy: str = Field(default="", max_length=28)
    rendering_style: str = Field(min_length=2, max_length=240)
    mood: str = Field(min_length=1, max_length=160)
    palette: str = Field(min_length=1, max_length=240)
    composition: str = Field(min_length=2, max_length=400)
    supporting_elements: list[str] = Field(default_factory=list, max_length=2)
    factual_constraints: list[str] = Field(default_factory=list, max_length=8)
    must_avoid: list[str] = Field(default_factory=list, max_length=12)

    @field_validator(
        "core_theme",
        "selection_reason",
        "content_category",
        "primary_subject",
        "scene",
        "visual_metaphor",
        "decorative_microcopy",
        "rendering_style",
        "mood",
        "palette",
        "composition",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())

    @field_validator(
        "evidence_sections",
        "supporting_elements",
        "factual_constraints",
        "must_avoid",
        mode="before",
    )
    @classmethod
    def _clean_string_list(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [line for line in value.splitlines() if line.strip()]
        if not isinstance(value, list):
            return []
        return [" ".join(str(item).split()) for item in value if str(item).strip()]


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def stored_visual_brief(report: dict[str, Any]) -> dict[str, Any]:
    value = json_object(report.get("cover_plan_json"))
    if not value:
        return {}
    try:
        return CoverVisualBrief.model_validate(value).model_dump()
    except ValidationError:
        return {}


def parse_visual_brief(value: Any) -> CoverVisualBrief:
    if isinstance(value, CoverVisualBrief):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```")
            text = text.rsplit("```", 1)[0].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise WeChatPublishingError("文本模型没有返回有效的封面视觉策划")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise WeChatPublishingError("文本模型返回的封面视觉策划不是合法 JSON") from exc
    try:
        return CoverVisualBrief.model_validate(value)
    except ValidationError as exc:
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in exc.errors()})
        detail = "、".join(fields[:5])
        raise WeChatPublishingError(f"封面视觉策划字段不完整：{detail}") from exc
