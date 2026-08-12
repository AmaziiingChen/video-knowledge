from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from config import settings
from services.database import connect, initialize_database
from services.cache import write_cache_meta
from services.content_source_text import load_content_source_text
from services.creator_sync import preview_creator_source, sync_saved_creator_source
from services.pipeline_runner import PipelineRequest
from services.repository import ContentRepository
from services.task_manager import task_manager
from services.source_context_refresh import refresh_source_context
from services.xiaohongshu_capability import XiaohongshuCollectorUnavailable, require_xiaohongshu_request
from services.xiaohongshu_cache import xiaohongshu_cache_dir
from services.xiaohongshu_capability import PUBLIC_COLLECTOR_UNAVAILABLE_REASON
from services.xiaohongshu_client import xiaohongshu_cookie_status
from services.xiaohongshu_ingest import sync_due_xiaohongshu_favorites


def test_public_cookie_status_preserves_configured_metadata(tmp_path):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    cookie_path = settings.data_dir / "xiaohongshu_cookie.txt"
    cookie_path.write_text("a=legacy-cookie", encoding="utf-8")

    status = xiaohongshu_cookie_status(probe=True)

    assert status == {
        "configured": True,
        "state": "unavailable",
        "label": "小红书采集不可用",
        "detail": PUBLIC_COLLECTOR_UNAVAILABLE_REASON,
        "collector_available": False,
        "collector_reason": PUBLIC_COLLECTOR_UNAVAILABLE_REASON,
    }
    assert cookie_path.read_text(encoding="utf-8") == "a=legacy-cookie"


def test_public_capture_and_task_endpoints_reject_without_persistence():
    initialize_database()
    client = TestClient(app)
    url = "https://www.xiaohongshu.com/explore/abc123?xsec_token=token"
    with connect() as connection:
        before_items = connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
        before_tasks = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    responses = [
        client.post("/api/inbox/capture", json={"url": url}),
        client.post("/api/ingest/link", json={"text": url, "mode": "capture"}),
        client.post("/api/tasks", json={"share_text": url, "source_url": url}),
        client.post("/api/tasks", json={"share_text": "https://xhslink.cn/a/abc"}),
        client.post("/api/source-sync-tasks", json={"kind": "favorite_xiaohongshu", "source_title": "XHS"}),
    ]

    assert [response.status_code for response in responses] == [400, 409, 409, 409, 409]
    assert all(PUBLIC_COLLECTOR_UNAVAILABLE_REASON in response.text for response in responses)
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == before_items
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before_tasks


def test_public_scheduler_skips_existing_xiaohongshu_subscription():
    initialize_database()
    now = "2026-01-01T00:00:00+00:00"
    with connect() as connection:
        connection.execute(
            """INSERT INTO xiaohongshu_favorite_sources
               (id, auto_analyze, enabled, sync_interval_minutes, sync_limit, next_sync_at, created_at, updated_at)
               VALUES ('legacy-xhs', 1, 1, 360, 5, ?, ?, ?)""",
            (now, now, now),
        )
        connection.commit()
        before_tasks = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    assert sync_due_xiaohongshu_favorites() == []
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before_tasks


