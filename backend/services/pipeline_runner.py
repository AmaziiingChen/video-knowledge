from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import uuid
from collections.abc import Callable
from threading import BoundedSemaphore
from types import SimpleNamespace

from config import settings
from services.cache import (
    cache_dir_for_url,
    ensure_preview_thumbnails,
    find_cached_video,
    read_cached_transcript_segments,
    read_cache_meta,
    media_duration_seconds,
    read_cached_subtitle_transcript,
    read_cached_transcript,
    write_cached_transcript_segments,
    write_cache_meta,
    write_cached_subtitle_transcript,
    write_cached_transcript,
)
from services.ai_call_logger import AICallRecord
from services.article_fetcher import fetch_article
from services.article_preview import ARTICLE_NORMALIZER_VERSION, normalize_article_html
from services.bilibili_context import fetch_bilibili_source_context
from services.published_at import PUBLISHED_AT_PARSER_VERSION
from services.pipeline_asr_policy import (
    ASR_MODEL_STRATEGIES,
    WHISPER_MODELS,  # noqa: F401 - public compatibility re-export
    duration_from_info as _duration_from_info,
    normalize_asr_options as _normalize_asr_options,
    resolve_asr_model as _resolve_asr_model,
    valid_whisper_model as _valid_whisper_model,
)
from services.pipeline_contracts import (
    AICallInfo,
    DownloadTransferInfo,
    PipelineCancelled,
    PipelineErrorInfo,  # noqa: F401 - public compatibility re-export
    PipelineLog,
    PipelineRequest,  # noqa: F401 - public compatibility re-export
    PipelineResponse,
    TextSourceInfo,
    classify_pipeline_error,
)
from services.pipeline_progress_rules import (
    clamp_percent as _clamp_percent,
    elapsed as _elapsed,
    level_from_message as _level_from_message,
)
from services.content_index import ensure_content_item_for_media, ensure_manual_collection_target_folder
from services.knowledge_library import attachments_root
from services.content_source_text import (
    _wechat_article_needs_ocr_refresh as _content_source_text_needs_ocr_refresh,
    load_content_source_text,
)
from services.database import connect, initialize_database
from services.repository import ContentRepository
from services.downloader import DownloadProgress, download_video, get_video_info
from services.douyin_context import fetch_douyin_source_context
from services.markdown_sync import replace_content_summary_and_sync, save_markdown_draft_and_sync
from services.search_index import upsert_search_document
from services.source_context import source_context_is_fresh
from services.source_context_store import save_source_context
from services.summarizer import generate_article_markdown, generate_markdown, summarize, summarize_stream
from services.subtitles import SUBTITLE_EXTENSIONS, fetch_bilibili_subtitle, parse_subtitle_text
from services.transcriber import ASR_BACKENDS, extract_audio_with_details, transcribe_with_details
from services.url_parser import parse_share_text, redact_sensitive_url
from services.video_download_settings import should_auto_download_bilibili_video


LOCAL_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
PROGRESS_STAGES = ["parse", "info", "download", "extract_audio", "transcribe", "summarize", "save"]
PROGRESS_WEIGHTS = {
    "parse": 4,
    "info": 4,
    "download": 22,
    "extract_audio": 10,
    "transcribe": 36,
    "summarize": 20,
    "save": 4,
}
# A desktop can keep one network transfer moving while the previous file is
# transcribed, but competing yt-dlp/browser downloads make both less reliable
# and saturate the local network. Every pipeline path shares this one slot.
_media_download_semaphore = BoundedSemaphore(1)
# One opened assistant panel is cheap enough to repaint at roughly 40 fps.
# This is a transport coalescing limit, not a typewriter effect: every
# snapshot still contains exactly the text the model has returned so far.
SUMMARY_PUBLISH_INTERVAL_SECONDS = 0.025


ProgressCallback = Callable[[PipelineResponse], None]
CancelCheck = Callable[[], bool]


def _is_under_data_dir(path: Path) -> bool:
    try:
        path.relative_to(settings.data_dir.resolve())
        return True
    except ValueError:
        return False


