from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import uuid
from collections.abc import Callable

from config import settings
from services.cache import (
    cache_dir_for_url,
    find_cached_video,
    read_cache_meta,
    media_duration_seconds,
    read_cached_subtitle_transcript,
    read_cached_transcript,
    write_cached_transcript_segments,
    write_cache_meta,
    write_cached_subtitle_transcript,
)
from services.article_fetcher import fetch_article
from services.article_preview import ARTICLE_NORMALIZER_VERSION, normalize_article_html
from services.bilibili_context import fetch_bilibili_source_context
from services.published_at import PUBLISHED_AT_PARSER_VERSION
from services.pipeline_asr_policy import (
    ASR_MODEL_STRATEGIES, WHISPER_MODELS,  # noqa: F401 - public compatibility re-exports
    duration_from_info as _duration_from_info,
    normalize_asr_options as _normalize_asr_options,
    resolve_asr_model as _resolve_asr_model,
    validate_asr_configuration,
)
from services.pipeline_cached_text import PipelineCachedTextRestorer
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
    elapsed as _elapsed,
)
from services.pipeline_content_updates import (
    prepare_preview_thumbnails as _ensure_preview_thumbnails,
    set_content_status as _set_content_status,
    set_content_title as _set_content_title,
)
from services.pipeline_local_inputs import LocalInputError, prepare_local_media, prepare_local_subtitle
from services.pipeline_local_media_policy import is_managed_local_media as _is_managed_local_media
from services.pipeline_local_media_policy import is_under_data_dir as _is_under_data_dir
from services.pipeline_media_download import download_media_with_live_logs
from services.pipeline_run_reporter import PipelineRunReporter
from services.pipeline_source_context import refresh_pipeline_source_context
from services.pipeline_stored_article import (
    StoredArticlePreparationError,
    prepare_stored_article,
    run_prepared_stored_article,
)
from services.pipeline_transcription import PipelineTranscriptionError, transcribe_pipeline_media
from services.content_index import ensure_content_item_for_media, ensure_manual_collection_target_folder
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
from services.source_context_store import save_source_context
from services.summarizer import generate_article_markdown, generate_markdown, summarize, summarize_stream
from services.subtitles import fetch_bilibili_subtitle, parse_subtitle_text
from services.transcriber import ASR_BACKENDS, extract_audio_with_details, transcribe_with_details
from services.url_parser import parse_share_text, redact_sensitive_url
from services.video_download_settings import should_auto_download_bilibili_video


