import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from config import settings

from services.ai_call_logger import AICallRecord, record_ai_call
from services.ai_response_envelope import (
    FOLLOWUP_RESPONSE_CONTRACT,
    AIResponseEnvelope,
    AIResponseStreamEvent,
    SuggestionTrailerParser,
)
from services.database import connect, initialize_database
from services.llm_provider import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
    default_llm_provider,
)
from services.prompt_file_store import sync_prompt_files
from services.pipeline_contracts import MAX_REASONING_CONTENT_CHARS, PipelineCancelled
from services.prompt_templates import (
    DEFAULT_ARTICLE_MATERIAL_REDUCTION_PROMPT,
    DEFAULT_ARTICLE_SUMMARY_PROMPT,
    DEFAULT_QA_PROMPT,
    DEFAULT_SUMMARY_PROMPT,
    PromptTemplateRepository,
)
from services.source_context import (
    render_source_context_for_prompt,
    render_source_context_markdown,
)
from services.source_context_prompt import active_source_context_system_prompt
from services.video_timestamps import (
    normalize_video_summary_timestamps,
    timestamped_video_transcript,
)

SYSTEM_PROMPT = DEFAULT_SUMMARY_PROMPT
ARTICLE_SYSTEM_PROMPT = DEFAULT_ARTICLE_SUMMARY_PROMPT
QA_SYSTEM_PROMPT = DEFAULT_QA_PROMPT

MAX_QA_TRANSCRIPT_CHARS = 60000
MAX_REGENERATION_DIRECT_SOURCE_CHARS = 54_000
MAX_REGENERATION_CHUNK_SOURCE_CHARS = 36_000
MAX_REGENERATION_FINAL_MATERIAL_CHARS = 54_000


@dataclass(frozen=True)
class SummaryStreamEvent:
    kind: str
    title: str = ""
    summary: str = ""
    reasoning_content: str = ""
    reasoning_truncated: bool = False


def _stream_provider_events(llm: LLMProvider, messages: list[LLMMessage], *, temperature: float) -> Iterator[LLMStreamChunk]:
    stream_events = getattr(llm, "chat_stream_events", None)
    if callable(stream_events):
        yield from stream_events(messages, temperature=temperature)
        return
    usage: LLMUsage | None = None

    def remember(value: LLMUsage) -> None:
        nonlocal usage
        usage = value

    for text in llm.chat_stream(messages, temperature=temperature, on_usage=remember):
        yield LLMStreamChunk(content=text)
    if usage:
        yield LLMStreamChunk(usage=usage)

# Re-generation is intentionally separate from ordinary QA. The normal QA
# path keeps a short, responsive context; this path must account for every
# paragraph, OCR annotation, or subtitle segment in a long source.
def get_active_system_prompt(task_type: str) -> str:
    fallback_prompts = {
        "article_material_reduction": DEFAULT_ARTICLE_MATERIAL_REDUCTION_PROMPT,
        "article_summary": ARTICLE_SYSTEM_PROMPT,
        "qa": QA_SYSTEM_PROMPT,
        "summary": SYSTEM_PROMPT,
    }
    fallback = fallback_prompts.get(task_type, SYSTEM_PROMPT)
    try:
        initialize_database()
        with connect() as connection:
            sync_prompt_files(connection)
            connection.commit()
            template = PromptTemplateRepository(connection).get_active_template(task_type)
            return template.template if template else fallback
    except Exception:
        return fallback

