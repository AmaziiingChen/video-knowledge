import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.creator_sync import CreatorVideo
from services.database import connect, initialize_database
from services import favorite_sync
from services.favorite_sync import FAVORITE_SYNC_LIMIT, FavoritePreview, _save_and_sync, process_pending_favorite_items, update_favorite_source
from routers.favorite_sources import BilibiliFavoriteRequest, DouyinFavoriteRequest


def _video(video_id: str) -> CreatorVideo:
    return CreatorVideo(
        provider="bilibili",
        canonical_id=video_id,
        source_url=f"https://www.bilibili.com/video/{video_id}",
        title=f"作品 {video_id}",
    )


def test_personal_favorite_sync_keeps_first_five_and_is_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    preview = FavoritePreview(
        "bilibili",
        "https://space.bilibili.com/42/favlist?fid=88",
        "AI 收藏夹",
        [_video(f"BV{i}") for i in range(8)],
    )

    first = _save_and_sync(preview, source_id=None, auto_analyze=False)
    second = _save_and_sync(preview, source_id=first["source"]["id"], auto_analyze=False)

    assert first["discovered_count"] == FAVORITE_SYNC_LIMIT
    assert first["created_count"] == FAVORITE_SYNC_LIMIT
    assert second["created_count"] == 0
    assert second["duplicate_count"] == FAVORITE_SYNC_LIMIT
    with connect() as connection:
        items = connection.execute("SELECT COUNT(*) FROM favorite_source_items").fetchone()[0]
        folder = connection.execute("SELECT name FROM library_folders WHERE id=?", (first["source"]["library_folder_id"],)).fetchone()
    assert items == FAVORITE_SYNC_LIMIT
    assert folder["name"] == "AI 收藏夹"


def test_personal_favorite_sources_use_distinct_folders_and_resume_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    first = _save_and_sync(FavoritePreview("bilibili", "https://space.bilibili.com/42/favlist?fid=1", "收藏夹", [_video("BV1")]), source_id=None, auto_analyze=False)
    second = _save_and_sync(FavoritePreview("bilibili", "https://space.bilibili.com/42/favlist?fid=2", "收藏夹", [_video("BV2")]), source_id=None, auto_analyze=False)

    assert first["source"]["library_folder_id"] != second["source"]["library_folder_id"]
    paused = update_favorite_source(first["source"]["id"], enabled=False)
    resumed = update_favorite_source(first["source"]["id"], enabled=True)

    assert paused["enabled"] is False
    assert resumed["enabled"] is True
    assert resumed["next_sync_at"]


def test_new_favorite_requests_default_to_full_analysis():
    assert BilibiliFavoriteRequest(source_url="https://space.bilibili.com/42/favlist?fid=88").auto_analyze is True
    assert DouyinFavoriteRequest().auto_analyze is True


def test_pending_favorite_items_can_be_explicitly_queued_without_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    source = _save_and_sync(
        FavoritePreview("bilibili", "https://space.bilibili.com/42/favlist?fid=88", "AI 收藏夹", [_video("BV1"), _video("BV2")]),
        source_id=None,
        auto_analyze=False,
    )["source"]
    requests = []
    monkeypatch.setattr(
        favorite_sync.task_manager,
        "create",
        lambda request: requests.append(request) or SimpleNamespace(task_id=f"task-{len(requests)}"),
    )

    first = process_pending_favorite_items(source["id"])
    second = process_pending_favorite_items(source["id"])

    assert first["queued_count"] == 2
    assert second["queued_count"] == 0
    assert [request.processing_mode for request in requests] == ["full", "full"]
    assert all(request.execution_mode == "background" for request in requests)
    with connect() as connection:
        statuses = [row[0] for row in connection.execute("SELECT status FROM content_items ORDER BY canonical_source_id").fetchall()]
    assert statuses == ["processing", "processing"]


def test_pending_favorite_restore_does_not_reset_items_that_were_already_queued(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    source = _save_and_sync(
        FavoritePreview("bilibili", "https://space.bilibili.com/42/favlist?fid=88", "AI 收藏夹", [_video("BV1"), _video("BV2")]),
        source_id=None,
        auto_analyze=False,
    )["source"]
    calls = 0
    queued_item_ids = []

    def create_task(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("queue unavailable")
        queued_item_ids.append(request.content_item_id)
        return SimpleNamespace(task_id="task-1")

    monkeypatch.setattr(favorite_sync.task_manager, "create", create_task)

    try:
        process_pending_favorite_items(source["id"])
    except favorite_sync.FavoriteSyncError as exc:
        assert "创建补处理任务失败" in str(exc)
    else:
        raise AssertionError("expected queue creation failure")

    with connect() as connection:
        rows = connection.execute("SELECT id, status FROM content_items").fetchall()
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[queued_item_ids[0]] == "processing"
    assert [status for item_id, status in statuses.items() if item_id != queued_item_ids[0]] == ["inbox"]
