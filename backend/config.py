import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def ensure_private_data_directory(path: Path) -> Path:
    """Create an application-data directory that other local users cannot read."""
    resolved = path.expanduser().resolve()
    filesystem_root = Path(resolved.anchor)
    if resolved in {filesystem_root, Path.home().resolve(), PROJECT_ROOT.resolve()}:
        raise ValueError("DATA_DIR 必须指向专用子目录，不能使用系统根目录、用户主目录或项目根目录")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and not path.is_symlink():
        path.chmod(0o700)
    return path


def ensure_private_data_file(path: Path, *, create: bool = False) -> Path:
    """Keep databases and credentials private inside the application-data root."""
    if create and not path.exists():
        path.touch(mode=0o600)
    if os.name == "posix" and path.exists() and not path.is_symlink():
        path.chmod(0o600)
    return path


# DeepSeek publishes separate prices for cache hits, cache misses and output.
# Keep the defaults here rather than in the UI so server-side call records are
# priced with the same rate card even when the desktop client is not open.
DEFAULT_DEEPSEEK_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {
        "input_cache_hit": 0.02,
        "input_cache_miss": 1.0,
        "output": 2.0,
    },
    "deepseek-v4-pro": {
        "input_cache_hit": 0.025,
        "input_cache_miss": 3.0,
        "output": 6.0,
    },
}


