from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import mimetypes
import re
import tempfile
import time
from time import perf_counter
from typing import Any
from urllib.parse import urlparse
from pathlib import Path

import requests

from config import settings
from services.paddle_ocr_settings import (
    PADDLE_OCR_IMAGE_CONCURRENCY,
    paddle_ocr_base_url,
    paddle_ocr_model,
)
from services.ocr_call_logger import record_ocr_call
from services.article_image_storage import write_article_image_preview
from services.wechat_browser import WECHAT_BROWSER_HEADERS
from services.public_url import get_public_http_response
from services.telemetry import record as record_telemetry
from services.database import connect, initialize_database, utc_now_iso
from threading import Lock


OCR_INLINE_WAIT_SECONDS = 15
OCR_POLL_INTERVAL_SECONDS = 1.0
OCR_RETRY_ATTEMPTS = 3
OCR_RETRY_BASE_SECONDS = 1.0
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024

# 网页文章中的海报、通知截图和表格，通常需要维持版面与阅读顺序。去畸变
# 主要服务于拍摄的褶皱或倾斜纸张，会额外增加耗时；本项目以网页原图为主，
# 因此保留关闭。这个配置仅包含官方异步 API 支持的 optionalPayload 字段。
OCR_OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": True,
    "useDocUnwarping": False,
    "useLayoutDetection": True,
    "useChartRecognition": True,
    "prettifyMarkdown": True,
    "temperature": 0,
    "visualize": False,
}

# 共享执行器让所有公众号文章共用同一份 OCR 并发预算。不能在每篇文章里
# 单独创建 5 个 worker，否则 6 个管线任务会瞬间扩张为 30 个 OCR 请求。
_ocr_executor = ThreadPoolExecutor(
    max_workers=PADDLE_OCR_IMAGE_CONCURRENCY,
    thread_name_prefix="wechat-image-ocr",
)
_ocr_resume_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr-resume")
_scheduled_resume_digests: set[str] = set()
_resume_lock = Lock()


@dataclass(frozen=True)
class OcrImageResult:
    url: str
    text: str = ""
    status: str = "skipped"
    error: str = ""
    cached_path: str = ""
    skip_reason: str = ""
    cloud_submitted: bool = False


class OcrJobPending(TimeoutError):
    """The provider accepted work which should be resumed instead of resent."""


def is_paddle_ocr_configured() -> bool:
    return bool(settings.paddle_ocr_access_token)


def recognize_wechat_images(
    image_urls: list[str],
    *,
    article_url: str,
    image_cache_dir: Path | None = None,
    content_item_id: str | None = None,
) -> list[OcrImageResult]:
    """Recognize article images concurrently while retaining their source order.

    The service accepts a local upload instead of passing WeChat CDN URLs to the
    OCR provider. This avoids failures caused by WeChat's referer checks and
    keeps the provider from needing access to a user's authenticated page.
    """
    urls = [str(url or "").strip() for url in image_urls if str(url or "").strip()]
    if not urls:
        return []
    if not is_paddle_ocr_configured():
        return [OcrImageResult(url=url, status="not_configured") for url in urls]

    # executor.map deliberately preserves the DOM order of the input URLs.
    # The executor is shared across all articles, so this remains a global cap.
    kwargs = {"content_item_id": content_item_id} if content_item_id else {}
    return list(
        _ocr_executor.map(
            lambda url: _recognize_one(
                url,
                article_url=article_url,
                image_cache_dir=image_cache_dir,
                **kwargs,
            ),
            urls,
        )
    )


def _recognize_one(
    url: str,
    *,
    article_url: str,
    image_cache_dir: Path | None = None,
    content_item_id: str | None = None,
) -> OcrImageResult:
    cached_path = ""
    try:
        image_bytes, filename, content_type = _download_image(url, article_url=article_url)
        cached_path = _cache_image(
            image_bytes,
            source_url=url,
            content_type=content_type,
            image_cache_dir=image_cache_dir,
        )
        return _recognize_image_bytes(
            image_bytes,
            url=url,
            filename=filename,
            content_type=content_type,
            cached_path=cached_path,
            content_item_id=content_item_id,
        )
    except Exception as exc:
        # Do not include request headers or provider payloads here: they may
        # carry an access token. A per-image failure must not block the article.
        return OcrImageResult(
            url=url,
            status="failed",
            error=_safe_error_message(exc),
            cached_path=cached_path,
            cloud_submitted=bool(cached_path),
        )


