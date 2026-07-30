from __future__ import annotations

import json
from urllib.parse import urlparse

from config import settings


SETTINGS_FILE = "paddle_ocr_settings.json"
PADDLE_OCR_DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
PADDLE_OCR_DEFAULT_MODEL = "PaddleOCR-VL-1.6"
# This is a process-wide budget, not a per-article multiplier. 公众号文章会在
# 管线任务中并行处理；若每篇文章再各自启动 5 个 OCR 请求，很容易把本机和
# 远端服务同时打满。DeepSeek 的分析并发与图片 OCR 分开控制。
PADDLE_OCR_IMAGE_CONCURRENCY = 6


def _path():
    return settings.data_dir / SETTINGS_FILE


def load_paddle_ocr_settings() -> dict[str, str]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_saved_paddle_ocr_settings() -> dict[str, str]:
    saved = load_paddle_ocr_settings()
    if "paddle_ocr_access_token" in saved:
        settings.paddle_ocr_access_token = str(saved["paddle_ocr_access_token"] or "").strip()
    if saved.get("paddle_ocr_base_url"):
        try:
            settings.paddle_ocr_base_url = _normalize_base_url(saved["paddle_ocr_base_url"])
        except ValueError:
            settings.paddle_ocr_base_url = PADDLE_OCR_DEFAULT_BASE_URL
    if saved.get("paddle_ocr_model"):
        try:
            settings.paddle_ocr_model = _normalize_model(saved["paddle_ocr_model"])
        except ValueError:
            settings.paddle_ocr_model = PADDLE_OCR_DEFAULT_MODEL
    return saved


def _normalize_base_url(value: object) -> str:
    candidate = str(value or "").strip() or PADDLE_OCR_DEFAULT_BASE_URL
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("PaddleOCR Base URL 必须是有效的 HTTPS 地址")
    return candidate.rstrip("/")


def _normalize_model(value: object) -> str:
    candidate = str(value or "").strip() or PADDLE_OCR_DEFAULT_MODEL
    if len(candidate) > 160:
        raise ValueError("PaddleOCR 模型名称过长")
    return candidate


def paddle_ocr_base_url() -> str:
    return _normalize_base_url(settings.paddle_ocr_base_url)


def paddle_ocr_model() -> str:
    return _normalize_model(settings.paddle_ocr_model)


def save_paddle_ocr_settings(
    *,
    access_token: str | None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, object]:
    values = load_paddle_ocr_settings()
    if access_token is not None:
        values["paddle_ocr_access_token"] = access_token.strip()
    if base_url is not None:
        values["paddle_ocr_base_url"] = _normalize_base_url(base_url)
    if model is not None:
        values["paddle_ocr_model"] = _normalize_model(model)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    apply_saved_paddle_ocr_settings()
    return paddle_ocr_settings_status()


def paddle_ocr_settings_status() -> dict[str, object]:
    return {
        "configured": bool(settings.paddle_ocr_access_token),
        "base_url": paddle_ocr_base_url(),
        "model": paddle_ocr_model(),
        "image_concurrency": PADDLE_OCR_IMAGE_CONCURRENCY,
    }


def reveal_paddle_ocr_access_token() -> str:
    """Return the local token only after an explicit UI reveal action."""
    saved = load_paddle_ocr_settings()
    return str(saved.get("paddle_ocr_access_token") or settings.paddle_ocr_access_token or "").strip()
