from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from services import article_ingest_preparation
from config import settings
from services.content_index import ensure_content_item_for_media
from services.content_source_text import ContentTextReadiness, should_resume_article_preparation
from services.database import initialize_database


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, dict[str, object]]] = []

    def submit(self, callback, content_item_id: str, **kwargs) -> None:
        self.calls.append((callback, content_item_id, kwargs))


def _reset_preparation_state() -> None:
    with article_ingest_preparation._pending_lock:
        article_ingest_preparation._pending_ids.clear()
        article_ingest_preparation._web_capture_queued_ids.clear()
        article_ingest_preparation._wechat_capture_queued_ids.clear()
        article_ingest_preparation._ocr_queued_ids.clear()
        article_ingest_preparation._active_web_capture_ids.clear()
        article_ingest_preparation._active_wechat_capture_ids.clear()
        article_ingest_preparation._active_ocr_ids.clear()
        article_ingest_preparation._priority_ocr_ids.clear()


def test_article_preparation_runs_without_ocr_configuration(monkeypatch):
    executor = _RecordingExecutor()
    monkeypatch.setattr(article_ingest_preparation, "_web_capture_executor", executor)
    monkeypatch.setattr(article_ingest_preparation, "_is_wechat_article", lambda _item_id: False)
    _reset_preparation_state()

    assert article_ingest_preparation.enqueue_article_source_preparation("article-without-ocr") is True
    assert [content_item_id for _, content_item_id, _ in executor.calls] == ["article-without-ocr"]

    _reset_preparation_state()


def test_article_preparation_status_reports_fifo_backlog(monkeypatch):
    executor = _RecordingExecutor()
    monkeypatch.setattr(article_ingest_preparation, "_web_capture_executor", executor)
    monkeypatch.setattr(article_ingest_preparation, "_is_wechat_article", lambda _item_id: False)
    _reset_preparation_state()
    article_ingest_preparation._completed_count = 0
    article_ingest_preparation._failed_count = 0

    assert article_ingest_preparation.enqueue_article_source_preparation("first") is True
    assert article_ingest_preparation.enqueue_article_source_preparation("second") is True
    status = article_ingest_preparation.article_source_preparation_status()

    assert [content_item_id for _, content_item_id, _ in executor.calls] == ["first", "second"]
    assert status["active_count"] == 0
    assert status["queued_count"] == 2
    assert status["pending_count"] == 2
    assert status["capture_queued_count"] == 2
    assert status["ocr_queued_count"] == 0

    _reset_preparation_state()