def recognize_local_image(
    path: Path,
    *,
    content_item_id: str | None = None,
    force_cloud: bool = False,
) -> OcrImageResult:
    """Run OCR for one local image, primarily for diagnostics and validation."""
    image_path = Path(path).expanduser().resolve()
    if not image_path.is_file():
        raise ValueError("本地图片不存在")
    image_bytes = image_path.read_bytes()
    if not image_bytes:
        raise ValueError("本地图片内容为空")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 20MB，已跳过")
    content_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    if not content_type.startswith("image/"):
        raise ValueError("不是可识别的图片")
    return _recognize_image_bytes(
        image_bytes,
        url=image_path.as_uri(),
        filename=image_path.name,
        content_type=content_type,
        cached_path=str(image_path),
        content_item_id=content_item_id,
        force_cloud=force_cloud,
    )


def recognize_document_bytes(
    document_bytes: bytes,
    *,
    url: str,
    filename: str,
    content_type: str,
    content_item_id: str | None = None,
) -> OcrImageResult:
    """Submit a PDF through the existing async OCR, cache and audit pipeline."""
    if not document_bytes:
        return OcrImageResult(url=url, status="failed", error="PDF 内容为空")
    if len(document_bytes) > MAX_DOCUMENT_BYTES:
        return OcrImageResult(url=url, status="failed", error="PDF 超过 50MB，已跳过")
    if content_type.lower().split(";", 1)[0].strip() != "application/pdf":
        return OcrImageResult(url=url, status="failed", error="不是可识别的 PDF")
    if not is_paddle_ocr_configured():
        return OcrImageResult(url=url, status="not_configured")
    return _recognize_ocr_bytes(
        document_bytes,
        url=url,
        filename=filename,
        content_type="application/pdf",
        cached_path="",
        content_item_id=content_item_id,
    )


def _recognize_image_bytes(
    image_bytes: bytes,
    *,
    url: str,
    filename: str,
    content_type: str,
    cached_path: str,
    content_item_id: str | None,
    force_cloud: bool = False,
) -> OcrImageResult:
    # Do not use device OCR as a gate. macOS Vision Fast produces false
    # negatives for Chinese tables and posters, which must still be submitted
    # to PaddleOCR. Source-HTML filters remove only explicit non-content media
    # before this function is reached.
    return _recognize_ocr_bytes(
        image_bytes,
        url=url,
        filename=filename,
        content_type=content_type,
        cached_path=cached_path,
        content_item_id=content_item_id,
        force_cloud=force_cloud,
    )


