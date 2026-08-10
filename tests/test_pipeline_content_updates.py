from __future__ import annotations

from contextlib import nullcontext

from services import pipeline_content_updates


class RecordingConnection:
    def __init__(self):
        self.executions = []
        self.commits = 0

    def execute(self, statement, parameters):
        self.executions.append((statement, parameters))

    def commit(self):
        self.commits += 1


def test_status_update_uses_parameterized_sql_and_commits(monkeypatch):
    connection = RecordingConnection()
    initialized = []
    monkeypatch.setattr(pipeline_content_updates, "initialize_database", lambda: initialized.append(True))
    monkeypatch.setattr(pipeline_content_updates, "connect", lambda: nullcontext(connection))

    pipeline_content_updates.set_content_status("item-1", "to_read")

    statement, parameters = connection.executions[0]
    assert "status = ?" in statement and "id = ?" in statement
    assert parameters[0] == "to_read"
    assert parameters[2] == "item-1"
    assert initialized == [True]
    assert connection.commits == 1


def test_title_update_trims_values_and_skips_empty_titles(monkeypatch):
    connection = RecordingConnection()
    initialized = []
    monkeypatch.setattr(pipeline_content_updates, "initialize_database", lambda: initialized.append(True))
    monkeypatch.setattr(pipeline_content_updates, "connect", lambda: nullcontext(connection))

    pipeline_content_updates.set_content_title("item-1", "  新标题  ")
    pipeline_content_updates.set_content_title("item-2", "   ")

    assert connection.executions[0][1][0] == "新标题"
    assert connection.executions[0][1][2] == "item-1"
    assert initialized == [True]
    assert connection.commits == 1


def test_best_effort_content_update_does_not_break_the_pipeline(monkeypatch):
    monkeypatch.setattr(
        pipeline_content_updates,
        "initialize_database",
        lambda: (_ for _ in ()).throw(OSError("database unavailable")),
    )

    assert pipeline_content_updates.set_content_status("item-1", "failed") is None
    assert pipeline_content_updates.set_content_title("item-1", "标题") is None


def test_preview_preparation_preserves_log_order_and_empty_input_behavior(monkeypatch, tmp_path):
    logs = []
    add_log = lambda *entry: logs.append(entry)
    cache_dir = tmp_path / "cache"
    video_path = tmp_path / "video.mp4"
    monkeypatch.setattr(
        pipeline_content_updates,
        "ensure_preview_thumbnails",
        lambda cache, video: cache / f"{video.stem}.jpg",
    )

    pipeline_content_updates.prepare_preview_thumbnails(None, video_path, add_log)
    pipeline_content_updates.prepare_preview_thumbnails(cache_dir, video_path, add_log)

    assert logs == [
        ("download", "正在准备播放器预览缩略图…", "info", None),
        ("download", "播放器预览缩略图已生成", "success", None),
    ]
