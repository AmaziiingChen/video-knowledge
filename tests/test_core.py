import hashlib
import json
import subprocess
import sys
import tempfile
import time
import threading
import unittest
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient

from config import settings
from main import app
from routers.cookie import _write_netscape_cookie_file
from routers.qa import _require_regenerable_content
from services.bilibili_auth import bilibili_yt_dlp_cookie_args, get_bilibili_cookie_status, save_bilibili_cookie
from services.ai_call_logger import record_ai_call, record_image_generation_call
from services.cache import (
    cache_dir_for_url,
    cache_key_for_url,
    ensure_preview_thumbnails,
    list_cache_entries,
    read_cache_meta,
    read_cached_transcript,
    write_cache_meta,
    write_cached_subtitle_transcript,
    write_cached_transcript,
)
from services.clipboard_watcher import ClipboardWatcher, extract_supported_links, read_system_clipboard
from services.clipboard_settings import load_clipboard_watcher_settings, save_clipboard_watcher_settings
from services.folder_import_settings import load_folder_import_watcher_settings, save_folder_import_watcher_settings
from services.folder_import_watcher import FolderImportWatcher
from services.content_analysis import create_content_analysis, list_content_analyses
from services.content_index import ensure_content_item_for_media
from services.knowledge_library import materialize_source_document
from services.content_source_text import (
    ContentSourceText,
    _article_text_readiness,
    _wechat_article_needs_ocr_refresh,
    inspect_content_text_readiness,
    load_content_source_text,
)
from services.database import SCHEMA_VERSION, connect, initialize_database
from services.douyin_cookie_status import get_douyin_cookie_status, invalidate_douyin_cookie_status
from services.douyin_cookie_status import _douyin_page_login_state
from services.downloader import (
    BILIBILI_1080P_FORMAT,
    _browser_capture_failure_message,
    _compress_video_for_storage,
    _lowest_douyin_video_variant,
    _looks_like_douyin_video_url,
    _needs_douyin_media_refresh,
    _yt_dlp_bytes_per_second,
)
from services.inbox import capture_link_to_inbox, list_inbox_items, process_inbox_item
from services.llm_settings import (
    load_llm_settings,
    reveal_campus_embedding_api_key,
    reveal_deepseek_api_key,
    save_campus_embedding_settings,
    save_deepseek_settings,
    test_campus_embedding_connection as run_campus_embedding_connection_test,
    test_deepseek_connection as run_deepseek_connection_test,
)
from services.llm_provider import LLMMessage, LLMResponse, LLMUsage, resolve_deepseek_model
from services.markdown_sync import (
    get_markdown_state,
    replace_content_summary_and_sync,
    replace_article_summary_and_sync,
    save_markdown_draft_and_sync,
    sync_markdown_to_obsidian,
    update_markdown_draft,
)
from services.obsidian_settings import is_managed_obsidian_note_path, save_obsidian_settings
from services.pipeline_runner import PipelineRequest, PipelineResponse, classify_pipeline_error, run_pipeline_sync
from services.paddle_ocr import OcrImageResult, _extract_json_result_text, _recognize_one, _wait_for_result
from services import paddle_ocr
from services.local_file_imports import run_pdf_import
from services.paddle_ocr_settings import (
    load_paddle_ocr_settings,
    reveal_paddle_ocr_access_token,
    save_paddle_ocr_settings,
)
from services.providers.bilibili import BilibiliProvider
from services.providers.douyin import DouyinProvider
from services.providers.registry import get_provider_for_url
from services.prompt_templates import PromptTemplateRepository
from services.repository import ContentRepository, TaskRepository
from services.runtime_components import (
    HUGGING_FACE_HUB_ENDPOINT,
    HUGGING_FACE_HUB_FALLBACK_ENDPOINT,
    MLX_WHISPER_REPOS,
    _download_progress_class,
    _mlx_model_available,
    mlx_whisper_model_dir,
)
from services.search_index import rebuild_search_index, search_documents, upsert_search_document, upsert_source_text_document
from services.subtitles import (
    SubtitleFetchResult,
    _browser_bound_bilibili_tracks,
    _fetch_best_browser_bilibili_subtitle_candidate,
    fetch_bilibili_subtitle,
    parse_subtitle_text,
)
from services.article_fetcher import ArticleFetchResult, _image_filter_reason
from services.article_preview import ARTICLE_NORMALIZER_VERSION
from services.summarizer import (
    QA_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    answer_question,
    append_qa_to_markdown,
    generate_article_markdown,
    generate_markdown,
    stream_regenerated_content_summary,
    stream_regenerated_article_summary,
    summarize,
    stream_answer_question,
)
from services.task_manager import TaskManager, TaskRecord
from services.text_normalizer import normalize_transcript_segments, normalize_transcript_text
from services.transcriber import TranscriptionResult, transcribe_with_details
from services.telegram_settings import load_telegram_settings, save_telegram_settings
from services.telegram_watcher import TelegramWatcher
from services.watcher_restore import restore_enabled_watchers
from services.url_parser import parse_share_text
from services.wechat_subscription import WeChatSubscriptionScheduler, WeChatSubscriptionService


class UrlParserTests(unittest.TestCase):
    def test_parse_share_text_supports_douyin_short_url(self):
        parsed = parse_share_text("复制这条内容 https://v.douyin.com/abc123/ 打开抖音")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.platform, "douyin")
        self.assertEqual(parsed.url, "https://v.douyin.com/abc123/")

    def test_parse_share_text_keeps_bilibili_page_number_for_player_subtitles(self):
        parsed = parse_share_text("https://www.bilibili.com/video/BV1xx411c7mD?p=2")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.platform, "bilibili")
        self.assertEqual(parsed.url, "https://www.bilibili.com/video/BV1xx411c7mD?p=2")

    def test_parse_share_text_supports_douyin_canonical_video_url(self):
        parsed = parse_share_text("https://www.douyin.com/video/7383262718230351154")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.platform, "douyin")
        self.assertEqual(parsed.url, "https://www.douyin.com/video/7383262718230351154")

    def test_parse_share_text_supports_bilibili_video_url(self):
        parsed = parse_share_text("https://www.bilibili.com/video/BV1xx411c7mD")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.platform, "bilibili")

    def test_parse_share_text_supports_bilibili_short_url(self):
        parsed = parse_share_text("看这个 https://b23.tv/abc123")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.platform, "bilibili")

    def test_parse_share_text_rejects_text_without_url(self):
        self.assertIsNone(parse_share_text("这里没有可处理的视频链接"))


class AsrBackendTests(unittest.TestCase):
    def test_mlx_whisper_repositories_use_current_public_names(self):
        self.assertEqual(HUGGING_FACE_HUB_ENDPOINT, "https://hf-mirror.com")
        self.assertEqual(HUGGING_FACE_HUB_FALLBACK_ENDPOINT, "https://huggingface.co")
        self.assertEqual(MLX_WHISPER_REPOS["base"], "mlx-community/whisper-base-mlx")
        self.assertEqual(MLX_WHISPER_REPOS["small"], "mlx-community/whisper-small-mlx")
        self.assertEqual(MLX_WHISPER_REPOS["large-v3"], "mlx-community/whisper-large-v3-mlx")

    def test_mlx_npz_weights_are_recognized_as_downloaded_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_data_dir = settings.data_dir
            settings.data_dir = Path(temp_dir)
            try:
                model_dir = mlx_whisper_model_dir("base")
                model_dir.mkdir(parents=True)
                (model_dir / "config.json").write_text("{}", encoding="utf-8")
                (model_dir / "weights.npz").write_bytes(b"weights")

                self.assertTrue(_mlx_model_available("base"))
            finally:
                settings.data_dir = original_data_dir

    def test_model_download_progress_adapter_exposes_tqdm_class_api(self):
        progress_class = _download_progress_class("model:mlx:base")

        self.assertTrue(callable(progress_class.get_lock))
        self.assertIsNotNone(progress_class.get_lock())
        with progress_class(total=2) as progress:
            progress.update(1)
            self.assertEqual(progress.current, 1)

        self.assertEqual(list(progress_class(["first", "second"], total=2)), ["first", "second"])

    def test_transcript_normalizer_converts_traditional_chinese_and_keeps_english(self):
        text = normalize_transcript_text("這是一個 AI Workflow 測試，支援 Cache。")

        self.assertEqual(text, "这是一个 AI Workflow 测试，支援 Cache。")

    def test_transcript_normalizer_converts_segment_text(self):
        segments = normalize_transcript_segments([
            {"start_seconds": 0, "end_seconds": 1, "text": "這是第一句"},
            {"start_seconds": 1, "end_seconds": 2, "text": "English term 保持"},
        ])

        self.assertEqual(segments[0]["text"], "这是第一句")
        self.assertEqual(segments[1]["text"], "English term 保持")

    def test_auto_backend_uses_mlx_on_apple_silicon(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            audio_path.write_bytes(b"")

            with (
                patch("services.transcriber.preferred_asr_backend", return_value="mlx"),
                patch(
                    "services.transcriber._transcribe_mlx",
                    return_value=TranscriptionResult(success=True, transcript="文本", backend="mlx"),
                ) as mlx_mock,
                patch("services.transcriber._transcribe_faster_whisper") as faster_mock,
            ):
                result = transcribe_with_details(audio_path, "base", backend="auto")

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "mlx")
        mlx_mock.assert_called_once()
        faster_mock.assert_not_called()

    def test_mlx_backend_falls_back_to_faster_whisper(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            audio_path.write_bytes(b"")

            with (
                patch("services.transcriber.preferred_asr_backend", return_value="mlx"),
                patch(
                    "services.transcriber._transcribe_mlx",
                    return_value=TranscriptionResult(success=False, error="mlx failed", backend="mlx"),
                ) as mlx_mock,
                patch(
                    "services.transcriber._transcribe_faster_whisper",
                    return_value=TranscriptionResult(success=True, transcript="文本", backend="faster_whisper"),
                ) as faster_mock,
            ):
                result = transcribe_with_details(audio_path, "base", backend="mlx", fallback_enabled=True)

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "faster_whisper")
        mlx_mock.assert_called_once()
        faster_mock.assert_called_once()


class SourceProviderTests(unittest.TestCase):
    def test_registry_selects_douyin_and_bilibili_providers(self):
        self.assertEqual(get_provider_for_url("https://v.douyin.com/abc123/").name, "douyin")
        self.assertEqual(get_provider_for_url("https://www.bilibili.com/video/BV1xx411c7mD").name, "bilibili")
        self.assertIsNone(get_provider_for_url("https://example.com/video"))

    def test_bilibili_provider_resolves_canonical_bvid_and_metadata(self):
        provider = BilibiliProvider(
            info_loader=lambda url, platform: {
                "title": "B站测试",
                "duration": 66,
                "thumbnail": "https://example.com/cover.jpg",
            }
        )

        resolved = provider.resolve("https://www.bilibili.com/video/BV1xx411c7mD?p=2")

        self.assertEqual(resolved.provider, "bilibili")
        self.assertEqual(resolved.source_url, "https://www.bilibili.com/video/BV1xx411c7mD?p=2")
        self.assertEqual(resolved.canonical_source_id, "BV1xx411c7mD:p2")
        self.assertEqual(resolved.title, "B站测试")
        self.assertEqual(resolved.duration_seconds, 66.0)
        self.assertEqual(resolved.metadata["page_number"], 2)

    def test_douyin_provider_resolves_video_or_note_id(self):
        provider = DouyinProvider(info_loader=lambda url, platform: {"title": "抖音测试"})

        resolved = provider.resolve("https://www.douyin.com/video/7660847053097979199")

        self.assertEqual(resolved.provider, "douyin")
        self.assertEqual(resolved.canonical_source_id, "7660847053097979199")
        self.assertEqual(resolved.title, "抖音测试")


class ClipboardWatcherTests(unittest.TestCase):
    def test_system_clipboard_uses_windows_powershell(self):
        completed = SimpleNamespace(returncode=0, stdout="https://b23.tv/example\n", stderr="")
        with patch("services.clipboard_watcher.platform.system", return_value="Windows"), patch(
            "services.clipboard_watcher.subprocess.run", return_value=completed
        ) as run:
            self.assertEqual(read_system_clipboard(), "https://b23.tv/example\n")

        self.assertEqual(run.call_args.args[0], ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"])

    def test_system_clipboard_rejects_unknown_platform(self):
        with patch("services.clipboard_watcher.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(RuntimeError, "macOS 和 Windows"):
                read_system_clipboard()

    def test_extract_supported_links_deduplicates_video_links(self):
        links = extract_supported_links(
            "抖音 https://v.douyin.com/abc123/ "
            "B站 https://www.bilibili.com/video/BV1xx411c7mD "
            "短链 https://b23.tv/xyz987 "
            "重复 https://v.douyin.com/abc123/"
        )

        self.assertEqual(
            links,
            [
                "https://v.douyin.com/abc123/",
                "https://www.bilibili.com/video/BV1xx411c7mD",
                "https://b23.tv/xyz987",
            ],
        )

    def test_clipboard_watcher_scan_text_creates_tasks_once(self):
        created_requests = []

        def fake_create(request):
            created_requests.append(request)
            return SimpleNamespace(task_id=f"task-{len(created_requests)}")

        watcher = ClipboardWatcher(task_creator=fake_create, clipboard_reader=lambda: "")
        watcher.start(whisper_model="base", use_cache=False, capture_mode="task")
        watcher.stop()

        first = watcher.scan_text("https://b23.tv/abc123")
        second = watcher.scan_text("https://b23.tv/abc123")
        retry = watcher.scan_text("重试 https://b23.tv/abc123")

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)
        self.assertEqual(len(retry), 1)
        self.assertEqual(created_requests[0].share_text, "https://b23.tv/abc123")
        self.assertEqual(created_requests[0].whisper_model, "base")
        self.assertFalse(created_requests[0].use_cache)
        self.assertEqual(created_requests[1].share_text, "https://b23.tv/abc123")

    def test_clipboard_watcher_defaults_to_manual_processing(self):
        created_requests = []

        def fake_create(request):
            created_requests.append(request)
            return SimpleNamespace(task_id=f"task-{len(created_requests)}")

        watcher = ClipboardWatcher(task_creator=fake_create, clipboard_reader=lambda: "")
        watcher.start()
        watcher.stop()

        first = watcher.scan_text("https://www.bilibili.com/video/BV1xx411c7mD")
        second = watcher.scan_text("https://www.bilibili.com/video/BV1xx411c7mD")
        retry = watcher.scan_text("稍后再看 https://www.bilibili.com/video/BV1xx411c7mD")

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)
        self.assertEqual(len(retry), 1)
        self.assertIsNone(first[0].item_id)
        self.assertIsNotNone(first[0].task_id)
        self.assertEqual(first[0].capture_mode, "task")
        self.assertFalse(retry[0].duplicate)
        self.assertEqual(created_requests[0].execution_mode, "background")

    def test_clipboard_watcher_restore_primes_current_clipboard_without_creating_task(self):
        created_requests = []

        def fake_create(request):
            created_requests.append(request)
            return SimpleNamespace(task_id=f"task-{len(created_requests)}")

        watcher = ClipboardWatcher(
            task_creator=fake_create,
            clipboard_reader=lambda: "https://www.bilibili.com/video/BV1xx411c7mD",
        )
        watcher.start(skip_current_clipboard=True)
        watcher.stop()

        self.assertEqual(watcher.scan_text("https://www.bilibili.com/video/BV1xx411c7mD"), [])
        self.assertEqual(len(watcher.scan_text("https://b23.tv/new-link")), 1)
        self.assertEqual(len(created_requests), 1)


class WatcherPersistenceTests(unittest.TestCase):
    def test_clipboard_settings_persist_enabled_listener_options(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                saved = save_clipboard_watcher_settings(
                    {"enabled": True, "whisper_model": "small", "poll_interval": 2.5, "capture_mode": "task"}
                )

                self.assertTrue(saved["enabled"])
                self.assertEqual(load_clipboard_watcher_settings()["whisper_model"], "small")
        finally:
            settings.data_dir = old_data_dir

    def test_folder_import_settings_require_an_accessible_directory(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                inbox = Path(temp_dir) / "inbox"
                inbox.mkdir()
                saved = save_folder_import_watcher_settings(
                    {"enabled": True, "folder_path": str(inbox), "poll_interval": 15}
                )
                self.assertTrue(saved["enabled"])
                self.assertEqual(load_folder_import_watcher_settings()["folder_path"], str(inbox.resolve()))
                with self.assertRaisesRegex(ValueError, "收件箱"):
                    save_folder_import_watcher_settings({"enabled": True, "folder_path": str(inbox / "missing")})
        finally:
            settings.data_dir = old_data_dir

    def test_folder_import_watcher_ignores_existing_then_imports_new_supported_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            inbox = Path(temp_dir)
            (inbox / "already.md").write_text("# already", encoding="utf-8")
            watcher = FolderImportWatcher()
            with patch("services.local_folder_import.import_folder_file", return_value={"content_item_id": "item-1", "task_id": None}):
                watcher.start(folder_path=str(inbox), poll_interval=10, skip_existing=True)
                self.assertEqual(watcher.scan_once(), [])
                (inbox / "new.md").write_text("# new", encoding="utf-8")
                events = watcher.scan_once()
                watcher.stop()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].content_item_id, "item-1")
            self.assertFalse(events[0].error)

    def test_telegram_watcher_restores_cursor_and_persists_completed_updates(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "services.telegram_settings._load_keychain_token", return_value="test-token"
            ), patch("services.telegram_settings._save_keychain_token"):
                settings.data_dir = Path(temp_dir)
                save_telegram_settings(
                    {
                        "bot_token": "test-token",
                        "allowed_user_ids": [100],
                        "reply_enabled": False,
                        "watch_enabled": True,
                        "watch_options": {"whisper_model": "small", "use_cache": False},
                        "last_update_id": 41,
                    }
                )
                watcher = TelegramWatcher()
                with patch("services.telegram_watcher.save_telegram_watcher_checkpoint") as checkpoint:
                    watcher._handle_updates(
                        [{"update_id": 42, "message": {"text": "无链接", "from": {"id": 100}, "chat": {"id": 100}}}]
                    )

                self.assertEqual(watcher.status()["last_update_id"], 42)
                self.assertEqual(watcher.status()["whisper_model"], "small")
                self.assertFalse(watcher.status()["use_cache"])
                checkpoint.assert_called_once_with(42)
        finally:
            settings.data_dir = old_data_dir

    def test_restore_enabled_watchers_restores_supported_listeners_only(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                save_clipboard_watcher_settings({"enabled": True, "whisper_model": "base"})
                with patch("services.watcher_restore.clipboard_watcher.start") as clipboard_start:
                    restore_enabled_watchers()

                self.assertTrue(clipboard_start.call_args.kwargs["skip_current_clipboard"])
        finally:
            settings.data_dir = old_data_dir


class ClipboardWatcherApiTests(unittest.TestCase):
    def test_clipboard_watcher_status_defaults_to_stopped(self):
        client = TestClient(app)

        response = client.get("/api/clipboard-watcher")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["running"])

    def test_clipboard_watcher_rejects_unknown_model(self):
        client = TestClient(app)

        response = client.post(
            "/api/clipboard-watcher/start",
            json={"whisper_model": "not-a-model"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("不支持", response.json()["detail"])


class OpenClawGatewayApiTests(unittest.TestCase):
    def test_openclaw_gateway_status_is_exposed(self):
        expected = {
            "state": "not_installed",
            "detail": "Gateway 服务尚未安装",
            "installed": True,
            "service_installed": False,
            "gateway_running": False,
            "version": "2026.6.11",
            "checked_at": "2026-07-13T00:00:00+00:00",
        }
        with patch("routers.openclaw.get_openclaw_status", return_value=expected):
            response = TestClient(app).get("/api/openclaw-gateway")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_openclaw_gateway_start_is_exposed(self):
        expected = {
            "state": "running",
            "detail": "Gateway 与本地 RPC 已连接",
            "installed": True,
            "service_installed": True,
            "gateway_running": True,
            "version": "2026.6.11",
            "checked_at": "2026-07-13T00:00:00+00:00",
        }
        with patch("routers.openclaw.start_openclaw_gateway", return_value=expected):
            response = TestClient(app).post("/api/openclaw-gateway/start")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)


class OpenClawGatewayServiceTests(unittest.TestCase):
    def test_status_includes_the_complete_wechat_ingest_path(self):
        from services import openclaw_gateway

        gateway = {
            "state": "running",
            "detail": "Gateway 与本地 RPC 已连接",
            "installed": True,
            "service_installed": True,
            "gateway_running": True,
            "version": "2026.6.11",
            "checked_at": "2026-07-22T00:00:00+00:00",
        }
        wechat = {"state": "running", "configured": True, "running": True, "detail": "微信通道已连接"}
        mcp = {"state": "configured", "configured": True, "detail": "KnowledgeHub MCP 已配置"}

        with (
            patch("services.openclaw_gateway._gateway_status", return_value=gateway),
            patch("services.openclaw_gateway._wechat_channel_status", return_value=wechat),
            patch("services.openclaw_gateway._mcp_status", return_value=mcp),
            patch("services.openclaw_gateway._backend_status", return_value={"state": "running", "ready": True, "detail": "后端可用"}),
        ):
            status = openclaw_gateway.get_openclaw_status(force_refresh=True)

        self.assertTrue(status["automation_ready"])
        self.assertEqual(status["wechat"]["state"], "running")
        self.assertEqual(status["mcp"]["state"], "configured")
        self.assertTrue(status["backend"]["ready"])

    def test_start_waits_for_gateway_to_accept_rpc_connections(self):
        from services.openclaw_gateway import start_openclaw_gateway

        not_installed = {
            "state": "not_installed",
            "detail": "Gateway 服务尚未安装",
            "installed": True,
            "service_installed": False,
            "gateway_running": False,
        }
        offline = {**not_installed, "state": "offline", "service_installed": True, "detail": "连接被拒绝"}
        running = {**offline, "state": "running", "gateway_running": True, "detail": "Gateway 与本地 RPC 已连接"}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("services.openclaw_gateway.get_openclaw_status", side_effect=[not_installed, offline, running]),
            patch("services.openclaw_gateway._run_openclaw", return_value=completed) as run_openclaw,
            patch("services.openclaw_gateway.time.sleep") as sleep,
        ):
            result = start_openclaw_gateway()

        self.assertTrue(result["gateway_running"])
        self.assertEqual(run_openclaw.call_count, 2)
        sleep.assert_called_once_with(0.75)