ProgressCallback = Callable[[PipelineResponse], None]
CancelCheck = Callable[[], bool]


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
    cache_dir: Path | None = None
    reporter = PipelineRunReporter(response, on_update)
    publish = reporter.publish
    update_overall_progress = reporter.update_overall_progress
    set_progress = reporter.set_progress
    set_download_transfer = reporter.set_download_transfer
    complete_stage = reporter.complete_stage
    add_log = reporter.add_log
    mark_stage = reporter.mark_stage
    set_many_complete = reporter.set_many_complete
    remember_ai_call = reporter.remember_ai_call
    publish_summary_delta = reporter.publish_summary_delta

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
            download_media_with_live_logs,
            parsed.url,
            parsed.platform,
            output_dir,
            add_log=add_log,
            set_download_transfer=set_download_transfer,
            check_cancel=check_cancel,
            provider_cancel_check=cancel_check,
            downloader=download_video,
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
        if cache_dir:
            write_cache_meta(cache_dir, {"pipeline_status": "failed", "pipeline_error": error})
        if response.content_item_id:
            _set_content_status(response.content_item_id, "failed")
        update_overall_progress()
        publish()
        return response

    try:
        asr_config_error = validate_asr_configuration(
            asr_options, selected_model=selected_model, supported_backends=ASR_BACKENDS
        )
        if asr_config_error:
            add_log("config", asr_config_error, "error")
            return fail("config", asr_config_error)

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

        # Persisted campus/RSS/XHS articles have their own preparation path;
        # they never enter link parsing, media download or ASR.
        try:
            stored_article = prepare_stored_article(
                content_item_id,
                add_log=add_log,
                load_source=load_content_source_text,
                persist_source_context=save_source_context,
            )
        except StoredArticlePreparationError as exc:
            return fail(exc.step, str(exc))
        if stored_article:
            return run_prepared_stored_article(
                stored_article,
                response=response,
                reporter=reporter,
                fail=fail,
                processing_mode=processing_mode,
                api_key_configured=bool(settings.deepseek_api_key),
                ai_model=ai_model,
                total_started_at=total_start,
                summarize_article=summarize,
                set_content_status=_set_content_status,
                set_content_title=_set_content_title,
                replace_summary=replace_content_summary_and_sync,
                update_search=upsert_search_document,
            )

        cached_video = None
        cached_subtitle_transcript = None
        cached_transcript = None
        transcript = ""
        transcript_segments: list[dict] = []
        article_info = None
        text_ready = False

        if local_subtitle_path:
            check_cancel()
            try:
                prepared_subtitle = prepare_local_subtitle(
                    local_subtitle_path,
                    source_url=source_url,
                    source_title=source_title,
                    content_item_id=content_item_id,
                    authorize=_is_managed_local_media,
                    parse_subtitle=parse_subtitle_text,
                    resolve_cache_dir=cache_dir_for_url,
                    cache_subtitle=write_cached_subtitle_transcript,
                )
            except LocalInputError as exc:
                add_log(exc.step, str(exc), "error")
                return fail(exc.step, str(exc))
            local_path = prepared_subtitle.path
            parsed = prepared_subtitle.source
            cache_dir = prepared_subtitle.cache_dir
            transcript = prepared_subtitle.transcript
            video_info = prepared_subtitle.video_info
            use_cache = False
            text_ready = True
            response.url = parsed.url
            response.platform = parsed.platform
            response.transcript = transcript
            response.text_source = prepared_subtitle.text_source
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
            # Imported originals may be deliberately retained beside the
            # external Markdown library (for example an Obsidian vault), not
            # below the private data directory.  Accept only application
            # managed attachments or the exact original registered for this
            # content item; never open an arbitrary local path from a task.
            try:
                prepared_media = prepare_local_media(
                    local_video_path,
                    source_url=source_url,
                    source_title=source_title,
                    content_item_id=content_item_id,
                    authorize=_is_managed_local_media,
                    resolve_cache_dir=cache_dir_for_url,
                    read_duration=media_duration_seconds,
                )
            except LocalInputError as exc:
                add_log(exc.step, str(exc), "error")
                return fail(exc.step, str(exc))
            local_path = prepared_media.path
            local_media_is_audio = prepared_media.is_audio
            parsed = prepared_media.source
            # A retranscription deliberately skips media reuse, but its new
            # transcript must still be written beside the retained source
            # video.  Without this, cache_dir remains None and the cache
            # writer fails after ASR has already completed.
            cache_dir = prepared_media.cache_dir
            video_info = prepared_media.video_info
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

        cached_text_restorer = PipelineCachedTextRestorer(
            response=response,
            cache_dir=cache_dir,
            cached_video=cached_video,
            publish_video_artifact=publish_video_artifact,
            set_many_complete=set_many_complete,
            add_log=add_log,
        )

        # An explicit subtitle retry is deliberately fresh: an old source
        # snapshot may be an ASR transcript and must not make the command look
        # successful without consulting the current Bilibili player.
        if text_ready and not subtitle_only:
            pass
        elif not force_video_download and cached_subtitle_transcript and not refresh_bilibili_subtitle:
            transcript, transcript_segments = cached_text_restorer.restore_subtitle(cached_subtitle_transcript)
        elif not force_video_download and cached_transcript and not refresh_bilibili_subtitle:
            transcript, transcript_segments = cached_text_restorer.restore_asr(cached_transcript, selected_model)
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
                transcript, transcript_segments = cached_text_restorer.restore_subtitle(cached_subtitle_transcript)
                subtitle_cache_used = True

            if subtitle_only and not subtitle_used and not subtitle_cache_used:
                return fail("transcribe", "当前 B站播放器未提供可验证的外挂字幕；未下载视频，也未执行语音识别")

            asr_cache_used = False
            if not force_video_download and not subtitle_used and not subtitle_cache_used and cached_transcript:
                transcript, transcript_segments = cached_text_restorer.restore_asr(cached_transcript, selected_model)
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
                    dl_result = download_media_with_live_logs(
                        parsed.url,
                        parsed.platform,
                        output_dir,
                        add_log=add_log,
                        set_download_transfer=set_download_transfer,
                        check_cancel=check_cancel,
                        provider_cancel_check=cancel_check,
                        downloader=download_video,
                    )

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

                try:
                    transcript, transcript_segments = transcribe_pipeline_media(
                        video_path,
                        local_media_is_audio=local_media_is_audio,
                        selected_model=selected_model,
                        asr_options=asr_options,
                        subtitle_fallback_reason=subtitle_fallback_reason,
                        cache_dir=cache_dir,
                        response=response,
                        reporter=reporter,
                        check_cancel=check_cancel,
                        provider_cancel_check=cancel_check,
                        extract_audio=extract_audio_with_details,
                        transcribe=transcribe_with_details,
                    )
                except PipelineTranscriptionError as exc:
                    return fail(exc.step, str(exc))

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
        source_context = refresh_pipeline_source_context(
            platform=parsed.platform,
            url=parsed.url,
            source_context=source_context,
            use_cache=use_cache,
            cache_dir=cache_dir,
            content_item_id=content_item_id,
            add_log=add_log,
            check_cancel=check_cancel,
            fetch_bilibili=fetch_bilibili_source_context,
            fetch_douyin=fetch_douyin_source_context,
        )

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