def _recognize_ocr_bytes(
    payload: bytes,
    *,
    url: str,
    filename: str,
    content_type: str,
    cached_path: str,
    content_item_id: str | None,
    force_cloud: bool = False,
) -> OcrImageResult:
    content_digest = hashlib.sha256(payload).hexdigest()
    if not force_cloud:
        cached_ocr = _read_ocr_result_cache(content_digest, url=url, cached_path=cached_path)
        if cached_ocr is not None:
            return cached_ocr

    started_at = perf_counter()
    cloud_submitted = False
    retry_count = 0
    try:
        job = _prepare_ocr_job(
            content_digest,
            content_item_id=content_item_id,
            source_url=url,
            cached_path=cached_path,
        )
        job_id = str(job.get("provider_job_id") or "")
        submit_retries = int(job.get("retry_count") or 0)
        if not job_id:
            if str(job.get("status") or "") == "submitting":
                return OcrImageResult(
                    url=url,
                    status="pending",
                    error="图片识别任务正在提交",
                    cached_path=cached_path,
                    cloud_submitted=True,
                )
            if str(job.get("status") or "") == "failed" and not force_cloud:
                return OcrImageResult(
                    url=url,
                    status="failed",
                    error=str(job.get("error") or "图片识别任务失败"),
                    cached_path=cached_path,
                )
            if not _claim_ocr_submission(content_digest, allow_retry=force_cloud):
                return OcrImageResult(
                    url=url,
                    status="pending",
                    error="图片识别任务正在提交",
                    cached_path=cached_path,
                    cloud_submitted=True,
                )
            try:
                job_id, submit_retries = _submit_job(payload, filename=filename, content_type=content_type)
            except Exception as exc:
                _mark_ocr_job_failed(content_digest, _safe_error_message(exc))
                raise
            _store_ocr_submission(content_digest, job_id, submit_retries)
            cloud_submitted = True
        else:
            cloud_submitted = True

        try:
            result_url, result_kind, poll_retries = _wait_for_result(
                job_id,
                timeout_seconds=OCR_INLINE_WAIT_SECONDS,
            )
        except OcrJobPending:
            _mark_ocr_job_pending(content_digest)
            _schedule_ocr_resume(content_digest)
            return OcrImageResult(
                url=url,
                status="pending",
                error="图片识别仍在处理中，将在后台继续获取结果",
                cached_path=cached_path,
                cloud_submitted=True,
            )
        retry_count = submit_retries + poll_retries
        text = (
            _download_json_result(result_url)
            if result_kind == "json"
            else _download_markdown(result_url)
        )
        result = OcrImageResult(
            url=url,
            text=text,
            status="succeeded" if text else "empty",
            cached_path=cached_path,
            cloud_submitted=True,
        )
        _write_ocr_result_cache(content_digest, result)
        _mark_ocr_job_succeeded(content_digest, result_url, result_kind, retry_count)
        record_ocr_call(
            content_item_id=content_item_id,
            image_url=url,
            image_bytes=len(payload),
            model=paddle_ocr_model(),
            status=result.status,
            cloud_submitted=True,
            retry_count=retry_count,
            elapsed_seconds=perf_counter() - started_at,
        )
        record_telemetry("paddle_ocr_completed", {"result": result.status})
        return result
    except Exception as exc:
        _mark_ocr_job_failed(content_digest, _safe_error_message(exc))
        if cloud_submitted:
            record_ocr_call(
                content_item_id=content_item_id,
                image_url=url,
                image_bytes=len(payload),
                model=paddle_ocr_model(),
                status="failed",
                cloud_submitted=True,
                retry_count=retry_count,
                elapsed_seconds=perf_counter() - started_at,
                error=_safe_error_message(exc),
            )
            record_telemetry("paddle_ocr_completed", {"result": "failed"})
        raise


def _ocr_result_cache_path(content_digest: str) -> Path:
    return settings.data_dir / "ocr_image_cache" / f"{content_digest}.json"


