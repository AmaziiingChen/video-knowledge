"""Cover-style, prompt and presentation contracts for WeChat publishing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from services.wechat_cover_brief import CoverVisualBrief, json_object
from services.wechat_publishing_covers import local_cover_url, validated_local_cover_path
from services.wechat_publishing_secrets import WeChatPublishingError


WECHAT_COVER_QUEUE_TASK_TYPE = "generate_wechat_cover"
COVER_STYLE_MINIMAL_ZINE = "minimal_zine"
COVER_STYLE_POETIC_ANIMATION = "poetic_animation"
COVER_STYLE_TRANSPARENT_WATERCOLOR = "transparent_watercolor"
COVER_STYLE_TWILIGHT_PAINTERLY = "twilight_painterly"
COVER_STYLE_DUOTONE_RISOGRAPH = "duotone_risograph"
COVER_STYLE_MODERN_GEOMETRIC = "modern_geometric"
COVER_STYLE_EDITORIAL_COLLECTOR = "editorial_collector"
COVER_STYLE_ORIENTAL_INK = "oriental_ink"
COVER_STYLE_LABELS = {
    COVER_STYLE_MINIMAL_ZINE: "Minimal Zine",
    COVER_STYLE_POETIC_ANIMATION: "诗意动画背景插画",
    COVER_STYLE_TRANSPARENT_WATERCOLOR: "雨幕透明水彩",
    COVER_STYLE_TWILIGHT_PAINTERLY: "暮色氛围绘画",
    COVER_STYLE_DUOTONE_RISOGRAPH: "两色孔版印刷",
    COVER_STYLE_MODERN_GEOMETRIC: "现代几何平涂",
    COVER_STYLE_EDITORIAL_COLLECTOR: "编辑型收藏海报",
    COVER_STYLE_ORIENTAL_INK: "东方水墨留白",
}
TEXT_PERMITTED_COVER_STYLES = {
    COVER_STYLE_MINIMAL_ZINE,
    COVER_STYLE_DUOTONE_RISOGRAPH,
    COVER_STYLE_EDITORIAL_COLLECTOR,
}
QWEN_ZINE_NEGATIVE_PROMPT = (
    "全幅写实场景，高分辨率图库摄影，商业广告，产品宣传，巨大商业标题，"
    "长段整齐文字，未指定文字，错误文字，乱码汉字，logo，品牌标志，CTA，"
    "水印，二维码，光泽海报样机，桌面摆拍，电影光效，硬阴影，景深虚化，"
    "3D，霓虹，干净企业矢量插画，可爱卡通，动漫，时尚大片，密集手账拼贴，"
    "多主题拼贴，过多物件，过多颜色，可辨识人物肖像，主体畸变"
)
QWEN_POETIC_ANIMATION_NEGATIVE_PROMPT = (
    "写实摄影，纪实摄影，图库摄影，3D，光泽CG，电影级写实渲染，景深虚化，"
    "真实皮肤，过度精细人脸，Q版人物，儿童绘本，可爱贴纸，粗重描边，"
    "企业矢量插画，信息图，PPT，UI，霓虹色，赛博朋克，拥挤场景，"
    "巨大标题，汉字，字母，数字，标牌，logo，品牌标志，水印，二维码，"
    "可辨识人物肖像，主体畸变"
)
QWEN_TRANSPARENT_WATERCOLOR_NEGATIVE_PROMPT = (
    "写实摄影，图库摄影，3D，光泽CG，镜头光斑，景深虚化，厚重油画，"
    "不透明厚涂，硬边矢量，粗黑描边，儿童课本插画，儿童绘本，Q版人物，"
    "可爱贴纸，企业宣传插画，信息图，PPT，霓虹色，拥挤场景，"
    "巨大标题，汉字，字母，数字，标牌，logo，品牌标志，水印，二维码，"
    "可辨识人物肖像，主体畸变"
)
QWEN_TWILIGHT_PAINTERLY_NEGATIVE_PROMPT = (
    "写实摄影，图库摄影，3D，光泽CG，镜头景深，清晰相机锐化，线稿插画，"
    "粗重描边，儿童课本插画，儿童绘本，Q版，可爱卡通，企业矢量插画，"
    "宣传合影，信息图，PPT，霓虹，赛博朋克，拥挤场景，"
    "标题，文字，数字，标牌，logo，水印，二维码，可辨识人物肖像，主体畸变"
)
QWEN_DUOTONE_RISOGRAPH_NEGATIVE_PROMPT = (
    "写实摄影，3D，光泽CG，平滑数字渐变，完美无颗粒表面，超过三种主色，"
    "彩虹配色，企业矢量插画，可爱卡通，儿童绘本，信息图，PPT，产品广告，"
    "巨大商业标题，长段文字，乱码汉字，logo，品牌标志，CTA，水印，二维码，"
    "密集拼贴，可辨识人物肖像，主体畸变"
)
QWEN_MODERN_GEOMETRIC_NEGATIVE_PROMPT = (
    "写实摄影，3D，光泽CG，复杂渐变，景深，厚重纹理，粗黑动漫描边，"
    "儿童课本插画，儿童绘本，Q版，可爱贴纸，通用企业团队插画，"
    "瑜伽健康素材插画，信息图，PPT，霓虹，密集小物件，巨大标题，"
    "文字，数字，logo，品牌标志，水印，二维码，可辨识人物肖像，主体畸变"
)
QWEN_EDITORIAL_COLLECTOR_NEGATIVE_PROMPT = (
    "写实图库摄影，商业广告，产品宣传，九宫格，信息墙，逐栏目拼贴，"
    "密集手账，PPT，信息图，3D，光泽样机，霓虹，赛博朋克，巨大商业标题，"
    "长段文字，乱码汉字，logo，品牌标志，CTA，二维码，水印，"
    "可辨识人物肖像，主体畸变"
)
QWEN_ORIENTAL_INK_NEGATIVE_PROMPT = (
    "写实摄影，3D，光泽CG，西式油画，厚重颜料，硬边矢量，粗黑动漫描边，"
    "儿童课本插画，儿童绘本，古风游戏海报，仙侠宣传图，金色奢华边框，"
    "饱和多彩背景，信息图，PPT，伪造书法，伪造印章，题字，文字，数字，"
    "logo，品牌标志，水印，二维码，可辨识人物肖像，主体畸变"
)
QWEN_COVER_NEGATIVE_PROMPTS = {
    COVER_STYLE_MINIMAL_ZINE: QWEN_ZINE_NEGATIVE_PROMPT,
    COVER_STYLE_POETIC_ANIMATION: QWEN_POETIC_ANIMATION_NEGATIVE_PROMPT,
    COVER_STYLE_TRANSPARENT_WATERCOLOR: QWEN_TRANSPARENT_WATERCOLOR_NEGATIVE_PROMPT,
    COVER_STYLE_TWILIGHT_PAINTERLY: QWEN_TWILIGHT_PAINTERLY_NEGATIVE_PROMPT,
    COVER_STYLE_DUOTONE_RISOGRAPH: QWEN_DUOTONE_RISOGRAPH_NEGATIVE_PROMPT,
    COVER_STYLE_MODERN_GEOMETRIC: QWEN_MODERN_GEOMETRIC_NEGATIVE_PROMPT,
    COVER_STYLE_EDITORIAL_COLLECTOR: QWEN_EDITORIAL_COLLECTOR_NEGATIVE_PROMPT,
    COVER_STYLE_ORIENTAL_INK: QWEN_ORIENTAL_INK_NEGATIVE_PROMPT,
}
_COVER_STYLE_BLOCK = re.compile(
    r"\[\[STYLE:([a-z_]+)\]\](.*?)\[\[/STYLE\]\]",
    re.DOTALL,
)


def cover_version_payload(
    row: dict[str, Any],
    *,
    current_path: str,
) -> dict[str, Any] | None:
    try:
        path = validated_local_cover_path(str(row.get("cover_path") or ""))
    except WeChatPublishingError:
        return None
    content_hash = str(row.get("content_hash") or "").strip()
    version = content_hash or str(row.get("id") or "")
    brief = json_object(row.get("visual_brief_json"))
    metadata = json_object(row.get("prompt_metadata_json"))
    style = str(
        brief.get("cover_style")
        or metadata.get("cover_style")
        or COVER_STYLE_MINIMAL_ZINE
    )
    try:
        normalized_current = Path(current_path).expanduser().resolve() if current_path else None
    except OSError:
        normalized_current = None
    return {
        "id": str(row.get("id") or ""),
        "url": local_cover_url(path, version=version[:12]),
        "selected": bool(normalized_current and path == normalized_current),
        "created_at": str(row.get("created_at") or ""),
        "cover_style": style,
        "cover_style_label": COVER_STYLE_LABELS.get(style, style),
    }


def resolve_required_prompt_inputs(
    template: str,
    inputs: dict[str, tuple[str, str]],
) -> str:
    """Resolve managed variables and retain required runtime inputs if removed."""
    source = str(template or "")
    resolved = source
    missing: list[tuple[str, str]] = []
    for variable, (label, value) in inputs.items():
        if variable in source:
            resolved = resolved.replace(variable, value)
        else:
            missing.append((label, value))
    if missing:
        fallback = "\n\n".join(f"{label}：\n{value}" for label, value in missing)
        resolved = f"{resolved.rstrip()}\n\n运行时必要输入：\n{fallback}"
    return resolved.strip()


def image_visual_brief(visual_brief: CoverVisualBrief) -> str:
    """Keep editorial reasoning out of the image model's attention budget."""
    def line(label: str, value: str) -> str | None:
        cleaned = " ".join(str(value or "").split())
        return f"{label}：{cleaned}" if cleaned else None

    visual_elements = [
        item
        for item in visual_brief.supporting_elements
        if not str(item).strip().startswith("微型排字：")
    ]
    lines = [
        line("唯一主题", visual_brief.core_theme),
        line("主视觉主体", visual_brief.primary_subject),
        line("场景与动作", visual_brief.scene),
        line("视觉隐喻", visual_brief.visual_metaphor),
        line("辅助视觉元素", "；".join(visual_elements)),
        line("表现媒介", visual_brief.rendering_style),
        line("画面情绪", visual_brief.mood),
        line("色彩", visual_brief.palette),
        line("横版构图", visual_brief.composition),
        line("避免", "；".join(visual_brief.must_avoid)),
    ]
    microcopy = visual_brief.decorative_microcopy
    if microcopy and visual_brief.cover_style in TEXT_PERMITTED_COVER_STYLES:
        lines.append(f"允许的唯一装饰微文案：{microcopy}")
    else:
        lines.append("允许的唯一装饰微文案：无")
    return "\n".join(item for item in lines if item)