class ContentLibraryApiTests(unittest.TestCase):
    def test_external_html_and_docx_import_keep_originals_and_create_askable_markdown(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                initialize_database()
                client = TestClient(app)

                html_result = client.post(
                    "/api/content/import-file",
                    files={"file": ("资料.html", "<html><head><title>安全标题</title><script>alert(1)</script></head><body><h1>正文标题</h1><p>可追问正文。</p></body></html>".encode("utf-8"), "text/html")},
                )
                self.assertEqual(html_result.status_code, 200)
                html_item = html_result.json()["item"]
                self.assertEqual(html_item["source_provider"], "local_file")
                self.assertTrue(html_item["text_readiness"]["can_ask_ai"])
                markdown = client.get(f"/api/markdown/content/{html_item['id']}").json()["markdown"]
                self.assertIn("可追问正文。", markdown)
                self.assertNotIn("alert(1)", markdown)
                attachment_dir = settings.data_dir / "attachments" / html_item["id"]
                self.assertTrue(any(path.name.startswith("original--") for path in attachment_dir.iterdir()))

                payload = io.BytesIO()
                with zipfile.ZipFile(payload, "w") as archive:
                    archive.writestr(
                        "word/document.xml",
                        """<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>Word 标题</w:t></w:r></w:p><w:p><w:r><w:t>Word 正文可追问。</w:t></w:r></w:p></w:body></w:document>""",
                    )
                docx_result = client.post(
                    "/api/content/import-file",
                    files={"file": ("资料.docx", payload.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                )
                self.assertEqual(docx_result.status_code, 200)
                docx_item = docx_result.json()["item"]
                self.assertTrue(docx_item["text_readiness"]["can_ask_ai"])
                docx_markdown = client.get(f"/api/markdown/content/{docx_item['id']}").json()["markdown"]
                self.assertIn("Word 正文可追问。", docx_markdown)
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_external_pdf_and_video_import_create_visible_durable_placeholders(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                initialize_database()
                client = TestClient(app)
                created = SimpleNamespace(task_id="external-task")
                with patch("routers.content.task_manager.create", return_value=created):
                    pdf_result = client.post(
                        "/api/content/import-file",
                        files={"file": ("扫描件.pdf", b"%PDF-1.4\nplaceholder", "application/pdf")},
                    )
                    video_result = client.post(
                        "/api/content/import-file",
                        files={"file": ("课堂.mp4", b"video-bytes", "video/mp4")},
                    )
                self.assertEqual(pdf_result.status_code, 200)
                self.assertTrue(pdf_result.json()["processing"])
                self.assertEqual(pdf_result.json()["task_id"], "external-task")
                self.assertEqual(pdf_result.json()["item"]["status"], "processing")
                pdf_item = pdf_result.json()["item"]
                self.assertTrue(pdf_item["original_file_path"].endswith("original--扫描件.pdf"))
                pdf_media = client.get("/api/media", params={"path": pdf_item["original_file_path"]})
                self.assertEqual(pdf_media.status_code, 200)
                self.assertEqual(pdf_media.headers["content-type"], "application/pdf")
                self.assertEqual(video_result.status_code, 200)
                self.assertEqual(video_result.json()["item"]["content_type"], "video")
                self.assertTrue(video_result.json()["item"]["video_path"].endswith("original--课堂.mp4"))
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_external_audio_and_image_import_keep_originals_and_reprocess(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                initialize_database()
                client = TestClient(app)
                with patch("routers.content.task_manager.create", return_value=SimpleNamespace(task_id="external-task")):
                    audio = client.post(
                        "/api/content/import-file",
                        files={"file": ("访谈.mp3", b"audio-bytes", "audio/mpeg")},
                    )
                    image = client.post(
                        "/api/content/import-file",
                        files={"file": ("扫描图.png", b"not-a-real-png", "image/png")},
                    )
                self.assertEqual(audio.status_code, 200)
                self.assertEqual(audio.json()["item"]["content_type"], "audio")
                self.assertTrue(audio.json()["item"]["video_path"].endswith("original--访谈.mp3"))
                self.assertEqual(image.status_code, 200)
                image_item = image.json()["item"]
                self.assertEqual(image_item["content_type"], "image")
                self.assertTrue(image_item["original_file_path"].endswith("original--扫描图.png"))
                with patch("routers.content.task_manager.create", return_value=SimpleNamespace(task_id="retry-task")):
                    retried = client.post(f"/api/content/{image_item['id']}/reprocess-local-source")
                self.assertEqual(retried.status_code, 200)
                self.assertEqual(retried.json()["task_id"], "retry-task")
                self.assertEqual(retried.json()["item"]["status"], "processing")
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_external_pdf_task_writes_ocr_text_to_the_same_question_markdown(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                initialize_database()
                client = TestClient(app)
                with patch("routers.content.task_manager.create", return_value=SimpleNamespace(task_id="external-task")):
                    imported = client.post(
                        "/api/content/import-file",
                        files={"file": ("扫描件.pdf", b"%PDF-1.4\nplaceholder", "application/pdf")},
                    ).json()["item"]
                original = settings.data_dir / "attachments" / imported["id"] / "original--扫描件.pdf"
                with patch(
                    "services.local_file_imports.recognize_document_bytes",
                    return_value=OcrImageResult(url="local", text="OCR 正文可追问。", status="succeeded"),
                ):
                    result = run_pdf_import(
                        content_item_id=imported["id"],
                        original_path=str(original),
                        task_id="external-task",
                    )
                self.assertTrue(result.success)
                markdown = client.get(f"/api/markdown/content/{imported['id']}").json()["markdown"]
                self.assertIn("OCR 正文可追问。", markdown)
                self.assertIn("## 追问记录", markdown)
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_pending_pdf_ocr_is_materialized_after_the_background_job_returns(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                initialize_database()
                client = TestClient(app)
                with patch("routers.content.task_manager.create", return_value=SimpleNamespace(task_id="external-task")):
                    imported = client.post(
                        "/api/content/import-file",
                        files={"file": ("扫描件.pdf", b"%PDF-1.4\npending", "application/pdf")},
                    ).json()["item"]
                original = settings.data_dir / "attachments" / imported["id"] / "original--扫描件.pdf"
                with patch(
                    "services.local_file_imports.recognize_document_bytes",
                    return_value=OcrImageResult(url="local", status="pending", error="图片识别仍在处理中"),
                ):
                    submitted = run_pdf_import(
                        content_item_id=imported["id"],
                        original_path=str(original),
                        task_id="external-task",
                    )
                self.assertTrue(submitted.success)
                digest = hashlib.sha256(original.read_bytes()).hexdigest()
                paddle_ocr._prepare_ocr_job(
                    digest,
                    content_item_id=imported["id"],
                    source_url=f"local-file:{imported['id']}",
                    cached_path="",
                )
                paddle_ocr._refresh_ocr_consumers(digest, text="后台 OCR 正文可追问。")
                markdown = client.get(f"/api/markdown/content/{imported['id']}").json()["markdown"]
                self.assertIn("后台 OCR 正文可追问。", markdown)
                detail = client.get(f"/api/content/item/{imported['id']}").json()
                self.assertEqual(detail["status"], "to_read")
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_imported_markdown_uses_the_external_import_tree(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                initialize_database()
                client = TestClient(app)

                first = client.post(
                    "/api/content/import-markdown",
                    files={"file": ("第一篇.md", "# 第一篇\n\n可在右侧提问。".encode("utf-8"), "text/markdown")},
                )
                self.assertEqual(first.status_code, 200)
                folders = client.get("/api/content/folders").json()
                external_root = next(folder for folder in folders if folder["name"] == "外部导入")
                self.assertEqual(first.json()["library_folder_id"], external_root["id"])
                self.assertTrue(first.json()["text_readiness"]["can_ask_ai"])
                preview_source = client.get(f"/api/markdown/content/{first.json()['id']}")
                self.assertEqual(preview_source.status_code, 200)
                self.assertIn("可在右侧提问。", preview_source.json()["markdown"])
                self.assertEqual(client.get("/api/tasks").json(), [])

                child = client.post(
                    "/api/content/folders",
                    json={"name": "研究资料", "parent_folder_id": external_root["id"]},
                )
                self.assertEqual(child.status_code, 200)
                second = client.post(
                    "/api/content/import-markdown",
                    data={"library_folder_id": child.json()["id"]},
                    files={"file": ("第二篇.md", "# 第二篇\n\n正文。".encode("utf-8"), "text/markdown")},
                )
                self.assertEqual(second.status_code, 200)
                self.assertEqual(second.json()["library_folder_id"], child.json()["id"])

                unrelated = client.post("/api/content/folders", json={"name": "其他资料"}).json()
                rejected = client.post(
                    "/api/content/import-markdown",
                    data={"library_folder_id": unrelated["id"]},
                    files={"file": ("第三篇.md", "# 第三篇\n".encode("utf-8"), "text/markdown")},
                )
                self.assertEqual(rejected.status_code, 400)
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_content_api_lists_and_updates_status(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="douyin",
                        source_url="https://v.douyin.com/abc123/",
                        canonical_source_id="abc123",
                        title="测试内容",
                        status="to_read",
                    )
                    connection.commit()
                cache_dir = cache_dir_for_url("https://v.douyin.com/abc123/")
                cache_dir.mkdir(parents=True)
                (cache_dir / "video.mp4").write_bytes(b"0" * 12000)
                (cache_dir / "preview_thumbnails.vtt").write_text("WEBVTT\n", encoding="utf-8")
                write_cache_meta(
                    cache_dir,
                    {
                        "source_url": "https://v.douyin.com/abc123/",
                        "platform": "douyin",
                        "video_info": {"title": "测试内容"},
                    },
                )
                write_cached_transcript(cache_dir, "small", "第一句\n第二句")

                client = TestClient(app)
                with patch("services.cache.media_duration_seconds", return_value=15.0):
                    listed = client.get("/api/content?status=to_read")
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(len(listed.json()), 1)
                self.assertEqual(listed.json()[0]["title"], "测试内容")
                self.assertTrue(listed.json()[0]["video_path"].endswith("video.mp4"))
                self.assertIn("preview_thumbnails.vtt", listed.json()[0]["thumbnail_vtt_url"])
                # Library rows deliberately avoid a recursive directory-size
                # scan. The cache manager remains the exact-size view.
                self.assertEqual(listed.json()[0]["cache_size_bytes"], 0)
                self.assertEqual(listed.json()[0]["duration_seconds"], 15.0)
                self.assertEqual(len(listed.json()[0]["transcript_segments"]), 2)
                self.assertEqual(listed.json()[0]["text_readiness"]["status"], "ready")
                self.assertEqual(listed.json()[0]["text_readiness"]["source_kind"], "transcript")

                updated = client.patch(f"/api/content/{item.id}/status", json={"status": "distilled"})
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["status"], "distilled")

                invalid = client.patch(f"/api/content/{item.id}/status", json={"status": "unknown"})
                self.assertEqual(invalid.status_code, 400)
        finally:
            settings.data_dir = old_data_dir

    def test_content_ai_calls_are_scoped_to_the_file(self):
        old_data_dir = settings.data_dir
        old_input_cost = settings.llm_input_cost_per_million_tokens
        old_output_cost = settings.llm_output_cost_per_million_tokens
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                settings.llm_input_cost_per_million_tokens = 0
                settings.llm_output_cost_per_million_tokens = 0
                initialize_database()
                with connect() as connection:
                    first = ContentRepository(connection).create_content_item(
                        source_provider="douyin",
                        source_url="https://v.douyin.com/first/",
                        canonical_source_id="first",
                        title="第一个文件",
                    )
                    second = ContentRepository(connection).create_content_item(
                        source_provider="douyin",
                        source_url="https://v.douyin.com/second/",
                        canonical_source_id="second",
                        title="第二个文件",
                    )
                    connection.commit()

                response = LLMResponse(
                    content="回答",
                    provider="fake",
                    model="fake-model",
                    usage=LLMUsage(prompt_tokens=80, completion_tokens=20, total_tokens=100),
                )
                record_ai_call(
                    call_type="summary",
                    provider_response=response,
                    input_chars=100,
                    output_chars=20,
                    elapsed_seconds=1,
                    content_item_id=first.id,
                )
                record_ai_call(
                    call_type="qa",
                    provider_response=response,
                    input_chars=100,
                    output_chars=20,
                    elapsed_seconds=1,
                    content_item_id=second.id,
                )

                calls = TestClient(app).get(f"/api/content/{first.id}/ai-calls")
                self.assertEqual(calls.status_code, 200)
                self.assertEqual(calls.json(), [{
                    "call_type": "summary",
                    "provider": "fake",
                    "model": "fake-model",
                    "usage_unit": "tokens",
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "total_tokens": 100,
                    "prompt_cache_hit_tokens": None,
                    "prompt_cache_miss_tokens": None,
                    "estimated_cost": None,
                    "elapsed_seconds": 1.0,
                    "image_count": 0,
                    "unit_price_cny": None,
                    "billing_region": None,
                    "request_id": None,
                    "image_width": None,
                    "image_height": None,
                }])
                record_image_generation_call(
                    call_type="wechat_cover_image",
                    provider="qwen",
                    model="qwen-image-2.0-pro",
                    endpoint="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/generation",
                    image_count=1,
                    input_chars=1200,
                    elapsed_seconds=8.25,
                    content_item_id=first.id,
                    request_id="req-content-cover",
                    image_width=2688,
                    image_height=1536,
                )
                image_call = TestClient(app).get(f"/api/content/{first.id}/ai-calls").json()[1]
                self.assertEqual(image_call["usage_unit"], "images")
                self.assertEqual(image_call["image_count"], 1)
                self.assertEqual(image_call["estimated_cost"], 0.5)
                self.assertEqual(image_call["request_id"], "req-content-cover")
                summary = TestClient(app).get("/api/ai-calls/summary").json()
                self.assertEqual(summary["image_call_count"], 1)
                self.assertEqual(summary["image_count"], 1)
                self.assertEqual(summary["image_estimated_cost"], 0.5)
        finally:
            settings.data_dir = old_data_dir
            settings.llm_input_cost_per_million_tokens = old_input_cost
            settings.llm_output_cost_per_million_tokens = old_output_cost


class MediaApiTests(unittest.TestCase):
    def test_media_api_serves_only_data_dir_files(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                media = settings.data_dir / "sample.txt"
                media.write_text("hello", encoding="utf-8")
                outside = Path(temp_dir).parent / "outside-video-knowledge-test.txt"
                outside.write_text("nope", encoding="utf-8")
                try:
                    client = TestClient(app)
                    ok = client.get("/api/media", params={"path": str(media)})
                    self.assertEqual(ok.status_code, 200)
                    self.assertEqual(ok.text, "hello")

                    denied = client.get("/api/media", params={"path": str(outside)})
                    self.assertEqual(denied.status_code, 403)
                finally:
                    outside.unlink(missing_ok=True)
        finally:
            settings.data_dir = old_data_dir

    def test_media_api_rewrites_thumbnail_vtt_urls_for_player_fetches(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                vtt = settings.data_dir / "preview_thumbnails.vtt"
                vtt.write_text(
                    "WEBVTT\n\n00:00:00.000 --> 00:00:05.000\n/api/media?path=sprite.jpg#xywh=0,0,160,90\n",
                    encoding="utf-8",
                )

                response = TestClient(app).get("/api/media", params={"path": str(vtt)})

                self.assertEqual(response.status_code, 200)
                self.assertIn("http://testserver/api/media?path=sprite.jpg", response.text)
        finally:
            settings.data_dir = old_data_dir


class CookieFileTests(unittest.TestCase):
    def test_write_netscape_cookie_file_converts_pairs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "cookies.txt"

            _write_netscape_cookie_file("sessionid=abc; uid=123", output)

            content = output.read_text(encoding="utf-8")
            self.assertIn("# Netscape HTTP Cookie File", content)
            self.assertIn(".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\tabc", content)
            self.assertIn(".douyin.com\tTRUE\t/\tFALSE\t0\tuid\t123", content)

    def test_bilibili_cookie_is_saved_as_a_private_yt_dlp_cookie_file(self):
        old_data_dir = settings.data_dir
        old_cookie = settings.bilibili_cookie
        old_cookie_file = settings.bilibili_cookie_file
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                settings.bilibili_cookie = ""
                settings.bilibili_cookie_file = ""

                saved_path = save_bilibili_cookie("SESSDATA=active; bili_jct=csrf")
                status = get_bilibili_cookie_status()
                with bilibili_yt_dlp_cookie_args() as args:
                    self.assertEqual(args, ["--cookies", str(saved_path)])

                self.assertTrue(status["configured"])
                self.assertIn(
                    ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tactive",
                    saved_path.read_text(encoding="utf-8"),
                )
                self.assertEqual(oct(saved_path.stat().st_mode & 0o777), "0o600")
        finally:
            settings.data_dir = old_data_dir
            settings.bilibili_cookie = old_cookie
            settings.bilibili_cookie_file = old_cookie_file

    def test_bilibili_subtitle_failure_does_not_fallback_to_unbound_extractor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "services.subtitles._fetch_bilibili_player_subtitle",
                return_value=SubtitleFetchResult(success=False, error="播放器无可验证字幕"),
            ):
                result = fetch_bilibili_subtitle(
                    "https://www.bilibili.com/video/BV1xx411c7mD",
                    Path(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "播放器无可验证字幕")

    def test_bilibili_browser_tracks_must_match_current_player_aid_and_cid(self):
        track = {"lan": "ai-zh", "subtitle_url": "//i0.hdslb.com/bfs/subtitle/current.json"}
        payload = {"data": {"subtitle": {"subtitles": [track]}}}
        tracks = _browser_bound_bilibili_tracks(
            [
                ("https://api.bilibili.com/x/player/wbi/v2?aid=123&cid=456", payload),
                ("https://api.bilibili.com/x/player/wbi/v2?aid=999&cid=456", payload),
            ],
            {"bvid": "BV1xx411c7mD", "aid": 123, "cid": 456, "title": "当前视频"},
        )

        self.assertEqual(tracks, [track])

    def test_bilibili_browser_subtitle_prefers_complete_track_and_uses_browser_context(self):
        class FakeResponse:
            ok = True

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class FakeRequestContext:
            def __init__(self, payloads):
                self.payloads = payloads
                self.calls = []

            def get(self, url, headers):
                self.calls.append((url, headers))
                return FakeResponse(self.payloads[url])

        sparse_url = "https://i0.hdslb.com/bfs/subtitle/sparse.json"
        full_url = "https://i0.hdslb.com/bfs/subtitle/full.json"
        request_context = FakeRequestContext(
            {
                sparse_url: {"body": [{"from": 0, "to": 1, "content": "短字幕"}]},
                full_url: {
                    "body": [
                        {"from": 0.2, "to": 1.4, "content": "第一句内容"},
                        {"from": 1.5, "to": 3.0, "content": "第二句内容"},
                    ]
                },
            }
        )

        candidate = _fetch_best_browser_bilibili_subtitle_candidate(
            [
                {"lan": "zh-CN", "subtitle_url": "//i0.hdslb.com/bfs/subtitle/sparse.json"},
                {"lan": "ai-zh", "subtitle_url": "//i0.hdslb.com/bfs/subtitle/full.json"},
            ],
            request_context=request_context,
            referer="https://www.bilibili.com/video/BV1xx411c7mD",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate[2], "第一句内容\n第二句内容")
        self.assertEqual(candidate[3:], (2, 3.0))
        self.assertEqual(len(request_context.calls), 2)
        self.assertTrue(all(headers["Referer"].startswith("https://www.bilibili.com/video/") for _, headers in request_context.calls))


class DouyinCookieStatusTests(unittest.TestCase):
    def test_status_marks_missing_cookie_as_missing_without_probe(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                invalidate_douyin_cookie_status()

                status = get_douyin_cookie_status(force=True)

                self.assertFalse(status["configured"])
                self.assertEqual(status["state"], "missing")
        finally:
            invalidate_douyin_cookie_status()
            settings.data_dir = old_data_dir

    def test_status_marks_expired_sid_guard_as_invalid_without_network_probe(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.data_dir.mkdir(parents=True)
                (settings.data_dir / "douyin_cookies.txt").write_text(
                    ".douyin.com\tTRUE\t/\tFALSE\t0\tsid_guard\tsid%7C1%7C1\n",
                    encoding="utf-8",
                )
                invalidate_douyin_cookie_status()

                with patch("services.douyin_cookie_status._probe_douyin_browser_session") as probe:
                    status = get_douyin_cookie_status(force=True)

                self.assertEqual(status["state"], "invalid")
                self.assertIn("过期", status["detail"])
                probe.assert_not_called()
        finally:
            invalidate_douyin_cookie_status()
            settings.data_dir = old_data_dir

    def test_status_reports_successful_browser_probe_as_valid(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.data_dir.mkdir(parents=True)
                (settings.data_dir / "douyin_cookies.txt").write_text(
                    ".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\tactive\n",
                    encoding="utf-8",
                )
                invalidate_douyin_cookie_status()

                with patch(
                    "services.douyin_cookie_status._probe_douyin_browser_session",
                    return_value=("valid", "已在抖音网页“我的”页面确认登录态"),
                ):
                    status = get_douyin_cookie_status(force=True)

                self.assertTrue(status["configured"])
                self.assertEqual(status["state"], "valid")
                self.assertEqual(status["label"], "抖音登录态可用")
        finally:
            invalidate_douyin_cookie_status()
            settings.data_dir = old_data_dir

    def test_status_can_defer_browser_probe_until_after_the_first_screen(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.data_dir.mkdir(parents=True)
                (settings.data_dir / "douyin_cookies.txt").write_text(
                    ".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\tactive\n",
                    encoding="utf-8",
                )
                invalidate_douyin_cookie_status()

                with patch("services.douyin_cookie_status._probe_douyin_browser_session") as probe:
                    status = get_douyin_cookie_status(force=True, probe=False)

                self.assertTrue(status["configured"])
                self.assertEqual(status["state"], "unknown")
                self.assertIn("后台检测", status["detail"])
                probe.assert_not_called()
        finally:
            invalidate_douyin_cookie_status()
            settings.data_dir = old_data_dir

    def test_recent_real_cdn_403_overrides_a_successful_fixed_probe(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.data_dir.mkdir(parents=True)
                (settings.data_dir / "douyin_cookies.txt").write_text(
                    ".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\tactive\n",
                    encoding="utf-8",
                )
                invalidate_douyin_cookie_status()

                with patch(
                    "services.douyin_cookie_status._probe_douyin_browser_session",
                    return_value=("valid", "已在抖音网页“我的”页面确认登录态"),
                ), patch(
                    "services.douyin_cookie_status._recent_douyin_cdn_failure",
                    return_value={"task_id": "recent403", "updated_at": "2026-07-13T15:55:58+00:00"},
                ):
                    status = get_douyin_cookie_status(force=True)

                self.assertEqual(status["state"], "blocked")
                self.assertEqual(status["label"], "抖音下载受限")
                self.assertIn("recent403", status["detail"])
        finally:
            invalidate_douyin_cookie_status()
            settings.data_dir = old_data_dir

    def test_browser_probe_recognizes_authenticated_and_login_pages(self):
        self.assertEqual(
            _douyin_page_login_state(
                "https://www.douyin.com/user/self",
                "测试账号的抖音 - 抖音",
                "",
            )[0],
            "valid",
        )
        self.assertEqual(
            _douyin_page_login_state(
                "https://www.douyin.com/login",
                "抖音",
                "扫码登录",
            )[0],
            "invalid",
        )


class CredentialSettingsTests(unittest.TestCase):
    def test_custom_text_model_is_preserved_for_provider_and_pricing(self):
        old_data_dir = settings.data_dir
        old_pricing = settings.deepseek_pricing
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                save_deepseek_settings(
                    deepseek_api_key=None,
                    deepseek_base_url="https://api.example.test/v1",
                    deepseek_pricing={
                        "deepseek-v4-flash": {"input_cache_hit": 0.02, "input_cache_miss": 1, "output": 2},
                        "my-provider/text-v1": {"input_cache_hit": 0.1, "input_cache_miss": 1.2, "output": 3.4},
                    },
                )
                self.assertEqual(
                    load_llm_settings()["deepseek_pricing"]["my-provider/text-v1"]["output"],
                    3.4,
                )
                self.assertEqual(resolve_deepseek_model("my-provider/text-v1:enabled"), ("my-provider/text-v1", "enabled"))
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_pricing = old_pricing

    def test_masked_deepseek_key_is_preserved_when_no_replacement_is_submitted(self):
        old_data_dir = settings.data_dir
        old_key = settings.deepseek_api_key
        old_base_url = settings.deepseek_base_url
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                save_deepseek_settings(
                    deepseek_api_key="saved-deepseek-key",
                    deepseek_base_url="https://api.deepseek.com",
                )
                save_deepseek_settings(
                    deepseek_api_key=None,
                    deepseek_base_url="https://proxy.example.test/v1",
                )

                saved = load_llm_settings()
                self.assertEqual(saved["deepseek_api_key"], "saved-deepseek-key")
                self.assertEqual(saved["deepseek_base_url"], "https://proxy.example.test/v1")
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_api_key = old_key
            settings.deepseek_base_url = old_base_url

    def test_masked_paddle_token_is_preserved_when_no_replacement_is_submitted(self):
        old_data_dir = settings.data_dir
        old_token = settings.paddle_ocr_access_token
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                save_paddle_ocr_settings(access_token="saved-paddle-token")
                save_paddle_ocr_settings(access_token=None)

                saved = load_paddle_ocr_settings()
                self.assertEqual(saved["paddle_ocr_access_token"], "saved-paddle-token")
        finally:
            settings.data_dir = old_data_dir
            settings.paddle_ocr_access_token = old_token

    def test_explicit_reveal_returns_only_the_requested_local_secret(self):
        old_data_dir = settings.data_dir
        old_deepseek_key = settings.deepseek_api_key
        old_deepseek_base_url = settings.deepseek_base_url
        old_embedding_key = settings.campus_embedding_api_key
        old_embedding_base_url = settings.campus_embedding_api_base_url
        old_embedding_model = settings.campus_embedding_api_model
        old_paddle_token = settings.paddle_ocr_access_token
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                save_deepseek_settings(
                    deepseek_api_key="saved-deepseek-key",
                    deepseek_base_url="https://api.deepseek.com",
                )
                save_campus_embedding_settings(
                    campus_embedding_api_key="saved-embedding-key",
                    campus_embedding_api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    campus_embedding_api_model="qwen3.7-text-embedding",
                )
                save_paddle_ocr_settings(access_token="saved-paddle-token")

                self.assertEqual(reveal_deepseek_api_key(), "saved-deepseek-key")
                self.assertEqual(reveal_campus_embedding_api_key(), "saved-embedding-key")
                self.assertEqual(reveal_paddle_ocr_access_token(), "saved-paddle-token")
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_api_key = old_deepseek_key
            settings.deepseek_base_url = old_deepseek_base_url
            settings.campus_embedding_api_key = old_embedding_key
            settings.campus_embedding_api_base_url = old_embedding_base_url
            settings.campus_embedding_api_model = old_embedding_model
            settings.paddle_ocr_access_token = old_paddle_token

    def test_masked_embedding_key_is_preserved_and_model_is_saved(self):
        old_data_dir = settings.data_dir
        old_key = settings.campus_embedding_api_key
        old_base_url = settings.campus_embedding_api_base_url
        old_model = settings.campus_embedding_api_model
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                save_campus_embedding_settings(
                    campus_embedding_api_key="saved-embedding-key",
                    campus_embedding_api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    campus_embedding_api_model="qwen3.7-text-embedding",
                )
                save_campus_embedding_settings(
                    campus_embedding_api_key=None,
                    campus_embedding_api_base_url="https://proxy.example.test/v1",
                    campus_embedding_api_model="text-embedding-v4",
                )

                saved = load_llm_settings()
                self.assertEqual(saved["campus_embedding_api_key"], "saved-embedding-key")
                self.assertEqual(saved["campus_embedding_api_base_url"], "https://proxy.example.test/v1")
                self.assertEqual(saved["campus_embedding_api_model"], "text-embedding-v4")
        finally:
            settings.data_dir = old_data_dir
            settings.campus_embedding_api_key = old_key
            settings.campus_embedding_api_base_url = old_base_url
            settings.campus_embedding_api_model = old_model

    @patch("services.llm_settings.record_ai_call")
    @patch("services.llm_settings.OpenAICompatibleProvider")
    def test_deepseek_connection_uses_current_form_values_without_saving(self, provider_class, record_call):
        old_model = settings.deepseek_model
        try:
            settings.deepseek_model = "deepseek-v4-flash"
            provider_class.return_value.chat.return_value = LLMResponse(
                content="OK",
                provider="deepseek",
                model="deepseek-v4-flash",
                usage=LLMUsage(prompt_tokens=9, completion_tokens=1, total_tokens=10),
            )

            result = run_deepseek_connection_test(
                deepseek_api_key="unsaved-test-key",
                deepseek_base_url="https://proxy.example.test/v1",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["model"], "deepseek-v4-flash")
            self.assertEqual(result["total_tokens"], 10)
            provider_class.assert_called_once_with(
                api_key="unsaved-test-key",
                base_url="https://proxy.example.test/v1",
                model="deepseek-v4-flash",
                thinking_type="enabled",
                provider_name="deepseek",
                request_timeout_seconds=20,
            )
            record_call.assert_called_once()
            self.assertEqual(record_call.call_args.kwargs["call_type"], "connection_test")
        finally:
            settings.deepseek_model = old_model

    @patch("services.llm_settings.record_ai_call")
    @patch("services.llm_settings.OpenAI")
    def test_embedding_connection_uses_unsaved_form_values(self, openai_class, record_call):
        response = SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.2, -0.1, 0.8])],
            model="qwen3.7-text-embedding",
            usage=SimpleNamespace(prompt_tokens=8, total_tokens=8),
        )
        openai_class.return_value.embeddings.create.return_value = response

        result = run_campus_embedding_connection_test(
            campus_embedding_api_key="unsaved-embedding-key",
            campus_embedding_api_base_url="https://proxy.example.test/v1",
            campus_embedding_api_model="qwen3.7-text-embedding",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "qwen3.7-text-embedding")
        self.assertEqual(result["dimensions"], 3)
        self.assertEqual(result["total_tokens"], 8)
        openai_class.assert_called_once_with(
            api_key="unsaved-embedding-key",
            base_url="https://proxy.example.test/v1",
            timeout=20,
            max_retries=0,
        )
        openai_class.return_value.embeddings.create.assert_called_once_with(
            model="qwen3.7-text-embedding",
            input="KnowledgeHub embedding connection test",
            encoding_format="float",
        )
        self.assertEqual(record_call.call_args.kwargs["call_type"], "knowledge_embedding_test")

    def test_embedding_settings_endpoint_saves_model(self):
        old_data_dir = settings.data_dir
        old_key = settings.campus_embedding_api_key
        old_base_url = settings.campus_embedding_api_base_url
        old_model = settings.campus_embedding_api_model
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                response = TestClient(app).put(
                    "/api/llm-settings/campus-embedding",
                    json={
                        "campus_embedding_api_key": "endpoint-test-key",
                        "campus_embedding_api_base_url": "https://proxy.example.test/v1",
                        "campus_embedding_api_model": "qwen3.7-text-embedding",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["campus_embedding_api_model"], "qwen3.7-text-embedding")
        finally:
            settings.data_dir = old_data_dir
            settings.campus_embedding_api_key = old_key
            settings.campus_embedding_api_base_url = old_base_url
            settings.campus_embedding_api_model = old_model

    @patch("routers.llm_settings.test_campus_embedding_connection")
    def test_embedding_connection_endpoint_uses_form_values(self, connection_test):
        connection_test.return_value = {
            "ok": True,
            "model": "qwen3.7-text-embedding",
            "dimensions": 1024,
            "elapsed_ms": 20,
            "total_tokens": 8,
        }

        response = TestClient(app).post(
            "/api/llm-settings/campus-embedding/test",
            json={
                "campus_embedding_api_key": "endpoint-test-key",
                "campus_embedding_api_base_url": "https://proxy.example.test/v1",
                "campus_embedding_api_model": "qwen3.7-text-embedding",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dimensions"], 1024)
        connection_test.assert_called_once_with(
            campus_embedding_api_key="endpoint-test-key",
            campus_embedding_api_base_url="https://proxy.example.test/v1",
            campus_embedding_api_model="qwen3.7-text-embedding",
        )


class PaddleOcrResultTests(unittest.TestCase):
    def test_hard_filter_excludes_gif_qrcode_avatar_logo_and_divider(self):
        self.assertEqual(
            _image_filter_reason({"data-type": "gif", "data-src": "https://example.com/a.gif"}),
            "gif",
        )
        self.assertEqual(
            _image_filter_reason({"class": ["qrcode"], "data-src": "https://example.com/a.png"}),
            "qrcode",
        )
        self.assertEqual(
            _image_filter_reason({"class": ["author-avatar"], "data-src": "https://example.com/a.png"}),
            "avatar_or_logo",
        )
        self.assertEqual(
            _image_filter_reason({"data-w": "1000", "data-ratio": "0.05", "data-src": "https://example.com/a.png"}),
            "decorative",
        )

    def test_normal_article_image_submits_to_paddle_without_device_ocr_gate(self):
        with (
            patch("services.paddle_ocr._download_image", return_value=(b"image", "image.jpg", "image/jpeg")),
            patch("services.paddle_ocr._cache_image", return_value="/tmp/image.jpg"),
            patch("services.paddle_ocr._read_ocr_result_cache", return_value=None),
            patch("services.paddle_ocr._submit_job", return_value=("job-1", 0)) as submit_mock,
            patch("services.paddle_ocr._wait_for_result", return_value=("https://example.com/result.json", "json", 0)),
            patch("services.paddle_ocr._download_json_result", return_value="图片里的有效文字"),
            patch("services.paddle_ocr._write_ocr_result_cache"),
            patch("services.paddle_ocr.record_ocr_call"),
        ):
            result = _recognize_one("https://example.com/image.jpg", article_url="https://example.com/article")

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.cloud_submitted)
        submit_mock.assert_called_once()

    def test_async_json_result_extracts_text_and_ignores_image_only_pages(self):
        text = _extract_json_result_text(
            {
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {
                                "text": '<div><img src="photo.jpg" alt="Image" /></div>'
                            }
                        },
                        {
                            "markdown": {
                                "text": "## 图片表格\n\n报名截止时间：8 月 1 日"
                            }
                        },
                    ]
                }
            }
        )

        self.assertNotIn("photo.jpg", text)
        self.assertIn("报名截止时间：8 月 1 日", text)

    def test_async_job_accepts_json_result_url(self):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "data": {
                    "jobId": "job-1",
                    "state": "done",
                    "resultUrl": {"jsonUrl": "https://example.com/result.json"},
                }
            },
        )

        with patch("services.paddle_ocr.requests.get", return_value=response):
            result_url, result_kind, retry_count = _wait_for_result("job-1")

        self.assertEqual(result_url, "https://example.com/result.json")
        self.assertEqual(result_kind, "json")
        self.assertEqual(retry_count, 0)

    def test_legacy_all_failed_ocr_cache_is_retried_once(self):
        article_info = {
            "images": ["https://mmbiz.qpic.cn/example.jpg"],
            "image_ocr": {
                "attempted": True,
                "recognized_count": 0,
                "failed_count": 1,
            },
        }

        with patch("services.content_source_text.is_paddle_ocr_configured", return_value=True):
            self.assertTrue(_wechat_article_needs_ocr_refresh(article_info))
            article_info["image_ocr"]["attempted_at"] = "2026-07-15T04:00:00+00:00"
            self.assertFalse(_wechat_article_needs_ocr_refresh(article_info))

    def test_legacy_local_prefilter_skip_is_retried_with_cloud_ocr(self):
        article_info = {
            "images": ["https://mmbiz.qpic.cn/example-table.jpg"],
            "image_ocr": {
                "attempted": True,
                "attempted_at": "2026-07-15T04:00:00+00:00",
                "local_filter_counts": {"text_below_threshold": 1},
            },
        }

        with patch("services.content_source_text.is_paddle_ocr_configured", return_value=True):
            self.assertTrue(_wechat_article_needs_ocr_refresh(article_info))

    def test_legacy_procurement_placeholder_is_retryable(self):
        readiness = _article_text_readiness(
            {
                "article_info": {
                    "body_text": "公告标题：测试采购公告\n正文暂未由该公开接口返回，请通过原始链接查看。",
                }
            }
        )

        self.assertEqual(readiness.status, "needs_fetch")
        self.assertTrue(readiness.retryable)
        self.assertEqual(readiness.label, "正文待更新")

    def test_legacy_document_ocr_capture_is_marked_for_structure_refresh(self):
        with patch("services.content_source_text.is_paddle_ocr_configured", return_value=True):
            readiness = _article_text_readiness(
                {
                    "article_info": {
                        "body_text": "采购公告正文已经提取。",
                        "document_ocr": {"attempted": True, "status": "succeeded"},
                    }
                }
            )

        self.assertEqual(readiness.status, "needs_fetch")
        self.assertEqual(readiness.label, "正文待优化")



class MarkdownTests(unittest.TestCase):
    def test_summary_prompt_has_grounding_and_uncertainty_rules(self):
        self.assertIn("不补充外部事实", SYSTEM_PROMPT)
        self.assertIn("不确定性", SYSTEM_PROMPT)
        self.assertIn("第一行必须是一个不超过 20 个中文字符的总结性标题", SYSTEM_PROMPT)

    def test_qa_prompt_has_grounding_rule(self):
        self.assertIn("当前材料", QA_SYSTEM_PROMPT)
        self.assertIn("模型补充", QA_SYSTEM_PROMPT)
        self.assertIn("需要联网核验", QA_SYSTEM_PROMPT)
        self.assertIn("不要输出空栏目", QA_SYSTEM_PROMPT)

    def test_generate_markdown_includes_source_summary_and_transcript(self):
        markdown = generate_markdown(
            "## 总结\n内容摘要",
            {
                "title": "测试视频",
                "platform": "bilibili",
                "uploader": "作者",
                "duration": 42,
                "transcript": "原始转写",
            },
            "https://example.com/video",
        )

        self.assertIn("source: https://example.com/video", markdown)
        self.assertIn("# 测试视频", markdown)
        self.assertIn("## 总结", markdown)
        self.assertIn("原始转写", markdown)

    def test_append_qa_to_markdown_adds_section(self):
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.obsidian_vault = Path(temp_dir)
                note_path = settings.obsidian_vault / "测试视频.md"
                note_path.write_text("# 测试视频\n\n## 总结\n内容摘要\n", encoding="utf-8")

                append_qa_to_markdown(note_path, "核心观点是什么？", "核心观点是测试。", "2026-01-02 03:04")

                content = note_path.read_text(encoding="utf-8")
                self.assertIn("## 追问记录", content)
                self.assertIn("**问：** 核心观点是什么？", content)
                self.assertIn("核心观点是测试。", content)
        finally:
            settings.obsidian_vault = old_vault

    def test_markdown_draft_sync_overwrites_external_obsidian_changes(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                save_obsidian_settings(
                    settings.obsidian_vault,
                    export_path=settings.obsidian_vault,
                    auto_write=True,
                )
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="douyin",
                        source_url="https://v.douyin.com/abc123/",
                        canonical_source_id="abc123",
                        title="同步测试",
                    )
                    connection.commit()

                state = save_markdown_draft_and_sync(
                    markdown="# 同步测试\n\n初始内容",
                    title="同步测试",
                    obsidian_path=settings.obsidian_vault / "同步测试.md",
                    content_item_id=item.id,
                )
                self.assertEqual(state.sync_status, "synced")
                self.assertTrue(Path(state.markdown_draft_path).exists())
                self.assertTrue(Path(state.obsidian_path).exists())

                Path(state.obsidian_path).write_text("# 外部修改\n", encoding="utf-8")
                resolved = update_markdown_draft(item.id, "# 同步测试\n\n内部修改")
                self.assertFalse(resolved.conflict)
                self.assertEqual(resolved.sync_status, "synced")
                self.assertIn("内部修改", Path(resolved.obsidian_path).read_text(encoding="utf-8"))
                self.assertIn("内部修改", get_markdown_state(item.id).markdown)

                Path(resolved.obsidian_path).write_text("# 再次外部修改\n", encoding="utf-8")
                summarized = replace_content_summary_and_sync(item.id, "重新生成摘要")
                self.assertFalse(summarized.conflict)
                self.assertEqual(summarized.sync_status, "synced")
                self.assertIn("重新生成摘要", Path(summarized.obsidian_path).read_text(encoding="utf-8"))
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_markdown_draft_update_refreshes_full_text_search(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                save_obsidian_settings(
                    settings.obsidian_vault,
                    export_path=settings.obsidian_vault,
                    auto_write=False,
                )
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="local_markdown",
                        canonical_source_id="markdown-search-refresh",
                        title="搜索索引刷新",
                    )
                    connection.commit()

                save_markdown_draft_and_sync(
                    markdown="# 搜索索引刷新\n\n初始正文",
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / "搜索索引刷新.md",
                    content_item_id=item.id,
                )
                update_markdown_draft(item.id, "# 搜索索引刷新\n\n编辑后可搜索关键词")

                results = search_documents("编辑后可搜索关键词")
                self.assertTrue(any(result.content_key == item.id for result in results))
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_replace_article_summary_preserves_original_body_and_followup_history(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                save_obsidian_settings(
                    settings.obsidian_vault,
                    export_path=settings.obsidian_vault,
                    auto_write=True,
                )
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/regenerate-summary",
                        canonical_source_id="regenerate-summary",
                        title="公众号总结替换测试",
                    )
                    connection.commit()

                markdown = generate_article_markdown(
                    "## 旧总结\n\n这里是旧总结内容。",
                    {
                        "title": item.title,
                        "platform": "wechat",
                        "author": "测试公众号",
                        "published_at": "2026-07-15 09:00:00",
                        "body_text": "这是需要永久保留的公众号原文正文。",
                    },
                    item.source_url,
                )
                markdown += "\n\n## 追问记录\n\n旧追问也必须保留。\n"
                save_markdown_draft_and_sync(
                    markdown=markdown,
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / f"{item.title}.md",
                    content_item_id=item.id,
                )

                state = replace_article_summary_and_sync(
                    item.id,
                    "模型生成的文件名标题\n\n## 新总结\n\n这是重新生成后的主总结。",
                )

                self.assertEqual(state.sync_status, "synced")
                self.assertNotIn("这里是旧总结内容", state.markdown)
                self.assertNotIn("模型生成的文件名标题", state.markdown)
                self.assertIn("这是重新生成后的主总结", state.markdown)
                self.assertIn("这是需要永久保留的公众号原文正文", state.markdown)
                self.assertIn("旧追问也必须保留", state.markdown)
                self.assertIn(
                    "这是重新生成后的主总结",
                    Path(state.obsidian_path).read_text(encoding="utf-8"),
                )
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault


class FakeLLMProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, content: str, usage: LLMUsage | None = None) -> None:
        self.content = content
        self.usage = usage
        self.calls: list[tuple[list[LLMMessage], float]] = []

    def chat(self, messages: list[LLMMessage], *, temperature: float = 0.2) -> LLMResponse:
        self.calls.append((messages, temperature))
        return LLMResponse(content=self.content, provider=self.name, model=self.model, usage=self.usage)


class FakeStreamingLLMProvider(FakeLLMProvider):
    def chat_stream(self, messages: list[LLMMessage], *, temperature: float = 0.2, on_usage=None):
        self.calls.append((messages, temperature))
        yield self.content
        if on_usage and self.usage:
            on_usage(self.usage)


class LLMProviderTests(unittest.TestCase):
    def test_summarize_uses_injected_llm_provider(self):
        provider = FakeLLMProvider("测试标题\n\n## 总结\n这是总结。")

        title, summary = summarize("转写文本", "原始标题", provider=provider)

        self.assertEqual(title, "测试标题")
        self.assertIn("这是总结", summary)
        self.assertEqual(provider.calls[0][1], 0.3)
        self.assertIn("视频标题：原始标题", provider.calls[0][0][1].content)

    def test_summarize_uses_active_database_prompt_template(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    repository = PromptTemplateRepository(connection)
                    repository.create_template(
                        name="custom_summary",
                        task_type="summary",
                        version="v-test",
                        template="自定义总结系统提示词",
                        is_active=True,
                    )
                    connection.commit()

                provider = FakeLLMProvider("测试标题\n\n## 总结\n这是总结。")
                summarize("转写文本", "原始标题", provider=provider)

                self.assertEqual(provider.calls[0][0][0].content, "自定义总结系统提示词")
        finally:
            settings.data_dir = old_data_dir

    def test_single_select_prompt_templates_keep_an_active_template_and_protect_the_last_one(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    repository = PromptTemplateRepository(connection)
                    original = repository.get_active_template("summary")
                    self.assertIsNotNone(original)
                    with self.assertRaisesRegex(ValueError, "至少保留一个"):
                        repository.delete_template(original.id)

                    draft = repository.create_template(
                        name="summary_draft",
                        task_type="summary",
                        version="v-test",
                        template="草稿提示词",
                    )
                    self.assertFalse(draft.is_active)
                    self.assertEqual(repository.get_active_template("summary").id, original.id)

                    repository.activate_template(draft.id)
                    repository.delete_template(draft.id)
                    self.assertEqual(repository.get_active_template("summary").id, original.id)
        finally:
            settings.data_dir = old_data_dir

    def test_summarize_records_ai_call_usage_when_callback_is_provided(self):
        old_data_dir = settings.data_dir
        old_input_cost = settings.llm_input_cost_per_million_tokens
        old_output_cost = settings.llm_output_cost_per_million_tokens
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                settings.llm_input_cost_per_million_tokens = 1.0
                settings.llm_output_cost_per_million_tokens = 2.0
                initialize_database()
                records = []
                provider = FakeLLMProvider(
                    "测试标题\n\n## 总结\n这是总结。",
                    usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
                )

                summarize("转写文本", "原始标题", provider=provider, ai_call_callback=records.append)

                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].total_tokens, 150)
                self.assertEqual(records[0].estimated_cost, 0.0002)
                with connect(settings.data_dir / "app.db") as connection:
                    row = connection.execute("SELECT * FROM ai_calls").fetchone()
                    self.assertEqual(row["call_type"], "summary")
                    self.assertEqual(row["provider"], "fake")
                    self.assertEqual(row["prompt_tokens"], 100)
                    self.assertEqual(row["completion_tokens"], 50)
                    self.assertEqual(row["estimated_cost"], 0.0002)
        finally:
            settings.data_dir = old_data_dir
            settings.llm_input_cost_per_million_tokens = old_input_cost
            settings.llm_output_cost_per_million_tokens = old_output_cost

    def test_answer_question_uses_injected_llm_provider(self):
        provider = FakeLLMProvider("## 回答\n材料里说了测试内容。")

        answer = answer_question(
            "讲了什么？",
            summary="## 总结\n测试",
            transcript="原文",
            video_title="标题",
            provider=provider,
        )

        self.assertIn("材料里说了测试内容", answer)
        self.assertEqual(provider.calls[0][1], 0.2)
        self.assertIn("用户问题", provider.calls[0][0][-1].content)
        self.assertIn("讲了什么？", provider.calls[0][0][-1].content)

    def test_streamed_question_records_reported_token_usage(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                records = []
                provider = FakeStreamingLLMProvider(
                    "流式回答",
                    usage=LLMUsage(prompt_tokens=120, completion_tokens=30, total_tokens=150),
                )

                answer = "".join(stream_answer_question(
                    "问题",
                    summary="总结",
                    transcript="转写",
                    provider=provider,
                    ai_call_callback=records.append,
                ))

                self.assertEqual(answer, "流式回答")
                self.assertEqual(records[0].total_tokens, 150)
                with connect(settings.data_dir / "app.db") as connection:
                    row = connection.execute("SELECT * FROM ai_calls").fetchone()
                    self.assertEqual(row["call_type"], "qa")
                    self.assertEqual(row["prompt_tokens"], 120)
                    self.assertEqual(row["completion_tokens"], 30)
        finally:
            settings.data_dir = old_data_dir

    def test_regenerated_article_summary_keeps_ocr_text_in_single_context(self):
        provider = FakeStreamingLLMProvider("新的文章总结")
        source = "段落一\n[图片文字 1]\n图片里的表格：报名时间 8 月 1 日\n[/图片文字 1]\n段落二"

        answer = "".join(stream_regenerated_article_summary(
            source,
            "测试文章",
            provider=provider,
        ))

        self.assertEqual(answer, "新的文章总结")
        self.assertEqual(len(provider.calls), 1)
        sent_material = provider.calls[0][0][1].content
        self.assertLess(sent_material.index("段落一"), sent_material.index("[图片文字 1]"))
        self.assertLess(sent_material.index("[图片文字 1]"), sent_material.index("段落二"))

    def test_regenerated_article_summary_reads_all_long_source_chunks_in_order(self):
        provider = FakeStreamingLLMProvider("最终总结")
        first = "段落一\n[图片文字 1]\n图片内容\n[/图片文字 1]\n"
        second = "段落二\n"
        source = first + ("甲" * 40_000) + second + ("乙" * 40_000)

        answer = "".join(stream_regenerated_article_summary(
            source,
            "长文测试",
            provider=provider,
        ))

        self.assertEqual(answer, "最终总结")
        self.assertGreater(len(provider.calls), 2)
        reduction_messages = [call[0][1].content for call in provider.calls[:-1]]
        self.assertTrue(any("段落一" in message and "[图片文字 1]" in message for message in reduction_messages))
        self.assertTrue(any("段落二" in message for message in reduction_messages))

    def test_regenerated_video_summary_uses_the_video_prompt(self):
        provider = FakeStreamingLLMProvider("视频总结")

        answer = "".join(stream_regenerated_content_summary(
            "第一段字幕\n第二段字幕",
            "测试视频",
            content_kind="video",
            provider=provider,
        ))

        self.assertEqual(answer, "视频总结")
        self.assertEqual(len(provider.calls), 1)
        messages = provider.calls[0][0]
        self.assertIn("视频标题：测试视频", messages[1].content)
        self.assertIn("字幕或转写", messages[1].content)
        self.assertTrue(messages[0].content.strip())

    def test_regenerated_audio_summary_preserves_timestamped_transcript_material(self):
        provider = FakeStreamingLLMProvider("音频总结")

        answer = "".join(stream_regenerated_content_summary(
            "未经整理的转写",
            "测试录音",
            content_kind="audio",
            transcript_segments=[{"start_seconds": 75, "text": "关键结论"}],
            provider=provider,
        ))

        self.assertEqual(answer, "音频总结")
        messages = provider.calls[0][0]
        self.assertIn("音频标题：测试录音", messages[1].content)
        self.assertIn("[01:15](#video-t=75) 关键结论", messages[1].content)


class CacheAndModelTests(unittest.TestCase):
    def test_cache_key_for_url_is_stable(self):
        url = "https://b23.tv/abc123"

        self.assertEqual(cache_key_for_url(url), cache_key_for_url(url))
        self.assertNotEqual(cache_key_for_url(url), cache_key_for_url(url + "x"))

    def test_preview_thumbnails_write_sprite_and_vtt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            video_path = cache_dir / "video.mp4"
            video_path.write_bytes(b"0" * 12000)

            def fake_run(cmd, *, output_path, **_kwargs):
                output_path.write_bytes(b"jpg")
                return SimpleNamespace(success=True)

            with (
                patch("services.cache.media_duration_seconds", return_value=22.0),
                patch("services.cache.run_ffmpeg", side_effect=fake_run) as run_mock,
            ):
                vtt_path = ensure_preview_thumbnails(cache_dir, video_path)

            self.assertEqual(vtt_path, cache_dir / "preview_thumbnails.vtt")
            self.assertTrue((cache_dir / "preview_sprite.jpg").exists())
            content = vtt_path.read_text(encoding="utf-8")
            self.assertIn("WEBVTT", content)
            self.assertIn("#xywh=0,0,160,90", content)
            self.assertIn("/api/media?path=", content)
            self.assertTrue(any("fps=1/5" in str(part) for part in run_mock.call_args.args[0]))

    def test_pipeline_rejects_unknown_whisper_model_before_work(self):
        result = run_pipeline_sync("https://b23.tv/abc123", whisper_model="not-a-model")

        self.assertFalse(result.success)
        self.assertEqual(result.step, "config")
        self.assertIn("不支持", result.error)
        self.assertFalse(result.error_info.retryable)
        self.assertEqual(result.error_info.category, "configuration")

    def test_error_classification_marks_input_as_not_retryable(self):
        info = classify_pipeline_error("parse", "未识别到有效链接")

        self.assertEqual(info.category, "input")
        self.assertFalse(info.retryable)
        self.assertEqual(info.retry_scope, "none")

    def test_cache_entries_include_size_and_transcripts(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                cache_dir = settings.data_dir / "cache" / "abc123"
                cache_dir.mkdir(parents=True)
                video_path = cache_dir / "video.mp4"
                video_path.write_bytes(b"0" * 12000)
                write_cached_transcript(cache_dir, "base", "转写文本")
                write_cache_meta(
                    cache_dir,
                    {
                        "source_url": "https://example.com/video",
                        "platform": "bilibili",
                        "video_info": {"title": "缓存视频", "duration": 12, "uploader": "测试作者"},
                        "obsidian_path": "/tmp/note.md",
                    },
                )

                entries = list_cache_entries()

                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["title"], "缓存视频")
                self.assertEqual(entries[0]["source_name"], "测试作者")
                self.assertIn("base", entries[0]["transcripts"])
                self.assertGreater(entries[0]["size_bytes"], 12000)
        finally:
            settings.data_dir = old_data_dir

    def test_cache_entries_expose_wechat_account_name_for_ranking(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                cache_dir = settings.data_dir / "cache" / "wechat123"
                cache_dir.mkdir(parents=True)
                write_cache_meta(
                    cache_dir,
                    {
                        "source_url": "https://mp.weixin.qq.com/s/example",
                        "platform": "wechat",
                        "article_info": {
                            "title": "公众号文章",
                            "author": "",
                            "body_text": "正文内容",
                        },
                    },
                )

                with patch(
                    "services.cache._wechat_source_names_by_url",
                    return_value={"https://mp.weixin.qq.com/s/example": "测试公众号"},
                ):
                    entries = list_cache_entries()

                self.assertEqual(entries[0]["content_kind"], "article")
                self.assertEqual(entries[0]["source_name"], "测试公众号")
        finally:
            settings.data_dir = old_data_dir


class SubtitleTests(unittest.TestCase):
    def test_parse_vtt_subtitle_text_strips_timestamps_tags_and_duplicates(self):
        content = """WEBVTT

00:00:01.000 --> 00:00:03.000
<c>第一句内容</c>

00:00:03.000 --> 00:00:05.000
第一句内容

00:00:05.000 --> 00:00:08.000
第二句&nbsp;内容
"""

        transcript = parse_subtitle_text(content, ".vtt")

        self.assertEqual(transcript, "第一句内容\n第二句 内容")

    def test_parse_subtitle_text_normalizes_to_simplified_chinese(self):
        content = """WEBVTT

00:00:00.000 --> 00:00:01.000
這是一個 AI Workflow 測試
"""

        transcript = parse_subtitle_text(content, ".vtt")

        self.assertEqual(transcript, "这是一个 AI Workflow 测试")

    def test_bilibili_pipeline_uses_subtitle_before_download_and_asr(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                settings.deepseek_api_key = "test-key"
                source_context = {
                    "version": 1,
                    "provider": "bilibili",
                    "fetched_at": "2026-07-30T00:00:00+00:00",
                    "engagement": {"play": 100, "comment": 2},
                    "comment_total": 2,
                    "comment_sample_count": 1,
                    "comments_complete": False,
                    "comments": [{"author": "观众", "text": "评论样本"}],
                }

                with (
                    patch("services.pipeline_runner.get_video_info", return_value={"title": "字幕优先测试", "duration": 12}),
                    patch(
                        "services.pipeline_runner.fetch_bilibili_subtitle",
                        return_value=SubtitleFetchResult(
                            success=True,
                            transcript="这是来自 B站字幕的文本",
                            source="bilibili_subtitle",
                        ),
                    ) as subtitle_mock,
                    patch("services.pipeline_runner.download_video") as download_mock,
                    patch("services.pipeline_runner.extract_audio_with_details") as extract_mock,
                    patch("services.pipeline_runner.transcribe_with_details") as transcribe_mock,
                    patch("services.pipeline_runner.load_content_source_text"),
                    patch("services.pipeline_runner.fetch_bilibili_source_context", return_value=source_context) as context_mock,
                    patch("services.pipeline_runner.summarize_stream", return_value=("字幕笔记", "## 快速判断\n值得看")) as summarize_mock,
                    patch(
                        "services.pipeline_runner.replace_content_summary_and_sync",
                        return_value=SimpleNamespace(
                            sync_status="synced",
                            obsidian_path=str(settings.obsidian_vault / "字幕笔记.md"),
                            markdown_draft_path="",
                        ),
                    ),
                ):
                    result = run_pipeline_sync(
                        "https://www.bilibili.com/video/BV1xx411c7mD",
                        whisper_model="base",
                        use_cache=True,
                    )

                self.assertTrue(result.success)
                self.assertEqual(result.transcript, "这是来自 B站字幕的文本")
                self.assertEqual(result.text_source.kind, "subtitle")
                self.assertEqual(result.text_source.source, "bilibili_subtitle")
                self.assertIn("字幕提取完成", "\n".join(log.message for log in result.logs))
                self.assertNotIn("video", result.cache_hits)
                subtitle_mock.assert_called_once()
                context_mock.assert_called_once()
                self.assertEqual(summarize_mock.call_args.kwargs["source_context"], source_context)
                download_mock.assert_not_called()
                extract_mock.assert_not_called()
                transcribe_mock.assert_not_called()
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key

    def test_bilibili_subtitle_summary_runs_while_optional_preview_downloads(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                settings.deepseek_api_key = "test-key"
                download_started = threading.Event()
                allow_download_finish = threading.Event()
                download_finished = threading.Event()

                def download_while_summary_runs(_url, _platform, output_dir, **_kwargs):
                    download_started.set()
                    if not allow_download_finish.wait(timeout=5):
                        raise AssertionError("summary did not start while the preview download was in flight")
                    video_path = output_dir / "preview.mp4"
                    video_path.write_bytes(b"video")
                    download_finished.set()
                    return SimpleNamespace(success=True, video_path=video_path, logs=[], error="", video_info=None)

                def summarize_while_downloading(*_args, **_kwargs):
                    if not download_started.wait(timeout=5):
                        raise AssertionError("preview download did not start before summary")
                    allow_download_finish.set()
                    return "并行字幕笔记", "## 快速判断\n已由外挂字幕总结"

                with (
                    patch("services.pipeline_runner.get_video_info", return_value={"title": "并行测试", "duration": 12}),
                    patch(
                        "services.pipeline_runner.fetch_bilibili_subtitle",
                        return_value=SubtitleFetchResult(success=True, transcript="可直接总结的外挂字幕", source="bilibili_subtitle"),
                    ),
                    # A manual preview request must retain the fast
                    # subtitle-first route even when automatic preview
                    # downloads are disabled.
                    patch("services.pipeline_runner.should_auto_download_bilibili_video", return_value=False),
                    patch("services.pipeline_runner.download_video", side_effect=download_while_summary_runs),
                    patch("services.pipeline_runner.extract_audio_with_details") as extract_mock,
                    patch("services.pipeline_runner.transcribe_with_details") as transcribe_mock,
                    patch("services.pipeline_runner.summarize_stream", side_effect=summarize_while_downloading),
                    patch("services.pipeline_runner.load_content_source_text"),
                    patch(
                        "services.pipeline_runner.replace_content_summary_and_sync",
                        return_value=SimpleNamespace(sync_status="synced", obsidian_path=str(settings.obsidian_vault / "并行字幕笔记.md"), markdown_draft_path=""),
                    ),
                ):
                    result = run_pipeline_sync(
                        "https://www.bilibili.com/video/BV1xx411c7mD",
                        whisper_model="base",
                        use_cache=True,
                        download_video_preview=True,
                    )

                self.assertTrue(result.success)
                self.assertTrue(download_started.is_set())
                self.assertTrue(download_finished.is_set())
                self.assertEqual(result.summary, "## 快速判断\n已由外挂字幕总结")
                self.assertTrue(result.video_path.endswith("preview.mp4"))
                extract_mock.assert_not_called()
                transcribe_mock.assert_not_called()
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key

    def test_bilibili_subtitle_only_never_downloads_or_runs_asr(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                settings.deepseek_api_key = "test-key"
                with (
                    patch("services.pipeline_runner.get_video_info", return_value={"title": "仅字幕测试", "duration": 12}),
                    patch(
                        "services.pipeline_runner.fetch_bilibili_subtitle",
                        return_value=SubtitleFetchResult(success=True, transcript="可信外挂字幕", source="bilibili_subtitle"),
                    ) as subtitle_mock,
                    patch("services.pipeline_runner.should_auto_download_bilibili_video", return_value=True),
                    patch("services.pipeline_runner.download_video") as download_mock,
                    patch("services.pipeline_runner.extract_audio_with_details") as extract_mock,
                    patch("services.pipeline_runner.transcribe_with_details") as transcribe_mock,
                    patch("services.pipeline_runner.summarize_stream", return_value=("字幕笔记", "仅使用外挂字幕完成总结")),
                    patch("services.pipeline_runner.load_content_source_text"),
                    patch(
                        "services.pipeline_runner.replace_content_summary_and_sync",
                        return_value=SimpleNamespace(sync_status="synced", obsidian_path=str(settings.obsidian_vault / "字幕笔记.md"), markdown_draft_path=""),
                    ),
                ):
                    result = run_pipeline_sync(
                        "https://www.bilibili.com/video/BV1xx411c7mD",
                        whisper_model="base",
                        use_cache=True,
                        subtitle_only=True,
                    )

                self.assertTrue(result.success)
                self.assertEqual(result.transcript, "可信外挂字幕")
                self.assertIn("只提取字幕，不下载视频", "\n".join(log.message for log in result.logs))
                subtitle_mock.assert_called_once()
                download_mock.assert_not_called()
                extract_mock.assert_not_called()
                transcribe_mock.assert_not_called()
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key

    def test_bilibili_pipeline_refreshes_player_subtitle_before_old_text_caches(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                settings.deepseek_api_key = "test-key"
                cache_dir = cache_dir_for_url(url)
                write_cached_transcript(cache_dir, "base", "这是旧的 Whisper 缓存")
                write_cached_subtitle_transcript(cache_dir, "这是旧的错误字幕缓存")

                with (
                    patch("services.pipeline_runner.get_video_info", return_value={"title": "字幕覆盖缓存测试", "duration": 12}),
                    patch(
                        "services.pipeline_runner.fetch_bilibili_subtitle",
                        return_value=SubtitleFetchResult(
                            success=True,
                            transcript="这是新读取的播放器外挂字幕",
                            source="bilibili_player_subtitle",
                            source_label="B站播放器外挂字幕",
                            language="中文",
                        ),
                    ) as subtitle_mock,
                    patch("services.pipeline_runner.download_video") as download_mock,
                    patch("services.pipeline_runner.extract_audio_with_details") as extract_mock,
                    patch("services.pipeline_runner.transcribe_with_details") as transcribe_mock,
                    patch("services.pipeline_runner.load_content_source_text"),
                ):
                    result = run_pipeline_sync(url, whisper_model="base", use_cache=True, processing_mode="transcript")

                self.assertTrue(result.success)
                self.assertEqual(result.transcript, "这是新读取的播放器外挂字幕")
                self.assertEqual(result.text_source.kind, "subtitle")
                self.assertEqual(result.text_source.source, "bilibili_player_subtitle")
                self.assertNotIn("transcript", result.cache_hits)
                self.assertNotIn("subtitle", result.cache_hits)
                subtitle_mock.assert_called_once()
                download_mock.assert_not_called()
                extract_mock.assert_not_called()
                transcribe_mock.assert_not_called()
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key

    def test_bilibili_pipeline_falls_back_to_asr_when_subtitle_is_unavailable(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                settings.deepseek_api_key = "test-key"
                source_url = "https://www.bilibili.com/video/BV1xx411c7mD"
                write_cached_subtitle_transcript(cache_dir_for_url(source_url), "这是旧的串台字幕缓存")
                video_path = settings.data_dir / "cache" / "fake" / "video.mp4"
                video_path.parent.mkdir(parents=True)
                video_path.write_bytes(b"0" * 12000)

                download_result = SimpleNamespace(
                    success=True,
                    video_path=video_path,
                    logs=["下载完成"],
                    error="",
                    video_info=None,
                )
                extract_result = SimpleNamespace(success=True, error="", elapsed_seconds=0.1)
                transcribe_result = SimpleNamespace(
                    success=True,
                    transcript="这是 ASR 文本",
                    error="",
                    timings={"whisper_model_load": 0.1, "whisper_decode": 0.2},
                )

                with (
                    patch("services.pipeline_runner.get_video_info", return_value={"title": "回退测试", "duration": 12}),
                    patch(
                        "services.pipeline_runner.fetch_bilibili_subtitle",
                        return_value=SubtitleFetchResult(success=False, error="无字幕"),
                    ),
                    patch("services.pipeline_runner.download_video", return_value=download_result) as download_mock,
                    patch("services.pipeline_runner.extract_audio_with_details", return_value=extract_result) as extract_mock,
                    patch("services.pipeline_runner.transcribe_with_details", return_value=transcribe_result) as transcribe_mock,
                    patch("services.pipeline_runner.summarize_stream", return_value=("回退笔记", "## 快速判断\n可用")),
                ):
                    result = run_pipeline_sync(
                        source_url,
                        whisper_model="base",
                        use_cache=True,
                    )

                self.assertTrue(result.success)
                self.assertEqual(result.transcript, "这是 ASR 文本")
                self.assertEqual(result.text_source.kind, "asr")
                self.assertEqual(result.text_source.source, "faster-whisper")
                self.assertNotIn("subtitle", result.cache_hits)
                self.assertEqual(result.text_source.fallback_reason, "无字幕")
                self.assertIn("改用语音识别", "\n".join(log.message for log in result.logs))
                download_mock.assert_called_once()
                extract_mock.assert_called_once()
                transcribe_mock.assert_called_once()
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key

    def test_douyin_pipeline_uses_download_metadata_without_preflight_info_warning(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                settings.deepseek_api_key = "test-key"
                video_path = settings.data_dir / "cache" / "fake" / "video.mp4"
                video_path.parent.mkdir(parents=True)
                video_path.write_bytes(b"0" * 12000)

                download_result = SimpleNamespace(
                    success=True,
                    video_path=video_path,
                    logs=["下载完成"],
                    error="",
                    video_info={"title": "下载后的抖音标题", "duration": 12, "platform": "douyin"},
                )
                extract_result = SimpleNamespace(success=True, error="", elapsed_seconds=0.1)
                transcribe_result = SimpleNamespace(
                    success=True,
                    transcript="这是抖音语音内容",
                    error="",
                    timings={"whisper_model_load": 0.1, "whisper_decode": 0.2},
                )

                with (
                    patch("services.pipeline_runner.get_video_info") as info_mock,
                    patch("services.pipeline_runner.download_video", return_value=download_result),
                    patch("services.pipeline_runner.extract_audio_with_details", return_value=extract_result),
                    patch("services.pipeline_runner.transcribe_with_details", return_value=transcribe_result),
                    patch("services.pipeline_runner.summarize_stream", return_value=("抖音笔记", "## 快速判断\n可用")) as summarize_mock,
                ):
                    result = run_pipeline_sync(
                        "https://v.douyin.com/abc123/",
                        whisper_model="base",
                        use_cache=False,
                    )

                self.assertTrue(result.success)
                info_mock.assert_not_called()
                self.assertEqual(summarize_mock.call_args.args[1], "下载后的抖音标题")
                self.assertNotIn("获取视频信息失败", "\n".join(log.message for log in result.logs))
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key

    def test_local_subtitle_pipeline_skips_video_processing(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.data_dir.mkdir(parents=True)
                settings.obsidian_vault.mkdir(parents=True)
                settings.deepseek_api_key = "test-key"
                subtitle_path = settings.data_dir / "uploaded.vtt"
                subtitle_path.write_text(
                    "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n本地字幕内容\n",
                    encoding="utf-8",
                )

                with (
                    patch("services.pipeline_runner.download_video") as download_mock,
                    patch("services.pipeline_runner.extract_audio_with_details") as extract_mock,
                    patch("services.pipeline_runner.transcribe_with_details") as transcribe_mock,
                    patch("services.pipeline_runner.summarize_stream", return_value=("本地字幕笔记", "## 快速判断\n可读")),
                ):
                    result = run_pipeline_sync(
                        local_subtitle_path=str(subtitle_path),
                        source_title="本地字幕",
                        whisper_model="base",
                    )

                self.assertTrue(result.success)
                self.assertEqual(result.platform, "subtitle")
                self.assertEqual(result.transcript, "本地字幕内容")
                self.assertEqual(result.text_source.kind, "subtitle")
                self.assertEqual(result.text_source.source, "manual")
                self.assertIn("字幕解析完成", "\n".join(log.message for log in result.logs))
                download_mock.assert_not_called()
                extract_mock.assert_not_called()
                transcribe_mock.assert_not_called()
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key


class DatabaseTests(unittest.TestCase):
    def test_initialize_database_creates_core_tables_and_migration_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "app.db"

            initialize_database(db_path)

            connection = connect(db_path)
            try:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
                    )
                }
                self.assertIn("schema_migrations", tables)
                self.assertIn("content_items", tables)
                self.assertIn("series", tables)
                self.assertIn("tasks", tables)
                self.assertIn("prompt_templates", tables)
                self.assertIn("library_folders", tables)
                self.assertIn("content_analyses", tables)
                self.assertNotIn("tags", tables)
                self.assertNotIn("content_tags", tables)
                version = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
                self.assertEqual(version["version"], SCHEMA_VERSION)
                report_schema = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='wechat_reports'"
                ).fetchone()
                self.assertIn("'range'", report_schema["sql"])
                prompt_count = connection.execute("SELECT COUNT(*) AS count FROM prompt_templates").fetchone()
                self.assertGreaterEqual(prompt_count["count"], 4)
            finally:
                connection.close()

    def test_source_provider_items_are_auto_classified_into_default_folders(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)

                item = ensure_content_item_for_media(
                    source_provider="douyin",
                    source_url="https://v.douyin.com/abc123/",
                    video_info={"id": "abc123", "title": "抖音测试"},
                    status="to_read",
                )

                with connect() as connection:
                    folder = connection.execute(
                        "SELECT * FROM library_folders WHERE id = ?",
                        (item.library_folder_id,),
                    ).fetchone()

                self.assertIsNotNone(folder)
                self.assertEqual(folder["name"], "抖音")
        finally:
            settings.data_dir = old_data_dir

    def test_direct_bilibili_pipeline_items_keep_parts_distinct(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                p1 = ensure_content_item_for_media(
                    source_provider="bilibili",
                    source_url="https://www.bilibili.com/video/BV1xx411c7mD",
                    video_info={"id": "BV1xx411c7mD", "title": "第一集"},
                )
                p2 = ensure_content_item_for_media(
                    source_provider="bilibili",
                    source_url="https://www.bilibili.com/video/BV1xx411c7mD?p=2",
                    video_info={"id": "BV1xx411c7mD", "title": "第二集"},
                )
                p3 = ensure_content_item_for_media(
                    source_provider="bilibili",
                    source_url="https://www.bilibili.com/video/BV1xx411c7mD?p=3",
                    video_info={},
                )

                self.assertEqual(p1.canonical_source_id, "BV1xx411c7mD")
                self.assertEqual(p2.canonical_source_id, "BV1xx411c7mD:p2")
                self.assertEqual(p3.canonical_source_id, "BV1xx411c7mD:p3")
                self.assertNotEqual(p1.id, p2.id)
                self.assertNotEqual(p2.id, p3.id)
        finally:
            settings.data_dir = old_data_dir

    def test_direct_bilibili_pipeline_repairs_a_legacy_part_before_creating_p1(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    legacy_p2 = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        source_url="https://www.bilibili.com/video/BV1xx411c7mD?p=2",
                        canonical_source_id="BV1xx411c7mD",
                        title="旧版第二集",
                    )
                    connection.commit()

                p1 = ensure_content_item_for_media(
                    source_provider="bilibili",
                    source_url="https://www.bilibili.com/video/BV1xx411c7mD",
                    video_info={"id": "BV1xx411c7mD", "title": "第一集"},
                )

                with connect() as connection:
                    repaired_p2 = ContentRepository(connection).get_content_item(legacy_p2.id)
                self.assertEqual(repaired_p2.canonical_source_id, "BV1xx411c7mD:p2")
                self.assertEqual(p1.canonical_source_id, "BV1xx411c7mD")
                self.assertNotEqual(p1.id, repaired_p2.id)
        finally:
            settings.data_dir = old_data_dir

    def test_content_and_task_repositories_support_basic_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "app.db"
            initialize_database(db_path)
            connection = connect(db_path)
            try:
                content_repo = ContentRepository(connection)
                task_repo = TaskRepository(connection)

                item = content_repo.create_content_item(
                    source_provider="bilibili",
                    source_url="https://www.bilibili.com/video/BV123",
                    canonical_source_id="BV123",
                    title="测试视频",
                )
                duplicate = content_repo.find_by_canonical_id(
                    source_provider="bilibili",
                    canonical_source_id="BV123",
                )
                task = task_repo.create_task(
                    task_type="process_video",
                    content_item_id=item.id,
                    priority=20,
                )
                task_repo.create_task(task_type="process_video", priority=50)
                updated_task = task_repo.update_task_state(
                    task.id,
                    status="running",
                    current_stage="transcribe",
                    progress=42.5,
                )

                self.assertIsNotNone(duplicate)
                self.assertEqual(duplicate.id, item.id)
                self.assertEqual(item.status, "inbox")
                self.assertEqual(updated_task.status, "running")
                self.assertEqual(updated_task.current_stage, "transcribe")
                self.assertEqual(updated_task.progress, 42.5)
                queued = task_repo.list_queued()
                self.assertEqual(len(queued), 1)
                self.assertEqual(queued[0].priority, 50)
            finally:
                connection.close()


class SearchIndexTests(unittest.TestCase):
    def test_search_index_finds_indexed_summary_and_transcript(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="local",
                        canonical_source_id="content-1",
                        title="效率学习视频",
                    )
                    connection.commit()
                upsert_search_document(
                    content_key=item.id,
                    title="效率学习视频",
                    summary="这是一条关于学习效率的总结。",
                    transcript="原始文本提到了费曼技巧和复盘。",
                )

                results = search_documents("效率")

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].content_key, item.id)
                self.assertEqual(results[0].title, "效率学习视频")
        finally:
            settings.data_dir = old_data_dir

    def test_search_api_returns_indexed_results(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="local",
                        canonical_source_id="content-2",
                        title="AI 工具视频",
                    )
                    connection.commit()
                upsert_search_document(
                    content_key=item.id,
                    title="AI 工具视频",
                    summary="介绍 AI 工作流。",
                    transcript="包含剪贴板监听和自动总结。",
                )
                client = TestClient(app)

                response = client.get("/api/search?q=工作流")

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data[0]["content_key"], item.id)
                self.assertIn("AI 工具", data[0]["title"])
        finally:
            settings.data_dir = old_data_dir

    def test_source_text_index_keeps_existing_summary(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="local",
                        canonical_source_id="content-3",
                        title="原始标题",
                    )
                    connection.commit()
                upsert_search_document(
                    content_key=item.id,
                    title="原始标题",
                    summary="已经生成的摘要内容。",
                    transcript="旧的转写内容。",
                )

                upsert_source_text_document(
                    content_key=item.id,
                    title="抓取后的标题",
                    transcript="刚刚抓到的公众号正文。",
                )

                self.assertEqual(search_documents("已经生成")[0].content_key, item.id)
                self.assertEqual(search_documents("公众号正文")[0].title, "抓取后的标题")
        finally:
            settings.data_dir = old_data_dir

    def test_rebuild_search_index_reads_local_markdown_without_network_or_ai(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat_report",
                        content_type="report",
                        canonical_source_id="report:search-rebuild",
                        title="校园日报",
                    )
                    connection.commit()
                save_markdown_draft_and_sync(
                    markdown="# 校园日报\n\n## 本期概览\n\n图书馆公布暑期开放安排。\n",
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / "reports" / "校园日报.md",
                    content_item_id=item.id,
                )

                stats = rebuild_search_index()

                self.assertEqual(stats["content_count"], 1)
                self.assertEqual(stats["markdown_indexed_count"], 1)
                self.assertEqual(search_documents("暑期开放")[0].content_key, item.id)
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

class WeChatSubscriptionTests(unittest.TestCase):
    def test_subscription_failure_backoff_is_recorded_and_success_resets_it(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                now = "2026-07-14T00:00:00+00:00"
                with connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO wechat_accounts (id, display_name, keychain_ref, status, created_at, updated_at)
                        VALUES ('account-backoff', '测试账号', 'test-backoff-keychain-ref', 'active', ?, ?)
                        """,
                        (now, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO wechat_subscriptions (
                            id, account_id, fakeid, mp_name, enabled, sync_interval_minutes,
                            next_sync_at, created_at, updated_at
                        ) VALUES ('subscription-backoff', 'account-backoff', 'fakeid', '测试公众号', 1, 60, ?, ?, ?)
                        """,
                        (now, now, now),
                    )
                    connection.commit()

                service = WeChatSubscriptionService()
                with patch("services.wechat_subscription._iso_after", return_value="2026-07-14T00:15:00+00:00") as delay_mock:
                    service._mark_sync_failure("subscription-backoff", "远端暂不可用", "remote")

                details = service.get_subscription("subscription-backoff")
                self.assertEqual(details["consecutive_failure_count"], 1)
                self.assertEqual(details["last_error_category"], "remote")
                self.assertEqual(details["next_sync_at"], "2026-07-14T00:15:00+00:00")
                self.assertEqual(delay_mock.call_args.args[0], 15)

                with patch("services.wechat_subscription._iso_after", return_value="2026-07-14T01:00:00+00:00"):
                    service._mark_sync_success("subscription-backoff", 60)

                recovered = service.get_subscription("subscription-backoff")
                self.assertEqual(recovered["consecutive_failure_count"], 0)
                self.assertIsNone(recovered["last_error"])
                self.assertIsNone(recovered["last_error_category"])
        finally:
            settings.data_dir = old_data_dir

    def test_subscription_exposes_latest_sync_result_and_reschedules_on_interval_change(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                now = "2026-07-14T00:00:00+00:00"
                with connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO wechat_accounts (id, display_name, keychain_ref, status, created_at, updated_at)
                        VALUES ('account-1', '测试账号', 'test-keychain-ref', 'active', ?, ?)
                        """,
                        (now, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO wechat_subscriptions (
                            id, account_id, fakeid, mp_name, enabled, auto_process,
                            sync_interval_minutes, next_sync_at, last_sync_at, created_at, updated_at
                        ) VALUES ('subscription-1', 'account-1', 'fakeid', '测试公众号', 1, 0, 360, ?, ?, ?, ?)
                        """,
                        ("2026-07-14T06:00:00+00:00", now, now, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO wechat_sync_runs (
                            id, subscription_id, status, started_at, finished_at, found_count, imported_count
                        ) VALUES ('run-1', 'subscription-1', 'succeeded', ?, ?, 4, 2)
                        """,
                        (now, "2026-07-14T00:01:00+00:00"),
                    )
                    connection.commit()

                service = WeChatSubscriptionService()
                details = service.get_subscription("subscription-1")
                self.assertEqual(details["last_run_status"], "succeeded")
                self.assertEqual(details["last_run_found_count"], 4)
                self.assertEqual(details["last_run_imported_count"], 2)

                with patch("services.wechat_subscription._iso_after", return_value="2026-07-14T01:00:00+00:00"):
                    updated = service.update_subscription("subscription-1", sync_interval_minutes=720)

                self.assertEqual(updated["sync_interval_minutes"], 720)
                self.assertEqual(updated["next_sync_at"], "2026-07-14T01:00:00+00:00")

                with connect() as connection:
                    connection.execute(
                        "INSERT INTO wechat_subscription_groups (id, name, created_at, updated_at) VALUES ('group-1', '行业动态', ?, ?)",
                        (now, now),
                    )
                    connection.commit()

                grouped = service.update_subscription("subscription-1", group_id="group-1")
                self.assertEqual(grouped["group_id"], "group-1")

                ungrouped = service.update_subscription("subscription-1", group_id=None)
                self.assertIsNone(ungrouped["group_id"])
        finally:
            settings.data_dir = old_data_dir

    def test_scheduler_checks_due_subscriptions_immediately_on_start(self):
        class FakeService:
            def __init__(self):
                self.calls = 0

            def sync_due_subscriptions(self):
                self.calls += 1

        service = FakeService()
        scheduler = WeChatSubscriptionScheduler(service)
        scheduler._stop_event.set()

        scheduler._run()

        self.assertEqual(service.calls, 1)


class ContentTaskRetryApiTests(unittest.TestCase):
    def test_retry_latest_failed_task_for_content(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        source_url="https://www.bilibili.com/video/BV1retry",
                        canonical_source_id="BV1retry",
                        title="处理失败的视频",
                        status="failed",
                    )
                    connection.execute(
                        """
                        INSERT INTO tasks (
                            id, task_type, content_item_id, status, priority, created_at, updated_at
                        ) VALUES ('retry-content-task', 'process_video', ?, 'failed', 100, ?, ?)
                        """,
                        (item.id, item.created_at, item.updated_at),
                    )
                    connection.commit()

                retried = TaskRecord(
                    task_id="retry-content-task",
                    content_item_id=item.id,
                    status="queued",
                )
                client = TestClient(app)
                with patch("routers.tasks.task_manager.retry", return_value=retried) as retry_mock:
                    response = client.post(f"/api/content/{item.id}/retry-processing")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "queued")
                retry_mock.assert_called_once_with("retry-content-task")
        finally:
            settings.data_dir = old_data_dir


class InboxTests(unittest.TestCase):
    def test_capture_link_to_inbox_keeps_bilibili_parts_distinct_and_deduplicates_p1(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)

                first = capture_link_to_inbox("https://www.bilibili.com/video/BV1xx411c7mD?p=2")
                second = capture_link_to_inbox("https://www.bilibili.com/video/BV1xx411c7mD")
                duplicate_p1 = capture_link_to_inbox("https://www.bilibili.com/video/BV1xx411c7mD?p=1")

                self.assertTrue(first.created)
                self.assertFalse(first.duplicate)
                self.assertIsNotNone(first.item)
                self.assertEqual(first.item.source_provider, "bilibili")
                self.assertEqual(first.item.status, "inbox")
                self.assertEqual(first.item.source_url, "https://www.bilibili.com/video/BV1xx411c7mD?p=2")
                self.assertEqual(first.item.canonical_source_id, "BV1xx411c7mD:p2")
                self.assertTrue(second.created)
                self.assertFalse(second.duplicate)
                self.assertEqual(second.item.canonical_source_id, "BV1xx411c7mD")
                self.assertNotEqual(second.item.id, first.item.id)
                self.assertFalse(duplicate_p1.created)
                self.assertTrue(duplicate_p1.duplicate)
                self.assertEqual(duplicate_p1.item.id, second.item.id)
        finally:
            settings.data_dir = old_data_dir

    def test_capture_link_to_inbox_repairs_a_legacy_bilibili_part_identity(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                source_url = "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
                with connect() as connection:
                    legacy = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        source_url=source_url,
                        canonical_source_id="BV1xx411c7mD",
                        title="旧版第二集",
                    )
                    connection.commit()

                captured = capture_link_to_inbox(source_url)

                self.assertTrue(captured.duplicate)
                self.assertEqual(captured.item.id, legacy.id)
                self.assertEqual(captured.item.canonical_source_id, "BV1xx411c7mD:p2")
        finally:
            settings.data_dir = old_data_dir

    def test_inbox_api_captures_and_lists_items(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                client = TestClient(app)

                capture_response = client.post(
                    "/api/inbox/capture",
                    json={"url": "https://www.douyin.com/video/7660847053097979199"},
                )
                self.assertEqual(capture_response.status_code, 200)
                data = capture_response.json()
                self.assertTrue(data["created"])
                self.assertEqual(data["item"]["source_provider"], "douyin")

                list_response = client.get("/api/inbox")
                self.assertEqual(list_response.status_code, 200)
                items = list_response.json()
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["canonical_source_id"], "7660847053097979199")
        finally:
            settings.data_dir = old_data_dir

    def test_process_inbox_item_creates_bound_task_and_updates_status(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                captured = capture_link_to_inbox("https://www.bilibili.com/video/BV1xx411c7mD")

                with patch("services.task_manager.TaskManager._schedule_next"):
                    item, task = process_inbox_item(captured.item.id, whisper_model="base", use_cache=False)

                self.assertEqual(item.status, "processing")
                self.assertEqual(task.content_item_id, captured.item.id)
                with connect(settings.data_dir / "app.db") as connection:
                    task_row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task.task_id,)).fetchone()
                    item_row = connection.execute("SELECT * FROM content_items WHERE id = ?", (captured.item.id,)).fetchone()
                    self.assertEqual(task_row["content_item_id"], captured.item.id)
                    self.assertEqual(item_row["status"], "processing")
        finally:
            settings.data_dir = old_data_dir

    def test_inbox_process_api_returns_task_id(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                captured = capture_link_to_inbox("https://www.bilibili.com/video/BV1xx411c7mD")
                client = TestClient(app)

                with patch("services.task_manager.TaskManager._schedule_next"):
                    response = client.post(
                        f"/api/inbox/{captured.item.id}/process",
                        json={"whisper_model": "base", "use_cache": False},
                    )

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["item"]["status"], "processing")
                self.assertTrue(data["task_id"])
        finally:
            settings.data_dir = old_data_dir


class PromptApiTests(unittest.TestCase):
    def test_prompt_api_lists_seeded_templates_and_activates_custom_template(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                client = TestClient(app)

                list_response = client.get("/api/prompts?task_type=summary")
                self.assertEqual(list_response.status_code, 200)
                seeded = list_response.json()
                self.assertTrue(any(item["name"] == "default_summary" for item in seeded))

                create_response = client.post(
                    "/api/prompts",
                    json={
                        "name": "custom_summary",
                        "task_type": "summary",
                        "version": "v2",
                        "template": "新的总结提示词",
                        "variables_schema": {"required": ["transcript"]},
                        "is_active": False,
                    },
                )
                self.assertEqual(create_response.status_code, 200)
                created = create_response.json()
                self.assertFalse(created["is_active"])

                activate_response = client.post(f"/api/prompts/{created['id']}/activate")
                self.assertEqual(activate_response.status_code, 200)
                self.assertTrue(activate_response.json()["is_active"])

                final_response = client.get("/api/prompts?task_type=summary")
                active = [item for item in final_response.json() if item["is_active"]]
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0]["name"], "custom_summary")
        finally:
            settings.data_dir = old_data_dir

    def test_prompt_seed_upgrades_only_unmodified_default_qa(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                client = TestClient(app)

                qa_templates = client.get("/api/prompts", params={"task_type": "qa"}).json()

                active = [item for item in qa_templates if item["is_active"]]
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0]["version"], "v2")
                self.assertIn("模型补充", active[0]["template"])

                shortcuts = client.get("/api/prompts", params={"task_type": "qa_shortcut"}).json()
                self.assertTrue({"拓展", "关联", "反例"}.issubset({item["name"] for item in shortcuts}))

                custom_buttons = client.get("/api/prompts", params={"task_type": "content_analysis"}).json()
                active_button = next(item for item in custom_buttons if item["is_active"])
                self.assertEqual(active_button["name"], "自定义按钮")

                renamed = client.patch(
                    f"/api/prompts/{active_button['id']}",
                    json={"name": "重点摘录按钮"},
                )
                self.assertEqual(renamed.status_code, 200)
                self.assertEqual(renamed.json()["name"], "重点摘录按钮")
        finally:
            settings.data_dir = old_data_dir

    def test_permanent_prompt_delete_removes_local_markdown_mirror(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                client = TestClient(app)
                client.get("/api/prompts", params={"task_type": "summary"})
                created = client.post(
                    "/api/prompts",
                    json={
                        "name": "待永久删除的提示词",
                        "task_type": "summary",
                        "version": "v1",
                        "template": "测试提示词正文",
                    },
                ).json()
                local_path = Path(created["local_path"])
                self.assertTrue(local_path.exists())

                self.assertEqual(client.delete(f"/api/prompts/{created['id']}").status_code, 204)
                self.assertEqual(
                    client.delete(f"/api/prompts/trash/prompt/{created['id']}").status_code,
                    200,
                )
                self.assertFalse(local_path.exists())
        finally:
            settings.data_dir = old_data_dir

    def test_permanent_folder_delete_removes_all_local_prompt_mirrors(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                client = TestClient(app)
                client.get("/api/prompts", params={"task_type": "summary"})
                folder = client.post(
                    "/api/prompt-folders",
                    json={"name": "待永久删除的文件夹", "task_type": "summary"},
                ).json()
                created = client.post(
                    "/api/prompts",
                    json={
                        "name": "文件夹内提示词",
                        "task_type": "summary",
                        "version": "v1",
                        "template": "测试提示词正文",
                        "folder_id": folder["id"],
                    },
                ).json()
                local_path = Path(created["local_path"])
                self.assertTrue(local_path.exists())

                self.assertEqual(client.delete(f"/api/prompt-folders/{folder['id']}").status_code, 204)
                self.assertEqual(
                    client.delete(f"/api/prompts/trash/folder/{folder['id']}").status_code,
                    200,
                )
                self.assertFalse(local_path.exists())
        finally:
            settings.data_dir = old_data_dir


class ObsidianSettingsApiTests(unittest.TestCase):
    def test_obsidian_settings_persist_and_apply_to_runtime_vault(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                target = root / "Obsidian" / "KnowledgeHub"
                client = TestClient(app)

                saved = client.post("/api/obsidian/settings", json={"vault_path": str(target)})

                self.assertEqual(saved.status_code, 200)
                self.assertEqual(saved.json()["vault_path"], str(target.resolve()))
                self.assertEqual(settings.obsidian_vault, target.resolve())
                self.assertTrue((settings.data_dir / "obsidian_settings.json").exists())

                restored = client.get("/api/obsidian/settings")
                self.assertEqual(restored.status_code, 200)
                self.assertEqual(restored.json()["vault_path"], str(target.resolve()))
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_switching_vault_keeps_old_notes_managed_for_permanent_delete(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                first_vault = root / "first-vault"
                second_vault = root / "second-vault"
                save_obsidian_settings(first_vault, export_path=first_vault, auto_write=True)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="local_markdown",
                        canonical_source_id="delete-old-vault-note",
                        title="旧 Vault 笔记",
                    )
                    connection.commit()

                state = save_markdown_draft_and_sync(
                    markdown="# 旧 Vault 笔记\n",
                    title=item.title,
                    obsidian_path=first_vault / f"{item.id}.md",
                    content_item_id=item.id,
                )
                note_path = Path(state.obsidian_path)
                self.assertTrue(note_path.exists())
                save_obsidian_settings(second_vault, export_path=second_vault, auto_write=True)
                self.assertTrue(is_managed_obsidian_note_path(note_path))
                self.assertFalse(is_managed_obsidian_note_path(root / "unmanaged" / "note.md"))

                client = TestClient(app)
                self.assertEqual(client.delete(f"/api/content/{item.id}").status_code, 200)
                self.assertEqual(client.delete(f"/api/content/trash/content/{item.id}").status_code, 200)
                self.assertFalse(note_path.exists())
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault


class DownloadStorageTests(unittest.TestCase):
    def test_bilibili_format_never_selects_above_1080p(self):
        self.assertIn("height<=1080", BILIBILI_1080P_FORMAT)

    def test_douyin_signed_url_refreshes_only_for_authorization_rejections(self):
        self.assertTrue(_needs_douyin_media_refresh(401))
        self.assertTrue(_needs_douyin_media_refresh(403))
        self.assertFalse(_needs_douyin_media_refresh(500))
        self.assertFalse(_needs_douyin_media_refresh(None))

    def test_douyin_low_bandwidth_policy_uses_lowest_advertised_variant(self):
        payload = {
            "data": {
                "aweme_detail": {
                    "aweme_id": "123",
                    "video": {
                        "bit_rate": [
                            {"bit_rate": 950000, "gear_name": "normal_1080", "play_addr": {"url_list": ["https://cdn.example/1080"]}},
                            {"bit_rate": 280000, "gear_name": "adapt_lower_540", "play_addr": {"url_list": ["https://cdn.example/540"]}},
                        ]
                    },
                }
            }
        }
        self.assertEqual(
            _lowest_douyin_video_variant(payload, "123"),
            ("https://cdn.example/540", 280000, "adapt_lower_540"),
        )

    def test_yt_dlp_speed_parser_reports_the_live_rate(self):
        self.assertEqual(_yt_dlp_bytes_per_second("[download] 50.0% of 20.00MiB at 1.50MiB/s ETA 00:05"), 1.5 * 1024**2)
        self.assertIsNone(_yt_dlp_bytes_per_second("[download] 50.0% of 20.00MiB"))

    def test_douyin_browser_capture_matches_modern_video_hosts(self):
        self.assertTrue(_looks_like_douyin_video_url("https://v3-web.douyinvod.com/video/tos/example.mp4"))
        self.assertTrue(_looks_like_douyin_video_url("https://www.douyin.com/aweme/v1/play/?video_id=abc&mime_type=video_mp4"))
        self.assertTrue(
            _looks_like_douyin_video_url(
                "https://cdb9c88d-9.sjxydc.com/video/tos/example.mp4?mime_type=video_mp4&dy_q=123"
            )
        )
        self.assertFalse(_looks_like_douyin_video_url("https://example.com/video/tos/example.mp4"))
        self.assertFalse(
            _looks_like_douyin_video_url("https://example.com/video/tos/example.mp4?mime_type=video_mp4")
        )

    def test_douyin_browser_capture_wait_is_long_enough_for_delayed_page_hydration(self):
        from services.downloader import DOUYIN_MEDIA_CAPTURE_WAIT_SECONDS

        self.assertGreaterEqual(DOUYIN_MEDIA_CAPTURE_WAIT_SECONDS, 15)

    def test_douyin_browser_capture_failure_distinguishes_cookie_and_browser_causes(self):
        self.assertIn(
            "登录或安全验证",
            _browser_capture_failure_message("https://www.douyin.com/login", "", True),
        )
        self.assertIn(
            "未加载抖音 Cookie",
            _browser_capture_failure_message("https://www.douyin.com/video/1", "", False),
        )
        self.assertIn(
            "并非已确认 Cookie 失效",
            _browser_capture_failure_message("https://www.douyin.com/video/1", "正常页面", True),
        )

    def test_compress_video_for_storage_copies_audio_and_replaces_large_video(self):
        old_compress = settings.compress_downloaded_video
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                settings.compress_downloaded_video = True
                video_path = Path(temp_dir) / "source.mp4"
                video_path.write_bytes(b"1" * 50000)
                logs = []
                captured_cmd = {}

                def fake_run(cmd, *, output_path, **_kwargs):
                    captured_cmd["cmd"] = cmd
                    output_path.write_bytes(b"2" * 12000)
                    return SimpleNamespace(success=True, cancelled=False, stalled=False, returncode=0, stderr="")

                with patch("services.downloader.run_ffmpeg", side_effect=fake_run):
                    optimized = _compress_video_for_storage(video_path, logs)

                self.assertEqual(optimized.name, "source_compact.mp4")
                self.assertTrue(optimized.exists())
                self.assertFalse(video_path.exists())
                self.assertIn("-c:a", captured_cmd["cmd"])
                audio_codec_index = captured_cmd["cmd"].index("-c:a") + 1
                self.assertEqual(captured_cmd["cmd"][audio_codec_index], "aac")
                self.assertIn("+faststart", captured_cmd["cmd"])
                self.assertTrue(any("节省" in line for line in logs))
            finally:
                settings.compress_downloaded_video = old_compress


class CacheApiTests(unittest.TestCase):
    def test_content_library_supports_folder_and_content_mutations(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                source_url = "https://example.com/library-video"
                cache_dir = settings.data_dir / "cache" / cache_key_for_url(source_url)
                cache_dir.mkdir(parents=True)
                (cache_dir / "video.mp4").write_bytes(b"0" * 12000)
                write_cache_meta(cache_dir, {"source_url": source_url, "platform": "douyin"})

                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="douyin",
                        source_url=source_url,
                        canonical_source_id="library-video",
                        title="原标题",
                    )
                    connection.commit()

                client = TestClient(app)
                created_folder = client.post("/api/content/folders", json={"name": "课程"}).json()
                self.assertEqual(created_folder["name"], "课程")
                location = client.get(f"/api/content/folders/{created_folder['id']}/location")
                self.assertEqual(location.status_code, 200)
                self.assertTrue(Path(location.json()["path"]).is_dir())
                self.assertEqual(Path(location.json()["path"]).name, "课程")

                renamed_folder = client.patch(
                    f"/api/content/folders/{created_folder['id']}",
                    json={"name": "课程资料"},
                ).json()
                self.assertEqual(renamed_folder["name"], "课程资料")

                pinned_folder = client.patch(
                    f"/api/content/folders/{created_folder['id']}",
                    json={"is_pinned": True},
                ).json()
                self.assertTrue(pinned_folder["is_pinned"])
                self.assertTrue(next(
                    folder for folder in client.get("/api/content/folders").json()
                    if folder["id"] == created_folder["id"]
                )["is_pinned"])
                restored_folder = client.patch(
                    f"/api/content/folders/{created_folder['id']}",
                    json={"is_pinned": False},
                ).json()
                self.assertFalse(restored_folder["is_pinned"])

                updated_item = client.patch(
                    f"/api/content/{item.id}",
                    json={
                        "title": "新标题",
                        "library_folder_id": created_folder["id"],
                        "sort_order": 3,
                    },
                ).json()
                self.assertEqual(updated_item["title"], "新标题")
                self.assertEqual(updated_item["library_folder_id"], created_folder["id"])

                delete_response = client.delete(f"/api/content/{item.id}")
                self.assertEqual(delete_response.status_code, 200)
                self.assertTrue(cache_dir.exists())
                trash = client.get("/api/content/trash").json()
                entry = next(entry for entry in trash if entry["id"] == item.id)
                self.assertEqual(entry["source_provider"], "douyin")
                self.assertEqual(entry["content_type"], "video")

                permanent = client.delete(f"/api/content/trash/content/{item.id}")
                self.assertEqual(permanent.status_code, 200)
                self.assertFalse(cache_dir.exists())
        finally:
            settings.data_dir = old_data_dir

    def test_permanent_delete_removes_auto_written_obsidian_note(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                save_obsidian_settings(
                    settings.obsidian_vault,
                    export_path=settings.obsidian_vault,
                    auto_write=True,
                )
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="local_markdown",
                        canonical_source_id="delete-obsidian-note",
                        title="待删除 Obsidian 笔记",
                    )
                    connection.commit()

                state = save_markdown_draft_and_sync(
                    markdown="# 待删除 Obsidian 笔记\n\n测试内容",
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / "导入 Markdown" / f"{item.id}.md",
                    content_item_id=item.id,
                )
                draft_path = Path(state.markdown_draft_path)
                note_path = Path(state.obsidian_path)
                self.assertTrue(draft_path.exists())
                self.assertTrue(note_path.exists())

                client = TestClient(app)
                self.assertEqual(client.delete(f"/api/content/{item.id}").status_code, 200)
                self.assertEqual(client.delete(f"/api/content/trash/content/{item.id}").status_code, 200)
                self.assertFalse(draft_path.exists())
                self.assertFalse(note_path.exists())
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_permanent_delete_removes_source_markdown_and_attachments(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                initialize_database()
                source_document = settings.data_dir / "library" / "bilibili" / "测试源文档.md"
                source_document.parent.mkdir(parents=True)
                source_document.write_text("# 测试源文档\n", encoding="utf-8")

                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        source_url="https://www.bilibili.com/video/BV1delete-source",
                        canonical_source_id="delete-source-document",
                        title="待删除源文档",
                    )
                    attachment_dir = settings.data_dir / "attachments" / item.id
                    attachment_dir.mkdir(parents=True)
                    attachment_path = attachment_dir / "video.mp4"
                    attachment_path.write_bytes(b"test-video")
                    connection.execute(
                        """
                        INSERT INTO content_documents (content_item_id, markdown_path, content_hash, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (item.id, str(source_document), "test-hash", item.updated_at),
                    )
                    connection.commit()

                client = TestClient(app)
                self.assertEqual(client.delete(f"/api/content/{item.id}").status_code, 200)
                self.assertEqual(client.delete(f"/api/content/trash/content/{item.id}").status_code, 200)
                self.assertFalse(source_document.exists())
                self.assertFalse(attachment_path.exists())
                self.assertFalse(attachment_dir.exists())
        finally:
            settings.data_dir = old_data_dir


class ContentAnalysisTests(unittest.TestCase):
    def test_report_analysis_uses_current_markdown_without_source_url(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat_report",
                        content_type="report",
                        canonical_source_id="report:custom-action",
                        title="2026-07-17 日报",
                        status="to_read",
                    )
                    connection.commit()

                report_markdown = "# 2026-07-17 日报\n\n## 今日重点\n\n学校发布了新的活动安排。"
                save_markdown_draft_and_sync(
                    markdown=report_markdown,
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / "日报" / f"{item.title}.md",
                    content_item_id=item.id,
                )

                class FakeProvider:
                    name = "test"
                    model = "test-model"

                    def __init__(self):
                        self.messages = []

                    def chat(self, messages, *, temperature=0.2):
                        self.messages = messages
                        return LLMResponse(
                            content="## 待办\n\n已从日报提取待办。",
                            provider=self.name,
                            model=self.model,
                        )

                provider = FakeProvider()
                with patch("services.content_analysis.load_content_source_text") as source_loader:
                    record = create_content_analysis(item.id, provider=provider)

                source_loader.assert_not_called()
                self.assertEqual(record.content_item_id, item.id)
                self.assertIn("材料类型：日报或周报", provider.messages[1].content)
                self.assertIn("当前材料：", provider.messages[1].content)
                self.assertIn(report_markdown, provider.messages[1].content)
                self.assertEqual(list_content_analyses(item.id)[0].id, record.id)
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_campus_analysis_falls_back_to_the_shared_custom_action_prompt(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="campus",
                        content_type="article",
                        source_url="https://ai.sztu.edu.cn/info/1039/1234.htm",
                        canonical_source_id="campus-ai-analysis",
                        title="人工智能学院通知",
                        status="to_read",
                    )
                    connection.commit()

                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url or "",
                    text="这是面向学生的学院通知正文。",
                    source_kind="article",
                )

                class FakeProvider:
                    name = "test"
                    model = "test-model"

                    def __init__(self):
                        self.messages = []

                    def chat(self, messages, *, temperature=0.2):
                        self.messages = messages
                        return LLMResponse(
                            content="## 复盘\n\n已使用通用深度复盘提示词。",
                            provider=self.name,
                            model=self.model,
                        )

                provider = FakeProvider()
                with patch("services.content_analysis.load_content_source_text", return_value=source):
                    record = create_content_analysis(item.id, provider=provider)

                self.assertEqual(record.prompt_template_name, "自定义按钮")
                self.assertIn("深度复盘", provider.messages[0].content)
                self.assertIn(source.text, provider.messages[1].content)
        finally:
            settings.data_dir = old_data_dir

    def test_manual_analysis_uses_source_text_and_persists_independently(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/analysis-history",
                        canonical_source_id="analysis-history",
                        title="结构化分析测试",
                        status="to_read",
                    )
                    template = PromptTemplateRepository(connection).get_active_template("content_analysis")
                    connection.commit()

                self.assertIsNotNone(template)
                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url or "",
                    text="这里是可供分析的公众号正文，包含一个明确观点。",
                    source_kind="article",
                )

                class FakeProvider:
                    name = "test"
                    model = "test-model"

                    def __init__(self):
                        self.messages = []

                    def chat(self, messages, *, temperature=0.2):
                        self.messages = messages
                        return LLMResponse(
                            content="## 摘要\n\n已保存的结构化分析。",
                            provider=self.name,
                            model=self.model,
                        )

                provider = FakeProvider()
                with patch("services.content_analysis.load_content_source_text", return_value=source):
                    record = create_content_analysis(
                        item.id,
                        template_id=template.id,
                        provider=provider,
                    )

                self.assertEqual(record.content_item_id, item.id)
                self.assertEqual(record.prompt_template_id, template.id)
                self.assertEqual(record.model, "test-model")
                self.assertIn(source.text, provider.messages[1].content)
                self.assertEqual(list_content_analyses(item.id)[0].id, record.id)
                with connect() as connection:
                    call = connection.execute(
                        "SELECT call_type, content_item_id FROM ai_calls ORDER BY created_at DESC LIMIT 1"
                    ).fetchone()
                self.assertEqual(call["call_type"], "content_analysis")
                self.assertEqual(call["content_item_id"], item.id)

                client = TestClient(app)
                listed = client.get(f"/api/content/{item.id}/analyses")
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()[0]["id"], record.id)
        finally:
            settings.data_dir = old_data_dir


class QAApiTests(unittest.TestCase):
    def test_regenerate_summary_stream_replaces_main_summary_and_emits_logs(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                settings.deepseek_api_key = "test-key"
                save_obsidian_settings(
                    settings.obsidian_vault,
                    export_path=settings.obsidian_vault,
                    auto_write=True,
                )
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/regenerate-stream",
                        canonical_source_id="regenerate-stream",
                        title="流式重新生成测试",
                    )
                    connection.commit()

                markdown = generate_article_markdown(
                    "## 旧总结\n\n旧的主总结。",
                    {
                        "title": item.title,
                        "platform": "wechat",
                        "body_text": "公众号完整正文。",
                    },
                    item.source_url,
                )
                state = save_markdown_draft_and_sync(
                    markdown=markdown,
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / f"{item.title}.md",
                    content_item_id=item.id,
                )
                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url,
                    text="公众号完整正文。",
                    source_kind="article",
                )

                with (
                    patch("routers.qa.load_content_source_text", return_value=source),
                    patch(
                        "routers.qa.stream_regenerated_content_summary",
                        return_value=iter(["模型生成的文件名标题\n\n", "## 新总结\n\n新的主总结。"]),
                    ),
                ):
                    response = TestClient(app).post(
                        "/api/qa/stream",
                        json={
                            "question": "重新生成 AI 总结",
                            "content_item_id": item.id,
                            "regenerate_summary": True,
                            "append_to_obsidian": False,
                        },
                    )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-cache, no-transform")
                self.assertEqual(response.headers["x-accel-buffering"], "no")
                self.assertIn("event: log", response.text)
                self.assertIn("event: done", response.text)
                self.assertIn('"markdown_state"', response.text)
                updated = Path(state.obsidian_path).read_text(encoding="utf-8")
                self.assertNotIn("旧的主总结", updated)
                self.assertNotIn("模型生成的文件名标题", updated)
                self.assertIn("新的主总结", updated)
                self.assertIn("公众号完整正文", updated)
                history = TestClient(app).get(f"/api/content/{item.id}/qa-history").json()["items"]
                self.assertEqual(history, [])
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key

    def test_regenerate_summary_rejects_non_wechat_article(self):
        old_data_dir = settings.data_dir
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                settings.deepseek_api_key = "test-key"
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="douyin",
                        content_type="article",
                        source_url="https://v.douyin.com/regenerate-summary/",
                        canonical_source_id="regenerate-summary-video",
                        title="不允许重新生成文章总结的非公众号文章",
                    )
                    connection.commit()

                response = TestClient(app).post(
                    "/api/qa/stream",
                    json={
                        "question": "重新生成 AI 总结",
                        "content_item_id": item.id,
                        "regenerate_summary": True,
                    },
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("尚未识别到可用于生成摘要的原文", response.json()["detail"])
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_api_key = old_key

    def test_regenerate_summary_accepts_campus_article_and_retires_legacy_prompts(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect() as connection:
                    legacy_count = connection.execute(
                        "SELECT COUNT(*) FROM prompt_templates WHERE task_type = 'campus_source' AND deleted_at IS NULL"
                    ).fetchone()[0]
                    item = ContentRepository(connection).create_content_item(
                        source_provider="campus",
                        content_type="article",
                        source_url="https://example.edu.cn/notice/1",
                        canonical_source_id="campus-regenerate-summary",
                        title="校园官网文章",
                    )
                    connection.commit()

                write_cache_meta(
                    cache_dir_for_url(item.source_url or ""),
                    {
                        "source_url": item.source_url,
                        "platform": "campus",
                        "article_info": {
                            "title": item.title,
                            "platform": "campus",
                            "body_text": "这是已识别并缓存的校园官网文章正文。",
                            "body_html": "<p>这是已识别并缓存的校园官网文章正文。</p>",
                        },
                    },
                )
                self.assertEqual(legacy_count, 0)
                self.assertEqual(_require_regenerable_content(item.id), "article")
        finally:
            settings.data_dir = old_data_dir

    def test_qa_api_saves_content_history_without_obsidian(self):
        old_data_dir = settings.data_dir
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                settings.deepseek_api_key = "test-key"
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/qa-history",
                        canonical_source_id="qa-history",
                        title="问答历史测试",
                        status="to_read",
                    )
                    connection.commit()

                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url or "",
                    text="这是一篇可用于手动追问的完整正文。",
                    source_kind="article",
                )
                client = TestClient(app)
                with (
                    patch("routers.qa.load_content_source_text", return_value=source),
                    patch("routers.qa.answer_question", return_value="已基于正文给出回答。"),
                ):
                    response = client.post(
                        "/api/qa",
                        json={
                            "question": "由快捷方式展开后的提问",
                            "display_question": "正文的重点是什么？",
                            "content_item_id": item.id,
                            "append_to_obsidian": False,
                        },
                    )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["saved_to_content"])
                history = client.get(f"/api/content/{item.id}/qa-history").json()["items"]
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0]["question"], "正文的重点是什么？")
                self.assertEqual(history[0]["answer"], "已基于正文给出回答。")
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_api_key = old_key

    def test_regenerate_latest_qa_answer_replaces_history_and_markdown(self):
        old_data_dir = settings.data_dir
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.deepseek_api_key = "test-key"
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/regenerate-qa-answer",
                        canonical_source_id="regenerate-qa-answer",
                        title="重新生成追问回答测试",
                    )
                    connection.commit()

                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url or "",
                    text="用于验证重新生成的完整正文。",
                    source_kind="article",
                )
                document_path = materialize_source_document(item, source)
                client = TestClient(app)
                with (
                    patch("routers.qa.load_content_source_text", return_value=source),
                    patch("routers.qa.answer_question", return_value="旧回答。"),
                ):
                    first = client.post(
                        "/api/qa",
                        json={
                            "question": "原始问题",
                            "content_item_id": item.id,
                            "append_to_obsidian": False,
                        },
                    )
                self.assertEqual(first.status_code, 200)
                history = client.get(f"/api/content/{item.id}/qa-history").json()["items"]

                with (
                    patch("routers.qa.load_content_source_text", return_value=source),
                    patch("routers.qa.stream_answer_question", return_value=iter(["重新生成后的回答。"])),
                ):
                    regenerated = client.post(
                        "/api/qa/stream",
                        json={
                            "question": "原始问题",
                            "content_item_id": item.id,
                            "append_to_obsidian": False,
                            "regenerate_assistant_message_id": history[0]["id"],
                        },
                    )

                self.assertEqual(regenerated.status_code, 200)
                updated_history = client.get(f"/api/content/{item.id}/qa-history").json()["items"]
                self.assertEqual([(entry["question"], entry["answer"]) for entry in updated_history], [("原始问题", "重新生成后的回答。")])
                markdown = document_path.read_text(encoding="utf-8")
                self.assertIn("重新生成后的回答。", markdown)
                self.assertNotIn("旧回答。", markdown)
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_api_key = old_key

    def test_new_conversation_archives_history_and_keeps_it_in_source_markdown(self):
        old_data_dir = settings.data_dir
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.deepseek_api_key = "test-key"
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/new-conversation",
                        canonical_source_id="new-conversation",
                        title="新对话归档测试",
                        status="to_read",
                    )
                    connection.commit()

                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url or "",
                    text="用于验证归档的完整正文。",
                    source_kind="article",
                )
                document_path = materialize_source_document(item, source)
                client = TestClient(app)
                with (
                    patch("routers.qa.load_content_source_text", return_value=source),
                    patch("routers.qa.answer_question", return_value="第一轮回答。"),
                ):
                    first = client.post(
                        "/api/qa",
                        json={
                            "question": "第一轮问题",
                            "content_item_id": item.id,
                            "append_to_obsidian": False,
                        },
                    )
                self.assertEqual(first.status_code, 200)

                archived = client.post(f"/api/content/{item.id}/qa/new-conversation")
                self.assertEqual(archived.status_code, 200)
                self.assertTrue(archived.json()["archived"])
                self.assertTrue(archived.json()["markdown_archived"])
                self.assertEqual(client.get(f"/api/content/{item.id}/qa-history").json()["items"], [])
                markdown = document_path.read_text(encoding="utf-8")
                self.assertIn("### 对话 1（已归档）", markdown)
                self.assertIn("### 对话 2（当前）", markdown)
                self.assertIn("第一轮问题", markdown)

                with (
                    patch("routers.qa.load_content_source_text", return_value=source),
                    patch("routers.qa.answer_question", return_value="第二轮回答。"),
                ):
                    second = client.post(
                        "/api/qa",
                        json={
                            "question": "第二轮问题",
                            "content_item_id": item.id,
                            "append_to_obsidian": False,
                        },
                    )
                self.assertEqual(second.status_code, 200)
                current_history = client.get(f"/api/content/{item.id}/qa-history").json()["items"]
                self.assertEqual([(entry["question"], entry["answer"]) for entry in current_history], [("第二轮问题", "第二轮回答。")])
                markdown = document_path.read_text(encoding="utf-8")
                self.assertIn("第二轮问题", markdown)
                self.assertIn("#### ", markdown)
                with connect() as connection:
                    statuses = connection.execute(
                        "SELECT status FROM qa_threads WHERE content_item_id = ? ORDER BY rowid",
                        (item.id,),
                    ).fetchall()
                self.assertEqual([row["status"] for row in statuses], ["archived", "active"])
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_api_key = old_key

    def test_generating_summary_promotes_markdown_first_article_to_editable_state(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/markdown-first-summary",
                        canonical_source_id="markdown-first-summary",
                        title="Markdown 优先摘要测试",
                    )
                    connection.commit()
                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url or "",
                    text="原文与 OCR 均已写入本地 Markdown。",
                    source_kind="article",
                )
                document_path = materialize_source_document(item, source)
                with connect() as connection:
                    before = connection.execute(
                        "SELECT 1 FROM obsidian_sync WHERE content_item_id = ?",
                        (item.id,),
                    ).fetchone()
                self.assertIsNone(before)

                state = replace_content_summary_and_sync(item.id, "这是首次生成的 AI 摘要。")

                self.assertEqual(Path(state.markdown_draft_path), document_path)
                self.assertIn("这是首次生成的 AI 摘要。", document_path.read_text(encoding="utf-8"))
                self.assertIn("这是首次生成的 AI 摘要。", get_markdown_state(item.id).markdown)
        finally:
            settings.data_dir = old_data_dir

    def test_qa_api_keeps_content_record_when_obsidian_write_fails(self):
        old_data_dir = settings.data_dir
        old_key = settings.deepseek_api_key
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                settings.obsidian_vault = Path(temp_dir) / "vault"
                settings.obsidian_vault.mkdir()
                settings.deepseek_api_key = "test-key"
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url="https://mp.weixin.qq.com/s/qa-history-obsidian",
                        canonical_source_id="qa-history-obsidian",
                        title="问答保存降级测试",
                        status="to_read",
                    )
                    connection.commit()

                source = ContentSourceText(
                    content_item_id=item.id,
                    title=item.title,
                    source_url=item.source_url or "",
                    text="正文。",
                    source_kind="article",
                )
                client = TestClient(app)
                with (
                    patch("routers.qa.load_content_source_text", return_value=source),
                    patch("routers.qa.answer_question", return_value="仍然需要保留的回答。"),
                    patch("routers.qa.append_qa_to_source_document", side_effect=ValueError("笔记不存在")),
                ):
                    response = client.post(
                        "/api/qa",
                        json={
                            "question": "请说明结论",
                            "content_item_id": item.id,
                            "obsidian_path": "缺失笔记.md",
                        },
                    )

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["saved_to_content"])
                self.assertFalse(response.json()["saved_to_obsidian"])
                self.assertEqual(response.json()["obsidian_error"], "笔记不存在")
                history = client.get(f"/api/content/{item.id}/qa-history").json()["items"]
                self.assertEqual(history[0]["answer"], "仍然需要保留的回答。")
        finally:
            settings.data_dir = old_data_dir
            settings.deepseek_api_key = old_key
            settings.obsidian_vault = old_vault

    def test_qa_api_uses_content_source_without_obsidian_note(self):
        old_key = settings.deepseek_api_key
        try:
            settings.deepseek_api_key = "test-key"
            source = ContentSourceText(
                content_item_id="article-1",
                title="公众号文章",
                source_url="https://mp.weixin.qq.com/s/example",
                text="这是文章的完整正文。",
                source_kind="article",
            )
            client = TestClient(app)
            with (
                patch("routers.qa.load_content_source_text", return_value=source),
                patch("routers.qa.answer_question", return_value="基于正文的回答") as answer_mock,
            ):
                response = client.post(
                    "/api/qa",
                    json={
                        "question": "请概括重点",
                        "content_item_id": source.content_item_id,
                        "transcript": "客户端的 Markdown 摘要，不应替代正文",
                        "append_to_obsidian": False,
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["answer"], "基于正文的回答")
            self.assertFalse(response.json()["saved_to_obsidian"])
            self.assertEqual(answer_mock.call_args.kwargs["transcript"], source.text)
            self.assertEqual(answer_mock.call_args.kwargs["video_title"], source.title)
        finally:
            settings.deepseek_api_key = old_key

    def test_qa_api_appends_answer_to_note(self):
        old_vault = settings.obsidian_vault
        old_key = settings.deepseek_api_key
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.obsidian_vault = Path(temp_dir)
                settings.deepseek_api_key = "test-key"
                note_path = settings.obsidian_vault / "追问测试.md"
                note_path.write_text("# 追问测试\n\n## 总结\n已有内容\n", encoding="utf-8")

                client = TestClient(app)
                with patch("routers.qa.answer_question", return_value="这是追问答案。"):
                    response = client.post(
                        "/api/qa",
                        json={
                            "question": "讲了什么？",
                            "summary": "## 总结\n已有内容",
                            "transcript": "原始转写",
                            "video_title": "追问测试",
                            "obsidian_path": str(note_path),
                        },
                    )

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertTrue(data["success"])
                self.assertTrue(data["saved_to_obsidian"])
                self.assertEqual(data["answer"], "这是追问答案。")
                self.assertIn("讲了什么？", note_path.read_text(encoding="utf-8"))
                self.assertIn("这是追问答案。", note_path.read_text(encoding="utf-8"))
        finally:
            settings.obsidian_vault = old_vault
            settings.deepseek_api_key = old_key


class ContentSourceTextTests(unittest.TestCase):
    def test_wechat_source_is_fetched_and_cached_without_ai(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                source_url = "https://mp.weixin.qq.com/s/example"
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url=source_url,
                        canonical_source_id="wechat-example",
                        title="订阅时标题",
                        status="to_read",
                    )
                    connection.commit()

                fetched = ArticleFetchResult(
                    url=source_url,
                    platform="wechat",
                    title="抓取后的文章标题",
                    body_text="文章正文内容",
                    body_html="<div>文章正文内容</div>",
                    author="作者",
                )
                with patch("services.content_source_text.fetch_article", return_value=fetched) as fetch_mock:
                    source = load_content_source_text(item.id)

                self.assertEqual(source.text, fetched.body_text)
                self.assertEqual(source.title, fetched.title)
                self.assertTrue(source.fetched_now)
                fetch_mock.assert_called_once_with(
                    source_url,
                    "wechat",
                    content_item_id=item.id,
                    include_image_ocr=True,
                )
                self.assertEqual(search_documents("文章正文内容")[0].content_key, item.id)
                cache_meta = read_cache_meta(cache_dir_for_url(source_url))
                self.assertEqual(cache_meta["article_info"]["body_html"], fetched.body_html)
                self.assertIn("文章正文内容", cache_meta["article_info"]["normalized_html"])
                self.assertEqual(
                    cache_meta["article_info"]["normalized_html_version"],
                    ARTICLE_NORMALIZER_VERSION,
                )
                with connect() as connection:
                    updated_item = ContentRepository(connection).get_content_item(item.id)
                self.assertEqual(updated_item.title, fetched.title)
                readiness = inspect_content_text_readiness(item)
                self.assertEqual(readiness.status, "ready")
                self.assertTrue(readiness.can_ask_ai)
        finally:
            settings.data_dir = old_data_dir

    def test_campus_detail_replaces_truncated_list_title_without_losing_folder(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                source_url = "https://sgim.sztu.edu.cn/info/1023/example.htm"
                with connect() as connection:
                    folder = connection.execute(
                        "SELECT id FROM library_folders ORDER BY created_at LIMIT 1"
                    ).fetchone()
                    item = ContentRepository(connection).create_content_item(
                        source_provider="campus",
                        content_type="article",
                        source_url=source_url,
                        canonical_source_id="campus-title-example",
                        title="访企拓岗促就业……",
                        status="to_read",
                        library_folder_id=str(folder["id"]) if folder else None,
                        source_name="商学院",
                        source_section="学院新闻",
                    )
                    connection.commit()

                fetched = ArticleFetchResult(
                    url=source_url,
                    platform="campus",
                    title="访企拓岗促就业 产教融合共育人——学院开展校企交流活动",
                    body_text="这是详情页中完整的文章正文。",
                    body_html="<div>这是详情页中完整的文章正文。</div>",
                    published_at="2026-07-16",
                )
                with patch("services.content_source_text.fetch_article", return_value=fetched):
                    source = load_content_source_text(item.id)

                with connect() as connection:
                    updated_item = ContentRepository(connection).get_content_item(item.id)
                self.assertEqual(updated_item.title, fetched.title)
                self.assertEqual(updated_item.published_at, fetched.published_at)
                self.assertEqual(updated_item.library_folder_id, item.library_folder_id)
                self.assertEqual(updated_item.source_name, item.source_name)
                self.assertEqual(updated_item.source_section, item.source_section)
                self.assertEqual(source.title, fetched.title)
        finally:
            settings.data_dir = old_data_dir

    def test_video_source_reuses_cached_subtitles_only(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                source_url = "https://www.bilibili.com/video/BV-example"
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        content_type="video",
                        source_url=source_url,
                        canonical_source_id="BV-example",
                        title="视频标题",
                        status="to_read",
                    )
                    connection.commit()

                write_cached_subtitle_transcript(cache_dir_for_url(source_url), "第一句字幕\n第二句字幕")
                source = load_content_source_text(item.id)

                self.assertEqual(source.text, "第一句字幕\n第二句字幕")
                self.assertEqual(source.source_kind, "video")
                self.assertFalse(source.fetched_now)
                self.assertEqual(inspect_content_text_readiness(item).label, "字幕已就绪")
        finally:
            settings.data_dir = old_data_dir

    def test_generated_report_uses_its_markdown_as_qa_source(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat_report",
                        content_type="report",
                        canonical_source_id="report:qa-source",
                        title="2026-07-18 日报",
                        status="to_read",
                    )
                    connection.commit()

                save_markdown_draft_and_sync(
                    markdown=(
                        "# 2026-07-18 日报\n\n"
                        "## 今日动态\n\n学校发布了新的活动安排。\n\n"
                        "## 追问记录\n\n### 对话 1（当前）\n\n"
                        "#### 2026-07-18 20:00\n\n**问：** 旧问题\n\n**答：** 旧回答"
                    ),
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / "日报" / f"{item.title}.md",
                    content_item_id=item.id,
                )

                before = get_markdown_state(item.id).markdown
                source = load_content_source_text(item.id)
                readiness = inspect_content_text_readiness(item)
                after = get_markdown_state(item.id).markdown

                self.assertEqual(source.source_kind, "report")
                self.assertIn("学校发布了新的活动安排", source.text)
                self.assertNotIn("旧回答", source.text)
                self.assertTrue(readiness.can_ask_ai)
                self.assertEqual(readiness.label, "报告已就绪")
                self.assertEqual(after, before)
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_failed_wechat_capture_is_visible_and_can_be_retried(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                source_url = "https://mp.weixin.qq.com/s/unavailable"
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url=source_url,
                        canonical_source_id="wechat-unavailable",
                        title="暂不可用的文章",
                        status="to_read",
                    )
                    connection.commit()

                with patch("services.content_source_text.fetch_article", side_effect=ValueError("微信要求客户端打开")):
                    with self.assertRaisesRegex(ValueError, "客户端打开"):
                        load_content_source_text(item.id)

                failed_readiness = inspect_content_text_readiness(item)
                self.assertEqual(failed_readiness.status, "unavailable")
                self.assertTrue(failed_readiness.retryable)
                self.assertIn("客户端打开", failed_readiness.detail)

                fetched = ArticleFetchResult(
                    url=source_url,
                    platform="wechat",
                    title="恢复后的文章",
                    body_text="恢复后的正文",
                    body_html="<div>恢复后的正文</div>",
                )
                with patch("services.content_source_text.fetch_article", return_value=fetched):
                    response = TestClient(app).post(f"/api/content/{item.id}/source-text/refresh")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ready")
                readiness_response = TestClient(app).get(f"/api/content/{item.id}/text-readiness")
                self.assertEqual(readiness_response.status_code, 200)
                self.assertEqual(readiness_response.json()["label"], "正文已就绪")
        finally:
            settings.data_dir = old_data_dir

    def test_wechat_pipeline_error_is_exposed_as_source_text_failure(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                source_url = "https://mp.weixin.qq.com/s/pipeline-failure"
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="wechat",
                        content_type="article",
                        source_url=source_url,
                        canonical_source_id="wechat-pipeline-failure",
                        title="自动处理失败的文章",
                        status="failed",
                    )
                    connection.commit()
                write_cache_meta(
                    cache_dir_for_url(source_url),
                    {"pipeline_status": "failed", "pipeline_error": "微信公众号页面拒绝访问"},
                )

                readiness = inspect_content_text_readiness(item)

                self.assertEqual(readiness.status, "unavailable")
                self.assertTrue(readiness.retryable)
                self.assertEqual(readiness.detail, "微信公众号页面拒绝访问")
        finally:
            settings.data_dir = old_data_dir


class PipelineApiTests(unittest.TestCase):
    def test_pipeline_invalid_text_returns_structured_failure(self):
        client = TestClient(app)

        response = client.post("/api/pipeline/run", json={"share_text": "没有链接"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["step"], "parse")
        self.assertEqual(data["logs"][0]["step"], "parse")
        self.assertIn("parse", data["timings"])
        self.assertIn("total", data["timings"])
        self.assertIn("parse", data["progress"])
        self.assertGreater(data["overall_progress"], 0)

    def test_local_video_outside_data_dir_is_rejected(self):
        result = run_pipeline_sync(local_video_path="/tmp/not-owned.mp4", whisper_model="base")

        self.assertFalse(result.success)
        self.assertEqual(result.step, "parse")
        self.assertIn("应用管理", result.error)

    def test_external_library_attachment_is_accepted_for_local_transcription(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "private-data"
                attachment_root = root / "Obsidian" / "attachments"
                audio_path = attachment_root / "audio-item" / "original--访谈.mp3"
                audio_path.parent.mkdir(parents=True)
                audio_path.write_bytes(b"retained-audio")
                transcribe_result = SimpleNamespace(
                    success=True,
                    transcript="外部资料库音频文本",
                    segments=[],
                    error="",
                    timings={"whisper_model_load": 0.1, "whisper_decode": 0.2},
                )
                with (
                    patch("services.pipeline_runner.attachments_root", return_value=attachment_root),
                    patch("services.pipeline_runner.media_duration_seconds", return_value=8),
                    patch("services.pipeline_runner.extract_audio_with_details") as extract_audio,
                    patch("services.pipeline_runner.transcribe_with_details", return_value=transcribe_result),
                    patch("services.pipeline_runner.load_content_source_text"),
                ):
                    result = run_pipeline_sync(
                        local_video_path=str(audio_path),
                        source_url="local-file:external-audio-item",
                        whisper_model="base",
                        use_cache=False,
                        processing_mode="transcript",
                    )

                self.assertTrue(result.success)
                self.assertEqual(result.transcript, "外部资料库音频文本")
                extract_audio.assert_not_called()
        finally:
            settings.data_dir = old_data_dir

    def test_local_video_retranscription_persists_transcript_in_source_cache(self):
        old_data_dir = settings.data_dir
        source_url = "https://v.douyin.com/retranscribe-test/"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                cache_dir = cache_dir_for_url(source_url)
                video_path = cache_dir / "retained.mp4"
                video_path.parent.mkdir(parents=True)
                video_path.write_bytes(b"video")
                extract_result = SimpleNamespace(success=True, error="", elapsed_seconds=0.1)
                transcribe_result = SimpleNamespace(
                    success=True,
                    transcript="重新转写得到的文本",
                    segments=[],
                    error="",
                    timings={"whisper_model_load": 0.1, "whisper_decode": 0.2},
                )

                with (
                    patch("services.pipeline_runner.media_duration_seconds", return_value=12),
                    patch("services.pipeline_runner.extract_audio_with_details", return_value=extract_result),
                    patch("services.pipeline_runner.transcribe_with_details", return_value=transcribe_result),
                    patch("services.pipeline_runner.load_content_source_text"),
                ):
                    result = run_pipeline_sync(
                        local_video_path=str(video_path),
                        source_url=source_url,
                        whisper_model="base",
                        use_cache=False,
                        processing_mode="transcript",
                    )

                self.assertTrue(result.success)
                self.assertEqual(result.transcript, "重新转写得到的文本")
                self.assertEqual(read_cached_transcript(cache_dir, "base"), "重新转写得到的文本")
        finally:
            settings.data_dir = old_data_dir

    def test_local_audio_transcription_uses_retained_audio_without_ffmpeg_rewrite(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir) / "data"
                audio_path = settings.data_dir / "attachments" / "audio-item" / "original--访谈.wav"
                audio_path.parent.mkdir(parents=True)
                audio_path.write_bytes(b"retained-audio")
                transcribe_result = SimpleNamespace(
                    success=True,
                    transcript="音频转写文本",
                    segments=[],
                    error="",
                    timings={"whisper_model_load": 0.1, "whisper_decode": 0.2},
                )
                with (
                    patch("services.pipeline_runner.media_duration_seconds", return_value=8),
                    patch("services.pipeline_runner.extract_audio_with_details") as extract_audio,
                    patch("services.pipeline_runner.transcribe_with_details", return_value=transcribe_result),
                    patch("services.pipeline_runner.load_content_source_text"),
                ):
                    result = run_pipeline_sync(
                        local_video_path=str(audio_path),
                        source_url="local-file:audio-item",
                        whisper_model="base",
                        use_cache=False,
                        processing_mode="transcript",
                    )
                self.assertTrue(result.success)
                extract_audio.assert_not_called()
                self.assertTrue(audio_path.exists())
        finally:
            settings.data_dir = old_data_dir


class TaskApiTests(unittest.TestCase):
    def test_task_manager_marks_unexpected_worker_error_as_failed(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                manager = TaskManager()
                try:
                    with patch(
                        "services.task_manager.run_pipeline_sync",
                        side_effect=RuntimeError("模拟工作线程异常"),
                    ):
                        created = manager.create(
                            PipelineRequest(share_text="https://www.bilibili.com/video/BV1xx411c7mD")
                        )
                        created.future.result(timeout=2)

                    current = manager.get(created.task_id)
                    self.assertEqual(current.status, "failed")
                    self.assertEqual(current.result.step, "executor")
                    self.assertIn("模拟工作线程异常", current.result.error)
                    with connect(settings.data_dir / "app.db") as connection:
                        row = connection.execute(
                            "SELECT status, error_message FROM tasks WHERE id = ?",
                            (created.task_id,),
                        ).fetchone()
                    self.assertEqual(row["status"], "failed")
                    self.assertIn("模拟工作线程异常", row["error_message"])
                finally:
                    manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_exposes_article_content_id_on_progress_update(self):
        """The UI can open a WeChat article snapshot before summarization completes."""
        manager = TaskManager()
        record = manager._record_from_request(
            "wechat-preview-task",
            PipelineRequest(share_text="https://mp.weixin.qq.com/s/example"),
        )
        with manager._lock:
            manager._tasks[record.task_id] = record

        progress_content_ids = []

        def pipeline_with_article_snapshot(*_args, on_update, **_kwargs):
            on_update(
                PipelineResponse(
                    success=False,
                    task_id="wechat-preview-task",
                    content_item_id="wechat-preview-item",
                    platform="wechat",
                    transcript="已抓取的公众号正文",
                    step="summarize",
                )
            )
            progress_content_ids.append(manager.get("wechat-preview-task").content_item_id)
            return PipelineResponse(
                success=True,
                task_id="wechat-preview-task",
                content_item_id="wechat-preview-item",
                platform="wechat",
                transcript="已抓取的公众号正文",
                step="save",
            )

        try:
            with patch("services.task_manager.run_pipeline_sync", side_effect=pipeline_with_article_snapshot), patch.object(
                TaskManager, "_persist_state", return_value=None
            ), patch.object(TaskManager, "_persist_content_status", return_value=None), patch.object(
                TaskManager, "_schedule_next", return_value=None
            ):
                manager._run("wechat-preview-task")

            self.assertEqual(progress_content_ids, ["wechat-preview-item"])
        finally:
            manager._executor.shutdown(wait=True, cancel_futures=True)

    def test_task_manager_recovers_queued_tasks_from_database(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                request_json = json.dumps(
                    {
                        "share_text": "https://www.bilibili.com/video/BV1xx411c7mD",
                        "whisper_model": "base",
                        "use_cache": True,
                    },
                    ensure_ascii=False,
                )
                with connect(settings.data_dir / "app.db") as connection:
                    task = TaskRepository(connection).create_task(
                        task_type="process_video",
                        task_id="recover1",
                        request_json=request_json,
                    )
                    connection.commit()

                manager = TaskManager()
                def hold_task(_task_id):
                    time.sleep(0.2)

                with patch.object(TaskManager, "_run", side_effect=hold_task) as run_mock:
                    manager.recover_from_database()
                    time.sleep(0.05)

                    recovered = manager.get(task.id)
                    self.assertIsNotNone(recovered)
                    self.assertEqual(recovered.status, "queued")
                    run_mock.assert_called_once_with(task.id)
                    manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_pauses_and_resumes_queued_tasks(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                manager = TaskManager()
                request = SimpleNamespace(
                    content_item_id=None,
                    share_text="https://www.bilibili.com/video/BV1xx411c7mD",
                    local_video_path=None,
                    local_subtitle_path=None,
                    source_title=None,
                    source_url=None,
                    whisper_model="base",
                    use_cache=True,
                )
                record = manager._record_from_request("pause1", request)
                with manager._lock:
                    manager._tasks[record.task_id] = record
                manager._persist_create(record)

                paused = manager.pause("pause1")

                self.assertEqual(paused.status, "paused")
                self.assertEqual(paused.result.step, "paused")
                with connect(settings.data_dir / "app.db") as connection:
                    row = connection.execute("SELECT status FROM tasks WHERE id = 'pause1'").fetchone()
                    self.assertEqual(row["status"], "paused")

                def hold_task(_task_id):
                    time.sleep(0.2)

                with patch.object(TaskManager, "_run", side_effect=hold_task) as run_mock:
                    resumed = manager.resume("pause1")
                    time.sleep(0.05)

                    self.assertEqual(resumed.status, "queued")
                    run_mock.assert_called_once_with("pause1")
                    manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_schedules_high_priority_task_first(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                manager = TaskManager()

                def request(priority):
                    return SimpleNamespace(
                        content_item_id=None,
                        share_text="https://www.bilibili.com/video/BV1xx411c7mD",
                        local_video_path=None,
                        local_subtitle_path=None,
                        source_title=None,
                        source_url=None,
                        whisper_model="base",
                        use_cache=True,
                        priority=priority,
                    )

                low = manager._record_from_request("priority-low", request(100))
                high = manager._record_from_request("priority-high", request(5))
                with manager._lock:
                    manager._tasks[low.task_id] = low
                    manager._tasks[high.task_id] = high

                with patch.object(TaskManager, "_run", return_value=None) as run_mock:
                    manager._schedule_next()

                run_mock.assert_called_once_with("priority-high")
                manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_bounds_desktop_pipeline_coordinators(self):
        old_data_dir = settings.data_dir
        old_pipeline_concurrency = settings.pipeline_concurrency
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                settings.pipeline_concurrency = 2
                initialize_database()
                manager = TaskManager()

                def request(task_index):
                    return SimpleNamespace(
                        content_item_id=None,
                        share_text=f"https://www.bilibili.com/video/BV1xx411c7mD?p={task_index}",
                        local_video_path=None,
                        local_subtitle_path=None,
                        source_title=None,
                        source_url=None,
                        whisper_model="base",
                        use_cache=True,
                        priority=100,
                    )

                first = manager._record_from_request("parallel-1", request(1))
                second = manager._record_from_request("parallel-2", request(2))
                third = manager._record_from_request("parallel-3", request(3))
                with manager._lock:
                    manager._tasks[first.task_id] = first
                    manager._tasks[second.task_id] = second
                    manager._tasks[third.task_id] = third

                def hold_task(_task_id):
                    time.sleep(0.2)

                with patch.object(TaskManager, "_run", side_effect=hold_task) as run_mock:
                    manager._schedule_next()
                    time.sleep(0.05)

                running_ids = {call.args[0] for call in run_mock.call_args_list}
                self.assertEqual(running_ids, {"parallel-1", "parallel-2"})
                self.assertNotIn("parallel-3", running_ids)
                manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.pipeline_concurrency = old_pipeline_concurrency
            settings.data_dir = old_data_dir

    def test_task_manager_reprioritize_updates_database(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                request_json = json.dumps(
                    {
                        "share_text": "https://www.bilibili.com/video/BV1xx411c7mD",
                        "whisper_model": "base",
                        "use_cache": True,
                    },
                    ensure_ascii=False,
                )
                with connect(settings.data_dir / "app.db") as connection:
                    repo = TaskRepository(connection)
                    repo.create_task(
                        task_type="process_video",
                        task_id="priority-db",
                        priority=100,
                        request_json=request_json,
                    )
                    repo.update_task_state("priority-db", status="paused", current_stage="paused", progress=0)
                    connection.commit()

                manager = TaskManager()
                manager.recover_from_database()
                updated = manager.reprioritize("priority-db", 10)

                self.assertEqual(updated.priority, 10)
                with connect(settings.data_dir / "app.db") as connection:
                    row = connection.execute("SELECT priority FROM tasks WHERE id = 'priority-db'").fetchone()
                    self.assertEqual(row["priority"], 10)
                manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_does_not_auto_submit_paused_tasks_on_recovery(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                request_json = json.dumps(
                    {
                        "share_text": "https://www.bilibili.com/video/BV1xx411c7mD",
                        "whisper_model": "base",
                        "use_cache": True,
                    },
                    ensure_ascii=False,
                )
                with connect(settings.data_dir / "app.db") as connection:
                    repo = TaskRepository(connection)
                    repo.create_task(
                        task_type="process_video",
                        task_id="pause2",
                        request_json=request_json,
                    )
                    repo.update_task_state("pause2", status="paused", current_stage="paused", progress=0)
                    connection.commit()

                manager = TaskManager()
                with patch.object(TaskManager, "_run", return_value=None) as run_mock:
                    manager.recover_from_database()

                recovered = manager.get("pause2")
                self.assertEqual(recovered.status, "paused")
                run_mock.assert_not_called()
                manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_marks_running_tasks_interrupted_after_restart_and_can_retry(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect(settings.data_dir / "app.db") as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        source_url="https://www.bilibili.com/video/BV1xx411c7mD",
                        canonical_source_id="BV1xx411c7mD",
                        title="重启时正在处理的视频",
                        status="processing",
                    )
                    connection.commit()
                request_json = json.dumps(
                    {
                        "content_item_id": item.id,
                        "share_text": "https://www.bilibili.com/video/BV1xx411c7mD",
                        "whisper_model": "base",
                        "use_cache": True,
                    },
                    ensure_ascii=False,
                )
                with connect(settings.data_dir / "app.db") as connection:
                    repo = TaskRepository(connection)
                    repo.create_task(
                        task_type="process_video",
                        task_id="recover2",
                        content_item_id=item.id,
                        request_json=request_json,
                    )
                    repo.update_task_state("recover2", status="running", current_stage="transcribe", progress=42)
                    connection.commit()

                manager = TaskManager()
                manager.recover_from_database()
                interrupted = manager.get("recover2")

                self.assertEqual(interrupted.status, "failed")
                self.assertIn("后端重启", interrupted.result.error)
                with connect(settings.data_dir / "app.db") as connection:
                    self.assertEqual(ContentRepository(connection).get_content_item(item.id).status, "failed")

                def hold_task(_task_id):
                    time.sleep(0.2)

                with patch.object(TaskManager, "_run", side_effect=hold_task) as run_mock:
                    retried = manager.retry("recover2")
                    time.sleep(0.05)

                    self.assertEqual(retried.status, "queued")
                    self.assertIsNone(retried.result.error)
                    run_mock.assert_called_once_with("recover2")
                    manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_requeues_interrupted_background_video_after_restart(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect(settings.data_dir / "app.db") as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        source_url="https://www.bilibili.com/video/BV1background-recovery",
                        canonical_source_id="BV1background-recovery",
                        title="后台收藏任务",
                        status="processing",
                    )
                    TaskRepository(connection).create_task(
                        task_type="process_video",
                        task_id="recover-background",
                        content_item_id=item.id,
                        request_json=json.dumps(
                            {
                                "content_item_id": item.id,
                                "share_text": item.source_url,
                                "source_url": item.source_url,
                                "execution_mode": "background",
                                "processing_mode": "full",
                            },
                            ensure_ascii=False,
                        ),
                    )
                    TaskRepository(connection).update_task_state(
                        "recover-background",
                        status="running",
                        current_stage="download",
                        progress=30,
                    )
                    connection.commit()

                manager = TaskManager()
                with patch.object(TaskManager, "_schedule_next"):
                    manager.recover_from_database()

                recovered = manager.get("recover-background")
                self.assertEqual(recovered.status, "queued")
                self.assertEqual(recovered.result.step, "queued")
                with connect(settings.data_dir / "app.db") as connection:
                    row = TaskRepository(connection).get_task("recover-background")
                    self.assertEqual(row.status, "queued")
                    self.assertEqual(ContentRepository(connection).get_content_item(item.id).status, "processing")
                manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_retry_marks_content_as_processing(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                with connect(settings.data_dir / "app.db") as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="bilibili",
                        source_url="https://www.bilibili.com/video/BV1retry-status",
                        canonical_source_id="BV1retry-status",
                        title="待重试内容",
                        status="failed",
                    )
                    request_json = json.dumps(
                        {
                            "content_item_id": item.id,
                            "share_text": item.source_url,
                            "whisper_model": "base",
                            "use_cache": True,
                        },
                        ensure_ascii=False,
                    )
                    repo = TaskRepository(connection)
                    repo.create_task(
                        task_type="process_video",
                        task_id="retry-content-status",
                        content_item_id=item.id,
                        request_json=request_json,
                    )
                    repo.update_task_state("retry-content-status", status="failed", current_stage="download", progress=20)
                    connection.commit()

                manager = TaskManager()
                manager.recover_from_database()
                with patch.object(TaskManager, "_run", side_effect=lambda _task_id: time.sleep(0.2)):
                    manager.retry("retry-content-status")
                    with connect(settings.data_dir / "app.db") as connection:
                        refreshed = ContentRepository(connection).get_content_item(item.id)
                        self.assertEqual(refreshed.status, "processing")
                manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_manager_retry_link_task_enables_cache_reuse(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                initialize_database()
                request = SimpleNamespace(
                    content_item_id=None,
                    share_text="https://www.bilibili.com/video/BV1xx411c7mD",
                    local_video_path=None,
                    local_subtitle_path=None,
                    source_title=None,
                    source_url=None,
                    whisper_model="base",
                    use_cache=False,
                    priority=100,
                )
                manager = TaskManager()
                record = manager._record_from_request("retry-cache", request, status="failed")
                with manager._lock:
                    manager._tasks[record.task_id] = record
                manager._persist_create(record)
                manager._persist_state(record)

                with patch.object(TaskManager, "_schedule_next", return_value=None):
                    retried = manager.retry("retry-cache")

                self.assertTrue(retried.use_cache)
                with connect(settings.data_dir / "app.db") as connection:
                    row = connection.execute("SELECT request_json FROM tasks WHERE id = 'retry-cache'").fetchone()
                    request_data = json.loads(row["request_json"])
                    self.assertTrue(request_data["use_cache"])
                manager._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            settings.data_dir = old_data_dir

    def test_task_invalid_text_can_be_polled_to_failure(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                client = TestClient(app)

                create_response = client.post(
                    "/api/tasks",
                    json={
                        "share_text": "没有链接",
                        "whisper_model": "base",
                        "use_cache": True,
                    },
                )

                self.assertEqual(create_response.status_code, 200)
                created = create_response.json()
                task_id = created["task_id"]
                self.assertEqual(created["whisper_model"], "base")
                self.assertEqual(created["source_url"], "没有链接")

                task_data = None
                for _ in range(20):
                    poll_response = client.get(f"/api/tasks/{task_id}")
                    self.assertEqual(poll_response.status_code, 200)
                    task_data = poll_response.json()
                    if task_data["status"] in {"failed", "cancelled", "succeeded"}:
                        break
                    time.sleep(0.05)

                self.assertIsNotNone(task_data)
                self.assertEqual(task_data["status"], "failed")
                self.assertEqual(task_data["step"], "parse")
                self.assertEqual(task_data["error_info"]["category"], "input")
                self.assertFalse(task_data["error_info"]["retryable"])
                self.assertEqual(task_data["whisper_model"], "base")
                self.assertEqual(task_data["logs"][0]["step"], "parse")

                with connect(settings.data_dir / "app.db") as connection:
                    row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row["status"], "failed")
                    self.assertEqual(row["current_stage"], "parse")
                    self.assertIn("没有链接", row["request_json"])
                    result_data = json.loads(row["result_json"])
                    self.assertEqual(result_data["step"], "parse")
        finally:
            settings.data_dir = old_data_dir

    def test_task_unknown_id_returns_404(self):
        client = TestClient(app)

        response = client.get("/api/tasks/not-found")

        self.assertEqual(response.status_code, 404)


class UploadApiTests(unittest.TestCase):
    def test_upload_rejects_non_video_file(self):
        client = TestClient(app)

        response = client.post(
            "/api/upload-tasks",
            files=[("files", ("note.txt", b"hello", "text/plain"))],
            data={"whisper_model": "base"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("不支持的视频格式", response.json()["detail"])

    def test_upload_subtitle_creates_task(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                client = TestClient(app)

                with patch("services.task_manager.TaskManager._schedule_next", return_value=None):
                    response = client.post(
                        "/api/upload-subtitle-tasks",
                        files=[("files", ("lesson.vtt", b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello", "text/vtt"))],
                        data={"whisper_model": "base"},
                    )

                self.assertEqual(response.status_code, 200)
                tasks = response.json()["tasks"]
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["source_title"], "lesson")
                self.assertTrue(tasks[0]["local_subtitle_path"].endswith(".vtt"))
        finally:
            settings.data_dir = old_data_dir

    def test_upload_rejects_oversized_file_without_leaving_a_partial_copy(self):
        old_data_dir = settings.data_dir
        old_file_limit = settings.upload_max_file_bytes
        old_batch_limit = settings.upload_max_batch_bytes
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                settings.upload_max_file_bytes = 4
                settings.upload_max_batch_bytes = 16
                response = TestClient(app).post(
                    "/api/upload-tasks",
                    files=[("files", ("too-large.mp4", b"12345", "video/mp4"))],
                )
                self.assertEqual(response.status_code, 413)
                self.assertFalse((Path(temp_dir) / "uploads").exists())
        finally:
            settings.data_dir = old_data_dir
            settings.upload_max_file_bytes = old_file_limit
            settings.upload_max_batch_bytes = old_batch_limit

    def test_invalid_file_in_batch_removes_earlier_uploaded_files(self):
        old_data_dir = settings.data_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.data_dir = Path(temp_dir)
                response = TestClient(app).post(
                    "/api/upload-subtitle-tasks",
                    files=[
                        ("files", ("valid.vtt", b"WEBVTT", "text/vtt")),
                        ("files", ("invalid.txt", b"not a subtitle", "text/plain")),
                    ],
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse((Path(temp_dir) / "uploads").exists())
        finally:
            settings.data_dir = old_data_dir


if __name__ == "__main__":
    unittest.main()