def _read_ocr_result_cache(
    content_digest: str,
    *,
    url: str,
    cached_path: str,
) -> OcrImageResult | None:
    path = _ocr_result_cache_path(content_digest)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = str(payload.get("status") or "")
        if status not in {"succeeded", "empty"}:
            return None
        return OcrImageResult(
            url=url,
            text=str(payload.get("text") or ""),
            status=status,
            cached_path=cached_path,
            skip_reason="duplicate_cache",
            cloud_submitted=False,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_ocr_result_cache(content_digest: str, result: OcrImageResult) -> None:
    path = _ocr_result_cache_path(content_digest)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "status": result.status,
                    "text": result.text,
                    "model": paddle_ocr_model(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _prepare_ocr_job(
    content_digest: str,
    *,
    content_item_id: str | None,
    source_url: str,
    cached_path: str,
) -> dict[str, Any]:
    """Get one durable remote job and register this article as a consumer."""
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO paddle_ocr_jobs (
                content_digest, provider_job_id, status, created_at, updated_at
            ) VALUES (?, NULL, 'created', ?, ?)
            """,
            (content_digest, now, now),
        )
        if content_item_id and connection.execute(
            "SELECT 1 FROM content_items WHERE id=?",
            (content_item_id,),
        ).fetchone():
            connection.execute(
                """
                INSERT INTO paddle_ocr_job_consumers (content_digest, content_item_id, source_url, cached_path)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(content_digest, content_item_id) DO UPDATE SET
                    source_url=excluded.source_url,
                    cached_path=excluded.cached_path
                """,
                (content_digest, content_item_id, source_url[:2000], cached_path[:2000]),
            )
        row = connection.execute(
            "SELECT * FROM paddle_ocr_jobs WHERE content_digest=?",
            (content_digest,),
        ).fetchone()
        connection.commit()
    return dict(row) if row else {"content_digest": content_digest, "status": "created"}


def _claim_ocr_submission(content_digest: str, *, allow_retry: bool) -> bool:
    """Atomically reserve the only POST allowed for this content digest."""
    with connect() as connection:
        allowed = ("created", "failed") if allow_retry else ("created",)
        placeholders = ",".join("?" for _ in allowed)
        cursor = connection.execute(
            f"""UPDATE paddle_ocr_jobs
                SET status='submitting', error='', updated_at=?
                WHERE content_digest=? AND provider_job_id IS NULL AND status IN ({placeholders})""",
            (utc_now_iso(), content_digest, *allowed),
        )
        connection.commit()
    return bool(cursor.rowcount)


def _store_ocr_submission(content_digest: str, job_id: str, retry_count: int) -> None:
    with connect() as connection:
        connection.execute(
            """UPDATE paddle_ocr_jobs
               SET provider_job_id=?, status='polling', retry_count=?, error='', updated_at=?
               WHERE content_digest=?""",
            (job_id, max(0, retry_count), utc_now_iso(), content_digest),
        )
        connection.commit()


def _mark_ocr_job_pending(content_digest: str, error: str = "") -> None:
    with connect() as connection:
        connection.execute(
            """UPDATE paddle_ocr_jobs
               SET status='polling', error=?, updated_at=?
               WHERE content_digest=? AND provider_job_id IS NOT NULL""",
            (error[:500], utc_now_iso(), content_digest),
        )
        connection.commit()


def _mark_ocr_job_succeeded(content_digest: str, result_url: str, result_kind: str, retry_count: int) -> None:
    with connect() as connection:
        connection.execute(
            """UPDATE paddle_ocr_jobs
               SET status='succeeded', result_url=?, result_kind=?, retry_count=?, error='',
                   updated_at=?, finished_at=?
               WHERE content_digest=?""",
            (result_url[:2000], result_kind, max(0, retry_count), utc_now_iso(), utc_now_iso(), content_digest),
        )
        connection.commit()


def _mark_ocr_job_failed(content_digest: str, error: str) -> None:
    try:
        with connect() as connection:
            connection.execute(
                """UPDATE paddle_ocr_jobs
                   SET status='failed', error=?, updated_at=?, finished_at=?
                   WHERE content_digest=?""",
                (error[:500], utc_now_iso(), utc_now_iso(), content_digest),
            )
            connection.commit()
    except Exception:
        return


def _load_ocr_job(content_digest: str) -> dict[str, Any] | None:
    try:
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM paddle_ocr_jobs WHERE content_digest=?",
                (content_digest,),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _ocr_job_consumers(content_digest: str) -> list[dict[str, str]]:
    try:
        with connect() as connection:
            rows = connection.execute(
                """SELECT content_item_id, source_url, cached_path
                   FROM paddle_ocr_job_consumers WHERE content_digest=?""",
                (content_digest,),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def _schedule_ocr_resume(content_digest: str) -> None:
    with _resume_lock:
        if content_digest in _scheduled_resume_digests:
            return
        _scheduled_resume_digests.add(content_digest)
    _ocr_resume_executor.submit(_resume_ocr_job, content_digest)


def _resume_ocr_job(content_digest: str) -> None:
    try:
        job = _load_ocr_job(content_digest)
        if not job or str(job.get("status") or "") == "succeeded":
            return
        job_id = str(job.get("provider_job_id") or "")
        if not job_id:
            # A crash after POST but before persisting the provider ID cannot
            # be safely retried: submitting again could create billable work.
            _mark_ocr_job_failed(content_digest, "识别任务提交状态不完整，请手动重试")
            return
        while True:
            try:
                result_url, result_kind, retry_count = _wait_for_result(job_id, timeout_seconds=None)
                text = _download_json_result(result_url) if result_kind == "json" else _download_markdown(result_url)
                result = OcrImageResult(url="", text=text, status="succeeded" if text else "empty", cloud_submitted=True)
                _write_ocr_result_cache(content_digest, result)
                _mark_ocr_job_succeeded(content_digest, result_url, result_kind, retry_count)
                _refresh_ocr_consumers(content_digest, text=result.text)
                return
            except (requests.RequestException, OcrJobPending):
                _mark_ocr_job_pending(content_digest, "等待图片识别服务响应")
                time.sleep(5)
            except Exception as exc:
                _mark_ocr_job_failed(content_digest, _safe_error_message(exc))
                return
    finally:
        with _resume_lock:
            _scheduled_resume_digests.discard(content_digest)


def _refresh_ocr_consumers(content_digest: str, *, text: str) -> None:
    """Materialize every durable consumer when remote OCR reaches completion."""
    for consumer in _ocr_job_consumers(content_digest):
        content_item_id = str(consumer.get("content_item_id") or "")
        if not content_item_id:
            continue
        try:
            if str(consumer.get("source_url") or "").startswith("local-file:"):
                # Local PDF/image imports create their Markdown only after the
                # asynchronous provider result is available. This is also the
                # restart path, so never rely on the original task worker.
                from services.local_file_imports import complete_pending_ocr_import

                complete_pending_ocr_import(content_item_id, body=text)
                continue
            from services.content_source_text import load_content_source_text

            load_content_source_text(content_item_id, include_image_ocr=True)
        except Exception:
            # The final OCR cache is durable. A later content load will merge
            # it even if this best-effort refresh races deletion or shutdown.
            continue


def resume_pending_ocr_jobs() -> None:
    """Recover accepted OCR work and materialize completions after a restart."""
    try:
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                """SELECT content_digest, status FROM paddle_ocr_jobs AS job
                   WHERE (status='polling' AND provider_job_id IS NOT NULL)
                      OR (
                          status='succeeded'
                          AND EXISTS (
                              SELECT 1 FROM paddle_ocr_job_consumers AS consumer
                              WHERE consumer.content_digest=job.content_digest
                                AND consumer.source_url LIKE 'local-file:%'
                          )
                      )
                   ORDER BY updated_at ASC LIMIT 100"""
            ).fetchall()
    except Exception:
        return
    for row in rows:
        content_digest = str(row["content_digest"])
        if str(row["status"]) == "succeeded":
            # Older builds could receive a provider result after the import
            # task had already been marked failed. Repair that durable gap on
            # startup using the cached result, without calling Paddle again.
            result = _read_ocr_result_cache(content_digest, url="", cached_path="")
            if result and result.status == "succeeded" and result.text.strip():
                _refresh_ocr_consumers(content_digest, text=result.text)
            continue
        _schedule_ocr_resume(content_digest)


def _download_image(url: str, *, article_url: str) -> tuple[bytes, str, str]:
    headers = {**WECHAT_BROWSER_HEADERS, "Referer": article_url}
    response, final_url = get_public_http_response(
        url,
        invalid_message="图片地址无效",
        blocked_message="图片地址不可访问",
        redirect_invalid_message="图片地址重定向地址无效",
        redirect_limit_message="图片地址重定向次数过多",
        max_redirects=5,
        headers=headers,
        timeout=30,
        stream=True,
    )
    try:
        response.raise_for_status()
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            raise ValueError("不是可识别的图片")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ValueError("图片超过 20MB，已跳过")
            chunks.append(chunk)
    finally:
        response.close()
    payload = b"".join(chunks)
    if not payload:
        raise ValueError("图片内容为空")
    return payload, _image_filename(final_url, content_type), content_type or "image/jpeg"


def _image_filename(url: str, content_type: str) -> str:
    path_name = urlparse(url).path.rsplit("/", 1)[-1]
    path_name = re.sub(r"[^A-Za-z0-9._-]", "_", path_name) or "wechat-image"
    if "." not in path_name:
        extension = mimetypes.guess_extension(content_type) or ".jpg"
        path_name += extension
    return path_name[:120]


def _cache_image(
    image_bytes: bytes,
    *,
    source_url: str,
    content_type: str,
    image_cache_dir: Path | None,
) -> str:
    """Persist an OCR input image so article preview never needs that CDN again."""
    if image_cache_dir is None or not image_bytes:
        return ""
    filename_stem = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:20]
    target = image_cache_dir / f"{filename_stem}.webp"
    if target.exists() and target.is_file() and target.stat().st_size > 0:
        return str(target)
    preview = write_article_image_preview(
        image_bytes,
        filename_stem=filename_stem,
        image_cache_dir=image_cache_dir,
    )
    if preview:
        return preview

    # OCR must not make an article unreadable when an uncommon image format
    # cannot be decoded by Pillow. Keep that source image as a narrow fallback.
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    extension = extension.lower() if re.fullmatch(r"\.[a-z0-9]{1,8}", extension.lower()) else ".jpg"
    fallback = image_cache_dir / f"{filename_stem}{extension}"
    image_cache_dir.mkdir(parents=True, exist_ok=True)
    fallback.write_bytes(image_bytes)
    return str(fallback)


def _submit_job(image_bytes: bytes, *, filename: str, content_type: str) -> tuple[str, int]:
    token = settings.paddle_ocr_access_token
    if not token:
        raise ValueError("未配置图片 OCR")
    response, retries = _request_with_backoff(
        lambda: requests.post(
            paddle_ocr_base_url(),
            headers={"Authorization": f"Bearer {token}"},
            data={
                "model": paddle_ocr_model(),
                "optionalPayload": json.dumps(OCR_OPTIONAL_PAYLOAD, ensure_ascii=False),
            },
            files={"file": (filename, image_bytes, content_type)},
            timeout=45,
        )
    )
    payload = _json_object(response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    job_id = str(data.get("jobId") or data.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("图片识别任务未返回编号")
    return job_id, retries


def _wait_for_result(
    job_id: str,
    *,
    timeout_seconds: float | None = OCR_INLINE_WAIT_SECONDS,
) -> tuple[str, str, int]:
    token = settings.paddle_ocr_access_token
    deadline = time.monotonic() + max(0.0, timeout_seconds) if timeout_seconds is not None else None
    retry_count = 0
    while deadline is None or time.monotonic() < deadline:
        response, retries = _request_with_backoff(
            lambda: requests.get(
                f"{paddle_ocr_base_url()}/{job_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
        )
        retry_count += retries
        payload = _json_object(response)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        result_urls = data.get("resultUrl") or data.get("result_url") or {}
        if isinstance(result_urls, dict):
            markdown_url = str(result_urls.get("markdownUrl") or result_urls.get("markdown_url") or "").strip()
            if markdown_url:
                return markdown_url, "markdown", retry_count
            json_url = str(result_urls.get("jsonUrl") or result_urls.get("json_url") or "").strip()
            if json_url:
                return json_url, "json", retry_count
        state = str(data.get("state") or data.get("status") or "").lower()
        if state in {"failed", "failure", "cancelled", "canceled", "error"}:
            raise ValueError("图片识别未完成")
        if state in {"done", "succeeded", "success", "completed"}:
            raise ValueError("图片识别结果缺少可读取地址")
        time.sleep(OCR_POLL_INTERVAL_SECONDS)
    raise OcrJobPending("图片识别仍在处理中")


def _request_with_backoff(send) -> tuple[Any, int]:
    """Retry explicit throttling and transient server responses.

    OCR submissions are asynchronous. Retrying a connection timeout could submit
    the same image twice, so transport exceptions are deliberately not retried.
    """
    for attempt in range(OCR_RETRY_ATTEMPTS):
        response = send()
        status_code = int(getattr(response, "status_code", 0) or 0)
        retryable = status_code == 429 or 500 <= status_code < 600
        if not retryable:
            response.raise_for_status()
            return response, attempt
        if attempt == OCR_RETRY_ATTEMPTS - 1:
            response.raise_for_status()
            return response, attempt
        time.sleep(_retry_delay_seconds(response, attempt))
    raise RuntimeError("图片 OCR 请求重试状态异常")


def _retry_delay_seconds(response, attempt: int) -> float:
    retry_after = str(getattr(response, "headers", {}).get("Retry-After") or "").strip()
    try:
        return min(30.0, max(0.0, float(retry_after)))
    except ValueError:
        return min(8.0, OCR_RETRY_BASE_SECONDS * (2 ** attempt))


def _download_markdown(url: str) -> str:
    response, _ = get_public_http_response(
        url,
        invalid_message="图片地址无效",
        blocked_message="图片地址不可访问",
        redirect_invalid_message="图片地址重定向地址无效",
        redirect_limit_message="图片地址重定向次数过多",
        max_redirects=5,
        timeout=30,
    )
    try:
        response.raise_for_status()
        return _clean_markdown(response.text)
    finally:
        response.close()


def _download_json_result(url: str) -> str:
    response, _ = get_public_http_response(
        url,
        invalid_message="图片地址无效",
        blocked_message="图片地址不可访问",
        redirect_invalid_message="图片地址重定向地址无效",
        redirect_limit_message="图片地址重定向次数过多",
        max_redirects=5,
        timeout=30,
    )
    try:
        response.raise_for_status()
        texts = [_extract_json_result_text(payload) for payload in _json_result_objects(response)]
        return "\n\n".join(text for text in texts if text).strip()
    finally:
        response.close()


def _json_result_objects(response: Any) -> list[dict[str, Any]]:
    """Accept both one JSON object and PaddleOCR's JSON-lines PDF result."""
    try:
        payload = response.json()
    except ValueError:
        payloads: list[dict[str, Any]] = []
        for line in str(getattr(response, "text", "") or "").splitlines():
            if not line.strip():
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("图片识别服务返回异常") from exc
            if not isinstance(candidate, dict):
                raise ValueError("图片识别服务返回异常")
            payloads.append(candidate)
        if payloads:
            return payloads
        raise ValueError("图片识别服务返回异常")
    if not isinstance(payload, dict):
        raise ValueError("图片识别服务返回异常")
    return [payload]


def _extract_json_result_text(payload: dict[str, Any]) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    pages = result.get("layoutParsingResults") or result.get("layout_parsing_results") or []
    if not isinstance(pages, list):
        return ""
    parts: list[str] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        markdown = page.get("markdown")
        if not isinstance(markdown, dict):
            continue
        text = _clean_markdown(str(markdown.get("text") or ""))
        # A photograph with no detected writing is often represented only by
        # an HTML/Markdown image tag. That is not usable OCR source material.
        readable = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        readable = re.sub(r"<[^>]+>", "", readable).strip()
        if readable:
            parts.append(text)
    return "\n\n".join(parts).strip()


def _clean_markdown(value: str) -> str:
    lines = [line.rstrip() for line in str(value or "").replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    empty_pending = False
    for line in lines:
        if not line.strip():
            empty_pending = bool(compact)
            continue
        if empty_pending:
            compact.append("")
            empty_pending = False
        compact.append(line)
    return "\n".join(compact).strip()


def _json_object(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("图片识别服务返回异常") from exc
    if not isinstance(payload, dict):
        raise ValueError("图片识别服务返回异常")
    return payload


def _safe_error_message(exc: Exception) -> str:
    message = str(exc or "").strip()
    if not message:
        return "识别失败"
    # Requests may include a URL in its message. Keep diagnostics useful but
    # bounded; provider authorization details never appear in public status.
    return message[:160]