def default_deepseek_pricing() -> dict[str, dict[str, float]]:
    return {model: dict(prices) for model, prices in DEFAULT_DEEPSEEK_PRICING.items()}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            Path(os.environ["KNOWLEDGEHUB_ENV_FILE"]).expanduser()
            if os.environ.get("KNOWLEDGEHUB_ENV_FILE")
            else Path(__file__).with_name(".env")
        )
    )
    # Desktop builds override DATA_DIR. These defaults also keep a source checkout
    # usable on another Mac without carrying the original developer's home path.
    obsidian_vault: Path = PROJECT_ROOT / "data" / "obsidian"
    data_dir: Path = PROJECT_ROOT / "data"
    # Resource limits are enforced while multipart data is copied to disk. They
    # stay out of the normal UI because they protect the local service rather
    # than describe a user-facing media preference.
    upload_max_file_bytes: int = 4 * 1024 * 1024 * 1024
    upload_max_batch_bytes: int = 8 * 1024 * 1024 * 1024
    upload_max_files: int = 20
    # Source directory consumed by the static public-report build. It is kept
    # outside SQLite so the deployment package contains only explicit public
    # artifacts, never the local application database or caches.
    public_report_source_dir: Path = PROJECT_ROOT / "frontend" / "public-report" / "public"
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "knowledgehub://app",
    ]
    allowed_origin_regex: str = r"http://(localhost|127\.0\.0\.1):\d+"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash:enabled"
    llm_request_timeout_seconds: float = 90.0
    paddle_ocr_access_token: str = ""
    paddle_ocr_base_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddle_ocr_model: str = "PaddleOCR-VL-1.6"
    deepseek_pricing: dict[str, dict[str, float]] = Field(default_factory=default_deepseek_pricing)
    # V4 has not enabled the announced peak/off-peak pricing yet. Keep the
    # estimate aligned with the published base price until the user explicitly
    # enables a different multiplier in settings.
    deepseek_peak_pricing_multiplier: float = 1.0
    # Retained as an environment-only fallback for a non-DeepSeek compatible
    # provider. DeepSeek calls use the cache-aware per-model rate card above.
    llm_input_cost_per_million_tokens: float = 0.0
    llm_output_cost_per_million_tokens: float = 0.0
    whisper_model: str = "small"
    whisper_device: str = "auto"
    asr_backend: str = "auto"
    # A single ``small`` model is the desktop default.  It avoids silently
    # keeping a second short-video model on disk merely because a task happens
    # to be short.
    asr_model_strategy: str = "manual"
    asr_short_video_model: str = "base"
    asr_long_video_model: str = "small"
    asr_beam_size: int = 1
    asr_vad_filter: bool = True
    # A cross-backend fallback otherwise encourages a second platform model to
    # be downloaded and retained.  It can still be enabled explicitly for a
    # compatibility investigation.
    asr_fallback_enabled: bool = False
    # This is intentionally environment-only for now.  It controls only
    # optional Whisper model downloads, never collector or media traffic.
    hugging_face_hub_endpoint: str = "https://hf-mirror.com"
    # Task coordinators may overlap lightweight work, while the pipeline keeps
    # actual downloads and ASR in their own single-resource lanes. These
    # values remain for compatibility with existing local settings.
    pipeline_concurrency: int = 3
    asr_concurrency: int = 1
    ffmpeg_path: str = ""
    yt_dlp_path: str = ""
    douyin_cookie_file: str = ""
    bilibili_cookie: str = ""
    bilibili_cookie_file: str = ""
    compress_downloaded_video: bool = False
    # Videos are regenerable preview artifacts. Text, Markdown and summaries
    # are durable; the local video cache is kept only for this window.
    video_cache_retention_days: int = 14
    auto_download_bilibili_video: bool = False
    storage_video_max_height: int = 240
    storage_video_crf: int = 38
    storage_video_preset: str = "veryfast"
    telegram_proxy_url: str = ""
    wechat_subscription_scheduler_enabled: bool = True
    wechat_subscription_scheduler_interval_seconds: int = 60
    wechat_subscription_default_interval_minutes: int = 1440
    # Automatic checks only inspect the newest small window. Historical
    # collection is always an explicit user action in the backfill dialog.
    wechat_subscription_default_initial_limit: int = 10
    creator_scheduler_enabled: bool = True
    creator_scheduler_interval_seconds: int = 60
    creator_default_interval_minutes: int = 360
    favorite_scheduler_enabled: bool = True
    favorite_scheduler_interval_seconds: int = 60
    rss_scheduler_enabled: bool = True
    rss_scheduler_interval_seconds: int = 60
    rss_default_interval_minutes: int = 180
    campus_source_scheduler_enabled: bool = True
    campus_source_scheduler_interval_seconds: int = 60
    # 自动生成报告会触发模型调用；在报告管线完成成本与质量验证前，默认只允许
    # 由用户在界面中手动发起，避免失败任务在后台反复重试并消耗额度。
    campus_digest_scheduler_enabled: bool = False
    campus_digest_scheduler_interval_seconds: int = 30
    campus_digest_backfill_days: int = 14
    campus_gwt_backfill_limit: int = 300
    campus_digest_daily_cutoff: str = "21:15"
    campus_digest_daily_generate_at: str = "21:30"
    campus_digest_weekly_cutoff: str = "19:30"
    campus_digest_weekly_generate_at: str = "20:00"
    campus_embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    campus_embedding_enabled: bool = False
    # Campus report clustering prefers a remotely hosted Qwen embedding model
    # when the user configures one. The local model remains an optional,
    # offline fallback and is never downloaded by report generation.
    campus_embedding_api_key: str = ""
    campus_embedding_api_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    campus_embedding_api_model: str = "qwen3.7-text-embedding"
    campus_embedding_api_dimensions: int = 1024
    # The WeChat mini-program visual collector is not ready for public
    # distribution. Builds must explicitly enable it.
    miniprogram_forum_capture_enabled: bool = False
    # Manual updates only: clients read the fixed public manifest and open its
    # official GitHub Release page in the browser. The app never downloads or
    # installs an update in the background.
    app_version: str = "0.1.4"
    release_manifest_url: str = (
        "https://knowledgehub-release-manifest.knowledgehub4chen.workers.dev/v1/manifest.json"
    )
    download_page_url: str = "https://github.com/AmaziiingChen/video-knowledge/releases"
    # The public collector is compiled as an exact-host allowlist in
    # telemetry_uploader. New installations use the fixed default-on catalog;
    # an explicit local opt-out leaves the loop inert without changing product
    # behavior or allowing an alternate destination.
    telemetry_collector_url: str = (
        "https://knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev/v1/events"
    )

settings = Settings()
ensure_private_data_directory(settings.data_dir)