def normalize_cover_style(value: Any) -> str:
    style = str(value or COVER_STYLE_MINIMAL_ZINE).strip()
    if style not in COVER_STYLE_LABELS:
        raise WeChatPublishingError("不支持的公众号封面风格")
    return style


def select_cover_style_block(template: str, cover_style: str) -> str:
    """Keep common prompt text and only the explicitly selected style block."""
    style = normalize_cover_style(cover_style)
    source = str(template or "")
    matches = list(_COVER_STYLE_BLOCK.finditer(source))
    if not matches:
        # Custom prompts created before style presets remain usable. The
        # selected key is still available through the managed variable.
        return source
    available = {match.group(1) for match in matches}
    if style not in available:
        raise WeChatPublishingError(f"当前提示词缺少“{COVER_STYLE_LABELS[style]}”风格区块")
    return _COVER_STYLE_BLOCK.sub(
        lambda match: match.group(2).strip() if match.group(1) == style else "",
        source,
    )


def cover_negative_prompt(cover_style: str) -> str:
    return QWEN_COVER_NEGATIVE_PROMPTS[normalize_cover_style(cover_style)]


def cover_task_dict(task: Any) -> dict[str, Any]:
    result = getattr(task, "result", None)
    return {
        "task_id": str(task.task_id),
        "task_type": str(getattr(task, "task_type", WECHAT_COVER_QUEUE_TASK_TYPE)),
        "content_item_id": str(task.content_item_id or ""),
        "status": str(task.status),
        "step": str(getattr(result, "step", "") or ""),
        "error": str(getattr(result, "error", "") or ""),
    }


def report_type_label(report_type: str) -> str:
    return {"daily": "日报", "weekly": "周报", "range": "专题汇总"}.get(report_type, "报告")