def summarize(
    transcript: str,
    video_title: str = "",
    provider: LLMProvider | None = None,
    model: str | None = None,
    task_type: str = "summary",
    task_id: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    transcript_segments: list[dict] | None = None,
    source_context: dict[str, object] | None = None,
) -> tuple[str, str]:
    """返回 (title, summary)"""
    should_record = provider is None or ai_call_callback is not None
    llm = provider or default_llm_provider(model)
    normalized_task_type = task_type if task_type in {"summary", "article_summary"} else "summary"
    system_prompt = get_active_system_prompt(normalized_task_type)
    timestamp_seconds: set[int] = set()
    if normalized_task_type == "article_summary":
        material = prepare_article_summary_material(
            transcript,
            llm=llm,
            task_id=task_id,
            content_item_id=content_item_id,
            ai_call_callback=ai_call_callback,
            preparation_call_type="article_summary_prepare",
        )
        user_content = f"文章标题：{video_title}\n\n正文文本：\n{material}"
    else:
        material, timestamp_seconds = timestamped_video_transcript(transcript, transcript_segments)
        timestamp_guidance = ""
        if timestamp_seconds:
            timestamp_guidance = (
                "\n\n转写中的时间链接对应可回看的原始片段。仅在最关键的 3–8 个观点、"
                "案例、转折或结论旁保留这些链接；必须逐字复制材料中已有的链接，"
                "不得编造、估算或改写时间。没有必要时可以少于 3 个。"
            )
        user_content = f"视频标题：{video_title}\n\n转写文本：\n{material}{timestamp_guidance}"
    context_material = render_source_context_for_prompt(source_context)
    if context_material:
        user_content += f"\n\n{context_material}"
    messages = [LLMMessage(role="system", content=system_prompt)]
    if context_material:
        messages.append(LLMMessage(role="system", content=active_source_context_system_prompt()))
    messages.append(LLMMessage(role="user", content=user_content))
    input_chars = sum(len(message.content) for message in messages)
    started_at = time.perf_counter()
    
    try:
        response = llm.chat(
            messages,
            temperature=0.3,
        )
        content = response.content.strip()
        
        if normalized_task_type == "article_summary":
            # Article titles are source metadata. Do not let a generative
            # first line replace the original title or discard its content.
            title = video_title or "未命名文章"
            summary = content
        else:
            lines = content.split("\n")
            title = lines[0].strip().strip("#").strip()
            summary = normalize_video_summary_timestamps("\n".join(lines[1:]).strip(), timestamp_seconds)
            if not title or len(title) > 30:
                title = video_title or "未命名视频"

        if should_record:
            record = record_ai_call(
                call_type="summary",
                provider_response=response,
                input_chars=input_chars,
                output_chars=len(response.content),
                elapsed_seconds=time.perf_counter() - started_at,
                task_id=task_id,
                content_item_id=content_item_id,
            )
            if record and ai_call_callback:
                ai_call_callback(record)
        
        return title, summary
    except Exception as e:
        if should_record:
            record_ai_call(
                call_type="summary",
                provider_response=None,
                input_chars=input_chars,
                elapsed_seconds=time.perf_counter() - started_at,
                task_id=task_id,
                content_item_id=content_item_id,
                error=str(e),
            )
        raise Exception(f"文本模型 API 调用失败: {str(e)}")