def test_public_creator_and_source_context_reject_before_task_write():
    initialize_database()
    client = TestClient(app)
    now = "2026-01-01T00:00:00+00:00"
    url = "https://www.xiaohongshu.com/user/profile/legacy?tab=fav"
    with connect() as connection:
        repository = ContentRepository(connection)
        item = repository.create_content_item(
            source_provider="xiaohongshu",
            content_type="article",
            source_url=url,
            canonical_source_id="cached-note",
            title="cached",
            status="ready",
        )
        connection.execute(
            """INSERT INTO creator_sources
               (id, provider, source_url, source_kind, creator_key, creator_name,
                created_at, updated_at)
               VALUES ('legacy-creator', 'xiaohongshu', ?, 'favorites', 'legacy', '旧收藏', ?, ?)""",
            (url, now, now),
        )
        connection.commit()
        before_tasks = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    responses = [
        client.post("/api/source-sync-tasks", json={"kind": "creator_saved", "source_title": "旧收藏", "source_id": "legacy-creator"}),
        client.post(f"/api/content/{item.id}/refresh-source-context"),
        client.post("/api/creator-sources/preview", json={"source_url": url, "allow_personal_sources": True}),
        client.post("/api/creator-sources/sync", json={"source_url": url, "allow_personal_sources": True}),
        client.post("/api/creator-sources/legacy-creator/sync"),
    ]
    assert [response.status_code for response in responses] == [409, 409, 409, 409, 409]
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before_tasks

    with connect() as connection:
        before_runs = connection.execute("SELECT COUNT(*) FROM creator_sync_runs").fetchone()[0]
        before_context = connection.execute("SELECT COUNT(*) FROM content_source_contexts").fetchone()[0]
    for operation in (
        lambda: preview_creator_source(source_url=url, allow_personal_sources=True),
        lambda: sync_saved_creator_source("legacy-creator"),
        lambda: refresh_source_context(item.id),
    ):
        try:
            operation()
        except XiaohongshuCollectorUnavailable:
            pass
        else:
            raise AssertionError("direct collector service must reject the public build")
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM creator_sync_runs").fetchone()[0] == before_runs
        assert connection.execute("SELECT COUNT(*) FROM content_source_contexts").fetchone()[0] == before_context


def test_public_existing_inbox_process_rejects_without_status_or_task_write():
    initialize_database()
    url = "https://www.xiaohongshu.com/explore/inbox-existing"
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="xiaohongshu", content_type="article", source_url=url,
            canonical_source_id="inbox-existing", title="收件箱缓存", status="inbox",
        )
        connection.commit()
        before = tuple(connection.execute("SELECT status, updated_at FROM content_items WHERE id=?", (item.id,)).fetchone())
        task_count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    response = TestClient(app).post(f"/api/inbox/{item.id}/process", json={})

    assert response.status_code == 409
    with connect() as connection:
        assert tuple(connection.execute("SELECT status, updated_at FROM content_items WHERE id=?", (item.id,)).fetchone()) == before
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == task_count


def test_public_cached_xiaohongshu_article_remains_readable_without_mutation():
    initialize_database()
    url = "https://www.xiaohongshu.com/explore/cached-readable"
    with connect() as connection:
        repository = ContentRepository(connection)
        item = repository.create_content_item(
            source_provider="xiaohongshu",
            content_type="article",
            source_url=url,
            canonical_source_id="cached-readable",
            title="缓存标题",
            status="ready",
        )
        connection.commit()
    cache_dir = xiaohongshu_cache_dir(url)
    image_path = cache_dir / "article_images" / "image-1.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"retained-image")
    write_cache_meta(cache_dir, {"article_info": {
        "title": "缓存标题",
        "description": "已经缓存的正文",
        "body_text": "已经缓存的正文",
        "xhs_gallery": [{
            "index": 1,
            "source_url": "https://example.com/image-1.jpg",
            "cached_path": str(image_path),
            "ocr_status": "ready",
            "ocr_text": "缓存图片文字",
        }],
    }})
    metadata_path = cache_dir / "metadata.json"
    before = metadata_path.read_bytes()
    image_before = image_path.read_bytes()
    with connect() as connection:
        row_count_before = connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]

    source = load_content_source_text(item.id)
    response = TestClient(app).get(f"/api/content/{item.id}/article-preview")

    assert source.text == "已经缓存的正文"
    assert response.status_code == 200
    assert response.json()["title"] == "缓存标题"
    assert "已经缓存的正文" in response.json()["html"]
    assert response.json()["gallery"][0]["ocr_text"] == "缓存图片文字"
    assert metadata_path.read_bytes() == before
    assert image_path.read_bytes() == image_before
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == row_count_before


def test_task_preflight_fails_closed_when_content_lookup_is_corrupt(monkeypatch):
    initialize_database()
    with connect() as connection:
        before_tasks = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    monkeypatch.setattr("services.database.connect", lambda: (_ for _ in ()).throw(RuntimeError("corrupt lookup")))

    try:
        task_manager.create(PipelineRequest(content_item_id="unknown"))
    except RuntimeError as exc:
        assert "corrupt lookup" in str(exc)
    else:
        raise AssertionError("an unresolved provider lookup must fail closed")
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before_tasks


