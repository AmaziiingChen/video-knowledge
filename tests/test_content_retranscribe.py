from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app
from routers import tasks
from services.cache import cache_dir_for_url, write_cache_meta
from services.database import connect, initialize_database
from services.repository import ContentRepository
from services.task_manager import TaskRecord


def test_retranscribe_reuses_retained_video_without_downloading(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    source_url = "https://www.bilibili.com/video/BV1example"
    cache_dir = cache_dir_for_url(source_url)
    cache_dir.mkdir(parents=True)
    video_path = cache_dir / "retained.mp4"
    video_path.write_bytes(b"v" * 12_000)
    write_cache_meta(cache_dir, {"source_url": source_url, "platform": "bilibili"})

    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="bilibili",
            source_url=source_url,
            canonical_source_id="BV1example",
            title="可重新转写的视频",
            content_type="video",
            status="failed",
        )
        connection.commit()

    captured = []

    def create_task(request):
        captured.append(request)
        return TaskRecord(
            task_id="retranscribe-task",
            content_item_id=item.id,
            local_video_path=request.local_video_path,
            source_title=request.source_title,
            source_url=request.source_url,
        )

    monkeypatch.setattr(tasks.task_manager, "create", create_task)
    with TestClient(app) as client:
        response = client.post(f"/api/content/{item.id}/retranscribe")

    assert response.status_code == 200
    assert response.json()["execution_mode"] == "foreground"
    assert len(captured) == 1
    request = captured[0]
    assert request.local_video_path == str(video_path.resolve())
    assert request.use_cache is False
    assert request.content_item_id == item.id
    assert request.source_url == source_url


def test_retranscribe_reuses_retained_imported_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    audio_path = tmp_path / "data" / "attachments" / "audio" / "original--meeting.m4a"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"a" * 12_000)
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="local_file",
            source_url="local-file:audio",
            canonical_source_id="local-file:audio",
            title="会议录音",
            content_type="audio",
            status="to_read",
        )
        connection.commit()

    captured = []

    def create_task(request):
        captured.append(request)
        return TaskRecord(task_id="audio-retranscribe-task", content_item_id=item.id, local_video_path=request.local_video_path)

    monkeypatch.setattr(tasks, "original_attachment_path", lambda content_item_id: audio_path if content_item_id == item.id else None)
    monkeypatch.setattr(tasks.task_manager, "create", create_task)
    with TestClient(app) as client:
        response = client.post(f"/api/content/{item.id}/retranscribe")

    assert response.status_code == 200
    assert len(captured) == 1
    assert captured[0].local_video_path == str(audio_path)
    assert captured[0].use_cache is False


def test_redownload_expired_video_keeps_existing_text_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    source_url = "https://www.douyin.com/video/123456"
    cache_dir = cache_dir_for_url(source_url)
    cache_dir.mkdir(parents=True)
    write_cache_meta(cache_dir, {
        "source_url": source_url,
        "platform": "douyin",
        "video_cache_status": "expired",
    })
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="douyin",
            source_url=source_url,
            canonical_source_id="123456",
            title="视频预览已过期",
            content_type="video",
            status="to_read",
        )
        connection.commit()

    captured = []

    def create_task(request):
        captured.append(request)
        return TaskRecord(task_id="redownload-task", content_item_id=item.id, source_url=request.source_url)

    monkeypatch.setattr(tasks.task_manager, "create", create_task)
    with TestClient(app) as client:
        response = client.post(f"/api/content/{item.id}/redownload-video")

    assert response.status_code == 200
    assert len(captured) == 1
    request = captured[0]
    assert request.processing_mode == "download_only"
    assert request.use_cache is True
    assert request.local_video_path is None
    assert request.source_url == source_url


def test_redownload_bilibili_video_does_not_rerun_transcript_or_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    source_url = "https://www.bilibili.com/video/BV1subtitlefirst"
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="bilibili",
            source_url=source_url,
            canonical_source_id="BV1subtitlefirst",
            title="优先外挂字幕的视频",
            content_type="video",
            status="to_read",
        )
        connection.commit()

    captured = []

    def create_task(request):
        captured.append(request)
        return TaskRecord(task_id="bilibili-redownload-task", content_item_id=item.id, source_url=request.source_url)

    monkeypatch.setattr(tasks.task_manager, "create", create_task)
    with TestClient(app) as client:
        response = client.post(f"/api/content/{item.id}/redownload-video")

    assert response.status_code == 200
    assert len(captured) == 1
    request = captured[0]
    assert request.processing_mode == "download_only"
    assert request.download_video_preview is False
    assert request.subtitle_only is False
    assert request.source_url == source_url


def test_fetch_external_subtitle_never_queues_media_download(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    source_url = "https://www.bilibili.com/video/BV1subtitle"
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="bilibili",
            source_url=source_url,
            canonical_source_id="BV1subtitle",
            title="只尝试外挂字幕",
            content_type="video",
            status="to_read",
        )
        connection.commit()

    captured = []

    def create_task(request):
        captured.append(request)
        return TaskRecord(task_id="subtitle-task", content_item_id=item.id, source_url=request.source_url)

    monkeypatch.setattr(tasks.task_manager, "create", create_task)
    with TestClient(app) as client:
        response = client.post(f"/api/content/{item.id}/fetch-external-subtitle")

    assert response.status_code == 200
    assert len(captured) == 1
    request = captured[0]
    assert request.subtitle_only is True
    assert request.processing_mode == "full"
    assert request.local_video_path is None
    assert request.source_url == source_url