def summarize_stream(
    transcript: str,
    video_title: str = "",
    provider: LLMProvider | None = None,
    model: str | None = None,
    task_type: str = "summary",
    task_id: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    transcript_segments: list[dict] | None = None,
    source_context: dict[str, object] | None = None,
    on_delta: Callable[[str, str], None] | None = None,
    on_reasoning_delta: Callable[[str, bool], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> tuple[str, str]:
    """Generate a summary while exposing safe, renderable partial text.

    The background pipeline persists these snapshots for the desktop client.
    ``on_delta`` receives the same title/body split as the final result, so a
    video title line is never rendered as part of the growing summary body.
    """
    title = video_title
    summary = ""
    for event in summarize_stream_events(
        transcript,
        video_title,
        provider=provider,
        model=model,
        task_type=task_type,
        task_id=task_id,
        content_item_id=content_item_id,
        ai_call_callback=ai_call_callback,
        transcript_segments=transcript_segments,
        source_context=source_context,
        cancel_check=cancel_check,
    ):
        if event.kind == "reasoning_delta":
            if on_reasoning_delta:
                on_reasoning_delta(event.reasoning_content, event.reasoning_truncated)
            continue
        if event.kind in {"summary_delta", "done"}:
            title = event.title
            summary = event.summary
            if event.kind == "summary_delta" and on_delta:
                on_delta(title, summary)
    return title, summary


def summarize_stream_events(
    transcript: str,
    video_title: str = "",
    provider: LLMProvider | None = None,
    model: str | None = None,
    task_type: str = "summary",
    task_id: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    transcript_segments: list[dict] | None = None,
    source_context: dict[str, object] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> Iterator[SummaryStreamEvent]:
    """Stream one automatic summary without mixing provider reasoning into its body."""
    should_record = provider is None or ai_call_callback is not None
    llm = provider or default_llm_provider(model)
    normalized_task_type = task_type if task_type in {"summary", "article_summary"} else "summary"
    system_prompt = get_active_system_prompt(normalized_task_type)
    timestamp_seconds: set[int] = set()
    if normalized_task_type == "article_summary":
        material = prepare_article_summary_material(
            transcript,
            llm=llm,
            task_id=task_id,
            content_item_id=content_item_id,
            ai_call_callback=ai_call_callback,
            preparation_call_type="article_summary_prepare",
        )
        user_content = f"文章标题：{video_title}\n\n正文文本：\n{material}"
    else:
        material, timestamp_seconds = timestamped_video_transcript(transcript, transcript_segments)
        timestamp_guidance = ""
        if timestamp_seconds:
            timestamp_guidance = (
                "\n\n转写中的时间链接对应可回看的原始片段。仅在最关键的 3–8 个观点、"
                "案例、转折或结论旁保留这些链接；必须逐字复制材料中已有的链接，"
                "不得编造、估算或改写时间。没有必要时可以少于 3 个。"
            )
        user_content = f"视频标题：{video_title}\n\n转写文本：\n{material}{timestamp_guidance}"
    context_material = render_source_context_for_prompt(source_context)
    if context_material:
        user_content += f"\n\n{context_material}"
    messages = [LLMMessage(role="system", content=system_prompt)]
    if context_material:
        messages.append(LLMMessage(role="system", content=active_source_context_system_prompt()))
    messages.append(LLMMessage(role="user", content=user_content))
    input_chars = sum(len(message.content) for message in messages)
    started_at = time.perf_counter()
    chunks: list[str] = []
    reasoning_parts: list[str] = []
    reasoning_chars = 0
    visible_reasoning_chars = 0
    reasoning_truncated = False
    stream_usage: LLMUsage | None = None

    def split_summary(raw: str) -> tuple[str, str]:
        content = raw.strip()
        if normalized_task_type == "article_summary":
            return video_title or "未命名文章", content
        lines = content.split("\n")
        title = lines[0].strip().strip("#").strip() if lines else ""
        summary = normalize_video_summary_timestamps("\n".join(lines[1:]).strip(), timestamp_seconds)
        if not title or len(title) > 30:
            title = video_title or "未命名视频"
        return title, summary

    try:
        for chunk in _stream_provider_events(llm, messages, temperature=0.3):
            if cancel_check:
                cancel_check()
            if chunk.usage:
                stream_usage = chunk.usage
            if chunk.reasoning_content:
                reasoning_chars += len(chunk.reasoning_content)
                remaining = MAX_REASONING_CONTENT_CHARS - visible_reasoning_chars
                if remaining > 0:
                    visible_chunk = chunk.reasoning_content[:remaining]
                    reasoning_parts.append(visible_chunk)
                    visible_reasoning_chars += len(visible_chunk)
                reasoning_truncated = reasoning_chars > MAX_REASONING_CONTENT_CHARS
                yield SummaryStreamEvent(
                    kind="reasoning_delta",
                    reasoning_content="".join(reasoning_parts),
                    reasoning_truncated=reasoning_truncated,
                )
            if chunk.content:
                chunks.append(chunk.content)
                title, partial_summary = split_summary("".join(chunks))
                yield SummaryStreamEvent(
                    kind="summary_delta",
                    title=title,
                    summary=partial_summary,
                )

        raw_content = "".join(chunks)
        visible_reasoning = "".join(reasoning_parts)
        title, summary = split_summary(raw_content)
        if should_record:
            provider_response = LLMResponse(
                content=raw_content,
                provider=llm.name,
                model=llm.model,
                usage=stream_usage,
                reasoning_content=visible_reasoning,
            )
            record = record_ai_call(
                call_type="summary",
                provider_response=provider_response,
                input_chars=input_chars,
                output_chars=len(raw_content) + reasoning_chars,
                elapsed_seconds=time.perf_counter() - started_at,
                task_id=task_id,
                content_item_id=content_item_id,
            )
            if record and ai_call_callback:
                ai_call_callback(record)
        yield SummaryStreamEvent(
            kind="done",
            title=title,
            summary=summary,
            reasoning_content=visible_reasoning,
            reasoning_truncated=reasoning_truncated,
        )
    except PipelineCancelled:
        raise
    except Exception as exc:
        if should_record:
            record_ai_call(
                call_type="summary",
                provider_response=None,
                input_chars=input_chars,
                elapsed_seconds=time.perf_counter() - started_at,
                task_id=task_id,
                content_item_id=content_item_id,
                error=str(exc),
            )
        raise Exception(f"文本模型 API 调用失败: {str(exc)}") from exc


def _trim_transcript_for_qa(transcript: str) -> str:
    if len(transcript) <= MAX_QA_TRANSCRIPT_CHARS:
        return transcript
    head = transcript[: MAX_QA_TRANSCRIPT_CHARS // 2]
    tail = transcript[-MAX_QA_TRANSCRIPT_CHARS // 2 :]
    return (
        f"{head}\n\n"
        "[中间部分因上下文过长被省略；如果问题依赖省略部分，请说明当前材料不足。]\n\n"
        f"{tail}"
    )


def stream_regenerated_content_summary(
    transcript: str,
    video_title: str = "",
    content_kind: str = "article",
    provider: LLMProvider | None = None,
    model: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    transcript_segments: list[dict] | None = None,
    source_context: dict[str, object] | None = None,
) -> Iterator[str]:
    """Stream a fresh article, video, or audio summary from the whole source."""
    for event in stream_regenerated_content_summary_events(
        transcript=transcript,
        video_title=video_title,
        content_kind=content_kind,
        provider=provider,
        model=model,
        content_item_id=content_item_id,
        ai_call_callback=ai_call_callback,
        transcript_segments=transcript_segments,
        source_context=source_context,
    ):
        if event.kind == "answer_delta":
            yield event.text


def stream_regenerated_content_summary_events(
    transcript: str,
    video_title: str = "",
    content_kind: str = "article",
    provider: LLMProvider | None = None,
    model: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    transcript_segments: list[dict] | None = None,
    source_context: dict[str, object] | None = None,
) -> Iterator[AIResponseStreamEvent]:
    """Stream a fresh summary with reasoning and follow-up metadata separated."""
    source_text = str(transcript or "").strip()
    if not source_text:
        raise ValueError("缺少可重新总结的正文、字幕或转写文本")

    normalized_kind = content_kind if content_kind in {"video", "audio"} else "article"

    llm = provider or default_llm_provider(model)
    timestamp_seconds: set[int] = set()
    if normalized_kind in {"video", "audio"}:
        source_text, timestamp_seconds = timestamped_video_transcript(source_text, transcript_segments)

    if len(source_text) <= MAX_REGENERATION_DIRECT_SOURCE_CHARS:
        final_material = source_text
    else:
        final_material = prepare_article_summary_material(
            source_text,
            llm=llm,
            task_id=None,
            content_item_id=content_item_id,
            ai_call_callback=ai_call_callback,
            preparation_call_type="article_regeneration_prepare",
        )

    messages = _build_regeneration_messages(
        video_title,
        final_material,
        normalized_kind,
        has_timestamps=bool(timestamp_seconds),
        source_context=source_context,
    )
    input_chars = sum(len(message.content) for message in messages)
    started_at = time.perf_counter()
    chunks: list[str] = []
    reasoning_chunks: list[str] = []
    stream_usage: LLMUsage | None = None

    def remember_usage(usage: LLMUsage) -> None:
        nonlocal stream_usage
        stream_usage = usage

    try:
        parser = SuggestionTrailerParser()
        visible_chars = 0
        for chunk in _stream_provider_events(llm, messages, temperature=0.25):
            if chunk.usage:
                remember_usage(chunk.usage)
            if chunk.reasoning_content:
                reasoning_chunks.append(chunk.reasoning_content)
                yield AIResponseStreamEvent(kind="reasoning_delta", text=chunk.reasoning_content)
            if chunk.content:
                chunks.append(chunk.content)
                visible = parser.feed(chunk.content)
                if visible:
                    visible_chars += len(visible)
                    yield AIResponseStreamEvent(kind="answer_delta", text=visible)
        envelope = parser.finish()
        if len(envelope.answer) > visible_chars:
            yield AIResponseStreamEvent(kind="answer_delta", text=envelope.answer[visible_chars:])
        envelope = type(envelope)(
            answer=envelope.answer,
            reasoning_content="".join(reasoning_chunks),
            suggested_questions=envelope.suggested_questions,
        )
        provider_response = LLMResponse(
            content="",
            provider=llm.name,
            model=llm.model,
            usage=stream_usage,
            reasoning_content=envelope.reasoning_content,
        ) if stream_usage else None
        record = record_ai_call(
            call_type="article_regeneration",
            provider_response=provider_response,
            input_chars=input_chars,
            output_chars=len("".join(chunks)) + len(envelope.reasoning_content),
            elapsed_seconds=time.perf_counter() - started_at,
            content_item_id=content_item_id,
        )
        if record and ai_call_callback:
            ai_call_callback(record)
        yield AIResponseStreamEvent(kind="done", envelope=envelope)
    except Exception as exc:
        error_message = str(exc)
        if "timed out" in error_message.lower() or "timeout" in error_message.lower():
            error_message = "AI 服务在 90 秒内没有返回内容，请稍后重试"
        record_ai_call(
            call_type="article_regeneration",
            provider_response=None,
            input_chars=input_chars,
            elapsed_seconds=time.perf_counter() - started_at,
            content_item_id=content_item_id,
            error=error_message,
        )
        raise Exception(f"文本模型 API 调用失败: {error_message}") from exc


def stream_regenerated_article_summary(
    transcript: str,
    video_title: str = "",
    provider: LLMProvider | None = None,
    model: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
) -> Iterator[str]:
    """Compatibility wrapper for article-only callers."""
    yield from stream_regenerated_content_summary(
        transcript=transcript,
        video_title=video_title,
        content_kind="article",
        provider=provider,
        model=model,
        content_item_id=content_item_id,
        ai_call_callback=ai_call_callback,
    )


def _build_regeneration_messages(
    title: str,
    material: str,
    content_kind: str,
    *,
    has_timestamps: bool = False,
    source_context: dict[str, object] | None = None,
) -> list[LLMMessage]:
    context_material = render_source_context_for_prompt(source_context)
    if content_kind in {"video", "audio"}:
        media_label = "视频" if content_kind == "video" else "音频"
        fallback_title = "未命名视频" if content_kind == "video" else "未命名音频"
        transcript_label = "完整字幕或转写材料" if content_kind == "video" else "完整转写材料"
        messages = [
            LLMMessage(role="system", content=get_active_system_prompt("summary")),
            LLMMessage(
                role="user",
                content=(
                    f"{media_label}标题：{title or fallback_title}\n\n"
                    f"以下为按时间顺序整理的{transcript_label}。请基于全部材料重新生成完整总结。"
                    + ("仅在关键节点旁复制材料已有的时间链接，不得编造时间。" if has_timestamps else "")
                    + "\n\n"
                    f"转写文本：\n{material}"
                ),
            ),
        ]
    else:
        messages = [
            LLMMessage(role="system", content=get_active_system_prompt("article_summary")),
            LLMMessage(
                role="user",
                content=(
                    f"文章标题：{title or '未命名公众号文章'}\n\n"
                    "以下为按原文出现顺序整理的完整材料；其中“[图片文字 N]”是对应图片的 OCR 结果，"
                    "必须与相邻段落一起理解。请基于全部材料重新生成完整总结。\n\n"
                    f"正文文本：\n{material}"
                ),
            ),
        ]
    if context_material:
        messages.insert(1, LLMMessage(role="system", content=active_source_context_system_prompt()))
        # LLMMessage is deliberately immutable so callers cannot alter a
        # prompt after it has been handed to a provider.  Build the enriched
        # user message instead of assigning to ``content`` in place.
        source_message = messages[-1]
        messages[-1] = LLMMessage(
            role=source_message.role,
            content=f"{source_message.content}\n\n{context_material}",
        )
    messages.insert(1, LLMMessage(role="system", content=FOLLOWUP_RESPONSE_CONTRACT))
    return messages


def prepare_article_summary_material(
    source_text: str,
    *,
    llm: LLMProvider,
    task_id: str | None,
    content_item_id: str | None,
    ai_call_callback: Callable[[AICallRecord], None] | None,
    preparation_call_type: str,
) -> str:
    """Return source text directly or compact oversized material in source order."""
    if len(source_text) <= MAX_REGENERATION_DIRECT_SOURCE_CHARS:
        return source_text
    chunks = _split_text_in_order(source_text, MAX_REGENERATION_CHUNK_SOURCE_CHARS)
    extracts = [
        _reduce_article_material(
            chunk,
            llm=llm,
            task_id=task_id,
            content_item_id=content_item_id,
            ai_call_callback=ai_call_callback,
            call_type=preparation_call_type,
            label=f"原文第 {index} / {len(chunks)} 段",
        )
        for index, chunk in enumerate(chunks, start=1)
    ]

    # A very long article can still produce too many extracts for the final
    # context. Re-compress in consecutive batches, never reordering source.
    reduction_rounds = 0
    while len("\n\n".join(extracts)) > MAX_REGENERATION_FINAL_MATERIAL_CHARS:
        reduction_rounds += 1
        if reduction_rounds > 6:
            raise ValueError("全文材料过长且分段整理未能收敛，请改用更大上下文模型后重试")
        batches = _pack_text_batches(extracts, MAX_REGENERATION_CHUNK_SOURCE_CHARS)
        if len(batches) == 1:
            # The reduction prompt asks for a compact output. This guard makes
            # progress even if a provider returns an unexpectedly verbose reply.
            batches = _split_text_in_order(batches[0], MAX_REGENERATION_CHUNK_SOURCE_CHARS // 2)
        extracts = [
            _reduce_article_material(
                batch,
                llm=llm,
                task_id=task_id,
                content_item_id=content_item_id,
                ai_call_callback=ai_call_callback,
                call_type=preparation_call_type,
                label=f"顺序材料汇总第 {index} / {len(batches)} 段",
            )
            for index, batch in enumerate(batches, start=1)
        ]
    return "\n\n".join(extracts).strip()


def _split_text_in_order(text: str, limit: int) -> list[str]:
    """Split only by forward traversal so paragraph/OCR order remains stable."""
    normalized = str(text or "").strip()
    if not normalized:
        return []
    pieces: list[str] = []
    current = ""
    for line in normalized.splitlines(keepends=True):
        remaining = line
        while remaining:
            space = limit - len(current)
            if space <= 0:
                pieces.append(current.strip())
                current = ""
                space = limit
            if len(remaining) <= space:
                current += remaining
                remaining = ""
            else:
                current += remaining[:space]
                remaining = remaining[space:]
                pieces.append(current.strip())
                current = ""
    if current.strip():
        pieces.append(current.strip())
    return [piece for piece in pieces if piece]


def _pack_text_batches(parts: list[str], limit: int) -> list[str]:
    batches: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n\n{part}".strip() if current else part
        if current and len(candidate) > limit:
            batches.append(current)
            current = part
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def _reduce_article_material(
    material: str,
    *,
    llm: LLMProvider,
    task_id: str | None,
    content_item_id: str | None,
    ai_call_callback: Callable[[AICallRecord], None] | None,
    label: str,
    call_type: str,
) -> str:
    messages = [
        LLMMessage(role="system", content=get_active_system_prompt("article_material_reduction")),
        LLMMessage(role="user", content=f"{label}：\n\n{material}"),
    ]
    input_chars = sum(len(message.content) for message in messages)
    started_at = time.perf_counter()
    try:
        response = llm.chat(messages, temperature=0.1)
    except Exception as exc:
        record_ai_call(
            call_type=call_type,
            provider_response=None,
            input_chars=input_chars,
            elapsed_seconds=time.perf_counter() - started_at,
            task_id=task_id,
            content_item_id=content_item_id,
            error=str(exc),
        )
        raise Exception(f"全文材料整理失败: {str(exc)}") from exc

    extracted = response.content.strip()
    if not extracted:
        raise ValueError("全文材料整理未返回内容")
    record = record_ai_call(
        call_type=call_type,
        provider_response=response,
        input_chars=input_chars,
        output_chars=len(extracted),
        elapsed_seconds=time.perf_counter() - started_at,
        task_id=task_id,
        content_item_id=content_item_id,
    )
    if record and ai_call_callback:
        ai_call_callback(record)
    return extracted


def answer_question(
    question: str,
    summary: str,
    transcript: str,
    video_title: str = "",
    history: list[dict] | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    task_id: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    source_context: dict[str, object] | None = None,
) -> str:
    return answer_question_envelope(
        question=question, summary=summary, transcript=transcript,
        video_title=video_title, history=history, provider=provider, model=model,
        task_id=task_id, content_item_id=content_item_id,
        ai_call_callback=ai_call_callback, source_context=source_context,
    ).answer


def answer_question_envelope(
    question: str,
    summary: str,
    transcript: str,
    video_title: str = "",
    history: list[dict] | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    task_id: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    source_context: dict[str, object] | None = None,
) -> AIResponseEnvelope:
    should_record = provider is None or ai_call_callback is not None
    llm = provider or default_llm_provider(model)
    messages, input_chars = build_qa_messages(
        question=question,
        summary=summary,
        transcript=transcript,
        video_title=video_title,
        history=history,
        source_context=source_context,
    )
    started_at = time.perf_counter()

    try:
        response = llm.chat(
            messages,
            temperature=0.2,
        )
        if should_record:
            record = record_ai_call(
                call_type="qa",
                provider_response=response,
                input_chars=input_chars,
                output_chars=len(response.content),
                elapsed_seconds=time.perf_counter() - started_at,
                task_id=task_id,
                content_item_id=content_item_id,
            )
            if record and ai_call_callback:
                ai_call_callback(record)
        parser = SuggestionTrailerParser()
        parser.feed(response.content)
        parsed = parser.finish()
        return AIResponseEnvelope(
            answer=parsed.answer.strip(),
            reasoning_content=response.reasoning_content,
            suggested_questions=parsed.suggested_questions,
        )
    except Exception as e:
        if should_record:
            record_ai_call(
                call_type="qa",
                provider_response=None,
                input_chars=input_chars,
                elapsed_seconds=time.perf_counter() - started_at,
                task_id=task_id,
                content_item_id=content_item_id,
                error=str(e),
            )
        raise Exception(f"文本模型 API 调用失败: {str(e)}")


def stream_answer_question(
    question: str,
    summary: str,
    transcript: str,
    video_title: str = "",
    history: list[dict] | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    task_id: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    source_context: dict[str, object] | None = None,
) -> Iterator[str]:
    for event in stream_answer_question_events(
        question=question,
        summary=summary,
        transcript=transcript,
        video_title=video_title,
        history=history,
        provider=provider,
        model=model,
        task_id=task_id,
        content_item_id=content_item_id,
        ai_call_callback=ai_call_callback,
        source_context=source_context,
    ):
        if event.kind == "answer_delta":
            yield event.text


def stream_answer_question_events(
    question: str,
    summary: str,
    transcript: str,
    video_title: str = "",
    history: list[dict] | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    task_id: str | None = None,
    content_item_id: str | None = None,
    ai_call_callback: Callable[[AICallRecord], None] | None = None,
    source_context: dict[str, object] | None = None,
) -> Iterator[AIResponseStreamEvent]:
    llm = provider or default_llm_provider(model)
    messages, input_chars = build_qa_messages(
        question=question,
        summary=summary,
        transcript=transcript,
        video_title=video_title,
        history=history,
        source_context=source_context,
    )
    started_at = time.perf_counter()
    chunks: list[str] = []
    reasoning_chunks: list[str] = []
    stream_usage: LLMUsage | None = None

    def remember_usage(usage: LLMUsage) -> None:
        nonlocal stream_usage
        stream_usage = usage

    try:
        parser = SuggestionTrailerParser()
        visible_chars = 0
        for chunk in _stream_provider_events(llm, messages, temperature=0.2):
            if chunk.usage:
                remember_usage(chunk.usage)
            if chunk.reasoning_content:
                reasoning_chunks.append(chunk.reasoning_content)
                yield AIResponseStreamEvent(kind="reasoning_delta", text=chunk.reasoning_content)
            if chunk.content:
                chunks.append(chunk.content)
                visible = parser.feed(chunk.content)
                if visible:
                    visible_chars += len(visible)
                    yield AIResponseStreamEvent(kind="answer_delta", text=visible)
        envelope = parser.finish()
        if len(envelope.answer) > visible_chars:
            yield AIResponseStreamEvent(kind="answer_delta", text=envelope.answer[visible_chars:])
        envelope = type(envelope)(
            answer=envelope.answer,
            reasoning_content="".join(reasoning_chunks),
            suggested_questions=envelope.suggested_questions,
        )
        provider_response = LLMResponse(
            content="",
            provider=llm.name,
            model=llm.model,
            usage=stream_usage,
            reasoning_content=envelope.reasoning_content,
        ) if stream_usage else None
        record = record_ai_call(
            call_type="qa",
            provider_response=provider_response,
            input_chars=input_chars,
            output_chars=len("".join(chunks)) + len(envelope.reasoning_content),
            elapsed_seconds=time.perf_counter() - started_at,
            task_id=task_id,
            content_item_id=content_item_id,
        )
        if record and ai_call_callback:
            ai_call_callback(record)
        yield AIResponseStreamEvent(kind="done", envelope=envelope)
    except Exception as e:
        record_ai_call(
            call_type="qa",
            provider_response=None,
            input_chars=input_chars,
            elapsed_seconds=time.perf_counter() - started_at,
            task_id=task_id,
            content_item_id=content_item_id,
            error=str(e),
        )
        raise Exception(f"文本模型 API 调用失败: {str(e)}")


def build_qa_messages(
    *,
    question: str,
    summary: str,
    transcript: str,
    video_title: str = "",
    history: list[dict] | None = None,
    source_context: dict[str, object] | None = None,
) -> tuple[list[LLMMessage], int]:
    system_prompt = get_active_system_prompt("qa")
    # Keep the invariant material first. DeepSeek's automatic context cache
    # reuses an identical request prefix, so placing the changing question
    # before the source text would invalidate the most valuable cache segment
    # on every follow-up. Individual historical exchanges then preserve their
    # natural user/assistant roles and remain part of the next request prefix.
    timestamp_guidance = (
        "\n媒体时间链接说明：链接对应可回看的原始片段。需要引用时间时只能原样使用材料中已有链接，"
        "不得编造、估算或改写时间。\n"
        if "#video-t=" in transcript
        else ""
    )
    context_material = render_source_context_for_prompt(source_context)
    source_material = f"""当前内容资料（以下资料在本次对话中保持不变）：

标题：{video_title or "未命名内容"}

原文或转写：
{_trim_transcript_for_qa(transcript or "")}
{timestamp_guidance}

已有总结：
{summary or "无"}
"""
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="system", content=FOLLOWUP_RESPONSE_CONTRACT),
    ]
    if context_material:
        messages.append(LLMMessage(role="system", content=active_source_context_system_prompt()))
        source_material += f"\n平台互动与评论辅助材料：\n{context_material}\n"
    messages.append(LLMMessage(role="user", content=source_material))
    for item in history or []:
        item_question = str(item.get("question", "")).strip()
        item_answer = str(item.get("answer", "")).strip()
        if not (item_question and item_answer):
            continue
        # Keep this byte-for-byte equal to the original question message. On
        # the next turn it becomes part of the replayed prefix for cache reuse.
        messages.append(LLMMessage(role="user", content=f"用户问题：\n{item_question}"))
        messages.append(LLMMessage(role="assistant", content=item_answer))

    messages.append(LLMMessage(role="user", content=f"用户问题：\n{question}"))
    return messages, sum(len(message.content) for message in messages)


def resolve_obsidian_note_path(obsidian_path: str | Path) -> Path:
    vault = settings.obsidian_vault.expanduser().resolve()
    note_path = Path(obsidian_path).expanduser()
    if not note_path.is_absolute():
        note_path = vault / note_path
    resolved = note_path.resolve()
    try:
        resolved.relative_to(vault)
    except ValueError as exc:
        raise ValueError("只能写入 Obsidian 知识库目录内的笔记") from exc
    return resolved


def append_qa_to_markdown(
    obsidian_path: str | Path,
    question: str,
    answer: str,
    timestamp: str,
) -> Path:
    note_path = resolve_obsidian_note_path(obsidian_path)
    if not note_path.exists() or not note_path.is_file():
        raise ValueError("对应的 Obsidian 笔记不存在")

    content = note_path.read_text(encoding="utf-8")
    section_title = "## 追问记录"
    if section_title not in content:
        content = content.rstrip() + f"\n\n{section_title}\n"

    entry = f"""
### {timestamp}

**问：** {question.strip()}

**答：**
{answer.strip()}
"""
    note_path.write_text(content.rstrip() + "\n\n" + entry.strip() + "\n", encoding="utf-8")
    return note_path

def generate_markdown(summary: str, video_info: dict, source_url: str) -> str:
    title = video_info.get("title", "未命名视频")
    uploader = video_info.get("uploader", "未知")
    duration = video_info.get("duration", 0)
    source_context_markdown = render_source_context_markdown(video_info.get("source_context"))
    context_section = f"\n\n{source_context_markdown}" if source_context_markdown else ""
    
    md = f"""---
source: {source_url}
platform: {video_info.get("platform", "unknown")}
uploader: {uploader}
duration: {duration}s
date: {video_info.get("upload_date", "")}
---

# {title}

{summary}{context_section}

<details>
<summary>原始转写文本</summary>

{video_info.get("transcript", "")}

</details>
"""
    return md


def generate_article_markdown(summary: str, article_info: dict, source_url: str) -> str:
    title = article_info.get("title", "未命名文章")
    author = article_info.get("author", "")
    published_at = article_info.get("published_at", "")
    body_text = article_info.get("body_text") or article_info.get("transcript", "")
    source_context_markdown = render_source_context_markdown(article_info.get("source_context"))
    context_section = f"\n\n{source_context_markdown}" if source_context_markdown else ""

    md = f"""---
source: {source_url}
platform: {article_info.get("platform", "wechat")}
author: {author}
published_at: {published_at}
---

# {title}

{summary}{context_section}

<details>
<summary>原文正文</summary>

{body_text}

</details>
"""
    return md