def test_task_preflight_preserves_unknown_content_id_behavior():
    initialize_database()

    require_xiaohongshu_request(PipelineRequest(content_item_id="missing-item"))
    require_xiaohongshu_request(PipelineRequest(source_sync_request={"kind": "creator_saved", "source_id": "missing-source"}))
    require_xiaohongshu_request(PipelineRequest(source_sync_request={"kind": "source_context_refresh", "source_id": "missing-item"}))


def test_public_recovery_preserves_queued_and_running_xiaohongshu_work():
    initialize_database()
    url = "https://www.xiaohongshu.com/explore/recovery-cache"
    with connect() as connection:
        repository = ContentRepository(connection)
        item = repository.create_content_item(
            source_provider="xiaohongshu",
            content_type="article",
            source_url=url,
            canonical_source_id="recovery-cache",
            title="恢复缓存",
            status="processing",
        )
        connection.commit()
    cache_dir = xiaohongshu_cache_dir(url)
    write_cache_meta(cache_dir, {"article_info": {"title": "恢复缓存", "body_text": "保留内容"}})
    metadata_path = cache_dir / "metadata.json"
    metadata_before = metadata_path.read_bytes()

    queued = task_manager._record_from_request(
        "xhs-queued",
        PipelineRequest(content_item_id=item.id, share_text=url, source_url=url, execution_mode="background"),
        task_type="process_video",
    )
    running = task_manager._record_from_request(
        "xhs-running",
        PipelineRequest(content_item_id=item.id, share_text=url, source_url=url, execution_mode="background"),
        task_type="process_video",
    )
    terminal = task_manager._record_from_request(
        "xhs-terminal",
        PipelineRequest(content_item_id=item.id, share_text=url, source_url=url),
        task_type="process_video",
    )
    assert task_manager._persist_create(queued)
    assert task_manager._persist_create(running)
    assert task_manager._persist_create(terminal)
    running.status = "running"
    assert task_manager._persist_state(running)
    terminal.status = "succeeded"
    assert task_manager._persist_state(terminal)
    with connect() as connection:
        task_rows_before = [
            tuple(row)
            for row in connection.execute(
                "SELECT id, status, request_json, result_json, updated_at FROM tasks WHERE id IN ('xhs-queued', 'xhs-running') ORDER BY id"
            ).fetchall()
        ]
        content_before = tuple(connection.execute(
            "SELECT status, updated_at FROM content_items WHERE id=?", (item.id,)
        ).fetchone())
        context_before = connection.execute("SELECT COUNT(*) FROM content_source_contexts").fetchone()[0]

    task_manager.recover_from_database()

    assert task_manager.get("xhs-queued") is None
    assert task_manager.get("xhs-running") is None
    assert task_manager.get("xhs-terminal").status == "succeeded"
    assert not task_manager._active_task_ids
    control_responses = [
        TestClient(app).post("/api/tasks/xhs-queued/prioritize"),
        TestClient(app).post("/api/tasks/xhs-queued/pause"),
        TestClient(app).post("/api/tasks/xhs-queued/retry"),
        TestClient(app).post("/api/tasks/xhs-queued/resume"),
    ]
    assert [response.status_code for response in control_responses] == [409, 409, 409, 409]
    assert task_manager.get("xhs-queued") is None
    task_manager._schedule_next()
    assert task_manager.get("xhs-queued") is None
    assert not task_manager._active_task_ids
    with connect() as connection:
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT id, status, request_json, result_json, updated_at FROM tasks WHERE id IN ('xhs-queued', 'xhs-running') ORDER BY id"
            ).fetchall()
        ] == task_rows_before
        assert tuple(connection.execute(
            "SELECT status, updated_at FROM content_items WHERE id=?", (item.id,)
        ).fetchone()) == content_before
        assert connection.execute("SELECT COUNT(*) FROM content_source_contexts").fetchone()[0] == context_before
    assert metadata_path.read_bytes() == metadata_before