def test_explicit_backfill_queues_articles_without_cached_body(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    item = ensure_content_item_for_media(
        source_provider="wechat",
        source_url="https://mp.weixin.qq.com/s/backfill",
        video_info={"title": "待预抓取文章"},
        content_type="article",
    )
    executor = _RecordingExecutor()
    monkeypatch.setattr(article_ingest_preparation, "_wechat_capture_executor", executor)
    _reset_preparation_state()

    assert article_ingest_preparation.enqueue_pending_article_preparation() == 1
    assert [content_item_id for _, content_item_id, _ in executor.calls] == [item.id]

    _reset_preparation_state()


def test_capture_skips_a_stale_job_that_no_longer_needs_preparation(monkeypatch):
    calls: list[bool] = []
    item = type("Article", (), {"id": "already-ready"})()
    monkeypatch.setattr(article_ingest_preparation, "_article_item", lambda _item_id: item)
    monkeypatch.setattr(article_ingest_preparation, "should_prepare_article_in_background", lambda _item: False)
    monkeypatch.setattr(
        article_ingest_preparation,
        "load_content_source_text",
        lambda _item_id, *, include_image_ocr: calls.append(include_image_ocr),
    )
    _reset_preparation_state()
    with article_ingest_preparation._pending_lock:
        article_ingest_preparation._pending_ids.add(item.id)
        article_ingest_preparation._web_capture_queued_ids.append(item.id)

    article_ingest_preparation._capture(item.id, is_wechat=False)

    assert calls == []
    status = article_ingest_preparation.article_source_preparation_status()
    assert status["pending_count"] == 0
    assert status["queued_count"] == 0
    assert status["active_count"] == 0


def test_body_capture_is_saved_before_ocr_enrichment(monkeypatch):
    ocr_executor = _RecordingExecutor()
    calls: list[bool] = []
    monkeypatch.setattr(article_ingest_preparation, "_ocr_executor", ocr_executor)
    monkeypatch.setattr(article_ingest_preparation, "_is_wechat_article", lambda _item_id: False)
    monkeypatch.setattr(
        article_ingest_preparation,
        "load_content_source_text",
        lambda _item_id, *, include_image_ocr: calls.append(include_image_ocr),
    )
    _reset_preparation_state()
    with article_ingest_preparation._pending_lock:
        article_ingest_preparation._pending_ids.add("article-1")
        article_ingest_preparation._web_capture_queued_ids.append("article-1")

    article_ingest_preparation._capture("article-1", is_wechat=False)

    assert calls == [False]
    assert [content_item_id for _, content_item_id, _ in ocr_executor.calls] == ["article-1"]
    assert article_ingest_preparation.article_source_preparation_status()["ocr_queued_count"] == 1

    callback, content_item_id, _ = ocr_executor.calls[0]
    callback(content_item_id)
    assert calls == [False, True]
    assert article_ingest_preparation.article_source_preparation_status()["pending_count"] == 0


def test_wechat_waiters_do_not_occupy_web_capture_workers(monkeypatch):
    web_executor = _RecordingExecutor()
    wechat_executor = _RecordingExecutor()
    monkeypatch.setattr(article_ingest_preparation, "_web_capture_executor", web_executor)
    monkeypatch.setattr(article_ingest_preparation, "_wechat_capture_executor", wechat_executor)
    monkeypatch.setattr(article_ingest_preparation, "_is_wechat_article", lambda item_id: item_id.startswith("wechat"))
    _reset_preparation_state()

    assert article_ingest_preparation.enqueue_article_source_preparation("wechat-1") is True
    assert article_ingest_preparation.enqueue_article_source_preparation("web-1") is True
    status = article_ingest_preparation.article_source_preparation_status()

    assert [content_item_id for _, content_item_id, _ in wechat_executor.calls] == ["wechat-1"]
    assert [content_item_id for _, content_item_id, _ in web_executor.calls] == ["web-1"]
    assert status["wechat_capture_queued_count"] == 1
    assert status["web_capture_queued_count"] == 1
    _reset_preparation_state()


def test_prioritizing_ocr_moves_an_existing_ocr_job_to_the_front(monkeypatch):
    monkeypatch.setattr(
        article_ingest_preparation,
        "article_image_ocr_status",
        lambda _item_id: {"status": "queued", "has_images": True, "priority": True},
    )
    _reset_preparation_state()
    with article_ingest_preparation._pending_lock:
        article_ingest_preparation._pending_ids.update({"other", "current"})
        article_ingest_preparation._ocr_queued_ids.extend(["other", "current"])

    article_ingest_preparation.prioritize_article_image_ocr("current")

    with article_ingest_preparation._pending_lock:
        assert list(article_ingest_preparation._ocr_queued_ids) == ["current", "other"]
        assert "current" in article_ingest_preparation._priority_ocr_ids
    _reset_preparation_state()


def test_completed_ocr_clears_a_stale_queued_job(monkeypatch):
    item = type("Article", (), {
        "id": "current",
        "content_type": "article",
        "source_provider": "wechat",
        "source_url": "https://mp.weixin.qq.com/s/current",
    })()
    monkeypatch.setattr(article_ingest_preparation, "_article_item", lambda _item_id: item)
    monkeypatch.setattr(
        article_ingest_preparation,
        "read_cache_meta",
        lambda _cache_dir: {
            "article_info": {
                "images": ["https://img.example/poster.png"],
                "image_ocr": {"attempted": True, "image_count": 1, "recognized_count": 0},
            }
        },
    )
    _reset_preparation_state()
    with article_ingest_preparation._pending_lock:
        article_ingest_preparation._pending_ids.add("current")
        article_ingest_preparation._priority_ocr_ids.add("current")
        article_ingest_preparation._ocr_queued_ids.append("current")

    status = article_ingest_preparation.article_image_ocr_status("current")

    assert status["status"] == "completed"
    assert status["priority"] is False
    with article_ingest_preparation._pending_lock:
        assert "current" not in article_ingest_preparation._ocr_queued_ids
        assert "current" not in article_ingest_preparation._pending_ids
    _reset_preparation_state()


def test_legacy_local_prefilter_skip_remains_ocr_pending(monkeypatch):
    item = type("Article", (), {
        "id": "current",
        "content_type": "article",
        "source_provider": "wechat",
        "source_url": "https://mp.weixin.qq.com/s/current",
    })()
    monkeypatch.setattr(article_ingest_preparation, "_article_item", lambda _item_id: item)
    monkeypatch.setattr(
        article_ingest_preparation,
        "read_cache_meta",
        lambda _cache_dir: {
            "article_info": {
                "images": ["https://img.example/table.png"],
                "image_ocr": {
                    "attempted": True,
                    "image_count": 1,
                    "local_filter_counts": {"text_below_threshold": 1},
                },
            }
        },
    )
    monkeypatch.setattr(article_ingest_preparation, "is_paddle_ocr_configured", lambda: True)
    _reset_preparation_state()

    status = article_ingest_preparation.article_image_ocr_status("current")

    assert status["status"] == "pending"
    _reset_preparation_state()


def test_startup_backfill_only_resumes_known_interrupted_capture_failures():
    interrupted = ContentTextReadiness(
        status="unavailable",
        label="正文暂不可用",
        detail="cannot schedule new futures after interpreter shutdown",
        source_kind="article",
        can_ask_ai=False,
        retryable=True,
    )
    deleted = ContentTextReadiness(
        status="unavailable",
        label="正文暂不可用",
        detail="微信公众号文章已被发布者删除",
        source_kind="article",
        can_ask_ai=False,
        retryable=True,
    )
    pending = ContentTextReadiness(
        status="needs_fetch",
        label="正文待获取",
        detail="等待后台预抓取",
        source_kind="article",
        can_ask_ai=True,
        retryable=True,
    )

    assert should_resume_article_preparation(interrupted) is True
    interrupted_without_interpreter = ContentTextReadiness(
        status="unavailable",
        label="正文暂不可用",
        detail="cannot schedule new futures after shutdown",
        source_kind="article",
        can_ask_ai=False,
        retryable=True,
    )
    assert should_resume_article_preparation(interrupted_without_interpreter) is True
    assert should_resume_article_preparation(deleted) is False
    assert should_resume_article_preparation(pending) is True