def _is_managed_local_media(path: Path, *, content_item_id: str | None = None) -> bool:
    """Allow cache/data media and only the original attachment of this item."""
    if _is_under_data_dir(path):
        return True
    try:
        path.relative_to(attachments_root().resolve())
        return True
    except ValueError:
        pass
    if not content_item_id:
        return False
    try:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM media_assets
                   WHERE content_item_id=? AND asset_type='original_file' AND path=? LIMIT 1""",
                (content_item_id, str(path)),
            ).fetchone()
        return row is not None
    except Exception:
        return False


def run_pipeline_sync(
    share_text: str | None = None,
    whisper_model: str | None = None,
    asr_backend: str | None = None,
    asr_model_strategy: str | None = None,
    asr_short_video_model: str | None = None,
    asr_long_video_model: str | None = None,
    asr_beam_size: int | None = None,
    asr_vad_filter: bool | None = None,
    asr_fallback_enabled: bool | None = None,
    use_cache: bool = True,
    task_id: str | None = None,
    on_update: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    content_item_id: str | None = None,
    local_video_path: str | None = None,
    local_subtitle_path: str | None = None,
    source_title: str | None = None,
    source_url: str | None = None,
    ai_model: str | None = None,
    processing_mode: str = "full",
    subtitle_only: bool = False,
    download_video_preview: bool = False,
    manual_collection: bool = False,
) -> PipelineResponse:
    total_start = time.perf_counter()
    response = PipelineResponse(success=False, task_id=task_id or str(uuid.uuid4())[:8])
    response.content_item_id = content_item_id
    local_media_is_audio = False
    asr_options = _normalize_asr_options(
        whisper_model=whisper_model,
        asr_backend=asr_backend,
        asr_model_strategy=asr_model_strategy,
        asr_short_video_model=asr_short_video_model,
        asr_long_video_model=asr_long_video_model,
        asr_beam_size=asr_beam_size,
        asr_vad_filter=asr_vad_filter,
        asr_fallback_enabled=asr_fallback_enabled,
    )
    selected_model = _resolve_asr_model(
        whisper_model=whisper_model,
        strategy=asr_options["strategy"],
        short_model=asr_options["short_model"],
        long_model=asr_options["long_model"],
        duration_seconds=None,
    )
    response.whisper_model = selected_model
    response.asr_backend = asr_options["backend"]
    processing_mode = processing_mode if processing_mode in {"transcript", "full", "download_only"} else "full"
    preview_download_executor: ThreadPoolExecutor | None = None
    preview_download_future: Future | None = None
    preview_download_started_at: float | None = None
    source_context: dict[str, object] = {}
    last_summary_publish_at = 0.0

    def publish() -> None:
        if on_update:
            on_update(response.model_copy(deep=True))

    def update_overall_progress() -> None:
        total = 0.0
        for step, weight in PROGRESS_WEIGHTS.items():
            total += (response.progress.get(step, 0.0) / 100.0) * weight
        response.overall_progress = _clamp_percent(total)

    def set_progress(step: str, percent: float, publish_update: bool = True) -> None:
        if step not in PROGRESS_WEIGHTS:
            return
        current = response.progress.get(step, 0.0)
        response.progress[step] = max(current, _clamp_percent(percent))
        response.step = step
        update_overall_progress()
        if publish_update:
            publish()

    def set_download_transfer(progress: DownloadProgress) -> None:
        """Publish only provider-reported media telemetry to the UI.

        The existing weighted ``overall_progress`` remains useful for task
        scheduling/history, but it must never be presented as a byte-level
        download percentage.
        """
        response.step = "download"
        response.download_transfer = DownloadTransferInfo(
            phase=progress.phase,
            detail=progress.detail,
            received_bytes=progress.received_bytes,
            total_bytes=progress.total_bytes,
            bytes_per_second=progress.bytes_per_second,
            percent=progress.percent,
        )
        if progress.percent is not None:
            current = response.progress.get("download", 0.0)
            response.progress["download"] = max(current, _clamp_percent(progress.percent))
            update_overall_progress()
        publish()

    def complete_stage(step: str) -> None:
        set_progress(step, 100.0, publish_update=False)

    def add_log(
        step: str,
        message: str,
        level: str = "info",
        elapsed_seconds: float | None = None,
    ) -> None:
        response.step = step
        if step in PROGRESS_WEIGHTS and response.progress.get(step, 0.0) == 0:
            set_progress(step, 5.0, publish_update=False)
        response.logs.append(
            PipelineLog(
                step=step,
                message=message,
                level=level,
                elapsed_seconds=elapsed_seconds,
                created_at=datetime.now().astimezone().isoformat(),
            )
        )
        publish()

    def download_with_live_logs(url: str, platform: str, output_dir: Path):
        """Run a media provider while forwarding provider milestones promptly.

        Download adapters still return their complete log for durable task
        history.  Keeping a count of lines already published avoids showing
        the same milestone twice when the adapter returns.
        """
        published_counts: dict[str, int] = {}
        waiting_for_download_slot = False

        while not _media_download_semaphore.acquire(timeout=0.12):
            check_cancel()
            if not waiting_for_download_slot:
                waiting_for_download_slot = True
                add_log("download", "等待上一条视频下载完成…")

        def publish_download_log(message: str) -> None:
            published_counts[message] = published_counts.get(message, 0) + 1
            add_log("download", message, _level_from_message(message))

        try:
            download_result = download_video(
                url,
                platform,
                output_dir,
                progress_callback=set_download_transfer,
                cancel_check=cancel_check,
                log_callback=publish_download_log,
            )
        finally:
            _media_download_semaphore.release()
        for line in download_result.logs:
            remaining = published_counts.get(line, 0)
            if remaining:
                published_counts[line] = remaining - 1
                continue
            add_log("download", line, _level_from_message(line))
        return download_result

    def check_cancel() -> None:
        if cancel_check and cancel_check():
            raise PipelineCancelled()

    def publish_video_artifact() -> None:
        """Persist and publish a playable video as soon as it exists.

        A media task used to wait until transcription had completed before it
        created its content item.  That made the renderer have no stable
        workspace target for a perfectly usable downloaded video, so the
        preview appeared only after every later pipeline stage had finished.
        Keep the item in ``processing`` while ASR and AI continue, but expose
        its id together with ``video_path`` immediately.
        """
        nonlocal content_item_id
        if not response.video_path:
            return
        if not content_item_id:
            manual_folder_id = None
            if manual_collection:
                initialize_database()
                with connect() as connection:
                    manual_folder_id = ensure_manual_collection_target_folder(connection, parsed.platform)
                    connection.commit()
            item = ensure_content_item_for_media(
                source_provider=parsed.platform,
                source_url=parsed.url,
                video_info=video_info,
                title=source_title,
                content_type="video",
                status="processing",
                library_folder_id=manual_folder_id,
            )
            content_item_id = item.id if item else None
        response.content_item_id = content_item_id
        publish()

    def start_parallel_bilibili_preview_download() -> None:
        """Download an optional Bilibili preview while subtitle-based AI runs."""
        nonlocal preview_download_executor, preview_download_future, preview_download_started_at
        if preview_download_future is not None:
            return
        preview_download_started_at = time.perf_counter()
        preview_download_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bilibili-preview")
        preview_download_future = preview_download_executor.submit(
            download_with_live_logs,
            parsed.url,
            parsed.platform,
            output_dir,
        )

    def finish_parallel_bilibili_preview_download() -> None:
        """Fold the optional preview result back into the current task."""
        nonlocal preview_download_executor, preview_download_future, preview_download_started_at
        if preview_download_future is None:
            return
        future = preview_download_future
        executor = preview_download_executor
        preview_download_future = None
        preview_download_executor = None
        try:
            dl_result = future.result()
            response.timings["download"] = _elapsed(preview_download_started_at or total_start)
            if not dl_result.success or not dl_result.video_path:
                add_log("download", f"字幕与总结已保留，但视频预览下载失败: {dl_result.error or '未知错误'}", "warn", response.timings["download"])
                complete_stage("download")
                return
            video_path = dl_result.video_path
            response.video_path = str(video_path)
            publish_video_artifact()
            downloaded_at = datetime.now(timezone.utc)
            write_cache_meta(cache_dir, {
                "video_path": video_path.name,
                "video_cache_status": "available",
                "video_cache_downloaded_at": downloaded_at.isoformat(),
                "video_cache_expires_at": (downloaded_at + timedelta(days=max(1, settings.video_cache_retention_days))).isoformat(),
                "video_cache_expired_at": "",
            })
            set_download_transfer(DownloadProgress("caching", "正在生成视频预览"))
            _ensure_preview_thumbnails(cache_dir, video_path, add_log)
            complete_stage("download")
            add_log("download", f"本地视频预览下载完成: {video_path.name}", "success", response.timings["download"])
        except Exception as exc:
            response.timings["download"] = _elapsed(preview_download_started_at or total_start)
            add_log("download", f"字幕与总结已保留，但视频预览下载失败: {exc}", "warn", response.timings["download"])
            complete_stage("download")
        finally:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=False)

    def fail(step: str, error: str) -> PipelineResponse:
        finish_parallel_bilibili_preview_download()
        response.success = False
        response.step = step
        response.error = error
        response.error_info = classify_pipeline_error(step, error)
        response.timings["total"] = _elapsed(total_start)
        active_cache_dir = locals().get("cache_dir")
        if active_cache_dir:
            write_cache_meta(active_cache_dir, {"pipeline_status": "failed", "pipeline_error": error})
        if response.content_item_id:
            _set_content_status(response.content_item_id, "failed")
        update_overall_progress()
        publish()
        return response

    def mark_stage(step: str, message: str, start: float, level: str = "success") -> None:
        elapsed_seconds = _elapsed(start)
        response.timings[step] = elapsed_seconds
        complete_stage(step)
        add_log(step, message, level, elapsed_seconds)

    def set_many_complete(steps: list[str]) -> None:
        for step in steps:
            complete_stage(step)

    def remember_ai_call(fallback_call_type: str) -> Callable[[AICallRecord], None]:
        def append_call(record: AICallRecord) -> None:
            call_type = record.call_type or fallback_call_type
            response.ai_calls.append(
                AICallInfo(
                    call_type=call_type,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    total_tokens=record.total_tokens,
                    prompt_cache_hit_tokens=record.prompt_cache_hit_tokens,
                    prompt_cache_miss_tokens=record.prompt_cache_miss_tokens,
                    estimated_cost=record.estimated_cost,
                    elapsed_seconds=record.elapsed_seconds,
                )
            )
            if call_type == "article_summary_prepare":
                count = sum(item.call_type == "article_summary_prepare" for item in response.ai_calls)
                add_log("summarize", f"超长文章材料压缩完成（第 {count} 次）", "success", record.elapsed_seconds)

        return append_call

    def publish_summary_delta(title: str, partial_summary: str) -> None:
        """Persist streamed summary text without turning every token into I/O."""
        nonlocal last_summary_publish_at
        response.display_title = title or response.display_title
        response.summary = partial_summary
        now = time.perf_counter()
        if now - last_summary_publish_at < SUMMARY_PUBLISH_INTERVAL_SECONDS:
            return
        last_summary_publish_at = now
        publish()

    try:
        if asr_options["backend"] not in ASR_BACKENDS:
            add_log("config", f"不支持的语音识别后端: {asr_options['backend']}", "error")
            return fail("config", f"不支持的语音识别后端: {asr_options['backend']}")
        if asr_options["strategy"] not in ASR_MODEL_STRATEGIES:
            add_log("config", f"不支持的模型策略: {asr_options['strategy']}", "error")
            return fail("config", f"不支持的模型策略: {asr_options['strategy']}")
        for model in {asr_options["initial_model"], asr_options["short_model"], asr_options["long_model"], selected_model}:
            if model and not _valid_whisper_model(model):
                add_log("config", f"不支持的 Whisper 模型: {model}", "error")
                return fail("config", f"不支持的 Whisper 模型: {model}")

        # Clipboard and integrations may create a generic task directly,
        # without first creating an inbox item. XHS image notes require an
        # article identity before processing (they have no video downloader),
        # so promote such a request into the normal inbox contract up front.
        if not content_item_id and not local_video_path and not local_subtitle_path:
            direct_source = source_url or share_text or ""
            parsed_direct_source = parse_share_text(direct_source)
            if parsed_direct_source and parsed_direct_source.platform == "xiaohongshu":
                from services.inbox import capture_link_to_inbox

                captured = capture_link_to_inbox(parsed_direct_source.url)
                if captured.error or captured.item is None:
                    return fail("parse", captured.error or "小红书图文入库失败")
                content_item_id = captured.item.id
                response.content_item_id = content_item_id

        # Campus and RSS entries are already persisted by their own stable
        # ingestion pipelines, so they must not be sent through URL parsing
        # (which only understands share links).  This task path reads the
        # stored article source, optionally summarizes it, and retains the
        # existing source folder.
        if content_item_id:
            with connect() as connection:
                try:
                    existing_item = ContentRepository(connection).get_content_item(content_item_id)
                except LookupError:
                    existing_item = None
                # Early XHS versions stored image notes as videos.  Repair
                # the durable type at the processing boundary too, so a
                # retry of an existing sidebar row enters the image-note
                # collector instead of the media downloader.
                if (
                    existing_item
                    and existing_item.source_provider == "xiaohongshu"
                    and existing_item.content_type != "article"
                ):
                    existing_item = ContentRepository(connection).update_content_type(existing_item.id, "article")
                    connection.commit()
                    add_log("parse", "已修复旧小红书图文类型，正在按图文采集…")
            if existing_item and existing_item.content_type == "article" and existing_item.source_provider == "xiaohongshu":
                add_log("parse", "正在读取小红书图文与图片…")
                try:
                    from services.xiaohongshu_ingest import capture_xiaohongshu_note

                    captured_article_info = capture_xiaohongshu_note(existing_item.id)
                    source_context = dict(captured_article_info.get("source_context") or {})
                except Exception as exc:
                    return fail("info", f"小红书图文采集失败：{exc}")
                if source_context:
                    try:
                        save_source_context(existing_item, source_context)
                    except Exception as exc:
                        add_log("info", f"互动数据持久化失败，继续使用图文正文：{exc}", "warn")
                with connect() as connection:
                    existing_item = ContentRepository(connection).get_content_item(existing_item.id)
                add_log("info", "图文素材已缓存，正在整理图片文字", "success")
            if existing_item and existing_item.content_type == "article" and existing_item.source_provider in {"campus", "rss", "xiaohongshu"}:
                response.url = existing_item.source_url
                response.platform = existing_item.source_provider
                provider_label = {"campus": "校园官网", "rss": "RSS", "xiaohongshu": "小红书"}[existing_item.source_provider]
                add_log("parse", f"读取已入库的{provider_label}文章", "success")
                try:
                    source = load_content_source_text(existing_item.id)
                except Exception as exc:
                    return fail("info", f"读取文章正文失败：{exc}")
                transcript = source.text.strip()
                if not transcript:
                    return fail("info", "文章正文为空")
                response.transcript = transcript
                response.text_source = TextSourceInfo(kind="article", source=existing_item.source_provider, detail="已入库文章正文")
                set_many_complete(["parse", "info", "download", "extract_audio", "transcribe"])
                add_log("info", f"正文已就绪（{len(transcript)} 字）", "success")
                if processing_mode == "transcript":
                    set_many_complete(["summarize", "save"])
                    _set_content_status(existing_item.id, "to_read")
                    response.display_title = existing_item.title
                    response.success = True
                    response.timings["total"] = _elapsed(total_start)
                    add_log("save", "正文已保存，未调用 AI 总结", "success")
                    response.step = None
                    publish()
                    return response
                if not settings.deepseek_api_key:
                    return fail("summarize", "未配置 DeepSeek API Key（请在设置 → 处理与 AI 中填写）")
                summarize_start = time.perf_counter()
                add_log("summarize", "调用 DeepSeek 生成文章总结...")
                try:
                    ai_title, summary = summarize(
                        transcript,
                        existing_item.title,
                        model=ai_model,
                        task_type="article_summary",
                        task_id=response.task_id,
                        content_item_id=existing_item.id,
                        ai_call_callback=remember_ai_call("summary"),
                        source_context=source_context,
                    )
                except Exception as exc:
                    return fail("summarize", str(exc))
                if not summary:
                    return fail("summarize", "总结生成失败")
                response.summary = summary
                response.display_title = ai_title or existing_item.title
                complete_stage("summarize")
                _set_content_title(existing_item.id, response.display_title)
                replace_content_summary_and_sync(existing_item.id, summary)
                _set_content_status(existing_item.id, "to_read")
                try:
                    upsert_search_document(
                        content_key=existing_item.id,
                        title=response.display_title,
                        summary=summary,
                        transcript=transcript,
                        source_context=source_context,
                    )
                except Exception as exc:
                    add_log("save", f"搜索索引更新失败：{exc}", "warn")
                complete_stage("save")
                response.timings["summarize"] = _elapsed(summarize_start)
                response.timings["total"] = _elapsed(total_start)
                response.success = True
                add_log("save", "文章总结已保存", "success")
                response.step = None
                publish()
                return response

        cache_dir = None
        cached_video = None
        cached_subtitle_transcript = None
        cached_transcript = None
        transcript = ""
        transcript_segments: list[dict] = []
        article_info = None
        text_ready = False

        if local_subtitle_path:
            check_cancel()
            local_path = Path(local_subtitle_path).expanduser().resolve()
            if not _is_managed_local_media(local_path, content_item_id=content_item_id):
                add_log("parse", "本地字幕必须位于 data 目录下", "error")
                return fail("parse", "本地字幕必须位于 data 目录下")
            if not local_path.exists() or not local_path.is_file():
                add_log("parse", "本地字幕文件不存在", "error")
                return fail("parse", "本地字幕文件不存在")
            if local_path.suffix.lower() not in SUBTITLE_EXTENSIONS:
                add_log("parse", f"不支持的字幕格式: {local_path.suffix}", "error")
                return fail("parse", f"不支持的字幕格式: {local_path.suffix}")

            transcript = parse_subtitle_text(
                local_path.read_text(encoding="utf-8", errors="replace"),
                local_path.suffix,
            )
            if not transcript:
                add_log("transcribe", "字幕文件为空或无法解析", "error")
                return fail("transcribe", "字幕文件为空或无法解析")

            parsed = SimpleNamespace(
                url=source_url or f"local://{local_path.name}",
                platform="subtitle",
            )
            cache_dir = cache_dir_for_url(parsed.url)
            write_cached_subtitle_transcript(cache_dir, transcript)
            video_info = {
                "title": source_title or local_path.stem,
                "platform": "subtitle",
                "duration": 0,
            }
            use_cache = False
            text_ready = True
            response.url = parsed.url
            response.platform = parsed.platform
            response.transcript = transcript
            response.text_source = TextSourceInfo(
                kind="subtitle",
                source="manual",
                detail=local_path.name,
            )
            response.timings["parse"] = 0.0
            response.timings["info"] = 0.0
            response.timings["download"] = 0.0
            response.timings["extract_audio"] = 0.0
            response.timings["transcribe"] = 0.0
            response.timings["whisper_model_load"] = 0.0
            response.timings["whisper_decode"] = 0.0
            set_many_complete(["parse", "info", "download", "extract_audio", "transcribe"])
            add_log("parse", f"使用本地字幕: {local_path.name}", "success", 0.0)
            add_log("info", f"标题: {video_info['title']}", "success", 0.0)
            add_log("download", "本地字幕已就绪，跳过下载", "success", 0.0)
            add_log("extract_audio", "本地字幕已就绪，跳过音频提取", "success", 0.0)
            add_log("transcribe", f"字幕解析完成（{len(transcript)} 字）", "success", 0.0)
        elif local_video_path:
            check_cancel()
            local_path = Path(local_video_path).expanduser().resolve()
            # Imported originals may be deliberately retained beside the
            # external Markdown library (for example an Obsidian vault), not
            # below the private data directory.  Accept only application
            # managed attachments or the exact original registered for this
            # content item; never open an arbitrary local path from a task.
            if not _is_managed_local_media(local_path, content_item_id=content_item_id):
                message = "本地媒体不在应用管理的 data 或附件目录中"
                add_log("parse", message, "error")
                return fail("parse", message)
            if not local_path.exists() or not local_path.is_file():
                add_log("parse", "本地视频文件不存在", "error")
                return fail("parse", "本地视频文件不存在")
            local_media_is_audio = local_path.suffix.lower() in LOCAL_AUDIO_EXTENSIONS

            parsed = SimpleNamespace(
                url=source_url or f"local://{local_path.name}",
                platform="local",
            )
            # A retranscription deliberately skips media reuse, but its new
            # transcript must still be written beside the retained source
            # video.  Without this, cache_dir remains None and the cache
            # writer fails after ASR has already completed.
            cache_dir = cache_dir_for_url(parsed.url)
            cache_dir.mkdir(parents=True, exist_ok=True)
            video_info = {
                "title": source_title or local_path.stem,
                "platform": "local",
                "duration": media_duration_seconds(local_path) or 0,
            }
            use_cache = False
            cached_video = local_path
            response.url = parsed.url
            response.platform = parsed.platform
            response.video_path = str(local_path)
            publish_video_artifact()
            response.timings["parse"] = 0.0
            response.timings["info"] = 0.0
            response.timings["download"] = 0.0
            set_many_complete(["parse", "info", "download"])
            add_log("parse", f"使用本地{'音频' if local_media_is_audio else '视频'}: {local_path.name}", "success", 0.0)
            add_log("info", f"标题: {video_info['title']}", "success", 0.0)
            add_log("download", f"本地{'音频' if local_media_is_audio else '视频'}已就绪，跳过下载", "success", 0.0)
        else:
            check_cancel()
            parse_start = time.perf_counter()
            parsed = parse_share_text(share_text or "")
            response.timings["parse"] = _elapsed(parse_start)
            if not parsed:
                add_log("parse", "未识别到有效链接", "error", response.timings["parse"])
                return fail("parse", "未识别到有效链接")

            response.url = parsed.url
            response.platform = parsed.platform
            complete_stage("parse")
            add_log(
                "parse",
                f"识别到 {parsed.platform} 链接: {redact_sensitive_url(parsed.url)}",
                "success",
                response.timings["parse"],
            )

            cache_dir = cache_dir_for_url(parsed.url)
            cache_meta = read_cache_meta(cache_dir) if use_cache else {}
            cached_source_context = cache_meta.get("source_context")
            if not source_context and isinstance(cached_source_context, dict):
                source_context = dict(cached_source_context)
            task_dir = response.task_id or str(uuid.uuid4())[:8]
            output_dir = cache_dir if use_cache else settings.data_dir / task_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            if parsed.platform == "wechat":
                info_start = time.perf_counter()
                cached_article = cache_meta.get("article_info") if use_cache else None
                if use_cache:
                    write_cache_meta(
                        cache_dir,
                        {
                            "source_url": parsed.url,
                            "platform": parsed.platform,
                            "cache_key": cache_dir.name,
                        },
                    )
                if cached_article and not _wechat_article_needs_ocr_refresh(cached_article):
                    article_info = cached_article
                    response.cache_hits.append("article")
                    add_log("info", f"复用公众号正文缓存，标题: {article_info.get('title', '未知')}", "success", 0.0)
                else:
                    add_log("info", "抓取微信公众号正文...")
                    try:
                        article = fetch_article(parsed.url, parsed.platform)
                    except Exception as exc:
                        response.timings["info"] = _elapsed(info_start)
                        add_log("info", str(exc), "error", response.timings["info"])
                        return fail("info", str(exc))
                    article_info = {
                        "title": article.title,
                        "platform": article.platform,
                        "author": article.author,
                        "published_at": article.published_at,
                        "published_at_parser_version": PUBLISHED_AT_PARSER_VERSION,
                        "body_text": article.body_text,
                        "body_html": article.body_html,
                        "normalized_html": normalize_article_html(article.body_html),
                        "normalized_html_version": ARTICLE_NORMALIZER_VERSION,
                        "images": article.images,
                        "image_ocr": article.image_ocr,
                    }
                    if use_cache:
                        write_cache_meta(cache_dir, {"article_info": article_info})
                    ocr_count = int(article.image_ocr.get("recognized_count") or 0)
                    cloud_count = int(article.image_ocr.get("cloud_submitted_count") or 0)
                    cached_ocr_count = int(article.image_ocr.get("cached_ocr_count") or 0)
                    hard_filters = article.image_ocr.get("hard_filter_counts") or {}
                    skipped_count = sum(int(value or 0) for value in hard_filters.values())
                    ocr_detail = ""
                    if bool(article.image_ocr.get("attempted")):
                        cached_detail = f"，复用 {cached_ocr_count} 张" if cached_ocr_count else ""
                        ocr_detail = (
                            f"，筛除 {skipped_count} 张，送 OCR {cloud_count} 张"
                            f"{cached_detail}，提取 {ocr_count} 张图片文字"
                        )
                    mark_stage("info", f"标题: {article.title}{ocr_detail}", info_start)

                transcript = str(article_info.get("body_text") or "").strip()
                if not transcript:
                    add_log("transcribe", "公众号正文为空", "error")
                    return fail("transcribe", "公众号正文为空")
                video_info = {
                    "title": article_info.get("title") or source_title or "未命名公众号文章",
                    "platform": "wechat",
                    "duration": 0,
                    "author": article_info.get("author", ""),
                    "published_at": article_info.get("published_at", ""),
                }
                text_ready = True
                response.transcript = transcript
                response.text_source = TextSourceInfo(
                    kind="article",
                    source="wechat",
                    cached=bool(cached_article),
                    detail="微信公众号正文",
                )
                response.timings["download"] = 0.0
                response.timings["extract_audio"] = 0.0
                response.timings["transcribe"] = 0.0
                response.timings["whisper_model_load"] = 0.0
                response.timings["whisper_decode"] = 0.0
                set_many_complete(["download", "extract_audio", "transcribe"])
                add_log("download", "文章正文已就绪，跳过下载", "success", 0.0)
                add_log("extract_audio", "文章正文已就绪，跳过音频提取", "success", 0.0)
                add_log("transcribe", f"正文提取完成（{len(transcript)} 字）", "success", 0.0)
            else:

                if use_cache:
                    cached_video = find_cached_video(cache_dir)
                    cached_subtitle_transcript = read_cached_subtitle_transcript(cache_dir)
                    write_cache_meta(
                        cache_dir,
                        {
                            "source_url": parsed.url,
                            "platform": parsed.platform,
                            "cache_key": cache_dir.name,
                        },
                    )

                check_cancel()
                info_start = time.perf_counter()
                cached_video_info = cache_meta.get("video_info") if use_cache else None
                # 抖音不走通用 yt-dlp 预检，浏览器下载器会在媒体请求中补充元数据。
                video_info = {}
                if cached_video_info:
                    video_info = cached_video_info
                    response.cache_hits.append("video_info")
                    mark_stage(
                        "info",
                        f"复用视频信息缓存，标题: {video_info.get('title', '未知')}，时长: {video_info.get('duration', 0)} 秒",
                        info_start,
                    )
                elif parsed.platform != "douyin":
                    add_log("info", "获取视频信息...")
                    video_info = get_video_info(parsed.url, parsed.platform)
                    if video_info and use_cache:
                        write_cache_meta(cache_dir, {"video_info": video_info})
                else:
                    # Douyin's usable metadata comes from the same signed
                    # detail request that yields the download URL.  The old
                    # generic probe has no Douyin implementation and always
                    # returned an empty result, creating a misleading warning
                    # before every otherwise successful download.
                    complete_stage("info")

                if video_info:
                    if not cached_video_info:
                        mark_stage(
                            "info",
                            f"标题: {video_info.get('title', '未知')}，时长: {video_info.get('duration', 0)} 秒",
                            info_start,
                        )
                elif parsed.platform != "douyin":
                    mark_stage("info", "获取视频信息失败（不影响下载）", info_start, "warn")

        selected_model = _resolve_asr_model(
            whisper_model=whisper_model,
            strategy=asr_options["strategy"],
            short_model=asr_options["short_model"],
            long_model=asr_options["long_model"],
            duration_seconds=_duration_from_info(video_info),
        )
        response.whisper_model = selected_model
        if use_cache and cache_dir and not cached_transcript:
            cached_transcript = read_cached_transcript(cache_dir, selected_model)

        force_video_download = processing_mode == "download_only"
        refresh_bilibili_subtitle = bool(not force_video_download and not local_video_path and parsed.platform == "bilibili")
        trusted_bilibili_subtitle_cache = (
            parsed.platform != "bilibili"
            or cache_meta.get("subtitle_trust") == "browser_player_binding_v1"
        )

        def reuse_cached_subtitle() -> None:
            nonlocal transcript, transcript_segments
            transcript = cached_subtitle_transcript
            transcript_segments = read_cached_transcript_segments(cache_dir, preferred_model="subtitle")
            response.transcript = transcript
            response.text_source = TextSourceInfo(
                kind="subtitle",
                source="cache",
                cached=True,
                detail="已缓存字幕文本",
            )
            response.cache_hits.append("subtitle")
            if cached_video:
                response.video_path = str(cached_video)
                publish_video_artifact()
                _ensure_preview_thumbnails(cache_dir, cached_video, add_log)
            response.timings["download"] = 0.0
            response.timings["extract_audio"] = 0.0
            response.timings["transcribe"] = 0.0
            response.timings["whisper_model_load"] = 0.0
            response.timings["whisper_decode"] = 0.0
            set_many_complete(["download", "extract_audio", "transcribe"])
            add_log("download", "复用字幕缓存，跳过下载", "success", 0.0)
            add_log("extract_audio", "复用字幕缓存，跳过音频提取", "success", 0.0)
            add_log("transcribe", f"复用字幕文本（{len(transcript)} 字）", "success", 0.0)

        def reuse_cached_asr_transcript() -> None:
            nonlocal transcript, transcript_segments
            transcript = cached_transcript
            transcript_segments = read_cached_transcript_segments(cache_dir, preferred_model=selected_model)
            response.transcript = transcript
            response.text_source = TextSourceInfo(
                kind="asr",
                source="cache",
                cached=True,
                detail=f"Whisper {selected_model} 转写缓存",
            )
            response.cache_hits.append("transcript")
            if cached_video:
                response.video_path = str(cached_video)
                publish_video_artifact()
                _ensure_preview_thumbnails(cache_dir, cached_video, add_log)
            response.timings["download"] = 0.0
            response.timings["extract_audio"] = 0.0
            response.timings["transcribe"] = 0.0
            response.timings["whisper_model_load"] = 0.0
            response.timings["whisper_decode"] = 0.0
            set_many_complete(["download", "extract_audio", "transcribe"])
            add_log("download", "复用转写缓存，跳过下载", "success", 0.0)
            add_log("extract_audio", "复用转写缓存，跳过音频提取", "success", 0.0)
            add_log("transcribe", f"复用转写缓存（模型: {selected_model}，{len(transcript)} 字）", "success", 0.0)

        # An explicit subtitle retry is deliberately fresh: an old source
        # snapshot may be an ASR transcript and must not make the command look
        # successful without consulting the current Bilibili player.
        if text_ready and not subtitle_only:
            pass
        elif not force_video_download and cached_subtitle_transcript and not refresh_bilibili_subtitle:
            reuse_cached_subtitle()
        elif not force_video_download and cached_transcript and not refresh_bilibili_subtitle:
            reuse_cached_asr_transcript()
        else:
            check_cancel()
            subtitle_used = False
            subtitle_fallback_reason = None
            if not force_video_download and not local_video_path and parsed.platform == "bilibili":
                subtitle_start = time.perf_counter()
                add_log("transcribe", "检查 B站播放器外挂字幕...")
                set_progress("transcribe", 15)
                subtitle_result = fetch_bilibili_subtitle(parsed.url, output_dir)
                if subtitle_result.success:
                    transcript = subtitle_result.transcript
                    transcript_segments = subtitle_result.segments
                    subtitle_used = True
                    response.text_source = TextSourceInfo(
                        kind="subtitle",
                        source=subtitle_result.source or "bilibili",
                        detail=(
                            f"{subtitle_result.source_label} · {subtitle_result.language}"
                            if subtitle_result.source_label and subtitle_result.language
                            else subtitle_result.source_label
                            or (subtitle_result.subtitle_path.name if subtitle_result.subtitle_path else "B站字幕")
                        ),
                    )
                    response.timings["download"] = 0.0
                    response.timings["extract_audio"] = 0.0
                    response.timings["transcribe"] = _elapsed(subtitle_start)
                    response.timings["whisper_model_load"] = 0.0
                    response.timings["whisper_decode"] = 0.0
                    set_many_complete(["extract_audio"])
                    complete_stage("transcribe")
                    add_log("extract_audio", "已获取字幕，跳过音频提取", "success", 0.0)
                    source_label = subtitle_result.source_label or "字幕"
                    language_suffix = f" · {subtitle_result.language}" if subtitle_result.language else ""
                    add_log(
                        "transcribe",
                        f"{source_label}{language_suffix}提取完成（{len(transcript)} 字）",
                        "success",
                        response.timings["transcribe"],
                    )
                    # The transcript is the durable source for the generated
                    # Markdown and later AI Q&A. ``use_cache`` controls large
                    # media reuse, not whether this essential text survives
                    # the save stage.
                    write_cached_subtitle_transcript(cache_dir, transcript)
                    write_cached_transcript_segments(cache_dir, "subtitle", transcript_segments)
                    write_cache_meta(
                        cache_dir,
                        {
                            "subtitle_source": subtitle_result.source,
                            "subtitle_trust": "browser_player_binding_v1",
                        },
                    )
                    if (should_auto_download_bilibili_video() or download_video_preview) and not subtitle_only:
                        add_log("download", "已获取字幕，后台下载本地视频预览；AI 总结将并行继续...")
                        start_parallel_bilibili_preview_download()
                    else:
                        complete_stage("download")
                        add_log(
                            "download",
                            "已获取字幕，只提取字幕，不下载视频" if subtitle_only else "已获取字幕，跳过视频下载",
                            "success",
                            0.0,
                        )
                else:
                    subtitle_fallback_reason = subtitle_result.error or "无字幕"
                    add_log(
                        "transcribe",
                        f"未获取到可用字幕，改用语音识别：{subtitle_fallback_reason}",
                        "warn",
                        _elapsed(subtitle_start),
                    )

            subtitle_cache_used = False
            if not force_video_download and not subtitle_used and cached_subtitle_transcript and trusted_bilibili_subtitle_cache:
                reuse_cached_subtitle()
                subtitle_cache_used = True

            if subtitle_only and not subtitle_used and not subtitle_cache_used:
                return fail("transcribe", "当前 B站播放器未提供可验证的外挂字幕；未下载视频，也未执行语音识别")

            asr_cache_used = False
            if not force_video_download and not subtitle_used and not subtitle_cache_used and cached_transcript:
                reuse_cached_asr_transcript()
                asr_cache_used = True

            if subtitle_used or subtitle_cache_used or asr_cache_used:
                pass
            else:
                if cached_video:
                    video_path = cached_video
                    response.video_path = str(video_path)
                    publish_video_artifact()
                    if not local_video_path:
                        response.cache_hits.append("video")
                    response.timings["download"] = 0.0
                    add_log("download", f"复用已下载视频: {video_path.name}", "success", 0.0)
                    set_download_transfer(DownloadProgress("caching", "正在生成视频预览"))
                    _ensure_preview_thumbnails(cache_dir, video_path, add_log)
                    complete_stage("download")
                else:
                    download_start = time.perf_counter()
                    add_log("download", "开始下载视频...")
                    dl_result = download_with_live_logs(parsed.url, parsed.platform, output_dir)

                    response.timings["download"] = _elapsed(download_start)
                    if not dl_result.success or not dl_result.video_path:
                        error = dl_result.error or "下载失败"
                        add_log("download", error, "error", response.timings["download"])
                        return fail("download", error)

                    video_path = dl_result.video_path
                    response.video_path = str(video_path)
                    if isinstance(dl_result.video_info, dict) and dl_result.video_info:
                        # The download adapter sees the final signed media detail
                        # and is authoritative for fields a preflight probe could
                        # not provide (Douyin deliberately skips that probe).
                        video_info = {
                            **(video_info or {}),
                            **{
                                key: value
                                for key, value in dl_result.video_info.items()
                                if value is not None and value != ""
                            },
                        }
                        if isinstance(video_info.get("source_context"), dict):
                            source_context = dict(video_info["source_context"])
                    publish_video_artifact()
                    if use_cache:
                        downloaded_at = datetime.now(timezone.utc)
                        meta_updates = {
                            "video_path": video_path.name,
                            "video_cache_status": "available",
                            "video_cache_downloaded_at": downloaded_at.isoformat(),
                            "video_cache_expires_at": (downloaded_at + timedelta(days=max(1, settings.video_cache_retention_days))).isoformat(),
                            "video_cache_expired_at": "",
                        }
                        if dl_result.video_info:
                            meta_updates["video_info"] = dl_result.video_info
                        write_cache_meta(cache_dir, meta_updates)
                        set_download_transfer(DownloadProgress("caching", "正在生成视频预览"))
                        _ensure_preview_thumbnails(cache_dir, video_path, add_log)
                    complete_stage("download")
                    add_log("download", f"下载完成: {video_path.name}", "success", response.timings["download"])

                if processing_mode == "download_only":
                    final_title = str((video_info or {}).get("title") or source_title or "未命名视频").strip()
                    response.display_title = final_title
                    set_many_complete(["extract_audio", "transcribe", "summarize", "save"])
                    response.timings["total"] = _elapsed(total_start)
                    response.success = True
                    response.error = None
                    if cache_dir:
                        write_cache_meta(cache_dir, {"pipeline_status": "succeeded", "pipeline_error": ""})
                    if response.content_item_id:
                        _set_content_status(response.content_item_id, "to_read")
                    add_log("save", "本地预览视频已恢复；保留原有文本与摘要", "success")
                    add_log("total", "视频重新下载完成", "success", response.timings["total"])
                    response.step = None
                    publish()
                    return response

                check_cancel()
                if local_media_is_audio:
                    # Never run ffmpeg with a WAV source and identical output:
                    # that can overwrite the user-retained original. The ASR
                    # backend accepts the uploaded audio file directly.
                    audio_path = video_path
                    response.timings["extract_audio"] = 0.0
                    complete_stage("extract_audio")
                    add_log("extract_audio", "本地音频已就绪，跳过音频提取", "success", 0.0)
                else:
                    audio_path = video_path.with_suffix(".wav")
                    extract_start = time.perf_counter()
                    add_log("extract_audio", "提取音频...")
                    set_progress("extract_audio", 30)
                    audio_result = extract_audio_with_details(
                        video_path,
                        audio_path,
                        progress_callback=lambda percent: set_progress("extract_audio", 30 + percent * 0.7),
                        cancel_check=cancel_check,
                    )
                    response.timings["extract_audio"] = round(audio_result.elapsed_seconds or _elapsed(extract_start), 2)
                    if getattr(audio_result, "cancelled", False) or (cancel_check and cancel_check()):
                        raise PipelineCancelled()
                    if not audio_result.success:
                        error = audio_result.error or "音频提取失败"
                        add_log("extract_audio", error, "error", response.timings["extract_audio"])
                        return fail("extract_audio", error)
                    complete_stage("extract_audio")
                    add_log("extract_audio", "音频提取完成", "success", response.timings["extract_audio"])

                check_cancel()
                transcribe_start = time.perf_counter()
                add_log("transcribe", f"开始语音识别（后端: {asr_options['backend']}，模型: {selected_model}，可能需要几分钟）...")
                transcribe_result = transcribe_with_details(
                    audio_path,
                    selected_model,
                    progress_callback=lambda percent: set_progress("transcribe", percent),
                    backend=asr_options["backend"],
                    beam_size=asr_options["beam_size"],
                    vad_filter=asr_options["vad_filter"],
                    fallback_enabled=asr_options["fallback_enabled"],
                )
                if not local_media_is_audio:
                    audio_path.unlink(missing_ok=True)
                response.timings["transcribe"] = _elapsed(transcribe_start)
                for key, value in transcribe_result.timings.items():
                    response.timings[key] = round(value, 2)

                if not transcribe_result.success:
                    error = transcribe_result.error or "转写失败"
                    add_log("transcribe", error, "error", response.timings["transcribe"])
                    return fail("transcribe", error)

                transcript = transcribe_result.transcript
                transcript_segments = getattr(transcribe_result, "segments", [])
                actual_backend = getattr(transcribe_result, "backend", "")
                response.asr_backend = actual_backend or response.asr_backend
                text_source_backend = "faster-whisper" if actual_backend in {"", "faster_whisper"} else actual_backend
                response.text_source = TextSourceInfo(
                    kind="asr",
                    source=text_source_backend,
                    detail=f"Whisper {selected_model}",
                    fallback_reason=subtitle_fallback_reason,
                )
                # Keep the compact text source even when large media caching
                # is disabled; the content document is saved immediately
                # afterwards and loads this transcript by content identity.
                write_cached_transcript(cache_dir, selected_model, transcript)
                write_cached_transcript_segments(cache_dir, selected_model, transcript_segments)

        response.transcript = transcript
        complete_stage("transcribe")
        if response.text_source and response.text_source.kind == "article":
            add_log("transcribe", f"正文提取完成（{len(transcript)} 字）", "success", response.timings["transcribe"])
        else:
            add_log("transcribe", f"转写完成（{len(transcript)} 字）", "success", response.timings["transcribe"])

        is_article = article_info is not None or parsed.platform == "wechat"
        if not content_item_id:
            manual_folder_id = None
            if manual_collection:
                initialize_database()
                with connect() as connection:
                    manual_folder_id = ensure_manual_collection_target_folder(connection, parsed.platform)
                    connection.commit()
            item = ensure_content_item_for_media(
                source_provider=parsed.platform,
                source_url=parsed.url,
                video_info=video_info,
                title=source_title,
                content_type="article" if is_article else "video",
                status="processing",
                library_folder_id=manual_folder_id,
            )
            content_item_id = item.id if item else None
            response.content_item_id = content_item_id

        if processing_mode == "transcript":
            final_title = (
                str((article_info or {}).get("title") or "").strip()
                or str((video_info or {}).get("title") or "").strip()
                or source_title
                or ("未命名公众号文章" if parsed.platform == "wechat" else "未命名视频")
            )
            response.display_title = final_title
            finish_parallel_bilibili_preview_download()
            set_many_complete(["summarize", "save"])
            response.timings["total"] = _elapsed(total_start)
            response.success = True
            response.error = None
            if cache_dir:
                write_cache_meta(cache_dir, {"pipeline_status": "succeeded", "pipeline_error": ""})
            if response.content_item_id:
                _set_content_title(response.content_item_id, final_title)
                _set_content_status(response.content_item_id, "to_read")
                try:
                    load_content_source_text(response.content_item_id)
                except (LookupError, OSError, ValueError):
                    add_log("save", "字幕已保存，正文快照将在下次读取时补齐", "warn")
            try:
                upsert_search_document(
                    content_key=content_item_id or response.task_id or parsed.url,
                    title=final_title,
                    summary="",
                    transcript=transcript,
                    source_context=source_context,
                )
            except Exception as exc:
                add_log("save", f"搜索索引更新失败：{exc}", "warn")
            add_log("save", "字幕提取完成，未调用 AI 总结", "success")
            response.step = None
            publish()
            return response

        if isinstance((video_info or {}).get("source_context"), dict):
            source_context = dict(video_info["source_context"])
        if parsed.platform == "bilibili" and not source_context_is_fresh(source_context):
            check_cancel()
            try:
                source_context = fetch_bilibili_source_context(parsed.url)
                if use_cache and cache_dir:
                    write_cache_meta(cache_dir, {"source_context": source_context})
                sample_count = int(source_context.get("comment_sample_count") or 0)
                add_log("info", f"已采集互动指标与 {sample_count} 条评论样本", "success")
            except Exception as exc:
                add_log("info", f"互动与评论采集失败，继续使用正文总结：{exc}", "warn")
            check_cancel()
        elif parsed.platform == "douyin" and not source_context_is_fresh(source_context):
            check_cancel()
            try:
                source_context = fetch_douyin_source_context(parsed.url)
                if use_cache and cache_dir:
                    write_cache_meta(cache_dir, {"source_context": source_context})
                sample_count = int(source_context.get("comment_sample_count") or 0)
                add_log("info", f"已采集互动指标与 {sample_count} 条评论样本", "success")
            except Exception as exc:
                add_log("info", f"互动与评论采集失败，继续使用正文总结：{exc}", "warn")
            check_cancel()
        elif source_context and use_cache and cache_dir:
            write_cache_meta(cache_dir, {"source_context": source_context})
        if source_context and content_item_id:
            try:
                with connect() as connection:
                    context_item = ContentRepository(connection).get_content_item(content_item_id)
                save_source_context(context_item, source_context)
            except Exception as exc:
                add_log("info", f"互动数据持久化失败，继续生成总结：{exc}", "warn")

        check_cancel()
        if not settings.deepseek_api_key:
            error = "未配置 DeepSeek API Key（请在设置 → 处理与 AI 中填写）"
            add_log("summarize", error, "error")
            return fail("summarize", error)

        summarize_start = time.perf_counter()
        add_log("summarize", "调用 DeepSeek 生成总结...")
        set_progress("summarize", 30)
        content_title = (
            str((article_info or {}).get("title") or "").strip()
            or str((video_info or {}).get("title") or "").strip()
            or source_title
        )
        try:
            ai_title, summary = summarize_stream(
                transcript,
                content_title,
                model=ai_model,
                task_type="article_summary" if is_article else "summary",
                task_id=response.task_id,
                content_item_id=content_item_id,
                ai_call_callback=remember_ai_call("summary"),
                transcript_segments=transcript_segments if not is_article else None,
                source_context=source_context,
                on_delta=publish_summary_delta,
            )
        except Exception as exc:
            response.timings["summarize"] = _elapsed(summarize_start)
            add_log("summarize", str(exc), "error", response.timings["summarize"])
            return fail("summarize", str(exc))

        response.timings["summarize"] = _elapsed(summarize_start)
        if not summary:
            add_log("summarize", "总结生成失败", "error", response.timings["summarize"])
            return fail("summarize", "总结生成失败")
        response.summary = summary
        complete_stage("summarize")
        add_log("summarize", f"总结完成，标题: {ai_title}", "success", response.timings["summarize"])

        check_cancel()
        save_start = time.perf_counter()
        final_title = ai_title
        if not final_title:
            final_title = (
                str((article_info or {}).get("title") or "").strip()
                or str((video_info or {}).get("title") or "").strip()
                or source_title
                or ("未命名公众号文章" if parsed.platform == "wechat" else "未命名视频")
            )

        response.display_title = final_title
        set_progress("save", 50)
        if content_item_id:
            _set_content_title(content_item_id, final_title)
            load_content_source_text(content_item_id)
            sync_state = replace_content_summary_and_sync(
                content_item_id,
                summary,
                drop_generated_title=not is_article,
            )
        else:
            full_info = {
                **(video_info or {}),
                "title": final_title,
                "platform": parsed.platform,
                "transcript": transcript,
                "source_context": source_context,
            }
            markdown = generate_article_markdown(summary, {**full_info, **(article_info or {}), "title": final_title, "body_text": transcript}, parsed.url) if is_article else generate_markdown(summary, full_info, parsed.url)
            fallback_path = settings.obsidian_vault / f"{response.task_id or 'untitled'}.md"
            sync_state = save_markdown_draft_and_sync(
                markdown=markdown,
                title=final_title,
                obsidian_path=fallback_path,
                content_item_id=None,
                draft_key=response.task_id or parsed.url,
            )
        obsidian_path = Path(sync_state.obsidian_path) if sync_state.obsidian_path else Path(sync_state.markdown_draft_path)
        response.obsidian_path = sync_state.obsidian_path
        response.markdown_draft_path = sync_state.markdown_draft_path
        if use_cache:
            write_cache_meta(
                cache_dir,
                {
                    "title": final_title,
                    "obsidian_path": str(obsidian_path),
                    "last_summary_at": datetime.now().isoformat(),
                },
            )
        if sync_state.sync_status == "synced":
            mark_stage("save", f"已自动写入 Markdown: {obsidian_path}", save_start)
        else:
            mark_stage("save", "Markdown 草稿已保存在本地，可从 AI 对话区导出", save_start)
        try:
            upsert_search_document(
                content_key=content_item_id or response.task_id or parsed.url,
                title=final_title,
                summary=summary,
                transcript=transcript,
                source_context=source_context,
            )
        except Exception as exc:
            add_log("save", f"搜索索引更新失败：{exc}", "warn")

        finish_parallel_bilibili_preview_download()
        response.timings["total"] = _elapsed(total_start)
        response.success = True
        response.error = None
        if cache_dir:
            write_cache_meta(cache_dir, {"pipeline_status": "succeeded", "pipeline_error": ""})
        if response.content_item_id:
            _set_content_title(response.content_item_id, final_title)
            _set_content_status(response.content_item_id, "to_read")
            try:
                # Persist the durable source document while the freshly fetched
                # article/subtitle is already available locally. This has no
                # model call and does not alter the existing summary pipeline.
                load_content_source_text(response.content_item_id)
            except (LookupError, OSError, ValueError):
                add_log("save", "内容库 Markdown 暂未写入，将在下次读取正文时补齐", "warn")
        add_log("total", "全流程完成", "success", response.timings["total"])
        response.step = None
        publish()
        return response
    except PipelineCancelled:
        add_log("cancelled", "任务已取消；如果当前阶段正在调用外部工具，取消会在该阶段结束后生效", "warn")
        return fail("cancelled", "任务已取消")


def _wechat_article_needs_ocr_refresh(article_info: object) -> bool:
    return isinstance(article_info, dict) and _content_source_text_needs_ocr_refresh(article_info)


def _set_content_status(content_item_id: str, status: str) -> None:
    try:
        initialize_database()
        with connect() as connection:
            connection.execute(
                "UPDATE content_items SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), content_item_id),
            )
            connection.commit()
    except Exception:
        return


def _set_content_title(content_item_id: str, title: str) -> None:
    safe_title = (title or "").strip()
    if not safe_title:
        return
    try:
        initialize_database()
        with connect() as connection:
            connection.execute(
                "UPDATE content_items SET title = ?, updated_at = ? WHERE id = ?",
                (safe_title, datetime.now().isoformat(), content_item_id),
            )
            connection.commit()
    except Exception:
        return


def _ensure_preview_thumbnails(
    cache_dir: Path | None,
    video_path: Path | None,
    add_log: Callable[[str, str, str, float | None], None],
) -> None:
    if not cache_dir or not video_path:
        return
    add_log("download", "正在准备播放器预览缩略图…", "info", None)
    preview_path = ensure_preview_thumbnails(cache_dir, video_path)
    if preview_path:
        add_log("download", "播放器预览缩略图已生成", "success", None)
