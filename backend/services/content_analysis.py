from __future__ import annotations

from dataclasses import dataclass
import json
from time import perf_counter

from services.ai_call_logger import record_ai_call
from services.campus_sources import campus_source_for_url
from services.content_source_text import load_content_source_text
from services.database import connect, initialize_database, utc_now_iso
from services.llm_provider import LLMMessage, LLMProvider, default_llm_provider
from services.markdown_sync import get_markdown_state
from services.prompt_templates import PromptTemplateRepository
from services.repository import ContentItemRecord, ContentRepository, new_id
from services.source_context import render_source_context_for_prompt
from services.source_context_prompt import active_source_context_system_prompt
from services.source_context_store import load_source_context


ANALYSIS_TASK_TYPE = "content_analysis"
CAMPUS_ANALYSIS_TASK_TYPE = "campus_source"
MAX_ANALYSIS_SOURCE_CHARS = 60_000


@dataclass(frozen=True)
class ContentAnalysisRecord:
    id: str
    content_item_id: str
    prompt_template_id: str | None
    prompt_template_name: str
    prompt_version: str
    model: str
    content: str
    created_at: str


def list_content_analyses(content_item_id: str, *, limit: int = 20) -> list[ContentAnalysisRecord]:
    initialize_database()
    with connect() as connection:
        ContentRepository(connection).get_content_item(content_item_id)
        rows = connection.execute(
            """
            SELECT * FROM content_analyses
            WHERE content_item_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (content_item_id, max(1, min(limit, 100))),
        ).fetchall()
    return [_record_from_row(row) for row in rows]


def create_content_analysis(
    content_item_id: str,
    *,
    template_id: str | None = None,
    model: str | None = None,
    provider: LLMProvider | None = None,
) -> ContentAnalysisRecord:
    """Run a reusable custom action against the selected content and save it."""
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
        templates = PromptTemplateRepository(connection)
        if template_id:
            template = templates.get_template(template_id)
        elif item.source_provider == "campus":
            source = campus_source_for_url(item.source_url or "")
            template = _campus_template_for_source(templates, source.slug if source else "")
            template = template or templates.get_active_template(ANALYSIS_TASK_TYPE)
        else:
            template = templates.get_active_template(ANALYSIS_TASK_TYPE)

    if template is None:
        raise ValueError("未找到可用的自定义按钮提示词")
    allowed_task_types = {ANALYSIS_TASK_TYPE}
    if item.source_provider == "campus":
        allowed_task_types.add(CAMPUS_ANALYSIS_TASK_TYPE)
    if template.task_type not in allowed_task_types:
        raise ValueError("所选模板不是自定义按钮提示词")
    if not template.is_active:
        raise ValueError("所选自定义按钮提示词已停用")

    material_title, material_text, material_kind = _load_analysis_material(item)
    material_text = _trim_source_text(material_text)
    context_material = render_source_context_for_prompt(load_source_context(item.id))
    user_content = (
        f"内容标题：{material_title}\n"
        f"材料类型：{_material_type_label(item.source_provider, material_kind)}\n\n"
        f"当前材料：\n{material_text}"
    )
    messages = [LLMMessage(role="system", content=template.template)]
    if context_material:
        messages.append(LLMMessage(role="system", content=active_source_context_system_prompt()))
        user_content += f"\n\n平台互动与评论辅助材料：\n{context_material}"
    messages.append(LLMMessage(role="user", content=user_content))
    input_chars = sum(len(message.content) for message in messages)
    llm = provider or default_llm_provider(model)
    started_at = perf_counter()
    try:
        response = llm.chat(messages, temperature=0.2)
    except Exception as exc:
        record_ai_call(
            call_type=ANALYSIS_TASK_TYPE,
            provider_response=None,
            input_chars=input_chars,
            elapsed_seconds=perf_counter() - started_at,
            content_item_id=content_item_id,
            error=str(exc),
        )
        raise RuntimeError(f"AI 分析调用失败：{exc}") from exc

    analysis_text = response.content.strip()
    if not analysis_text:
        raise RuntimeError("AI 未返回可保存的分析结果")
    record_ai_call(
        call_type=ANALYSIS_TASK_TYPE,
        provider_response=response,
        input_chars=input_chars,
        output_chars=len(analysis_text),
        elapsed_seconds=perf_counter() - started_at,
        content_item_id=content_item_id,
    )

    now = utc_now_iso()
    record = ContentAnalysisRecord(
        id=new_id(),
        content_item_id=content_item_id,
        prompt_template_id=template.id,
        prompt_template_name=template.name,
        prompt_version=template.version,
        model=response.model,
        content=analysis_text,
        created_at=now,
    )
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO content_analyses (
                id, content_item_id, prompt_template_id, prompt_template_name,
                prompt_version, model, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.content_item_id,
                record.prompt_template_id,
                record.prompt_template_name,
                record.prompt_version,
                record.model,
                record.content,
                record.created_at,
            ),
        )
        connection.commit()
    return record


def _load_analysis_material(item: ContentItemRecord) -> tuple[str, str, str]:
    """Resolve the best available material without requiring an original source.

    Reports are first-class documents and intentionally have no source URL. For
    ordinary articles and videos, the original source remains preferable, while
    the current Markdown document is a safe fallback when that source is not
    available locally anymore.
    """
    is_forum_capture = (
        item.source_provider == "wechat_miniprogram"
        and item.content_type in {"forum_capture", "report"}
    )
    if is_forum_capture:
        source = load_content_source_text(item.id)
        return source.title, source.text, source.source_kind

    is_report = item.source_provider == "wechat_report" or item.content_type == "report"
    if not is_report:
        try:
            source = load_content_source_text(item.id)
        except ValueError as source_error:
            return _load_markdown_material(item, fallback_error=source_error)
        return source.title, source.text, source.source_kind
    return _load_markdown_material(item, material_kind="report")


def _load_markdown_material(
    item: ContentItemRecord,
    *,
    material_kind: str = "markdown",
    fallback_error: ValueError | None = None,
) -> tuple[str, str, str]:
    try:
        markdown = get_markdown_state(item.id).markdown.strip()
    except (LookupError, OSError, ValueError):
        if fallback_error is not None:
            raise fallback_error
        raise ValueError("当前内容没有可供自定义按钮处理的文本") from None
    if not markdown:
        if fallback_error is not None:
            raise fallback_error
        raise ValueError("当前内容没有可供自定义按钮处理的文本")
    return item.title or "未命名内容", markdown, material_kind


def _campus_template_for_source(repository: PromptTemplateRepository, source_slug: str):
    for template in repository.list_templates(CAMPUS_ANALYSIS_TASK_TYPE):
        if not template.is_active:
            continue
        try:
            schema = json.loads(template.variables_schema or "{}")
        except (TypeError, ValueError):
            schema = {}
        if schema.get("source_slug") == source_slug:
            return template
    return None


def _material_type_label(source_provider: str, source_kind: str) -> str:
    if source_provider == "wechat_miniprogram" and source_kind in {"report", "forum_capture"}:
        return "微信小程序采集文档"
    if source_provider == "wechat_report" or source_kind == "report":
        return "日报或周报"
    if source_kind == "markdown":
        return "当前 Markdown 文档"
    if source_provider == "campus":
        return "校园官网或公文通文章"
    if source_provider == "wechat_miniprogram" or source_kind == "forum_post":
        return "校园匿名论坛帖子及评论"
    if source_kind == "article":
        return "微信公众号文章"
    return "视频字幕或转写"


def _trim_source_text(text: str) -> str:
    normalized = text.strip()
    if len(normalized) <= MAX_ANALYSIS_SOURCE_CHARS:
        return normalized
    head_chars = MAX_ANALYSIS_SOURCE_CHARS * 2 // 3
    tail_chars = MAX_ANALYSIS_SOURCE_CHARS - head_chars
    return (
        f"{normalized[:head_chars]}\n\n"
        f"[材料过长，已省略中间 {len(normalized) - MAX_ANALYSIS_SOURCE_CHARS} 个字符]\n\n"
        f"{normalized[-tail_chars:]}"
    )


def _record_from_row(row) -> ContentAnalysisRecord:
    return ContentAnalysisRecord(
        id=row["id"],
        content_item_id=row["content_item_id"],
        prompt_template_id=row["prompt_template_id"],
        prompt_template_name=row["prompt_template_name"],
        prompt_version=row["prompt_version"],
        model=row["model"],
        content=row["content"],
        created_at=row["created_at"],
    )
